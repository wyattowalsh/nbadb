from __future__ import annotations

from pathlib import Path
from typing import Annotated, Any

import typer

from nbadb.cli.app import app
from nbadb.contracts.assurance import (
    ADMISSION_NAME,
    GENERATION_INDEX_NAME,
    PROFILE_PRE_EXTRACTION,
    ContractAssuranceError,
    check_pre_extraction_assurance,
    generate_pre_extraction_assurance,
)

ProfileOption = Annotated[
    str,
    typer.Option(
        "--profile",
        help="Assurance profile to compile (currently: pre-extraction).",
    ),
]
EndpointAnalysisDocsRootOption = Annotated[
    Path,
    typer.Option(
        "--endpoint-analysis-docs-root",
        exists=True,
        file_okay=False,
        dir_okay=True,
        readable=True,
        resolve_path=True,
        help="Local exact-source nba_api checkout; no network access is performed.",
    ),
]
CheckOption = Annotated[
    bool,
    typer.Option(
        "--check",
        help="Generate twice in distinct fresh directories and compare semantic digests.",
    ),
]
OutputRootOption = Annotated[
    Path,
    typer.Option(
        "--output-root",
        help="Parent for brand-new assurance generation directories.",
    ),
]


@app.command("contract-assurance")
def contract_assurance(
    endpoint_analysis_docs_root: EndpointAnalysisDocsRootOption,
    profile: ProfileOption = PROFILE_PRE_EXTRACTION,
    check: CheckOption = False,
    output_root: OutputRootOption = Path("artifacts/contract-assurance/pre-extraction"),
) -> None:
    """Generate exact local contracts and report MODEL-GREEN separately.

    MODEL diagnostic, not a DATA gate: exit 0 means MODEL-GREEN, exit 1 means
    MODEL-RED or a local generation failure, exit 2 means an unsupported
    profile. The local DATA result is always UNPROVEN here -- hard DATA
    assurance comes only from the remote-readback and human-verification
    receipt chain, so no workflow may treat this command's exit status as
    publication DATA authority.
    """

    if profile != PROFILE_PRE_EXTRACTION:
        typer.echo(f"Unsupported assurance profile: {profile}", err=True)
        raise typer.Exit(2)
    try:
        result: dict[str, Any]
        if check:
            result = check_pre_extraction_assurance(
                endpoint_analysis_docs_root=endpoint_analysis_docs_root,
                output_root=output_root,
            )
        else:
            output_root.mkdir(parents=True, exist_ok=True)
            generation = generate_pre_extraction_assurance(
                endpoint_analysis_docs_root=endpoint_analysis_docs_root,
                output_dir=output_root / "generation",
            )
            result = {
                "assurance_location": "fresh_generation_directory",
                "generation_semantic_sha256": generation.semantic_sha256,
                "semantic_determinism": "NOT_CHECKED",
                "structural_generation": "GREEN",
                "model_green": generation.model_green,
                "model_status": "GREEN" if generation.model_green else "RED",
                "assurance_admission_location": ADMISSION_NAME,
                "assurance_admission_sha256": generation.admission_sha256,
                "assurance_admission_status": generation.admission_status,
                "assurance_generation_index_location": GENERATION_INDEX_NAME,
                "assurance_generation_index_sha256": generation.generation_index_sha256,
                "data_green": "UNPROVEN",
                "model_blockers": generation.manifest["model_blockers"],
            }
    except (ContractAssuranceError, OSError) as exc:
        typer.echo(f"Contract assurance failed: {exc}", err=True)
        raise typer.Exit(1) from None

    typer.echo(f"Structural generation: {result['structural_generation']}")
    typer.echo(f"Semantic determinism: {result['semantic_determinism']}")
    typer.echo(f"MODEL-GREEN: {result['model_status']}")
    typer.echo(f"DATA-GREEN: {result['data_green']}")
    typer.echo(f"Generation semantic SHA-256: {result['generation_semantic_sha256']}")
    typer.echo(f"Assurance location: {result['assurance_location']}")
    typer.echo(f"Assurance admission: {result['assurance_admission_location']}")
    typer.echo(f"Assurance admission SHA-256: {result['assurance_admission_sha256']}")
    typer.echo(f"Assurance admission status: {result['assurance_admission_status']}")
    typer.echo(f"Assurance generation index: {result['assurance_generation_index_location']}")
    typer.echo(f"Assurance generation index SHA-256: {result['assurance_generation_index_sha256']}")
    blockers = result["model_blockers"]
    typer.echo(f"MODEL blockers: {len(blockers)}")
    for blocker in blockers:
        typer.echo(
            "- "
            f"{blocker.get('child')}:{blocker.get('scope')}:{blocker.get('code')} "
            f"count={blocker.get('occurrence_count')}"
        )
    if result["model_green"] is not True:
        raise typer.Exit(1)
