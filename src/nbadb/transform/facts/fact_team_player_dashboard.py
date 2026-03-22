from __future__ import annotations

from typing import ClassVar

from nbadb.transform.base import SqlTransformer


class FactTeamPlayerDashboardTransformer(SqlTransformer):
    output_table: ClassVar[str] = "fact_team_player_dashboard"
    depends_on: ClassVar[list[str]] = [
        "stg_team_player_dashboard",
        "stg_team_player_dash_players",
        "stg_team_player_dash_overall",
    ]

    _SQL: ClassVar[str] = """
        SELECT *, 'dashboard' AS dashboard_type
        FROM stg_team_player_dashboard
        UNION ALL BY NAME
        SELECT *, 'players' AS dashboard_type
        FROM stg_team_player_dash_players
        UNION ALL BY NAME
        SELECT *, 'overall' AS dashboard_type
        FROM stg_team_player_dash_overall
    """
