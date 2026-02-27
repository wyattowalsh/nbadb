from __future__ import annotations

from typing import TYPE_CHECKING, ClassVar

import duckdb

from nbadb.transform.base import BaseTransformer

if TYPE_CHECKING:
    import polars as pl


class AggPlayerSeasonPer100Transformer(BaseTransformer):
    output_table: ClassVar[str] = "agg_player_season_per100"
    depends_on: ClassVar[list[str]] = ["agg_player_season"]

    _SQL: ClassVar[str] = """
        SELECT
            player_id, season_year, season_type, gp, avg_min,
            CASE WHEN total_min > 0
                 THEN total_pts * 100.0 * 48.0 / (total_min * 1.0)
                 ELSE NULL END AS pts_per100,
            CASE WHEN total_min > 0
                 THEN total_reb * 100.0 * 48.0 / (total_min * 1.0)
                 ELSE NULL END AS reb_per100,
            CASE WHEN total_min > 0
                 THEN total_ast * 100.0 * 48.0 / (total_min * 1.0)
                 ELSE NULL END AS ast_per100,
            CASE WHEN total_min > 0
                 THEN total_stl * 100.0 * 48.0 / (total_min * 1.0)
                 ELSE NULL END AS stl_per100,
            CASE WHEN total_min > 0
                 THEN total_blk * 100.0 * 48.0 / (total_min * 1.0)
                 ELSE NULL END AS blk_per100,
            CASE WHEN total_min > 0
                 THEN total_tov * 100.0 * 48.0 / (total_min * 1.0)
                 ELSE NULL END AS tov_per100
        FROM agg_player_season
        ORDER BY season_year, player_id
    """

    def transform(self, staging: dict[str, pl.LazyFrame]) -> pl.DataFrame:
        conn = duckdb.connect()
        conn.register("agg_player_season", staging["agg_player_season"].collect())
        result = conn.execute(self._SQL).pl()
        conn.close()
        return result
