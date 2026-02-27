from __future__ import annotations

import typer

from nbadb.cli.app import app


@app.command()
def status(
    verbose: bool = typer.Option(False, "--verbose", "-v"),
) -> None:
    """DB stats and freshness."""
    typer.echo("nbadb status: not yet implemented")
    raise typer.Exit(1)
