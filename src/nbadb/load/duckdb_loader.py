from __future__ import annotations

from typing import TYPE_CHECKING, Literal

from loguru import logger

from nbadb.core.types import validate_sql_identifier
from nbadb.load.base import BaseLoader

if TYPE_CHECKING:
    import duckdb
    import polars as pl
    import pyarrow as pa


# Threshold above which Arrow zero-copy is preferred over register+SELECT.
_ARROW_THRESHOLD_ROWS = 100_000


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
        # For large frames, use Arrow zero-copy path to avoid materialisation
        if df.shape[0] >= _ARROW_THRESHOLD_ROWS:
            self._load_via_arrow(table, df, mode)
        else:
            self._load_via_register(table, df, mode)

    def _load_via_register(
        self,
        table: str,
        df: pl.DataFrame,
        mode: Literal["replace", "append"],
    ) -> None:
        """Standard load path: register DataFrame then SELECT."""
        self._conn.register("_load_df", df)
        if mode == "replace":
            self._conn.execute(f"CREATE OR REPLACE TABLE {table} AS SELECT * FROM _load_df")
        else:
            self._conn.execute(f"INSERT INTO {table} SELECT * FROM _load_df")
        self._conn.unregister("_load_df")
        logger.debug(f"DuckDB: wrote {df.shape[0]} rows to {table} (mode={mode})")

    def _load_via_arrow(
        self,
        table: str,
        df: pl.DataFrame,
        mode: Literal["replace", "append"],
    ) -> None:
        """Zero-copy Arrow interchange — avoids materialising intermediate views
        for large DataFrames (>100K rows)."""
        arrow_table = df.to_arrow()
        self._conn.register("_load_arrow", arrow_table)
        if mode == "replace":
            self._conn.execute(f"CREATE OR REPLACE TABLE {table} AS SELECT * FROM _load_arrow")
        else:
            self._conn.execute(f"INSERT INTO {table} SELECT * FROM _load_arrow")
        self._conn.unregister("_load_arrow")
        logger.debug(
            f"DuckDB (Arrow): wrote {df.shape[0]} rows to {table} (mode={mode})"
        )

    def load_arrow(
        self,
        table: str,
        arrow_table: pa.Table,
        mode: Literal["replace", "append"] = "replace",
    ) -> None:
        """Load a PyArrow table directly — zero-copy, no Polars intermediary."""
        validate_sql_identifier(table)
        self._conn.register("_load_arrow", arrow_table)
        if mode == "replace":
            self._conn.execute(f"CREATE OR REPLACE TABLE {table} AS SELECT * FROM _load_arrow")
        else:
            self._conn.execute(f"INSERT INTO {table} SELECT * FROM _load_arrow")
        self._conn.unregister("_load_arrow")
        logger.debug(
            f"DuckDB (Arrow direct): wrote {arrow_table.num_rows} rows to {table} (mode={mode})"
        )
