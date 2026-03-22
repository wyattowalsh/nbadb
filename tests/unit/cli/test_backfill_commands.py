"""Unit tests for the ``nbadb backfill`` CLI subcommands."""

from __future__ import annotations

import json
from typing import TYPE_CHECKING
from unittest.mock import MagicMock, patch

import duckdb
from typer.testing import CliRunner

from nbadb.cli.app import app

if TYPE_CHECKING:
    from pathlib import Path

runner = CliRunner()

_SETTINGS_PATH = "nbadb.cli.commands.backfill._build_settings"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_db(path: Path) -> None:
    """Create a DuckDB file with the pipeline tables needed by backfill commands."""
    conn = duckdb.connect(str(path))
    conn.execute("""
        CREATE TABLE _pipeline_watermarks (
            table_name VARCHAR NOT NULL,
            watermark_type VARCHAR NOT NULL,
            watermark_value VARCHAR,
            last_updated TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            row_count_at_watermark BIGINT,
            PRIMARY KEY (table_name, watermark_type)
        )
    """)
    conn.execute("""
        CREATE TABLE _extraction_journal (
            endpoint VARCHAR NOT NULL,
            params VARCHAR,
            status VARCHAR NOT NULL,
            started_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            completed_at TIMESTAMP,
            rows_extracted BIGINT,
            error_message VARCHAR,
            retry_count INTEGER DEFAULT 0,
            PRIMARY KEY (endpoint, params)
        )
    """)
    conn.execute("""
        CREATE TABLE _pipeline_metrics (
            endpoint VARCHAR NOT NULL,
            run_timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            duration_seconds FLOAT,
            rows_extracted BIGINT,
            error_count INT DEFAULT 0,
            PRIMARY KEY (endpoint, run_timestamp)
        )
    """)
    conn.close()


def _settings_mock(db_path: Path) -> MagicMock:
    """Return a mock settings object whose ``duckdb_path`` points at *db_path*."""
    return MagicMock(duckdb_path=db_path)


# ---------------------------------------------------------------------------
# backfill run
# ---------------------------------------------------------------------------


class TestBackfillRun:
    def test_run_extract_only_and_transform_only_conflict(self) -> None:
        """--extract-only and --transform-only together must exit 1."""
        result = runner.invoke(
            app,
            ["backfill", "run", "--extract-only", "--transform-only"],
        )
        assert result.exit_code == 1
        assert "Cannot use --extract-only and --transform-only together" in result.output

    def test_run_dry_run(self, tmp_path: Path) -> None:
        """--dry-run prints a plan summary without executing the pipeline."""
        db_path = tmp_path / "nba.duckdb"
        _make_db(db_path)

        with patch(_SETTINGS_PATH, return_value=_settings_mock(db_path)):
            result = runner.invoke(app, ["backfill", "run", "--dry-run"])

        assert result.exit_code == 0, result.output
        assert "Backfill plan" in result.output


# ---------------------------------------------------------------------------
# backfill gaps
# ---------------------------------------------------------------------------


class TestBackfillGaps:
    def test_gaps_no_db(self, tmp_path: Path) -> None:
        """Missing database file must exit 1 with 'Database not found'."""
        missing = tmp_path / "nonexistent.duckdb"
        with patch(_SETTINGS_PATH, return_value=_settings_mock(missing)):
            result = runner.invoke(app, ["backfill", "gaps"])

        assert result.exit_code == 1
        assert "Database not found" in result.output

    def test_gaps_json_output(self, tmp_path: Path) -> None:
        """JSON output for gaps contains 'gaps' and 'summary' keys."""
        db_path = tmp_path / "nba.duckdb"
        _make_db(db_path)

        with patch(_SETTINGS_PATH, return_value=_settings_mock(db_path)):
            result = runner.invoke(
                app,
                [
                    "backfill",
                    "gaps",
                    "--output-format",
                    "json",
                    "--pattern",
                    "static",
                    "--endpoint",
                    "franchise_history",
                ],
            )

        assert result.exit_code == 0, result.output
        data = json.loads(result.output)
        assert "gaps" in data
        assert "summary" in data


# ---------------------------------------------------------------------------
# backfill completeness
# ---------------------------------------------------------------------------


class TestBackfillCompleteness:
    def test_completeness_no_db(self, tmp_path: Path) -> None:
        """Missing database file must exit 1 with 'Database not found'."""
        missing = tmp_path / "nonexistent.duckdb"
        with patch(_SETTINGS_PATH, return_value=_settings_mock(missing)):
            result = runner.invoke(app, ["backfill", "completeness"])

        assert result.exit_code == 1
        assert "Database not found" in result.output

    def test_completeness_json_output(self, tmp_path: Path) -> None:
        """JSON output for completeness has the expected top-level keys."""
        db_path = tmp_path / "nba.duckdb"
        _make_db(db_path)

        with patch(_SETTINGS_PATH, return_value=_settings_mock(db_path)):
            result = runner.invoke(
                app,
                ["backfill", "completeness", "--output-format", "json"],
            )

        assert result.exit_code == 0, result.output
        data = json.loads(result.output)
        assert "summary" in data
        assert "by_season" in data
        assert "by_endpoint" in data
        assert "total_gaps" in data


# ---------------------------------------------------------------------------
# backfill journal
# ---------------------------------------------------------------------------


class TestBackfillJournal:
    def test_journal_count_empty(self, tmp_path: Path) -> None:
        """An empty journal must report 'Journal is empty.'."""
        db_path = tmp_path / "nba.duckdb"
        _make_db(db_path)

        with patch(_SETTINGS_PATH, return_value=_settings_mock(db_path)):
            result = runner.invoke(app, ["backfill", "journal", "--action", "count"])

        assert result.exit_code == 0, result.output
        assert "Journal is empty" in result.output

    def test_journal_show_empty_json(self, tmp_path: Path) -> None:
        """An empty journal with --output-format json returns an empty JSON array."""
        db_path = tmp_path / "nba.duckdb"
        _make_db(db_path)

        with patch(_SETTINGS_PATH, return_value=_settings_mock(db_path)):
            result = runner.invoke(
                app,
                ["backfill", "journal", "--action", "show", "--output-format", "json"],
            )

        assert result.exit_code == 0, result.output
        data = json.loads(result.output)
        assert data == []

    def test_journal_invalid_action(self, tmp_path: Path) -> None:
        """An unknown --action value must exit 1 with 'Unknown action'."""
        db_path = tmp_path / "nba.duckdb"
        _make_db(db_path)

        with patch(_SETTINGS_PATH, return_value=_settings_mock(db_path)):
            result = runner.invoke(
                app,
                ["backfill", "journal", "--action", "bogus"],
            )

        assert result.exit_code == 1
        assert "Unknown action" in result.output

    def test_journal_invalid_status(self, tmp_path: Path) -> None:
        """An invalid --status value must exit 1 with validation message (HR-S-005)."""
        db_path = tmp_path / "nba.duckdb"
        _make_db(db_path)

        with patch(_SETTINGS_PATH, return_value=_settings_mock(db_path)):
            result = runner.invoke(
                app,
                ["backfill", "journal", "--status", "pending"],
            )

        assert result.exit_code == 1
        assert "Invalid status" in result.output
        assert "Must be one of" in result.output


# ---------------------------------------------------------------------------
# Season format validation
# ---------------------------------------------------------------------------


class TestSeasonValidation:
    def test_season_bad_hyphen_position(self) -> None:
        """A season like '24-2025' (hyphen NOT at position 4) must error (HR-S-006)."""
        result = runner.invoke(
            app,
            ["backfill", "run", "--seasons", "24-2025"],
        )
        assert result.exit_code != 0
        assert "Invalid season" in result.output

    def test_season_non_numeric_format(self) -> None:
        """A season like 'abcd-ef' (non-numeric) must error (HR-S-006)."""
        result = runner.invoke(
            app,
            ["backfill", "run", "--seasons", "abcd-ef"],
        )
        assert result.exit_code != 0
        assert "Invalid season" in result.output
