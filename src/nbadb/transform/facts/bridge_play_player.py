from __future__ import annotations

from typing import ClassVar

from nbadb.transform.base import SqlTransformer


class BridgePlayPlayerTransformer(SqlTransformer):
    output_table: ClassVar[str] = "bridge_play_player"
    depends_on: ClassVar[list[str]] = ["stg_play_by_play"]

    _SQL: ClassVar[str] = """
        SELECT
            game_id,
            action_number AS event_num,
            person_id AS player_id,
            team_id,
            'primary' AS player_role
        FROM stg_play_by_play
        WHERE person_id IS NOT NULL
    """
