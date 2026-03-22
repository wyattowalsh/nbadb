from __future__ import annotations

from typing import ClassVar

from nbadb.transform.base import SqlTransformer


class FactLeagueHustleTransformer(SqlTransformer):
    output_table: ClassVar[str] = "fact_league_hustle"
    depends_on: ClassVar[list[str]] = [
        "stg_league_hustle_player",
        "stg_league_hustle_team",
        "stg_league_hustle_stats_player",
        "stg_league_hustle_stats_team",
        "stg_league_dash_player_bio_stats",
    ]

    _SQL: ClassVar[str] = """
        SELECT *, 'player' AS entity_type
        FROM stg_league_hustle_player
        UNION ALL BY NAME
        SELECT *, 'team' AS entity_type
        FROM stg_league_hustle_team
        UNION ALL BY NAME
        SELECT *, 'hustle_stats_player' AS entity_type
        FROM stg_league_hustle_stats_player
        UNION ALL BY NAME
        SELECT *, 'hustle_stats_team' AS entity_type
        FROM stg_league_hustle_stats_team
        UNION ALL BY NAME
        SELECT *, 'bio_stats' AS entity_type
        FROM stg_league_dash_player_bio_stats
    """
