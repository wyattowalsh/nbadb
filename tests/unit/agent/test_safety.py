"""Tests for the ReadOnlyGuard SQL safety validator."""

from __future__ import annotations

import pytest

from nbadb.agent.safety import ReadOnlyGuard


@pytest.fixture
def guard() -> ReadOnlyGuard:
    return ReadOnlyGuard()


# ---------------------------------------------------------------------------
# Allowed queries
# ---------------------------------------------------------------------------


def test_allows_select(guard: ReadOnlyGuard) -> None:
    assert guard.validate("SELECT * FROM dim_player") is None


def test_allows_with_cte(guard: ReadOnlyGuard) -> None:
    assert guard.validate("WITH cte AS (SELECT 1) SELECT * FROM cte") is None


def test_allows_word_read_in_column(guard: ReadOnlyGuard) -> None:
    """'read' as part of a column name should be fine."""
    assert guard.validate("SELECT read_count FROM metrics") is None


# ---------------------------------------------------------------------------
# Blocked: write operations
# ---------------------------------------------------------------------------


def test_blocks_insert(guard: ReadOnlyGuard) -> None:
    result = guard.validate("INSERT INTO dim_player VALUES (1)")
    assert result is not None
    assert "Write operation" in result


def test_blocks_drop(guard: ReadOnlyGuard) -> None:
    result = guard.validate("DROP TABLE dim_player")
    assert result is not None


# ---------------------------------------------------------------------------
# Blocked: dangerous file-access functions
# ---------------------------------------------------------------------------


def test_blocks_read_csv(guard: ReadOnlyGuard) -> None:
    result = guard.validate("SELECT * FROM read_csv('/etc/passwd')")
    assert result is not None
    assert "File access function" in result


def test_blocks_read_parquet(guard: ReadOnlyGuard) -> None:
    result = guard.validate("SELECT * FROM read_parquet('*.parquet')")
    assert result is not None


def test_blocks_read_json(guard: ReadOnlyGuard) -> None:
    result = guard.validate("SELECT * FROM read_json_auto('/tmp/data.json')")
    assert result is not None


def test_blocks_glob(guard: ReadOnlyGuard) -> None:
    result = guard.validate("SELECT * FROM glob('/tmp/*')")
    assert result is not None


def test_blocks_http_get(guard: ReadOnlyGuard) -> None:
    result = guard.validate("SELECT * FROM http_get('http://evil.com')")
    assert result is not None


# ---------------------------------------------------------------------------
# Blocked: empty query
# ---------------------------------------------------------------------------


def test_blocks_empty_query(guard: ReadOnlyGuard) -> None:
    result = guard.validate("")
    assert result is not None


# ---------------------------------------------------------------------------
# wrap_with_limit
# ---------------------------------------------------------------------------


def test_wrap_with_limit_adds_limit(guard: ReadOnlyGuard) -> None:
    result = guard.wrap_with_limit("SELECT * FROM t")
    assert "LIMIT" in result


def test_wrap_with_limit_preserves_existing(guard: ReadOnlyGuard) -> None:
    result = guard.wrap_with_limit("SELECT * FROM t LIMIT 5")
    assert result.count("LIMIT") == 1
