from __future__ import annotations

from typing import Any, ClassVar

import polars as pl

from nbadb.transform.base import BaseTransformer
from nbadb.transform.facts._comparison_detail import (
    ComparisonDetailSpec,
    consolidate_detail_family,
)

_PLAYER_MATCHUP_DETAIL_SPECS: tuple[ComparisonDetailSpec, ...] = (
    ComparisonDetailSpec(
        "stg_player_compare_individual",
        labels={"detail_source": "player_compare", "detail_variant": "individual"},
    ),
    ComparisonDetailSpec(
        "stg_player_compare_overall",
        labels={"detail_source": "player_compare", "detail_variant": "overall_compare"},
    ),
    ComparisonDetailSpec(
        "stg_pvp_on_off_court",
        labels={"detail_source": "player_vs_player", "detail_variant": "on_off_court"},
    ),
    ComparisonDetailSpec(
        "stg_pvp_overall",
        labels={"detail_source": "player_vs_player", "detail_variant": "overall"},
    ),
)

_OUTPUT_SCHEMA: dict[str, Any] = {
    "detail_source": pl.Utf8,
    "detail_variant": pl.Utf8,
    "group_set": pl.Utf8,
    "group_value": pl.Utf8,
    "description": pl.Utf8,
    "player_id": pl.Int64,
    "player_name": pl.Utf8,
    "vs_player_id": pl.Int64,
    "vs_player_name": pl.Utf8,
    "court_status": pl.Utf8,
    "gp": pl.Int64,
    "w": pl.Int64,
    "l": pl.Int64,
    "w_pct": pl.Float64,
    "min": pl.Float64,
    "fgm": pl.Float64,
    "fga": pl.Float64,
    "fg_pct": pl.Float64,
    "fg3m": pl.Float64,
    "fg3a": pl.Float64,
    "fg3_pct": pl.Float64,
    "ftm": pl.Float64,
    "fta": pl.Float64,
    "ft_pct": pl.Float64,
    "oreb": pl.Float64,
    "dreb": pl.Float64,
    "reb": pl.Float64,
    "ast": pl.Float64,
    "tov": pl.Float64,
    "stl": pl.Float64,
    "blk": pl.Float64,
    "blka": pl.Float64,
    "pf": pl.Float64,
    "pfd": pl.Float64,
    "pts": pl.Float64,
    "plus_minus": pl.Float64,
    "nba_fantasy_pts": pl.Float64,
    "cfid": pl.Utf8,
    "cfparams": pl.Utf8,
}


class FactPlayerMatchupsDetailTransformer(BaseTransformer):
    output_table: ClassVar[str] = "fact_player_matchups_detail"
    depends_on: ClassVar[list[str]] = [spec.staging_key for spec in _PLAYER_MATCHUP_DETAIL_SPECS]

    def transform(self, staging: dict[str, pl.LazyFrame]) -> pl.DataFrame:
        return consolidate_detail_family(
            staging,
            specs=_PLAYER_MATCHUP_DETAIL_SPECS,
            output_schema=_OUTPUT_SCHEMA,
            passthrough_columns=(
                "group_set",
                "group_value",
                "description",
                "player_id",
                "player_name",
                "vs_player_id",
                "vs_player_name",
                "court_status",
                "gp",
                "w",
                "l",
                "w_pct",
                "min",
                "fgm",
                "fga",
                "fg_pct",
                "fg3m",
                "fg3a",
                "fg3_pct",
                "ftm",
                "fta",
                "ft_pct",
                "oreb",
                "dreb",
                "reb",
                "ast",
                "tov",
                "stl",
                "blk",
                "blka",
                "pf",
                "pfd",
                "pts",
                "plus_minus",
                "nba_fantasy_pts",
                "cfid",
                "cfparams",
            ),
            sort_columns=(
                "detail_source",
                "detail_variant",
                "player_id",
                "vs_player_id",
                "description",
                "group_value",
            ),
        )
