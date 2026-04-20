from __future__ import annotations

from typing import ClassVar

from nbadb.transform.base import SqlTransformer


class FactPlayerMatchupsTransformer(SqlTransformer):
    output_table: ClassVar[str] = "fact_player_matchups"
    depends_on: ClassVar[list[str]] = [
        "stg_player_vs_player",
        "stg_player_compare",
    ]

    _SQL: ClassVar[str] = """
        SELECT *, 'head_to_head' AS matchup_type
        FROM stg_player_vs_player
        UNION ALL BY NAME
        SELECT *, 'compare' AS matchup_type
        FROM stg_player_compare
    """
