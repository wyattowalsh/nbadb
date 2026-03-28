from __future__ import annotations

from typing import ClassVar

from nbadb.transform.base import SqlTransformer


class AnalyticsGameSummaryTransformer(SqlTransformer):
    output_table: ClassVar[str] = "analytics_game_summary"
    depends_on: ClassVar[list[str]] = [
        "fact_game_result",
        "dim_game",
        "bridge_game_team",
        "dim_team",
    ]

    _SQL: ClassVar[str] = """
        SELECT
            g.game_id,
            g.game_date,
            g.season_year,
            g.season_type,
            g.matchup,
            g.arena_name,
            h.team_id AS home_team_id,
            ht.full_name AS home_team_name,
            ht.abbreviation AS home_team_abbreviation,
            a.team_id AS away_team_id,
            awt.full_name AS away_team_name,
            awt.abbreviation AS away_team_abbreviation,
            r.pts_home,
            r.pts_away,
            r.plus_minus_home,
            r.wl_home,
            r.pts_qtr1_home, r.pts_qtr2_home,
            r.pts_qtr3_home, r.pts_qtr4_home,
            r.pts_ot1_home, r.pts_ot2_home,
            r.pts_qtr1_away, r.pts_qtr2_away,
            r.pts_qtr3_away, r.pts_qtr4_away,
            r.pts_ot1_away, r.pts_ot2_away
        FROM dim_game g
        INNER JOIN fact_game_result r ON g.game_id = r.game_id
        LEFT JOIN bridge_game_team h
            ON g.game_id = h.game_id AND h.side = 'home'
        LEFT JOIN bridge_game_team a
            ON g.game_id = a.game_id AND a.side = 'away'
        LEFT JOIN dim_team ht ON h.team_id = ht.team_id
        LEFT JOIN dim_team awt ON a.team_id = awt.team_id
    """
