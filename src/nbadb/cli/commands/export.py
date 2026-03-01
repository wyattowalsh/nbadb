from __future__ import annotations

import typer

from nbadb.cli.app import app
from nbadb.cli.commands._helpers import _build_settings
from nbadb.cli.options import DataDirOption, FormatOption  # noqa: TC001


@app.command()
def export(
    data_dir: DataDirOption = None,
    format: FormatOption = None,  # noqa: A002
) -> None:
    """Export database tables to specified formats (csv, parquet, sqlite)."""
    import duckdb

    from nbadb.load.multi import create_multi_loader

    settings = _build_settings(data_dir, format)
    db_path = settings.duckdb_path

    if db_path is None or not db_path.exists():
        typer.echo("Database not found. Run 'nbadb init' first.")
        raise typer.Exit(1)

    try:
        conn = duckdb.connect(str(db_path), read_only=True)
    except Exception as exc:
        typer.echo(f"Cannot open database: {exc}", err=True)
        raise typer.Exit(1) from exc

    try:
        from nbadb.core.db import get_user_tables
        tables = get_user_tables(conn)
        if not tables:
            typer.echo("No tables found to export.")
            raise typer.Exit(1)

        loader = create_multi_loader(settings, duckdb_conn=conn)
        exported = 0
        for table in tables:
            try:
                df = conn.execute(
                    f"SELECT * FROM {table}"  # noqa: S608
                ).pl()
                loader.load(table, df, mode="replace")
                typer.echo(f"  {table}: {df.shape[0]:,} rows")
                exported += 1
            except Exception as exc:
                typer.echo(
                    f"  {table}: export failed ({exc})", err=True
                )

        typer.echo(
            f"\nExported {exported}/{len(tables)} tables "
            f"to formats: {', '.join(settings.formats)}"
        )
    finally:
        conn.close()
