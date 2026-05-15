from __future__ import annotations

from types import SimpleNamespace
from typing import TYPE_CHECKING
from unittest.mock import patch

from typer.testing import CliRunner

from nbadb.cli.app import app

if TYPE_CHECKING:
    from pathlib import Path

runner = CliRunner()


def test_table_year_coverage_writes_artifacts_and_prints_summary(tmp_path: Path) -> None:
    db_path = tmp_path / "nba.duckdb"
    db_path.write_text("", encoding="utf-8")
    output_dir = tmp_path / "coverage"
    coverage_payload = {
        "summary": {
            "expected_row_count": 3,
            "actual_row_count": 2,
            "blocking_missing_count": 1,
            "contract_gap_count": 0,
            "coverage_status_breakdown": {"missing": 1, "present": 2},
        },
        "expected": [],
        "actual": [],
        "diff": [],
        "journal": [],
        "tables": [],
    }

    with (
        patch("nbadb.cli.commands.table_year_coverage._build_settings") as mock_settings,
        patch("nbadb.cli.commands.table_year_coverage._open_db_readonly") as mock_open,
        patch("nbadb.cli.commands.table_year_coverage.EndpointCoverageGenerator") as mock_generator,
        patch("nbadb.cli.commands.table_year_coverage.build_table_year_coverage") as mock_build,
    ):
        mock_settings.return_value = SimpleNamespace(duckdb_path=db_path)
        mock_conn = mock_open.return_value
        mock_generator.return_value.build_artifacts.return_value = {
            "temporal_coverage_matrix": {"matrix": [{"endpoint_name": "league_game_log"}]}
        }
        mock_build.return_value = coverage_payload

        result = runner.invoke(
            app,
            ["table-year-coverage", "--output-dir", str(output_dir)],
        )

    assert result.exit_code == 0, result.output
    mock_open.assert_called_once_with(db_path)
    mock_conn.close.assert_called_once_with()
    mock_build.assert_called_once_with(mock_conn, [{"endpoint_name": "league_game_log"}])
    assert "expected=3" in result.output
    assert "actual=2" in result.output
    assert "blocking_missing=1" in result.output
    assert "missing=1" in result.output
    assert (output_dir / "table-year-coverage-summary.json").exists()
    assert (output_dir / "table-year-coverage-diff.json").exists()


def test_table_year_coverage_require_complete_exits_when_gaps_remain(tmp_path: Path) -> None:
    db_path = tmp_path / "nba.duckdb"
    db_path.write_text("", encoding="utf-8")
    with (
        patch("nbadb.cli.commands.table_year_coverage._build_settings") as mock_settings,
        patch("nbadb.cli.commands.table_year_coverage._open_db_readonly"),
        patch("nbadb.cli.commands.table_year_coverage.EndpointCoverageGenerator") as mock_generator,
        patch("nbadb.cli.commands.table_year_coverage.build_table_year_coverage") as mock_build,
    ):
        mock_settings.return_value = SimpleNamespace(duckdb_path=db_path)
        mock_generator.return_value.build_artifacts.return_value = {
            "temporal_coverage_matrix": {"matrix": []}
        }
        mock_build.return_value = {
            "summary": {
                "expected_row_count": 1,
                "actual_row_count": 0,
                "blocking_missing_count": 1,
                "contract_gap_count": 0,
                "coverage_status_breakdown": {"missing": 1},
            },
            "expected": [],
            "actual": [],
            "diff": [],
            "journal": [],
            "tables": [],
        }

        result = runner.invoke(app, ["table-year-coverage", "--require-complete"])

    assert result.exit_code == 1
    assert "require-complete check failed" in result.output
