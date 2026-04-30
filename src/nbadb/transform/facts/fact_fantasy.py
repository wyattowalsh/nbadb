from __future__ import annotations

from typing import ClassVar

from nbadb.transform.base import SqlTransformer


class FactFantasyTransformer(SqlTransformer):
    output_table: ClassVar[str] = "fact_fantasy"
    depends_on: ClassVar[list[str]] = [
        "fact_infographic_fanduel_player",
        "fact_fantasy_widget",
        "fact_player_fantasy_profile_last_five_games_avg",
        "fact_player_fantasy_profile_season_avg",
    ]

    _SQL: ClassVar[str] = """
        SELECT *, 'infographic_fanduel_player' AS fantasy_source
        FROM fact_infographic_fanduel_player
        UNION ALL BY NAME
        SELECT *, 'fantasy_widget' AS fantasy_source
        FROM fact_fantasy_widget
        UNION ALL BY NAME
        SELECT *, 'player_fantasy_profile_last_five_games_avg' AS fantasy_source
        FROM fact_player_fantasy_profile_last_five_games_avg
        UNION ALL BY NAME
        SELECT *, 'player_fantasy_profile_season_avg' AS fantasy_source
        FROM fact_player_fantasy_profile_season_avg
    """
