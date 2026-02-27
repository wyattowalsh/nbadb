from __future__ import annotations

import typer

from nbadb.cli.app import app


@app.command()
def schema(
    table: str | None = typer.Argument(None, help="Table name to inspect"),
    verbose: bool = typer.Option(False, "--verbose", "-v"),
) -> None:
    """List/show table schemas."""
    typer.echo("nbadb schema: not yet implemented")
    raise typer.Exit(1)
