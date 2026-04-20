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
) -> dict[str, Path]:
    inventory_path = directory / "inventory.json"
    matrix_path = directory / "matrix.json"
    report_path = directory / "report.md"

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
        },
        "baseline_comparison": baseline_comparison,
    }

    inventory_path.write_text(json.dumps(payload) + "\n", encoding="utf-8")
    matrix_path.write_text('{"matrix": []}\n', encoding="utf-8")
    report_path.write_text("# Model Audit Report\n", encoding="utf-8")
    return {
        "inventory": inventory_path,
        "matrix": matrix_path,
        "report": report_path,
    }


def test_audit_models_prints_summary_and_forwards_options(tmp_path: Path) -> None:
    written = _write_inventory_artifact(
        tmp_path,
        baseline_comparison={
            "regression_detected": False,
            "new_problem_keys": [],
            "resolved_problem_keys": ["RuntimeSurface:stats:foo:source_gap"],
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
    assert "regression_detected=False" in result.output
    assert "resolved_problem_keys=1" in result.output


def test_audit_models_exits_nonzero_on_audit_failure() -> None:
    with patch(_ENGINE_PATH) as mock_engine:
        mock_engine.return_value.write.side_effect = AuditFailureError("zero-gaps check failed")
        result = runner.invoke(app, ["audit-models", "--strictness", "zero-gaps"])

    assert result.exit_code == 1
    assert "zero-gaps check failed" in result.output
