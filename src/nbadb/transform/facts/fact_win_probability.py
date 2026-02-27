from __future__ import annotations

from typing import TYPE_CHECKING, ClassVar

import duckdb

from nbadb.transform.base import BaseTransformer

if TYPE_CHECKING:
    import polars as pl


class FactWinProbabilityTransformer(BaseTransformer):
    output_table: ClassVar[str] = "fact_win_probability"
    depends_on: ClassVar[list[str]] = ["stg_win_probability"]

    _SQL: ClassVar[str] = """
        SELECT
            game_id, event_num, period,
            pc_time_string,
            home_pct, visitor_pct,
            home_pts, visitor_pts,
            home_score_margin
        FROM stg_win_probability
        ORDER BY game_id, event_num
    """

    def transform(self, staging: dict[str, pl.LazyFrame]) -> pl.DataFrame:
        conn = duckdb.connect()
        conn.register("stg_win_probability", staging["stg_win_probability"].collect())
        result = conn.execute(self._SQL).pl()
        conn.close()
        return result
