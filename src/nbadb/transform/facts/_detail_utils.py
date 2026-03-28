from __future__ import annotations

from typing import Any

import polars as pl


def empty_frame(schema: dict[str, Any]) -> pl.DataFrame:
    return pl.DataFrame(
        {column: pl.Series(column, [], dtype=dtype) for column, dtype in schema.items()}
    )


def typed_column(df: pl.DataFrame, column: str, dtype: Any) -> pl.Expr:
    if column in df.columns:
        return pl.col(column).cast(dtype, strict=False).alias(column)
    return pl.lit(None).cast(dtype, strict=False).alias(column)
