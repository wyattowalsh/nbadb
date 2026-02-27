from __future__ import annotations

from typing import TYPE_CHECKING, ClassVar

import duckdb

from nbadb.transform.base import BaseTransformer

if TYPE_CHECKING:
    import polars as pl


class AggShotLocationSeasonTransformer(BaseTransformer):
    output_table: ClassVar[str] = "agg_shot_location_season"
    depends_on: ClassVar[list[str]] = ["stg_shot_locations"]

    _SQL: ClassVar[str] = """
        SELECT *
        FROM stg_shot_locations
        ORDER BY season_year, player_id
    """

    def transform(self, staging: dict[str, pl.LazyFrame]) -> pl.DataFrame:
        conn = duckdb.connect()
        conn.register("stg_shot_locations", staging["stg_shot_locations"].collect())
        result = conn.execute(self._SQL).pl()
        conn.close()
        return result
