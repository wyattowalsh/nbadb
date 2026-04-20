from __future__ import annotations

from typing import ClassVar

from nbadb.transform.base import SqlTransformer


class FactPlayerCareerTransformer(SqlTransformer):
    output_table: ClassVar[str] = "fact_player_career"
    depends_on: ClassVar[list[str]] = [
        "stg_player_career_total_regular",
        "stg_player_career_total_postseason",
        "stg_player_career_total_allstar",
        "stg_player_career_total_college",
        "stg_player_career_allstar",
        "stg_player_career_college",
        "stg_player_career_regular",
        "stg_player_career_postseason",
    ]

    _SQL: ClassVar[str] = """
        SELECT *, 'regular' AS career_type
        FROM stg_player_career_total_regular
        UNION ALL BY NAME
        SELECT *, 'postseason' AS career_type
        FROM stg_player_career_total_postseason
        UNION ALL BY NAME
        SELECT *, 'total_allstar' AS career_type
        FROM stg_player_career_total_allstar
        UNION ALL BY NAME
        SELECT *, 'total_college' AS career_type
        FROM stg_player_career_total_college
        UNION ALL BY NAME
        SELECT *, 'allstar' AS career_type
        FROM stg_player_career_allstar
        UNION ALL BY NAME
        SELECT *, 'college' AS career_type
        FROM stg_player_career_college
        UNION ALL BY NAME
        SELECT *, 'season_regular' AS career_type
        FROM stg_player_career_regular
        UNION ALL BY NAME
        SELECT *, 'season_postseason' AS career_type
        FROM stg_player_career_postseason
    """
