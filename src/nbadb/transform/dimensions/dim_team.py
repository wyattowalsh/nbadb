from __future__ import annotations

from typing import TYPE_CHECKING, ClassVar

from nbadb.transform.base import BaseTransformer

if TYPE_CHECKING:
    import polars as pl


class DimTeamTransformer(BaseTransformer):
    output_table: ClassVar[str] = "dim_team"
    depends_on: ClassVar[list[str]] = ["stg_team_info"]

    def transform(self, staging: dict[str, pl.LazyFrame]) -> pl.DataFrame:
        ti = staging["stg_team_info"]
        return (
            ti.select(
                "team_id",
                "abbreviation",
                "full_name",
                "city",
                "state",
                "arena",
                "year_founded",
                "conference",
                "division",
            )
            .unique(subset=["team_id"], keep="last")
            .sort("team_id")
            .collect()  # ty: ignore[invalid-return-type]
        )
