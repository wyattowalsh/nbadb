from __future__ import annotations

import typer

from nbadb.cli.app import app
from nbadb.cli.commands._helpers import _build_settings
from nbadb.cli.options import DataDirOption  # noqa: TC001


@app.command("run-quality")
def run_quality(
    data_dir: DataDirOption = None,
) -> None:
    """Run data quality checks on the existing DuckDB database."""
    settings = _build_settings(data_dir)
    db_path = settings.duckdb_path

    if db_path is None or not db_path.exists():
        typer.echo("Error: database not found. Run 'nbadb init' first.", err=True)
        raise typer.Exit(1)

    import duckdb

    from nbadb.transform.quality import DataQualityMonitor

    conn = duckdb.connect(str(db_path), read_only=True)
    try:
        monitor = DataQualityMonitor(conn)
        monitor.log_summary()
        s = monitor.summary()
        typer.echo(f"Quality: {s['passed']}/{s['total']} checks passed")
        if monitor.failed():
            typer.echo(
                f"  {len(monitor.failed())} checks failed",
                err=True,
            )
    except Exception as exc:
        typer.echo(f"Quality check failed: {type(exc).__name__}", err=True)
        raise typer.Exit(1) from exc
    finally:
        conn.close()
