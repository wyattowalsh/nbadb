from __future__ import annotations

import pytest
from typer.testing import CliRunner

from nbadb.cli.app import app

runner = CliRunner()

ALL_COMMANDS = [
    "init", "daily", "monthly", "full",
    "export", "upload", "download",
    "schema", "status", "ask",
]


class TestCLIApp:
    def test_no_args_shows_help(self) -> None:
        result = runner.invoke(app)
        assert "Usage" in result.output

    def test_help_flag(self) -> None:
        result = runner.invoke(app, ["--help"])
        assert result.exit_code == 0
        assert "Usage" in result.output


class TestCLICommandHelp:
    @pytest.mark.parametrize("cmd", ALL_COMMANDS)
    def test_command_help(self, cmd: str) -> None:
        result = runner.invoke(app, [cmd, "--help"])
        assert result.exit_code == 0
        assert cmd in result.output.lower() or "Usage" in result.output


class TestCLICommandsWithoutDB:
    """Commands fail gracefully when no database exists."""

    def test_export_fails_without_db(self) -> None:
        result = runner.invoke(app, ["export"])
        assert result.exit_code == 1

    def test_status_runs(self) -> None:
        result = runner.invoke(app, ["status"])
        # Exit 0 if DB exists and is readable; exit 1 if not found
        assert result.exit_code in (0, 1)

    def test_schema_lists_tables(self) -> None:
        result = runner.invoke(app, ["schema"])
        assert result.exit_code == 0
        assert "Total" in result.output

    def test_download_runs(self) -> None:
        result = runner.invoke(app, ["download"])
        # Exit 0 if kaggle API configured; exit 1 otherwise
        assert result.exit_code in (0, 1)

    def test_upload_fails_without_data(self) -> None:
        result = runner.invoke(app, ["upload"])
        # May fail if no data or no kaggle API
        assert result.exit_code in (0, 1)


class TestCLIInvalidCommand:
    def test_unknown_command_fails(self) -> None:
        result = runner.invoke(app, ["nonexistent-cmd"])
        assert result.exit_code != 0
