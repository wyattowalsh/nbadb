from __future__ import annotations

from typing import ClassVar

from nbadb.transform.base import SqlTransformer


class FactTeamAvailableSeasonsTransformer(SqlTransformer):
    output_table: ClassVar[str] = "fact_team_available_seasons"
    depends_on: ClassVar[list[str]] = ["stg_team_available_seasons"]

    _SQL: ClassVar[str] = """SELECT * FROM stg_team_available_seasons"""
