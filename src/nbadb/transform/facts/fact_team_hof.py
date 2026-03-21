from __future__ import annotations

from typing import ClassVar

from nbadb.transform.base import SqlTransformer


class FactTeamHofTransformer(SqlTransformer):
    output_table: ClassVar[str] = "fact_team_hof"
    depends_on: ClassVar[list[str]] = ["stg_team_hof"]

    _SQL: ClassVar[str] = """
        SELECT *
        FROM stg_team_hof
    """
