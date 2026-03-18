from __future__ import annotations

from typing import ClassVar

from nbadb.transform.base import SqlTransformer


class FactPlayerSplitsTransformer(SqlTransformer):
    output_table: ClassVar[str] = "fact_player_splits"
    depends_on: ClassVar[list[str]] = [
        "stg_player_dash_game_splits",
        "stg_player_dash_general_splits",
        "stg_player_dash_last_n_games",
        "stg_player_dash_shooting_splits",
        "stg_player_dash_team_perf",
        "stg_player_dash_yoy",
    ]

    _SQL: ClassVar[str] = """
        SELECT *, 'game_splits' AS split_type
        FROM stg_player_dash_game_splits
        UNION ALL BY NAME
        SELECT *, 'general_splits' AS split_type
        FROM stg_player_dash_general_splits
        UNION ALL BY NAME
        SELECT *, 'last_n_games' AS split_type
        FROM stg_player_dash_last_n_games
        UNION ALL BY NAME
        SELECT *, 'shooting_splits' AS split_type
        FROM stg_player_dash_shooting_splits
        UNION ALL BY NAME
        SELECT *, 'team_perf' AS split_type
        FROM stg_player_dash_team_perf
        UNION ALL BY NAME
        SELECT *, 'yoy' AS split_type
        FROM stg_player_dash_yoy
    """
