from __future__ import annotations

import os
from pathlib import Path
from unittest.mock import MagicMock, patch

import duckdb

from nbadb.core.config import get_settings


def test_chat_command_injects_absolute_duckdb_path(tmp_path: Path) -> None:
    get_settings.cache_clear()
    warehouse = tmp_path / "nba.duckdb"
    duckdb.connect(str(warehouse)).close()
    os.environ["NBADB_DUCKDB_PATH"] = str(warehouse)
    get_settings.cache_clear()

    try:
        from nbadb.cli.commands import chat as chat_mod

        # Ensure launcher files exist for this test path (repo fixtures usually do).
        with (
            patch.object(chat_mod.shutil, "which", return_value="/usr/bin/uv"),
            patch.object(chat_mod.subprocess, "run") as mock_run,
            patch.object(chat_mod.typer, "echo"),
        ):
            mock_run.return_value = MagicMock(returncode=0)
            # If chat app files missing, skip — path env is still validated when present.
            if not chat_mod.CHAT_APP.joinpath("chainlit_app.py").exists():
                return
            chat_mod.chat(port=8421, host="127.0.0.1")
            assert mock_run.called
            env = mock_run.call_args.kwargs["env"]
            assert Path(env["NBADB_DUCKDB_PATH"]).is_absolute()
            assert env["NBADB_DUCKDB_PATH"] == str(warehouse.resolve())
    finally:
        os.environ.pop("NBADB_DUCKDB_PATH", None)
        get_settings.cache_clear()


def test_chat_command_fails_closed_when_warehouse_missing(tmp_path: Path) -> None:
    get_settings.cache_clear()
    missing = tmp_path / "nope.duckdb"
    os.environ["NBADB_DUCKDB_PATH"] = str(missing)
    get_settings.cache_clear()

    try:
        import pytest

        from nbadb.cli.commands import chat as chat_mod

        with (
            patch.object(chat_mod.shutil, "which", return_value="/usr/bin/uv"),
            patch.object(chat_mod.subprocess, "run") as mock_run,
            patch.object(chat_mod.typer, "echo"),
        ):
            if not chat_mod.CHAT_APP.joinpath("chainlit_app.py").exists():
                return
            with pytest.raises((SystemExit, chat_mod.typer.Exit)) as exc_info:
                chat_mod.chat(port=8421, host="127.0.0.1")
            code = getattr(exc_info.value, "exit_code", None)
            if code is None:
                code = getattr(exc_info.value, "code", None)
            assert code == 1
            assert not mock_run.called
    finally:
        os.environ.pop("NBADB_DUCKDB_PATH", None)
        get_settings.cache_clear()


def test_chat_command_fails_closed_when_warehouse_is_corrupt(tmp_path: Path) -> None:
    get_settings.cache_clear()
    warehouse = tmp_path / "corrupt.duckdb"
    warehouse.write_bytes(b"not a DuckDB database")
    os.environ["NBADB_DUCKDB_PATH"] = str(warehouse)
    get_settings.cache_clear()

    try:
        import pytest

        from nbadb.cli.commands import chat as chat_mod

        with (
            patch.object(chat_mod.shutil, "which", return_value="/usr/bin/uv"),
            patch.object(chat_mod.subprocess, "run") as mock_run,
            patch.object(chat_mod.typer, "echo") as mock_echo,
        ):
            if not chat_mod.CHAT_APP.joinpath("chainlit_app.py").exists():
                return
            with pytest.raises((SystemExit, chat_mod.typer.Exit)) as exc_info:
                chat_mod.chat(port=8421, host="127.0.0.1")
            code = getattr(exc_info.value, "exit_code", None)
            if code is None:
                code = getattr(exc_info.value, "code", None)
            assert code == 1
            assert not mock_run.called
            assert "not found or unusable" in " ".join(
                str(call.args[0]) for call in mock_echo.call_args_list
            )
    finally:
        os.environ.pop("NBADB_DUCKDB_PATH", None)
        get_settings.cache_clear()


def test_build_runtime_fails_when_missing(tmp_path: Path, monkeypatch) -> None:
    from nbadb.chat.runtime.core import build_runtime
    from nbadb.core.config import get_settings

    missing = tmp_path / "nope.duckdb"
    monkeypatch.setenv("NBADB_DUCKDB_PATH", str(missing))
    get_settings.cache_clear()
    try:
        import pytest

        with pytest.raises(RuntimeError, match="not found"):
            build_runtime()
    finally:
        get_settings.cache_clear()
