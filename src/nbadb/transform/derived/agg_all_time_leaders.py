from __future__ import annotations

from typing import TYPE_CHECKING, ClassVar

from nbadb.transform.base import BaseTransformer

if TYPE_CHECKING:
    import polars as pl


class AggAllTimeLeadersTransformer(BaseTransformer):
    output_table: ClassVar[str] = "agg_all_time_leaders"
    depends_on: ClassVar[list[str]] = ["stg_all_time"]

    _SQL: ClassVar[str] = """
        SELECT
            *,
            ROW_NUMBER() OVER (ORDER BY pts DESC NULLS LAST) AS pts_rank,
            ROW_NUMBER() OVER (ORDER BY ast DESC NULLS LAST) AS ast_rank,
            ROW_NUMBER() OVER (ORDER BY reb DESC NULLS LAST) AS reb_rank
        FROM stg_all_time
        ORDER BY pts_rank
    """

    def transform(self, staging: dict[str, pl.LazyFrame]) -> pl.DataFrame:
        return self.conn.execute(self._SQL).pl()
