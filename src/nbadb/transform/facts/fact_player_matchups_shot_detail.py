from __future__ import annotations

from typing import Any, ClassVar

import polars as pl

from nbadb.transform.base import BaseTransformer
from nbadb.transform.facts._comparison_detail import (
    ComparisonDetailSpec,
    consolidate_detail_family,
)

_PLAYER_MATCHUP_SHOT_DETAIL_SPECS: tuple[ComparisonDetailSpec, ...] = (
    ComparisonDetailSpec(
        "stg_pvp_shot_area_off",
        labels={"split_family": "shot_area", "split_scope": "off_court"},
    ),
    ComparisonDetailSpec(
        "stg_pvp_shot_area_on",
        labels={"split_family": "shot_area", "split_scope": "on_court"},
    ),
    ComparisonDetailSpec(
        "stg_pvp_shot_area_overall",
        labels={"split_family": "shot_area", "split_scope": "overall"},
    ),
    ComparisonDetailSpec(
        "stg_pvp_shot_dist_off",
        labels={"split_family": "shot_distance", "split_scope": "off_court"},
    ),
    ComparisonDetailSpec(
        "stg_pvp_shot_dist_on",
        labels={"split_family": "shot_distance", "split_scope": "on_court"},
    ),
    ComparisonDetailSpec(
        "stg_pvp_shot_dist_overall",
        labels={"split_family": "shot_distance", "split_scope": "overall"},
    ),
)

_OUTPUT_SCHEMA: dict[str, Any] = {
    "split_family": pl.Utf8,
    "split_scope": pl.Utf8,
    "group_set": pl.Utf8,
    "group_value": pl.Utf8,
    "player_id": pl.Int64,
    "player_name": pl.Utf8,
    "vs_player_id": pl.Int64,
    "vs_player_name": pl.Utf8,
    "court_status": pl.Utf8,
    "fgm": pl.Float64,
    "fga": pl.Float64,
    "fg_pct": pl.Float64,
    "cfid": pl.Utf8,
    "cfparams": pl.Utf8,
}


class FactPlayerMatchupsShotDetailTransformer(BaseTransformer):
    output_table: ClassVar[str] = "fact_player_matchups_shot_detail"
    depends_on: ClassVar[list[str]] = [
        spec.staging_key for spec in _PLAYER_MATCHUP_SHOT_DETAIL_SPECS
    ]

    def transform(self, staging: dict[str, pl.LazyFrame]) -> pl.DataFrame:
        return consolidate_detail_family(
            staging,
            specs=_PLAYER_MATCHUP_SHOT_DETAIL_SPECS,
            output_schema=_OUTPUT_SCHEMA,
            passthrough_columns=(
                "group_set",
                "group_value",
                "player_id",
                "player_name",
                "vs_player_id",
                "vs_player_name",
                "court_status",
                "fgm",
                "fga",
                "fg_pct",
                "cfid",
                "cfparams",
            ),
            sort_columns=(
                "split_family",
                "split_scope",
                "player_id",
                "vs_player_id",
                "group_value",
            ),
        )
