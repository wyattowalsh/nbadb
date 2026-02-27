from __future__ import annotations

import asyncio

import typer

from nbadb.cli.app import app
from nbadb.cli.commands._helpers import (
    _build_settings,
    _print_result,
    _setup_logging,
)
from nbadb.cli.options import DataDirOption, VerboseOption  # noqa: TC001
from nbadb.orchestrate import Orchestrator


@app.command()
def full(
    data_dir: DataDirOption = None,
    verbose: VerboseOption = False,
) -> None:
    """Fill gaps and retry failed extractions."""
    _setup_logging(verbose)
    settings = _build_settings(data_dir)
    try:
        result = asyncio.run(Orchestrator(settings).run_full())
    except Exception as exc:
        typer.echo(f"full failed: {exc}", err=True)
        raise typer.Exit(1) from exc
    _print_result("full", result)
