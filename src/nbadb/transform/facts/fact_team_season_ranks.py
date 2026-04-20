from __future__ import annotations

from typing import ClassVar

from nbadb.transform.base import SqlTransformer


class FactTeamSeasonRanksTransformer(SqlTransformer):
    output_table: ClassVar[str] = "fact_team_season_ranks"
    depends_on: ClassVar[list[str]] = ["stg_team_season_ranks"]

    _SQL: ClassVar[str] = """
        SELECT *
        FROM stg_team_season_ranks
    """
