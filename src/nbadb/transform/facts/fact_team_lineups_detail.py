from __future__ import annotations

from typing import ClassVar

from nbadb.transform.base import SqlTransformer


class FactTeamLineupsDetailTransformer(SqlTransformer):
    output_table: ClassVar[str] = "fact_team_lineups_detail"
    depends_on: ClassVar[list[str]] = ["stg_team_lineups_overall"]

    _SQL: ClassVar[str] = """SELECT * FROM stg_team_lineups_overall"""
