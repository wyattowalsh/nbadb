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
        help="Exit non-zero when runtime_gap, staging_only, or extractor_only endpoints remain.",
    ),
]


@app.command("extract-completeness")
def extract_completeness(
    output_dir: OutputDirOption = None,
    require_full: RequireFullOption = False,
) -> None:
    """Generate endpoint coverage artifacts and report coverage counts."""
    generator = EndpointCoverageGenerator()
    written = generator.write(output_dir=output_dir)
    summary = json.loads(written["summary"].read_text(encoding="utf-8"))
    coverage = summary.get("coverage", {})

    covered = int(coverage.get("covered", 0))
    runtime_gap = int(coverage.get("runtime_gap", 0))
    staging_only = int(coverage.get("staging_only", 0))
    extractor_only = int(coverage.get("extractor_only", 0))
    non_covered = runtime_gap + staging_only + extractor_only

    typer.echo(
        "Coverage counts: "
        f"covered={covered} runtime_gap={runtime_gap} "
        f"staging_only={staging_only} extractor_only={extractor_only} "
        f"non_covered={non_covered}"
    )
    typer.echo(f"Artifacts dir: {written['summary'].parent}")

    if require_full and non_covered:
        typer.echo("require-full check failed: non-covered endpoints remain", err=True)
        raise typer.Exit(1)
