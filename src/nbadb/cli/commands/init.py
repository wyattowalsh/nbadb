from __future__ import annotations

import typer

from nbadb.cli.app import app
from nbadb.cli.commands._helpers import _build_settings, _run_pipeline
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
    season_end: int | None = typer.Option(
        None,
        "--season-end",
        "-e",
        help="End season year (default: current)",
    ),
    verbose: VerboseOption = False,
    quality_check: bool = typer.Option(
        False, "--quality-check", help="Run quality checks after pipeline"
    ),
) -> None:
    """Initialize database with full NBA history (resume-safe)."""
    settings = _build_settings(data_dir, format)
    _run_pipeline(
        "init",
        lambda orch: orch.run_init(start_season=season_start, end_season=season_end),
        settings,
        verbose,
        quality_check,
        orchestrator_cls=Orchestrator,
    )
