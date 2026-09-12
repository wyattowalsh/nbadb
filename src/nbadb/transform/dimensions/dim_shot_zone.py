from __future__ import annotations

import hashlib
import json
from typing import TYPE_CHECKING, ClassVar

from nbadb.transform.base import BaseTransformer

if TYPE_CHECKING:
    import polars as pl

_MAX_SIGNED_BIGINT = (1 << 63) - 1


def _stable_shot_zone_id(value: dict[str, str | None]) -> int:
    """Return a reproducible positive BIGINT for one exact zone tuple."""

    identity = json.dumps(
        [
            value["shot_zone_basic"],
            value["shot_zone_area"],
            value["shot_zone_range"],
        ],
        ensure_ascii=False,
        separators=(",", ":"),
    ).encode()
    return int.from_bytes(hashlib.sha256(identity).digest()[:8], "big") % _MAX_SIGNED_BIGINT + 1


class DimShotZoneTransformer(BaseTransformer):
    output_table: ClassVar[str] = "dim_shot_zone"
    depends_on: ClassVar[list[str]] = ["stg_shot_chart"]

    def transform(self, staging: dict[str, pl.LazyFrame]) -> pl.DataFrame:
        import polars as pl

        sc = staging["stg_shot_chart"]
        zones = (
            sc.select("shot_zone_basic", "shot_zone_area", "shot_zone_range")
            .unique()
            .drop_nulls()
            .sort("shot_zone_basic", "shot_zone_area", "shot_zone_range")
        )
        zones = zones.with_columns(
            pl.struct("shot_zone_basic", "shot_zone_area", "shot_zone_range")
            .map_elements(_stable_shot_zone_id, return_dtype=pl.Int64)
            .alias("zone_id")
        )

        result = zones.select(
            pl.col("zone_id").cast(pl.Int64),
            "shot_zone_basic",
            "shot_zone_area",
            "shot_zone_range",
        ).collect()
        if result["zone_id"].n_unique() != result.height:
            raise ValueError("deterministic shot-zone surrogate collision")
        return result
