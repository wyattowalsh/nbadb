from __future__ import annotations

import typer

from nbadb.cli.app import app


@app.command()
def full(
    verbose: bool = typer.Option(False, "--verbose", "-v"),
) -> None:
    """Fill gaps, preserve existing data."""
    typer.echo("nbadb full: not yet implemented")
    raise typer.Exit(1)
