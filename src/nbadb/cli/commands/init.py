from __future__ import annotations

import typer

from nbadb.cli.app import app


@app.command()
def init(
    verbose: bool = typer.Option(False, "--verbose", "-v"),
) -> None:
    """Full rebuild from scratch (~2-4h)."""
    typer.echo("nbadb init: not yet implemented")
    raise typer.Exit(1)
