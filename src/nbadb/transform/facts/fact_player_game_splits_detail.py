from __future__ import annotations

from typing import ClassVar

from nbadb.transform.base import SqlTransformer


class FactPlayerGameSplitsDetailTransformer(SqlTransformer):
    output_table: ClassVar[str] = "fact_player_game_splits_detail"
    depends_on: ClassVar[list[str]] = [
        "stg_player_split_actual_margin",
        "stg_player_split_by_half",
        "stg_player_split_by_period",
        "stg_player_split_score_margin",
        "stg_player_split_game_overall",
    ]

    _SQL: ClassVar[str] = """
        SELECT *, 'actual_margin' AS split_type
        FROM stg_player_split_actual_margin
        UNION ALL BY NAME
        SELECT *, 'by_half' AS split_type
        FROM stg_player_split_by_half
        UNION ALL BY NAME
        SELECT *, 'by_period' AS split_type
        FROM stg_player_split_by_period
        UNION ALL BY NAME
        SELECT *, 'score_margin' AS split_type
        FROM stg_player_split_score_margin
        UNION ALL BY NAME
        SELECT *, 'game_overall' AS split_type
        FROM stg_player_split_game_overall
    """
