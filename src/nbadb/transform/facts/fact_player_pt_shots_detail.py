from __future__ import annotations

from typing import ClassVar

from nbadb.transform.base import SqlTransformer


class FactPlayerPtShotsDetailTransformer(SqlTransformer):
    output_table: ClassVar[str] = "fact_player_pt_shots_detail"
    depends_on: ClassVar[list[str]] = [
        "stg_player_pt_shots",
        "stg_player_pt_shots_closest_def",
        "stg_player_pt_shots_dribble",
        "stg_player_pt_shots_general",
        "stg_player_pt_shots_overall",
        "stg_player_pt_shots_shot_clock",
        "stg_player_pt_shots_touch_time",
    ]

    _SQL: ClassVar[str] = """
        SELECT *, 'base' AS breakdown_type
        FROM stg_player_pt_shots
        UNION ALL BY NAME
        SELECT *, 'closest_def' AS breakdown_type
        FROM stg_player_pt_shots_closest_def
        UNION ALL BY NAME
        SELECT *, 'dribble' AS breakdown_type
        FROM stg_player_pt_shots_dribble
        UNION ALL BY NAME
        SELECT *, 'general' AS breakdown_type
        FROM stg_player_pt_shots_general
        UNION ALL BY NAME
        SELECT *, 'overall' AS breakdown_type
        FROM stg_player_pt_shots_overall
        UNION ALL BY NAME
        SELECT *, 'shot_clock' AS breakdown_type
        FROM stg_player_pt_shots_shot_clock
        UNION ALL BY NAME
        SELECT *, 'touch_time' AS breakdown_type
        FROM stg_player_pt_shots_touch_time
    """
