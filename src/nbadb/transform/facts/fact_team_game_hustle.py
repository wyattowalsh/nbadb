from __future__ import annotations

from typing import ClassVar

from nbadb.transform.base import SqlTransformer


class FactTeamGameHustleTransformer(SqlTransformer):
    output_table: ClassVar[str] = "fact_team_game_hustle"
    depends_on: ClassVar[list[str]] = ["stg_box_score_hustle_team"]

    _SQL: ClassVar[str] = """
        SELECT *
        FROM stg_box_score_hustle_team
    """
