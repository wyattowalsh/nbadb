from __future__ import annotations

from typing import Any, ClassVar, cast

import polars as pl

from nbadb.transform.base import BaseTransformer
from nbadb.transform.facts._leaderboard_detail import empty_frame, typed_column

_HOMEPAGE_LEADER_VARIANTS: tuple[tuple[str, str], ...] = (
    ("stg_homepage_leaders_main", "main"),
    ("stg_homepage_leaders_league_avg", "league_avg"),
    ("stg_homepage_leaders_league_max", "league_max"),
)

_OUTPUT_SCHEMA: dict[str, Any] = {
    "leader_variant": pl.Utf8,
    "rank": pl.Int64,
    "team_id": pl.Int64,
    "team_abbreviation": pl.Utf8,
    "team_name": pl.Utf8,
    "season_type": pl.Utf8,
    "pts": pl.Float64,
    "fg_pct": pl.Float64,
    "fg3_pct": pl.Float64,
    "ft_pct": pl.Float64,
    "efg_pct": pl.Float64,
    "ts_pct": pl.Float64,
    "pts_per48": pl.Float64,
}


class FactHomepageLeadersDetailTransformer(BaseTransformer):
    output_table: ClassVar[str] = "fact_homepage_leaders_detail"
    depends_on: ClassVar[list[str]] = [
        "stg_homepage_leaders_main",
        "stg_homepage_leaders_league_avg",
        "stg_homepage_leaders_league_max",
    ]

    def transform(self, staging: dict[str, pl.LazyFrame]) -> pl.DataFrame:
        frames: list[pl.DataFrame] = []

        for staging_key, variant in _HOMEPAGE_LEADER_VARIANTS:
            frame = staging.get(staging_key)
            if frame is None:
                continue

            df = cast("pl.DataFrame", frame.collect())
            if df.is_empty():
                continue

            frames.append(
                df.select(
                    pl.lit(variant).cast(pl.Utf8).alias("leader_variant"),
                    typed_column(df, "rank", pl.Int64),
                    typed_column(df, "team_id", pl.Int64),
                    typed_column(df, "team_abbreviation", pl.Utf8),
                    typed_column(df, "team_name", pl.Utf8),
                    typed_column(df, "season_type", pl.Utf8),
                    typed_column(df, "pts", pl.Float64),
                    typed_column(df, "fg_pct", pl.Float64),
                    typed_column(df, "fg3_pct", pl.Float64),
                    typed_column(df, "ft_pct", pl.Float64),
                    typed_column(df, "efg_pct", pl.Float64),
                    typed_column(df, "ts_pct", pl.Float64),
                    typed_column(df, "pts_per48", pl.Float64),
                )
            )

        if not frames:
            return empty_frame(_OUTPUT_SCHEMA)

        return (
            pl.concat(frames, how="diagonal_relaxed")
            .select(list(_OUTPUT_SCHEMA))
            .sort(["leader_variant", "season_type", "rank", "team_id"])
        )
