from __future__ import annotations

from typing import TYPE_CHECKING, ClassVar

from nbadb.transform.base import BaseTransformer

if TYPE_CHECKING:
    import polars as pl


class DimArenaTransformer(BaseTransformer):
    output_table: ClassVar[str] = "dim_arena"
    depends_on: ClassVar[list[str]] = ["stg_schedule", "stg_league_game_log"]

    def transform(self, staging: dict[str, pl.LazyFrame]) -> pl.DataFrame:
        import polars as pl

        sched = staging["stg_schedule"].select("arena_name", "arena_city")
        gl = staging["stg_league_game_log"].select("arena_name", "arena_city")
        arenas = pl.concat([sched, gl]).unique(subset=["arena_name", "arena_city"], keep="first")
        return (
            arenas.with_row_index("arena_id", offset=1)
            .select(
                pl.col("arena_id").cast(pl.Int32),
                "arena_name",
                "arena_city",
            )
            .sort("arena_name")
            .collect()  # ty: ignore[invalid-return-type]
        )
