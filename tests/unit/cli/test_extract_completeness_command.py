from __future__ import annotations

import json
from typing import TYPE_CHECKING
from unittest.mock import patch

from typer.testing import CliRunner

from nbadb.cli.app import app

if TYPE_CHECKING:
    from pathlib import Path

runner = CliRunner()

_GENERATOR_PATH = "nbadb.cli.commands.extract_completeness.EndpointCoverageGenerator"


def _artifact_paths(tmp_path: Path, coverage: dict[str, int]) -> dict[str, Path]:
    matrix_path = tmp_path / "endpoint-coverage-matrix.json"
    summary_path = tmp_path / "endpoint-coverage-summary.json"
    report_path = tmp_path / "endpoint-coverage-report.md"
    extraction_summary_path = tmp_path / "endpoint-extraction-summary.json"
    extraction_report_path = tmp_path / "endpoint-extraction-report.md"
    full_extraction_definition_path = tmp_path / "full-extraction-definition.json"

    matrix_path.write_text('{"matrix": []}\n', encoding="utf-8")
    summary_path.write_text(json.dumps({"coverage": coverage}) + "\n", encoding="utf-8")
    report_path.write_text("# Endpoint Coverage Report\n", encoding="utf-8")
    extraction_summary_path.write_text("{}\n", encoding="utf-8")
    extraction_report_path.write_text("# Endpoint Extraction Contract\n", encoding="utf-8")
    full_extraction_definition_path.write_text("{}\n", encoding="utf-8")
    return {
        "matrix": matrix_path,
        "summary": summary_path,
        "report": report_path,
        "extraction_summary": extraction_summary_path,
        "extraction_report": extraction_report_path,
        "full_extraction_definition": full_extraction_definition_path,
    }


def test_extract_completeness_prints_summary_and_uses_output_dir(tmp_path: Path) -> None:
    written = _artifact_paths(
        tmp_path,
        {
            "covered": 5,
            "runtime_gap": 1,
            "staging_only": 1,
            "extractor_only": 0,
            "source_only": 0,
        },
    )
    summary_payload = {
        "coverage": {
            "covered": 5,
            "runtime_gap": 1,
            "staging_only": 1,
            "extractor_only": 0,
            "source_only": 0,
        },
        "extraction_contract": {
            "in_scope_endpoint_count": 6,
            "extractable_endpoint_count": 4,
            "partial_endpoint_count": 1,
            "blocked_endpoint_count": 1,
            "excluded_endpoint_count": 2,
            "season_type_contract_open_count": 1,
            "ready_for_full_backfill": False,
        },
        "model_ownership": {
            "stats_endpoint_count": 4,
            "analytically_modeled_stats_endpoints": 1,
            "passthrough_only_stats_endpoints": 2,
            "compatibility_reference_only_stats_endpoints": 1,
            "model_excluded_stats_endpoints": 1,
            "model_unowned_stats_endpoints": 0,
            "staging_entry_count": 9,
            "analytically_modeled_staging_entries": 2,
            "passthrough_only_staging_entries": 4,
            "compatibility_reference_only_staging_entries": 1,
            "model_excluded_staging_entries": 1,
            "model_unowned_staging_entries": 1,
        },
        "star_schema_coverage": {
            "transform_output_count": 5,
            "schema_backed_transform_outputs": 3,
            "schema_missing_transform_outputs": 2,
            "schema_only_table_count": 1,
        },
    }
    written["summary"].write_text(json.dumps(summary_payload) + "\n", encoding="utf-8")
    with patch(_GENERATOR_PATH) as mock_generator:
        mock_generator.return_value.build_artifacts.return_value = {
            "summary": summary_payload,
        }
        mock_generator.return_value.write_artifacts.return_value = written
        result = runner.invoke(app, ["extract-completeness", "--output-dir", str(tmp_path)])

    assert result.exit_code == 0, result.output
    mock_generator.return_value.build_artifacts.assert_called_once_with()
    mock_generator.return_value.write_artifacts.assert_called_once()
    assert "in_scope=6" in result.output
    assert "extractable=4" in result.output
    assert "partial=1" in result.output
    assert "blocked=1" in result.output
    assert "excluded=2" in result.output
    assert "season_type_open=1" in result.output
    assert "ready_for_full_backfill=False" in result.output
    assert "stats_endpoints=4" in result.output
    assert "modeled_endpoints=1" in result.output
    assert "passthrough_endpoints=2" in result.output
    assert "compatibility_reference_endpoints=1" in result.output
    assert "model_excluded_endpoints=1" in result.output
    assert "model_unowned_endpoints=0" in result.output
    assert "staging_entries=9" in result.output
    assert "modeled=2" in result.output
    assert "passthrough=4" in result.output
    assert "compatibility_reference=1" in result.output
    assert "model_excluded=1" in result.output
    assert "model_unowned=1" in result.output
    assert "Star schema coverage:" in result.output
    assert "transform_outputs=5" in result.output
    assert "schema_backed=3" in result.output
    assert "schema_missing=2" in result.output
    assert "schema_only=1" in result.output


def test_extract_completeness_require_full_exits_when_noncovered(tmp_path: Path) -> None:
    written = _artifact_paths(
        tmp_path,
        {
            "covered": 4,
            "runtime_gap": 1,
            "staging_only": 0,
            "extractor_only": 0,
            "source_only": 1,
        },
    )
    with patch(_GENERATOR_PATH) as mock_generator:
        mock_generator.return_value.build_artifacts.return_value = {
            "summary": {
                "coverage": {
                    "covered": 4,
                    "runtime_gap": 1,
                    "staging_only": 0,
                    "extractor_only": 0,
                    "source_only": 1,
                },
                "extraction_contract": {
                    "in_scope_endpoint_count": 5,
                    "extractable_endpoint_count": 3,
                    "partial_endpoint_count": 1,
                    "blocked_endpoint_count": 1,
                    "excluded_endpoint_count": 0,
                    "season_type_contract_open_count": 1,
                    "ready_for_full_backfill": False,
                },
            }
        }
        mock_generator.return_value.write_artifacts.return_value = written
        result = runner.invoke(app, ["extract-completeness", "--require-full"])

    assert result.exit_code == 1
    assert "require-full check failed" in result.output


def test_extract_completeness_require_model_contract_exits_when_unowned(tmp_path: Path) -> None:
    written = _artifact_paths(
        tmp_path,
        {
            "covered": 5,
            "runtime_gap": 0,
            "staging_only": 0,
            "extractor_only": 0,
            "source_only": 0,
        },
    )
    summary_payload = {
        "coverage": {
            "covered": 5,
            "runtime_gap": 0,
            "staging_only": 0,
            "extractor_only": 0,
            "source_only": 0,
        },
        "extraction_contract": {
            "in_scope_endpoint_count": 5,
            "extractable_endpoint_count": 5,
            "partial_endpoint_count": 0,
            "blocked_endpoint_count": 0,
            "excluded_endpoint_count": 0,
            "season_type_contract_open_count": 0,
            "ready_for_full_backfill": True,
        },
        "model_ownership": {
            "stats_endpoint_count": 5,
            "analytically_modeled_stats_endpoints": 3,
            "passthrough_only_stats_endpoints": 1,
            "compatibility_reference_only_stats_endpoints": 0,
            "model_excluded_stats_endpoints": 0,
            "model_unowned_stats_endpoints": 1,
            "staging_entry_count": 9,
            "analytically_modeled_staging_entries": 5,
            "passthrough_only_staging_entries": 2,
            "compatibility_reference_only_staging_entries": 0,
            "model_excluded_staging_entries": 0,
            "model_unowned_staging_entries": 2,
        },
    }
    written["summary"].write_text(json.dumps(summary_payload) + "\n", encoding="utf-8")
    with patch(_GENERATOR_PATH) as mock_generator:
        mock_generator.return_value.build_artifacts.return_value = {
            "summary": summary_payload,
        }
        mock_generator.return_value.write_artifacts.return_value = written
        result = runner.invoke(app, ["extract-completeness", "--require-model-contract"])

    assert result.exit_code == 1
    assert "require-model-contract check failed" in result.output
