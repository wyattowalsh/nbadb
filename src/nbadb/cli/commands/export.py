from __future__ import annotations

import typer

from nbadb.cli.app import app
from nbadb.cli.commands._helpers import _build_settings
from nbadb.cli.options import DataDirOption, FormatOption  # noqa: TC001


@app.command()
def export(
    data_dir: DataDirOption = None,
    format: FormatOption = None,  # noqa: A002
    allow_partial: bool = typer.Option(
        False,
        "--allow-partial",
        help="Continue and exit 0 when non-critical export formats fail.",
    ),
) -> None:
    """Export database tables to specified formats (csv, parquet, sqlite)."""
    from nbadb.load.multi import SUPPORTED_FORMATS, create_multi_loader

    settings = _build_settings(data_dir, format)
    unknown_formats = sorted(set(settings.formats) - SUPPORTED_FORMATS)
    if unknown_formats:
        typer.echo(
            f"Unsupported export format(s): {', '.join(unknown_formats)}",
            err=True,
        )
        raise typer.Exit(1)

    db_path = settings.duckdb_path

    if db_path is None or not db_path.exists():
        typer.echo("Database not found. Run 'nbadb init' first.")
        raise typer.Exit(1)

    import duckdb

    conn = duckdb.connect(str(db_path))

    try:
        from nbadb.core.db import get_user_tables

        tables = get_user_tables(conn)
        if not tables:
            typer.echo("No tables found to export.")
            raise typer.Exit(1)

        loader = create_multi_loader(settings, duckdb_conn=conn, strict=not allow_partial)
        exported = 0
        failures: list[str] = []
        for table in tables:
            try:
                df = conn.execute(f"SELECT * FROM {table}").pl()
                loader.load(table, df, mode="replace")
                typer.echo(f"  {table}: {df.shape[0]:,} rows")
                exported += 1
            except Exception as exc:
                typer.echo(f"  {table}: export failed ({type(exc).__name__})", err=True)
                failures.append(table)

        typer.echo(
            f"\nExported {exported}/{len(tables)} tables to formats: {', '.join(settings.formats)}"
        )
        if failures and not allow_partial:
            typer.echo(
                f"Export failed for {len(failures)} table(s): {', '.join(failures)}",
                err=True,
            )
            raise typer.Exit(1)
    finally:
        conn.close()
