from __future__ import annotations

from typing import ClassVar

from nbadb.transform.base import SqlTransformer


class FactCumulativeStatsDetailTransformer(SqlTransformer):
    output_table: ClassVar[str] = "fact_cumulative_stats_detail"
    depends_on: ClassVar[list[str]] = [
        "stg_cume_player_game_by_game",
        "stg_cume_player_totals",
        "stg_cume_team_game_by_game",
        "stg_cume_team_totals",
    ]

    _SQL: ClassVar[str] = """
        SELECT *, 'player_game_by_game' AS cume_type
        FROM stg_cume_player_game_by_game
        UNION ALL BY NAME
        SELECT *, 'player_totals' AS cume_type
        FROM stg_cume_player_totals
        UNION ALL BY NAME
        SELECT *, 'team_game_by_game' AS cume_type
        FROM stg_cume_team_game_by_game
        UNION ALL BY NAME
        SELECT *, 'team_totals' AS cume_type
        FROM stg_cume_team_totals
    """
