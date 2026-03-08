"""Unit tests for nbadb status and schema CLI commands."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import duckdb
from typer.testing import CliRunner

from nbadb.cli.app import app

runner = CliRunner()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_db_with_tables(path: object) -> None:
    """Create a DuckDB file with the three pipeline tables (empty)."""
    conn = duckdb.connect(str(path))
    conn.execute(
        "CREATE TABLE _pipeline_watermarks ("
        "  table_name VARCHAR,"
        "  watermark_type VARCHAR,"
        "  watermark_value VARCHAR,"
        "  last_updated TIMESTAMP,"
        "  row_count_at_watermark BIGINT,"
        "  PRIMARY KEY (table_name, watermark_type)"
        ")"
    )
    conn.execute(
        "CREATE TABLE _extraction_journal ("
        "  endpoint VARCHAR,"
        "  params VARCHAR,"
        "  status VARCHAR,"
        "  started_at TIMESTAMP,"
        "  completed_at TIMESTAMP,"
        "  rows_extracted BIGINT,"
        "  error_message VARCHAR,"
        "  PRIMARY KEY (endpoint, params)"
        ")"
    )
    conn.execute(
        "CREATE TABLE _pipeline_metadata ("
        "  table_name VARCHAR PRIMARY KEY,"
        "  last_updated TIMESTAMP,"
        "  row_count BIGINT,"
        "  schema_hash VARCHAR"
        ")"
    )
    conn.close()


def _mock_transformer(output_table: str, depends_on: list[str] | None = None) -> MagicMock:
    t = MagicMock()
    t.output_table = output_table
    t.depends_on = depends_on or []
    return t


# ---------------------------------------------------------------------------
# status command tests
# ---------------------------------------------------------------------------


class TestStatusCommand:
    def test_status_no_db_file(self, tmp_path: object) -> None:
        """--data-dir pointing to nonexistent subdir exits 1 with 'Database not found'."""
        missing = tmp_path / "nonexistent_xyz"
        result = runner.invoke(app, ["status", "--data-dir", str(missing)])
        assert result.exit_code == 1
        assert "Database not found" in result.output

    def test_status_empty_watermarks(self, tmp_path: object) -> None:
        """Empty _pipeline_watermarks table shows '(empty)'."""
        db_path = tmp_path / "nba.duckdb"
        _make_db_with_tables(db_path)
        result = runner.invoke(app, ["status", "--data-dir", str(tmp_path)])
        assert result.exit_code == 0
        assert "(empty)" in result.output

    def test_status_empty_journal(self, tmp_path: object) -> None:
        """Empty _extraction_journal table shows '(empty)'."""
        db_path = tmp_path / "nba.duckdb"
        _make_db_with_tables(db_path)
        result = runner.invoke(app, ["status", "--data-dir", str(tmp_path)])
        assert result.exit_code == 0
        assert "Extraction Journal" in result.output
        assert "(empty)" in result.output

    def test_status_populated_watermarks(self, tmp_path: object) -> None:
        """A watermark row is displayed in the status output."""
        db_path = tmp_path / "nba.duckdb"
        _make_db_with_tables(db_path)
        conn = duckdb.connect(str(db_path))
        conn.execute(
            "INSERT INTO _pipeline_watermarks VALUES "
            "('stg_game_log', 'season', '2024-25', '2024-01-01 00:00:00', 5000)"
        )
        conn.close()
        result = runner.invoke(app, ["status", "--data-dir", str(tmp_path)])
        assert result.exit_code == 0
        assert "stg_game_log" in result.output

    def test_status_missing_tables(self, tmp_path: object) -> None:
        """DuckDB file without pipeline tables shows fallback '(no watermark data)'."""
        db_path = tmp_path / "nba.duckdb"
        # Create an empty DuckDB file (no pipeline tables)
        conn = duckdb.connect(str(db_path))
        conn.close()
        result = runner.invoke(app, ["status", "--data-dir", str(tmp_path)])
        assert result.exit_code == 0
        assert "(no watermark data)" in result.output

    def test_status_json_output_structure(self, tmp_path: object) -> None:
        """--output-format json produces valid JSON with expected keys."""
        db_path = tmp_path / "nba.duckdb"
        _make_db_with_tables(db_path)
        result = runner.invoke(
            app, ["status", "--data-dir", str(tmp_path), "--output-format", "json"]
        )
        assert result.exit_code == 0
        data = json.loads(result.output)
        assert "watermarks" in data
        assert "journal" in data
        assert "metadata" in data

    def test_status_json_output_watermarks_is_list(self, tmp_path: object) -> None:
        """JSON output 'watermarks' is a list."""
        db_path = tmp_path / "nba.duckdb"
        _make_db_with_tables(db_path)
        result = runner.invoke(
            app, ["status", "--data-dir", str(tmp_path), "--output-format", "json"]
        )
        assert result.exit_code == 0
        data = json.loads(result.output)
        assert isinstance(data["watermarks"], list)

    def test_status_json_populated_watermark_entry(self, tmp_path: object) -> None:
        """JSON output 'watermarks' contains row data with expected keys."""
        db_path = tmp_path / "nba.duckdb"
        _make_db_with_tables(db_path)
        conn = duckdb.connect(str(db_path))
        conn.execute(
            "INSERT INTO _pipeline_watermarks VALUES "
            "('dim_date', 'last_load', '2025-26', '2025-01-01 00:00:00', 1000)"
        )
        conn.close()
        result = runner.invoke(
            app, ["status", "--data-dir", str(tmp_path), "--output-format", "json"]
        )
        assert result.exit_code == 0
        data = json.loads(result.output)
        assert len(data["watermarks"]) == 1
        entry = data["watermarks"][0]
        assert entry["table"] == "dim_date"
        assert entry["value"] == "2025-26"


# ---------------------------------------------------------------------------
# schema command tests
# ---------------------------------------------------------------------------

DISCOVER_PATH = "nbadb.cli.commands.schema.discover_all_transformers"
_DOCS_AUTOGEN_PATH = "nbadb.cli.commands.docs_autogen.generate_docs_artifacts"


class TestSchemaCommand:
    def test_schema_lists_all_tables(self) -> None:
        """All mocked output_tables appear in the listing output."""
        mock_transformers = [
            _mock_transformer("dim_player"),
            _mock_transformer("fact_game_log"),
        ]
        with patch(DISCOVER_PATH, return_value=mock_transformers):
            result = runner.invoke(app, ["schema"])
        assert result.exit_code == 0
        assert "dim_player" in result.output
        assert "fact_game_log" in result.output

    def test_schema_no_argument_groups_by_prefix(self) -> None:
        """Without a table argument the output contains a 'Dimensions (dim_)' heading."""
        mock_transformers = [
            _mock_transformer("dim_player"),
            _mock_transformer("fact_game_log"),
        ]
        with patch(DISCOVER_PATH, return_value=mock_transformers):
            result = runner.invoke(app, ["schema"])
        assert result.exit_code == 0
        assert "Dimensions (dim_)" in result.output

    def test_schema_detail_found(self) -> None:
        """Invoking schema with a table name shows table and depends_on."""
        mock_transformers = [
            _mock_transformer("dim_player", depends_on=["stg_x"]),
        ]
        with patch(DISCOVER_PATH, return_value=mock_transformers):
            result = runner.invoke(app, ["schema", "dim_player"])
        assert result.exit_code == 0
        assert "dim_player" in result.output
        assert "depends_on" in result.output.lower() or "Depends on" in result.output

    def test_schema_detail_not_found(self) -> None:
        """Invoking schema with an unknown table name exits 1."""
        with patch(DISCOVER_PATH, return_value=[]):
            result = runner.invoke(app, ["schema", "nonexistent"])
        assert result.exit_code == 1

    def test_schema_empty_no_tables(self) -> None:
        """When discovery returns no transformers, output shows 'Total: 0 tables'."""
        with patch(DISCOVER_PATH, return_value=[]):
            result = runner.invoke(app, ["schema"])
        assert result.exit_code == 0
        assert "Total: 0 tables" in result.output


# ---------------------------------------------------------------------------
# docs-autogen command tests
# ---------------------------------------------------------------------------


class TestDocsAutogenCommand:
    def test_docs_autogen_invokes_generator(self, tmp_path: object) -> None:
        docs_root = Path(str(tmp_path))
        updated = [docs_root / "schema" / "star-reference.mdx"]
        unchanged = [docs_root / "lineage" / "lineage.json"]

        with patch(_DOCS_AUTOGEN_PATH, return_value=(updated, unchanged)) as mock_generate:
            result = runner.invoke(app, ["docs-autogen", "--docs-root", str(docs_root)])

        assert result.exit_code == 0, result.output
        mock_generate.assert_called_once_with(docs_root)
        assert "updated: " in result.output
        assert "unchanged: " in result.output
        assert "Docs autogen complete (1 updated, 1 unchanged)." in result.output


# ---------------------------------------------------------------------------
# migrate command tests
# ---------------------------------------------------------------------------

_DB_MANAGER_PATH = "nbadb.core.db.DBManager"


class TestMigrateCommand:
    def test_migrate_runs_successfully(self, tmp_path: object) -> None:
        """migrate calls DBManager.init() and exits 0."""
        mock_db = MagicMock()
        with patch(_DB_MANAGER_PATH, return_value=mock_db):
            result = runner.invoke(app, ["migrate", "--data-dir", str(tmp_path)])
        assert result.exit_code == 0, result.output
        mock_db.init.assert_called_once()
        mock_db.close.assert_called_once()
        assert "Migration complete" in result.output

    def test_migrate_failure_exits_nonzero(self, tmp_path: object) -> None:
        """When DBManager.init() raises, exit 1 with error output."""
        mock_db = MagicMock()
        mock_db.init.side_effect = RuntimeError("disk full")
        with patch(_DB_MANAGER_PATH, return_value=mock_db):
            result = runner.invoke(app, ["migrate", "--data-dir", str(tmp_path)])
        assert result.exit_code == 1
        mock_db.close.assert_called_once()
        assert "Migration failed" in result.output or "RuntimeError" in result.output

    def test_migrate_idempotent(self, tmp_path: object) -> None:
        """Calling migrate twice on the same db does not raise (init is idempotent)."""
        mock_db = MagicMock()
        with patch(_DB_MANAGER_PATH, return_value=mock_db):
            result1 = runner.invoke(app, ["migrate", "--data-dir", str(tmp_path)])
            result2 = runner.invoke(app, ["migrate", "--data-dir", str(tmp_path)])
        assert result1.exit_code == 0, result1.output
        assert result2.exit_code == 0, result2.output
        assert mock_db.init.call_count == 2
