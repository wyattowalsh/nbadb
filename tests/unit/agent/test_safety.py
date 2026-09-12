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


@pytest.mark.parametrize(
    "sql",
    [
        "INSERT INTO dim_player VALUES (1)",
        "UPDATE dim_player SET full_name='x'",
        "DELETE FROM dim_player",
        "DROP TABLE dim_player",
        "ALTER TABLE dim_player ADD COLUMN x INT",
        "CREATE TABLE t (id INT)",
        "TRUNCATE dim_player",
        "COPY dim_player TO 'out.csv'",
        "ATTACH 'other.db'",
        "PRAGMA show_tables",
        "SET threads=1",
        "INSTALL httpfs",
        "LOAD httpfs",
    ],
)
def test_blocks_write_keywords(guard: ReadOnlyGuard, sql: str) -> None:
    result = guard.validate(sql)
    assert result is not None
    assert "Write" in result or "not allowed" in result.lower()


def test_allows_replace_function(guard: ReadOnlyGuard) -> None:
    assert guard.validate("SELECT REPLACE(full_name, 'a', 'b') FROM dim_player") is None


def test_blocks_replace_into(guard: ReadOnlyGuard) -> None:
    result = guard.validate("REPLACE INTO dim_player VALUES (1)")
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
    assert result.startswith("SELECT * FROM (")
    assert "_limited" in result


def test_wrap_with_limit_always_wraps(guard: ReadOnlyGuard) -> None:
    """Even if the inner query has LIMIT, the outer wrapper enforces the cap."""
    result = guard.wrap_with_limit("SELECT * FROM t LIMIT 5")
    assert "_limited" in result
    assert result.endswith("LIMIT 10000")


def test_wrap_with_limit_cte(guard: ReadOnlyGuard) -> None:
    """CTE queries are safely wrapped with an outer LIMIT."""
    sql = "WITH cte AS (SELECT 1) SELECT * FROM cte"
    result = guard.wrap_with_limit(sql)
    assert result.startswith("SELECT * FROM (")
    assert "_limited" in result


# ---------------------------------------------------------------------------
# INFRA-004: SQL comment bypass
# ---------------------------------------------------------------------------


def test_blocks_write_hidden_in_block_comment(guard: ReadOnlyGuard) -> None:
    """Block comments must not hide write keywords."""
    result = guard.validate("SELECT /* DROP TABLE dim_player */ 1")
    assert result is None, "Benign query with comment should pass"


def test_blocks_drop_outside_block_comment(guard: ReadOnlyGuard) -> None:
    result = guard.validate("SELECT 1; /* harmless */ DROP TABLE dim_player")
    assert result is not None
    assert "Multiple statements" in result or "Write operation" in result


def test_blocks_write_in_line_comment(guard: ReadOnlyGuard) -> None:
    result = guard.validate("SELECT 1 -- DROP TABLE\nFROM dim_player")
    assert result is None, "Write keyword inside line comment should be ignored"


def test_blocks_actual_drop_after_line_comment(guard: ReadOnlyGuard) -> None:
    result = guard.validate("SELECT 1 -- safe\n; DROP TABLE dim_player")
    assert result is not None


# ---------------------------------------------------------------------------
# INFRA-004: Unicode normalization
# ---------------------------------------------------------------------------


def test_blocks_fullwidth_drop(guard: ReadOnlyGuard) -> None:
    """Fullwidth 'DROP' (U+FF24 etc.) must be caught after NFKC normalization."""
    fullwidth_drop = "\uff24\uff32\uff2f\uff30"  # DROP in fullwidth
    result = guard.validate(f"SELECT 1; {fullwidth_drop} TABLE dim_player")
    assert result is not None


# ---------------------------------------------------------------------------
# Blocked: DuckDB table-function aliases (W8.5 R3-L1)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "fn",
    ["parquet_scan", "sniff_csv", "iceberg_scan", "delta_scan", "st_read"],
)
def test_blocks_duckdb_table_function_aliases(guard: ReadOnlyGuard, fn: str) -> None:
    problem = guard.validate(f"SELECT * FROM {fn}('x.parquet')")
    assert problem is not None
    assert problem.startswith("File access function not allowed")


def test_every_duckdb_connect_site_disables_external_access() -> None:
    """Each read-only DuckDB connection must also set enable_external_access = false."""
    from pathlib import Path

    src_root = Path(__file__).resolve().parents[3] / "src" / "nbadb"
    sites = [
        "agent/query.py",
        "agent/entity.py",
        "agent/context.py",
        "chat/runtime/core.py",
    ]
    for rel in sites:
        text = (src_root / rel).read_text(encoding="utf-8")
        parts = text.split("duckdb.connect(")
        assert len(parts) >= 2, f"{rel}: expected at least one duckdb.connect site"
        for tail in parts[1:]:
            assert "enable_external_access" in tail, f"{rel}: connect site missing the flag"
