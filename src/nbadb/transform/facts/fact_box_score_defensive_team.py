from __future__ import annotations

from typing import ClassVar

from nbadb.transform.base import SqlTransformer


class FactBoxScoreDefensiveTeamTransformer(SqlTransformer):
    output_table: ClassVar[str] = "fact_box_score_defensive_team"
    depends_on: ClassVar[list[str]] = ["stg_box_score_defensive_team"]

    _SQL: ClassVar[str] = """
        SELECT *
        FROM stg_box_score_defensive_team
    """
