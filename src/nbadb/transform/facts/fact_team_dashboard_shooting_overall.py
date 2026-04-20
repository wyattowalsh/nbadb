from __future__ import annotations

from typing import ClassVar

from nbadb.transform.base import SqlTransformer


class FactTeamDashboardShootingOverallTransformer(SqlTransformer):
    output_table: ClassVar[str] = "fact_team_dashboard_shooting_overall"
    depends_on: ClassVar[list[str]] = ["stg_team_dash_shooting_splits"]

    _SQL: ClassVar[str] = """
        SELECT *
        FROM stg_team_dash_shooting_splits
    """
