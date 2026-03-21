from __future__ import annotations

from typing import ClassVar

from nbadb.transform.base import SqlTransformer


class FactTeamPtRebDetailTransformer(SqlTransformer):
    output_table: ClassVar[str] = "fact_team_pt_reb_detail"
    depends_on: ClassVar[list[str]] = ["stg_team_pt_reb"]

    _SQL: ClassVar[str] = """SELECT * FROM stg_team_pt_reb"""
