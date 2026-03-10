from __future__ import annotations

from contextlib import contextmanager
from typing import TYPE_CHECKING

import duckdb
from sqlalchemy import Engine, text
from sqlmodel import Session, SQLModel, create_engine

from nbadb.core.config import get_settings

if TYPE_CHECKING:
    from collections.abc import Generator
    from pathlib import Path

try:
    from loguru import logger
except ImportError:
    import logging

    logger = logging.getLogger(__name__)  # ty: ignore[invalid-assignment]


class DBManager:
    def __init__(
        self,
        sqlite_path: Path | None = None,
        duckdb_path: Path | None = None,
    ) -> None:
        settings = get_settings()
        self._sqlite_path = sqlite_path or settings.sqlite_path
        self._duckdb_path = duckdb_path or settings.duckdb_path
        self._engine: Engine | None = None
        self._duckdb_conn: duckdb.DuckDBPyConnection | None = None

    def init(self) -> None:
        if self._sqlite_path is None:
            raise ValueError("sqlite_path required")
        if self._duckdb_path is None:
            raise ValueError("duckdb_path required")
        self._sqlite_path.parent.mkdir(parents=True, exist_ok=True)
        self._duckdb_path.parent.mkdir(parents=True, exist_ok=True)
        self._engine = create_engine(f"sqlite:///{self._sqlite_path}", echo=False)
        self._apply_sqlite_pragmas()
        SQLModel.metadata.create_all(self._engine)
        self._duckdb_conn = duckdb.connect(str(self._duckdb_path))
        self._create_pipeline_tables()
        logger.info(f"DB initialized: SQLite={self._sqlite_path}, DuckDB={self._duckdb_path}")

    def _apply_sqlite_pragmas(self) -> None:
        if self._engine is None:
            raise RuntimeError("DB not initialized")
        with self._engine.connect() as conn:
            for pragma in [
                "PRAGMA journal_mode = WAL",
                "PRAGMA synchronous = NORMAL",
                "PRAGMA cache_size = -262144",
                "PRAGMA page_size = 16384",  # only effective on newly created databases
                "PRAGMA mmap_size = 1073741824",
                "PRAGMA temp_store = MEMORY",
            ]:
                conn.execute(text(pragma))
            conn.commit()

    def _create_pipeline_tables(self) -> None:
        if self._duckdb_conn is None:
            raise RuntimeError("DB not initialized")
        self._duckdb_conn.execute("""
            CREATE TABLE IF NOT EXISTS _pipeline_watermarks (
                table_name VARCHAR NOT NULL,
                watermark_type VARCHAR NOT NULL,
                watermark_value VARCHAR,
                last_updated TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                row_count_at_watermark BIGINT,
                PRIMARY KEY (table_name, watermark_type)
            )
        """)
        self._duckdb_conn.execute("""
            CREATE TABLE IF NOT EXISTS _extraction_journal (
                endpoint VARCHAR NOT NULL,
                params VARCHAR,
                status VARCHAR NOT NULL,
                started_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                completed_at TIMESTAMP,
                rows_extracted BIGINT,
                error_message VARCHAR,
                PRIMARY KEY (endpoint, params)
            )
        """)
        self._duckdb_conn.execute("""
            CREATE TABLE IF NOT EXISTS _pipeline_metadata (
                table_name VARCHAR PRIMARY KEY,
                last_updated TIMESTAMP,
                row_count BIGINT,
                schema_hash VARCHAR
            )
        """)
        self._duckdb_conn.execute("""
            CREATE TABLE IF NOT EXISTS _pipeline_metrics (
                endpoint VARCHAR NOT NULL,
                run_timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                duration_seconds FLOAT,
                rows_extracted BIGINT,
                error_count INT DEFAULT 0,
                PRIMARY KEY (endpoint, run_timestamp)
            )
        """)
        self._duckdb_conn.execute("""
            CREATE TABLE IF NOT EXISTS _transform_checkpoints (
                run_id VARCHAR NOT NULL,
                table_name VARCHAR NOT NULL,
                completed_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                row_count BIGINT,
                PRIMARY KEY (run_id, table_name)
            )
        """)
        self._duckdb_conn.execute("""
            CREATE TABLE IF NOT EXISTS _schema_versions (
                table_name VARCHAR NOT NULL,
                version INT NOT NULL DEFAULT 1,
                column_hash VARCHAR NOT NULL,
                columns_json VARCHAR NOT NULL,
                recorded_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                PRIMARY KEY (table_name)
            )
        """)
        self._duckdb_conn.execute("""
            CREATE TABLE IF NOT EXISTS _schema_version_history (
                table_name VARCHAR NOT NULL,
                version INT NOT NULL,
                column_hash VARCHAR NOT NULL,
                columns_json VARCHAR NOT NULL,
                recorded_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                PRIMARY KEY (table_name, version)
            )
        """)
        self._duckdb_conn.execute("""
            CREATE TABLE IF NOT EXISTS _transform_metrics (
                run_id VARCHAR NOT NULL,
                table_name VARCHAR NOT NULL,
                started_at TIMESTAMP,
                completed_at TIMESTAMP,
                duration_seconds FLOAT,
                row_count BIGINT,
                column_count INT,
                status VARCHAR NOT NULL DEFAULT 'success',
                error_message VARCHAR,
                PRIMARY KEY (run_id, table_name)
            )
        """)

    @property
    def engine(self) -> Engine:
        if not self._engine:
            raise RuntimeError("DB not initialized. Call init() first.")
        return self._engine

    @property
    def duckdb(self) -> duckdb.DuckDBPyConnection:  # ty: ignore[unresolved-attribute]
        if not self._duckdb_conn:
            raise RuntimeError("DB not initialized. Call init() first.")
        return self._duckdb_conn

    @contextmanager
    def session(self) -> Generator[Session, None, None]:
        with Session(self.engine) as session:
            yield session

    def close(self) -> None:
        if self._engine:
            self._engine.dispose()
        if self._duckdb_conn:
            self._duckdb_conn.close()
        logger.info("DB connections closed")

    def __enter__(self) -> DBManager:
        self.init()
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()


def get_user_tables(conn: object) -> list[str]:
    """Return sorted list of user-created table names in the main schema.

    Excludes internal pipeline tables (prefixed with underscore).
    """
    rows = conn.execute(
        "SELECT table_name FROM information_schema.tables "
        "WHERE table_schema = 'main' "
        "AND table_name NOT LIKE '\\_%' ESCAPE '\\'"
    ).fetchall()
    return sorted(row[0] for row in rows)
