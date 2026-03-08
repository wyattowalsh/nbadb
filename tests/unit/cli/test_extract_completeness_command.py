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
        {"covered": 5, "runtime_gap": 1, "staging_only": 1, "extractor_only": 0},
    )
    with patch(_GENERATOR_PATH) as mock_generator:
        mock_generator.return_value.write.return_value = written
        result = runner.invoke(app, ["extract-completeness", "--output-dir", str(tmp_path)])

    assert result.exit_code == 0, result.output
    mock_generator.return_value.write.assert_called_once_with(output_dir=tmp_path)
    assert "covered=5" in result.output
    assert "runtime_gap=1" in result.output
    assert "staging_only=1" in result.output
    assert "extractor_only=0" in result.output
    assert "non_covered=2" in result.output


def test_extract_completeness_require_full_exits_when_noncovered(tmp_path: Path) -> None:
    written = _artifact_paths(
        tmp_path,
        {"covered": 4, "runtime_gap": 1, "staging_only": 0, "extractor_only": 1},
    )
    with patch(_GENERATOR_PATH) as mock_generator:
        mock_generator.return_value.write.return_value = written
        result = runner.invoke(app, ["extract-completeness", "--require-full"])

    assert result.exit_code == 1
    assert "require-full check failed" in result.output
