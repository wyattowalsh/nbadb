from __future__ import annotations

from typing import TYPE_CHECKING, Literal, cast

import polars as pl
from loguru import logger

from nbadb.core.types import validate_sql_identifier
from nbadb.kaggle.raw_value_codec import RawScalarValue, encode_raw_value
from nbadb.load.base import BaseLoader

if TYPE_CHECKING:
    from pathlib import Path


def _is_fixed_raw_authority_table(table: str) -> bool:
    if not table.startswith("raw_nba_api_"):
        return False
    from nbadb.orchestrate.raw_request_store import RAW_REQUEST_AUTHORITY_TABLES

    return table in RAW_REQUEST_AUTHORITY_TABLES


def _encode_convenience_scalar(value: object) -> str:
    return encode_raw_value(cast("RawScalarValue", value))


def _project_raw_authority_convenience_frame(
    table: str,
    df: pl.DataFrame,
) -> pl.DataFrame:
    """Encode type-lossy raw scalars for CSV and SQLite projections only."""

    if not _is_fixed_raw_authority_table(table):
        return df
    convenience_columns = [
        column_name
        for column_name, dtype in df.schema.items()
        if dtype in (pl.Binary, pl.String, pl.Null)
    ]
    if not convenience_columns:
        return df
    return df.with_columns(
        pl.col(column_name)
        .map_elements(
            _encode_convenience_scalar,
            return_dtype=pl.String,
            skip_nulls=False,
        )
        .alias(column_name)
        for column_name in convenience_columns
    )


class CSVLoader(BaseLoader):
    def __init__(self, csv_dir: Path) -> None:
        self.csv_dir = csv_dir

    def load(
        self,
        table: str,
        df: pl.DataFrame,
        mode: Literal["replace", "append"] = "replace",
    ) -> None:
        validate_sql_identifier(table)
        if "/" in table or "\\" in table or ".." in table:
            raise ValueError(f"Invalid table name: {table!r}")
        if mode == "append":
            raise NotImplementedError("append mode not supported for CSV — overwrite only")
        self.csv_dir.mkdir(parents=True, exist_ok=True)
        output_path = self.csv_dir / f"{table}.csv"
        projected = _project_raw_authority_convenience_frame(table, df)
        projected.write_csv(output_path)
        logger.debug(f"CSV: wrote {df.shape[0]} rows to {output_path.name}")
