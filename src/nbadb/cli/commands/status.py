from __future__ import annotations

import typer

from nbadb.cli.app import app
from nbadb.cli.commands._helpers import _build_settings
from nbadb.cli.options import DataDirOption  # noqa: TC001


@app.command()
def status(
    data_dir: DataDirOption = None,
) -> None:
    """Show pipeline status, watermarks, and failed extractions."""
    import duckdb

    settings = _build_settings(data_dir)
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
        _show_watermarks(conn)
        _show_journal_summary(conn)
        _show_table_metadata(conn)
    finally:
        conn.close()


def _show_watermarks(conn: object) -> None:
    """Display pipeline watermarks."""
    try:
        rows = conn.execute(  # type: ignore[union-attr]
            "SELECT table_name, watermark_type, watermark_value, "
            "last_updated, row_count_at_watermark "
            "FROM _pipeline_watermarks ORDER BY last_updated DESC"
        ).fetchall()
    except Exception:
        typer.echo("  (no watermark data)")
        return

    typer.echo("\n--- Pipeline Watermarks ---")
    if not rows:
        typer.echo("  (empty)")
        return
    for table, wtype, wval, updated, count in rows:
        typer.echo(
            f"  {table} [{wtype}]: {wval}  "
            f"(updated {updated}, {count or '?'} rows)"
        )


def _show_journal_summary(conn: object) -> None:
    """Display extraction journal status counts."""
    try:
        rows = conn.execute(  # type: ignore[union-attr]
            "SELECT status, COUNT(*) AS cnt "
            "FROM _extraction_journal GROUP BY status ORDER BY status"
        ).fetchall()
    except Exception:
        typer.echo("  (no extraction journal)")
        return

    typer.echo("\n--- Extraction Journal ---")
    if not rows:
        typer.echo("  (empty)")
        return
    for s, cnt in rows:
        typer.echo(f"  {s}: {cnt}")


def _show_table_metadata(conn: object) -> None:
    """Display pipeline metadata (table sizes)."""
    try:
        rows = conn.execute(  # type: ignore[union-attr]
            "SELECT table_name, row_count, last_updated "
            "FROM _pipeline_metadata ORDER BY table_name"
        ).fetchall()
    except Exception:
        typer.echo("  (no table metadata)")
        return

    typer.echo("\n--- Table Metadata ---")
    if not rows:
        typer.echo("  (empty)")
        return
    for table, count, updated in rows:
        typer.echo(
            f"  {table}: {count:,} rows  (updated {updated})"
        )
