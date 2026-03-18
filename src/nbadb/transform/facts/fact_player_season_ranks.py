from __future__ import annotations

from typing import ClassVar

from nbadb.transform.base import SqlTransformer


class FactPlayerSeasonRanksTransformer(SqlTransformer):
    output_table: ClassVar[str] = "fact_player_season_ranks"
    depends_on: ClassVar[list[str]] = [
        "stg_player_season_ranks_regular",
        "stg_player_season_ranks_postseason",
    ]

    _SQL: ClassVar[str] = """
        SELECT *, 'regular' AS rank_type
        FROM stg_player_season_ranks_regular
        UNION ALL BY NAME
        SELECT *, 'postseason' AS rank_type
        FROM stg_player_season_ranks_postseason
    """
