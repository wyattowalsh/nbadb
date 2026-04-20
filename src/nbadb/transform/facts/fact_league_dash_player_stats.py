from __future__ import annotations

from typing import ClassVar

from nbadb.transform.base import SqlTransformer


class FactLeagueDashPlayerStatsTransformer(SqlTransformer):
    output_table: ClassVar[str] = "fact_league_dash_player_stats"
    depends_on: ClassVar[list[str]] = ["stg_league_dash_player_stats"]

    _SQL: ClassVar[str] = """
        SELECT *
        FROM stg_league_dash_player_stats
    """
