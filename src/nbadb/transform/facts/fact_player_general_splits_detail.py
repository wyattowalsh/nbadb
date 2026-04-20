from __future__ import annotations

from typing import ClassVar

from nbadb.transform.base import SqlTransformer


class FactPlayerGeneralSplitsDetailTransformer(SqlTransformer):
    output_table: ClassVar[str] = "fact_player_general_splits_detail"
    depends_on: ClassVar[list[str]] = [
        "stg_player_split_days_rest",
        "stg_player_split_location",
        "stg_player_split_month",
        "stg_player_split_general_overall",
        "stg_player_split_pre_post_allstar",
        "stg_player_split_starting_pos",
        "stg_player_split_wins_losses",
    ]

    _SQL: ClassVar[str] = """
        SELECT *, 'days_rest' AS split_type
        FROM stg_player_split_days_rest
        UNION ALL BY NAME
        SELECT *, 'location' AS split_type
        FROM stg_player_split_location
        UNION ALL BY NAME
        SELECT *, 'month' AS split_type
        FROM stg_player_split_month
        UNION ALL BY NAME
        SELECT *, 'general_overall' AS split_type
        FROM stg_player_split_general_overall
        UNION ALL BY NAME
        SELECT *, 'pre_post_allstar' AS split_type
        FROM stg_player_split_pre_post_allstar
        UNION ALL BY NAME
        SELECT *, 'starting_pos' AS split_type
        FROM stg_player_split_starting_pos
        UNION ALL BY NAME
        SELECT *, 'wins_losses' AS split_type
        FROM stg_player_split_wins_losses
    """
