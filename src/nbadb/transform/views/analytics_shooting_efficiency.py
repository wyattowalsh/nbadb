from __future__ import annotations

from typing import ClassVar

from nbadb.transform.base import SqlTransformer


class AnalyticsShootingEfficiencyTransformer(SqlTransformer):
    output_table: ClassVar[str] = "analytics_shooting_efficiency"
    depends_on: ClassVar[list[str]] = [
        "fact_shot_chart",
        "fact_shot_chart_league_averages",
    ]

    _SQL: ClassVar[str] = """
        WITH average_distinct AS (
            SELECT DISTINCT
                season_year,
                season_type,
                league_id,
                shot_zone_basic,
                shot_zone_area,
                shot_zone_range,
                fgm,
                fga,
                fg_pct
            FROM fact_shot_chart_league_averages
            WHERE average_source = 'shot_chart_detail'
        ),
        average_authority AS (
            SELECT
                season_year,
                season_type,
                league_id,
                shot_zone_basic,
                shot_zone_area,
                shot_zone_range,
                CASE WHEN COUNT(*) > 1
                    THEN error('conflicting scoped shot-chart league averages')
                    ELSE MIN(fgm) END AS fgm,
                MIN(fga) AS fga,
                MIN(fg_pct) AS fg_pct
            FROM average_distinct
            GROUP BY
                season_year,
                season_type,
                league_id,
                shot_zone_basic,
                shot_zone_area,
                shot_zone_range
        )
        SELECT
            s.player_id,
            s.game_id,
            s.game_event_id,
            s.team_id,
            s.player_name,
            s.league_id,
            s.season_year,
            s.season_type,
            s.game_date,
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
            la.fg_pct AS league_avg_fg_pct,
            CASE
                WHEN s.shot_type LIKE '3PT%' THEN 3.0
                WHEN s.shot_type LIKE '2PT%' THEN 2.0
                ELSE NULL
            END AS shot_value,
            CASE
                WHEN s.shot_made_flag IS NULL THEN NULL
                WHEN s.shot_type LIKE '3PT%' THEN 3 * s.shot_made_flag
                WHEN s.shot_type LIKE '2PT%' THEN 2 * s.shot_made_flag
                ELSE NULL
            END AS actual_points,
            CASE
                WHEN la.fg_pct IS NULL THEN NULL
                WHEN s.shot_type LIKE '3PT%' THEN 3 * la.fg_pct
                WHEN s.shot_type LIKE '2PT%' THEN 2 * la.fg_pct
                ELSE NULL
            END AS empirical_zone_expected_points,
            CASE
                WHEN s.shot_made_flag IS NULL OR la.fg_pct IS NULL THEN NULL
                WHEN s.shot_type LIKE '3PT%'
                    THEN 3 * (s.shot_made_flag - la.fg_pct)
                WHEN s.shot_type LIKE '2PT%'
                    THEN 2 * (s.shot_made_flag - la.fg_pct)
                ELSE NULL
            END AS points_above_empirical_zone_expectation
        FROM fact_shot_chart s
        LEFT JOIN average_authority la
            ON s.shot_zone_basic = la.shot_zone_basic
            AND s.shot_zone_area = la.shot_zone_area
            AND s.shot_zone_range = la.shot_zone_range
            AND s.season_year IS NOT DISTINCT FROM la.season_year
            AND s.season_type IS NOT DISTINCT FROM la.season_type
            AND s.league_id IS NOT DISTINCT FROM la.league_id
    """
