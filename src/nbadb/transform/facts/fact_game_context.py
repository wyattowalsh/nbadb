from __future__ import annotations

from typing import ClassVar

from nbadb.transform.base import SqlTransformer


class FactGameContextTransformer(SqlTransformer):
    output_table: ClassVar[str] = "fact_game_context"
    depends_on: ClassVar[list[str]] = [
        "stg_game_info",
        "stg_game_summary",
        "stg_other_stats",
        "stg_inactive_players",
        "stg_season_series",
        "stg_last_meeting",
        "stg_game_summary_available_video",
    ]

    _SQL: ClassVar[str] = """
        SELECT s.*, i.* EXCLUDE (game_id), o.* EXCLUDE (game_id),
               'summary' AS context_source
        FROM stg_game_summary s
        LEFT JOIN stg_game_info i USING (game_id)
        LEFT JOIN stg_other_stats o USING (game_id)
        UNION ALL BY NAME
        SELECT *, 'inactive_players' AS context_source
        FROM stg_inactive_players
        UNION ALL BY NAME
        SELECT *, 'season_series' AS context_source
        FROM stg_season_series
        UNION ALL BY NAME
        SELECT *, 'last_meeting' AS context_source
        FROM stg_last_meeting
        UNION ALL BY NAME
        SELECT *, 'available_video' AS context_source
        FROM stg_game_summary_available_video
    """
