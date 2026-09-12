from __future__ import annotations

import shutil

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
    if not settings.formats:
        typer.echo("At least one export format must be requested.", err=True)
        raise typer.Exit(1)
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

    from nbadb.core.artifact_identity import assert_no_private_capture_sentinels

    # The canonical DuckDB is already the requested DuckDB resource. Export is
    # a read-only projection into the secondary formats and must never rewrite
    # its source tables through a DuckDBLoader round trip.
    conn = duckdb.connect(str(db_path), read_only=True)

    try:
        from nbadb.core.db import get_user_tables

        tables = get_user_tables(conn)
        if not tables:
            typer.echo("No tables found to export.")
            raise typer.Exit(1)

        for format_name in ("csv", "parquet"):
            export_root = settings.data_dir / format_name
            if export_root.is_symlink():
                raise RuntimeError(f"Refusing to replace symlinked export root: {export_root}")

        if settings.data_dir.exists():
            assert_no_private_capture_sentinels(settings.data_dir)

        for format_name in ("csv", "parquet"):
            export_root = settings.data_dir / format_name
            if export_root.exists():
                shutil.rmtree(export_root)

        secondary_formats = [
            format_name for format_name in settings.formats if format_name != "duckdb"
        ]
        loader = (
            create_multi_loader(
                settings.model_copy(update={"formats": secondary_formats}),
                strict=not allow_partial,
            )
            if secondary_formats
            else None
        )
        exported = 0
        failures: list[str] = []
        for table in tables:
            try:
                if loader is None:
                    count_row = conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()
                    if count_row is None:
                        raise RuntimeError(f"DuckDB did not return a row count for {table}")
                    row_count = int(count_row[0])
                else:
                    df = conn.execute(f"SELECT * FROM {table}").pl()
                    loader.load(table, df, mode="replace")
                    row_count = df.shape[0]
                typer.echo(f"  {table}: {row_count:,} rows")
                exported += 1
            except Exception as exc:
                typer.echo(f"  {table}: export failed ({type(exc).__name__})", err=True)
                failures.append(table)

        typer.echo(
            f"\nExported {exported}/{len(tables)} tables to formats: {', '.join(settings.formats)}"
        )
        assert_no_private_capture_sentinels(settings.data_dir)
        if failures and not allow_partial:
            typer.echo(
                f"Export failed for {len(failures)} table(s): {', '.join(failures)}",
                err=True,
            )
            raise typer.Exit(1)
    finally:
        conn.close()
