from __future__ import annotations

from typing import ClassVar

from nbadb.transform.base import SqlTransformer


class FactPlayerGameLogTransformer(SqlTransformer):
    output_table: ClassVar[str] = "fact_player_game_log"
    depends_on: ClassVar[list[str]] = [
        "stg_player_game_logs",
        "stg_player_game_log",
        "stg_player_game_logs_v2",
    ]

    _SQL: ClassVar[str] = """
        SELECT *
        FROM (
            SELECT *
            FROM stg_player_game_logs
            UNION ALL BY NAME
            SELECT *
            FROM stg_player_game_log
            UNION ALL BY NAME
            SELECT *
            FROM stg_player_game_logs_v2
        )
        QUALIFY ROW_NUMBER() OVER (
            PARTITION BY player_id, game_id
            ORDER BY season_year DESC NULLS LAST
        ) = 1
    """
