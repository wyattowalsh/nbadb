from __future__ import annotations

from typing import TYPE_CHECKING, ClassVar

from nbadb.transform.base import BaseTransformer

if TYPE_CHECKING:
    import polars as pl


class DimCollegeTransformer(BaseTransformer):
    output_table: ClassVar[str] = "dim_college"
    depends_on: ClassVar[list[str]] = ["stg_player_college"]

    def transform(self, staging: dict[str, pl.LazyFrame]) -> pl.DataFrame:
        import polars as pl

        pc = staging["stg_player_college"]
        colleges = pc.select("college_name").unique().drop_nulls().sort("college_name")
        return (
            colleges.with_row_index("college_id", offset=1)
            .select(
                pl.col("college_id").cast(pl.Int32),
                "college_name",
            )
            .collect()  # ty: ignore[invalid-return-type]
        )
