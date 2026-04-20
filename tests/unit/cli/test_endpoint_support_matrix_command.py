from __future__ import annotations

import json
from typing import TYPE_CHECKING
from unittest.mock import patch

from typer.testing import CliRunner

from nbadb.cli.app import app

if TYPE_CHECKING:
    from pathlib import Path

runner = CliRunner()

_GENERATOR_PATH = "nbadb.cli.commands.endpoint_support_matrix.EndpointCoverageGenerator"


def _artifact_paths(tmp_path: Path, summary: dict[str, object]) -> dict[str, Path]:
    matrix_path = tmp_path / "endpoint-coverage-matrix.json"
    summary_path = tmp_path / "endpoint-coverage-summary.json"
    report_path = tmp_path / "endpoint-coverage-report.md"
    support_matrix_path = tmp_path / "endpoint-support-matrix.json"
    support_summary_path = tmp_path / "endpoint-support-summary.json"
    support_report_path = tmp_path / "endpoint-support-report.md"

    matrix_path.write_text('{"matrix": []}\n', encoding="utf-8")
    summary_path.write_text('{"coverage": {}}\n', encoding="utf-8")
    report_path.write_text("# Endpoint Coverage Report\n", encoding="utf-8")
    support_matrix_path.write_text('{"matrix": []}\n', encoding="utf-8")
    support_summary_path.write_text(json.dumps(summary) + "\n", encoding="utf-8")
    support_report_path.write_text("# Endpoint Support Matrix\n", encoding="utf-8")
    return {
        "matrix": matrix_path,
        "summary": summary_path,
        "report": report_path,
        "support_matrix": support_matrix_path,
        "support_summary": support_summary_path,
        "support_report": support_report_path,
    }


def test_endpoint_support_matrix_prints_summary_and_uses_output_dir(tmp_path: Path) -> None:
    written = _artifact_paths(
        tmp_path,
        {
            "endpoint_count": 7,
            "complete_endpoint_count": 2,
            "partial_endpoint_count": 1,
            "gap_endpoint_count": 4,
            "season_type_contract_open_count": 2,
            "season_type_contract_untracked_count": 1,
            "execution_semantics_breakdown": {
                "historical_backfill": 3,
                "reference_snapshot": 2,
                "live_snapshot": 2,
            },
            "gap_breakdown": {
                "input_schema_missing": 1,
                "snapshot_staging_missing": 2,
                "transform_contract_missing": 3,
            },
        },
    )
    with patch(_GENERATOR_PATH) as mock_generator:
        mock_generator.return_value.write.return_value = written
        result = runner.invoke(app, ["endpoint-support-matrix", "--output-dir", str(tmp_path)])

    assert result.exit_code == 0, result.output
    mock_generator.return_value.write.assert_called_once_with(output_dir=tmp_path)
    assert "endpoints=7" in result.output
    assert "complete=2" in result.output
    assert "partial=1" in result.output
    assert "gaps=4" in result.output
    assert "season_type_open=2" in result.output
    assert "season_type_untracked=1" in result.output
    assert "historical_backfill=3" in result.output
    assert "reference_snapshot=2" in result.output
    assert "live_snapshot=2" in result.output
    assert "input_schema_missing=1" in result.output
    assert "snapshot_staging_missing=2" in result.output
    assert "transform_contract_missing=3" in result.output


def test_endpoint_support_matrix_require_complete_exits_when_gaps_exist(tmp_path: Path) -> None:
    written = _artifact_paths(
        tmp_path,
        {
            "endpoint_count": 4,
            "complete_endpoint_count": 1,
            "partial_endpoint_count": 0,
            "gap_endpoint_count": 3,
            "season_type_contract_open_count": 0,
            "season_type_contract_untracked_count": 0,
            "execution_semantics_breakdown": {},
            "gap_breakdown": {},
        },
    )
    with patch(_GENERATOR_PATH) as mock_generator:
        mock_generator.return_value.write.return_value = written
        result = runner.invoke(app, ["endpoint-support-matrix", "--require-complete"])

    assert result.exit_code == 1
    assert "require-complete check failed" in result.output


def test_endpoint_support_matrix_require_complete_exits_when_partial_remains(
    tmp_path: Path,
) -> None:
    written = _artifact_paths(
        tmp_path,
        {
            "endpoint_count": 4,
            "complete_endpoint_count": 1,
            "partial_endpoint_count": 1,
            "gap_endpoint_count": 0,
            "season_type_contract_open_count": 1,
            "season_type_contract_untracked_count": 1,
            "execution_semantics_breakdown": {},
            "gap_breakdown": {},
        },
    )
    with patch(_GENERATOR_PATH) as mock_generator:
        mock_generator.return_value.write.return_value = written
        result = runner.invoke(app, ["endpoint-support-matrix", "--require-complete"])

    assert result.exit_code == 1
    assert "require-complete check failed" in result.output


def test_endpoint_support_matrix_help_mentions_exclusions() -> None:
    result = runner.invoke(app, ["endpoint-support-matrix", "--help"])

    assert result.exit_code == 0
    assert "explicitly excluded" in result.output


def test_endpoint_support_matrix_require_season_type_contract_exits_when_untracked(
    tmp_path: Path,
) -> None:
    written = _artifact_paths(
        tmp_path,
        {
            "endpoint_count": 4,
            "complete_endpoint_count": 2,
            "partial_endpoint_count": 2,
            "gap_endpoint_count": 0,
            "season_type_contract_open_count": 2,
            "season_type_contract_untracked_count": 2,
            "execution_semantics_breakdown": {},
            "gap_breakdown": {},
        },
    )
    with patch(_GENERATOR_PATH) as mock_generator:
        mock_generator.return_value.write.return_value = written
        result = runner.invoke(
            app,
            ["endpoint-support-matrix", "--require-season-type-contract"],
        )

    assert result.exit_code == 1
    assert "require-season-type-contract check failed" in result.output
