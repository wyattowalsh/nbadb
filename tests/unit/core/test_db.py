from __future__ import annotations

import pytest
from sqlalchemy import Engine, text
from sqlmodel import Session

from nbadb.core.db import DBManager


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
        assert len(rows) == 4


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
