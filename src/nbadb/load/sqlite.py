from __future__ import annotations

from typing import TYPE_CHECKING, Literal

from loguru import logger

from nbadb.load.base import BaseLoader

if TYPE_CHECKING:
    from pathlib import Path

    import polars as pl


class SQLiteLoader(BaseLoader):
    def __init__(self, db_path: Path) -> None:
        self._db_path = db_path
        self._connection_string = f"sqlite:///{db_path}"

    def load(
        self,
        table: str,
        df: pl.DataFrame,
        mode: Literal["replace", "append"] = "replace",
    ) -> None:
        if_exists = "replace" if mode == "replace" else "append"
        df.write_database(
            table,
            self._connection_string,
            engine="adbc",
            if_table_exists=if_exists,
        )
        logger.debug(
            f"SQLite: wrote {df.shape[0]} rows to {table} "
            f"(mode={mode})"
        )
