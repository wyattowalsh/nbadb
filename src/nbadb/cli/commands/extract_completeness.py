from __future__ import annotations

import json
from pathlib import Path
from typing import Annotated

import typer

from nbadb.cli.app import app
from nbadb.core.endpoint_coverage import EndpointCoverageGenerator

OutputDirOption = Annotated[
    Path | None,
    typer.Option("--output-dir", "-o", help="Output directory for endpoint coverage artifacts."),
]
RequireFullOption = Annotated[
    bool,
    typer.Option(
        "--require-full",
        help=(
            "Exit non-zero when in-scope extraction readiness gaps remain for the "
            "historical full-backfill contract."
        ),
    ),
]
RequireModelContractOption = Annotated[
    bool,
    typer.Option(
        "--require-model-contract",
        help=(
            "Exit non-zero when a staged stats endpoint lacks both transform "
            "ownership and an explicit model exclusion."
        ),
    ),
]


@app.command("extract-completeness")
def extract_completeness(
    output_dir: OutputDirOption = None,
    require_full: RequireFullOption = False,
    require_model_contract: RequireModelContractOption = False,
) -> None:
    """Generate endpoint coverage artifacts and report coverage counts."""
    generator = EndpointCoverageGenerator()
    artifacts = generator.build_artifacts()
    written = generator.write_artifacts(artifacts, output_dir=output_dir)
    summary = artifacts["summary"]
    extraction = summary.get("extraction_contract", {})
    extraction_ready = bool(extraction.get("ready_for_full_backfill", False))
    extractable = int(extraction.get("extractable_endpoint_count", 0))
    partial = int(extraction.get("partial_endpoint_count", 0))
    blocked = int(extraction.get("blocked_endpoint_count", 0))
    excluded = int(extraction.get("excluded_endpoint_count", 0))
    in_scope = int(extraction.get("in_scope_endpoint_count", 0))
    season_type_open = int(extraction.get("season_type_contract_open_count", 0))

    typer.echo(
        "Extraction readiness: "
        f"in_scope={in_scope} extractable={extractable} "
        f"partial={partial} blocked={blocked} excluded={excluded} "
        f"season_type_open={season_type_open} "
        f"ready_for_full_backfill={extraction_ready}"
    )
    model_ownership = summary.get("model_ownership", {})
    if model_ownership:
        typer.echo(
            "Model ownership: "
            f"stats_endpoints={model_ownership.get('stats_endpoint_count', 0)} "
            f"transform_owned_endpoints="
            f"{model_ownership.get('transform_owned_stats_endpoints', 0)} "
            f"model_excluded_endpoints={model_ownership.get('model_excluded_stats_endpoints', 0)} "
            f"model_unowned_endpoints={model_ownership.get('model_unowned_stats_endpoints', 0)} "
            f"staging_entries={model_ownership.get('staging_entry_count', 0)} "
            f"transform_owned={model_ownership.get('transform_owned_staging_entries', 0)} "
            f"model_excluded={model_ownership.get('model_excluded_staging_entries', 0)} "
            f"model_unowned={model_ownership.get('model_unowned_staging_entries', 0)}"
        )
    star_schema_coverage = summary.get("star_schema_coverage", {})
    if star_schema_coverage:
        typer.echo(
            "Star schema coverage: "
            f"transform_outputs={star_schema_coverage.get('transform_output_count', 0)} "
            f"schema_backed={star_schema_coverage.get('schema_backed_transform_outputs', 0)} "
            f"schema_missing={star_schema_coverage.get('schema_missing_transform_outputs', 0)} "
            f"schema_only={star_schema_coverage.get('schema_only_table_count', 0)}"
        )
    typer.echo(f"Artifacts dir: {written['summary'].parent}")

    if require_full and (partial or blocked or season_type_open):
        typer.echo(
            "require-full check failed: extraction contract gaps remain for in-scope endpoints",
            err=True,
        )
        raise typer.Exit(1)
    if require_model_contract and int(model_ownership.get("model_unowned_stats_endpoints", 0)):
        typer.echo(
            "require-model-contract check failed: staged stats endpoints lack a model decision",
            err=True,
        )
        raise typer.Exit(1)
