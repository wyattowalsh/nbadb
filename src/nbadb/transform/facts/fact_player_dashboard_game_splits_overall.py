from __future__ import annotations

from typing import ClassVar

from nbadb.transform.base import SqlTransformer


class FactPlayerDashboardGameSplitsOverallTransformer(SqlTransformer):
    output_table: ClassVar[str] = "fact_player_dashboard_game_splits_overall"
    depends_on: ClassVar[list[str]] = ["stg_player_dashboard_game_splits"]

    _SQL: ClassVar[str] = """
        SELECT *
        FROM stg_player_dashboard_game_splits
    """
