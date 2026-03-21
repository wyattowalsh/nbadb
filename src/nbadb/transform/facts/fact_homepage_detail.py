from __future__ import annotations

from typing import Any, ClassVar

import polars as pl

from nbadb.transform.base import BaseTransformer
from nbadb.transform.facts._leaderboard_detail import (
    SingleMetricDetailSpec,
    consolidate_single_metric_family,
)

_HOMEPAGE_DETAIL_SPECS: tuple[SingleMetricDetailSpec, ...] = (
    SingleMetricDetailSpec("stg_homepage_v2_stat1", metric_column="pts"),
    SingleMetricDetailSpec("stg_homepage_v2_stat2", metric_column="reb"),
    SingleMetricDetailSpec("stg_homepage_v2_stat3", metric_column="ast"),
    SingleMetricDetailSpec("stg_homepage_v2_stat4", metric_column="stl"),
    SingleMetricDetailSpec("stg_homepage_v2_stat5", metric_column="fg_pct"),
    SingleMetricDetailSpec("stg_homepage_v2_stat6", metric_column="ft_pct"),
    SingleMetricDetailSpec("stg_homepage_v2_stat7", metric_column="fg3_pct"),
    SingleMetricDetailSpec("stg_homepage_v2_stat8", metric_column="blk"),
)

_OUTPUT_SCHEMA: dict[str, Any] = {
    "homepage_metric": pl.Utf8,
    "rank": pl.Int64,
    "team_id": pl.Int64,
    "team_abbreviation": pl.Utf8,
    "team_name": pl.Utf8,
    "season_type": pl.Utf8,
    "stat_value": pl.Float64,
}


class FactHomepageDetailTransformer(BaseTransformer):
    output_table: ClassVar[str] = "fact_homepage_detail"
    depends_on: ClassVar[list[str]] = [
        "stg_homepage_v2_stat1",
        "stg_homepage_v2_stat2",
        "stg_homepage_v2_stat3",
        "stg_homepage_v2_stat4",
        "stg_homepage_v2_stat5",
        "stg_homepage_v2_stat6",
        "stg_homepage_v2_stat7",
        "stg_homepage_v2_stat8",
    ]

    def transform(self, staging: dict[str, pl.LazyFrame]) -> pl.DataFrame:
        return consolidate_single_metric_family(
            staging,
            specs=_HOMEPAGE_DETAIL_SPECS,
            variant_column="homepage_metric",
            output_schema=_OUTPUT_SCHEMA,
            passthrough_columns=(
                "rank",
                "team_id",
                "team_abbreviation",
                "team_name",
                "season_type",
            ),
            sort_columns=("season_type", "homepage_metric", "rank", "team_id"),
        )
