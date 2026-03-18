from __future__ import annotations

from typing import ClassVar

from nbadb.transform.base import SqlTransformer


class FactCumulativeStatsTransformer(SqlTransformer):
    output_table: ClassVar[str] = "fact_cumulative_stats"
    depends_on: ClassVar[list[str]] = [
        "stg_cume_player",
        "stg_cume_player_games",
        "stg_cume_team",
        "stg_cume_team_games",
    ]

    _SQL: ClassVar[str] = """
        SELECT *, 'player' AS entity_type, 'stats' AS stat_type
        FROM stg_cume_player
        UNION ALL BY NAME
        SELECT *, 'player' AS entity_type, 'games' AS stat_type
        FROM stg_cume_player_games
        UNION ALL BY NAME
        SELECT *, 'team' AS entity_type, 'stats' AS stat_type
        FROM stg_cume_team
        UNION ALL BY NAME
        SELECT *, 'team' AS entity_type, 'games' AS stat_type
        FROM stg_cume_team_games
    """
