from __future__ import annotations

from typing import ClassVar

from nbadb.transform.base import SqlTransformer


class FactPlayerProfileTransformer(SqlTransformer):
    output_table: ClassVar[str] = "fact_player_profile"
    depends_on: ClassVar[list[str]] = [
        "stg_player_profile_career_highs",
        "stg_player_profile_season_highs",
        "stg_player_profile_next_game",
    ]

    _SQL: ClassVar[str] = """
        SELECT *, 'career_highs' AS profile_type
        FROM stg_player_profile_career_highs
        UNION ALL BY NAME
        SELECT *, 'season_highs' AS profile_type
        FROM stg_player_profile_season_highs
        UNION ALL BY NAME
        SELECT *, 'next_game' AS profile_type
        FROM stg_player_profile_next_game
    """
