from __future__ import annotations

from typing import ClassVar

from nbadb.transform.base import SqlTransformer


class FactSeasonMatchupsTransformer(SqlTransformer):
    output_table: ClassVar[str] = "fact_season_matchups"
    depends_on: ClassVar[list[str]] = [
        "stg_season_matchups",
        "stg_matchups_rollup",
    ]

    _SQL: ClassVar[str] = """
        SELECT *, 'detail' AS matchup_type
        FROM stg_season_matchups
        UNION ALL BY NAME
        SELECT *, 'rollup' AS matchup_type
        FROM stg_matchups_rollup
    """
