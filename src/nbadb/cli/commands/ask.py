from __future__ import annotations

import typer

from nbadb.cli.app import app


@app.command()
def ask(
    question: str = typer.Argument(..., help="Natural language question"),
    limit: int = typer.Option(10, "--limit", "-l", help="Maximum rows to return"),
    verbose: bool = typer.Option(False, "--verbose", "-v"),
    strict: bool = typer.Option(
        False,
        "--strict",
        help="Exit non-zero when the question is unsupported or the query fails",
    ),
) -> None:
    """Ask a read-only catalog question about the NBA warehouse."""
    from nbadb.agent.query import QueryAgent
    from nbadb.chat.runtime.core import WarehouseUnavailableError, require_usable_warehouse
    from nbadb.core.config import get_settings

    settings = get_settings()
    duckdb_path = settings.duckdb_path
    if duckdb_path is None:
        typer.echo("Error: duckdb_path not configured")
        raise typer.Exit(1)
    try:
        warehouse = require_usable_warehouse(duckdb_path)
    except WarehouseUnavailableError as exc:
        typer.echo(f"Error: {exc}")
        raise typer.Exit(1) from None
    agent = QueryAgent(duckdb_path=warehouse)
    response = agent.ask_result(question, limit=limit)
    text = response.render_text(verbose=verbose)
    if not text:
        typer.echo("(no results)")
    else:
        typer.echo(text)
    if strict and not response.ok:
        raise typer.Exit(1)
