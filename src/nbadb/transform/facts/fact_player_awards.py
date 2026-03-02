from __future__ import annotations

from typing import TYPE_CHECKING, ClassVar

from nbadb.transform.base import BaseTransformer

if TYPE_CHECKING:
    import polars as pl


class FactPlayerAwardsTransformer(BaseTransformer):
    output_table: ClassVar[str] = "fact_player_awards"
    depends_on: ClassVar[list[str]] = ["stg_player_awards"]

    _SQL: ClassVar[str] = """
        SELECT *
        FROM stg_player_awards
        ORDER BY season_year, player_id
    """

    def transform(self, staging: dict[str, pl.LazyFrame]) -> pl.DataFrame:
        return self._conn.execute(self._SQL).pl()
