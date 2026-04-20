from __future__ import annotations

from typing import ClassVar

from nbadb.transform.base import SqlTransformer


class FactPlayerPtTrackingTransformer(SqlTransformer):
    output_table: ClassVar[str] = "fact_player_pt_tracking"
    depends_on: ClassVar[list[str]] = [
        "stg_player_pt_pass",
        "stg_player_pt_pass_received",
        "stg_player_pt_reb",
        "stg_player_pt_shots",
        "stg_player_pt_shot_defend",
    ]

    _SQL: ClassVar[str] = """
        SELECT *, 'pass' AS tracking_type
        FROM stg_player_pt_pass
        UNION ALL BY NAME
        SELECT *, 'pass_received' AS tracking_type
        FROM stg_player_pt_pass_received
        UNION ALL BY NAME
        SELECT *, 'rebound' AS tracking_type
        FROM stg_player_pt_reb
        UNION ALL BY NAME
        SELECT *, 'shots' AS tracking_type
        FROM stg_player_pt_shots
        UNION ALL BY NAME
        SELECT *, 'shot_defend' AS tracking_type
        FROM stg_player_pt_shot_defend
    """
