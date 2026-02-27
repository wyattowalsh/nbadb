from __future__ import annotations

from typing import TYPE_CHECKING, ClassVar

import duckdb

from nbadb.transform.base import BaseTransformer

if TYPE_CHECKING:
    import polars as pl


class AggPlayerSeasonTransformer(BaseTransformer):
    output_table: ClassVar[str] = "agg_player_season"
    depends_on: ClassVar[list[str]] = [
        "fact_player_game_traditional",
        "fact_player_game_advanced",
        "fact_player_game_misc",
        "dim_game",
    ]

    _SQL: ClassVar[str] = """
        SELECT
            t.player_id,
            t.team_id,
            g.season_year,
            g.season_type,
            COUNT(*) AS gp,
            SUM(t.min) AS total_min,
            AVG(t.min) AS avg_min,
            SUM(t.pts) AS total_pts, AVG(t.pts) AS avg_pts,
            SUM(t.reb) AS total_reb, AVG(t.reb) AS avg_reb,
            SUM(t.ast) AS total_ast, AVG(t.ast) AS avg_ast,
            SUM(t.stl) AS total_stl, AVG(t.stl) AS avg_stl,
            SUM(t.blk) AS total_blk, AVG(t.blk) AS avg_blk,
            SUM(t.tov) AS total_tov, AVG(t.tov) AS avg_tov,
            SUM(t.fgm) AS total_fgm, SUM(t.fga) AS total_fga,
            CASE WHEN SUM(t.fga)>0
                 THEN SUM(t.fgm)::FLOAT/SUM(t.fga) ELSE NULL END AS fg_pct,
            SUM(t.fg3m) AS total_fg3m, SUM(t.fg3a) AS total_fg3a,
            CASE WHEN SUM(t.fg3a)>0
                 THEN SUM(t.fg3m)::FLOAT/SUM(t.fg3a) ELSE NULL END AS fg3_pct,
            SUM(t.ftm) AS total_ftm, SUM(t.fta) AS total_fta,
            CASE WHEN SUM(t.fta)>0
                 THEN SUM(t.ftm)::FLOAT/SUM(t.fta) ELSE NULL END AS ft_pct,
            AVG(a.off_rating) AS avg_off_rating,
            AVG(a.def_rating) AS avg_def_rating,
            AVG(a.net_rating) AS avg_net_rating,
            AVG(a.ts_pct) AS avg_ts_pct,
            AVG(a.usg_pct) AS avg_usg_pct,
            AVG(a.pie) AS avg_pie
        FROM fact_player_game_traditional t
        JOIN dim_game g ON t.game_id = g.game_id
        LEFT JOIN fact_player_game_advanced a
            ON t.game_id = a.game_id AND t.player_id = a.player_id
        GROUP BY t.player_id, t.team_id, g.season_year, g.season_type
        ORDER BY g.season_year, t.player_id, t.team_id
    """

    def transform(self, staging: dict[str, pl.LazyFrame]) -> pl.DataFrame:
        conn = duckdb.connect()
        conn.register(
            "fact_player_game_traditional",
            staging["fact_player_game_traditional"].collect(),
        )
        conn.register("dim_game", staging["dim_game"].collect())
        conn.register(
            "fact_player_game_advanced",
            staging["fact_player_game_advanced"].collect(),
        )
        result = conn.execute(self._SQL).pl()
        conn.close()
        return result
