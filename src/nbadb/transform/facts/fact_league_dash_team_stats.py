from __future__ import annotations

from typing import TYPE_CHECKING, ClassVar

from nbadb.transform.base import BaseTransformer

if TYPE_CHECKING:
    import polars as pl


class FactLeagueDashTeamStatsTransformer(BaseTransformer):
    output_table: ClassVar[str] = "fact_league_dash_team_stats"
    depends_on: ClassVar[list[str]] = ["stg_league_dash_team_stats"]

    _SQL: ClassVar[str] = """
        SELECT *
        FROM stg_league_dash_team_stats
        ORDER BY team_id
    """

    def transform(self, staging: dict[str, pl.LazyFrame]) -> pl.DataFrame:
        return self._conn.execute(self._SQL).pl()
