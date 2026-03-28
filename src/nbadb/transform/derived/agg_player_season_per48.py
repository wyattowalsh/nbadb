from __future__ import annotations

from typing import ClassVar

from nbadb.transform.base import SqlTransformer


class AggPlayerSeasonPer48Transformer(SqlTransformer):
    output_table: ClassVar[str] = "agg_player_season_per48"
    depends_on: ClassVar[list[str]] = ["agg_player_season"]

    _SQL: ClassVar[str] = """
        SELECT
            player_id, team_id, season_year, season_type, gp, avg_min,
            total_pts * 48.0 / NULLIF(total_min, 0) AS pts_per48,
            total_reb * 48.0 / NULLIF(total_min, 0) AS reb_per48,
            total_ast * 48.0 / NULLIF(total_min, 0) AS ast_per48,
            total_stl * 48.0 / NULLIF(total_min, 0) AS stl_per48,
            total_blk * 48.0 / NULLIF(total_min, 0) AS blk_per48,
            total_tov * 48.0 / NULLIF(total_min, 0) AS tov_per48
        FROM agg_player_season
    """
