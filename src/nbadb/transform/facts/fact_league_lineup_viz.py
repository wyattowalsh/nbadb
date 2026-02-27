from __future__ import annotations

from typing import TYPE_CHECKING, ClassVar

import duckdb

from nbadb.transform.base import BaseTransformer

if TYPE_CHECKING:
    import polars as pl


class FactLeagueLineupVizTransformer(BaseTransformer):
    output_table: ClassVar[str] = "fact_league_lineup_viz"
    depends_on: ClassVar[list[str]] = ["stg_league_lineup_viz"]

    _SQL: ClassVar[str] = """
        SELECT *
        FROM stg_league_lineup_viz
        ORDER BY team_id, group_id
    """

    def transform(self, staging: dict[str, pl.LazyFrame]) -> pl.DataFrame:
        conn = duckdb.connect()
        conn.register("stg_league_lineup_viz", staging["stg_league_lineup_viz"].collect())
        result = conn.execute(self._SQL).pl()
        conn.close()
        return result
