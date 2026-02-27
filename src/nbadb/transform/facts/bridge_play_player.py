from __future__ import annotations

from typing import TYPE_CHECKING, ClassVar

import duckdb

from nbadb.transform.base import BaseTransformer

if TYPE_CHECKING:
    import polars as pl


class BridgePlayPlayerTransformer(BaseTransformer):
    output_table: ClassVar[str] = "bridge_play_player"
    depends_on: ClassVar[list[str]] = ["stg_play_by_play"]

    _SQL: ClassVar[str] = """
        SELECT game_id, event_num, 1 AS slot, player1_id AS player_id,
               player1_team_id AS team_id
        FROM stg_play_by_play WHERE player1_id IS NOT NULL
        UNION ALL
        SELECT game_id, event_num, 2 AS slot, player2_id AS player_id,
               player2_team_id AS team_id
        FROM stg_play_by_play WHERE player2_id IS NOT NULL
        UNION ALL
        SELECT game_id, event_num, 3 AS slot, player3_id AS player_id,
               player3_team_id AS team_id
        FROM stg_play_by_play WHERE player3_id IS NOT NULL
        ORDER BY game_id, event_num, slot
    """

    def transform(self, staging: dict[str, pl.LazyFrame]) -> pl.DataFrame:
        conn = duckdb.connect()
        conn.register("stg_play_by_play", staging["stg_play_by_play"].collect())
        result = conn.execute(self._SQL).pl()
        conn.close()
        return result
