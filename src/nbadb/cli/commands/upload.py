from __future__ import annotations

import typer

from nbadb.cli.app import app


@app.command()
def upload(
    verbose: bool = typer.Option(False, "--verbose", "-v"),
) -> None:
    """Push to Kaggle."""
    typer.echo("nbadb upload: not yet implemented")
    raise typer.Exit(1)
