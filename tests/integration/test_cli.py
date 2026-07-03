from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest
from typer.testing import CliRunner

from nbadb.cli.app import app

runner = CliRunner()


def _registered_command_name(command_info: object) -> str:
    name = command_info.name
    if isinstance(name, str):
        return name

    callback = command_info.callback
    if callback is None:
        msg = f"Registered command is missing a callback: {command_info!r}"
        raise AssertionError(msg)
    return callback.__name__.replace("_", "-")


def _registered_group_name(group_info: object) -> str:
    name = group_info.name
    if isinstance(name, str):
        return name

    typer_instance = group_info.typer_instance
    group_name = typer_instance.info.name
    if not isinstance(group_name, str):
        msg = f"Registered command group is missing a name: {group_info!r}"
        raise AssertionError(msg)
    return group_name


ALL_COMMANDS = sorted(
    {
        *(_registered_command_name(command) for command in app.registered_commands),
        *(_registered_group_name(group) for group in app.registered_groups),
    }
)


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
        with patch("nbadb.kaggle.client.KaggleClient") as mock_cls:
            mock_cls.return_value.ensure_metadata.side_effect = FileNotFoundError(
                "Data directory does not exist"
            )
            mock_cls.return_value.upload.return_value = Path("/tmp/should-not-upload.json")
            result = runner.invoke(app, ["upload"])

        assert result.exit_code == 1
        assert "Upload failed" in result.output
        mock_cls.return_value.upload.assert_not_called()


class TestCLIInvalidCommand:
    def test_unknown_command_fails(self) -> None:
        result = runner.invoke(app, ["nonexistent-cmd"])
        assert result.exit_code != 0
