from __future__ import annotations

import hashlib
import json
from typing import TYPE_CHECKING, ClassVar

from nbadb.transform.base import BaseTransformer

if TYPE_CHECKING:
    import polars as pl

_MAX_SIGNED_BIGINT = (1 << 63) - 1


def _stable_arena_id(value: dict[str, str | None]) -> int:
    """Return a reproducible positive BIGINT for one exact name/city identity."""

    identity = json.dumps(
        [value["arena_name"], value["arena_city"]],
        ensure_ascii=False,
        separators=(",", ":"),
    ).encode()
    return int.from_bytes(hashlib.sha256(identity).digest()[:8], "big") % _MAX_SIGNED_BIGINT + 1


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
            pl.struct("arena_name", "arena_city")
            .map_elements(_stable_arena_id, return_dtype=pl.Int64)
            .alias("arena_id")
        )

        result = (
            arenas.select(
                pl.col("arena_id").cast(pl.Int64),
                "arena_name",
                pl.col("arena_city").alias("city"),
                pl.col("arena_state").alias("state"),
                pl.col("arena_country").alias("country"),
                pl.col("arena_timezone").alias("timezone"),
            )
            .sort("arena_name")
            .collect()
        )
        if result["arena_id"].n_unique() != result.height:
            raise ValueError("deterministic arena surrogate collision")
        return result
