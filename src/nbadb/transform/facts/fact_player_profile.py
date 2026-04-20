from __future__ import annotations

from typing import ClassVar

from nbadb.transform.base import SqlTransformer


class FactPlayerProfileTransformer(SqlTransformer):
    output_table: ClassVar[str] = "fact_player_profile"
    depends_on: ClassVar[list[str]] = [
        "stg_player_profile_career_highs",
        "stg_player_profile_season_highs",
        "stg_player_profile_next_game",
        "stg_player_profile_regular",
        "stg_player_profile_postseason",
        "stg_player_profile_allstar",
        "stg_player_profile_college",
        "stg_player_profile_preseason",
        "stg_player_profile_ranks_regular",
        "stg_player_profile_ranks_postseason",
        "stg_player_profile_total_regular",
        "stg_player_profile_total_postseason",
        "stg_player_profile_total_allstar",
        "stg_player_profile_total_college",
        "stg_player_profile_total_preseason",
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
        UNION ALL BY NAME
        SELECT *, 'season_regular' AS profile_type
        FROM stg_player_profile_regular
        UNION ALL BY NAME
        SELECT *, 'season_postseason' AS profile_type
        FROM stg_player_profile_postseason
        UNION ALL BY NAME
        SELECT *, 'season_allstar' AS profile_type
        FROM stg_player_profile_allstar
        UNION ALL BY NAME
        SELECT *, 'season_college' AS profile_type
        FROM stg_player_profile_college
        UNION ALL BY NAME
        SELECT *, 'season_preseason' AS profile_type
        FROM stg_player_profile_preseason
        UNION ALL BY NAME
        SELECT *, 'ranks_regular' AS profile_type
        FROM stg_player_profile_ranks_regular
        UNION ALL BY NAME
        SELECT *, 'ranks_postseason' AS profile_type
        FROM stg_player_profile_ranks_postseason
        UNION ALL BY NAME
        SELECT *, 'total_regular' AS profile_type
        FROM stg_player_profile_total_regular
        UNION ALL BY NAME
        SELECT *, 'total_postseason' AS profile_type
        FROM stg_player_profile_total_postseason
        UNION ALL BY NAME
        SELECT *, 'total_allstar' AS profile_type
        FROM stg_player_profile_total_allstar
        UNION ALL BY NAME
        SELECT *, 'total_college' AS profile_type
        FROM stg_player_profile_total_college
        UNION ALL BY NAME
        SELECT *, 'total_preseason' AS profile_type
        FROM stg_player_profile_total_preseason
    """
