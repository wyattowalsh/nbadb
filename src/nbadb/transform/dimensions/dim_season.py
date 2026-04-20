from __future__ import annotations

from typing import TYPE_CHECKING, ClassVar

from nbadb.transform.base import BaseTransformer

if TYPE_CHECKING:
    import polars as pl


class DimSeasonTransformer(BaseTransformer):
    output_table: ClassVar[str] = "dim_season"
    depends_on: ClassVar[list[str]] = ["stg_league_game_log"]

    def transform(self, staging: dict[str, pl.LazyFrame]) -> pl.DataFrame:
        import polars as pl

        gl = staging["stg_league_game_log"]
        return (
            gl.select("season_year", "game_date")
            .group_by("season_year")
            .agg(
                pl.col("game_date").min().alias("start_date"),
                pl.col("game_date").max().alias("end_date"),
            )
            .sort("season_year")
            .collect()  # ty: ignore[invalid-return-type]
        )
