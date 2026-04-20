from __future__ import annotations

from typing import Any, ClassVar

import polars as pl

from nbadb.transform.base import BaseTransformer
from nbadb.transform.facts._leaderboard_detail import (
    SingleMetricDetailSpec,
    consolidate_single_metric_family,
)

_DEFENSE_HUB_SPECS: tuple[SingleMetricDetailSpec, ...] = (
    SingleMetricDetailSpec("stg_defense_hub_stat1", metric_column="dreb"),
    SingleMetricDetailSpec("stg_defense_hub_stat10"),
    SingleMetricDetailSpec("stg_defense_hub_stat2", metric_column="stl"),
    SingleMetricDetailSpec("stg_defense_hub_stat3", metric_column="blk"),
    SingleMetricDetailSpec("stg_defense_hub_stat4", metric_column="tm_def_rating"),
    SingleMetricDetailSpec("stg_defense_hub_stat5", metric_column="overall_pm"),
    SingleMetricDetailSpec("stg_defense_hub_stat6", metric_column="threep_dfgpct"),
    SingleMetricDetailSpec("stg_defense_hub_stat7", metric_column="twop_dfgpct"),
    SingleMetricDetailSpec("stg_defense_hub_stat8", metric_column="fifeteenf_dfgpct"),
    SingleMetricDetailSpec("stg_defense_hub_stat9", metric_column="def_rim_pct"),
)

_OUTPUT_SCHEMA: dict[str, Any] = {
    "defense_metric": pl.Utf8,
    "rank": pl.Int64,
    "team_id": pl.Int64,
    "team_abbreviation": pl.Utf8,
    "team_name": pl.Utf8,
    "season_type": pl.Utf8,
    "stat_value": pl.Float64,
}


class FactDefenseHubDetailTransformer(BaseTransformer):
    output_table: ClassVar[str] = "fact_defense_hub_detail"
    depends_on: ClassVar[list[str]] = [
        "stg_defense_hub_stat1",
        "stg_defense_hub_stat10",
        "stg_defense_hub_stat2",
        "stg_defense_hub_stat3",
        "stg_defense_hub_stat4",
        "stg_defense_hub_stat5",
        "stg_defense_hub_stat6",
        "stg_defense_hub_stat7",
        "stg_defense_hub_stat8",
        "stg_defense_hub_stat9",
    ]

    def transform(self, staging: dict[str, pl.LazyFrame]) -> pl.DataFrame:
        return consolidate_single_metric_family(
            staging,
            specs=_DEFENSE_HUB_SPECS,
            variant_column="defense_metric",
            output_schema=_OUTPUT_SCHEMA,
            passthrough_columns=(
                "rank",
                "team_id",
                "team_abbreviation",
                "team_name",
                "season_type",
            ),
            sort_columns=("season_type", "defense_metric", "rank", "team_id"),
        )
