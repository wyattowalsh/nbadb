from __future__ import annotations

import typer

from nbadb.cli.app import app


@app.command()
def ask(
    question: str = typer.Argument(..., help="Natural language question"),
    verbose: bool = typer.Option(False, "--verbose", "-v"),
) -> None:
    """Ask a question about the NBA data."""
    from nbadb.agent.query import QueryAgent
    from nbadb.core.config import get_settings

    settings = get_settings()
    duckdb_path = settings.duckdb_path
    if duckdb_path is None:
        typer.echo("Error: duckdb_path not configured")
        raise typer.Exit(1)
    agent = QueryAgent(duckdb_path=duckdb_path)
    result = agent.ask(question)
    typer.echo(result)
