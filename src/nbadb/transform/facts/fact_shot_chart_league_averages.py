from __future__ import annotations

from typing import ClassVar

from nbadb.transform.base import SqlTransformer


class FactShotChartLeagueAveragesTransformer(SqlTransformer):
    output_table: ClassVar[str] = "fact_shot_chart_league_averages"
    depends_on: ClassVar[list[str]] = [
        "stg_shot_chart_league_averages",
        "stg_shot_chart_lineup_league_avg",
    ]

    _SQL: ClassVar[str] = """
        SELECT *, 'shot_chart_detail' AS average_source
        FROM stg_shot_chart_league_averages
        UNION ALL BY NAME
        SELECT *, 'shot_chart_lineup_detail' AS average_source
        FROM stg_shot_chart_lineup_league_avg
    """
