from __future__ import annotations

import asyncio
import json
import os
import signal
import sys
from pathlib import Path
from typing import TYPE_CHECKING, Any, cast

import typer
from loguru import logger

from nbadb.cli._progress_common import fmt_rows, fmt_time

if TYPE_CHECKING:
    from collections.abc import Callable, Coroutine, Mapping

    import duckdb as _duckdb_type

    from nbadb.cli._progress_common import RunSummary
    from nbadb.core.config import NbaDbSettings
    from nbadb.orchestrate import PipelineResult


def _build_settings(
    data_dir: str | Path | None = None,
    formats: list[str] | None = None,
) -> NbaDbSettings:
    """Build NbaDbSettings, overriding data_dir and formats if provided."""
    from nbadb.core.config import NbaDbSettings

    resolved_data_dir = Path(data_dir) if isinstance(data_dir, str) else data_dir
    if resolved_data_dir is None:
        if formats is None:
            return NbaDbSettings()
        return NbaDbSettings(formats=formats)
    if formats is None:
        return NbaDbSettings(data_dir=resolved_data_dir)
    return NbaDbSettings(data_dir=resolved_data_dir, formats=formats)


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


def _coerce_int(value: object) -> int:
    """Convert loose summary values to integers for display."""
    if isinstance(value, bool):
        return int(value)
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        return int(value)
    if isinstance(value, str):
        try:
            return int(value)
        except ValueError:
            return 0
    return 0


def _coerce_float(value: object) -> float:
    """Convert loose summary values to floats for display."""
    if isinstance(value, bool):
        return float(value)
    if isinstance(value, int | float):
        return float(value)
    if isinstance(value, str):
        try:
            return float(value)
        except ValueError:
            return 0.0
    return 0.0


def _summary_metric(values: Mapping[str, object], *keys: str) -> int:
    """Read the first present numeric metric from a summary mapping."""
    for key in keys:
        if key in values:
            return _coerce_int(values[key])
    return 0


def _summary_label(values: Mapping[str, object]) -> str:
    """Read a human-friendly label from a summary mapping."""
    label = values.get("label", "")
    return label if isinstance(label, str) else str(label)


def _pattern_duration(values: Mapping[str, object]) -> float:
    """Read a pattern duration in seconds from a summary mapping."""
    return _coerce_float(values.get("duration", 0.0))


def _format_pipeline_exception(exc: BaseException) -> str:
    """Render an exception with its message when one is available."""
    message = str(exc).strip()
    if not message:
        return type(exc).__name__
    typed_prefix = f"{type(exc).__name__}:"
    if message.startswith(typed_prefix):
        return message
    return f"{typed_prefix} {message}"


def _print_result(
    mode: str,
    result: PipelineResult,
    summary: RunSummary | None = None,
    settings: NbaDbSettings | None = None,
) -> None:
    """Display a human-readable summary of a pipeline run."""
    duration = fmt_time(result.duration_seconds)
    typer.echo(
        f"\n🏀 {mode} complete in {duration}\n"
        f"  {result.tables_updated} tables | {result.rows_total:,} rows"
    )

    # Extraction stats from summary
    if summary and summary.totals:
        ok = _summary_metric(summary.totals, "ok", "succeeded")
        fail = _summary_metric(summary.totals, "fail", "failed")
        skip = _summary_metric(summary.totals, "skip", "skipped")
        total = ok + fail + skip
        if total > 0:
            fg_pct = ok / total * 100
            typer.echo(
                f"  {total:,} extractions: {ok:,} ok, {fail:,} failed, "
                f"{skip:,} skipped (FG% {fg_pct:.1f})"
            )

        # Top 3 slowest patterns
        if summary.patterns:
            sorted_patterns = sorted(
                summary.patterns,
                key=_pattern_duration,
                reverse=True,
            )
            top3 = [pattern for pattern in sorted_patterns if _pattern_duration(pattern) > 0][:3]
            if top3:
                parts = [
                    f"{_summary_label(pattern)} ({fmt_time(_pattern_duration(pattern))})"
                    for pattern in top3
                ]
                typer.echo(f"  Top 3 slowest: {', '.join(parts)}")

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
    for e in result.errors[:10]:
        typer.echo(f"  ERROR: {e}", err=True)
    if len(result.errors) > 10:
        typer.echo(f"  ... and {len(result.errors) - 10} more errors", err=True)

    # Write JSON summary
    if summary and settings:
        try:
            summary_path = settings.data_dir / "run_summary.json"
            summary_path.parent.mkdir(parents=True, exist_ok=True)
            import dataclasses

            summary_path.write_text(
                json.dumps(dataclasses.asdict(summary), indent=2, default=str),
                encoding="utf-8",
            )
            typer.echo(f"  Summary: {summary_path}")
        except Exception as exc:
            logger.debug("Failed to write run summary JSON: {}", exc)

    # Write GH Step Summary
    _write_gh_step_summary(mode, result, summary)


def _write_gh_step_summary(
    mode: str,
    result: PipelineResult,
    summary: RunSummary | None,
) -> None:
    """Write markdown extraction summary to $GITHUB_STEP_SUMMARY if available."""
    summary_path = os.environ.get("GITHUB_STEP_SUMMARY")
    if not summary_path:
        return

    from datetime import datetime

    lines: list[str] = []
    lines.append(f"## 🏀 {mode.title()} Extraction — {datetime.now().strftime('%Y-%m-%d')}")
    lines.append("")

    duration = fmt_time(result.duration_seconds)
    lines.append(
        f"**{result.tables_updated} tables** | **{result.rows_total:,} rows** | **{duration}**"
    )
    lines.append("")

    if summary and summary.patterns:
        lines.append("| Pattern | Total | OK | Fail | Skip | Rows | Time | FG% |")
        lines.append("|---------|------:|---:|-----:|-----:|-----:|------|----:|")
        for pattern in summary.patterns:
            total = _summary_metric(pattern, "total")
            ok = _summary_metric(pattern, "ok", "succeeded")
            fail = _summary_metric(pattern, "fail", "failed")
            skip = _summary_metric(pattern, "skip", "skipped")
            rows = _summary_metric(pattern, "rows", "rows_extracted")
            dur = fmt_time(_pattern_duration(pattern))
            fg = f"{ok / total * 100:.1f}%" if total > 0 else "-"
            lines.append(
                f"| {_summary_label(pattern)} | {total:,} | {ok:,} | {fail:,} | {skip:,} "
                f"| {fmt_rows(rows)} | {dur} | {fg} |"
            )

        # Totals row
        t = summary.totals
        total_ok = _summary_metric(t, "ok", "succeeded")
        total_fail = _summary_metric(t, "fail", "failed")
        total_skip = _summary_metric(t, "skip", "skipped")
        total_rows = _summary_metric(t, "rows", "rows_extracted")
        total_all = total_ok + total_fail + total_skip
        fg_all = f"{total_ok / total_all * 100:.1f}%" if total_all > 0 else "-"
        lines.append(
            f"| **Total** | **{total_all:,}** | **{total_ok:,}** | "
            f"**{total_fail:,}** | **{total_skip:,}** | "
            f"**{fmt_rows(total_rows)}** | **{duration}** | **{fg_all}** |"
        )
        lines.append("")

    if result.errors:
        lines.append(f"<details><summary>Errors ({len(result.errors)})</summary>")
        lines.append("")
        for e in result.errors[:20]:
            lines.append(f"- `{e}`")
        if len(result.errors) > 20:
            lines.append(f"- ... and {len(result.errors) - 20} more")
        lines.append("")
        lines.append("</details>")
        lines.append("")

    try:
        with open(summary_path, "a", encoding="utf-8") as fh:
            fh.write("\n".join(lines))
            fh.write("\n")
    except Exception as exc:
        logger.debug("Failed to write GitHub step summary: {}", exc)


def _run_quality_checks(settings: NbaDbSettings) -> None:
    """Run DataScanner checks on the database after a pipeline run.

    Runs ``missing_table`` and ``data_quality`` categories.  Warns on
    findings but never raises — quality issues are informational only.
    """
    import duckdb

    duckdb_path = settings.duckdb_path
    if duckdb_path is None or not duckdb_path.exists():
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
    run_fn: Callable[[object], Coroutine[Any, Any, Any]],
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
    progress = None
    summary: RunSummary | None = None

    if use_tui:
        from nbadb.cli.tui import run_with_tui

        result_obj, error, summary_obj = run_with_tui(mode, run_fn, settings, orchestrator_cls)
        summary = cast("Any", summary_obj)
        if error is not None:
            typer.echo(f"{mode} failed: {_format_pipeline_exception(error)}", err=True)
            raise typer.Exit(1)
        if result_obj is None:
            typer.echo(f"{mode}: stopped — progress saved in journal (resume-safe)", err=True)
            raise typer.Exit(0)
        result = cast("Any", result_obj)
    else:
        from nbadb.cli.progress import CIProgress

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

        progress = CIProgress(mode)
        orch = None
        try:
            with progress:
                orch = orchestrator_cls(settings=settings, progress=progress)
                try:
                    result = asyncio.run(run_fn(orch))
                except (asyncio.CancelledError, KeyboardInterrupt):
                    typer.echo(
                        f"\n{mode}: stopped — progress saved in journal (resume-safe)", err=True
                    )
                    raise typer.Exit(0) from None
                except Exception as exc:
                    typer.echo(f"{mode} failed: {_format_pipeline_exception(exc)}", err=True)
                    raise typer.Exit(1) from exc
        finally:
            if orch is not None and hasattr(orch, "close"):
                orch.close()
            signal.signal(signal.SIGINT, prev_sigint)
            signal.signal(signal.SIGTERM, prev_sigterm)

        # Export summary from progress tracker
        summary = None
        if progress is not None:
            try:
                summary = progress.export_summary()
            except Exception as exc:
                logger.debug("Failed to export progress summary: {}", exc)

    _print_result(mode, result, summary=summary, settings=settings)
    if result.failed_extractions and result.tables_updated == 0 and result.rows_total == 0:
        raise typer.Exit(1)  # Complete failure — nothing extracted
    # Partial failure — data was extracted, continue with warnings already printed
    if quality_check:
        _run_quality_checks(settings)
