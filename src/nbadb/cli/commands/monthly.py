from __future__ import annotations

import typer

from nbadb.cli.app import app


@app.command()
def monthly(
    verbose: bool = typer.Option(False, "--verbose", "-v"),
) -> None:
    """Dimension refresh (~30-60m)."""
    typer.echo("nbadb monthly: not yet implemented")
    raise typer.Exit(1)
