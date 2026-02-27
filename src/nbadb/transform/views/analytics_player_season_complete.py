from __future__ import annotations

from typing import TYPE_CHECKING, ClassVar

import duckdb

from nbadb.transform.base import BaseTransformer

if TYPE_CHECKING:
    import polars as pl


class AnalyticsPlayerSeasonCompleteTransformer(BaseTransformer):
    output_table: ClassVar[str] = "analytics_player_season_complete"
    depends_on: ClassVar[list[str]] = [
        "agg_player_season",
        "agg_player_season_per36",
        "agg_player_season_per100",
        "dim_player",
        "dim_team",
    ]

    _SQL: ClassVar[str] = """
        SELECT
            s.player_id,
            s.season_year,
            s.team_id,
            p.player_name,
            tm.team_abbreviation,
            -- totals
            s.gp, s.total_min,
            s.total_pts, s.total_reb, s.total_ast,
            s.total_stl, s.total_blk, s.total_tov,
            s.avg_pts, s.avg_reb, s.avg_ast,
            s.avg_fg_pct, s.avg_fg3_pct, s.avg_ft_pct,
            s.avg_off_rating, s.avg_def_rating, s.avg_net_rating,
            s.avg_pie,
            -- per-36
            p36.pts_per36, p36.reb_per36, p36.ast_per36,
            p36.stl_per36, p36.blk_per36, p36.tov_per36,
            -- per-100
            p100.pts_per100, p100.reb_per100, p100.ast_per100,
            p100.stl_per100, p100.blk_per100, p100.tov_per100
        FROM agg_player_season s
        LEFT JOIN agg_player_season_per36 p36
            ON s.player_id = p36.player_id AND s.season_year = p36.season_year
        LEFT JOIN agg_player_season_per100 p100
            ON s.player_id = p100.player_id AND s.season_year = p100.season_year
        LEFT JOIN dim_player p ON s.player_id = p.player_id
        LEFT JOIN dim_team tm ON s.team_id = tm.team_id
        ORDER BY s.season_year, s.avg_pts DESC
    """

    def transform(self, staging: dict[str, pl.LazyFrame]) -> pl.DataFrame:
        conn = duckdb.connect()
        for dep in self.depends_on:
            conn.register(dep, staging[dep].collect())
        result = conn.execute(self._SQL).pl()
        conn.close()
        return result
