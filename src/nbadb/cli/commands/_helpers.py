from __future__ import annotations

import asyncio
import sys
from typing import TYPE_CHECKING

import typer

if TYPE_CHECKING:
    from collections.abc import Callable
    from pathlib import Path

    import duckdb as _duckdb_type

    from nbadb.core.config import NbaDbSettings
    from nbadb.orchestrate import PipelineResult


def _build_settings(
    data_dir: str | Path | None = None,
    formats: list[str] | None = None,
) -> NbaDbSettings:
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
    if result.failed_loads:
        typer.echo(
            f"  {result.failed_loads} loads failed",
            err=True,
        )
    for e in result.errors:
        typer.echo(f"  ERROR: {e}", err=True)


def _run_quality_checks(settings: NbaDbSettings) -> None:
    """Open DuckDB and run row-count checks on all user tables.

    Warns on empty tables but never raises — quality issues are
    informational only.
    """
    import duckdb
    from loguru import logger

    from nbadb.transform.quality import (
        CheckLayer,
        DataQualityMonitor,
        QualityResult,
    )

    duckdb_path = settings.duckdb_path
    if not duckdb_path.exists():
        typer.echo("  Quality check skipped: database not found", err=True)
        return

    conn = duckdb.connect(str(duckdb_path), read_only=True)
    try:
        monitor = DataQualityMonitor(conn)
        from nbadb.core.db import get_user_tables

        tables = get_user_tables(conn)
        skipped = 0
        if tables:
            union_sql = " UNION ALL ".join(
                f"SELECT '{t}' AS tbl, COUNT(*) AS cnt FROM {t}"  # noqa: S608
                for t in tables
            )
            try:
                for tbl, cnt in conn.execute(union_sql).fetchall():
                    monitor.results.append(
                        QualityResult(
                            table=tbl,
                            check_type="row_count",
                            layer=CheckLayer.STRUCTURAL,
                            passed=cnt > 0,
                            message=f"{tbl}: {cnt:,} rows",
                        )
                    )
            except Exception:
                # Fall back to per-table queries on batch failure
                for table in tables:
                    try:
                        row = conn.execute(
                            f"SELECT COUNT(*) FROM {table}"  # noqa: S608
                        ).fetchone()
                        count = row[0] if row else 0
                        monitor.results.append(
                            QualityResult(
                                table=table,
                                check_type="row_count",
                                layer=CheckLayer.STRUCTURAL,
                                passed=count > 0,
                                message=f"{table}: {count:,} rows",
                            )
                        )
                    except Exception as exc:
                        logger.debug("quality check skipped for {}: {}", table, type(exc).__name__)
                        skipped += 1
        if skipped:
            typer.echo(f"  {skipped} tables skipped (query errors)", err=True)
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


def _open_db_readonly(db_path: Path) -> _duckdb_type.DuckDBPyConnection:
    """Open DuckDB in read-only mode, exiting with error message on failure."""
    import duckdb as _duckdb

    try:
        return _duckdb.connect(str(db_path), read_only=True)
    except Exception as exc:
        typer.echo(f"Cannot open database: {type(exc).__name__}", err=True)
        raise typer.Exit(1) from exc


def _run_pipeline(
    mode: str,
    run_fn: Callable[[object], object],
    settings: NbaDbSettings,
    verbose: bool,
    quality_check: bool = False,
    orchestrator_cls: type | None = None,
) -> None:
    """Run a pipeline mode end-to-end: log → orchestrate → print → (optionally) quality.

    ``run_fn`` receives the ``Orchestrator`` instance and must return a coroutine
    that resolves to a ``PipelineResult``.  Example::

        _run_pipeline("daily", lambda orch: orch.run_daily(), settings, verbose,
                      orchestrator_cls=Orchestrator)

    ``orchestrator_cls`` should be the ``Orchestrator`` class imported in the
    calling module so that test patches on the caller's namespace are respected.
    When omitted the class is imported lazily.
    """
    if orchestrator_cls is None:
        from nbadb.orchestrate import Orchestrator

        orchestrator_cls = Orchestrator

    _setup_logging(verbose)
    orch = orchestrator_cls(settings=settings)
    try:
        result = asyncio.run(run_fn(orch))  # type: ignore[arg-type]
    except Exception as exc:
        typer.echo(f"{mode} failed: {type(exc).__name__}", err=True)
        raise typer.Exit(1) from exc
    _print_result(mode, result)  # type: ignore[arg-type]
    if quality_check:
        _run_quality_checks(settings)
