from __future__ import annotations

from typing import ClassVar

from nbadb.transform.base import SqlTransformer


class AggLeagueLeadersTransformer(SqlTransformer):
    output_table: ClassVar[str] = "agg_league_leaders"
    depends_on: ClassVar[list[str]] = ["agg_player_season"]

    _SQL: ClassVar[str] = """
        SELECT
            player_id, season_year, season_type,
            gp, avg_pts, avg_reb, avg_ast, avg_stl, avg_blk,
            fg_pct, fg3_pct, ft_pct,
            RANK() OVER (
                PARTITION BY season_year, season_type ORDER BY avg_pts DESC
            ) AS pts_rank,
            RANK() OVER (
                PARTITION BY season_year, season_type ORDER BY avg_reb DESC
            ) AS reb_rank,
            RANK() OVER (
                PARTITION BY season_year, season_type ORDER BY avg_ast DESC
            ) AS ast_rank,
            RANK() OVER (
                PARTITION BY season_year, season_type ORDER BY avg_stl DESC
            ) AS stl_rank,
            RANK() OVER (
                PARTITION BY season_year, season_type ORDER BY avg_blk DESC
            ) AS blk_rank
        FROM agg_player_season
        WHERE gp >= 10
        ORDER BY season_year, pts_rank
    """
