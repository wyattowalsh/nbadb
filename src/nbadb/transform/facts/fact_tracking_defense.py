from __future__ import annotations

from typing import TYPE_CHECKING, ClassVar

import duckdb

from nbadb.transform.base import BaseTransformer

if TYPE_CHECKING:
    import polars as pl


class FactTrackingDefenseTransformer(BaseTransformer):
    output_table: ClassVar[str] = "fact_tracking_defense"
    depends_on: ClassVar[list[str]] = ["stg_tracking_defense"]

    _SQL: ClassVar[str] = """
        SELECT *
        FROM stg_tracking_defense
        ORDER BY season_year, player_id
    """

    def transform(self, staging: dict[str, pl.LazyFrame]) -> pl.DataFrame:
        conn = duckdb.connect()
        conn.register("stg_tracking_defense", staging["stg_tracking_defense"].collect())
        result = conn.execute(self._SQL).pl()
        conn.close()
        return result
