from __future__ import annotations

from typing import ClassVar

from nbadb.transform.base import SqlTransformer


class FactShotChartLineupTransformer(SqlTransformer):
    output_table: ClassVar[str] = "fact_shot_chart_lineup"
    depends_on: ClassVar[list[str]] = [
        "stg_shot_chart_lineup",
        "stg_shot_chart_lineup_detail",
    ]

    _SQL: ClassVar[str] = """
        SELECT *, 'lineup' AS chart_type
        FROM stg_shot_chart_lineup
        UNION ALL BY NAME
        SELECT *, 'lineup_detail' AS chart_type
        FROM stg_shot_chart_lineup_detail
    """
