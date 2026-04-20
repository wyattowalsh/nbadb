from __future__ import annotations

from typing import ClassVar

from nbadb.transform.base import SqlTransformer


class FactPlayerTeamPerfDetailTransformer(SqlTransformer):
    output_table: ClassVar[str] = "fact_player_team_perf_detail"
    depends_on: ClassVar[list[str]] = [
        "stg_player_perf_overall",
        "stg_player_perf_pts_scored",
        "stg_player_perf_pts_against",
        "stg_player_perf_score_diff",
    ]

    _SQL: ClassVar[str] = """
        SELECT *, 'overall' AS perf_context
        FROM stg_player_perf_overall
        UNION ALL BY NAME
        SELECT *, 'pts_scored' AS perf_context
        FROM stg_player_perf_pts_scored
        UNION ALL BY NAME
        SELECT *, 'pts_against' AS perf_context
        FROM stg_player_perf_pts_against
        UNION ALL BY NAME
        SELECT *, 'score_diff' AS perf_context
        FROM stg_player_perf_score_diff
    """
