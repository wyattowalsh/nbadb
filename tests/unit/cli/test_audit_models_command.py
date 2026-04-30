from __future__ import annotations

import json
from typing import TYPE_CHECKING
from unittest.mock import patch

if TYPE_CHECKING:
    from pathlib import Path

from typer.testing import CliRunner

from nbadb.cli.app import app
from nbadb.core.model_audit import AuditFailureError, AuditMode, AuditStrictness

runner = CliRunner()

_ENGINE_PATH = "nbadb.cli.commands.audit_models.ModelAuditEngine"


def _write_inventory_artifact(
    directory: Path,
    *,
    baseline_comparison: dict[str, object] | None = None,
    result_table_summary: dict[str, object] | None = None,
) -> dict[str, Path]:
    inventory_path = directory / "inventory.json"
    matrix_path = directory / "matrix.json"
    report_path = directory / "report.md"
    result_table_inventory_path = directory / "result-table-inventory.json"

    payload = {
        "summary": {
            "inventory": {
                "runtime_stats_surface_count": 137,
                "runtime_static_surface_count": 2,
                "runtime_live_surface_count": 4,
                "staging_entry_count": 402,
                "runtime_transform_output_count": 176,
            },
            "problem_count": 12,
            "discovery_issue_count": 1,
            "result_table_contract": {
                "passes": True,
                "failure_count": 0,
                "failure_breakdown": {},
                "failure_keys": [],
            },
        },
        "baseline_comparison": baseline_comparison,
    }
    result_table_payload = {
        "summary": result_table_summary
        or {
            "row_count": 176,
            "ownership_status_breakdown": {
                "modeled": 120,
                "passthrough_only": 40,
                "compatibility_reference_only": 10,
                "excluded": 4,
                "deprecated": 2,
            },
            "contract_strength_breakdown": {
                "explicit": 174,
                "deprecated": 2,
            },
            "contract": {
                "passes": True,
                "failure_count": 0,
                "failure_breakdown": {},
                "failure_keys": [],
            },
        }
    }

    inventory_path.write_text(json.dumps(payload) + "\n", encoding="utf-8")
    matrix_path.write_text('{"matrix": []}\n', encoding="utf-8")
    report_path.write_text("# Model Audit Report\n", encoding="utf-8")
    result_table_inventory_path.write_text(
        json.dumps(result_table_payload) + "\n",
        encoding="utf-8",
    )
    return {
        "inventory": inventory_path,
        "matrix": matrix_path,
        "report": report_path,
        "result_table_inventory": result_table_inventory_path,
    }


def test_audit_models_prints_summary_and_forwards_options(tmp_path: Path) -> None:
    written = _write_inventory_artifact(
        tmp_path,
        baseline_comparison={
            "regression_detected": False,
            "new_problem_keys": [],
            "resolved_problem_keys": ["RuntimeSurface:stats:foo:source_gap"],
            "new_result_table_failure_keys": [],
        },
    )
    baseline_path = tmp_path / "baseline.json"
    baseline_path.write_text("{}\n", encoding="utf-8")

    with patch(_ENGINE_PATH) as mock_engine:
        mock_engine.return_value.write.return_value = written
        result = runner.invoke(
            app,
            [
                "audit-models",
                "--mode",
                "inventory",
                "--strictness",
                "no-regressions",
                "--output-dir",
                str(tmp_path),
                "--baseline",
                str(baseline_path),
            ],
        )

    assert result.exit_code == 0, result.output
    mock_engine.return_value.write.assert_called_once_with(
        mode=AuditMode.INVENTORY,
        strictness=AuditStrictness.NO_REGRESSIONS,
        output_dir=tmp_path,
        baseline_path=baseline_path,
    )
    assert "runtime_stats=137" in result.output
    assert "runtime_static=2" in result.output
    assert "runtime_live=4" in result.output
    assert "staging_entries=402" in result.output
    assert "transform_outputs=176" in result.output
    assert "problem_count=12" in result.output
    assert "discovery_issues=1" in result.output
    assert "Result-table contract:" in result.output
    assert "modeled=120" in result.output
    assert "passthrough_only=40" in result.output
    assert "compatibility_reference_only=10" in result.output
    assert "excluded=4" in result.output
    assert "deprecated=2" in result.output
    assert "unowned=0" in result.output
    assert "missing=0" in result.output
    assert "weakly_classified=0" in result.output
    assert "failures=0" in result.output
    assert "regression_detected=False" in result.output
    assert "resolved_problem_keys=1" in result.output
    assert "new_result_table_failures=0" in result.output


def test_audit_models_exits_nonzero_on_audit_failure() -> None:
    with patch(_ENGINE_PATH) as mock_engine:
        mock_engine.return_value.write.side_effect = AuditFailureError("zero-gaps check failed")
        result = runner.invoke(app, ["audit-models", "--strictness", "zero-gaps"])

    assert result.exit_code == 1
    assert "zero-gaps check failed" in result.output


def test_audit_models_require_result_table_contract_exits_when_failures_remain(
    tmp_path: Path,
) -> None:
    written = _write_inventory_artifact(
        tmp_path,
        result_table_summary={
            "row_count": 3,
            "ownership_status_breakdown": {
                "modeled": 1,
                "unowned": 1,
                "missing": 1,
            },
            "contract_strength_breakdown": {
                "explicit": 1,
                "unowned": 1,
                "missing": 1,
            },
            "contract": {
                "passes": False,
                "failure_count": 2,
                "failure_breakdown": {"missing": 1, "unowned": 1},
                "failure_keys": ["foo:0:runtime_only:missing", "bar:1:stg_bar:unowned"],
            },
        },
    )
    with patch(_ENGINE_PATH) as mock_engine:
        mock_engine.return_value.write.return_value = written
        result = runner.invoke(app, ["audit-models", "--require-result-table-contract"])

    assert result.exit_code == 1
    assert "require-result-table-contract check failed" in result.output
