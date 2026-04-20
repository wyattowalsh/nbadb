from __future__ import annotations

from typing import ClassVar

from nbadb.transform.base import SqlTransformer


class FactBoxScoreSummaryV3Transformer(SqlTransformer):
    output_table: ClassVar[str] = "fact_box_score_summary_v3"
    depends_on: ClassVar[list[str]] = [
        "stg_summary_v3_game_summary",
        "stg_summary_v3_game_info",
        "stg_summary_v3_line_score",
        "stg_summary_v3_officials",
        "stg_summary_v3_other_stats",
        "stg_summary_v3_inactive_players",
        "stg_summary_v3_last_five_meetings",
        "stg_summary_v3_available_video",
    ]

    _SQL: ClassVar[str] = """
        SELECT *, 'game_summary' AS summary_type
        FROM stg_summary_v3_game_summary
        UNION ALL BY NAME
        SELECT *, 'game_info' AS summary_type
        FROM stg_summary_v3_game_info
        UNION ALL BY NAME
        SELECT *, 'line_score' AS summary_type
        FROM stg_summary_v3_line_score
        UNION ALL BY NAME
        SELECT *, 'officials' AS summary_type
        FROM stg_summary_v3_officials
        UNION ALL BY NAME
        SELECT *, 'other_stats' AS summary_type
        FROM stg_summary_v3_other_stats
        UNION ALL BY NAME
        SELECT *, 'inactive_players' AS summary_type
        FROM stg_summary_v3_inactive_players
        UNION ALL BY NAME
        SELECT *, 'last_five_meetings' AS summary_type
        FROM stg_summary_v3_last_five_meetings
        UNION ALL BY NAME
        SELECT *, 'available_video' AS summary_type
        FROM stg_summary_v3_available_video
    """
