from __future__ import annotations

from typing import TYPE_CHECKING, ClassVar

from nbadb.transform.base import BaseTransformer

if TYPE_CHECKING:
    import polars as pl


class DimOfficialTransformer(BaseTransformer):
    output_table: ClassVar[str] = "dim_official"
    depends_on: ClassVar[list[str]] = ["stg_officials"]

    def transform(self, staging: dict[str, pl.LazyFrame]) -> pl.DataFrame:
        off = staging["stg_officials"]
        return (
            off.select(
                "official_id",
                "first_name",
                "last_name",
                "jersey_number",
            )
            .unique(subset=["official_id"], keep="last")
            .sort("official_id")
            .collect()  # ty: ignore[invalid-return-type]
        )
