from __future__ import annotations

from typing import ClassVar

from nbadb.transform.base import SqlTransformer


class FactRotationTransformer(SqlTransformer):
    output_table: ClassVar[str] = "fact_rotation"
    depends_on: ClassVar[list[str]] = ["stg_rotation_away", "stg_rotation_home"]

    _SQL: ClassVar[str] = """
        SELECT
            game_id,
            team_id,
            person_id AS player_id,
            in_time_real,
            out_time_real,
            player_pts AS pts,
            pt_diff AS pts_diff,
            usg_pct,
            side
        FROM (
            SELECT *, 'away' AS side FROM stg_rotation_away
            UNION ALL BY NAME
            SELECT *, 'home' AS side FROM stg_rotation_home
        )
    """
