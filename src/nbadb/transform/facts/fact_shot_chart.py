from __future__ import annotations

from typing import ClassVar

from nbadb.transform.base import SqlTransformer


class FactShotChartTransformer(SqlTransformer):
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
