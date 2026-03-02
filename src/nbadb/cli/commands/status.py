from __future__ import annotations

import json

import duckdb
import typer

from nbadb.cli.app import app
from nbadb.cli.commands._helpers import _build_settings, _open_db_readonly
from nbadb.cli.options import DataDirOption  # noqa: TC001


@app.command()
def status(
    data_dir: DataDirOption = None,
    output_format: str = typer.Option(
        "text",
        "--output-format",
        "-f",
        help="Output format: text or json",
    ),
) -> None:
    """Show pipeline status, watermarks, and failed extractions."""
    settings = _build_settings(data_dir)
    db_path = settings.duckdb_path

    if db_path is None or not db_path.exists():
        typer.echo("Database not found. Run 'nbadb init' first.")
        raise typer.Exit(1)

    conn = _open_db_readonly(db_path)

    try:
        if output_format == "json":
            data = {
                "watermarks": _get_watermarks(conn) or [],
                "journal": _get_journal_summary(conn) or {},
                "metadata": _get_table_metadata(conn) or [],
            }
            typer.echo(json.dumps(data, indent=2, default=str))
        else:
            _show_watermarks(conn)
            _show_journal_summary(conn)
            _show_table_metadata(conn)
    finally:
        conn.close()


def _get_watermarks(conn: object) -> list[dict] | None:
    """Return watermark rows, or None if the table doesn't exist."""
    try:
        rows = conn.execute(  # type: ignore[union-attr]
            "SELECT table_name, watermark_type, watermark_value, "
            "last_updated, row_count_at_watermark "
            "FROM _pipeline_watermarks ORDER BY last_updated DESC"
        ).fetchall()
        return [
            {
                "table": r[0],
                "type": r[1],
                "value": r[2],
                "updated": str(r[3]),
                "rows": r[4],
            }
            for r in rows
        ]
    except duckdb.Error:
        return None


def _get_journal_summary(conn: object) -> dict[str, int] | None:
    """Return journal status counts, or None if the table doesn't exist."""
    try:
        rows = conn.execute(  # type: ignore[union-attr]
            "SELECT status, COUNT(*) AS cnt "
            "FROM _extraction_journal GROUP BY status ORDER BY status"
        ).fetchall()
        return {r[0]: r[1] for r in rows}
    except duckdb.Error:
        return None


def _get_table_metadata(conn: object) -> list[dict] | None:
    """Return table metadata rows, or None if the table doesn't exist."""
    try:
        rows = conn.execute(  # type: ignore[union-attr]
            "SELECT table_name, row_count, last_updated FROM _pipeline_metadata ORDER BY table_name"
        ).fetchall()
        return [{"table": r[0], "rows": r[1], "updated": str(r[2])} for r in rows]
    except duckdb.Error:
        return None


def _show_watermarks(conn: object) -> None:
    """Display pipeline watermarks."""
    rows = _get_watermarks(conn)
    typer.echo("\n--- Pipeline Watermarks ---")
    if rows is None:
        typer.echo("  (no watermark data)")
        return
    if not rows:
        typer.echo("  (empty)")
        return
    for r in rows:
        typer.echo(
            f"  {r['table']} [{r['type']}]: {r['value']}  "
            f"(updated {r['updated']}, {r['rows'] or '?'} rows)"
        )


def _show_journal_summary(conn: object) -> None:
    """Display extraction journal status counts."""
    counts = _get_journal_summary(conn)
    typer.echo("\n--- Extraction Journal ---")
    if counts is None:
        typer.echo("  (no extraction journal)")
        return
    if not counts:
        typer.echo("  (empty)")
        return
    for s, cnt in counts.items():
        typer.echo(f"  {s}: {cnt}")


def _show_table_metadata(conn: object) -> None:
    """Display pipeline metadata (table sizes)."""
    rows = _get_table_metadata(conn)
    typer.echo("\n--- Table Metadata ---")
    if rows is None:
        typer.echo("  (no table metadata)")
        return
    if not rows:
        typer.echo("  (empty)")
        return
    for r in rows:
        typer.echo(f"  {r['table']}: {r['rows']:,} rows  (updated {r['updated']})")
