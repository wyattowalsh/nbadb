from __future__ import annotations

import typer

from nbadb.cli.app import app
from nbadb.cli.commands._helpers import _build_settings
from nbadb.cli.options import DataDirOption  # noqa: TC001


@app.command()
def migrate(
    data_dir: DataDirOption = None,
) -> None:
    """Create or migrate pipeline tables in the DuckDB database."""
    from nbadb.core.db import DBManager

    settings = _build_settings(data_dir)

    if settings.sqlite_path is None:
        typer.echo("Error: sqlite_path not configured.", err=True)
        raise typer.Exit(1)

    if settings.duckdb_path is None:
        typer.echo("Error: duckdb_path not configured.", err=True)
        raise typer.Exit(1)

    try:
        db = DBManager(
            sqlite_path=settings.sqlite_path,
            duckdb_path=settings.duckdb_path,
        )
        db.init()
        db.close()
        typer.echo("Migration complete.")
    except Exception as exc:
        typer.echo(f"Migration failed: {type(exc).__name__}", err=True)
        raise typer.Exit(1) from exc
