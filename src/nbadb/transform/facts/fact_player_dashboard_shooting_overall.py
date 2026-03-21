from __future__ import annotations

from typing import ClassVar

from nbadb.transform.base import SqlTransformer


class FactPlayerDashboardShootingOverallTransformer(SqlTransformer):
    output_table: ClassVar[str] = "fact_player_dashboard_shooting_overall"
    depends_on: ClassVar[list[str]] = ["stg_player_dashboard_shooting_splits"]

    _SQL: ClassVar[str] = """
        SELECT *
        FROM stg_player_dashboard_shooting_splits
    """
