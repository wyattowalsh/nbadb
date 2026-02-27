from __future__ import annotations

import typer

from nbadb.cli.app import app


@app.command()
def export(
    verbose: bool = typer.Option(False, "--verbose", "-v"),
) -> None:
    """Re-export to all formats."""
    typer.echo("nbadb export: not yet implemented")
    raise typer.Exit(1)
