from __future__ import annotations

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
            f"modeled_endpoints={model_ownership.get('analytically_modeled_stats_endpoints', 0)} "
            f"passthrough_endpoints={model_ownership.get('passthrough_only_stats_endpoints', 0)} "
            "compatibility_reference_endpoints="
            f"{model_ownership.get('compatibility_reference_only_stats_endpoints', 0)} "
            f"model_excluded_endpoints={model_ownership.get('model_excluded_stats_endpoints', 0)} "
            f"model_unowned_endpoints={model_ownership.get('model_unowned_stats_endpoints', 0)} "
            f"staging_entries={model_ownership.get('staging_entry_count', 0)} "
            f"modeled={model_ownership.get('analytically_modeled_staging_entries', 0)} "
            f"passthrough={model_ownership.get('passthrough_only_staging_entries', 0)} "
            "compatibility_reference="
            f"{model_ownership.get('compatibility_reference_only_staging_entries', 0)} "
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
    upstream_contract = summary.get("upstream_contract", {})
    upstream_field_fate = summary.get("upstream_field_fate", {})
    temporal_coverage = summary.get("temporal_coverage", {})
    if upstream_field_fate or temporal_coverage:
        typer.echo(
            "Contract field coverage: "
            f"field_gaps={upstream_contract.get('field_gap_count', 0)} "
            f"contract_unknown_result_sets="
            f"{upstream_contract.get('contract_unknown_result_set_count', 0)} "
            f"blocking_contract_unknown_result_sets="
            f"{upstream_contract.get('blocking_contract_unknown_result_set_count', 0)} "
            f"missing_sink={upstream_field_fate.get('missing_sink_count', 0)} "
            f"model_usage_unknown="
            f"{upstream_field_fate.get('model_usage_unknown_count', 0)} "
            f"unmodeled_unclassified="
            f"{upstream_field_fate.get('unmodeled_unclassified_count', 0)} "
            f"required_temporal_missing="
            f"{temporal_coverage.get('required_temporal_missing_count', 0)}"
        )
    typer.echo(f"Artifacts dir: {written['summary'].parent}")

    field_gaps = int(upstream_contract.get("field_gap_count", 0))
    invalid_result_sets = int(upstream_contract.get("invalid_result_set_index_count", 0))
    missing_result_sets = int(upstream_contract.get("missing_result_set_staging_count", 0))
    missing_input_schemas = int(upstream_contract.get("missing_input_schema_count", 0))
    blocking_contract_unknown_result_sets = int(
        upstream_contract.get("blocking_contract_unknown_result_set_count", 0)
    )
    missing_sink = int(upstream_field_fate.get("missing_sink_count", 0))
    model_usage_unknown = int(upstream_field_fate.get("model_usage_unknown_count", 0))
    unmodeled_unclassified = int(upstream_field_fate.get("unmodeled_unclassified_count", 0))
    required_temporal_missing = int(temporal_coverage.get("required_temporal_missing_count", 0))
    if require_full and (
        partial
        or blocked
        or season_type_open
        or field_gaps
        or invalid_result_sets
        or missing_result_sets
        or missing_input_schemas
        or blocking_contract_unknown_result_sets
        or missing_sink
        or model_usage_unknown
        or unmodeled_unclassified
        or required_temporal_missing
    ):
        typer.echo(
            "require-full check failed: extraction, field sink, or temporal contract gaps remain",
            err=True,
        )
        raise typer.Exit(1)
    if require_model_contract and int(model_ownership.get("model_unowned_stats_endpoints", 0)):
        typer.echo(
            "require-model-contract check failed: staged stats endpoints lack a model decision",
            err=True,
        )
        raise typer.Exit(1)
