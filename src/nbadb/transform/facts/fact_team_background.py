from __future__ import annotations

from typing import ClassVar

from nbadb.transform.base import SqlTransformer


class FactTeamBackgroundTransformer(SqlTransformer):
    output_table: ClassVar[str] = "fact_team_background"
    depends_on: ClassVar[list[str]] = ["stg_team_background"]

    _SQL: ClassVar[str] = """
        SELECT *
        FROM stg_team_background
    """
