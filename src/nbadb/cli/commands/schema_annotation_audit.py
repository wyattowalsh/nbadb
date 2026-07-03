from __future__ import annotations

from pathlib import Path
from typing import Annotated, cast

import typer

from nbadb.cli.app import app
from nbadb.core.schema_annotations import (
    Tier,
    schema_annotation_strict_issues,
    write_schema_annotation_artifacts,
)

TiersOption = Annotated[
    str,
    typer.Option(
        "--tiers",
        help="Comma-separated schema tiers to audit: raw,staging,star",
    ),
]
OutputDirOption = Annotated[
    Path,
    typer.Option("--output-dir", help="Directory for schema annotation audit artifacts"),
]
EndpointDocsRootOption = Annotated[
    Path | None,
    typer.Option(
        "--endpoint-analysis-docs-root",
        help="Optional nba_api repository/docs root for bronze contract fate coverage",
    ),
]
BronzeContractsPathOption = Annotated[
    Path | None,
    typer.Option(
        "--bronze-contracts-path",
        help="Optional nba-api-bronze-contracts.json artifact for full bronze field fate coverage",
    ),
]


def _parse_tiers(value: str) -> tuple[Tier, ...]:
    tiers = tuple(part.strip() for part in value.split(",") if part.strip())
    invalid = [tier for tier in tiers if tier not in {"raw", "staging", "star"}]
    if invalid:
        msg = f"Unsupported tier(s): {', '.join(invalid)}"
        raise typer.BadParameter(msg)
    if not tiers:
        raise typer.BadParameter("At least one tier is required")
    return cast("tuple[Tier, ...]", tiers)


@app.command("schema-annotation-audit")
def schema_annotation_audit(
    tiers: TiersOption = "raw,staging,star",
    output_dir: OutputDirOption = Path("artifacts/schema-annotation-audit"),
    endpoint_analysis_docs_root: EndpointDocsRootOption = None,
    bronze_contracts_path: BronzeContractsPathOption = None,
    require_bronze_contracts: Annotated[
        bool,
        typer.Option(
            "--require-bronze-contracts",
            help=(
                "Fail strict audits unless bronze contract evidence is present, enabled, "
                "and non-empty."
            ),
        ),
    ] = False,
    strict: Annotated[
        bool,
        typer.Option("--strict", help="Fail if any schema annotation gate has blocking issues"),
    ] = False,
) -> None:
    """Write raw-to-silver/gold fate and silver/gold annotation audit artifacts."""
    parsed_tiers = _parse_tiers(tiers)
    written = write_schema_annotation_artifacts(
        output_dir=output_dir,
        tiers=parsed_tiers,
        endpoint_analysis_docs_root=endpoint_analysis_docs_root,
        bronze_contracts_path=bronze_contracts_path,
        require_bronze_contracts=require_bronze_contracts,
    )
    for path in written.values():
        typer.echo(f"wrote: {path}")

    audit_path = written["schema_annotation_audit"]
    import json

    audit_payload = json.loads(audit_path.read_text(encoding="utf-8"))
    issues = schema_annotation_strict_issues({"schema_annotation_audit": audit_payload})
    if issues:
        typer.echo("Schema annotation audit issues: " + ", ".join(issues))
    else:
        typer.echo("Schema annotation audit passed.")

    if strict and issues:
        raise typer.Exit(1)
