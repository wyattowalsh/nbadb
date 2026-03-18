from __future__ import annotations

from typing import ClassVar

from nbadb.transform.base import SqlTransformer


class FactGameContextTransformer(SqlTransformer):
    output_table: ClassVar[str] = "fact_game_context"
    depends_on: ClassVar[list[str]] = [
        "stg_game_info",
        "stg_game_summary",
        "stg_other_stats",
        "stg_season_series",
        "stg_last_meeting",
        "stg_inactive_players",
    ]

    _SQL: ClassVar[str] = """
        SELECT
            s.*,
            i.* EXCLUDE (game_id),
            o.* EXCLUDE (game_id)
        FROM stg_game_summary s
        LEFT JOIN stg_game_info i USING (game_id)
        LEFT JOIN stg_other_stats o USING (game_id)
    """
