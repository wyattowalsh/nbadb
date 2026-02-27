from __future__ import annotations

from typing import TYPE_CHECKING, ClassVar

import duckdb

from nbadb.transform.base import BaseTransformer

if TYPE_CHECKING:
    import polars as pl


class FactPlayerGameTraditionalTransformer(BaseTransformer):
    output_table: ClassVar[str] = "fact_player_game_traditional"
    depends_on: ClassVar[list[str]] = ["stg_box_score_traditional"]

    _SQL: ClassVar[str] = """
        SELECT
            game_id, player_id, team_id,
            start_position, comment, min,
            fgm, fga, fg_pct,
            fg3m, fg3a, fg3_pct,
            ftm, fta, ft_pct,
            oreb, dreb, reb,
            ast, stl, blk, tov, pf,
            pts, plus_minus
        FROM stg_box_score_traditional
        WHERE player_id IS NOT NULL
    """

    def transform(self, staging: dict[str, pl.LazyFrame]) -> pl.DataFrame:
        conn = duckdb.connect()
        conn.register("stg_box_score_traditional", staging["stg_box_score_traditional"].collect())
        result = conn.execute(self._SQL).pl()
        conn.close()
        return result
