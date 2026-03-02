from __future__ import annotations

from typing import TYPE_CHECKING, Literal

from loguru import logger

from nbadb.core.types import validate_sql_identifier
from nbadb.load.base import BaseLoader

if TYPE_CHECKING:
    import duckdb
    import polars as pl


class DuckDBLoader(BaseLoader):
    def __init__(self, conn: duckdb.DuckDBPyConnection) -> None:
        self._conn = conn

    def load(
        self,
        table: str,
        df: pl.DataFrame,
        mode: Literal["replace", "append"] = "replace",
    ) -> None:
        validate_sql_identifier(table)
        self._conn.register("_load_df", df)
        if mode == "replace":
            self._conn.execute(f"CREATE OR REPLACE TABLE {table} AS SELECT * FROM _load_df")
        else:
            self._conn.execute(f"INSERT INTO {table} SELECT * FROM _load_df")
        self._conn.unregister("_load_df")
        logger.debug(f"DuckDB: wrote {df.shape[0]} rows to {table} (mode={mode})")
