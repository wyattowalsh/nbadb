from __future__ import annotations

from typing import ClassVar

from nbadb.transform.base import SqlTransformer


class FactWinProbPbpTransformer(SqlTransformer):
    output_table: ClassVar[str] = "fact_win_prob_pbp"
    depends_on: ClassVar[list[str]] = ["stg_win_prob_pbp"]

    _SQL: ClassVar[str] = """
        SELECT
            game_id,
            event_num,
            home_pct,
            visitor_pct,
            home_pts,
            visitor_pts,
            home_score_margin,
            period,
            seconds_remaining,
            home_poss_ind,
            home_g,
            description,
            location,
            pctimestring,
            isvisible
        FROM stg_win_prob_pbp
    """
