from __future__ import annotations

from typing import ClassVar

from nbadb.transform.base import SqlTransformer


class FactTeamPlayerDashboardTransformer(SqlTransformer):
    output_table: ClassVar[str] = "fact_team_player_dashboard"
    depends_on: ClassVar[list[str]] = ["stg_team_player_dashboard"]

    _SQL: ClassVar[str] = """
        SELECT *
        FROM stg_team_player_dashboard
    """
