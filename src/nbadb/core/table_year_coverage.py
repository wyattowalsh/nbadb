from __future__ import annotations

import json
from collections import Counter, defaultdict
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

from nbadb.orchestrate.staging_map import STAGING_MAP

if TYPE_CHECKING:
    from pathlib import Path

    import duckdb


_SEASON_COLUMNS = ("season_year", "season", "season_id")
_YEAR_COLUMNS = ("year",)
_DATE_COLUMNS = ("game_date", "game_date_est", "date")
_SEASON_TYPE_COLUMNS = (
    "season_type",
    "season_type_all_star",
    "season_type_playoffs",
    "season_type_nullable",
    "season_type_all_star_nullable",
)


def _now_iso() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _quote_ident(identifier: str) -> str:
    return '"' + identifier.replace('"', '""') + '"'


def _season_string_sql(expr: str) -> str:
    value = f"CAST({expr} AS VARCHAR)"
    numeric_year = (
        f"CASE WHEN regexp_matches({value}, '^[0-9]{{4}}$') THEN CAST({value} AS INTEGER) "
        "ELSE NULL END"
    )
    return (
        "CASE "
        f"WHEN {expr} IS NULL THEN NULL "
        f"WHEN regexp_matches({value}, '^[0-9]{{4}}-[0-9]{{2}}$') THEN {value} "
        f"WHEN regexp_matches({value}, '^2[0-9]{{3}}$|^1[0-9]{{3}}$') "
        f"THEN CAST(({numeric_year}) AS VARCHAR) || '-' || "
        f"LPAD(CAST(((({numeric_year}) + 1) % 100) AS VARCHAR), 2, '0') "
        f"WHEN regexp_matches({value}, '^2[0-9]{{4}}$|^1[0-9]{{4}}$') "
        f"THEN SUBSTR({value}, 2, 4) || '-' || "
        f"LPAD(CAST(((CAST(SUBSTR({value}, 2, 4) AS INTEGER) + 1) % 100) AS VARCHAR), 2, '0') "
        f"ELSE {value} "
        "END"
    )


def _date_season_sql(column_name: str) -> str:
    date_expr = f"CAST({_quote_ident(column_name)} AS DATE)"
    year_expr = f"CAST(EXTRACT('year' FROM {date_expr}) AS INTEGER)"
    start_year = (
        f"CASE WHEN CAST(EXTRACT('month' FROM {date_expr}) AS INTEGER) >= 10 "
        f"THEN {year_expr} ELSE {year_expr} - 1 END"
    )
    return (
        f"CAST(({start_year}) AS VARCHAR) || '-' || "
        f"LPAD(CAST(((({start_year}) + 1) % 100) AS VARCHAR), 2, '0')"
    )


def _staging_entries_by_key() -> dict[str, list[Any]]:
    grouped: dict[str, list[Any]] = defaultdict(list)
    for entry in STAGING_MAP:
        grouped[entry.staging_key].append(entry)
    return dict(grouped)


def _table_exists(conn: duckdb.DuckDBPyConnection, table_name: str) -> bool:
    row = conn.execute(
        """
        SELECT 1
        FROM information_schema.tables
        WHERE table_schema = 'main'
          AND table_name = $1
        LIMIT 1
        """,
        [table_name],
    ).fetchone()
    return row is not None


def _table_columns(conn: duckdb.DuckDBPyConnection, table_name: str) -> set[str]:
    rows = conn.execute(
        """
        SELECT column_name
        FROM information_schema.columns
        WHERE table_schema = 'main'
          AND table_name = $1
        ORDER BY ordinal_position
        """,
        [table_name],
    ).fetchall()
    return {str(row[0]) for row in rows}


def _row_count(conn: duckdb.DuckDBPyConnection, table_name: str) -> int:
    row = conn.execute(f"SELECT COUNT(*) FROM {_quote_ident(table_name)}").fetchone()
    return int(row[0]) if row else 0


def _season_expression(columns: set[str]) -> tuple[str | None, str | None]:
    for column in _SEASON_COLUMNS:
        if column in columns:
            return _season_string_sql(_quote_ident(column)), column
    for column in _YEAR_COLUMNS:
        if column in columns:
            return _season_string_sql(_quote_ident(column)), column
    for column in _DATE_COLUMNS:
        if column in columns:
            return _date_season_sql(column), column
    return None, None


def _season_type_expression(columns: set[str]) -> tuple[str, str | None]:
    for column in _SEASON_TYPE_COLUMNS:
        if column in columns:
            return f"CAST({_quote_ident(column)} AS VARCHAR)", column
    return "NULL", None


def build_expected_table_year_matrix(
    temporal_coverage_matrix: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Normalize endpoint temporal coverage rows into table/year expectations."""

    entries_by_key = _staging_entries_by_key()
    rows: list[dict[str, Any]] = []
    for row in temporal_coverage_matrix:
        table_name = str(row["staging_key"])
        entries = entries_by_key.get(table_name, [])
        endpoint_name = str(row["endpoint_name"])
        rows.append(
            {
                "endpoint_name": endpoint_name,
                "table_name": table_name,
                "staging_key": table_name,
                "result_set_index": row.get("result_set_index"),
                "param_pattern": row.get("param_pattern"),
                "season": row.get("season"),
                "season_type": row.get("season_type"),
                "expected_status": row.get("expected_status", "required"),
                "contract_status": row.get("actual_status", "unknown"),
                "contract_reason": row.get("reason"),
                "min_season": min(
                    (entry.min_season for entry in entries if entry.min_season is not None),
                    default=None,
                ),
                "deprecated_after": next(
                    (entry.deprecated_after for entry in entries if entry.deprecated_after),
                    None,
                ),
            }
        )
    return rows


def build_actual_table_year_matrix(
    conn: duckdb.DuckDBPyConnection,
    table_names: list[str],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Inspect DuckDB tables and return observed table/year row counts."""

    actual_rows: list[dict[str, Any]] = []
    table_summaries: list[dict[str, Any]] = []
    for table_name in sorted(set(table_names)):
        if not _table_exists(conn, table_name):
            table_summaries.append(
                {
                    "table_name": table_name,
                    "exists": False,
                    "row_count": 0,
                    "season_source_column": None,
                    "season_type_source_column": None,
                    "temporal_status": "missing_table",
                }
            )
            continue

        columns = _table_columns(conn, table_name)
        count = _row_count(conn, table_name)
        season_expr, season_source = _season_expression(columns)
        season_type_expr, season_type_source = _season_type_expression(columns)
        if season_expr is None:
            table_summaries.append(
                {
                    "table_name": table_name,
                    "exists": True,
                    "row_count": count,
                    "season_source_column": None,
                    "season_type_source_column": season_type_source,
                    "temporal_status": "no_temporal_column",
                }
            )
            continue

        rows = conn.execute(
            f"""
            WITH normalized AS (
                SELECT
                    {season_expr} AS season,
                    {season_type_expr} AS season_type
                FROM {_quote_ident(table_name)}
            )
            SELECT season, season_type, COUNT(*) AS row_count
            FROM normalized
            WHERE season IS NOT NULL
            GROUP BY season, season_type
            ORDER BY season, season_type
            """
        ).fetchall()
        for season, season_type, row_count in rows:
            actual_rows.append(
                {
                    "table_name": table_name,
                    "season": str(season),
                    "season_type": None if season_type is None else str(season_type),
                    "row_count": int(row_count),
                    "season_source_column": season_source,
                    "season_type_source_column": season_type_source,
                }
            )
        table_summaries.append(
            {
                "table_name": table_name,
                "exists": True,
                "row_count": count,
                "season_source_column": season_source,
                "season_type_source_column": season_type_source,
                "temporal_status": "temporal_rows" if rows else "no_temporal_rows",
                "temporal_row_count": len(rows),
            }
        )
    return actual_rows, table_summaries


def build_journal_status_matrix(conn: duckdb.DuckDBPyConnection) -> list[dict[str, Any]]:
    if not _table_exists(conn, "_extraction_journal"):
        return []
    rows = conn.execute(
        """
        SELECT
            endpoint,
            json_extract_string(params, '$.season') AS season,
            json_extract_string(params, '$.season_type') AS season_type,
            status,
            COUNT(*) AS count,
            COALESCE(SUM(rows_extracted), 0) AS rows_extracted,
            MAX(completed_at) AS latest_completed_at
        FROM _extraction_journal
        GROUP BY endpoint, season, season_type, status
        ORDER BY endpoint, season, season_type, status
        """
    ).fetchall()
    return [
        {
            "endpoint_name": str(endpoint),
            "season": None if season is None else str(season),
            "season_type": None if season_type is None else str(season_type),
            "status": str(status),
            "count": int(count),
            "rows_extracted": int(rows_extracted or 0),
            "latest_completed_at": (
                None if latest_completed_at is None else str(latest_completed_at)
            ),
        }
        for (
            endpoint,
            season,
            season_type,
            status,
            count,
            rows_extracted,
            latest_completed_at,
        ) in rows
    ]


def _actual_indexes(
    actual_rows: list[dict[str, Any]],
) -> tuple[dict[tuple[str, str, str | None], int], dict[tuple[str, str], int]]:
    exact: dict[tuple[str, str, str | None], int] = defaultdict(int)
    any_type: dict[tuple[str, str], int] = defaultdict(int)
    for row in actual_rows:
        table_name = str(row["table_name"])
        season = str(row["season"])
        season_type = row.get("season_type")
        typed_season = None if season_type is None else str(season_type)
        row_count = int(row.get("row_count", 0))
        exact[(table_name, season, typed_season)] += row_count
        any_type[(table_name, season)] += row_count
    return dict(exact), dict(any_type)


def _journal_indexes(
    journal_rows: list[dict[str, Any]],
) -> tuple[
    dict[tuple[str, str, str | None], Counter[str]],
    dict[tuple[str, str], Counter[str]],
    dict[tuple[str, str, str | None], int],
    dict[tuple[str, str], int],
]:
    exact: dict[tuple[str, str, str | None], Counter[str]] = defaultdict(Counter)
    any_type: dict[tuple[str, str], Counter[str]] = defaultdict(Counter)
    exact_rows: dict[tuple[str, str, str | None], int] = defaultdict(int)
    any_type_rows: dict[tuple[str, str], int] = defaultdict(int)
    for row in journal_rows:
        season = row.get("season")
        if season is None:
            continue
        endpoint = str(row["endpoint_name"])
        season_text = str(season)
        season_type = row.get("season_type")
        typed_season = None if season_type is None else str(season_type)
        status = str(row["status"])
        count = int(row.get("count", 0))
        rows_extracted = int(row.get("rows_extracted", 0))
        exact[(endpoint, season_text, typed_season)][status] += count
        any_type[(endpoint, season_text)][status] += count
        exact_rows[(endpoint, season_text, typed_season)] += rows_extracted
        any_type_rows[(endpoint, season_text)] += rows_extracted
    return exact, any_type, exact_rows, any_type_rows


def build_table_year_coverage_diff(
    expected_rows: list[dict[str, Any]],
    actual_rows: list[dict[str, Any]],
    journal_rows: list[dict[str, Any]],
    table_summaries: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    exact_actual, any_actual = _actual_indexes(actual_rows)
    exact_journal, any_journal, exact_journal_rows, any_journal_rows = _journal_indexes(
        journal_rows
    )
    table_summary_by_name = {str(row["table_name"]): row for row in table_summaries}
    diff: list[dict[str, Any]] = []

    for expected in expected_rows:
        table_name = str(expected["table_name"])
        endpoint_name = str(expected["endpoint_name"])
        season = str(expected["season"])
        season_type = expected.get("season_type")
        typed_season = None if season_type is None else str(season_type)
        table_summary = table_summary_by_name.get(table_name, {})
        any_season_row_count = any_actual.get((table_name, season), 0)
        if typed_season is None:
            row_count = any_season_row_count
            journal_counts = any_journal.get((endpoint_name, season), Counter())
            journal_rows_extracted = any_journal_rows.get((endpoint_name, season), 0)
            actual_match_scope = "season"
        else:
            row_count = exact_actual.get((table_name, season, typed_season), 0)
            journal_counts = exact_journal.get((endpoint_name, season, typed_season), Counter())
            journal_rows_extracted = exact_journal_rows.get(
                (endpoint_name, season, typed_season),
                0,
            )
            actual_match_scope = "season_type"
            if not journal_counts:
                journal_counts = any_journal.get((endpoint_name, season), Counter())
                journal_rows_extracted = any_journal_rows.get((endpoint_name, season), 0)

        contract_status = str(expected.get("contract_status", "unknown"))
        if contract_status != "staged":
            coverage_status = "contract_gap"
        elif not bool(table_summary.get("exists", False)):
            coverage_status = "missing_table"
        elif row_count > 0:
            coverage_status = "present"
        elif (
            typed_season is not None
            and table_summary.get("season_type_source_column") is None
            and any_season_row_count > 0
        ):
            coverage_status = "present_untyped"
            row_count = any_season_row_count
            actual_match_scope = "season_without_type"
        elif (
            table_summary.get("season_source_column") is None
            and int(table_summary.get("row_count", 0)) > 0
            and journal_counts.get("done", 0) > 0
            and journal_rows_extracted > 0
        ):
            coverage_status = "present_inferred"
            row_count = journal_rows_extracted
            actual_match_scope = "journal"
        elif journal_counts.get("done", 0) > 0:
            coverage_status = "empty_valid"
        elif journal_counts.get("failed", 0) > 0:
            coverage_status = "failed"
        elif journal_counts.get("running", 0) > 0:
            coverage_status = "running"
        elif journal_counts.get("abandoned", 0) > 0:
            coverage_status = "abandoned"
        else:
            coverage_status = "missing"

        diff.append(
            {
                **expected,
                "coverage_status": coverage_status,
                "actual_row_count": row_count,
                "actual_any_season_row_count": any_season_row_count,
                "actual_match_scope": actual_match_scope,
                "journal_counts": dict(sorted(journal_counts.items())),
                "journal_rows_extracted": journal_rows_extracted,
                "table_exists": bool(table_summary.get("exists", False)),
                "season_source_column": table_summary.get("season_source_column"),
                "season_type_source_column": table_summary.get("season_type_source_column"),
            }
        )
    return diff


def build_table_year_coverage(
    conn: duckdb.DuckDBPyConnection,
    temporal_coverage_matrix: list[dict[str, Any]],
) -> dict[str, Any]:
    expected_rows = build_expected_table_year_matrix(temporal_coverage_matrix)
    table_names = [str(row["table_name"]) for row in expected_rows]
    actual_rows, table_summaries = build_actual_table_year_matrix(conn, table_names)
    journal_rows = build_journal_status_matrix(conn)
    diff_rows = build_table_year_coverage_diff(
        expected_rows,
        actual_rows,
        journal_rows,
        table_summaries,
    )
    status_counts = Counter(str(row["coverage_status"]) for row in diff_rows)
    summary = {
        "generated_at": _now_iso(),
        "expected_row_count": len(expected_rows),
        "actual_row_count": len(actual_rows),
        "diff_row_count": len(diff_rows),
        "expected_table_count": len(set(table_names)),
        "actual_temporal_table_count": len({str(row["table_name"]) for row in actual_rows}),
        "journal_row_count": len(journal_rows),
        "coverage_status_breakdown": dict(sorted(status_counts.items())),
        "blocking_missing_count": sum(
            status_counts[status]
            for status in ("missing_table", "missing", "failed", "running", "abandoned")
        ),
        "contract_gap_count": status_counts["contract_gap"],
    }
    return {
        "summary": summary,
        "expected": expected_rows,
        "actual": actual_rows,
        "diff": diff_rows,
        "journal": journal_rows,
        "tables": table_summaries,
    }


def write_table_year_coverage_artifacts(
    coverage: dict[str, Any],
    output_dir: Path,
) -> dict[str, Path]:
    output_dir.mkdir(parents=True, exist_ok=True)
    paths = {
        "summary": output_dir / "table-year-coverage-summary.json",
        "expected": output_dir / "expected-table-year-matrix.json",
        "actual": output_dir / "actual-table-year-matrix.json",
        "diff": output_dir / "table-year-coverage-diff.json",
        "journal": output_dir / "journal-status-matrix.json",
        "tables": output_dir / "table-temporal-summary.json",
    }
    payload_by_key = {
        "summary": coverage["summary"],
        "expected": {"matrix": coverage["expected"]},
        "actual": {"matrix": coverage["actual"]},
        "diff": {"matrix": coverage["diff"]},
        "journal": {"matrix": coverage["journal"]},
        "tables": {"tables": coverage["tables"]},
    }
    for key, path in paths.items():
        path.write_text(json.dumps(payload_by_key[key], indent=2, sort_keys=True) + "\n")
    return paths
