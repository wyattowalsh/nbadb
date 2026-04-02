"""Unit tests for nbadb CLI helper functions."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest
import typer

from nbadb.cli.commands._helpers import (
    _build_settings,
    _open_db_readonly,
    _print_result,
    _run_pipeline,
    _setup_logging,
)
from nbadb.core.config import NbaDbSettings
from nbadb.orchestrate.orchestrator import PipelineResult

# ---------------------------------------------------------------------------
# _build_settings
# ---------------------------------------------------------------------------


def test_build_settings_defaults(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("NBADB_DATA_DIR", raising=False)
    settings = _build_settings()
    assert isinstance(settings, NbaDbSettings)


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
    all_calls = [str(call) for call in mock_echo.call_args_list]
    assert any("init complete" in c for c in all_calls)
    assert any("5 tables" in c for c in all_calls)


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


# ---------------------------------------------------------------------------
# _open_db_readonly
# ---------------------------------------------------------------------------


def test_open_db_readonly_nonexistent_path(tmp_path) -> None:
    """Non-existent database path raises typer.Exit(1)."""
    bad_path = tmp_path / "does_not_exist.duckdb"
    with pytest.raises(typer.Exit) as exc_info:
        _open_db_readonly(bad_path)
    assert exc_info.value.exit_code == 1


def test_open_db_readonly_valid_path(tmp_path) -> None:
    """Valid DuckDB file opens successfully in read-only mode."""
    import duckdb

    db_path = tmp_path / "test.duckdb"
    # Create a valid database first
    conn = duckdb.connect(str(db_path))
    conn.execute("CREATE TABLE t (id INT)")
    conn.close()

    result = _open_db_readonly(db_path)
    try:
        # Should be able to read
        assert result.execute("SELECT COUNT(*) FROM t").fetchone()[0] == 0
    finally:
        result.close()


# ---------------------------------------------------------------------------
# _run_pipeline — non-TTY path (signal handling, exception paths)
# ---------------------------------------------------------------------------


def test_run_pipeline_non_tty_success() -> None:
    """Non-TTY run pipeline completes successfully and calls _print_result."""
    fake_result = PipelineResult(
        tables_updated=3,
        rows_total=100,
        duration_seconds=1.0,
        failed_extractions=0,
        errors=[],
    )

    async def fake_run(orch):
        return fake_result

    class FakeOrchCls:
        def __init__(self, **kwargs):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *a):
            pass

    with (
        patch("nbadb.cli.commands._helpers.sys.stdout") as mock_stdout,
        patch("nbadb.cli.commands._helpers.asyncio.run", return_value=fake_result),
        patch("nbadb.cli.commands._helpers._print_result") as mock_print,
        patch("nbadb.cli.commands._helpers._setup_logging"),
    ):
        mock_stdout.isatty.return_value = False
        settings = _build_settings()
        _run_pipeline(
            "test",
            fake_run,
            settings,
            verbose=False,
            orchestrator_cls=FakeOrchCls,
        )
        mock_print.assert_called_once()
        call_args = mock_print.call_args
        assert call_args[0][0] == "test"
        assert call_args[0][1] == fake_result


def test_run_pipeline_non_tty_exception_raises_exit() -> None:
    """Non-TTY pipeline raises typer.Exit(1) on exception."""

    async def fake_run(orch):
        return None

    class FakeOrchCls:
        def __init__(self, **kwargs):
            pass

    with (
        patch("nbadb.cli.commands._helpers.sys.stdout") as mock_stdout,
        patch(
            "nbadb.cli.commands._helpers.asyncio.run",
            side_effect=RuntimeError("boom"),
        ),
        patch("nbadb.cli.commands._helpers._setup_logging"),
    ):
        mock_stdout.isatty.return_value = False
        settings = _build_settings()
        with pytest.raises(typer.Exit) as exc_info:
            _run_pipeline(
                "test",
                fake_run,
                settings,
                verbose=False,
                orchestrator_cls=FakeOrchCls,
            )
        assert exc_info.value.exit_code == 1


def test_run_pipeline_non_tty_cancelled_error_raises_exit_0() -> None:
    """CancelledError in non-TTY mode raises typer.Exit(0)."""
    import asyncio as _asyncio

    async def fake_run(orch):
        return None

    class FakeOrchCls:
        def __init__(self, **kwargs):
            pass

    with (
        patch("nbadb.cli.commands._helpers.sys.stdout") as mock_stdout,
        patch(
            "nbadb.cli.commands._helpers.asyncio.run",
            side_effect=_asyncio.CancelledError(),
        ),
        patch("nbadb.cli.commands._helpers._setup_logging"),
    ):
        mock_stdout.isatty.return_value = False
        settings = _build_settings()
        with pytest.raises(typer.Exit) as exc_info:
            _run_pipeline(
                "test",
                fake_run,
                settings,
                verbose=False,
                orchestrator_cls=FakeOrchCls,
            )
        assert exc_info.value.exit_code == 0


def test_run_pipeline_keyboard_interrupt_raises_exit_0() -> None:
    """KeyboardInterrupt in non-TTY mode raises typer.Exit(0)."""

    async def fake_run(orch):
        return None

    class FakeOrchCls:
        def __init__(self, **kwargs):
            pass

    with (
        patch("nbadb.cli.commands._helpers.sys.stdout") as mock_stdout,
        patch(
            "nbadb.cli.commands._helpers.asyncio.run",
            side_effect=KeyboardInterrupt(),
        ),
        patch("nbadb.cli.commands._helpers._setup_logging"),
    ):
        mock_stdout.isatty.return_value = False
        settings = _build_settings()
        with pytest.raises(typer.Exit) as exc_info:
            _run_pipeline(
                "test",
                fake_run,
                settings,
                verbose=False,
                orchestrator_cls=FakeOrchCls,
            )
        assert exc_info.value.exit_code == 0


def test_run_pipeline_lazy_import_orchestrator() -> None:
    """When orchestrator_cls is None, it is lazily imported."""
    fake_result = PipelineResult(
        tables_updated=1,
        rows_total=10,
        duration_seconds=0.1,
        failed_extractions=0,
        errors=[],
    )

    async def fake_run(orch):
        return fake_result

    with (
        patch("nbadb.cli.commands._helpers.sys.stdout") as mock_stdout,
        patch("nbadb.cli.commands._helpers.asyncio.run", return_value=fake_result),
        patch("nbadb.cli.commands._helpers._print_result"),
        patch("nbadb.cli.commands._helpers._setup_logging"),
        patch("nbadb.orchestrate.Orchestrator") as mock_orch_cls,
    ):
        mock_stdout.isatty.return_value = False
        mock_orch_cls.return_value = mock_orch_cls
        settings = _build_settings()
        _run_pipeline(
            "test",
            fake_run,
            settings,
            verbose=False,
            orchestrator_cls=None,
        )


def test_run_pipeline_tui_path_success() -> None:
    """TUI path completes successfully when stdout is a TTY."""
    fake_result = PipelineResult(
        tables_updated=2,
        rows_total=50,
        duration_seconds=0.5,
        failed_extractions=0,
        errors=[],
    )

    async def fake_run(orch):
        return fake_result

    with (
        patch("nbadb.cli.commands._helpers.sys.stdout") as mock_stdout,
        patch("nbadb.cli.commands._helpers._print_result") as mock_print,
        patch("nbadb.cli.tui.run_with_tui", return_value=(fake_result, None, None)) as mock_tui,
    ):
        mock_stdout.isatty.return_value = True
        settings = _build_settings()
        _run_pipeline(
            "test",
            fake_run,
            settings,
            verbose=False,
            orchestrator_cls=type("FakeOrch", (), {}),
        )
        mock_tui.assert_called_once()
        mock_print.assert_called_once()
        call_args = mock_print.call_args
        assert call_args[0][0] == "test"
        assert call_args[0][1] == fake_result


def test_run_pipeline_tui_path_error() -> None:
    """TUI path with error raises typer.Exit(1)."""

    async def fake_run(orch):
        return None

    with (
        patch("nbadb.cli.commands._helpers.sys.stdout") as mock_stdout,
        patch(
            "nbadb.cli.tui.run_with_tui",
            return_value=(None, RuntimeError("tui failed"), None),
        ),
    ):
        mock_stdout.isatty.return_value = True
        settings = _build_settings()
        with pytest.raises(typer.Exit) as exc_info:
            _run_pipeline(
                "test",
                fake_run,
                settings,
                verbose=False,
                orchestrator_cls=type("FakeOrch", (), {}),
            )
        assert exc_info.value.exit_code == 1


def test_run_pipeline_tui_path_none_result() -> None:
    """TUI path with None result (user cancelled) raises typer.Exit(0)."""

    async def fake_run(orch):
        return None

    with (
        patch("nbadb.cli.commands._helpers.sys.stdout") as mock_stdout,
        patch("nbadb.cli.tui.run_with_tui", return_value=(None, None, None)),
    ):
        mock_stdout.isatty.return_value = True
        settings = _build_settings()
        with pytest.raises(typer.Exit) as exc_info:
            _run_pipeline(
                "test",
                fake_run,
                settings,
                verbose=False,
                orchestrator_cls=type("FakeOrch", (), {}),
            )
        assert exc_info.value.exit_code == 0
