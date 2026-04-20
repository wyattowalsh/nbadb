from __future__ import annotations

from typing import TYPE_CHECKING, ClassVar

from nbadb.transform.base import BaseTransformer

if TYPE_CHECKING:
    import polars as pl


class DimArenaTransformer(BaseTransformer):
    output_table: ClassVar[str] = "dim_arena"
    depends_on: ClassVar[list[str]] = [
        "stg_schedule",
        "stg_league_game_log",
        "stg_arena_info",
    ]

    def transform(self, staging: dict[str, pl.LazyFrame]) -> pl.DataFrame:
        import polars as pl

        sched = staging["stg_schedule"].select("arena_name", "arena_city")
        gl = staging["stg_league_game_log"].select("arena_name", "arena_city")
        arenas = pl.concat([sched, gl]).unique(subset=["arena_name", "arena_city"], keep="first")

        arena_info = (
            staging["stg_arena_info"]
            .select(
                "arena_name",
                "arena_city",
                "arena_state",
                "arena_country",
                "arena_timezone",
            )
            .unique(subset=["arena_name", "arena_city"], keep="first")
        )

        arenas = arenas.join(
            arena_info,
            on=["arena_name", "arena_city"],
            how="left",
        )

        arenas = arenas.with_columns(
            (pl.concat_str(["arena_name", "arena_city"], separator="|").hash() % 2_147_483_647 + 1)
            .cast(pl.Int32)
            .alias("arena_id")
        )

        return (
            arenas.select(
                pl.col("arena_id").cast(pl.Int32),
                "arena_name",
                "arena_city",
                "arena_state",
                "arena_country",
                "arena_timezone",
            )
            .sort("arena_name")
            .collect()  # ty: ignore[invalid-return-type]
        )
