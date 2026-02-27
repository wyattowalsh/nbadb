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


class TestCLIStubCommands:
    def test_init_not_implemented(self) -> None:
        result = runner.invoke(app, ["init"])
        assert "not yet implemented" in result.output
        assert result.exit_code == 1

    def test_daily_not_implemented(self) -> None:
        result = runner.invoke(app, ["daily"])
        assert "not yet implemented" in result.output
        assert result.exit_code == 1

    def test_monthly_not_implemented(self) -> None:
        result = runner.invoke(app, ["monthly"])
        assert "not yet implemented" in result.output
        assert result.exit_code == 1

    def test_full_not_implemented(self) -> None:
        result = runner.invoke(app, ["full"])
        assert "not yet implemented" in result.output
        assert result.exit_code == 1

    def test_export_not_implemented(self) -> None:
        result = runner.invoke(app, ["export"])
        assert "not yet implemented" in result.output
        assert result.exit_code == 1

    def test_status_not_implemented(self) -> None:
        result = runner.invoke(app, ["status"])
        assert "not yet implemented" in result.output
        assert result.exit_code == 1

    def test_schema_not_implemented(self) -> None:
        result = runner.invoke(app, ["schema"])
        assert "not yet implemented" in result.output
        assert result.exit_code == 1

    def test_download_not_implemented(self) -> None:
        result = runner.invoke(app, ["download"])
        assert "not yet implemented" in result.output
        assert result.exit_code == 1

    def test_upload_not_implemented(self) -> None:
        result = runner.invoke(app, ["upload"])
        assert "not yet implemented" in result.output
        assert result.exit_code == 1


class TestCLIInvalidCommand:
    def test_unknown_command_fails(self) -> None:
        result = runner.invoke(app, ["nonexistent-cmd"])
        assert result.exit_code != 0
