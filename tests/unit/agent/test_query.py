"""Tests for nbadb.agent.query.QueryAgent."""

from __future__ import annotations

from typing import TYPE_CHECKING
from unittest.mock import MagicMock, patch

import duckdb
import pytest

if TYPE_CHECKING:
    from pathlib import Path

from nbadb.agent.query import _PATTERNS, QueryAgent
from nbadb.agent.safety import MAX_RESULT_ROWS

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


@pytest.fixture
def tmp_db(tmp_path: Path) -> Path:
    """Create a minimal DuckDB file with a test table."""
    db_path = tmp_path / "test.duckdb"
    with duckdb.connect(str(db_path)) as conn:
        conn.execute(
            "CREATE TABLE dim_player (  player_id INTEGER, full_name VARCHAR, is_current BOOLEAN)"
        )
        conn.execute("INSERT INTO dim_player VALUES (1, 'Test Player', TRUE)")
    return db_path


@pytest.fixture
def agent(tmp_db: Path) -> QueryAgent:
    return QueryAgent(tmp_db)


@pytest.fixture
def agent_empty(tmp_path: Path) -> QueryAgent:
    """Agent pointing to an empty database (no tables)."""
    db_path = tmp_path / "empty.duckdb"
    with duckdb.connect(str(db_path)) as conn:
        conn.execute("SELECT 1")  # just create the file
    return QueryAgent(db_path)


# ---------------------------------------------------------------------------
# TestQueryAgentInit
# ---------------------------------------------------------------------------


class TestQueryAgentInit:
    def test_creates_with_path(self, tmp_db: Path) -> None:
        agent = QueryAgent(tmp_db)
        assert agent._path == tmp_db

    def test_has_readonly_guard(self, agent: QueryAgent) -> None:
        from nbadb.agent.safety import ReadOnlyGuard

        assert isinstance(agent._guard, ReadOnlyGuard)

    def test_has_schema_context(self, agent: QueryAgent) -> None:
        from nbadb.agent.context import SchemaContext

        assert isinstance(agent._context, SchemaContext)


# ---------------------------------------------------------------------------
# TestQueryAgentPatternMatching
# ---------------------------------------------------------------------------


class TestQueryAgentPatternMatching:
    """Verify every compiled pattern matches its expected trigger phrases."""

    @pytest.mark.parametrize(
        "question,expected_fragment",
        [
            ("who led in scoring last season?", "total_pts"),
            ("who led scoring this year?", "total_pts"),
            ("which player had the most points?", "total_pts"),
            ("who had the most assists this season?", "total_ast"),
            ("who had the most rebounds?", "total_reb"),
            ("show team standings", "fact_standings"),
            ("what are the standings?", "fact_standings"),
            ("how many games are there?", "_pipeline_metadata"),
            ("how many records do you have?", "_pipeline_metadata"),
        ],
    )
    def test_pattern_matches_trigger_phrase(
        self, agent: QueryAgent, question: str, expected_fragment: str
    ) -> None:
        sql = agent._match_pattern(question)
        assert sql is not None, f"No pattern matched for: {question!r}"
        assert expected_fragment in sql

    def test_unmatched_input_returns_schema_context(self, agent: QueryAgent) -> None:
        result = agent.ask("what is the meaning of life?")
        assert "couldn't match" in result.lower()
        assert "schema" in result.lower() or "tables" in result.lower()

    def test_unmatched_input_does_not_contain_traceback(self, agent: QueryAgent) -> None:
        result = agent.ask("random gibberish xyz 12345")
        assert "Traceback" not in result
        assert "Error" not in result

    def test_all_patterns_have_ignorecase(self) -> None:
        for pattern, _sql in _PATTERNS:
            assert pattern.flags & 2, (  # re.IGNORECASE == 2
                f"Pattern {pattern.pattern!r} missing IGNORECASE flag"
            )

    def test_pattern_count(self) -> None:
        """Sanity check: we expect 6 patterns."""
        assert len(_PATTERNS) == 6


# ---------------------------------------------------------------------------
# TestQueryAgentExecution
# ---------------------------------------------------------------------------


class TestQueryAgentExecution:
    def test_execute_returns_formatted_table(self, agent: QueryAgent) -> None:
        mock_result = MagicMock()
        mock_result.description = [("player_id",), ("full_name",), ("total_pts",)]
        mock_result.fetchall.return_value = [(1, "Test Player", 2500)]

        mock_conn = MagicMock()
        # First call is SET statement_timeout, second is the actual query
        mock_conn.execute.side_effect = [None, mock_result]
        mock_conn.__enter__ = MagicMock(return_value=mock_conn)
        mock_conn.__exit__ = MagicMock(return_value=False)

        with patch("nbadb.agent.query.duckdb.connect", return_value=mock_conn):
            result = agent.ask("who led scoring?")

        assert "Test Player" in result
        assert "player_id" in result  # header row
        assert " | " in result  # column separator

    def test_execute_no_results(self, agent: QueryAgent) -> None:
        mock_result = MagicMock()
        mock_result.description = [("player_id",), ("full_name",), ("total_pts",)]
        mock_result.fetchall.return_value = []

        mock_conn = MagicMock()
        mock_conn.execute.side_effect = [None, mock_result]
        mock_conn.__enter__ = MagicMock(return_value=mock_conn)
        mock_conn.__exit__ = MagicMock(return_value=False)

        with patch("nbadb.agent.query.duckdb.connect", return_value=mock_conn):
            result = agent.ask("who led scoring?")

        assert result == "No results found."

    def test_execute_formats_separator_correctly(self, agent: QueryAgent) -> None:
        mock_result = MagicMock()
        mock_result.description = [("col_a",), ("col_b",)]
        mock_result.fetchall.return_value = [("x", "y"), ("a", "b")]

        mock_conn = MagicMock()
        mock_conn.execute.side_effect = [None, mock_result]
        mock_conn.__enter__ = MagicMock(return_value=mock_conn)
        mock_conn.__exit__ = MagicMock(return_value=False)

        with patch("nbadb.agent.query.duckdb.connect", return_value=mock_conn):
            result = agent.ask("who led scoring?")

        lines = result.split("\n")
        assert len(lines) == 4  # header + separator + 2 data rows
        assert "-+-" in lines[1]  # separator line


# ---------------------------------------------------------------------------
# TestQueryAgentSafety
# ---------------------------------------------------------------------------


class TestQueryAgentSafety:
    def test_duckdb_error_returns_safe_message(self, tmp_path: Path) -> None:
        """DuckDB errors should return a generic message, not raw exception text."""
        db_path = tmp_path / "bad.duckdb"
        # Create a DB but without the tables the query expects
        with duckdb.connect(str(db_path)) as conn:
            conn.execute("SELECT 1")

        agent = QueryAgent(db_path)
        result = agent.ask("who led scoring?")
        assert result == "Query execution failed. Please try a different question."
        # Should NOT leak SQL or table names
        assert "agg_player_season" not in result
        assert "Traceback" not in result

    def test_duckdb_error_does_not_expose_exception_details(self, tmp_path: Path) -> None:
        """Verify the error message does not include type(exc).__name__ in user output."""
        db_path = tmp_path / "err.duckdb"
        with duckdb.connect(str(db_path)) as conn:
            conn.execute("SELECT 1")

        agent = QueryAgent(db_path)
        result = agent.ask("most points?")
        # The user-facing message should be generic
        assert "CatalogException" not in result
        assert "failed" in result.lower()

    def test_readonly_connection_used(self, tmp_db: Path) -> None:
        """Verify the agent opens DuckDB in read_only mode."""
        agent = QueryAgent(tmp_db)
        with patch("nbadb.agent.query.duckdb.connect") as mock_connect:
            mock_conn = MagicMock()
            mock_result = MagicMock()
            mock_result.description = [("col1",)]
            mock_result.fetchall.return_value = [("val1",)]
            mock_conn.execute.return_value = mock_result
            mock_conn.__enter__ = MagicMock(return_value=mock_conn)
            mock_conn.__exit__ = MagicMock(return_value=False)
            mock_connect.return_value = mock_conn

            agent.ask("who led scoring?")

            mock_connect.assert_called_once_with(str(tmp_db), read_only=True)

    def test_guard_blocks_write_query(self, agent: QueryAgent) -> None:
        """If a pattern somehow produced a write query, the guard should block it."""
        with patch.object(agent, "_match_pattern", return_value="DROP TABLE dim_player"):
            result = agent.ask("anything")
            assert "blocked" in result.lower()

    def test_guard_wraps_with_limit(self, agent: QueryAgent) -> None:
        """Queries without LIMIT should have one added by the guard."""
        wrapped = agent._guard.wrap_with_limit("SELECT 1 FROM t")
        assert "LIMIT" in wrapped

    def test_ask_applies_custom_limit(self, tmp_db: Path) -> None:
        """Custom limit should be applied to built-in matched queries."""
        agent = QueryAgent(tmp_db)
        with patch("nbadb.agent.query.duckdb.connect") as mock_connect:
            mock_conn = MagicMock()
            mock_result = MagicMock()
            mock_result.description = [("c",)]
            mock_result.fetchall.return_value = [("v",)]
            mock_conn.execute.side_effect = [None, mock_result]
            mock_conn.__enter__ = MagicMock(return_value=mock_conn)
            mock_conn.__exit__ = MagicMock(return_value=False)
            mock_connect.return_value = mock_conn

            agent.ask("who led scoring?", limit=3)

            sql = mock_conn.execute.call_args_list[1].args[0]
            assert "LIMIT 3" in sql.upper()

    @pytest.mark.parametrize("limit", [0, -5])
    def test_ask_clamps_non_positive_limit(self, tmp_db: Path, limit: int) -> None:
        """Non-positive limits should be clamped to 1."""
        agent = QueryAgent(tmp_db)
        with patch("nbadb.agent.query.duckdb.connect") as mock_connect:
            mock_conn = MagicMock()
            mock_result = MagicMock()
            mock_result.description = [("c",)]
            mock_result.fetchall.return_value = [("v",)]
            mock_conn.execute.side_effect = [None, mock_result]
            mock_conn.__enter__ = MagicMock(return_value=mock_conn)
            mock_conn.__exit__ = MagicMock(return_value=False)
            mock_connect.return_value = mock_conn

            agent.ask("who led scoring?", limit=limit)

            sql = mock_conn.execute.call_args_list[1].args[0]
            assert "LIMIT 1" in sql.upper()

    def test_ask_clamps_very_large_limit(self, tmp_db: Path) -> None:
        """Very large limits should be capped at MAX_RESULT_ROWS."""
        agent = QueryAgent(tmp_db)
        with patch("nbadb.agent.query.duckdb.connect") as mock_connect:
            mock_conn = MagicMock()
            mock_result = MagicMock()
            mock_result.description = [("c",)]
            mock_result.fetchall.return_value = [("v",)]
            mock_conn.execute.side_effect = [None, mock_result]
            mock_conn.__enter__ = MagicMock(return_value=mock_conn)
            mock_conn.__exit__ = MagicMock(return_value=False)
            mock_connect.return_value = mock_conn

            agent.ask("who led scoring?", limit=MAX_RESULT_ROWS + 1)

            sql = mock_conn.execute.call_args_list[1].args[0]
            assert f"LIMIT {MAX_RESULT_ROWS}" in sql.upper()

    def test_timeout_is_set(self, tmp_db: Path) -> None:
        """Verify statement_timeout is configured during execution."""
        agent = QueryAgent(tmp_db)
        with patch("nbadb.agent.query.duckdb.connect") as mock_connect:
            mock_conn = MagicMock()
            mock_result = MagicMock()
            mock_result.description = [("c",)]
            mock_result.fetchall.return_value = [("v",)]
            mock_conn.execute.return_value = mock_result
            mock_conn.__enter__ = MagicMock(return_value=mock_conn)
            mock_conn.__exit__ = MagicMock(return_value=False)
            mock_connect.return_value = mock_conn

            agent.ask("who led scoring?")

            calls = [str(c) for c in mock_conn.execute.call_args_list]
            timeout_calls = [c for c in calls if "statement_timeout" in c]
            assert len(timeout_calls) == 1
