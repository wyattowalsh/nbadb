"""Tests for the chat app's inlined ReadOnlyGuard."""

from __future__ import annotations

import pytest

from apps.chat.server._safety import ReadOnlyGuard


@pytest.fixture()
def guard() -> ReadOnlyGuard:
    return ReadOnlyGuard()


class TestValidation:
    def test_allows_select(self, guard):
        assert guard.validate("SELECT * FROM dim_player") is None

    def test_allows_with_cte(self, guard):
        assert guard.validate("WITH cte AS (SELECT 1) SELECT * FROM cte") is None

    def test_allows_explain(self, guard):
        assert guard.validate("EXPLAIN SELECT 1") is None

    def test_blocks_insert(self, guard):
        assert guard.validate("INSERT INTO t VALUES (1)") is not None

    def test_blocks_drop(self, guard):
        assert guard.validate("DROP TABLE dim_player") is not None

    def test_blocks_delete(self, guard):
        assert guard.validate("DELETE FROM dim_player") is not None

    def test_blocks_update(self, guard):
        assert guard.validate("UPDATE dim_player SET x=1") is not None

    def test_blocks_stacked_queries(self, guard):
        err = guard.validate("SELECT 1; DROP TABLE t")
        assert err is not None
        assert "Multiple" in err

    def test_blocks_read_csv(self, guard):
        assert guard.validate("SELECT * FROM read_csv('/etc/passwd')") is not None

    def test_blocks_http_get(self, guard):
        assert guard.validate("SELECT * FROM http_get('http://evil.com')") is not None

    def test_blocks_read_parquet(self, guard):
        assert guard.validate("SELECT * FROM read_parquet('s3://x')") is not None

    def test_blocks_attach(self, guard):
        assert guard.validate("ATTACH '/tmp/x.db'") is not None

    def test_blocks_set(self, guard):
        assert guard.validate("SET enable_external_access = true") is not None

    def test_blocks_install(self, guard):
        assert guard.validate("INSTALL httpfs") is not None

    def test_empty_query(self, guard):
        assert guard.validate("") is not None

    def test_whitespace_only(self, guard):
        assert guard.validate("   ") is not None

    def test_comment_hidden_write(self, guard):
        assert guard.validate("/* SELECT */ DROP TABLE x") is not None

    def test_allows_select_with_comments(self, guard):
        assert guard.validate("SELECT /* col */ * FROM t -- ok") is None

    def test_unicode_fullwidth_drop(self, guard):
        assert guard.validate("\uff24\uff32\uff2f\uff30 TABLE t") is not None

    def test_case_insensitive(self, guard):
        assert guard.validate("dElEtE FROM t") is not None

    def test_non_select_statement(self, guard):
        err = guard.validate("VALUES (1, 2)")
        assert err is not None
        assert "Only SELECT" in err


class TestWrapWithLimit:
    def test_adds_limit(self, guard):
        result = guard.wrap_with_limit("SELECT * FROM t", max_rows=100)
        assert "LIMIT 100" in result

    def test_strips_semicolon(self, guard):
        result = guard.wrap_with_limit("SELECT 1;", max_rows=50)
        assert "LIMIT 50" in result

    def test_default_limit(self, guard):
        result = guard.wrap_with_limit("SELECT 1")
        assert "LIMIT" in result

    def test_explain_passthrough(self, guard):
        result = guard.wrap_with_limit("EXPLAIN SELECT 1", max_rows=50)
        assert result == "EXPLAIN SELECT 1"

    def test_show_passthrough(self, guard):
        result = guard.wrap_with_limit("SHOW TABLES", max_rows=50)
        assert result == "SHOW TABLES"

    def test_describe_passthrough(self, guard):
        result = guard.wrap_with_limit("DESCRIBE dim_player", max_rows=50)
        assert result == "DESCRIBE dim_player"
