from __future__ import annotations

from typing import ClassVar

from nbadb.transform.base import SqlTransformer


class FactLineupStatsTransformer(SqlTransformer):
    output_table: ClassVar[str] = "fact_lineup_stats"
    depends_on: ClassVar[list[str]] = [
        "stg_lineup",
        "stg_team_lineups",
    ]

    _SQL: ClassVar[str] = """
        SELECT *, 'league' AS lineup_source
        FROM stg_lineup
        UNION ALL BY NAME
        SELECT *, 'team' AS lineup_source
        FROM stg_team_lineups
    """
