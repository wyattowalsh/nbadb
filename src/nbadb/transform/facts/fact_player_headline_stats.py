from __future__ import annotations

from typing import ClassVar

from nbadb.transform.base import SqlTransformer


class FactPlayerHeadlineStatsTransformer(SqlTransformer):
    output_table: ClassVar[str] = "fact_player_headline_stats"
    depends_on: ClassVar[list[str]] = ["stg_player_headline_stats"]

    _SQL: ClassVar[str] = """
        SELECT *
        FROM stg_player_headline_stats
    """
