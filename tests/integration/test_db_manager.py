from __future__ import annotations

from typing import TYPE_CHECKING

from nbadb.core.db import DBManager

if TYPE_CHECKING:
    from pathlib import Path


class TestDBManagerIntegration:
    def test_context_manager_lifecycle(self, tmp_path: Path) -> None:
        sqlite = tmp_path / "test.sqlite"
        duck = tmp_path / "test.duckdb"
        with DBManager(sqlite_path=sqlite, duckdb_path=duck) as db:
            assert db.engine is not None
            assert db.duckdb is not None
            tables = db.duckdb.execute(
                "SELECT table_name FROM information_schema.tables "
                "WHERE table_name LIKE '\\_%' ESCAPE '\\'"
            ).fetchall()
            table_names = {row[0] for row in tables}
            assert "_pipeline_watermarks" in table_names
            assert "_extraction_journal" in table_names
            assert "_pipeline_metadata" in table_names
            assert "_pipeline_metrics" in table_names

    def test_session_yields_sqlmodel_session(self, tmp_path: Path) -> None:
        from sqlmodel import Session

        sqlite = tmp_path / "test.sqlite"
        duck = tmp_path / "test.duckdb"
        with (
            DBManager(sqlite_path=sqlite, duckdb_path=duck) as db,
            db.session() as session,
        ):
            assert isinstance(session, Session)

    def test_engine_raises_before_init(self, tmp_path: Path) -> None:
        import pytest

        db = DBManager(
            sqlite_path=tmp_path / "a.sqlite",
            duckdb_path=tmp_path / "a.duckdb",
        )
        with pytest.raises(RuntimeError, match="not initialized"):
            _ = db.engine

    def test_duckdb_raises_before_init(self, tmp_path: Path) -> None:
        import pytest

        db = DBManager(
            sqlite_path=tmp_path / "a.sqlite",
            duckdb_path=tmp_path / "a.duckdb",
        )
        with pytest.raises(RuntimeError, match="not initialized"):
            _ = db.duckdb

    def test_creates_parent_directories(self, tmp_path: Path) -> None:
        nested_sqlite = tmp_path / "deep" / "nested" / "test.sqlite"
        nested_duck = tmp_path / "deep" / "nested" / "test.duckdb"
        with DBManager(sqlite_path=nested_sqlite, duckdb_path=nested_duck):
            assert nested_sqlite.parent.exists()
            assert nested_duck.parent.exists()

    def test_sqlite_pragmas_applied(self, tmp_path: Path) -> None:
        from sqlalchemy import text

        sqlite = tmp_path / "pragma_test.sqlite"
        duck = tmp_path / "pragma_test.duckdb"
        with (
            DBManager(sqlite_path=sqlite, duckdb_path=duck) as db,
            db.engine.connect() as conn,
        ):
            result = conn.execute(text("PRAGMA journal_mode")).fetchone()
            assert result[0] == "wal"
