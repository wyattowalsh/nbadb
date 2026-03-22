from __future__ import annotations

from typing import ClassVar

from nbadb.transform.base import SqlTransformer


class FactPlayerPtRebDetailTransformer(SqlTransformer):
    output_table: ClassVar[str] = "fact_player_pt_reb_detail"
    depends_on: ClassVar[list[str]] = [
        "stg_player_pt_reb",
        "stg_player_pt_reb_overall",
        "stg_player_pt_reb_distance",
        "stg_player_pt_reb_shot_dist",
        "stg_player_pt_reb_shot_type",
    ]

    _SQL: ClassVar[str] = """
        SELECT *, 'base' AS breakdown_type
        FROM stg_player_pt_reb
        UNION ALL BY NAME
        SELECT *, 'overall' AS breakdown_type
        FROM stg_player_pt_reb_overall
        UNION ALL BY NAME
        SELECT *, 'distance' AS breakdown_type
        FROM stg_player_pt_reb_distance
        UNION ALL BY NAME
        SELECT *, 'shot_dist' AS breakdown_type
        FROM stg_player_pt_reb_shot_dist
        UNION ALL BY NAME
        SELECT *, 'shot_type' AS breakdown_type
        FROM stg_player_pt_reb_shot_type
    """
