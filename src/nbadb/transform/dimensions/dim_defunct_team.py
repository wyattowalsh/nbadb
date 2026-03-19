from __future__ import annotations

from typing import ClassVar

from nbadb.transform.base import SqlTransformer


class DimDefunctTeamTransformer(SqlTransformer):
    output_table: ClassVar[str] = "dim_defunct_team"
    depends_on: ClassVar[list[str]] = ["stg_defunct_teams"]

    _SQL: ClassVar[str] = """
        SELECT *
        FROM stg_defunct_teams
    """
