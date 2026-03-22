from __future__ import annotations

from typing import ClassVar

from nbadb.transform.base import SqlTransformer


class AnalyticsPlayerMatchupTransformer(SqlTransformer):
    output_table: ClassVar[str] = "analytics_player_matchup"
    depends_on: ClassVar[list[str]] = [
        "fact_player_matchups",
        "dim_player",
        "dim_team",
    ]

    _SQL: ClassVar[str] = """
        SELECT
            m.player_id,
            m.team_id,
            m.vs_player_id,
            m.season_year,
            p1.full_name AS player_name,
            tm.abbreviation AS team_abbreviation,
            p2.full_name AS vs_player_name,
            m.matchup_min,
            m.player_pts,
            m.team_pts,
            m.ast,
            m.tov,
            m.stl,
            m.blk,
            m.fgm, m.fga, m.fg_pct,
            m.fg3m, m.fg3a, m.fg3_pct
        FROM fact_player_matchups m
        LEFT JOIN dim_player p1 ON m.player_id = p1.player_id AND p1.is_current = TRUE
        LEFT JOIN dim_player p2 ON m.vs_player_id = p2.player_id AND p2.is_current = TRUE
        LEFT JOIN dim_team tm ON m.team_id = tm.team_id
        ORDER BY m.season_year, p1.full_name, m.matchup_min DESC NULLS LAST
    """
