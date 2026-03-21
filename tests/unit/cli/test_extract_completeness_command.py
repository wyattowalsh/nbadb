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

    matrix_path.write_text('{"matrix": []}\n', encoding="utf-8")
    summary_path.write_text(json.dumps({"coverage": coverage}) + "\n", encoding="utf-8")
    report_path.write_text("# Endpoint Coverage Report\n", encoding="utf-8")
    return {"matrix": matrix_path, "summary": summary_path, "report": report_path}


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
        "model_ownership": {
            "stats_endpoint_count": 4,
            "transform_owned_stats_endpoints": 3,
            "model_excluded_stats_endpoints": 1,
            "model_unowned_stats_endpoints": 0,
            "staging_entry_count": 9,
            "transform_owned_staging_entries": 7,
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
        mock_generator.return_value.write.return_value = written
        result = runner.invoke(app, ["extract-completeness", "--output-dir", str(tmp_path)])

    assert result.exit_code == 0, result.output
    mock_generator.return_value.write.assert_called_once_with(output_dir=tmp_path)
    assert "covered=5" in result.output
    assert "runtime_gap=1" in result.output
    assert "staging_only=1" in result.output
    assert "extractor_only=0" in result.output
    assert "source_only=0" in result.output
    assert "non_covered=2" in result.output
    assert "stats_endpoints=4" in result.output
    assert "transform_owned_endpoints=3" in result.output
    assert "model_excluded_endpoints=1" in result.output
    assert "model_unowned_endpoints=0" in result.output
    assert "staging_entries=9" in result.output
    assert "transform_owned=7" in result.output
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
        mock_generator.return_value.write.return_value = written
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
        "model_ownership": {
            "stats_endpoint_count": 5,
            "transform_owned_stats_endpoints": 4,
            "model_excluded_stats_endpoints": 0,
            "model_unowned_stats_endpoints": 1,
            "staging_entry_count": 9,
            "transform_owned_staging_entries": 7,
            "model_excluded_staging_entries": 0,
            "model_unowned_staging_entries": 2,
        },
    }
    written["summary"].write_text(json.dumps(summary_payload) + "\n", encoding="utf-8")
    with patch(_GENERATOR_PATH) as mock_generator:
        mock_generator.return_value.write.return_value = written
        result = runner.invoke(app, ["extract-completeness", "--require-model-contract"])

    assert result.exit_code == 1
    assert "require-model-contract check failed" in result.output
