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
