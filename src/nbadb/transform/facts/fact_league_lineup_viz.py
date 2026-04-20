from __future__ import annotations

from typing import ClassVar

from nbadb.transform.base import SqlTransformer


class FactLeagueLineupVizTransformer(SqlTransformer):
    output_table: ClassVar[str] = "fact_league_lineup_viz"
    depends_on: ClassVar[list[str]] = ["stg_league_lineup_viz"]

    _SQL: ClassVar[str] = """
        SELECT *
        FROM stg_league_lineup_viz
    """
