from __future__ import annotations

from typing import TYPE_CHECKING, ClassVar

from nbadb.transform.base import BaseTransformer

if TYPE_CHECKING:
    import polars as pl


class AggPlayerSeasonPer36Transformer(BaseTransformer):
    output_table: ClassVar[str] = "agg_player_season_per36"
    depends_on: ClassVar[list[str]] = ["agg_player_season"]

    _SQL: ClassVar[str] = """
        SELECT
            player_id, season_year, season_type, gp, avg_min,
            CASE WHEN avg_min>0 THEN avg_pts*36.0/avg_min ELSE NULL END AS pts_per36,
            CASE WHEN avg_min>0 THEN avg_reb*36.0/avg_min ELSE NULL END AS reb_per36,
            CASE WHEN avg_min>0 THEN avg_ast*36.0/avg_min ELSE NULL END AS ast_per36,
            CASE WHEN avg_min>0 THEN avg_stl*36.0/avg_min ELSE NULL END AS stl_per36,
            CASE WHEN avg_min>0 THEN avg_blk*36.0/avg_min ELSE NULL END AS blk_per36,
            CASE WHEN avg_min>0 THEN avg_tov*36.0/avg_min ELSE NULL END AS tov_per36
        FROM agg_player_season
        ORDER BY season_year, player_id
    """

    def transform(self, staging: dict[str, pl.LazyFrame]) -> pl.DataFrame:
        return self._conn.execute(self._SQL).pl()
