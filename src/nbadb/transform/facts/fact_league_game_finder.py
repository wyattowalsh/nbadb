from __future__ import annotations

from typing import ClassVar

from nbadb.transform.base import SqlTransformer


class FactLeagueGameFinderTransformer(SqlTransformer):
    output_table: ClassVar[str] = "fact_league_game_finder"
    depends_on: ClassVar[list[str]] = ["stg_league_game_finder"]

    _SQL: ClassVar[str] = """
        SELECT *
        FROM stg_league_game_finder
    """
