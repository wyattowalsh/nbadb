from __future__ import annotations

from typing import ClassVar

from nbadb.transform.base import SqlTransformer


class FactWinProbabilityTransformer(SqlTransformer):
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
