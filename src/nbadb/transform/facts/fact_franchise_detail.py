from __future__ import annotations

from typing import ClassVar

from nbadb.transform.base import SqlTransformer


class FactFranchiseDetailTransformer(SqlTransformer):
    output_table: ClassVar[str] = "fact_franchise_detail"
    depends_on: ClassVar[list[str]] = [
        "stg_franchise_leaders",
        "stg_franchise_players",
    ]

    _SQL: ClassVar[str] = """
        SELECT *, 'leaders' AS detail_type
        FROM stg_franchise_leaders
        UNION ALL BY NAME
        SELECT *, 'players' AS detail_type
        FROM stg_franchise_players
    """
