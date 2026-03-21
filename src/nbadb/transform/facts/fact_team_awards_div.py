from __future__ import annotations

from typing import ClassVar

from nbadb.transform.base import SqlTransformer


class FactTeamAwardsDivTransformer(SqlTransformer):
    output_table: ClassVar[str] = "fact_team_awards_div"
    depends_on: ClassVar[list[str]] = ["stg_team_awards_div"]

    _SQL: ClassVar[str] = """
        SELECT *
        FROM stg_team_awards_div
    """
