from __future__ import annotations

from typing import ClassVar

import polars as pl

from nbadb.transform.base import BaseTransformer


class DimTeamTransformer(BaseTransformer):
    output_table: ClassVar[str] = "dim_team"
    depends_on: ClassVar[list[str]] = [
        "stg_static_teams",
        "stg_team_details",
        "stg_team_info_common",
    ]

    def transform(self, staging: dict[str, pl.LazyFrame]) -> pl.DataFrame:
        teams = staging["stg_static_teams"].select(
            pl.col("id").alias("team_id"),
            "abbreviation",
            "full_name",
            "city",
            "state",
            "year_founded",
        )
        details = staging["stg_team_details"].select("team_id", "arena")
        info = staging["stg_team_info_common"].select(
            "team_id",
            pl.col("team_conference").alias("conference"),
            pl.col("team_division").alias("division"),
        )
        return (
            teams.join(
                details.unique(subset=["team_id"], keep="last"),
                on="team_id",
                how="left",
            )
            .join(
                info.unique(subset=["team_id"], keep="last"),
                on="team_id",
                how="left",
            )
            .select(
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
            .collect()
        )
