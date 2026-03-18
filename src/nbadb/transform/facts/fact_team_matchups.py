from __future__ import annotations

from typing import ClassVar

from nbadb.transform.base import SqlTransformer


class FactTeamMatchupsTransformer(SqlTransformer):
    output_table: ClassVar[str] = "fact_team_matchups"
    depends_on: ClassVar[list[str]] = [
        "stg_team_vs_player",
        "stg_team_and_players_vs",
        "stg_team_and_players_vs_players",
    ]

    _SQL: ClassVar[str] = """
        SELECT *, 'team_vs_player' AS matchup_type
        FROM stg_team_vs_player
        UNION ALL BY NAME
        SELECT *, 'team_and_players_vs' AS matchup_type
        FROM stg_team_and_players_vs
        UNION ALL BY NAME
        SELECT *, 'team_and_players_vs_players' AS matchup_type
        FROM stg_team_and_players_vs_players
    """
