from __future__ import annotations

from typing import ClassVar

from nbadb.transform.base import SqlTransformer


class FactLeagueTeamClutchTransformer(SqlTransformer):
    output_table: ClassVar[str] = "fact_league_team_clutch"
    depends_on: ClassVar[list[str]] = ["stg_league_team_clutch"]

    _SQL: ClassVar[str] = """
        SELECT *
        FROM stg_league_team_clutch
    """
