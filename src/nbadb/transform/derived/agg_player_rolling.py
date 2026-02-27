from __future__ import annotations

from typing import TYPE_CHECKING, ClassVar

import duckdb

from nbadb.transform.base import BaseTransformer

if TYPE_CHECKING:
    import polars as pl


class AggPlayerRollingTransformer(BaseTransformer):
    output_table: ClassVar[str] = "agg_player_rolling"
    depends_on: ClassVar[list[str]] = ["fact_player_game_traditional", "dim_game"]

    _SQL: ClassVar[str] = """
        SELECT
            t.game_id, t.player_id, g.game_date,
            AVG(t.pts) OVER w5 AS pts_roll5,
            AVG(t.reb) OVER w5 AS reb_roll5,
            AVG(t.ast) OVER w5 AS ast_roll5,
            AVG(t.pts) OVER w10 AS pts_roll10,
            AVG(t.reb) OVER w10 AS reb_roll10,
            AVG(t.ast) OVER w10 AS ast_roll10,
            AVG(t.pts) OVER w20 AS pts_roll20,
            AVG(t.reb) OVER w20 AS reb_roll20,
            AVG(t.ast) OVER w20 AS ast_roll20
        FROM fact_player_game_traditional t
        JOIN dim_game g ON t.game_id = g.game_id
        WINDOW
            w5 AS (PARTITION BY t.player_id ORDER BY g.game_date
                   ROWS BETWEEN 4 PRECEDING AND CURRENT ROW),
            w10 AS (PARTITION BY t.player_id ORDER BY g.game_date
                    ROWS BETWEEN 9 PRECEDING AND CURRENT ROW),
            w20 AS (PARTITION BY t.player_id ORDER BY g.game_date
                    ROWS BETWEEN 19 PRECEDING AND CURRENT ROW)
        ORDER BY t.player_id, g.game_date
    """

    def transform(self, staging: dict[str, pl.LazyFrame]) -> pl.DataFrame:
        conn = duckdb.connect()
        conn.register(
            "fact_player_game_traditional",
            staging["fact_player_game_traditional"].collect(),
        )
        conn.register("dim_game", staging["dim_game"].collect())
        result = conn.execute(self._SQL).pl()
        conn.close()
        return result
