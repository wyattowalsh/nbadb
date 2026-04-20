"""Tests for nbadb.agent.context.SchemaContext."""

from __future__ import annotations

from typing import TYPE_CHECKING

import duckdb
import pytest

if TYPE_CHECKING:
    from pathlib import Path

from nbadb.agent.context import SchemaContext

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def empty_db(tmp_path: Path) -> Path:
    """Create an empty DuckDB file (no user tables)."""
    db_path = tmp_path / "empty.duckdb"
    with duckdb.connect(str(db_path)) as conn:
        conn.execute("SELECT 1")
    return db_path


@pytest.fixture
def populated_db(tmp_path: Path) -> Path:
    """Create a DuckDB file with known tables and columns."""
    db_path = tmp_path / "populated.duckdb"
    with duckdb.connect(str(db_path)) as conn:
        conn.execute(
            "CREATE TABLE dim_player (  player_id INTEGER, full_name VARCHAR, is_current BOOLEAN)"
        )
        conn.execute(
            "CREATE TABLE dim_team (  team_id INTEGER, abbreviation VARCHAR, city VARCHAR)"
        )
        # Internal table (underscore prefix) should be excluded by get_user_tables
        conn.execute("CREATE TABLE _pipeline_metadata (  table_name VARCHAR, row_count INTEGER)")
    return db_path


# ---------------------------------------------------------------------------
# TestSchemaContextInit
# ---------------------------------------------------------------------------


class TestSchemaContextInit:
    def test_instantiation(self, empty_db: Path) -> None:
        ctx = SchemaContext(empty_db)
        assert ctx._path == empty_db

    def test_instantiation_with_nonexistent_path(self, tmp_path: Path) -> None:
        """SchemaContext stores the path; errors only occur on access."""
        ctx = SchemaContext(tmp_path / "does_not_exist.duckdb")
        assert ctx._path.name == "does_not_exist.duckdb"


# ---------------------------------------------------------------------------
# TestGetTables
# ---------------------------------------------------------------------------


class TestGetTables:
    def test_empty_database_returns_empty_list(self, empty_db: Path) -> None:
        ctx = SchemaContext(empty_db)
        tables = ctx.get_tables()
        assert tables == []

    def test_populated_database_returns_user_tables(self, populated_db: Path) -> None:
        ctx = SchemaContext(populated_db)
        tables = ctx.get_tables()
        assert "dim_player" in tables
        assert "dim_team" in tables

    def test_excludes_internal_tables(self, populated_db: Path) -> None:
        ctx = SchemaContext(populated_db)
        tables = ctx.get_tables()
        assert "_pipeline_metadata" not in tables

    def test_tables_are_sorted(self, populated_db: Path) -> None:
        ctx = SchemaContext(populated_db)
        tables = ctx.get_tables()
        assert tables == sorted(tables)


# ---------------------------------------------------------------------------
# TestGetColumns
# ---------------------------------------------------------------------------


class TestGetColumns:
    def test_returns_column_names_and_types(self, populated_db: Path) -> None:
        ctx = SchemaContext(populated_db)
        cols = ctx.get_columns("dim_player")
        col_names = [name for name, _ in cols]
        assert "player_id" in col_names
        assert "full_name" in col_names
        assert "is_current" in col_names

    def test_column_types_are_strings(self, populated_db: Path) -> None:
        ctx = SchemaContext(populated_db)
        cols = ctx.get_columns("dim_player")
        for name, dtype in cols:
            assert isinstance(name, str)
            assert isinstance(dtype, str)

    def test_nonexistent_table_returns_empty(self, populated_db: Path) -> None:
        ctx = SchemaContext(populated_db)
        cols = ctx.get_columns("nonexistent_table")
        assert cols == []

    def test_column_order_matches_ordinal(self, populated_db: Path) -> None:
        ctx = SchemaContext(populated_db)
        cols = ctx.get_columns("dim_player")
        col_names = [name for name, _ in cols]
        assert col_names == ["player_id", "full_name", "is_current"]


# ---------------------------------------------------------------------------
# TestBuildPromptContext
# ---------------------------------------------------------------------------


class TestBuildPromptContext:
    def test_empty_database_message(self, empty_db: Path) -> None:
        ctx = SchemaContext(empty_db)
        result = ctx.build_prompt_context()
        assert result == "No tables found in the database."

    def test_populated_database_contains_table_names(self, populated_db: Path) -> None:
        ctx = SchemaContext(populated_db)
        result = ctx.build_prompt_context()
        assert "dim_player" in result
        assert "dim_team" in result

    def test_populated_database_contains_column_info(self, populated_db: Path) -> None:
        ctx = SchemaContext(populated_db)
        result = ctx.build_prompt_context()
        assert "player_id" in result
        assert "full_name" in result

    def test_result_is_string(self, populated_db: Path) -> None:
        ctx = SchemaContext(populated_db)
        result = ctx.build_prompt_context()
        assert isinstance(result, str)

    def test_result_starts_with_header(self, populated_db: Path) -> None:
        ctx = SchemaContext(populated_db)
        result = ctx.build_prompt_context()
        assert result.startswith("Available tables and columns:")

    def test_excludes_internal_tables_from_context(self, populated_db: Path) -> None:
        ctx = SchemaContext(populated_db)
        result = ctx.build_prompt_context()
        assert "_pipeline_metadata" not in result
