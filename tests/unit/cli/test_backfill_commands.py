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


def _insert_journal_entries(path: Path) -> None:
    """Insert sample journal entries for testing non-empty journal paths."""
    conn = duckdb.connect(str(path))
    conn.execute(
        "INSERT INTO _extraction_journal"
        " (endpoint, params, status, started_at, rows_extracted, retry_count)"
        " VALUES"
        " ('box_score_traditional',"
        """  '{"season": "2024-25", "season_type": "Regular Season"}',"""
        "  'done', '2025-01-01 00:00:00', 100, 0),"
        " ('box_score_traditional',"
        """  '{"season": "2024-25", "season_type": "Playoffs"}',"""
        "  'failed', '2025-01-01 01:00:00', 0, 2),"
        " ('league_game_log',"
        """  '{"season": "2024-25", "season_type": "Regular Season"}',"""
        "  'done', '2025-01-02 00:00:00', 50, 0),"
        " ('franchise_history', '{}', 'done', '2025-01-03 00:00:00', 30, 0),"
        " ('play_by_play', '{\"game_id\": \"0022400001\"}',"
        "  'abandoned', '2025-01-04 00:00:00', 0, 5)"
    )
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

    def test_run_dry_run_no_db(self, tmp_path: Path) -> None:
        """--dry-run when database does not exist must exit 1."""
        missing = tmp_path / "nonexistent.duckdb"
        with patch(_SETTINGS_PATH, return_value=_settings_mock(missing)):
            result = runner.invoke(app, ["backfill", "run", "--dry-run"])

        assert result.exit_code == 1
        assert "Database not found" in result.output


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

    def test_gaps_text_output_with_gaps(self, tmp_path: Path) -> None:
        """Text output for gaps renders the table header and gap rows."""
        db_path = tmp_path / "nba.duckdb"
        _make_db(db_path)

        # Use static pattern + a known endpoint so detect_gaps finds a real gap
        # (no journal entries for franchise_history, so expected=1 actual=0).
        with patch(_SETTINGS_PATH, return_value=_settings_mock(db_path)):
            result = runner.invoke(
                app,
                [
                    "backfill",
                    "gaps",
                    "--pattern",
                    "static",
                    "--endpoint",
                    "franchise_history",
                ],
            )

        assert result.exit_code == 0, result.output
        # _print_gap_report renders a table header and data rows
        assert "Endpoint" in result.output
        assert "franchise_history" in result.output
        assert "Summary by pattern" in result.output

    def test_gaps_text_output_no_gaps(self, tmp_path: Path) -> None:
        """Text output when there are no gaps reports 'No gaps detected.'."""
        db_path = tmp_path / "nba.duckdb"
        _make_db(db_path)
        _insert_journal_entries(db_path)

        # franchise_history has a 'done' entry, so static pattern is satisfied
        with patch(_SETTINGS_PATH, return_value=_settings_mock(db_path)):
            result = runner.invoke(
                app,
                [
                    "backfill",
                    "gaps",
                    "--pattern",
                    "static",
                    "--endpoint",
                    "franchise_history",
                ],
            )

        assert result.exit_code == 0, result.output
        assert "No gaps detected" in result.output


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

    def test_completeness_text_output_with_gaps(self, tmp_path: Path) -> None:
        """Text output renders total gaps, by-endpoint, and by-season sections."""
        db_path = tmp_path / "nba.duckdb"
        _make_db(db_path)

        # Filter to static pattern for franchise_history -- 0 done = 1 gap
        with patch(_SETTINGS_PATH, return_value=_settings_mock(db_path)):
            result = runner.invoke(
                app,
                [
                    "backfill",
                    "completeness",
                    "--endpoint",
                    "franchise_history",
                ],
            )

        assert result.exit_code == 0, result.output
        assert "Total gaps" in result.output
        assert "By pattern" in result.output
        assert "By endpoint" in result.output

    def test_completeness_text_output_all_complete(self, tmp_path: Path) -> None:
        """Text output when no gaps says 'All endpoints complete.'."""
        db_path = tmp_path / "nba.duckdb"
        _make_db(db_path)
        _insert_journal_entries(db_path)

        with patch(_SETTINGS_PATH, return_value=_settings_mock(db_path)):
            result = runner.invoke(
                app,
                [
                    "backfill",
                    "completeness",
                    "--endpoint",
                    "franchise_history",
                ],
            )

        assert result.exit_code == 0, result.output
        assert "All endpoints complete" in result.output


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

    # -- count with entries --------------------------------------------------

    def test_journal_count_text_with_entries(self, tmp_path: Path) -> None:
        """Non-empty journal count renders a table with endpoint/status/count."""
        db_path = tmp_path / "nba.duckdb"
        _make_db(db_path)
        _insert_journal_entries(db_path)

        with patch(_SETTINGS_PATH, return_value=_settings_mock(db_path)):
            result = runner.invoke(app, ["backfill", "journal", "--action", "count"])

        assert result.exit_code == 0, result.output
        # Table header
        assert "Endpoint" in result.output
        assert "Status" in result.output
        assert "Count" in result.output
        # At least one endpoint from our fixture
        assert "box_score_traditional" in result.output

    def test_journal_count_json_with_entries(self, tmp_path: Path) -> None:
        """Non-empty journal count as JSON returns list of endpoint/status/count dicts."""
        db_path = tmp_path / "nba.duckdb"
        _make_db(db_path)
        _insert_journal_entries(db_path)

        with patch(_SETTINGS_PATH, return_value=_settings_mock(db_path)):
            result = runner.invoke(
                app,
                ["backfill", "journal", "--action", "count", "--output-format", "json"],
            )

        assert result.exit_code == 0, result.output
        data = json.loads(result.output)
        assert isinstance(data, list)
        assert len(data) > 0
        assert all("endpoint" in d and "status" in d and "count" in d for d in data)

    def test_journal_count_json_empty(self, tmp_path: Path) -> None:
        """Empty journal count as JSON returns an empty list."""
        db_path = tmp_path / "nba.duckdb"
        _make_db(db_path)

        with patch(_SETTINGS_PATH, return_value=_settings_mock(db_path)):
            result = runner.invoke(
                app,
                ["backfill", "journal", "--action", "count", "--output-format", "json"],
            )

        assert result.exit_code == 0, result.output
        data = json.loads(result.output)
        assert data == []

    # -- show with entries ---------------------------------------------------

    def test_journal_show_text_with_entries(self, tmp_path: Path) -> None:
        """Non-empty journal show renders a text table with entries."""
        db_path = tmp_path / "nba.duckdb"
        _make_db(db_path)
        _insert_journal_entries(db_path)

        with patch(_SETTINGS_PATH, return_value=_settings_mock(db_path)):
            result = runner.invoke(
                app,
                ["backfill", "journal", "--action", "show"],
            )

        assert result.exit_code == 0, result.output
        assert "Endpoint" in result.output
        assert "Status" in result.output
        assert "Retries" in result.output
        assert "box_score_traditional" in result.output

    def test_journal_show_text_empty(self, tmp_path: Path) -> None:
        """Empty journal show renders 'No matching journal entries.'."""
        db_path = tmp_path / "nba.duckdb"
        _make_db(db_path)

        with patch(_SETTINGS_PATH, return_value=_settings_mock(db_path)):
            result = runner.invoke(
                app,
                ["backfill", "journal", "--action", "show"],
            )

        assert result.exit_code == 0, result.output
        assert "No matching journal entries" in result.output

    def test_journal_show_json_with_entries(self, tmp_path: Path) -> None:
        """Non-empty journal show as JSON returns a list of entry dicts."""
        db_path = tmp_path / "nba.duckdb"
        _make_db(db_path)
        _insert_journal_entries(db_path)

        with patch(_SETTINGS_PATH, return_value=_settings_mock(db_path)):
            result = runner.invoke(
                app,
                ["backfill", "journal", "--action", "show", "--output-format", "json"],
            )

        assert result.exit_code == 0, result.output
        data = json.loads(result.output)
        assert isinstance(data, list)
        assert len(data) > 0
        assert all("endpoint" in d and "params" in d and "status" in d for d in data)

    # -- reset ---------------------------------------------------------------

    def test_journal_reset_by_endpoint(self, tmp_path: Path) -> None:
        """Reset with --endpoint resets matching entries and reports count."""
        db_path = tmp_path / "nba.duckdb"
        _make_db(db_path)
        _insert_journal_entries(db_path)

        with patch(_SETTINGS_PATH, return_value=_settings_mock(db_path)):
            result = runner.invoke(
                app,
                [
                    "backfill",
                    "journal",
                    "--action",
                    "reset",
                    "--endpoint",
                    "box_score_traditional",
                    "--yes",
                ],
            )

        assert result.exit_code == 0, result.output
        assert "Reset" in result.output
        assert "journal entries" in result.output

    def test_journal_reset_by_status(self, tmp_path: Path) -> None:
        """Reset with --status resets entries matching the given status."""
        db_path = tmp_path / "nba.duckdb"
        _make_db(db_path)
        _insert_journal_entries(db_path)

        with patch(_SETTINGS_PATH, return_value=_settings_mock(db_path)):
            result = runner.invoke(
                app,
                [
                    "backfill",
                    "journal",
                    "--action",
                    "reset",
                    "--status",
                    "failed",
                    "--yes",
                ],
            )

        assert result.exit_code == 0, result.output
        assert "Reset" in result.output

    def test_journal_reset_by_season(self, tmp_path: Path) -> None:
        """Reset with --seasons resets entries whose params match the season."""
        db_path = tmp_path / "nba.duckdb"
        _make_db(db_path)
        _insert_journal_entries(db_path)

        with patch(_SETTINGS_PATH, return_value=_settings_mock(db_path)):
            result = runner.invoke(
                app,
                [
                    "backfill",
                    "journal",
                    "--action",
                    "reset",
                    "--seasons",
                    "2024-25",
                    "--yes",
                ],
            )

        assert result.exit_code == 0, result.output
        assert "Reset" in result.output

    def test_journal_reset_no_filters(self, tmp_path: Path) -> None:
        """Reset without any filter flags must exit 1."""
        db_path = tmp_path / "nba.duckdb"
        _make_db(db_path)

        with patch(_SETTINGS_PATH, return_value=_settings_mock(db_path)):
            result = runner.invoke(
                app,
                ["backfill", "journal", "--action", "reset", "--yes"],
            )

        assert result.exit_code == 1
        assert "Provide at least one" in result.output

    # -- clear ---------------------------------------------------------------

    def test_journal_clear_by_endpoint(self, tmp_path: Path) -> None:
        """Clear with --endpoint deletes matching entries and reports count."""
        db_path = tmp_path / "nba.duckdb"
        _make_db(db_path)
        _insert_journal_entries(db_path)

        with patch(_SETTINGS_PATH, return_value=_settings_mock(db_path)):
            result = runner.invoke(
                app,
                [
                    "backfill",
                    "journal",
                    "--action",
                    "clear",
                    "--endpoint",
                    "play_by_play",
                    "--yes",
                ],
            )

        assert result.exit_code == 0, result.output
        assert "Cleared" in result.output
        assert "journal entries" in result.output

    def test_journal_clear_by_status(self, tmp_path: Path) -> None:
        """Clear with --status deletes entries matching the given status."""
        db_path = tmp_path / "nba.duckdb"
        _make_db(db_path)
        _insert_journal_entries(db_path)

        with patch(_SETTINGS_PATH, return_value=_settings_mock(db_path)):
            result = runner.invoke(
                app,
                [
                    "backfill",
                    "journal",
                    "--action",
                    "clear",
                    "--status",
                    "abandoned",
                    "--yes",
                ],
            )

        assert result.exit_code == 0, result.output
        assert "Cleared" in result.output

    def test_journal_clear_by_season(self, tmp_path: Path) -> None:
        """Clear with --seasons deletes entries whose params match the season."""
        db_path = tmp_path / "nba.duckdb"
        _make_db(db_path)
        _insert_journal_entries(db_path)

        with patch(_SETTINGS_PATH, return_value=_settings_mock(db_path)):
            result = runner.invoke(
                app,
                [
                    "backfill",
                    "journal",
                    "--action",
                    "clear",
                    "--seasons",
                    "2024-25",
                    "--yes",
                ],
            )

        assert result.exit_code == 0, result.output
        assert "Cleared" in result.output

    def test_journal_clear_no_filters(self, tmp_path: Path) -> None:
        """Clear without any filter flags must exit 1."""
        db_path = tmp_path / "nba.duckdb"
        _make_db(db_path)

        with patch(_SETTINGS_PATH, return_value=_settings_mock(db_path)):
            result = runner.invoke(
                app,
                ["backfill", "journal", "--action", "clear", "--yes"],
            )

        assert result.exit_code == 1
        assert "Provide at least one" in result.output


# ---------------------------------------------------------------------------
# _describe_filters
# ---------------------------------------------------------------------------


class TestDescribeFilters:
    def test_describe_all_filters(self) -> None:
        """All three filters produce an AND-joined description."""
        from nbadb.cli.commands.backfill import _describe_filters

        result = _describe_filters(
            endpoints=["box_score_traditional"],
            seasons=["2024-25"],
            status_filter="failed",
        )
        assert "endpoint=box_score_traditional" in result
        assert "seasons=2024-25" in result
        assert "status=failed" in result
        assert " AND " in result

    def test_describe_no_filters(self) -> None:
        """No filters produce '(all)' description."""
        from nbadb.cli.commands.backfill import _describe_filters

        result = _describe_filters(endpoints=None, seasons=None, status_filter=None)
        assert result == "(all)"

    def test_describe_endpoint_only(self) -> None:
        """Single endpoint filter description."""
        from nbadb.cli.commands.backfill import _describe_filters

        result = _describe_filters(
            endpoints=["play_by_play", "box_score_traditional"],
            seasons=None,
            status_filter=None,
        )
        assert "endpoint=play_by_play,box_score_traditional" in result
        assert " AND " not in result


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
