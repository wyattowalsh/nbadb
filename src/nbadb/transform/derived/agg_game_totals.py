from __future__ import annotations

from typing import ClassVar

from nbadb.transform.base import SqlTransformer


class AggGameTotalsTransformer(SqlTransformer):
    output_table: ClassVar[str] = "agg_game_totals"
    depends_on: ClassVar[list[str]] = [
        "fact_team_game",
        "bridge_game_team",
        "dim_game",
    ]

    _SQL: ClassVar[str] = """
        WITH home_stats AS (
            SELECT
                t.game_id,
                t.team_id AS home_team_id,
                t.pts     AS home_pts,
                t.reb     AS home_reb,
                t.ast     AS home_ast,
                t.fgm::FLOAT / NULLIF(t.fga, 0) AS home_fg_pct
            FROM fact_team_game t
            JOIN bridge_game_team b
                ON t.game_id = b.game_id AND t.team_id = b.team_id
            WHERE b.side = 'home'
        ),
        away_stats AS (
            SELECT
                t.game_id,
                t.team_id AS away_team_id,
                t.pts     AS away_pts,
                t.reb     AS away_reb,
                t.ast     AS away_ast,
                t.fgm::FLOAT / NULLIF(t.fga, 0) AS away_fg_pct
            FROM fact_team_game t
            JOIN bridge_game_team b
                ON t.game_id = b.game_id AND t.team_id = b.team_id
            WHERE b.side = 'away'
        )
        SELECT
            g.game_id,
            g.game_date,
            g.season_year,
            g.season_type,
            h.home_team_id,
            a.away_team_id,
            h.home_pts,
            a.away_pts,
            h.home_pts + a.away_pts AS total_pts,
            h.home_reb,
            a.away_reb,
            h.home_ast,
            a.away_ast,
            h.home_fg_pct,
            a.away_fg_pct
        FROM dim_game g
        JOIN home_stats h ON g.game_id = h.game_id
        JOIN away_stats a ON g.game_id = a.game_id
    """
