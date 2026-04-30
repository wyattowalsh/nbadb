from __future__ import annotations

from typing import ClassVar

from nbadb.transform.base import SqlTransformer


class FactLeagueLeadersDetailTransformer(SqlTransformer):
    output_table: ClassVar[str] = "fact_league_leaders_detail"
    depends_on: ClassVar[list[str]] = [
        "fact_league_leaders",
        "fact_assist_leaders",
        "fact_assist_tracker",
        "fact_dunk_score_leaders",
        "fact_gravity_leaders",
    ]

    _SQL: ClassVar[str] = """
        SELECT *, 'league' AS leader_type
        FROM fact_league_leaders
        UNION ALL BY NAME
        SELECT *, 'assist' AS leader_type
        FROM fact_assist_leaders
        UNION ALL BY NAME
        SELECT *, 'assist_tracker' AS leader_type
        FROM fact_assist_tracker
        UNION ALL BY NAME
        SELECT *, 'dunk_score' AS leader_type
        FROM fact_dunk_score_leaders
        UNION ALL BY NAME
        SELECT *, 'gravity' AS leader_type
        FROM fact_gravity_leaders
    """
