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
        errors: list[tuple[str, Exception]] = []
        for loader in self._loaders:
            try:
                loader.load(table, df, mode)
            except Exception as e:
                errors.append((type(loader).__name__, e))
                logger.error(
                    "MultiLoader: {} failed for {}: {}",
                    type(loader).__name__,
                    table,
                    type(e).__name__,
                )
        if errors:
            failed = ", ".join(name for name, _ in errors)
            raise RuntimeError(f"MultiLoader: {len(errors)} loader(s) failed for {table}: {failed}")
        logger.info(f"MultiLoader: {table} → {len(self._loaders)} formats")


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
        if settings.sqlite_path is None:
            raise ValueError("sqlite_path must be set in settings to use SQLite loader")
        loaders.append(SQLiteLoader(settings.sqlite_path))
    if "duckdb" in settings.formats:
        if duckdb_conn is not None:
            loaders.append(DuckDBLoader(duckdb_conn))
        else:
            import duckdb

            conn = duckdb.connect(str(settings.duckdb_path))
            loaders.append(DuckDBLoader(conn))
    if "parquet" in settings.formats:
        loaders.append(ParquetLoader(settings.data_dir / "parquet"))
    if "csv" in settings.formats:
        loaders.append(CSVLoader(settings.data_dir / "csv"))

    return MultiLoader(loaders)
