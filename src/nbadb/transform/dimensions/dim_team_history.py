from __future__ import annotations

from typing import TYPE_CHECKING, ClassVar

from nbadb.transform.base import BaseTransformer

if TYPE_CHECKING:
    import polars as pl


class DimTeamHistoryTransformer(BaseTransformer):
    output_table: ClassVar[str] = "dim_team_history"
    depends_on: ClassVar[list[str]] = ["stg_team_info", "stg_franchise"]

    def transform(self, staging: dict[str, pl.LazyFrame]) -> pl.DataFrame:
        ti = staging["stg_team_info"]
        fr = staging["stg_franchise"]
        return (
            ti.select("team_id", "full_name", "city", "season_year")
            .join(
                fr.select("team_id", "franchise_name"),
                on="team_id",
                how="left",
            )
            .unique(subset=["team_id", "season_year"], keep="last")
            .sort("team_id", "season_year")
            .collect()  # ty: ignore[invalid-return-type]
        )
