"""Unit tests for the chat CLI command."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from typer.testing import CliRunner

# Import the command module so the @app.command() decorator registers it
import nbadb.cli.commands.chat  # noqa: F401
from nbadb.cli.app import app

runner = CliRunner()


# ---------------------------------------------------------------------------
# Tests — missing app file
# ---------------------------------------------------------------------------


def test_chat_app_file_missing(tmp_path) -> None:  # noqa: ANN001
    """Exit 1 when chainlit_app.py does not exist."""
    fake_chat_dir = tmp_path / "apps" / "chat"
    fake_chat_dir.mkdir(parents=True)

    with patch("nbadb.cli.commands.chat.CHAT_APP", fake_chat_dir):
        result = runner.invoke(app, ["chat"])
    assert result.exit_code == 1
    assert "chat app not found" in result.output


# ---------------------------------------------------------------------------
# Tests — missing uv
# ---------------------------------------------------------------------------


def test_chat_uv_not_found(tmp_path) -> None:  # noqa: ANN001
    """Exit 1 when uv is not on PATH."""
    fake_chat_dir = tmp_path / "apps" / "chat"
    fake_chat_dir.mkdir(parents=True)
    (fake_chat_dir / "chainlit_app.py").write_text("# app", encoding="utf-8")

    with (
        patch("nbadb.cli.commands.chat.CHAT_APP", fake_chat_dir),
        patch("nbadb.cli.commands.chat.shutil.which", return_value=None),
    ):
        result = runner.invoke(app, ["chat"])
    assert result.exit_code == 1
    assert "uv is required but not found" in result.output


# ---------------------------------------------------------------------------
# Tests — successful launch
# ---------------------------------------------------------------------------


def test_chat_success(tmp_path) -> None:  # noqa: ANN001
    """Successful launch calls subprocess.run with correct arguments."""
    fake_chat_dir = tmp_path / "apps" / "chat"
    fake_chat_dir.mkdir(parents=True)
    (fake_chat_dir / "chainlit_app.py").write_text("# app", encoding="utf-8")

    mock_run = MagicMock()

    with (
        patch("nbadb.cli.commands.chat.CHAT_APP", fake_chat_dir),
        patch("nbadb.cli.commands.chat.shutil.which", return_value="/usr/bin/uv"),
        patch("nbadb.cli.commands.chat.subprocess.run", mock_run),
    ):
        result = runner.invoke(app, ["chat", "--port", "9000", "--host", "0.0.0.0"])

    assert result.exit_code == 0
    assert "Starting nbadb chat on http://0.0.0.0:9000" in result.output

    mock_run.assert_called_once()
    call_args = mock_run.call_args
    cmd = call_args[0][0]
    assert cmd[0] == "/usr/bin/uv"
    assert "chainlit" in cmd[2]
    assert "--port" in cmd
    assert "9000" in cmd
    assert "--host" in cmd
    assert "0.0.0.0" in cmd
    assert call_args[1]["check"] is True


def test_chat_default_options(tmp_path) -> None:  # noqa: ANN001
    """Default host and port are used when no flags are provided."""
    fake_chat_dir = tmp_path / "apps" / "chat"
    fake_chat_dir.mkdir(parents=True)
    (fake_chat_dir / "chainlit_app.py").write_text("# app", encoding="utf-8")

    mock_run = MagicMock()

    with (
        patch("nbadb.cli.commands.chat.CHAT_APP", fake_chat_dir),
        patch("nbadb.cli.commands.chat.shutil.which", return_value="/usr/bin/uv"),
        patch("nbadb.cli.commands.chat.subprocess.run", mock_run),
    ):
        result = runner.invoke(app, ["chat"])

    assert result.exit_code == 0
    assert "http://127.0.0.1:8421" in result.output

    cmd = mock_run.call_args[0][0]
    assert "8421" in cmd
    assert "127.0.0.1" in cmd


def test_chat_keyboard_interrupt(tmp_path) -> None:  # noqa: ANN001
    """KeyboardInterrupt is caught and prints stop message."""
    fake_chat_dir = tmp_path / "apps" / "chat"
    fake_chat_dir.mkdir(parents=True)
    (fake_chat_dir / "chainlit_app.py").write_text("# app", encoding="utf-8")

    with (
        patch("nbadb.cli.commands.chat.CHAT_APP", fake_chat_dir),
        patch("nbadb.cli.commands.chat.shutil.which", return_value="/usr/bin/uv"),
        patch("nbadb.cli.commands.chat.subprocess.run", side_effect=KeyboardInterrupt),
    ):
        result = runner.invoke(app, ["chat"])

    assert result.exit_code == 0
    assert "Chat server stopped" in result.output
