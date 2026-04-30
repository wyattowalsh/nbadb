from __future__ import annotations

import json
from pathlib import Path
from typing import Annotated

import typer

from nbadb.cli.app import app
from nbadb.core.endpoint_coverage import EndpointCoverageGenerator

OutputDirOption = Annotated[
    Path | None,
    typer.Option("--output-dir", "-o", help="Output directory for endpoint adequacy artifacts."),
]


@app.command("endpoint-adequacy-scorecard")
def endpoint_adequacy_scorecard(output_dir: OutputDirOption = None) -> None:
    """Generate the endpoint adequacy scorecard and report."""

    generator = EndpointCoverageGenerator()
    written = generator.write_endpoint_adequacy_scorecard(output_dir=output_dir)
    payload = json.loads(written["endpoint_adequacy_scorecard"].read_text(encoding="utf-8"))
    summary = payload["summary"]

    typer.echo(
        "Endpoint adequacy: "
        f"endpoints={summary.get('endpoint_count', 0)} "
        f"adequate={summary.get('adequate_endpoint_count', 0)} "
        f"coverage_gaps={summary.get('coverage_gap_endpoint_count', 0)} "
        f"contract_gaps={summary.get('contract_gap_endpoint_count', 0)} "
        f"downstream_modeled={summary.get('downstream_modeled_endpoint_count', 0)} "
        "downstream_passthrough="
        f"{summary.get('downstream_passthrough_only_endpoint_count', 0)} "
        "downstream_compatibility_reference="
        f"{summary.get('downstream_compatibility_reference_only_endpoint_count', 0)} "
        f"downstream_excluded={summary.get('downstream_excluded_endpoint_count', 0)} "
        f"downstream_unowned={summary.get('downstream_unowned_endpoint_count', 0)}"
    )

    adequacy = summary.get("adequacy_status_breakdown", {})
    if adequacy:
        typer.echo(
            "Adequacy breakdown: "
            + " ".join(f"{key}={value}" for key, value in sorted(adequacy.items()))
        )

    downstream = summary.get("downstream_status_breakdown", {})
    if downstream:
        typer.echo(
            "Downstream breakdown: "
            + " ".join(f"{key}={value}" for key, value in sorted(downstream.items()))
        )

    typer.echo(f"Artifacts dir: {written['endpoint_adequacy_scorecard'].parent}")
