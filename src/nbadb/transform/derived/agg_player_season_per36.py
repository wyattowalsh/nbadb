from __future__ import annotations

from typing import ClassVar

from nbadb.transform.base import SqlTransformer


class AggPlayerSeasonPer36Transformer(SqlTransformer):
    output_table: ClassVar[str] = "agg_player_season_per36"
    depends_on: ClassVar[list[str]] = ["agg_player_season"]

    _SQL: ClassVar[str] = """
        SELECT
            player_id, team_id, season_year, season_type, gp, avg_min,
            avg_pts * 36.0 / NULLIF(avg_min, 0) AS pts_per36,
            avg_reb * 36.0 / NULLIF(avg_min, 0) AS reb_per36,
            avg_ast * 36.0 / NULLIF(avg_min, 0) AS ast_per36,
            avg_stl * 36.0 / NULLIF(avg_min, 0) AS stl_per36,
            avg_blk * 36.0 / NULLIF(avg_min, 0) AS blk_per36,
            avg_tov * 36.0 / NULLIF(avg_min, 0) AS tov_per36
        FROM agg_player_season
    """
