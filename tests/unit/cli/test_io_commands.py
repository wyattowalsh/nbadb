"""Unit tests for nbadb I/O CLI commands: export, download, upload, ask."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import duckdb
from typer.testing import CliRunner

from nbadb.cli.app import app

runner = CliRunner()

# ---------------------------------------------------------------------------
# Patch paths
# Because each command uses lazy imports (inside the function body), the
# imported names are never bound to the command module's namespace.  We must
# patch at the *source* module where the symbol is defined.
# ---------------------------------------------------------------------------

_MULTI_LOADER = "nbadb.load.multi.create_multi_loader"
_KAGGLE_CLIENT = "nbadb.kaggle.client.KaggleClient"
_GET_SETTINGS = "nbadb.core.config.get_settings"
_QUERY_AGENT = "nbadb.agent.query.QueryAgent"

# ---------------------------------------------------------------------------
# export
# ---------------------------------------------------------------------------


def test_export_no_db(tmp_path: Path) -> None:
    """Exit 1 with 'Database not found' when the DuckDB file is absent."""
    result = runner.invoke(app, ["export", "--data-dir", str(tmp_path / "nonexistent_xyz")])
    assert result.exit_code == 1
    assert "Database not found" in result.output


def test_export_success(tmp_path: Path) -> None:
    """Exit 0 when a valid DB exists and create_multi_loader is patched."""
    db_file = tmp_path / "nba.duckdb"
    conn = duckdb.connect(str(db_file))
    conn.execute("CREATE TABLE dim_player AS SELECT 1 AS player_id, 'Test' AS player_name")
    conn.close()

    mock_loader = MagicMock()
    with patch(_MULTI_LOADER, return_value=mock_loader):
        result = runner.invoke(app, ["export", "--data-dir", str(tmp_path)])

    assert result.exit_code == 0, result.output


def test_export_no_tables(tmp_path: Path) -> None:
    """Exit 1 with 'No tables found' when the DB has only internal tables."""
    db_file = tmp_path / "nba.duckdb"
    conn = duckdb.connect(str(db_file))
    conn.execute("CREATE TABLE _pipeline_meta AS SELECT 1 AS id")
    conn.close()

    result = runner.invoke(app, ["export", "--data-dir", str(tmp_path)])
    assert result.exit_code == 1
    assert "No tables found" in result.output


# ---------------------------------------------------------------------------
# download
# ---------------------------------------------------------------------------


def test_download_success() -> None:
    """Exit 0 and print 'Downloaded to' when KaggleClient.download succeeds."""
    with patch(_KAGGLE_CLIENT) as mock_cls:
        mock_cls.return_value.download.return_value = "/tmp/data.zip"
        result = runner.invoke(app, ["download"])
    assert result.exit_code == 0
    assert "Downloaded to" in result.output


def test_download_failure() -> None:
    """Exit 1 and print 'Download failed' when KaggleClient.download raises."""
    with patch(_KAGGLE_CLIENT) as mock_cls:
        mock_cls.return_value.download.side_effect = RuntimeError("no api key")
        result = runner.invoke(app, ["download"])
    assert result.exit_code == 1
    # CliRunner mixes stdout and stderr into output by default
    assert "Download failed" in result.output


# ---------------------------------------------------------------------------
# upload
# ---------------------------------------------------------------------------


def test_upload_success() -> None:
    """Exit 0 and print 'Upload complete' when KaggleClient succeeds."""
    with patch(_KAGGLE_CLIENT) as mock_cls:
        mock_cls.return_value.ensure_metadata.return_value = None
        mock_cls.return_value.upload.return_value = None
        result = runner.invoke(app, ["upload"])
    assert result.exit_code == 0
    assert "Upload complete" in result.output


def test_upload_failure() -> None:
    """Exit 1 and print 'Upload failed' when KaggleClient raises."""
    with patch(_KAGGLE_CLIENT) as mock_cls:
        mock_cls.return_value.ensure_metadata.side_effect = RuntimeError("no creds")
        result = runner.invoke(app, ["upload"])
    assert result.exit_code == 1
    assert "Upload failed" in result.output


def test_upload_message_option() -> None:
    """Exit 0 when --message option is passed alongside a patched KaggleClient."""
    with patch(_KAGGLE_CLIENT) as mock_cls:
        mock_cls.return_value.ensure_metadata.return_value = None
        mock_cls.return_value.upload.return_value = None
        result = runner.invoke(app, ["upload", "--message", "test run"])
    assert result.exit_code == 0


# ---------------------------------------------------------------------------
# ask
# ---------------------------------------------------------------------------


def test_ask_success() -> None:
    """Exit 0 and print QueryAgent answer when duckdb_path is configured."""
    mock_settings = MagicMock()
    mock_settings.duckdb_path = Path("/tmp/test.duckdb")

    with (
        patch(_GET_SETTINGS, return_value=mock_settings),
        patch(_QUERY_AGENT) as mock_agent_cls,
    ):
        mock_agent_cls.return_value.ask.return_value = "LeBron scored 30"
        result = runner.invoke(app, ["ask", "How many points did LeBron score?"])

    assert result.exit_code == 0, result.output
    assert "LeBron scored 30" in result.output


def test_ask_no_duckdb_path() -> None:
    """Exit 1 when duckdb_path is None in settings."""
    mock_settings = MagicMock()
    mock_settings.duckdb_path = None

    with patch(_GET_SETTINGS, return_value=mock_settings):
        result = runner.invoke(app, ["ask", "What is the answer?"])

    assert result.exit_code == 1
