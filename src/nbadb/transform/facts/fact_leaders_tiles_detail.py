from __future__ import annotations

from typing import Any, ClassVar

import polars as pl

from nbadb.transform.base import BaseTransformer
from nbadb.transform.facts._leaderboard_detail import (
    SingleMetricDetailSpec,
    consolidate_single_metric_family,
)

_LEADERS_TILES_SPECS: tuple[SingleMetricDetailSpec, ...] = (
    SingleMetricDetailSpec(
        "stg_leaders_tiles_alltime_high",
        metric_column="pts",
        variant="all_time_high",
    ),
    SingleMetricDetailSpec(
        "stg_leaders_tiles_last_season",
        metric_column="pts",
        variant="last_season_high",
    ),
    SingleMetricDetailSpec(
        "stg_leaders_tiles_main",
        metric_column="pts",
        variant="main",
    ),
    SingleMetricDetailSpec(
        "stg_leaders_tiles_low_season",
        metric_column="pts",
        variant="low_season_high",
    ),
)

_OUTPUT_SCHEMA: dict[str, Any] = {
    "tile_variant": pl.Utf8,
    "rank": pl.Int64,
    "team_id": pl.Int64,
    "team_abbreviation": pl.Utf8,
    "team_name": pl.Utf8,
    "season_year": pl.Utf8,
    "season_type": pl.Utf8,
    "pts": pl.Float64,
}


class FactLeadersTilesDetailTransformer(BaseTransformer):
    output_table: ClassVar[str] = "fact_leaders_tiles_detail"
    depends_on: ClassVar[list[str]] = [
        "stg_leaders_tiles_alltime_high",
        "stg_leaders_tiles_last_season",
        "stg_leaders_tiles_main",
        "stg_leaders_tiles_low_season",
    ]

    def transform(self, staging: dict[str, pl.LazyFrame]) -> pl.DataFrame:
        return consolidate_single_metric_family(
            staging,
            specs=_LEADERS_TILES_SPECS,
            variant_column="tile_variant",
            output_schema=_OUTPUT_SCHEMA,
            passthrough_columns=(
                "rank",
                "team_id",
                "team_abbreviation",
                "team_name",
                "season_year",
                "season_type",
            ),
            value_column="pts",
            sort_columns=("season_type", "tile_variant", "season_year", "rank", "team_id"),
        )
