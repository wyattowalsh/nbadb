from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import duckdb
import typer

from nbadb.cli.app import app
from nbadb.cli.commands._helpers import _build_settings, _open_db_readonly
from nbadb.cli.options import DataDirOption  # noqa: TC001

OUTPUT_PATH_OPTION = typer.Option(
    None,
    "--output-path",
    help="Write JSON output directly to a file",
)
DuckDbConnection = duckdb.DuckDBPyConnection


@app.command()
def status(
    data_dir: DataDirOption = None,
    output_format: str = typer.Option(
        "text",
        "--output-format",
        "-f",
        help="Output format: text or json",
    ),
) -> None:
    """Show pipeline status, watermarks, and failed extractions."""
    settings = _build_settings(data_dir)
    db_path = settings.duckdb_path

    if db_path is None or not db_path.exists():
        typer.echo("Database not found. Run 'nbadb init' first.")
        raise typer.Exit(1)

    conn = _open_db_readonly(db_path)

    try:
        if output_format == "json":
            data = {
                "watermarks": _get_watermarks(conn) or [],
                "journal": _get_journal_summary(conn) or {},
                "metadata": _get_table_metadata(conn) or [],
            }
            typer.echo(json.dumps(data, indent=2, default=str))
        else:
            _show_watermarks(conn)
            _show_journal_summary(conn)
            _show_table_metadata(conn)
    finally:
        conn.close()


@app.command("journal-summary")
def journal_summary(
    data_dir: DataDirOption = None,
    output_format: str = typer.Option(
        "text",
        "--output-format",
        "-f",
        help="Output format: text or json",
    ),
    json_output: bool = typer.Option(
        False,
        "--json",
        help="Shortcut for --output-format json",
    ),
    output_path: str | None = OUTPUT_PATH_OPTION,
    window_days: int = typer.Option(
        14,
        "--window-days",
        min=1,
        max=90,
        help="Number of days of metric rollups to include",
    ),
    limit: int = typer.Option(
        8,
        "--limit",
        min=1,
        max=25,
        help="Top-N limit for endpoint and failure breakdowns",
    ),
) -> None:
    """Export pipeline telemetry for the docs admin panel."""
    settings = _build_settings(data_dir)
    db_path = settings.duckdb_path

    if db_path is None or not db_path.exists():
        typer.echo("Database not found. Run 'nbadb init' first.")
        raise typer.Exit(1)

    conn = _open_db_readonly(db_path)
    try:
        summary = _build_pipeline_telemetry_summary(
            conn,
            window_days=window_days,
            limit=limit,
        )
    finally:
        conn.close()

    fmt = "json" if json_output else output_format.lower()
    if output_path is not None:
        fmt = "json"

    if fmt not in {"json", "text"}:
        typer.echo("Output format must be 'text' or 'json'.", err=True)
        raise typer.Exit(1)

    if output_path is not None:
        output_file = Path(output_path)
        output_file.parent.mkdir(parents=True, exist_ok=True)
        output_file.write_text(
            json.dumps(summary, indent=2, default=str) + "\n",
            encoding="utf-8",
        )
        typer.echo(f"Wrote telemetry snapshot to {output_file}")
        return

    if fmt == "json":
        typer.echo(json.dumps(summary, indent=2, default=str))
    else:
        _show_pipeline_telemetry_summary(summary)


def _get_watermarks(conn: DuckDbConnection) -> list[dict[str, Any]] | None:
    """Return watermark rows, or None if the table doesn't exist."""
    try:
        rows = conn.execute(
            "SELECT table_name, watermark_type, watermark_value, "
            "last_updated, row_count_at_watermark "
            "FROM _pipeline_watermarks ORDER BY last_updated DESC"
        ).fetchall()
        return [
            {
                "table": r[0],
                "type": r[1],
                "value": r[2],
                "updated": str(r[3]),
                "rows": r[4],
            }
            for r in rows
        ]
    except duckdb.Error:
        return None


def _get_journal_summary(conn: DuckDbConnection) -> dict[str, int] | None:
    """Return journal status counts, or None if the table doesn't exist."""
    try:
        rows = conn.execute(
            "SELECT status, COUNT(*) AS cnt "
            "FROM _extraction_journal GROUP BY status ORDER BY status"
        ).fetchall()
        return {r[0]: r[1] for r in rows}
    except duckdb.Error:
        return None


def _get_total_tables(conn: DuckDbConnection) -> int:
    """Return total tables tracked in pipeline metadata."""
    try:
        row = conn.execute(
            "SELECT COUNT(*) FROM _pipeline_metadata"
        ).fetchone()
        return int(row[0]) if row else 0
    except duckdb.Error:
        return 0


def _get_staging_coverage(conn: DuckDbConnection) -> int:
    """Return percentage of staging metadata entries with a last_updated value."""
    try:
        row = conn.execute(
            """
            SELECT
                COUNT(*) FILTER (WHERE table_name LIKE 'stg\\_%' ESCAPE '\\') AS total_staging,
                COUNT(*) FILTER (
                    WHERE table_name LIKE 'stg\\_%' ESCAPE '\\'
                      AND last_updated IS NOT NULL
                ) AS updated_staging
            FROM _pipeline_metadata
            """
        ).fetchone()
        if not row or not row[0]:
            return 0
        return int(round((row[1] / row[0]) * 100))
    except duckdb.Error:
        return 0


def _get_last_run(conn: DuckDbConnection) -> str | None:
    """Return the most recent metric or journal timestamp."""
    try:
        row = conn.execute(
            """
            SELECT MAX(ts) AS last_run
            FROM (
                SELECT run_timestamp AS ts FROM _pipeline_metrics
                UNION ALL
                SELECT COALESCE(completed_at, started_at) AS ts
                FROM _extraction_journal
            ) timestamps
            """
        ).fetchone()
        if row and row[0] is not None:
            return str(row[0])
        return None
    except duckdb.Error:
        return None


def _get_daily_rollups(
    conn: DuckDbConnection,
    *,
    window_days: int,
    limit: int,
) -> list[dict[str, Any]]:
    """Return recent daily metric buckets for observability charts."""
    try:
        rows = conn.execute(
            """
            WITH daily AS (
                SELECT
                    CAST(run_timestamp AS DATE) AS bucket_date,
                    COUNT(*) AS run_count,
                    COUNT(DISTINCT endpoint) AS tables_processed,
                    COALESCE(SUM(rows_extracted), 0) AS rows_extracted,
                    COALESCE(SUM(error_count), 0) AS error_count,
                    COALESCE(SUM(duration_seconds), 0) AS total_duration_seconds,
                    COALESCE(AVG(duration_seconds), 0) AS avg_duration_seconds,
                    COALESCE(quantile_cont(duration_seconds, 0.95), 0) AS p95_duration_seconds
                FROM _pipeline_metrics
                WHERE run_timestamp >= CURRENT_TIMESTAMP
                  - INTERVAL (CAST($1 AS VARCHAR) || ' days')
                GROUP BY 1
                ORDER BY bucket_date DESC
                LIMIT $2
            )
            SELECT *
            FROM daily
            ORDER BY bucket_date ASC
            """,
            [window_days, limit],
        ).fetchall()
    except duckdb.Error:
        return []

    return [
        {
            "date": str(row[0]),
            "label": str(row[0]),
            "runCount": int(row[1]),
            "tablesProcessed": int(row[2]),
            "rowsExtracted": int(row[3] or 0),
            "errorCount": int(row[4] or 0),
            "durationMs": int(round(float(row[5] or 0) * 1000)),
            "avgDurationMs": int(round(float(row[6] or 0) * 1000)),
            "p95DurationMs": int(round(float(row[7] or 0) * 1000)),
        }
        for row in rows
    ]


def _get_slow_endpoints(conn: DuckDbConnection, *, limit: int) -> list[dict[str, Any]]:
    """Return slowest endpoints ranked by p95 duration."""
    try:
        rows = conn.execute(
            """
            SELECT
                endpoint,
                COUNT(*) AS run_count,
                COALESCE(SUM(rows_extracted), 0) AS rows_extracted,
                COALESCE(SUM(error_count), 0) AS error_count,
                COALESCE(AVG(duration_seconds), 0) AS avg_duration_seconds,
                COALESCE(quantile_cont(duration_seconds, 0.95), 0) AS p95_duration_seconds,
                COALESCE(MAX(duration_seconds), 0) AS max_duration_seconds,
                MAX(run_timestamp) AS last_run
            FROM _pipeline_metrics
            GROUP BY endpoint
            ORDER BY p95_duration_seconds DESC, avg_duration_seconds DESC, endpoint ASC
            LIMIT $1
            """,
            [limit],
        ).fetchall()
    except duckdb.Error:
        return []

    slow_endpoints = []
    for row in rows:
        run_count = int(row[1] or 0)
        error_count = int(row[3] or 0)
        slow_endpoints.append(
            {
                "endpoint": row[0],
                "runCount": run_count,
                "rowsExtracted": int(row[2] or 0),
                "errorCount": error_count,
                "errorRate": round((error_count / run_count) * 100, 2) if run_count else 0,
                "avgDurationMs": int(round(float(row[4] or 0) * 1000)),
                "p95DurationMs": int(round(float(row[5] or 0) * 1000)),
                "maxDurationMs": int(round(float(row[6] or 0) * 1000)),
                "lastRun": str(row[7]) if row[7] is not None else None,
            }
        )
    return slow_endpoints


def _get_failure_hotspots(
    conn: DuckDbConnection,
    *,
    limit: int,
) -> list[dict[str, Any]]:
    """Return current failed or abandoned endpoints grouped for operator triage."""
    try:
        rows = conn.execute(
            """
            SELECT
                endpoint,
                status,
                COUNT(*) AS failure_count,
                MAX(COALESCE(completed_at, started_at)) AS last_seen,
                MIN(error_message) FILTER (WHERE error_message IS NOT NULL) AS sample_error
            FROM _extraction_journal
            WHERE status IN ('failed', 'abandoned')
            GROUP BY endpoint, status
            ORDER BY failure_count DESC, last_seen DESC, endpoint ASC
            LIMIT $1
            """,
            [limit],
        ).fetchall()
    except duckdb.Error:
        return []

    return [
        {
            "endpoint": row[0],
            "status": row[1],
            "count": int(row[2] or 0),
            "lastSeen": str(row[3]) if row[3] is not None else None,
            "sampleError": row[4],
        }
        for row in rows
    ]


def _get_recent_errors(conn: DuckDbConnection, *, limit: int) -> list[str]:
    """Return recent failed or abandoned journal entries as operator-friendly lines."""
    try:
        rows = conn.execute(
            """
            SELECT
                endpoint,
                params,
                status,
                retry_count,
                COALESCE(error_message, '') AS error_message,
                COALESCE(completed_at, started_at) AS seen_at
            FROM _extraction_journal
            WHERE status IN ('failed', 'abandoned')
            ORDER BY seen_at DESC, endpoint ASC
            LIMIT $1
            """,
            [limit],
        ).fetchall()
    except duckdb.Error:
        return []

    errors = []
    for endpoint, params, status, retry_count, error_message, seen_at in rows:
        errors.append(
            " | ".join(
                [
                    f"{seen_at}",
                    f"{status.upper()}",
                    endpoint,
                    f"retries={retry_count}",
                    error_message or "no error message",
                    params,
                ]
            )
        )
    return errors


def _build_pipeline_runs(daily: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Project daily metric buckets into the legacy PipelineRun shape."""
    runs = []
    for bucket in daily:
        status = "failed" if bucket["errorCount"] > 0 else "done"
        errors = []
        if bucket["errorCount"] > 0:
            errors.append(f"{bucket['errorCount']} endpoint failures")
        runs.append(
            {
                "timestamp": bucket["date"],
                "status": status,
                "tablesProcessed": bucket["tablesProcessed"],
                "rowsExtracted": bucket["rowsExtracted"],
                "durationMs": bucket["durationMs"],
                "errors": errors,
            }
        )
    return runs


def _build_pipeline_totals(
    daily: list[dict[str, Any]],
    slow_endpoints: list[dict[str, Any]],
) -> dict[str, Any]:
    """Summarize the active telemetry window for KPI display."""
    total_runs = sum(bucket["runCount"] for bucket in daily)
    total_rows = sum(bucket["rowsExtracted"] for bucket in daily)
    total_errors = sum(bucket["errorCount"] for bucket in daily)
    total_duration = sum(bucket["durationMs"] for bucket in daily)
    avg_duration = int(round(total_duration / total_runs)) if total_runs else 0
    p95_duration = slow_endpoints[0]["p95DurationMs"] if slow_endpoints else 0
    return {
        "runs": total_runs,
        "rowsExtracted": total_rows,
        "errorCount": total_errors,
        "avgDurationMs": avg_duration,
        "p95DurationMs": p95_duration,
    }


def _build_pipeline_telemetry_summary(
    conn: DuckDbConnection,
    *,
    window_days: int,
    limit: int,
) -> dict[str, Any]:
    """Build a JSON-friendly pipeline observability snapshot."""
    counts = _get_journal_summary(conn) or {}
    normalized_counts = {
        "done": int(counts.get("done", 0)),
        "failed": int(counts.get("failed", 0)),
        "running": int(counts.get("running", 0)),
        "abandoned": int(counts.get("abandoned", 0)),
    }
    daily = _get_daily_rollups(conn, window_days=window_days, limit=window_days)
    slow_endpoints = _get_slow_endpoints(conn, limit=limit)
    failure_hotspots = _get_failure_hotspots(conn, limit=limit)
    recent_errors = _get_recent_errors(conn, limit=max(limit * 2, 10))
    return {
        "generatedAt": datetime.now(UTC).isoformat(),
        "lastRun": _get_last_run(conn),
        "totalTables": _get_total_tables(conn),
        "stagingCoverage": _get_staging_coverage(conn),
        "runs": _build_pipeline_runs(daily),
        "recentErrors": recent_errors,
        "counts": normalized_counts,
        "windowDays": window_days,
        "daily": daily,
        "slowEndpoints": slow_endpoints,
        "failureHotspots": failure_hotspots,
        "totals": _build_pipeline_totals(daily, slow_endpoints),
    }


def _show_pipeline_telemetry_summary(summary: dict[str, Any]) -> None:
    """Display a human-readable telemetry summary."""
    typer.echo("\n--- Pipeline Telemetry ---")
    typer.echo(f"  Generated: {summary['generatedAt']}")
    typer.echo(f"  Last run:  {summary['lastRun'] or '(none)'}")
    typer.echo(f"  Tables:    {summary['totalTables']}")
    typer.echo(f"  Staging:   {summary['stagingCoverage']}% with metadata")
    typer.echo(
        "  Statuses:  "
        + ", ".join(f"{name}={count}" for name, count in summary["counts"].items())
    )

    totals = summary["totals"]
    typer.echo(
        "  Window:    "
        f"{summary['windowDays']}d, {totals['runs']} metric rows, "
        f"{totals['rowsExtracted']:,} rows, p95 {totals['p95DurationMs']}ms"
    )

    typer.echo("\n--- Slow Endpoints ---")
    if summary["slowEndpoints"]:
        for item in summary["slowEndpoints"]:
            typer.echo(
                "  "
                f"{item['endpoint']}: p95={item['p95DurationMs']}ms, "
                f"avg={item['avgDurationMs']}ms, runs={item['runCount']}, "
                f"errors={item['errorCount']}"
            )
    else:
        typer.echo("  (no metric data)")

    typer.echo("\n--- Failure Hotspots ---")
    if summary["failureHotspots"]:
        for item in summary["failureHotspots"]:
            typer.echo(
                "  "
                f"{item['endpoint']} [{item['status']}]: {item['count']} current failures"
            )
    else:
        typer.echo("  (no failed or abandoned entries)")


def _get_table_metadata(conn: DuckDbConnection) -> list[dict[str, Any]] | None:
    """Return table metadata rows, or None if the table doesn't exist."""
    try:
        rows = conn.execute(
            "SELECT table_name, row_count, last_updated FROM _pipeline_metadata ORDER BY table_name"
        ).fetchall()
        return [{"table": r[0], "rows": r[1], "updated": str(r[2])} for r in rows]
    except duckdb.Error:
        return None


def _show_watermarks(conn: DuckDbConnection) -> None:
    """Display pipeline watermarks."""
    rows = _get_watermarks(conn)
    typer.echo("\n--- Pipeline Watermarks ---")
    if rows is None:
        typer.echo("  (no watermark data)")
        return
    if not rows:
        typer.echo("  (empty)")
        return
    for r in rows:
        typer.echo(
            f"  {r['table']} [{r['type']}]: {r['value']}  "
            f"(updated {r['updated']}, {r['rows'] or '?'} rows)"
        )


def _show_journal_summary(conn: DuckDbConnection) -> None:
    """Display extraction journal status counts."""
    counts = _get_journal_summary(conn)
    typer.echo("\n--- Extraction Journal ---")
    if counts is None:
        typer.echo("  (no extraction journal)")
        return
    if not counts:
        typer.echo("  (empty)")
        return
    for s, cnt in counts.items():
        typer.echo(f"  {s}: {cnt}")


def _show_table_metadata(conn: DuckDbConnection) -> None:
    """Display pipeline metadata (table sizes)."""
    rows = _get_table_metadata(conn)
    typer.echo("\n--- Table Metadata ---")
    if rows is None:
        typer.echo("  (no table metadata)")
        return
    if not rows:
        typer.echo("  (empty)")
        return
    for r in rows:
        typer.echo(f"  {r['table']}: {r['rows']:,} rows  (updated {r['updated']})")
