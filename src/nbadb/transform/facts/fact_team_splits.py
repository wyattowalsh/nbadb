from __future__ import annotations

from typing import ClassVar

from nbadb.transform.base import SqlTransformer


class FactTeamSplitsTransformer(SqlTransformer):
    output_table: ClassVar[str] = "fact_team_splits"
    depends_on: ClassVar[list[str]] = [
        "stg_team_dash_general_splits",
        "stg_team_dash_shooting_splits",
    ]

    _SQL: ClassVar[str] = """
        SELECT *, 'general' AS split_type
        FROM stg_team_dash_general_splits
        UNION ALL BY NAME
        SELECT *, 'shooting' AS split_type
        FROM stg_team_dash_shooting_splits
    """
