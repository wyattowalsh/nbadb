from __future__ import annotations

from typing import ClassVar

from nbadb.transform.base import SqlTransformer


class FactShotChartTransformer(SqlTransformer):
    output_table: ClassVar[str] = "fact_shot_chart"
    depends_on: ClassVar[list[str]] = ["stg_shot_chart", "dim_game"]

    _SQL: ClassVar[str] = """
        SELECT
            s.grid_type,
            s.game_id,
            s.game_event_id,
            s.player_id,
            s.player_name,
            s.team_id,
            s.team_name,
            s.league_id,
            COALESCE(
                CAST(s.season_year AS VARCHAR),
                CAST(g.season_year AS VARCHAR)
            ) AS season_year,
            COALESCE(
                CAST(s.season_type AS VARCHAR),
                CAST(g.season_type AS VARCHAR)
            ) AS season_type,
            s.period, s.minutes_remaining, s.seconds_remaining,
            s.event_type, s.action_type, s.shot_type,
            s.shot_zone_basic, s.shot_zone_area, s.shot_zone_range,
            s.shot_distance, s.loc_x, s.loc_y,
            s.shot_attempted_flag, s.shot_made_flag,
            COALESCE(s.game_date, g.game_date) AS game_date,
            s.htm, s.vtm
        FROM stg_shot_chart s
        LEFT JOIN dim_game g ON s.game_id = g.game_id
    """
