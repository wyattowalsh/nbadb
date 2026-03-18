from __future__ import annotations

from typing import ClassVar

from nbadb.transform.base import SqlTransformer


class AggPlayerSeasonPer48Transformer(SqlTransformer):
    output_table: ClassVar[str] = "agg_player_season_per48"
    depends_on: ClassVar[list[str]] = ["agg_player_season"]

    _SQL: ClassVar[str] = """
        SELECT
            player_id, team_id, season_year, season_type, gp, avg_min,
            CASE WHEN total_min > 0
                 THEN total_pts * 48.0 / (total_min * 1.0)
                 ELSE NULL END AS pts_per48,
            CASE WHEN total_min > 0
                 THEN total_reb * 48.0 / (total_min * 1.0)
                 ELSE NULL END AS reb_per48,
            CASE WHEN total_min > 0
                 THEN total_ast * 48.0 / (total_min * 1.0)
                 ELSE NULL END AS ast_per48,
            CASE WHEN total_min > 0
                 THEN total_stl * 48.0 / (total_min * 1.0)
                 ELSE NULL END AS stl_per48,
            CASE WHEN total_min > 0
                 THEN total_blk * 48.0 / (total_min * 1.0)
                 ELSE NULL END AS blk_per48,
            CASE WHEN total_min > 0
                 THEN total_tov * 48.0 / (total_min * 1.0)
                 ELSE NULL END AS tov_per48
        FROM agg_player_season
        ORDER BY season_year, player_id
    """
