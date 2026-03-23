from __future__ import annotations

import asyncio
import signal
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


def _setup_logging(verbose: bool, *, tui: bool = False) -> None:
    """Configure loguru level based on verbose flag.

    When ``tui=True`` (Rich Live dashboard active), logs go to a file
    instead of stderr to prevent corrupting the terminal display.
    """
    from loguru import logger

    logger.remove()
    if tui:
        logger.add("extraction.log", level="DEBUG", rotation="10 MB")
    elif verbose:
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
    """Run DataScanner checks on the database after a pipeline run.

    Runs ``missing_table`` and ``data_quality`` categories.  Warns on
    findings but never raises — quality issues are informational only.
    """
    import duckdb

    duckdb_path = settings.duckdb_path
    if not duckdb_path.exists():
        typer.echo("  Quality check skipped: database not found", err=True)
        return

    from nbadb.orchestrate.scanner import DataScanner

    conn = duckdb.connect(str(duckdb_path), read_only=True)
    try:
        scanner = DataScanner(conn)
        report = scanner.scan(categories=["missing_table", "data_quality"])
        s = report.summary()
        typer.echo(
            f"\nScan: {s['checks_run']} checks, "
            f"{s['tables_scanned']} tables ({report.duration_seconds:.1f}s)"
        )
        typer.echo(f"  {s['error']} errors, {s['warning']} warnings, {s['info']} info")
        for f in report.filter(severity="error"):
            typer.echo(f"  ERROR: {f.message}", err=True)
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

    # Use interactive Textual TUI when stdout is a terminal and not verbose
    use_tui = sys.stdout.isatty() and not verbose

    if use_tui:
        from nbadb.cli.tui import run_with_tui

        result, error = run_with_tui(mode, run_fn, settings, orchestrator_cls)
        if error is not None:
            typer.echo(f"{mode} failed: {type(error).__name__}", err=True)
            raise typer.Exit(1)
        if result is None:
            typer.echo(f"{mode}: stopped — progress saved in journal (resume-safe)", err=True)
            raise typer.Exit(0)
    else:
        from nbadb.cli.progress import NoopProgress

        _setup_logging(verbose)

        # Graceful shutdown: SIGINT/SIGTERM cancel the asyncio loop
        shutdown_requested = False

        def _handle_signal(signum: int, _frame: object) -> None:
            nonlocal shutdown_requested
            if shutdown_requested:
                typer.echo(f"\n{mode}: forced shutdown", err=True)
                raise SystemExit(1)
            shutdown_requested = True
            typer.echo(
                f"\n{mode}: shutting down gracefully (press Ctrl+C again to force)...", err=True
            )
            try:
                loop = asyncio.get_running_loop()
                for task in asyncio.all_tasks(loop):
                    task.cancel()
            except RuntimeError:
                pass

        prev_sigint = signal.signal(signal.SIGINT, _handle_signal)
        prev_sigterm = signal.signal(signal.SIGTERM, _handle_signal)

        progress = NoopProgress()
        try:
            with progress:
                orch = orchestrator_cls(settings=settings, progress=progress)
                try:
                    result = asyncio.run(run_fn(orch))  # type: ignore[arg-type]
                except (asyncio.CancelledError, KeyboardInterrupt):
                    typer.echo(
                        f"\n{mode}: stopped — progress saved in journal (resume-safe)", err=True
                    )
                    raise typer.Exit(0) from None
                except Exception as exc:
                    typer.echo(f"{mode} failed: {type(exc).__name__}", err=True)
                    raise typer.Exit(1) from exc
        finally:
            signal.signal(signal.SIGINT, prev_sigint)
            signal.signal(signal.SIGTERM, prev_sigterm)

    _print_result(mode, result)  # type: ignore[arg-type]
    if result.failed_extractions and result.tables_updated == 0 and result.rows_total == 0:  # type: ignore[union-attr]
        raise typer.Exit(1)  # Complete failure — nothing extracted
    # Partial failure — data was extracted, continue with warnings already printed
    if quality_check:
        _run_quality_checks(settings)
