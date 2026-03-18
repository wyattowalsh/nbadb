from __future__ import annotations

from typing import ClassVar

from nbadb.transform.base import SqlTransformer


class FactTeamGameLogTransformer(SqlTransformer):
    output_table: ClassVar[str] = "fact_team_game_log"
    depends_on: ClassVar[list[str]] = [
        "stg_team_game_logs_v2",
        "stg_team_game_log",
    ]

    _SQL: ClassVar[str] = """
        SELECT *
        FROM (
            SELECT *
            FROM stg_team_game_logs_v2
            UNION ALL BY NAME
            SELECT *
            FROM stg_team_game_log
        )
        QUALIFY ROW_NUMBER() OVER (
            PARTITION BY team_id, game_id
            ORDER BY team_id
        ) = 1
    """
