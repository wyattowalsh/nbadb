from __future__ import annotations

from typing import TYPE_CHECKING, ClassVar

from nbadb.transform.base import BaseTransformer

if TYPE_CHECKING:
    import polars as pl


class DimShotZoneTransformer(BaseTransformer):
    output_table: ClassVar[str] = "dim_shot_zone"
    depends_on: ClassVar[list[str]] = ["stg_shot_chart"]

    def transform(self, staging: dict[str, pl.LazyFrame]) -> pl.DataFrame:
        import polars as pl

        sc = staging["stg_shot_chart"]
        zones = (
            sc.select("shot_zone_basic", "shot_zone_area", "shot_zone_range")
            .unique()
            .sort("shot_zone_basic", "shot_zone_area", "shot_zone_range")
        )
        zones = zones.with_columns(
            (
                pl.concat_str(
                    ["shot_zone_basic", "shot_zone_area", "shot_zone_range"],
                    separator="|",
                ).hash()
                % 2_147_483_647
                + 1
            )
            .cast(pl.Int32)
            .alias("zone_id")
        )

        return (
            zones.select(
                pl.col("zone_id").cast(pl.Int32),
                "shot_zone_basic",
                "shot_zone_area",
                "shot_zone_range",
            ).collect()  # ty: ignore[invalid-return-type]
        )
