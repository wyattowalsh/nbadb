from __future__ import annotations

from typing import TYPE_CHECKING, ClassVar

import duckdb

from nbadb.transform.base import BaseTransformer

if TYPE_CHECKING:
    import polars as pl


class FactRotationTransformer(BaseTransformer):
    output_table: ClassVar[str] = "fact_rotation"
    depends_on: ClassVar[list[str]] = ["stg_rotation"]

    _SQL: ClassVar[str] = """
        SELECT
            game_id, team_id, player_id,
            team_side,
            in_period, in_time_remaining,
            out_period, out_time_remaining,
            player_pts, pt_diff
        FROM stg_rotation
        ORDER BY game_id, team_id, in_period, in_time_remaining DESC
    """

    def transform(self, staging: dict[str, pl.LazyFrame]) -> pl.DataFrame:
        conn = duckdb.connect()
        conn.register("stg_rotation", staging["stg_rotation"].collect())
        result = conn.execute(self._SQL).pl()
        conn.close()
        return result
