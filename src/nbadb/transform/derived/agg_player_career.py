from __future__ import annotations

from typing import ClassVar

from nbadb.transform.base import SqlTransformer


class AggPlayerCareerTransformer(SqlTransformer):
    output_table: ClassVar[str] = "agg_player_career"
    depends_on: ClassVar[list[str]] = ["agg_player_season"]

    _SQL: ClassVar[str] = """
        SELECT
            player_id,
            SUM(gp) AS career_gp,
            SUM(total_min) AS career_min,
            SUM(total_pts) AS career_pts,
            SUM(total_pts)::FLOAT / NULLIF(SUM(gp), 0) AS career_ppg,
            SUM(total_reb)::FLOAT / NULLIF(SUM(gp), 0) AS career_rpg,
            SUM(total_ast)::FLOAT / NULLIF(SUM(gp), 0) AS career_apg,
            SUM(total_stl)::FLOAT / NULLIF(SUM(gp), 0) AS career_spg,
            SUM(total_blk)::FLOAT / NULLIF(SUM(gp), 0) AS career_bpg,
            SUM(total_fgm)::FLOAT / NULLIF(SUM(total_fga), 0) AS career_fg_pct,
            SUM(total_fg3m)::FLOAT / NULLIF(SUM(total_fg3a), 0) AS career_fg3_pct,
            SUM(total_ftm)::FLOAT / NULLIF(SUM(total_fta), 0) AS career_ft_pct,
            MIN(season_year) AS first_season,
            MAX(season_year) AS last_season,
            COUNT(DISTINCT season_year) AS seasons_played
        FROM agg_player_season
        WHERE season_type = 'Regular Season'
        GROUP BY player_id
        ORDER BY career_pts DESC
    """
