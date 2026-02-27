from __future__ import annotations

from typing import TYPE_CHECKING, Literal

from loguru import logger

if TYPE_CHECKING:
    import duckdb
    import polars as pl

    from nbadb.core.config import NbaDbSettings
    from nbadb.load.base import BaseLoader


class MultiLoader:
    def __init__(self, loaders: list[BaseLoader]) -> None:
        self._loaders = loaders

    def load(
        self,
        table: str,
        df: pl.DataFrame,
        mode: Literal["replace", "append"] = "replace",
    ) -> None:
        for loader in self._loaders:
            loader.load(table, df, mode)
        logger.info(
            f"MultiLoader: {table} → "
            f"{len(self._loaders)} formats"
        )


def create_multi_loader(
    settings: NbaDbSettings,
    duckdb_conn: duckdb.DuckDBPyConnection | None = None,
) -> MultiLoader:
    from nbadb.load.csv_loader import CSVLoader
    from nbadb.load.duckdb_loader import DuckDBLoader
    from nbadb.load.parquet_loader import ParquetLoader
    from nbadb.load.sqlite import SQLiteLoader

    loaders: list[BaseLoader] = []

    if "sqlite" in settings.formats:
        assert settings.sqlite_path is not None, "sqlite_path required for sqlite format"
        loaders.append(SQLiteLoader(settings.sqlite_path))
    if "duckdb" in settings.formats and duckdb_conn:
        loaders.append(DuckDBLoader(duckdb_conn))
    if "parquet" in settings.formats:
        loaders.append(ParquetLoader(settings.data_dir / "parquet"))
    if "csv" in settings.formats:
        loaders.append(CSVLoader(settings.data_dir / "csv"))

    return MultiLoader(loaders)
