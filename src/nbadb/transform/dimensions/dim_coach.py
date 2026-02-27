from __future__ import annotations

from typing import TYPE_CHECKING, ClassVar

from nbadb.transform.base import BaseTransformer

if TYPE_CHECKING:
    import polars as pl


class DimCoachTransformer(BaseTransformer):
    output_table: ClassVar[str] = "dim_coach"
    depends_on: ClassVar[list[str]] = ["stg_team_info"]

    def transform(self, staging: dict[str, pl.LazyFrame]) -> pl.DataFrame:
        ti = staging["stg_team_info"]
        return (
            ti.select(
                "coach_id",
                "coach_name",
                "team_id",
                "season_year",
                "coach_type",
            )
            .unique(subset=["coach_id", "team_id", "season_year"], keep="last")
            .sort("coach_id", "season_year")
            .collect()  # ty: ignore[invalid-return-type]
        )
