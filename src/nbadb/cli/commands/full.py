from __future__ import annotations

import typer

from nbadb.cli.app import app
from nbadb.cli.commands._helpers import _build_settings, _run_pipeline
from nbadb.cli.options import DataDirOption, VerboseOption  # noqa: TC001
from nbadb.orchestrate import Orchestrator


@app.command(deprecated=True)
def full(
    data_dir: DataDirOption = None,
    verbose: VerboseOption = False,
    quality_check: bool = typer.Option(
        False, "--quality-check", help="Run quality checks after pipeline"
    ),
) -> None:
    """Fill gaps and retry failed extractions.

    .. deprecated::
        Use ``nbadb backfill`` instead.
    """
    settings = _build_settings(data_dir)
    _run_pipeline(
        "full",
        lambda orch: orch.run_retry(),
        settings,
        verbose,
        quality_check,
        orchestrator_cls=Orchestrator,
    )
