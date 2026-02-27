from __future__ import annotations

from abc import ABC, abstractmethod
from typing import TYPE_CHECKING, ClassVar

from loguru import logger

if TYPE_CHECKING:
    import polars as pl


class BaseTransformer(ABC):
    output_table: ClassVar[str]
    depends_on: ClassVar[list[str]] = []

    @abstractmethod
    def transform(self, staging: dict[str, pl.LazyFrame]) -> pl.DataFrame: ...

    def validate(self, df: pl.DataFrame) -> pl.DataFrame:
        """Override to apply Pandera star schema validation."""
        return df

    def run(self, staging: dict[str, pl.LazyFrame]) -> pl.DataFrame:
        logger.info(f"Transforming {self.output_table}")
        df = self.transform(staging)
        df = self.validate(df)
        logger.info(f"{self.output_table}: {df.shape[0]} rows, {df.shape[1]} cols")
        return df
