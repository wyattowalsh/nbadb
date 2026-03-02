from __future__ import annotations

from abc import ABC, abstractmethod
from typing import TYPE_CHECKING, ClassVar

from loguru import logger

if TYPE_CHECKING:
    import duckdb
    import polars as pl


class BaseTransformer(ABC):
    output_table: ClassVar[str]
    depends_on: ClassVar[list[str]] = []

    def __init__(self) -> None:
        self._conn: duckdb.DuckDBPyConnection | None = None

    @property
    def conn(self) -> duckdb.DuckDBPyConnection:
        """Shared DuckDB connection injected by TransformPipeline."""
        if self._conn is None:
            raise RuntimeError(
                "No DuckDB connection injected. Use TransformPipeline.run() "
                "to execute transforms — do not call transformer.run() directly."
            )
        return self._conn

    @abstractmethod
    def transform(self, staging: dict[str, pl.LazyFrame]) -> pl.DataFrame: ...

    def run(self, staging: dict[str, pl.LazyFrame]) -> pl.DataFrame:
        logger.info(f"Transforming {self.output_table}")
        df = self.transform(staging)
        logger.info(f"{self.output_table}: {df.shape[0]} rows, {df.shape[1]} cols")
        return df
