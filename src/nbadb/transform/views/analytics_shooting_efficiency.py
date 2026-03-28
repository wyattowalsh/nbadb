from __future__ import annotations

from typing import ClassVar

from nbadb.transform.base import SqlTransformer


class AnalyticsShootingEfficiencyTransformer(SqlTransformer):
    output_table: ClassVar[str] = "analytics_shooting_efficiency"
    depends_on: ClassVar[list[str]] = [
        "fact_shot_chart",
        "fact_shot_chart_league_averages",
        "dim_player",
        "dim_game",
    ]

    _SQL: ClassVar[str] = """
        SELECT
            s.player_id,
            s.game_id,
            s.team_id,
            p.full_name AS player_name,
            g.season_year,
            g.game_date,
            s.shot_zone_basic,
            s.shot_zone_area,
            s.shot_zone_range,
            s.shot_distance,
            s.shot_type,
            s.shot_made_flag,
            s.loc_x,
            s.loc_y,
            la.fgm AS league_avg_fgm,
            la.fga AS league_avg_fga,
            la.fg_pct AS league_avg_fg_pct
        FROM fact_shot_chart s
        LEFT JOIN fact_shot_chart_league_averages la
            ON s.shot_zone_basic = la.shot_zone_basic
            AND s.shot_zone_area = la.shot_zone_area
            AND s.shot_zone_range = la.shot_zone_range
        -- is_current=TRUE: player name from current record; team_id from fact table
        LEFT JOIN dim_player p ON s.player_id = p.player_id AND p.is_current = TRUE
        LEFT JOIN dim_game g ON s.game_id = g.game_id
    """
