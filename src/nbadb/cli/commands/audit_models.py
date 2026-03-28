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


@app.command("audit-models")
def audit_models(
    mode: ModeOption = AuditMode.INVENTORY,
    strictness: StrictnessOption = AuditStrictness.CONSISTENCY,
    output_dir: OutputDirOption = None,
    baseline: BaselineOption = None,
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
    summary = payload["summary"]
    inventory = summary["inventory"]

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

    baseline_comparison = payload.get("baseline_comparison")
    if baseline_comparison is not None:
        typer.echo(
            "Baseline comparison: "
            f"regression_detected={baseline_comparison.get('regression_detected', False)} "
            f"new_problem_keys={len(baseline_comparison.get('new_problem_keys', []))} "
            f"resolved_problem_keys={len(baseline_comparison.get('resolved_problem_keys', []))}"
        )

    typer.echo(f"Artifacts dir: {written['inventory'].parent}")
