from __future__ import annotations

from unittest.mock import MagicMock, patch

import duckdb
import pytest
from sqlalchemy import Engine, text
from sqlmodel import Session

from nbadb.core.db import DBManager, DuckDBLockError


@pytest.fixture()
def db(tmp_path):
    return DBManager(
        sqlite_path=tmp_path / "test.sqlite",
        duckdb_path=tmp_path / "test.duckdb",
    )


@pytest.fixture()
def initialized_db(db):
    db.init()
    yield db
    db.close()


class TestDBManagerInit:
    def test_init_creates_files(self, db, tmp_path):
        db.init()
        db.close()
        assert (tmp_path / "test.sqlite").exists()
        assert (tmp_path / "test.duckdb").exists()

    def test_init_retries_duckdb_lock_then_succeeds(self, db):
        mock_conn = MagicMock()
        lock_error = duckdb.IOException('IO Error: Could not set lock on file "/tmp/test.duckdb"')

        with (
            patch("nbadb.core.db.duckdb.connect", side_effect=[lock_error, mock_conn]),
            patch("nbadb.core.db.time.sleep") as mock_sleep,
        ):
            db.init()
        try:
            assert db.duckdb is mock_conn
            mock_sleep.assert_called_once_with(0.5)
        finally:
            db.close()

    def test_init_raises_helpful_error_after_repeated_duckdb_lock_conflicts(self, db):
        lock_error = duckdb.IOException(
            'IO Error: Could not set lock on file "/tmp/test.duckdb": Conflicting lock is held'
        )

        with (
            patch("nbadb.core.db.duckdb.connect", side_effect=lock_error),
            patch("nbadb.core.db.time.sleep") as mock_sleep,
        ):
            try:
                with pytest.raises(DuckDBLockError, match="DuckDB database is locked"):
                    db.init()
            finally:
                db.close()

        assert mock_sleep.call_count == 3

    def test_engine_returns_after_init(self, initialized_db):
        assert initialized_db.engine is not None
        assert isinstance(initialized_db.engine, Engine)

    def test_duckdb_returns_after_init(self, initialized_db):
        assert initialized_db.duckdb is not None

    def test_engine_before_init_raises(self, db):
        with pytest.raises(RuntimeError, match="not initialized"):
            _ = db.engine

    def test_duckdb_before_init_raises(self, db):
        with pytest.raises(RuntimeError, match="not initialized"):
            _ = db.duckdb


class TestPipelineTables:
    EXPECTED_TABLES = {
        "_pipeline_watermarks",
        "_extraction_journal",
        "_pipeline_metadata",
        "_pipeline_metrics",
        "_transform_checkpoints",
        "_transform_metrics",
        "_schema_versions",
        "_schema_version_history",
    }

    def test_pipeline_tables_created(self, initialized_db):
        rows = initialized_db.duckdb.execute(
            "SELECT table_name FROM information_schema.tables WHERE table_schema='main'"
        ).fetchall()
        table_names = {row[0] for row in rows}
        assert self.EXPECTED_TABLES.issubset(table_names)

    def test_metadata_table_names(self, initialized_db):
        rows = initialized_db.duckdb.execute(
            "SELECT table_name FROM information_schema.tables"
            " WHERE table_name LIKE '\\_%' ESCAPE '\\'"
        ).fetchall()
        assert len(rows) == len(self.EXPECTED_TABLES)


class TestSession:
    def test_session_yields_session(self, initialized_db):
        with initialized_db.session() as s:
            assert isinstance(s, Session)


class TestClose:
    def test_close_disposes_connections(self, db):
        db.init()
        db.close()  # should not raise

    def test_close_before_init_does_not_raise(self, db):
        db.close()  # _engine and _duckdb_conn are None — should be a no-op


class TestContextManager:
    def test_context_manager(self, tmp_path):
        with DBManager(
            sqlite_path=tmp_path / "cm.sqlite",
            duckdb_path=tmp_path / "cm.duckdb",
        ) as db:
            assert isinstance(db.engine, Engine)
            assert db.duckdb is not None

    def test_context_manager_files_created(self, tmp_path):
        with DBManager(
            sqlite_path=tmp_path / "cm.sqlite",
            duckdb_path=tmp_path / "cm.duckdb",
        ):
            pass
        assert (tmp_path / "cm.sqlite").exists()
        assert (tmp_path / "cm.duckdb").exists()


class TestSQLitePragmas:
    def test_sqlite_wal_mode(self, initialized_db):
        with initialized_db.engine.connect() as conn:
            result = conn.execute(text("PRAGMA journal_mode")).fetchone()
        assert result[0] == "wal"


class TestDoubleInit:
    def test_second_init_does_not_raise(self, db):
        db.init()
        db.init()  # second call should not error
        db.close()


class TestGetUserTables:
    def test_returns_user_tables_only(self, initialized_db):
        from nbadb.core.db import get_user_tables

        # Create a user table
        initialized_db.duckdb.execute("CREATE TABLE my_table (id INT)")
        tables = get_user_tables(initialized_db.duckdb)
        assert "my_table" in tables
        # Internal tables (prefixed with _) should be excluded
        assert all(not t.startswith("_") for t in tables)

    def test_empty_when_no_user_tables(self, initialized_db):
        from nbadb.core.db import get_user_tables

        tables = get_user_tables(initialized_db.duckdb)
        assert tables == []

    def test_sorted_output(self, initialized_db):
        from nbadb.core.db import get_user_tables

        initialized_db.duckdb.execute("CREATE TABLE z_table (id INT)")
        initialized_db.duckdb.execute("CREATE TABLE a_table (id INT)")
        tables = get_user_tables(initialized_db.duckdb)
        assert tables == sorted(tables)


class TestDBManagerDefaultPaths:
    def test_defaults_from_settings(self, tmp_path, monkeypatch):
        """DBManager uses settings defaults when paths not provided."""
        from nbadb.core.config import get_settings

        get_settings.cache_clear()
        monkeypatch.setenv("NBADB_SQLITE_PATH", str(tmp_path / "s.sqlite"))
        monkeypatch.setenv("NBADB_DUCKDB_PATH", str(tmp_path / "d.duckdb"))
        get_settings.cache_clear()
        db = DBManager()
        db.init()
        db.close()
        get_settings.cache_clear()
        assert (tmp_path / "s.sqlite").exists()
        assert (tmp_path / "d.duckdb").exists()

    def test_init_raises_when_sqlite_path_is_none(self, monkeypatch):
        """init() raises ValueError when sqlite_path resolves to None."""
        from unittest.mock import patch

        from nbadb.core.config import get_settings

        get_settings.cache_clear()
        mock_settings = MagicMock()
        mock_settings.sqlite_path = None
        mock_settings.duckdb_path = None
        with patch("nbadb.core.db.get_settings", return_value=mock_settings):
            db = DBManager(sqlite_path=None, duckdb_path=None)
            with pytest.raises(ValueError, match="sqlite_path required"):
                db.init()
        get_settings.cache_clear()


class TestApplySqlitePragmasBeforeInit:
    def test_pragmas_raises_before_engine(self, db):
        with pytest.raises(RuntimeError, match="not initialized"):
            db._apply_sqlite_pragmas()


class TestCreatePipelineTablesBeforeInit:
    def test_raises_before_duckdb(self, db):
        with pytest.raises(RuntimeError, match="not initialized"):
            db._create_pipeline_tables()
