from __future__ import annotations

import json
from typing import TYPE_CHECKING
from unittest.mock import patch

from typer.testing import CliRunner

from nbadb.cli.app import app

if TYPE_CHECKING:
    from pathlib import Path

runner = CliRunner()

_GENERATOR_PATH = "nbadb.cli.commands.endpoint_adequacy_scorecard.EndpointCoverageGenerator"


def _artifact_paths(tmp_path: Path, summary: dict[str, object]) -> dict[str, Path]:
    scorecard_path = tmp_path / "endpoint-adequacy-scorecard.json"
    report_path = tmp_path / "endpoint-adequacy-scorecard-report.md"

    scorecard_path.write_text(json.dumps(summary) + "\n", encoding="utf-8")
    report_path.write_text("# Endpoint Adequacy Scorecard\n", encoding="utf-8")
    return {
        "endpoint_adequacy_scorecard": scorecard_path,
        "endpoint_adequacy_report": report_path,
    }


def test_endpoint_adequacy_scorecard_prints_summary_and_uses_output_dir(
    tmp_path: Path,
) -> None:
    written = _artifact_paths(
        tmp_path,
        {
            "scorecard": [],
            "summary": {
                "endpoint_count": 4,
                "adequate_endpoint_count": 2,
                "coverage_gap_endpoint_count": 1,
                "contract_gap_endpoint_count": 1,
                "downstream_modeled_endpoint_count": 1,
                "downstream_passthrough_only_endpoint_count": 1,
                "downstream_compatibility_reference_only_endpoint_count": 1,
                "downstream_excluded_endpoint_count": 1,
                "downstream_unowned_endpoint_count": 0,
                "downstream_not_applicable_endpoint_count": 0,
                "adequacy_status_breakdown": {"adequate": 2, "gap": 1, "runtime_gap": 1},
                "downstream_status_breakdown": {
                    "modeled": 1,
                    "passthrough_only": 1,
                    "compatibility_reference_only": 1,
                    "excluded": 1,
                    "unowned": 0,
                    "not_applicable": 0,
                },
            },
        },
    )
    with patch(_GENERATOR_PATH) as mock_generator:
        mock_generator.return_value.write_endpoint_adequacy_scorecard.return_value = written
        result = runner.invoke(app, ["endpoint-adequacy-scorecard", "--output-dir", str(tmp_path)])

    assert result.exit_code == 0, result.output
    mock_generator.return_value.write_endpoint_adequacy_scorecard.assert_called_once_with(
        output_dir=tmp_path
    )
    assert "endpoints=4" in result.output
    assert "adequate=2" in result.output
    assert "coverage_gaps=1" in result.output
    assert "contract_gaps=1" in result.output
    assert "downstream_modeled=1" in result.output
    assert "downstream_passthrough=1" in result.output
    assert "downstream_compatibility_reference=1" in result.output
    assert "downstream_excluded=1" in result.output
    assert "downstream_unowned=0" in result.output
