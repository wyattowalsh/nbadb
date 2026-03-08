"""Unit tests for NBA pipeline CLI commands (init, daily, monthly, full, run-quality)."""

from __future__ import annotations

import json
from typing import TYPE_CHECKING
from unittest.mock import AsyncMock, MagicMock, patch

import duckdb
from typer.testing import CliRunner

if TYPE_CHECKING:
    from pathlib import Path

from nbadb.cli.app import app
from nbadb.orchestrate.orchestrator import PipelineResult

runner = CliRunner()

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

# Each command module binds Orchestrator into its own namespace via
# `from nbadb.orchestrate import Orchestrator`, so we must patch there.
_INIT_PATH = "nbadb.cli.commands.init.Orchestrator"
_DAILY_PATH = "nbadb.cli.commands.daily.Orchestrator"
_MONTHLY_PATH = "nbadb.cli.commands.monthly.Orchestrator"
_FULL_PATH = "nbadb.cli.commands.full.Orchestrator"


def _make_result(**kwargs: object) -> PipelineResult:
    defaults: dict[str, object] = dict(
        tables_updated=3,
        rows_total=500,
        duration_seconds=1.0,
        failed_extractions=0,
        errors=[],
    )
    defaults.update(kwargs)
    return PipelineResult(**defaults)  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# init
# ---------------------------------------------------------------------------


def test_init_success() -> None:
    with patch(_INIT_PATH) as mock_cls:
        mock_cls.return_value.run_init = AsyncMock(
            return_value=_make_result(tables_updated=5, rows_total=1000, duration_seconds=2.5)
        )
        result = runner.invoke(app, ["init"])
    assert result.exit_code == 0
    assert "init" in result.output


def test_init_failure() -> None:
    with patch(_INIT_PATH) as mock_cls:
        mock_cls.return_value.run_init = AsyncMock(side_effect=RuntimeError("boom"))
        result = runner.invoke(app, ["init"])
    assert result.exit_code == 1
    assert "init failed" in result.output


def test_init_verbose_flag() -> None:
    with patch(_INIT_PATH) as mock_cls:
        mock_cls.return_value.run_init = AsyncMock(return_value=_make_result())
        result = runner.invoke(app, ["init", "--verbose"])
    assert result.exit_code == 0


def test_init_data_dir_option() -> None:
    with patch(_INIT_PATH) as mock_cls:
        mock_cls.return_value.run_init = AsyncMock(return_value=_make_result())
        result = runner.invoke(app, ["init", "--data-dir", "/tmp/testdata"])
    assert result.exit_code == 0


def test_init_season_start() -> None:
    with patch(_INIT_PATH) as mock_cls:
        mock_cls.return_value.run_init = AsyncMock(return_value=_make_result())
        result = runner.invoke(app, ["init", "--season-start", "2020"])
    assert result.exit_code == 0
    # Verify the season was forwarded to run_init
    mock_cls.return_value.run_init.assert_awaited_once_with(start_season=2020, end_season=None)


def test_init_season_end() -> None:
    with patch(_INIT_PATH) as mock_cls:
        mock_cls.return_value.run_init = AsyncMock(return_value=_make_result())
        result = runner.invoke(app, ["init", "--season-start", "2020", "--season-end", "2024"])
    assert result.exit_code == 0
    mock_cls.return_value.run_init.assert_awaited_once_with(start_season=2020, end_season=2024)


def test_init_partial_failure_exits_nonzero() -> None:
    with patch(_INIT_PATH) as mock_cls:
        mock_cls.return_value.run_init = AsyncMock(
            return_value=_make_result(failed_extractions=5)
        )
        result = runner.invoke(app, ["init"])
    assert result.exit_code == 1


# ---------------------------------------------------------------------------
# daily
# ---------------------------------------------------------------------------


def test_daily_success() -> None:
    with patch(_DAILY_PATH) as mock_cls:
        mock_cls.return_value.run_daily = AsyncMock(return_value=_make_result())
        result = runner.invoke(app, ["daily"])
    assert result.exit_code == 0
    assert "daily" in result.output


def test_daily_failure() -> None:
    with patch(_DAILY_PATH) as mock_cls:
        mock_cls.return_value.run_daily = AsyncMock(side_effect=RuntimeError("boom"))
        result = runner.invoke(app, ["daily"])
    assert result.exit_code == 1
    assert "daily failed" in result.output


def test_daily_data_dir_option() -> None:
    with patch(_DAILY_PATH) as mock_cls:
        mock_cls.return_value.run_daily = AsyncMock(return_value=_make_result())
        result = runner.invoke(app, ["daily", "--data-dir", "/tmp/testdata"])
    assert result.exit_code == 0


# ---------------------------------------------------------------------------
# monthly
# ---------------------------------------------------------------------------


def test_monthly_success() -> None:
    with patch(_MONTHLY_PATH) as mock_cls:
        mock_cls.return_value.run_monthly = AsyncMock(return_value=_make_result())
        result = runner.invoke(app, ["monthly"])
    assert result.exit_code == 0
    assert "monthly" in result.output


def test_monthly_failure() -> None:
    with patch(_MONTHLY_PATH) as mock_cls:
        mock_cls.return_value.run_monthly = AsyncMock(side_effect=RuntimeError("boom"))
        result = runner.invoke(app, ["monthly"])
    assert result.exit_code == 1
    assert "monthly failed" in result.output


def test_monthly_data_dir_option() -> None:
    with patch(_MONTHLY_PATH) as mock_cls:
        mock_cls.return_value.run_monthly = AsyncMock(return_value=_make_result())
        result = runner.invoke(app, ["monthly", "--data-dir", "/tmp/testdata"])
    assert result.exit_code == 0


# ---------------------------------------------------------------------------
# full
# ---------------------------------------------------------------------------


def test_full_success() -> None:
    with patch(_FULL_PATH) as mock_cls:
        mock_cls.return_value.run_full = AsyncMock(return_value=_make_result())
        result = runner.invoke(app, ["full"])
    assert result.exit_code == 0
    assert "full" in result.output


def test_full_failure() -> None:
    with patch(_FULL_PATH) as mock_cls:
        mock_cls.return_value.run_full = AsyncMock(side_effect=RuntimeError("boom"))
        result = runner.invoke(app, ["full"])
    assert result.exit_code == 1
    assert "full failed" in result.output


def test_full_data_dir_option() -> None:
    with patch(_FULL_PATH) as mock_cls:
        mock_cls.return_value.run_full = AsyncMock(return_value=_make_result())
        result = runner.invoke(app, ["full", "--data-dir", "/tmp/testdata"])
    assert result.exit_code == 0


# ---------------------------------------------------------------------------
# run-quality
# ---------------------------------------------------------------------------

_MONITOR_PATH = "nbadb.transform.quality.DataQualityMonitor"
_DUCKDB_CONNECT_PATH = "nbadb.cli.commands.run_quality.duckdb"


class TestRunQualityCommand:
    def test_run_quality_invokes_monitor(self, tmp_path: Path) -> None:
        """DataQualityMonitor is instantiated with the DuckDB connection, exit 0."""
        db_file = tmp_path / "nba.duckdb"
        real_conn = duckdb.connect(str(db_file))
        real_conn.close()

        mock_monitor = MagicMock()
        mock_monitor.summary.return_value = {"passed": 1, "total": 1, "failed": 0}
        mock_monitor.failed.return_value = []

        with patch(_MONITOR_PATH, return_value=mock_monitor) as mock_cls:
            result = runner.invoke(app, ["run-quality", "--data-dir", str(tmp_path)])

        assert result.exit_code == 0, result.output
        mock_cls.assert_called_once()
        mock_monitor.log_summary.assert_called_once()

    def test_run_quality_fails_when_no_checks_run(self, tmp_path: Path) -> None:
        """When no checks are executed, run-quality exits with a non-zero code."""
        db_file = tmp_path / "nba.duckdb"
        real_conn = duckdb.connect(str(db_file))
        real_conn.close()

        mock_monitor = MagicMock()
        mock_monitor.summary.return_value = {"passed": 0, "total": 0, "failed": 0}
        mock_monitor.failed.return_value = []

        with patch(_MONITOR_PATH, return_value=mock_monitor):
            result = runner.invoke(app, ["run-quality", "--data-dir", str(tmp_path)])

        assert result.exit_code == 1
        assert "no checks were executed" in result.output.lower()

    def test_run_quality_no_database(self, tmp_path: Path) -> None:
        """When the DuckDB file does not exist, exit 1 with error message."""
        missing_dir = tmp_path / "nonexistent_xyz"
        result = runner.invoke(app, ["run-quality", "--data-dir", str(missing_dir)])
        assert result.exit_code == 1
        assert "Error" in result.output or "not found" in result.output

    def test_run_quality_handles_monitor_failure(self, tmp_path: Path) -> None:
        """When DataQualityMonitor raises, error appears in output, exit 1."""
        db_file = tmp_path / "nba.duckdb"
        real_conn = duckdb.connect(str(db_file))
        real_conn.close()

        with patch(_MONITOR_PATH, side_effect=RuntimeError("monitor exploded")):
            result = runner.invoke(app, ["run-quality", "--data-dir", str(tmp_path)])

        assert result.exit_code == 1
        assert "Quality check failed" in result.output or "RuntimeError" in result.output

    def test_run_quality_writes_report_json(self, tmp_path: Path) -> None:
        """When --report-path is set, run-quality writes a JSON report artifact."""
        db_file = tmp_path / "nba.duckdb"
        real_conn = duckdb.connect(str(db_file))
        real_conn.close()

        mock_monitor = MagicMock()
        mock_monitor.summary.return_value = {"passed": 1, "total": 1, "failed": 0}
        mock_monitor.failed.return_value = []
        mock_monitor.to_report.return_value = {
            "summary": {"passed": 1, "total": 1, "failed": 0},
            "summary_by_layer": {"structural": {"passed": 1, "total": 1, "failed": 0}},
            "results": [
                {
                    "table": "dim_player",
                    "check_type": "row_count",
                    "layer": "structural",
                    "passed": True,
                    "message": "dim_player: 1 rows",
                    "details": None,
                }
            ],
        }
        report_path = tmp_path / "quality-report.json"

        with patch(_MONITOR_PATH, return_value=mock_monitor):
            result = runner.invoke(
                app,
                [
                    "run-quality",
                    "--data-dir",
                    str(tmp_path),
                    "--report-path",
                    str(report_path),
                ],
            )

        assert result.exit_code == 0
        assert report_path.exists()
        report = json.loads(report_path.read_text(encoding="utf-8"))
        assert report["summary"]["total"] == 1
