from __future__ import annotations

from typing import ClassVar

from nbadb.transform.base import SqlTransformer


class FactFantasyTransformer(SqlTransformer):
    output_table: ClassVar[str] = "fact_fantasy"
    depends_on: ClassVar[list[str]] = [
        "stg_fanduel_player",
        "stg_fantasy_widget",
        "stg_player_fantasy_profile_last_five_games_avg",
        "stg_player_fantasy_profile_season_avg",
    ]

    _SQL: ClassVar[str] = """
        SELECT *, 'fanduel' AS fantasy_source
        FROM stg_fanduel_player
        UNION ALL BY NAME
        SELECT *, 'fantasy_widget' AS fantasy_source
        FROM stg_fantasy_widget
        UNION ALL BY NAME
        SELECT *, 'player_fantasy_profile_last_five_games_avg' AS fantasy_source
        FROM stg_player_fantasy_profile_last_five_games_avg
        UNION ALL BY NAME
        SELECT *, 'player_fantasy_profile_season_avg' AS fantasy_source
        FROM stg_player_fantasy_profile_season_avg
    """
