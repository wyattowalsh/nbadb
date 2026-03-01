from __future__ import annotations

import asyncio

import typer

from nbadb.cli.app import app
from nbadb.cli.commands._helpers import (
    _build_settings,
    _print_result,
    _run_quality_checks,
    _setup_logging,
)
from nbadb.cli.options import DataDirOption, FormatOption, VerboseOption  # noqa: TC001
from nbadb.orchestrate import Orchestrator


@app.command()
def init(
    data_dir: DataDirOption = None,
    format: FormatOption = None,  # noqa: A002
    season_start: int = typer.Option(
        1946,
        "--season-start",
        "-s",
        help="Start season year",
    ),
    verbose: VerboseOption = False,
    quality_check: bool = typer.Option(
        False, "--quality-check", help="Run quality checks after pipeline"
    ),
) -> None:
    """Initialize database with full NBA history (resume-safe)."""
    _setup_logging(verbose)
    settings = _build_settings(data_dir, format)
    try:
        result = asyncio.run(
            Orchestrator(settings).run_init(start_season=season_start)
        )
    except Exception as exc:
        typer.echo(f"init failed: {exc}", err=True)
        raise typer.Exit(1) from exc
    _print_result("init", result)
    if quality_check:
        _run_quality_checks(settings)
