from __future__ import annotations

from typing import ClassVar

from nbadb.transform.base import SqlTransformer


class FactStreakFinderTransformer(SqlTransformer):
    output_table: ClassVar[str] = "fact_streak_finder"
    depends_on: ClassVar[list[str]] = [
        "stg_player_streak_finder",
        "stg_player_game_streak_finder",
        "stg_team_streak_finder",
    ]

    _SQL: ClassVar[str] = """
        SELECT *, 'player' AS entity_type
        FROM stg_player_streak_finder
        UNION ALL BY NAME
        SELECT *, 'player_game' AS entity_type
        FROM stg_player_game_streak_finder
        UNION ALL BY NAME
        SELECT *, 'team' AS entity_type
        FROM stg_team_streak_finder
    """
