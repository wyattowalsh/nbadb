from __future__ import annotations

from pathlib import Path
from typing import Annotated

import typer

from nbadb.cli.app import app
from nbadb.cli.commands._helpers import _build_settings, _open_db_readonly
from nbadb.cli.options import DataDirOption  # noqa: TC001
from nbadb.core.endpoint_coverage import EndpointCoverageGenerator
from nbadb.core.table_year_coverage import (
    build_table_year_coverage,
    write_table_year_coverage_artifacts,
)

OutputDirOption = Annotated[
    Path | None,
    typer.Option("--output-dir", "-o", help="Output directory for table/year coverage artifacts."),
]
RequireCompleteOption = Annotated[
    bool,
    typer.Option(
        "--require-complete",
        help=(
            "Exit non-zero when expected table/year rows are missing, failed, "
            "running, or abandoned."
        ),
    ),
]


@app.command("table-year-coverage")
def table_year_coverage(
    data_dir: DataDirOption = None,
    output_dir: OutputDirOption = None,
    require_complete: RequireCompleteOption = False,
) -> None:
    """Compare expected endpoint/year coverage with actual DuckDB table contents."""

    settings = _build_settings(data_dir)
    db_path = settings.duckdb_path
    if db_path is None or not db_path.exists():
        typer.echo("Database not found. Run 'nbadb init' first.", err=True)
        raise typer.Exit(1)

    generator = EndpointCoverageGenerator()
    endpoint_artifacts = generator.build_artifacts()
    temporal_matrix = endpoint_artifacts["temporal_coverage_matrix"]["matrix"]

    conn = _open_db_readonly(db_path)
    try:
        coverage = build_table_year_coverage(conn, temporal_matrix)
    finally:
        conn.close()

    artifact_dir = output_dir or Path("artifacts") / "coverage"
    paths = write_table_year_coverage_artifacts(coverage, artifact_dir)
    summary = coverage["summary"]
    typer.echo(
        "Table/year coverage: "
        f"expected={summary['expected_row_count']} "
        f"actual={summary['actual_row_count']} "
        f"blocking_missing={summary['blocking_missing_count']} "
        f"contract_gaps={summary['contract_gap_count']}"
    )
    breakdown = summary.get("coverage_status_breakdown", {})
    if breakdown:
        typer.echo(
            "Status breakdown: "
            + " ".join(f"{key}={value}" for key, value in sorted(breakdown.items()))
        )
    typer.echo(f"Artifacts dir: {paths['summary'].parent}")

    if require_complete and int(summary.get("blocking_missing_count", 0)) > 0:
        typer.echo(
            "require-complete check failed: actual table/year coverage gaps remain",
            err=True,
        )
        raise typer.Exit(1)
