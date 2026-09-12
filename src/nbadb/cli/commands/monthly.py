from __future__ import annotations

import typer

from nbadb.cli.app import app
from nbadb.cli.commands._helpers import _build_settings, _run_pipeline
from nbadb.cli.options import DataDirOption, VerboseOption  # noqa: TC001
from nbadb.orchestrate import Orchestrator


@app.command()
def monthly(
    data_dir: DataDirOption = None,
    verbose: VerboseOption = False,
    quality_check: bool = typer.Option(
        False, "--quality-check", help="Run quality checks after pipeline"
    ),
) -> None:
    """Refresh recent NBA seasons from the current local/Kaggle baseline."""
    settings = _build_settings(data_dir)
    _run_pipeline(
        "monthly",
        lambda orch: orch.run_monthly(),
        settings,
        verbose,
        quality_check,
        orchestrator_cls=Orchestrator,
        require_complete_result=True,
    )
