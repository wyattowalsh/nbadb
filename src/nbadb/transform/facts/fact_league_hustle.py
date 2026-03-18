from __future__ import annotations

from typing import ClassVar

from nbadb.transform.base import SqlTransformer


class FactLeagueHustleTransformer(SqlTransformer):
    output_table: ClassVar[str] = "fact_league_hustle"
    depends_on: ClassVar[list[str]] = [
        "stg_league_hustle_player",
        "stg_league_hustle_team",
    ]

    _SQL: ClassVar[str] = """
        SELECT *, 'player' AS entity_type
        FROM stg_league_hustle_player
        UNION ALL BY NAME
        SELECT *, 'team' AS entity_type
        FROM stg_league_hustle_team
    """
