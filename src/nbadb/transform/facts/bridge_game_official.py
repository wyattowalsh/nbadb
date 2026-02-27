from __future__ import annotations

from typing import TYPE_CHECKING, ClassVar

import duckdb

from nbadb.transform.base import BaseTransformer

if TYPE_CHECKING:
    import polars as pl


class BridgeGameOfficialTransformer(BaseTransformer):
    output_table: ClassVar[str] = "bridge_game_official"
    depends_on: ClassVar[list[str]] = ["stg_officials"]

    _SQL: ClassVar[str] = """
        SELECT DISTINCT game_id, official_id
        FROM stg_officials
        ORDER BY game_id, official_id
    """

    def transform(self, staging: dict[str, pl.LazyFrame]) -> pl.DataFrame:
        conn = duckdb.connect()
        conn.register("stg_officials", staging["stg_officials"].collect())
        result = conn.execute(self._SQL).pl()
        conn.close()
        return result
