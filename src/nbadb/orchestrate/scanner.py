"""Database scanner for identifying missing data, gaps, and quality issues.

All queries are read-only. The DuckDB connection should be opened with
``read_only=True``.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from enum import StrEnum
from typing import ClassVar

import duckdb
from loguru import logger


class ScanCategory(StrEnum):
    CROSS_TABLE = "cross_table"
    TEMPORAL = "temporal"
    MISSING_TABLE = "missing_table"
    DATA_QUALITY = "data_quality"


class ScanSeverity(StrEnum):
    ERROR = "error"
    WARNING = "warning"
    INFO = "info"


@dataclass(frozen=True, slots=True)
class ScanFinding:
    """A single issue detected by the scanner."""

    category: str
    severity: str
    table: str
    check: str
    message: str
    details: dict | None = None


@dataclass
class ScanReport:
    """Aggregated scan results."""

    findings: list[ScanFinding] = field(default_factory=list)
    tables_scanned: int = 0
    checks_run: int = 0
    duration_seconds: float = 0.0

    def filter(
        self,
        *,
        category: str | None = None,
        severity: str | None = None,
        table: str | None = None,
    ) -> list[ScanFinding]:
        results = self.findings
        if category:
            results = [f for f in results if f.category == category]
        if severity:
            results = [f for f in results if f.severity == severity]
        if table:
            results = [f for f in results if f.table == table or f.table.startswith(table)]
        return results

    def summary(self) -> dict[str, int]:
        by_sev: dict[str, int] = {"error": 0, "warning": 0, "info": 0}
        for f in self.findings:
            by_sev[f.severity] = by_sev.get(f.severity, 0) + 1
        return {
            "total": len(self.findings),
            **by_sev,
            "tables_scanned": self.tables_scanned,
            "checks_run": self.checks_run,
        }

    def to_dict(self) -> dict:
        return {
            "summary": self.summary(),
            "duration_seconds": self.duration_seconds,
            "findings": [
                {
                    "category": f.category,
                    "severity": f.severity,
                    "table": f.table,
                    "check": f.check,
                    "message": f.message,
                    "details": f.details,
                }
                for f in self.findings
            ],
        }

    # ── CI output helpers ──────────────────────────────────────

    _SEVERITY_ICONS: ClassVar[dict[str, str]] = {
        "error": ":red_circle:",
        "warning": ":yellow_circle:",
        "info": ":blue_circle:",
    }

    _CATEGORY_LABELS: ClassVar[dict[str, str]] = {
        "missing_table": "Missing / Empty Tables",
        "cross_table": "Cross-Table Gaps",
        "temporal": "Temporal Coverage",
        "data_quality": "Data Quality",
    }

    _MAX_FINDINGS_PER_CATEGORY: ClassVar[int] = 50

    def to_markdown(self) -> str:
        """Render report as GitHub-flavored markdown for step summaries."""
        s = self.summary()
        if s["error"] == 0:
            status = ":white_check_mark: **All clear**"
        else:
            status = f":x: **{s['error']} error(s)**"

        lines = [
            "## Data Scan Report",
            "",
            status,
            "",
            "| Metric | Value |",
            "|--------|-------|",
            f"| Checks run | {s['checks_run']} |",
            f"| Tables scanned | {s['tables_scanned']} |",
            f"| Errors | {s['error']} |",
            f"| Warnings | {s['warning']} |",
            f"| Info | {s['info']} |",
            f"| Duration | {self.duration_seconds:.1f}s |",
            "",
        ]

        if not self.findings:
            lines.append("No issues found.")
            return "\n".join(lines)

        # Group by category, render per-category tables
        by_cat: dict[str, list[ScanFinding]] = {}
        for f in self.findings:
            by_cat.setdefault(f.category, []).append(f)

        cat_order = ["missing_table", "cross_table", "temporal", "data_quality"]
        for cat in cat_order:
            cat_findings = by_cat.get(cat, [])
            if not cat_findings:
                continue
            label = self._CATEGORY_LABELS.get(cat, cat)
            lines.append(f"### {label} ({len(cat_findings)})")
            lines.append("")
            lines.append("| Severity | Table | Message |")
            lines.append("|----------|-------|---------|")

            shown = cat_findings[: self._MAX_FINDINGS_PER_CATEGORY]
            for f in shown:
                icon = self._SEVERITY_ICONS.get(f.severity, "")
                # Escape pipe chars in message for markdown table safety
                msg = f.message.replace("|", "\\|")
                lines.append(f"| {icon} {f.severity} | `{f.table}` | {msg} |")

            remaining = len(cat_findings) - len(shown)
            if remaining > 0:
                lines.append(f"| | | *... and {remaining} more* |")
            lines.append("")

        return "\n".join(lines)

    def to_github_annotations(self) -> list[str]:
        """Return ``::error::`` / ``::warning::`` lines for GitHub Actions."""
        annotations: list[str] = []
        for f in self.findings:
            if f.severity == "error":
                annotations.append(f"::error::{f.message}")
            elif f.severity == "warning":
                annotations.append(f"::warning::{f.message}")
        return annotations


class DataScanner:
    """Read-only scanner that analyzes DuckDB for missing or incomplete data.

    All queries are SELECT-only.  The connection should be opened in
    read-only mode.
    """

    # Game-level fact tables that should have entries for every game.
    _GAME_COVERAGE_TABLES: ClassVar[list[str]] = [
        "fact_box_score_traditional",
        "fact_play_by_play",
        "fact_game_result",
        "fact_rotation",
    ]

    # Explicit referential-integrity pairs:
    # (fact_table, fk_column, dim_table, pk_column)
    _REF_INTEGRITY_CHECKS: ClassVar[list[tuple[str, str, str, str]]] = [
        ("fact_game_result", "game_id", "dim_game", "game_id"),
        ("fact_player_game_log", "player_id", "dim_player", "player_id"),
        ("fact_standings", "team_id", "dim_team", "team_id"),
    ]

    def __init__(self, conn: duckdb.DuckDBPyConnection) -> None:
        self._conn = conn
        self._report = ScanReport()
        self._tables_cache: list[str] | None = None
        self._columns_cache: dict[str, list[tuple[str, str]]] = {}

    # ── public API ────────────────────────────────────────────────

    def scan(
        self,
        *,
        categories: list[str] | None = None,
        table_filter: str | None = None,
    ) -> ScanReport:
        """Run all (or selected) scan categories and return the report."""
        start = time.monotonic()
        self._report = ScanReport()
        self._tables_cache = None
        self._columns_cache = {}

        active = categories if categories else [c.value for c in ScanCategory]

        if ScanCategory.MISSING_TABLE in active:
            self._check_missing_tables(table_filter)

        if ScanCategory.CROSS_TABLE in active:
            self._check_cross_table_gaps(table_filter)

        if ScanCategory.TEMPORAL in active:
            self._check_temporal_coverage(table_filter)

        if ScanCategory.DATA_QUALITY in active:
            self._check_data_quality(table_filter)

        self._report.duration_seconds = time.monotonic() - start
        return self._report

    # ── helpers ───────────────────────────────────────────────────

    def _get_existing_tables(self) -> list[str]:
        """Return all user tables (excluding ``_*`` pipeline tables)."""
        if self._tables_cache is not None:
            return self._tables_cache
        rows = self._conn.execute(
            "SELECT table_name FROM information_schema.tables "
            "WHERE table_schema = 'main' "
            "AND table_name NOT LIKE '\\_%' ESCAPE '\\'"
        ).fetchall()
        self._tables_cache = sorted(r[0] for r in rows)
        return self._tables_cache

    def _get_columns(self, table: str) -> list[str]:
        """Return column names for *table* (cached)."""
        return [name for name, _ in self._get_columns_typed(table)]

    def _get_columns_typed(self, table: str) -> list[tuple[str, str]]:
        """Return ``(column_name, data_type)`` tuples for *table* (cached)."""
        if table in self._columns_cache:
            return self._columns_cache[table]
        try:
            rows = self._conn.execute(
                "SELECT column_name, data_type FROM information_schema.columns "
                "WHERE table_name = $1 AND table_schema = 'main' "
                "ORDER BY ordinal_position",
                [table],
            ).fetchall()
            cols = [(r[0], r[1]) for r in rows]
        except duckdb.Error:
            cols = []
        self._columns_cache[table] = cols
        return cols

    def _row_count(self, table: str) -> int:
        try:
            row = self._conn.execute(f'SELECT COUNT(*) FROM "{table}"').fetchone()
            return row[0] if row else 0
        except duckdb.Error:
            return 0

    _NUMERIC_TYPES: ClassVar[frozenset[str]] = frozenset(
        {
            "INTEGER",
            "BIGINT",
            "FLOAT",
            "DOUBLE",
            "DECIMAL",
            "SMALLINT",
            "TINYINT",
            "HUGEINT",
        }
    )

    def _get_numeric_columns(self, table: str) -> list[str]:
        """Return columns with numeric types, excluding ``*_id`` columns."""
        return [
            name
            for name, dtype in self._get_columns_typed(table)
            if dtype.upper() in self._NUMERIC_TYPES and not name.endswith("_id")
        ]

    def _infer_key_columns(self, table: str) -> list[str]:
        """Infer likely primary-key columns from convention."""
        columns = self._get_columns(table)
        col_set = set(columns)
        keys: list[str] = []
        for col in ("game_id", "player_id", "team_id", "event_num"):
            if col in col_set:
                keys.append(col)
        if not keys:
            keys = [c for c in columns if c.endswith("_id")]
        return keys[:4]

    @staticmethod
    def _matches_filter(table: str, table_filter: str | None) -> bool:
        if table_filter is None:
            return True
        return table.startswith(table_filter)

    def _add(self, finding: ScanFinding) -> None:
        self._report.findings.append(finding)

    # ── category 1: missing / empty tables ────────────────────────

    def _batch_row_counts(self, tables: list[str]) -> dict[str, int]:
        """Return ``{table: row_count}`` for *tables* in a single query."""
        if not tables:
            return {}
        parts = [f"SELECT '{t}' AS tbl, COUNT(*) AS cnt FROM \"{t}\"" for t in tables]
        try:
            rows = self._conn.execute(" UNION ALL ".join(parts)).fetchall()
            return {r[0]: r[1] for r in rows}
        except duckdb.Error:
            # Fallback to per-table counts if UNION ALL fails
            return {t: self._row_count(t) for t in tables}

    def _check_missing_tables(self, table_filter: str | None) -> None:
        existing = set(self._get_existing_tables())

        # 1. Staging tables
        from nbadb.orchestrate.staging_map import get_all_staging_keys

        staging_keys = [k for k in get_all_staging_keys() if self._matches_filter(k, table_filter)]
        existing_staging = [k for k in staging_keys if k in existing]
        staging_counts = self._batch_row_counts(existing_staging)

        for key in staging_keys:
            self._report.checks_run += 1
            if key not in existing:
                self._add(
                    ScanFinding(
                        category=ScanCategory.MISSING_TABLE,
                        severity=ScanSeverity.ERROR,
                        table=key,
                        check="missing_staging_table",
                        message=f"Staging table {key} not found in database",
                    )
                )
            else:
                if staging_counts.get(key, 0) == 0:
                    self._add(
                        ScanFinding(
                            category=ScanCategory.MISSING_TABLE,
                            severity=ScanSeverity.WARNING,
                            table=key,
                            check="empty_staging_table",
                            message=f"Staging table {key} exists but is empty",
                            details={"row_count": 0},
                        )
                    )
                self._report.tables_scanned += 1

        # 2. Transform outputs
        try:
            from nbadb.orchestrate.transformers import discover_all_transformers

            transformers = discover_all_transformers()
        except Exception as exc:
            logger.warning("scanner: cannot discover transformers: {}", exc)
            transformers = []

        tf_map = {
            tf.output_table: tf
            for tf in transformers
            if self._matches_filter(tf.output_table, table_filter)
        }
        existing_tf = [t for t in tf_map if t in existing]
        tf_counts = self._batch_row_counts(existing_tf)

        for out, tf in tf_map.items():
            self._report.checks_run += 1
            if out not in existing:
                self._add(
                    ScanFinding(
                        category=ScanCategory.MISSING_TABLE,
                        severity=ScanSeverity.ERROR,
                        table=out,
                        check="missing_transform_table",
                        message=f"Transform output {out} not found in database",
                        details={"depends_on": tf.depends_on},
                    )
                )
            else:
                if tf_counts.get(out, 0) == 0:
                    self._add(
                        ScanFinding(
                            category=ScanCategory.MISSING_TABLE,
                            severity=ScanSeverity.WARNING,
                            table=out,
                            check="empty_transform_table",
                            message=f"Transform output {out} exists but is empty",
                            details={"row_count": 0, "depends_on": tf.depends_on},
                        )
                    )
                self._report.tables_scanned += 1

    # ── category 2: cross-table gaps ──────────────────────────────

    def _check_cross_table_gaps(self, table_filter: str | None) -> None:
        existing = set(self._get_existing_tables())

        # 1. Game coverage
        if "dim_game" in existing:
            for fact_table in self._GAME_COVERAGE_TABLES:
                if fact_table not in existing:
                    continue
                if not self._matches_filter(fact_table, table_filter):
                    continue
                self._report.checks_run += 1
                try:
                    row = self._conn.execute(f"""
                        SELECT
                            (SELECT COUNT(DISTINCT game_id) FROM dim_game) AS dim_count,
                            (SELECT COUNT(DISTINCT game_id) FROM "{fact_table}") AS fact_count
                    """).fetchone()
                    dim_count, fact_count = row[0], row[1]
                    missing = dim_count - fact_count
                    if missing > 0:
                        pct = missing / dim_count * 100 if dim_count > 0 else 0
                        severity = ScanSeverity.ERROR if pct > 10 else ScanSeverity.WARNING
                        self._add(
                            ScanFinding(
                                category=ScanCategory.CROSS_TABLE,
                                severity=severity,
                                table=fact_table,
                                check="game_coverage",
                                message=(
                                    f"{fact_table}: {missing:,} games in dim_game "
                                    f"missing from fact table ({pct:.1f}%)"
                                ),
                                details={
                                    "dim_game_count": dim_count,
                                    "fact_game_count": fact_count,
                                    "missing": missing,
                                    "missing_pct": round(pct, 2),
                                },
                            )
                        )
                except duckdb.Error as exc:
                    logger.debug("scanner: game coverage check failed for {}: {}", fact_table, exc)

        # 2. Explicit referential integrity
        for fact_table, fk_col, dim_table, pk_col in self._REF_INTEGRITY_CHECKS:
            if fact_table not in existing or dim_table not in existing:
                continue
            if not self._matches_filter(fact_table, table_filter):
                continue
            self._report.checks_run += 1
            try:
                row = self._conn.execute(f"""
                    SELECT COUNT(*) FROM "{fact_table}" f
                    LEFT JOIN "{dim_table}" d ON f."{fk_col}" = d."{pk_col}"
                    WHERE d."{pk_col}" IS NULL AND f."{fk_col}" IS NOT NULL
                """).fetchone()
                orphans = row[0] if row else 0
                if orphans > 0:
                    self._add(
                        ScanFinding(
                            category=ScanCategory.CROSS_TABLE,
                            severity=ScanSeverity.WARNING,
                            table=fact_table,
                            check="referential_integrity",
                            message=(
                                f"{fact_table}.{fk_col} -> {dim_table}.{pk_col}: "
                                f"{orphans:,} orphan records"
                            ),
                            details={
                                "fk": f"{fact_table}.{fk_col}",
                                "pk": f"{dim_table}.{pk_col}",
                                "orphans": orphans,
                            },
                        )
                    )
            except duckdb.Error as exc:
                logger.debug("scanner: ref integrity check failed: {}", exc)

        # 3. Dynamic ref integrity for all fact_ tables with game_id
        checked_facts = {t for t, _, _, _ in self._REF_INTEGRITY_CHECKS}
        if "dim_game" in existing:
            for table in sorted(existing):
                if not table.startswith("fact_"):
                    continue
                if table in checked_facts:
                    continue
                if not self._matches_filter(table, table_filter):
                    continue
                cols = self._get_columns(table)
                if "game_id" not in cols:
                    continue
                self._report.checks_run += 1
                try:
                    row = self._conn.execute(f"""
                        SELECT COUNT(*) FROM "{table}" f
                        LEFT JOIN dim_game d ON f.game_id = d.game_id
                        WHERE d.game_id IS NULL AND f.game_id IS NOT NULL
                    """).fetchone()
                    orphans = row[0] if row else 0
                    if orphans > 0:
                        self._add(
                            ScanFinding(
                                category=ScanCategory.CROSS_TABLE,
                                severity=ScanSeverity.WARNING,
                                table=table,
                                check="referential_integrity",
                                message=(
                                    f"{table}.game_id -> dim_game.game_id: "
                                    f"{orphans:,} orphan records"
                                ),
                                details={"fk": f"{table}.game_id", "orphans": orphans},
                            )
                        )
                except duckdb.Error:
                    pass

    # ── category 3: temporal coverage ─────────────────────────────

    def _check_temporal_coverage(
        self,
        table_filter: str | None,
        *,
        low_threshold: float = 0.3,
    ) -> None:
        existing = self._get_existing_tables()

        for table in existing:
            if not self._matches_filter(table, table_filter):
                continue
            cols = self._get_columns(table)

            # Season distribution
            if "season_year" in cols:
                self._report.checks_run += 1
                self._report.tables_scanned += 1
                try:
                    rows = self._conn.execute(f"""
                        SELECT season_year, COUNT(*) AS cnt
                        FROM "{table}"
                        WHERE season_year IS NOT NULL
                        GROUP BY season_year
                        ORDER BY season_year
                    """).fetchall()
                    if len(rows) >= 3:
                        counts = [r[1] for r in rows]
                        median = sorted(counts)[len(counts) // 2]
                        threshold = median * low_threshold
                        for season, cnt in rows:
                            if cnt < threshold and median > 0:
                                self._add(
                                    ScanFinding(
                                        category=ScanCategory.TEMPORAL,
                                        severity=ScanSeverity.WARNING,
                                        table=table,
                                        check="low_season_count",
                                        message=(
                                            f"{table}: season {season} has {cnt:,} rows "
                                            f"(median={median:,}, threshold={threshold:.0f})"
                                        ),
                                        details={
                                            "season": str(season),
                                            "row_count": cnt,
                                            "median": median,
                                            "threshold": threshold,
                                        },
                                    )
                                )
                except duckdb.Error as exc:
                    logger.debug("scanner: temporal check failed for {}: {}", table, exc)

            # Date gap detection (game-level tables only)
            if "game_date" in cols and table in (
                "dim_game",
                "stg_league_game_log",
                "fact_game_result",
            ):
                self._report.checks_run += 1
                try:
                    rows = self._conn.execute(f"""
                        WITH dates AS (
                            SELECT DISTINCT CAST(game_date AS DATE) AS d
                            FROM "{table}"
                            WHERE game_date IS NOT NULL
                        ),
                        gaps AS (
                            SELECT
                                d AS gap_start,
                                LEAD(d) OVER (ORDER BY d) AS gap_end,
                                DATEDIFF('day', d, LEAD(d) OVER (ORDER BY d)) AS gap_days
                            FROM dates
                        )
                        SELECT gap_start, gap_end, gap_days
                        FROM gaps
                        WHERE gap_days > 14
                        ORDER BY gap_days DESC
                        LIMIT 10
                    """).fetchall()
                    for gap_start, gap_end, gap_days in rows:
                        # Skip off-season gaps (June-September)
                        if (
                            gap_start is not None
                            and hasattr(gap_start, "month")
                            and 6 <= gap_start.month <= 9
                        ):
                            continue
                        self._add(
                            ScanFinding(
                                category=ScanCategory.TEMPORAL,
                                severity=ScanSeverity.INFO,
                                table=table,
                                check="date_gap",
                                message=(
                                    f"{table}: {gap_days}-day gap from {gap_start} to {gap_end}"
                                ),
                                details={
                                    "gap_start": str(gap_start),
                                    "gap_end": str(gap_end),
                                    "gap_days": gap_days,
                                },
                            )
                        )
                except duckdb.Error as exc:
                    logger.debug("scanner: date gap check failed for {}: {}", table, exc)

    # ── category 4: data quality ──────────────────────────────────

    def _check_data_quality(self, table_filter: str | None) -> None:
        existing = self._get_existing_tables()
        critical_cols = {"game_id", "player_id", "team_id"}

        for table in existing:
            if not self._matches_filter(table, table_filter):
                continue
            # Skip staging tables — raw data can be messy
            if table.startswith("stg_"):
                continue

            cols = self._get_columns(table)
            col_set = set(cols)

            # 1. Null rate on critical columns
            for critical in sorted(critical_cols & col_set):
                self._report.checks_run += 1
                try:
                    row = self._conn.execute(f"""
                        SELECT
                            COUNT(*) AS total,
                            COUNT(*) FILTER (WHERE "{critical}" IS NULL) AS nulls
                        FROM "{table}"
                    """).fetchone()
                    total, nulls = row[0], row[1]
                    if nulls > 0 and total > 0:
                        pct = nulls / total * 100
                        self._add(
                            ScanFinding(
                                category=ScanCategory.DATA_QUALITY,
                                severity=ScanSeverity.ERROR if pct > 1 else ScanSeverity.WARNING,
                                table=table,
                                check="null_key_column",
                                message=(
                                    f"{table}.{critical}: {nulls:,}/{total:,} nulls ({pct:.2f}%)"
                                ),
                                details={
                                    "column": critical,
                                    "nulls": nulls,
                                    "total": total,
                                    "null_pct": round(pct, 4),
                                },
                            )
                        )
                except duckdb.Error:
                    pass

            # 2. Duplicate key detection
            keys = self._infer_key_columns(table)
            if keys:
                self._report.checks_run += 1
                cols_str = ", ".join(f'"{k}"' for k in keys)
                try:
                    row = self._conn.execute(
                        f'SELECT COUNT(*) - COUNT(DISTINCT ({cols_str})) FROM "{table}"'
                    ).fetchone()
                    dupes = row[0] if row else 0
                    if dupes > 0:
                        self._add(
                            ScanFinding(
                                category=ScanCategory.DATA_QUALITY,
                                severity=ScanSeverity.WARNING,
                                table=table,
                                check="duplicate_keys",
                                message=f"{table}[{', '.join(keys)}]: {dupes:,} duplicate rows",
                                details={"key_columns": keys, "duplicates": dupes},
                            )
                        )
                except duckdb.Error:
                    pass

            # 3. Zero-stat detection (fact tables with ≥5 numeric columns)
            if table.startswith("fact_"):
                numeric_cols = self._get_numeric_columns(table)
                if len(numeric_cols) >= 5:
                    self._report.checks_run += 1
                    check_cols = numeric_cols[:15]
                    zero_conds = " AND ".join(f'COALESCE("{c}", 0) = 0' for c in check_cols)
                    try:
                        row = self._conn.execute(
                            f'SELECT COUNT(*) FROM "{table}" WHERE {zero_conds}'
                        ).fetchone()
                        zero_rows = row[0] if row else 0
                        total = self._row_count(table)
                        if zero_rows > 0 and total > 0:
                            pct = zero_rows / total * 100
                            if pct > 5:
                                self._add(
                                    ScanFinding(
                                        category=ScanCategory.DATA_QUALITY,
                                        severity=ScanSeverity.INFO,
                                        table=table,
                                        check="zero_stat_rows",
                                        message=(
                                            f"{table}: {zero_rows:,}/{total:,} rows "
                                            f"with all-zero stats ({pct:.1f}%)"
                                        ),
                                        details={
                                            "zero_rows": zero_rows,
                                            "total": total,
                                            "pct": round(pct, 2),
                                            "numeric_columns_checked": len(check_cols),
                                        },
                                    )
                                )
                    except duckdb.Error:
                        pass

            self._report.tables_scanned += 1
