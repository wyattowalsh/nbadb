from __future__ import annotations

from typing import TYPE_CHECKING, ClassVar

import duckdb

from nbadb.transform.base import BaseTransformer

if TYPE_CHECKING:
    import polars as pl


class FactShotChartTransformer(BaseTransformer):
    output_table: ClassVar[str] = "fact_shot_chart"
    depends_on: ClassVar[list[str]] = ["stg_shot_chart"]

    _SQL: ClassVar[str] = """
        SELECT
            game_id, player_id, team_id,
            period, minutes_remaining, seconds_remaining,
            action_type, shot_type,
            zone_basic, zone_area, zone_range,
            shot_distance, loc_x, loc_y,
            shot_made_flag
        FROM stg_shot_chart
        ORDER BY game_id, period, minutes_remaining DESC, seconds_remaining DESC
    """

    def transform(self, staging: dict[str, pl.LazyFrame]) -> pl.DataFrame:
        conn = duckdb.connect()
        conn.register("stg_shot_chart", staging["stg_shot_chart"].collect())
        result = conn.execute(self._SQL).pl()
        conn.close()
        return result
