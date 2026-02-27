from __future__ import annotations

from typing import TYPE_CHECKING, ClassVar

import duckdb

from nbadb.transform.base import BaseTransformer

if TYPE_CHECKING:
    import polars as pl


class AggAllTimeLeadersTransformer(BaseTransformer):
    output_table: ClassVar[str] = "agg_all_time_leaders"
    depends_on: ClassVar[list[str]] = ["stg_all_time"]

    _SQL: ClassVar[str] = """
        SELECT *
        FROM stg_all_time
        ORDER BY player_id
    """

    def transform(self, staging: dict[str, pl.LazyFrame]) -> pl.DataFrame:
        conn = duckdb.connect()
        conn.register("stg_all_time", staging["stg_all_time"].collect())
        result = conn.execute(self._SQL).pl()
        conn.close()
        return result
