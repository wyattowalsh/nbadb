from __future__ import annotations

from typing import TYPE_CHECKING, ClassVar

import duckdb

from nbadb.transform.base import BaseTransformer

if TYPE_CHECKING:
    import polars as pl


class FactPlayByPlayTransformer(BaseTransformer):
    output_table: ClassVar[str] = "fact_play_by_play"
    depends_on: ClassVar[list[str]] = ["stg_play_by_play"]

    _SQL: ClassVar[str] = """
        SELECT
            game_id,
            event_num,
            event_msg_type,
            event_msg_action_type,
            period,
            wc_time_string,
            pc_time_string,
            home_description,
            neutral_description,
            visitor_description,
            score,
            score_margin,
            player1_id, player1_team_id,
            player2_id, player2_team_id,
            player3_id, player3_team_id,
            CASE event_msg_type
                WHEN 1 THEN 'made_shot'
                WHEN 2 THEN 'missed_shot'
                WHEN 3 THEN 'free_throw'
                WHEN 4 THEN 'rebound'
                WHEN 5 THEN 'turnover'
                WHEN 6 THEN 'foul'
                WHEN 7 THEN 'violation'
                WHEN 8 THEN 'substitution'
                WHEN 9 THEN 'timeout'
                WHEN 10 THEN 'jump_ball'
                WHEN 11 THEN 'ejection'
                WHEN 12 THEN 'period_start'
                WHEN 13 THEN 'period_end'
                ELSE 'unknown'
            END AS event_type_name
        FROM stg_play_by_play
        ORDER BY game_id, event_num
    """

    def transform(self, staging: dict[str, pl.LazyFrame]) -> pl.DataFrame:
        conn = duckdb.connect()
        conn.register("stg_play_by_play", staging["stg_play_by_play"].collect())
        result = conn.execute(self._SQL).pl()
        conn.close()
        return result
