from __future__ import annotations

import sys
from typing import TYPE_CHECKING

import typer

if TYPE_CHECKING:
    from nbadb.orchestrate import PipelineResult


def _build_settings(
    data_dir: object = None,
    formats: object = None,
) -> object:
    """Build NbaDbSettings, overriding data_dir and formats if provided."""
    from nbadb.core.config import NbaDbSettings

    kwargs: dict[str, object] = {}
    if data_dir:
        kwargs["data_dir"] = data_dir
    if formats:
        kwargs["formats"] = formats
    return NbaDbSettings(**kwargs)


def _setup_logging(verbose: bool) -> None:
    """Configure loguru level based on verbose flag."""
    from loguru import logger

    logger.remove()
    if verbose:
        logger.add(sys.stderr, level="DEBUG")
    else:
        logger.add(sys.stderr, level="WARNING")


def _print_result(mode: str, result: PipelineResult) -> None:
    """Display a human-readable summary of a pipeline run."""
    typer.echo(
        f"{mode}: {result.tables_updated} tables, "
        f"{result.rows_total:,} rows, "
        f"{result.duration_seconds:.1f}s"
    )
    if result.failed_extractions:
        typer.echo(
            f"  {result.failed_extractions} extractions failed",
            err=True,
        )
    for e in result.errors:
        typer.echo(f"  ERROR: {e}", err=True)


def _run_quality_checks(settings: object) -> None:
    """Open DuckDB and run row-count checks on all user tables.

    Warns on empty tables but never raises — quality issues are
    informational only.
    """
    import duckdb

    from nbadb.transform.quality import (
        CheckLayer,
        DataQualityMonitor,
        QualityResult,
    )

    duckdb_path = getattr(settings, "duckdb_path", None)
    if duckdb_path is None or not duckdb_path.exists():
        typer.echo("  Quality check skipped: database not found", err=True)
        return

    conn = duckdb.connect(str(duckdb_path), read_only=True)
    try:
        monitor = DataQualityMonitor(conn)
        tables = [
            row[0]
            for row in conn.execute(
                "SELECT table_name FROM information_schema.tables "
                "WHERE table_schema = 'main' "
                "AND table_name NOT LIKE '\\_%' ESCAPE '\\'"
            ).fetchall()
        ]
        for table in sorted(tables):
            try:
                row = conn.execute(
                    f"SELECT COUNT(*) FROM {table}"  # noqa: S608
                ).fetchone()
                count = row[0] if row else 0
                monitor.results.append(QualityResult(
                    table=table,
                    check_type="row_count",
                    layer=CheckLayer.STRUCTURAL,
                    passed=count > 0,
                    message=f"{table}: {count:,} rows",
                ))
            except Exception:
                pass
        monitor.log_summary()
        s = monitor.summary()
        typer.echo(f"\nQuality: {s['passed']}/{s['total']} checks passed")
        if monitor.failed():
            typer.echo(
                f"  {len(monitor.failed())} empty tables detected",
                err=True,
            )
    finally:
        conn.close()
