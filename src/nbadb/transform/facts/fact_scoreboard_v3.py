from __future__ import annotations

from typing import ClassVar

from nbadb.transform.base import SqlTransformer


class FactScoreboardV3Transformer(SqlTransformer):
    output_table: ClassVar[str] = "fact_scoreboard_v3"
    depends_on: ClassVar[list[str]] = [
        "stg_scoreboard_v3_broadcaster",
        "stg_scoreboard_v3_line_score",
        "stg_scoreboard_v3_metadata",
        "stg_scoreboard_v3_summary",
        "stg_scoreboard_v3_team_stats",
    ]

    _SQL: ClassVar[str] = """
        SELECT *, 'broadcaster' AS scoreboard_type
        FROM stg_scoreboard_v3_broadcaster
        UNION ALL BY NAME
        SELECT *, 'line_score' AS scoreboard_type
        FROM stg_scoreboard_v3_line_score
        UNION ALL BY NAME
        SELECT *, 'metadata' AS scoreboard_type
        FROM stg_scoreboard_v3_metadata
        UNION ALL BY NAME
        SELECT *, 'summary' AS scoreboard_type
        FROM stg_scoreboard_v3_summary
        UNION ALL BY NAME
        SELECT *, 'team_stats' AS scoreboard_type
        FROM stg_scoreboard_v3_team_stats
    """
