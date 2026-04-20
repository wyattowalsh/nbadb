from __future__ import annotations

import json

import typer

from nbadb.cli.app import app
from nbadb.cli.commands._helpers import _build_settings
from nbadb.cli.options import DataDirOption  # noqa: TC001

_REPORT_PATH_OPTION = typer.Option(
    None,
    "--report-path",
    help="Write machine-readable quality report JSON to this path.",
)


@app.command("run-quality", deprecated=True)
def run_quality(
    data_dir: DataDirOption = None,
    report_path: str | None = _REPORT_PATH_OPTION,
) -> None:
    """Run data quality checks on the existing DuckDB database.

    .. deprecated::
        Use ``nbadb scan`` instead — it covers row counts and much more.
    """
    typer.echo(
        "WARNING: 'run-quality' is deprecated — use 'nbadb scan' instead.",
        err=True,
    )
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
        summary = monitor.summary()
        failed_checks = monitor.failed()
        if report_path is not None:
            from pathlib import Path

            report_output = Path(report_path)
            report_output.parent.mkdir(parents=True, exist_ok=True)
            report_output.write_text(
                json.dumps(monitor.to_report(), indent=2, sort_keys=True),
                encoding="utf-8",
            )
            typer.echo(f"Quality report: {report_output}")
        typer.echo(f"Quality: {summary['passed']}/{summary['total']} checks passed")
        if summary["total"] == 0:
            typer.echo("Quality check failed: no checks were executed", err=True)
            raise typer.Exit(1)
        if failed_checks:
            typer.echo(
                f"  {len(failed_checks)} checks failed",
                err=True,
            )
    except typer.Exit:
        raise
    except Exception as exc:
        typer.echo(f"Quality check failed: {type(exc).__name__}", err=True)
        raise typer.Exit(1) from exc
    finally:
        conn.close()
