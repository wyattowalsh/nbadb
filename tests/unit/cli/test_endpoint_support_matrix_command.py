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
    extraction_matrix_path = tmp_path / "endpoint-extraction-matrix.json"
    extraction_summary_path = tmp_path / "endpoint-extraction-summary.json"
    extraction_report_path = tmp_path / "endpoint-extraction-report.md"
    full_extraction_definition_path = tmp_path / "full-extraction-definition.json"

    matrix_path.write_text('{"matrix": []}\n', encoding="utf-8")
    summary_path.write_text('{"coverage": {}}\n', encoding="utf-8")
    report_path.write_text("# Endpoint Coverage Report\n", encoding="utf-8")
    support_matrix_path.write_text('{"matrix": []}\n', encoding="utf-8")
    support_summary_path.write_text(json.dumps(summary) + "\n", encoding="utf-8")
    support_report_path.write_text("# Endpoint Support Matrix\n", encoding="utf-8")
    extraction_matrix_path.write_text('{"matrix": []}\n', encoding="utf-8")
    extraction_summary_path.write_text(json.dumps(summary) + "\n", encoding="utf-8")
    extraction_report_path.write_text("# Endpoint Extraction Contract\n", encoding="utf-8")
    full_extraction_definition_path.write_text("{}\n", encoding="utf-8")
    return {
        "matrix": matrix_path,
        "summary": summary_path,
        "report": report_path,
        "support_matrix": support_matrix_path,
        "support_summary": support_summary_path,
        "support_report": support_report_path,
        "extraction_matrix": extraction_matrix_path,
        "extraction_summary": extraction_summary_path,
        "extraction_report": extraction_report_path,
        "full_extraction_definition": full_extraction_definition_path,
    }


def test_endpoint_support_matrix_prints_summary_and_uses_output_dir(tmp_path: Path) -> None:
    written = _artifact_paths(
        tmp_path,
        {
            "endpoint_count": 7,
            "in_scope_endpoint_count": 5,
            "extractable_endpoint_count": 2,
            "partial_endpoint_count": 1,
            "blocked_endpoint_count": 2,
            "excluded_endpoint_count": 2,
            "season_type_contract_open_count": 2,
            "ready_for_full_backfill": False,
            "execution_semantics_breakdown": {
                "historical_backfill": 3,
                "reference_snapshot": 2,
                "live_snapshot": 2,
            },
            "extraction_gap_breakdown": {
                "input_schema_missing": 1,
                "season_type_contract_untracked": 2,
            },
            "explicit_exclusion_breakdown": {"intentionally_deferred": 2},
        },
    )
    with patch(_GENERATOR_PATH) as mock_generator:
        mock_generator.return_value.write.return_value = written
        result = runner.invoke(app, ["endpoint-support-matrix", "--output-dir", str(tmp_path)])

    assert result.exit_code == 0, result.output
    mock_generator.return_value.write.assert_called_once_with(output_dir=tmp_path)
    assert "endpoints=7" in result.output
    assert "in_scope=5" in result.output
    assert "extractable=2" in result.output
    assert "partial=1" in result.output
    assert "blocked=2" in result.output
    assert "excluded=2" in result.output
    assert "season_type_open=2" in result.output
    assert "ready_for_full_backfill=False" in result.output
    assert "historical_backfill=3" in result.output
    assert "reference_snapshot=2" in result.output
    assert "live_snapshot=2" in result.output
    assert "input_schema_missing=1" in result.output
    assert "season_type_contract_untracked=2" in result.output
    assert "intentionally_deferred=2" in result.output


def test_endpoint_support_matrix_require_complete_exits_when_gaps_exist(tmp_path: Path) -> None:
    written = _artifact_paths(
        tmp_path,
        {
            "endpoint_count": 4,
            "in_scope_endpoint_count": 4,
            "extractable_endpoint_count": 1,
            "partial_endpoint_count": 0,
            "blocked_endpoint_count": 3,
            "excluded_endpoint_count": 0,
            "season_type_contract_open_count": 0,
            "ready_for_full_backfill": False,
            "execution_semantics_breakdown": {},
            "extraction_gap_breakdown": {},
            "explicit_exclusion_breakdown": {},
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
            "in_scope_endpoint_count": 4,
            "extractable_endpoint_count": 1,
            "partial_endpoint_count": 1,
            "blocked_endpoint_count": 0,
            "excluded_endpoint_count": 0,
            "season_type_contract_open_count": 1,
            "ready_for_full_backfill": False,
            "execution_semantics_breakdown": {},
            "extraction_gap_breakdown": {},
            "explicit_exclusion_breakdown": {},
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
    assert "excluded surfaces" in result.output.lower()


def test_endpoint_support_matrix_require_season_type_contract_exits_when_untracked(
    tmp_path: Path,
) -> None:
    written = _artifact_paths(
        tmp_path,
        {
            "endpoint_count": 4,
            "in_scope_endpoint_count": 4,
            "extractable_endpoint_count": 2,
            "partial_endpoint_count": 2,
            "blocked_endpoint_count": 0,
            "excluded_endpoint_count": 0,
            "season_type_contract_open_count": 2,
            "ready_for_full_backfill": False,
            "execution_semantics_breakdown": {},
            "extraction_gap_breakdown": {},
            "explicit_exclusion_breakdown": {},
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
