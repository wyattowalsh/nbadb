from __future__ import annotations

import typer

from nbadb.cli.app import app


@app.command()
def download(
    verbose: bool = typer.Option(False, "--verbose", "-v"),
) -> None:
    """Pull from Kaggle."""
    typer.echo("nbadb download: not yet implemented")
    raise typer.Exit(1)
