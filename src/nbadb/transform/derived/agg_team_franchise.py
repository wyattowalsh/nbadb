from __future__ import annotations

from typing import TYPE_CHECKING, ClassVar

import duckdb

from nbadb.transform.base import BaseTransformer

if TYPE_CHECKING:
    import polars as pl


class AggTeamFranchiseTransformer(BaseTransformer):
    output_table: ClassVar[str] = "agg_team_franchise"
    depends_on: ClassVar[list[str]] = ["stg_franchise"]

    _SQL: ClassVar[str] = """
        SELECT *
        FROM stg_franchise
        ORDER BY team_id
    """

    def transform(self, staging: dict[str, pl.LazyFrame]) -> pl.DataFrame:
        conn = duckdb.connect()
        conn.register("stg_franchise", staging["stg_franchise"].collect())
        result = conn.execute(self._SQL).pl()
        conn.close()
        return result
