from __future__ import annotations

from typing import ClassVar

from nbadb.transform.base import SqlTransformer


class FactTeamPtTrackingTransformer(SqlTransformer):
    output_table: ClassVar[str] = "fact_team_pt_tracking"
    depends_on: ClassVar[list[str]] = [
        "stg_team_pt_pass",
        "stg_team_pt_reb",
        "stg_team_pt_shots",
    ]

    _SQL: ClassVar[str] = """
        SELECT *, 'pass' AS tracking_type
        FROM stg_team_pt_pass
        UNION ALL BY NAME
        SELECT *, 'rebound' AS tracking_type
        FROM stg_team_pt_reb
        UNION ALL BY NAME
        SELECT *, 'shots' AS tracking_type
        FROM stg_team_pt_shots
    """
