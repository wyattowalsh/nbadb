"""Unit tests for nbadb CLI helper functions."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

from nbadb.cli.commands._helpers import (
    _build_settings,
    _print_result,
    _setup_logging,
)
from nbadb.core.config import NbaDbSettings
from nbadb.orchestrate.orchestrator import PipelineResult

# ---------------------------------------------------------------------------
# _build_settings
# ---------------------------------------------------------------------------


def test_build_settings_defaults() -> None:
    settings = _build_settings()
    assert isinstance(settings, NbaDbSettings)
    assert settings.data_dir == Path("nbadb")


def test_build_settings_data_dir_override() -> None:
    settings = _build_settings(data_dir="/tmp/testdata")
    assert settings.data_dir == Path("/tmp/testdata")


def test_build_settings_formats_override() -> None:
    settings = _build_settings(formats=["csv"])
    assert settings.formats == ["csv"]


# ---------------------------------------------------------------------------
# _setup_logging
# ---------------------------------------------------------------------------


def test_setup_logging_verbose() -> None:
    from loguru import logger

    _setup_logging(verbose=True)
    # After verbose setup, a DEBUG-level handler should be active
    handlers = logger._core.handlers
    assert len(handlers) >= 1
    # At least one handler should accept DEBUG level (levelno 10)
    assert any(h.levelno <= 10 for h in handlers.values())


def test_setup_logging_non_verbose() -> None:
    from loguru import logger

    _setup_logging(verbose=False)
    # After non-verbose setup, only WARNING-level handler should be active
    handlers = logger._core.handlers
    assert len(handlers) >= 1
    # All handlers should be WARNING (30) or above
    assert all(h.levelno >= 30 for h in handlers.values())


# ---------------------------------------------------------------------------
# _print_result
# ---------------------------------------------------------------------------


def test_print_result_success() -> None:
    result = PipelineResult(
        tables_updated=5,
        rows_total=1000,
        duration_seconds=2.5,
        failed_extractions=0,
        errors=[],
    )
    with patch("nbadb.cli.commands._helpers.typer.echo") as mock_echo:
        _print_result("init", result)
    assert any("init: 5 tables" in str(call) for call in mock_echo.call_args_list)


def test_print_result_with_failures() -> None:
    result = PipelineResult(
        tables_updated=1,
        rows_total=50,
        duration_seconds=0.5,
        failed_extractions=2,
        errors=["ep1: oops"],
    )
    with patch("nbadb.cli.commands._helpers.typer.echo") as mock_echo:
        _print_result("daily", result)
    all_calls = [str(call) for call in mock_echo.call_args_list]
    assert any("2 extractions failed" in c for c in all_calls)


def test_print_result_with_failed_loads() -> None:
    result = PipelineResult(
        tables_updated=3,
        rows_total=500,
        duration_seconds=5.0,
        failed_extractions=0,
        failed_loads=2,
        errors=[],
    )
    with patch("nbadb.cli.commands._helpers.typer.echo") as mock_echo:
        _print_result("full", result)
    all_calls = [str(call) for call in mock_echo.call_args_list]
    assert any("2 loads failed" in c for c in all_calls)


def test_print_result_with_errors_list() -> None:
    result = PipelineResult(
        tables_updated=0,
        rows_total=0,
        duration_seconds=1.0,
        failed_extractions=1,
        errors=["timeout on box_score", "connection reset"],
    )
    with patch("nbadb.cli.commands._helpers.typer.echo") as mock_echo:
        _print_result("init", result)
    all_calls = [str(call) for call in mock_echo.call_args_list]
    assert any("timeout on box_score" in c for c in all_calls)
    assert any("connection reset" in c for c in all_calls)


def test_setup_logging_tui_mode(tmp_path) -> None:
    """TUI mode logs to file instead of stderr."""
    import os

    original_cwd = os.getcwd()
    try:
        os.chdir(tmp_path)
        _setup_logging(verbose=False, tui=True)
        # Should have created a file-based handler
        from loguru import logger

        handlers = logger._core.handlers
        assert len(handlers) >= 1
    finally:
        os.chdir(original_cwd)


def test_build_settings_both_overrides(tmp_path) -> None:
    settings = _build_settings(data_dir=str(tmp_path), formats=["csv", "parquet"])
    assert settings.data_dir == tmp_path
    assert settings.formats == ["csv", "parquet"]
