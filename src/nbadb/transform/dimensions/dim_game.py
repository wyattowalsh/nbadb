from __future__ import annotations

from typing import TYPE_CHECKING, ClassVar

from nbadb.transform.base import BaseTransformer

if TYPE_CHECKING:
    import polars as pl


class DimGameTransformer(BaseTransformer):
    output_table: ClassVar[str] = "dim_game"
    depends_on: ClassVar[list[str]] = ["stg_league_game_log", "stg_schedule"]

    def transform(self, staging: dict[str, pl.LazyFrame]) -> pl.DataFrame:
        gl = staging["stg_league_game_log"]
        sched = staging["stg_schedule"]
        games = gl.select(
            "game_id",
            "game_date",
            "season_year",
            "season_type",
            "home_team_id",
            "visitor_team_id",
            "matchup",
        )
        arenas = sched.select("game_id", "arena_name", "arena_city").unique(
            subset=["game_id"], keep="last"
        )
        return (
            games.join(arenas, on="game_id", how="left")
            .unique(subset=["game_id"], keep="last")
            .sort("game_date", "game_id")
            .collect()  # ty: ignore[invalid-return-type]
        )
