from __future__ import annotations

from typing import ClassVar

from nbadb.transform.base import SqlTransformer


class FactPlayerDashboardYoyOverallTransformer(SqlTransformer):
    output_table: ClassVar[str] = "fact_player_dashboard_yoy_overall"
    depends_on: ClassVar[list[str]] = ["stg_player_dashboard_year_over_year"]

    _SQL: ClassVar[str] = """
        SELECT *
        FROM stg_player_dashboard_year_over_year
    """
