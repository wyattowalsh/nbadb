from __future__ import annotations

from typing import TYPE_CHECKING, ClassVar

import duckdb

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
        conn = duckdb.connect()
        conn.register("stg_league_dash_team_stats", staging["stg_league_dash_team_stats"].collect())
        result = conn.execute(self._SQL).pl()
        conn.close()
        return result
