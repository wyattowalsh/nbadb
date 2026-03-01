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
    _setup_logging(verbose=True)


def test_setup_logging_non_verbose() -> None:
    _setup_logging(verbose=False)


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
