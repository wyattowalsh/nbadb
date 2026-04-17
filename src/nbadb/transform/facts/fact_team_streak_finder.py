from __future__ import annotations

from typing import ClassVar

from nbadb.transform.base import SqlTransformer


class FactTeamStreakFinderTransformer(SqlTransformer):
    output_table: ClassVar[str] = "fact_team_streak_finder"
    depends_on: ClassVar[list[str]] = ["stg_team_streak_finder"]

    _SQL: ClassVar[str] = """
        SELECT *
        FROM stg_team_streak_finder
    """
