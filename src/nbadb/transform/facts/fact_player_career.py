from __future__ import annotations

from typing import ClassVar

from nbadb.transform.base import SqlTransformer


class FactPlayerCareerTransformer(SqlTransformer):
    output_table: ClassVar[str] = "fact_player_career"
    depends_on: ClassVar[list[str]] = [
        "stg_player_career_total_regular",
        "stg_player_career_total_postseason",
        "stg_player_career_allstar",
        "stg_player_career_college",
    ]

    _SQL: ClassVar[str] = """
        SELECT *, 'regular' AS career_type
        FROM stg_player_career_total_regular
        UNION ALL BY NAME
        SELECT *, 'postseason' AS career_type
        FROM stg_player_career_total_postseason
        UNION ALL BY NAME
        SELECT *, 'allstar' AS career_type
        FROM stg_player_career_allstar
        UNION ALL BY NAME
        SELECT *, 'college' AS career_type
        FROM stg_player_career_college
    """
