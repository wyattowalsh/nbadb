from __future__ import annotations

from typing import ClassVar

from nbadb.transform.base import SqlTransformer


class FactLeagueDashTeamStatsTransformer(SqlTransformer):
    output_table: ClassVar[str] = "fact_league_dash_team_stats"
    depends_on: ClassVar[list[str]] = ["stg_league_dash_team_stats"]

    _SQL: ClassVar[str] = """
        SELECT *
        FROM stg_league_dash_team_stats
        ORDER BY team_id
    """
