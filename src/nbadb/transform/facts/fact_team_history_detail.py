from __future__ import annotations

from typing import ClassVar

from nbadb.transform.base import SqlTransformer


class FactTeamHistoryDetailTransformer(SqlTransformer):
    output_table: ClassVar[str] = "fact_team_history_detail"
    depends_on: ClassVar[list[str]] = ["stg_team_history"]

    _SQL: ClassVar[str] = """
        SELECT *
        FROM stg_team_history
    """
