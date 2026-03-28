from __future__ import annotations

from datetime import date, timedelta
from typing import TYPE_CHECKING, ClassVar

from nbadb.transform.base import BaseTransformer

if TYPE_CHECKING:
    import polars as pl

_NBA_FIRST_DATE = date(1946, 1, 1)


class DimDateTransformer(BaseTransformer):
    output_table: ClassVar[str] = "dim_date"
    depends_on: ClassVar[list[str]] = []

    def transform(self, staging: dict[str, pl.LazyFrame]) -> pl.DataFrame:
        import polars as pl

        end = date.today() + timedelta(days=365)
        dates = pl.date_range(_NBA_FIRST_DATE, end, interval="1d", eager=True)
        df = pl.DataFrame({"date": dates})
        return df.with_columns(
            (
                pl.col("date").dt.year() * 10000
                + pl.col("date").dt.month() * 100
                + pl.col("date").dt.day()
            )
            .cast(pl.Int32)
            .alias("date_key"),
            pl.col("date").dt.strftime("%Y-%m-%d").alias("full_date"),
            pl.col("date").dt.year().alias("year"),
            pl.col("date").dt.month().alias("month"),
            pl.col("date").dt.day().alias("day"),
            pl.col("date").dt.weekday().alias("day_of_week"),
            pl.col("date").dt.strftime("%A").alias("day_name"),
            pl.col("date").dt.strftime("%B").alias("month_name"),
            pl.col("date").dt.weekday().ge(6).alias("is_weekend"),
            pl.when(pl.col("date").dt.month() >= 10)
            .then(
                pl.col("date").dt.year().cast(pl.Utf8)
                + "-"
                + ((pl.col("date").dt.year() + 1) % 100).cast(pl.Utf8).str.zfill(2)
            )
            .otherwise(
                (pl.col("date").dt.year() - 1).cast(pl.Utf8)
                + "-"
                + (pl.col("date").dt.year() % 100).cast(pl.Utf8).str.zfill(2)
            )
            .alias("nba_season"),
        )
