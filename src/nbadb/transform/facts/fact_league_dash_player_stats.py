from __future__ import annotations

from typing import TYPE_CHECKING, ClassVar

from nbadb.transform.base import BaseTransformer

if TYPE_CHECKING:
    import polars as pl


class FactLeagueDashPlayerStatsTransformer(BaseTransformer):
    output_table: ClassVar[str] = "fact_league_dash_player_stats"
    depends_on: ClassVar[list[str]] = ["stg_league_dash_player_stats"]

    _SQL: ClassVar[str] = """
        SELECT *
        FROM stg_league_dash_player_stats
        ORDER BY player_id
    """

    def transform(self, staging: dict[str, pl.LazyFrame]) -> pl.DataFrame:
        return self._conn.execute(self._SQL).pl()
