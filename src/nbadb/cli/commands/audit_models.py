from __future__ import annotations

import json
from pathlib import Path
from typing import Annotated

import typer

from nbadb.cli.app import app
from nbadb.core.model_audit import AuditFailureError, AuditMode, AuditStrictness, ModelAuditEngine

ModeOption = Annotated[
    AuditMode,
    typer.Option(
        "--mode",
        help="Audit execution mode: inventory only, live probe, sampled build, or full.",
        case_sensitive=False,
    ),
]
StrictnessOption = Annotated[
    AuditStrictness,
    typer.Option(
        "--strictness",
        help="Enforcement level for the audit: consistency, no-regressions, or zero-gaps.",
        case_sensitive=False,
    ),
]
OutputDirOption = Annotated[
    Path | None,
    typer.Option("--output-dir", "-o", help="Output directory for model audit artifacts."),
]
BaselineOption = Annotated[
    Path | None,
    typer.Option(
        "--baseline",
        help="Baseline inventory summary or inventory artifact used for no-regressions checks.",
    ),
]
RequireResultTableContractOption = Annotated[
    bool,
    typer.Option(
        "--require-result-table-contract",
        help=(
            "Exit non-zero when any runtime result table remains missing, unowned, or only "
            "weakly classified."
        ),
    ),
]


@app.command("audit-models")
def audit_models(
    mode: ModeOption = AuditMode.INVENTORY,
    strictness: StrictnessOption = AuditStrictness.CONSISTENCY,
    output_dir: OutputDirOption = None,
    baseline: BaselineOption = None,
    require_result_table_contract: RequireResultTableContractOption = False,
) -> None:
    """Generate end-to-end model audit artifacts for nba_api coverage."""
    engine = ModelAuditEngine()
    try:
        written = engine.write(
            mode=mode,
            strictness=strictness,
            output_dir=output_dir,
            baseline_path=baseline,
        )
    except AuditFailureError as exc:
        typer.echo(str(exc), err=True)
        raise typer.Exit(1) from exc

    payload = json.loads(written["inventory"].read_text(encoding="utf-8"))
    result_table_payload = json.loads(written["result_table_inventory"].read_text(encoding="utf-8"))
    summary = payload["summary"]
    inventory = summary["inventory"]
    result_table_summary = result_table_payload["summary"]
    result_table_contract = result_table_summary.get("contract", {})
    ownership = result_table_summary.get("ownership_status_breakdown", {})
    contract_strength = result_table_summary.get("contract_strength_breakdown", {})

    typer.echo(
        "Model audit: "
        f"mode={mode.value} "
        f"strictness={strictness.value} "
        f"runtime_stats={inventory.get('runtime_stats_surface_count', 0)} "
        f"runtime_static={inventory.get('runtime_static_surface_count', 0)} "
        f"runtime_live={inventory.get('runtime_live_surface_count', 0)} "
        f"staging_entries={inventory.get('staging_entry_count', 0)} "
        f"transform_outputs={inventory.get('runtime_transform_output_count', 0)} "
        f"problem_count={summary.get('problem_count', 0)} "
        f"discovery_issues={summary.get('discovery_issue_count', 0)}"
    )
    typer.echo(
        "Result-table contract: "
        f"rows={result_table_summary.get('row_count', 0)} "
        f"modeled={ownership.get('modeled', 0)} "
        f"passthrough_only={ownership.get('passthrough_only', 0)} "
        "compatibility_reference_only="
        f"{ownership.get('compatibility_reference_only', 0)} "
        f"excluded={ownership.get('excluded', 0)} "
        f"deprecated={ownership.get('deprecated', 0)} "
        f"unowned={ownership.get('unowned', 0)} "
        f"missing={ownership.get('missing', 0)} "
        "weakly_classified="
        f"{contract_strength.get('weakly_classified', 0)} "
        f"failures={result_table_contract.get('failure_count', 0)}"
    )

    baseline_comparison = payload.get("baseline_comparison")
    if baseline_comparison is not None:
        typer.echo(
            "Baseline comparison: "
            f"regression_detected={baseline_comparison.get('regression_detected', False)} "
            f"new_problem_keys={len(baseline_comparison.get('new_problem_keys', []))} "
            f"resolved_problem_keys={len(baseline_comparison.get('resolved_problem_keys', []))} "
            "new_result_table_failures="
            f"{len(baseline_comparison.get('new_result_table_failure_keys', []))}"
        )

    typer.echo(f"Artifacts dir: {written['inventory'].parent}")
    if require_result_table_contract and int(result_table_contract.get("failure_count", 0)) > 0:
        typer.echo(
            "require-result-table-contract check failed: result-table contract failures remain",
            err=True,
        )
        raise typer.Exit(1)
