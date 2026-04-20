from __future__ import annotations

from typing import ClassVar

from nbadb.transform.base import SqlTransformer


class FactStaticPlayersTransformer(SqlTransformer):
    output_table: ClassVar[str] = "fact_static_players"
    depends_on: ClassVar[list[str]] = ["stg_static_players"]

    _SQL: ClassVar[str] = """
        SELECT *
        FROM stg_static_players
    """


class FactStaticTeamsTransformer(SqlTransformer):
    output_table: ClassVar[str] = "fact_static_teams"
    depends_on: ClassVar[list[str]] = ["stg_static_teams"]

    _SQL: ClassVar[str] = """
        SELECT *
        FROM stg_static_teams
    """
