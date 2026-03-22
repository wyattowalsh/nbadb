"""Tests for server/db.py — database bootstrap and schema context."""

from __future__ import annotations

import sys
from typing import TYPE_CHECKING
from unittest.mock import MagicMock

if TYPE_CHECKING:
    from pathlib import Path

import duckdb
import pytest


@pytest.fixture()
def sample_db(tmp_path: Path) -> Path:
    db_path = tmp_path / "test.duckdb"
    with duckdb.connect(str(db_path)) as conn:
        conn.execute("CREATE TABLE dim_player (player_id INT, full_name VARCHAR)")
        conn.execute("INSERT INTO dim_player VALUES (1, 'LeBron James')")
        conn.execute("CREATE TABLE fact_game_log (game_id INT, pts INT)")
        conn.execute("INSERT INTO fact_game_log VALUES (100, 30)")
    return db_path


class TestEnsureDatabase:
    def test_returns_existing_db(self, sample_db):
        from apps.chat.server.db import ensure_database

        result = ensure_database(sample_db)
        assert result == sample_db

    def test_creates_parent_dirs(self, tmp_path):
        from apps.chat.server.db import ensure_database

        nested = tmp_path / "deep" / "nested" / "nba.duckdb"
        # Create a fake duckdb in mock download dir
        mock_dl = tmp_path / "kaggle"
        mock_dl.mkdir()
        fake_db = mock_dl / "nba.duckdb"
        with duckdb.connect(str(fake_db)) as conn:
            conn.execute("CREATE TABLE test (id INT)")
            conn.execute("INSERT INTO test VALUES (1)")

        # kagglehub is imported inside the function, so mock via sys.modules
        mock_kh = MagicMock()
        mock_kh.dataset_download.return_value = str(mock_dl)
        sys.modules["kagglehub"] = mock_kh
        try:
            result = ensure_database(nested)
        finally:
            del sys.modules["kagglehub"]

        assert result.exists()
        assert result.parent.exists()


class TestGetSchemaContext:
    def test_includes_table_names(self, sample_db):
        from apps.chat.server.db import get_schema_context

        ctx = get_schema_context(sample_db)
        assert "dim_player" in ctx

    def test_includes_columns_for_dim(self, sample_db):
        from apps.chat.server.db import get_schema_context

        ctx = get_schema_context(sample_db)
        assert "player_id" in ctx
        assert "full_name" in ctx

    def test_fact_tables_listed_under_summary(self, sample_db):
        from apps.chat.server.db import get_schema_context

        ctx = get_schema_context(sample_db)
        assert "fact_game_log" in ctx
        # fact tables should NOT have column details in the compact version
        # (they go under "use describe_table for columns")
        assert "describe_table" in ctx

    def test_empty_database(self, tmp_path):
        from apps.chat.server.db import get_schema_context

        db_path = tmp_path / "empty.duckdb"
        with duckdb.connect(str(db_path)):
            pass
        ctx = get_schema_context(db_path)
        assert "Available tables" in ctx
