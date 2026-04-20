from __future__ import annotations

from typing import ClassVar

from nbadb.transform.base import SqlTransformer


class FactShotChartTransformer(SqlTransformer):
    output_table: ClassVar[str] = "fact_shot_chart"
    depends_on: ClassVar[list[str]] = ["stg_shot_chart", "dim_game"]

    _SQL: ClassVar[str] = """
        SELECT
            s.game_id, s.player_id, s.team_id,
            g.season_year,
            s.period, s.minutes_remaining, s.seconds_remaining,
            s.action_type, s.shot_type,
            s.shot_zone_basic, s.shot_zone_area, s.shot_zone_range,
            s.shot_distance, s.loc_x, s.loc_y,
            s.shot_made_flag
        FROM stg_shot_chart s
        LEFT JOIN dim_game g ON s.game_id = g.game_id
    """
