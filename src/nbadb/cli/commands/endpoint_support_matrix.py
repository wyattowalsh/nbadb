from __future__ import annotations

from pathlib import Path
from typing import Annotated

import typer

from nbadb.cli.app import app
from nbadb.core.endpoint_coverage import EndpointCoverageGenerator

OutputDirOption = Annotated[
    Path | None,
    typer.Option("--output-dir", "-o", help="Output directory for endpoint support artifacts."),
]
RequireCompleteOption = Annotated[
    bool,
    typer.Option(
        "--require-complete",
        help=(
            "Exit non-zero when in-scope extraction contract gaps remain for the full "
            "historical backfill contract. explicitly excluded surfaces are reported "
            "separately and do not fail this gate."
        ),
    ),
]
RequireSeasonTypeContractOption = Annotated[
    bool,
    typer.Option(
        "--require-season-type-contract",
        help=(
            "Exit non-zero when historical surfaces still lack explicit season-type tracking "
            "or are explicitly blocked from that contract."
        ),
    ),
]


@app.command("endpoint-support-matrix")
def endpoint_support_matrix(
    output_dir: OutputDirOption = None,
    require_complete: RequireCompleteOption = False,
    require_season_type_contract: RequireSeasonTypeContractOption = False,
) -> None:
    """Generate the extraction support matrix and summary."""

    generator = EndpointCoverageGenerator()
    artifacts = generator.build_artifacts()
    written = generator.write_artifacts(artifacts, output_dir=output_dir)
    summary = artifacts["extraction_summary"]

    typer.echo(
        "Endpoint support: "
        f"endpoints={summary.get('endpoint_count', 0)} "
        f"in_scope={summary.get('in_scope_endpoint_count', 0)} "
        f"extractable={summary.get('extractable_endpoint_count', 0)} "
        f"partial={summary.get('partial_endpoint_count', 0)} "
        f"blocked={summary.get('blocked_endpoint_count', 0)} "
        f"excluded={summary.get('excluded_endpoint_count', 0)} "
        "season_type_open="
        f"{summary.get('season_type_contract_open_count', 0)} "
        "ready_for_full_backfill="
        f"{summary.get('ready_for_full_backfill', False)}"
    )

    semantics = summary.get("execution_semantics_breakdown", {})
    if semantics:
        typer.echo(
            "Execution semantics: "
            f"historical_backfill={semantics.get('historical_backfill', 0)} "
            f"reference_snapshot={semantics.get('reference_snapshot', 0)} "
            f"live_snapshot={semantics.get('live_snapshot', 0)}"
        )

    gaps = summary.get("extraction_gap_breakdown", {})
    if gaps:
        typer.echo(
            "Gap breakdown: " + " ".join(f"{key}={value}" for key, value in sorted(gaps.items()))
        )

    exclusions = summary.get("explicit_exclusion_breakdown", {})
    if exclusions:
        typer.echo(
            "Exclusions: " + " ".join(f"{key}={value}" for key, value in sorted(exclusions.items()))
        )

    typer.echo(f"Artifacts dir: {written['extraction_summary'].parent}")

    if require_complete and (
        int(summary.get("partial_endpoint_count", 0)) > 0
        or int(summary.get("blocked_endpoint_count", 0)) > 0
    ):
        typer.echo("require-complete check failed: endpoint contract gaps remain", err=True)
        raise typer.Exit(1)

    if require_season_type_contract and int(summary.get("season_type_contract_open_count", 0)) > 0:
        typer.echo(
            (
                "require-season-type-contract check failed: historical surfaces still lack "
                "explicit season-type tracking or remain blocked from that contract"
            ),
            err=True,
        )
        raise typer.Exit(1)
