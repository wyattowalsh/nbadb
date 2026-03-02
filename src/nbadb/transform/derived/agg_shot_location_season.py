from __future__ import annotations

from typing import TYPE_CHECKING, ClassVar

from nbadb.transform.base import BaseTransformer

if TYPE_CHECKING:
    import polars as pl


class AggShotLocationSeasonTransformer(BaseTransformer):
    output_table: ClassVar[str] = "agg_shot_location_season"
    depends_on: ClassVar[list[str]] = ["stg_shot_locations"]

    _SQL: ClassVar[str] = """
        SELECT
            *,
            ROW_NUMBER() OVER (
                PARTITION BY season_year
                ORDER BY fgm DESC NULLS LAST
            ) AS season_fgm_rank
        FROM stg_shot_locations
        ORDER BY season_year, season_fgm_rank
    """

    def transform(self, staging: dict[str, pl.LazyFrame]) -> pl.DataFrame:
        return self.conn.execute(self._SQL).pl()
