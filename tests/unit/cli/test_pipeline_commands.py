"""Unit tests for NBA pipeline CLI commands (init, daily, monthly, full)."""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

from typer.testing import CliRunner

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
    mock_cls.return_value.run_init.assert_awaited_once_with(start_season=2020)


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
