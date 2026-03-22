from __future__ import annotations

from typing import ClassVar

from nbadb.transform.base import SqlTransformer


class FactPlayerLastNDetailTransformer(SqlTransformer):
    output_table: ClassVar[str] = "fact_player_last_n_detail"
    depends_on: ClassVar[list[str]] = [
        "stg_player_lastn_game_number",
        "stg_player_lastn_last10",
        "stg_player_lastn_last15",
        "stg_player_lastn_last20",
        "stg_player_lastn_last5",
        "stg_player_lastn_overall",
    ]

    _SQL: ClassVar[str] = """
        SELECT *, 'game_number' AS window_size
        FROM stg_player_lastn_game_number
        UNION ALL BY NAME
        SELECT *, 'last10' AS window_size
        FROM stg_player_lastn_last10
        UNION ALL BY NAME
        SELECT *, 'last15' AS window_size
        FROM stg_player_lastn_last15
        UNION ALL BY NAME
        SELECT *, 'last20' AS window_size
        FROM stg_player_lastn_last20
        UNION ALL BY NAME
        SELECT *, 'last5' AS window_size
        FROM stg_player_lastn_last5
        UNION ALL BY NAME
        SELECT *, 'overall' AS window_size
        FROM stg_player_lastn_overall
    """
