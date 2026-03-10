from __future__ import annotations

from typing import ClassVar

from nbadb.transform.base import SqlTransformer


class AnalyticsHeadToHeadTransformer(SqlTransformer):
    output_table: ClassVar[str] = "analytics_head_to_head"
    depends_on: ClassVar[list[str]] = [
        "fact_team_game",
        "dim_team",
        "dim_game",
    ]

    _SQL: ClassVar[str] = """
        WITH game_teams AS (
            SELECT f.game_id, f.team_id, f.pts, g.season_year,
                   CASE WHEN g.home_team_id = f.team_id THEN g.visitor_team_id
                        ELSE g.home_team_id END AS opponent_team_id
            FROM fact_team_game f
            JOIN dim_game g ON f.game_id = g.game_id
        ),
        matchups AS (
            SELECT gt.game_id, gt.team_id, gt.opponent_team_id, gt.season_year,
                   gt.pts, opp.pts AS pts_against,
                   CASE WHEN gt.pts > opp.pts THEN 'W' ELSE 'L' END AS wl
            FROM game_teams gt
            JOIN fact_team_game opp
                ON gt.game_id = opp.game_id AND gt.opponent_team_id = opp.team_id
        )
        SELECT
            m.team_id, m.opponent_team_id, m.season_year,
            t1.abbreviation AS team_abbr,
            t2.abbreviation AS opponent_abbr,
            COUNT(*) AS games_played,
            SUM(CASE WHEN m.wl = 'W' THEN 1 ELSE 0 END) AS wins,
            SUM(CASE WHEN m.wl = 'L' THEN 1 ELSE 0 END) AS losses,
            AVG(m.pts) AS avg_pts_scored,
            AVG(m.pts_against) AS avg_pts_allowed,
            AVG(m.pts - m.pts_against) AS avg_margin
        FROM matchups m
        LEFT JOIN dim_team t1 ON m.team_id = t1.team_id
        LEFT JOIN dim_team t2 ON m.opponent_team_id = t2.team_id
        GROUP BY m.team_id, m.opponent_team_id, m.season_year,
                 t1.abbreviation, t2.abbreviation
        ORDER BY m.season_year, t1.abbreviation, wins DESC
    """
