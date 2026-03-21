from __future__ import annotations

from typing import ClassVar

from nbadb.transform.base import SqlTransformer


class FactTeamRetiredTransformer(SqlTransformer):
    output_table: ClassVar[str] = "fact_team_retired"
    depends_on: ClassVar[list[str]] = ["stg_team_retired"]

    _SQL: ClassVar[str] = """
        SELECT *
        FROM stg_team_retired
    """
