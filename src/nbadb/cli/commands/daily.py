from __future__ import annotations

import typer

from nbadb.cli.app import app


@app.command()
def daily(
    verbose: bool = typer.Option(False, "--verbose", "-v"),
) -> None:
    """Incremental update (~5-15m)."""
    typer.echo("nbadb daily: not yet implemented")
    raise typer.Exit(1)
