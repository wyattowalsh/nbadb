"""Tests for the DuckDB SQL query logic used by the MCP server.

Tests the core SQL execution and safety validation without requiring
the `mcp` package (which lives in the chat app's own venv).
"""

from __future__ import annotations

import contextlib
import json
from typing import TYPE_CHECKING

import duckdb
import pytest

from nbadb.agent.context import SchemaContext
from nbadb.agent.safety import ReadOnlyGuard

if TYPE_CHECKING:
    from pathlib import Path

_guard = ReadOnlyGuard()


@pytest.fixture()
def sample_db(tmp_path: Path) -> Path:
    """Create a sample DuckDB with test data."""
    db_path = tmp_path / "test.duckdb"
    with duckdb.connect(str(db_path)) as conn:
        conn.execute(
            "CREATE TABLE dim_player "
            "(player_id INT, full_name VARCHAR, is_current BOOLEAN)",
        )
        conn.execute(
            "INSERT INTO dim_player VALUES "
            "(1, 'LeBron James', TRUE), (2, 'Stephen Curry', TRUE)",
        )
        conn.execute(
            "CREATE TABLE fact_player_game_log "
            "(player_id INT, pts INT, reb INT, ast INT)",
        )
        conn.execute(
            "INSERT INTO fact_player_game_log VALUES "
            "(1, 30, 8, 10), (2, 35, 5, 7)",
        )
    return db_path


def _execute_sql(db_path: Path, query: str) -> dict:
    """Mimic the MCP server's run_sql logic."""
    error = _guard.validate(query)
    if error:
        return {"error": f"Query blocked: {error}"}

    safe_sql = _guard.wrap_with_limit(query, max_rows=1000)
    try:
        with duckdb.connect(str(db_path), read_only=True) as conn:
            conn.execute("SET enable_external_access = false")
            with contextlib.suppress(duckdb.CatalogException):
                conn.execute("SET statement_timeout = '30s'")
            result = conn.execute(safe_sql)
            columns = [desc[0] for desc in result.description]
            rows = result.fetchall()
            return {
                "columns": columns,
                "rows": [list(row) for row in rows],
                "row_count": len(rows),
                "sql": safe_sql,
            }
    except duckdb.Error as exc:
        return {"error": f"Query failed: {type(exc).__name__}"}


def test_run_sql_valid_query(sample_db):
    """Valid SELECT query returns structured results."""
    result = _execute_sql(
        sample_db,
        "SELECT full_name, is_current FROM dim_player ORDER BY player_id",
    )
    assert "columns" in result
    assert "rows" in result
    assert result["columns"] == ["full_name", "is_current"]
    assert len(result["rows"]) == 2
    assert result["rows"][0][0] == "LeBron James"


def test_run_sql_blocks_write(sample_db):
    """Write operations are blocked by ReadOnlyGuard."""
    result = _execute_sql(
        sample_db,
        "DELETE FROM dim_player WHERE player_id = 1",
    )
    assert "error" in result
    assert "not allowed" in result["error"].lower()


def test_run_sql_blocks_stacked_queries(sample_db):
    """Stacked queries (semicolon-separated) are blocked."""
    result = _execute_sql(sample_db, "SELECT 1; DROP TABLE dim_player")
    assert "error" in result


def test_run_sql_blocks_file_access(sample_db):
    """File access functions are blocked."""
    result = _execute_sql(
        sample_db, "SELECT * FROM read_csv('/etc/passwd')",
    )
    assert "error" in result


def test_list_tables(sample_db):
    """SchemaContext.get_tables returns all table names."""
    ctx = SchemaContext(sample_db)
    tables = ctx.get_tables()
    assert "dim_player" in tables
    assert "fact_player_game_log" in tables


def test_describe_table(sample_db):
    """SchemaContext.get_columns returns column names and types."""
    ctx = SchemaContext(sample_db)
    cols = ctx.get_columns("dim_player")
    names = [name for name, _ in cols]
    assert "player_id" in names
    assert "full_name" in names
    assert "is_current" in names


def test_run_sql_empty_query(sample_db):
    """Empty query returns error."""
    result = _execute_sql(sample_db, "")
    assert "error" in result


def test_run_sql_result_serializable(sample_db):
    """Results can be JSON-serialized."""
    result = _execute_sql(
        sample_db,
        "SELECT * FROM dim_player",
    )
    # Should not raise
    serialized = json.dumps(result, default=str)
    assert isinstance(serialized, str)
    parsed = json.loads(serialized)
    assert parsed["row_count"] == 2
