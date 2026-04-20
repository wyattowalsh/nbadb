from __future__ import annotations

from typing import ClassVar

from nbadb.transform.base import SqlTransformer


class FactShotChartLeagueTransformer(SqlTransformer):
    output_table: ClassVar[str] = "fact_shot_chart_league"
    depends_on: ClassVar[list[str]] = ["stg_shot_chart_league_wide"]

    _SQL: ClassVar[str] = """
        SELECT *
        FROM stg_shot_chart_league_wide
    """
