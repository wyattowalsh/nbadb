from __future__ import annotations

from typing import ClassVar

from nbadb.transform.base import SqlTransformer


class FactBoxScoreFourFactorsTeamTransformer(SqlTransformer):
    output_table: ClassVar[str] = "fact_box_score_four_factors_team"
    depends_on: ClassVar[list[str]] = ["stg_box_score_four_factors_team"]

    _SQL: ClassVar[str] = """
        SELECT *
        FROM stg_box_score_four_factors_team
    """
