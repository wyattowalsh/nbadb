from __future__ import annotations

from typing import ClassVar

from nbadb.transform.base import SqlTransformer


class FactLeagueShotLocationsTransformer(SqlTransformer):
    output_table: ClassVar[str] = "fact_league_shot_locations"
    depends_on: ClassVar[list[str]] = ["stg_league_team_shot_locations"]

    _SQL: ClassVar[str] = """
        SELECT *
        FROM stg_league_team_shot_locations
    """
