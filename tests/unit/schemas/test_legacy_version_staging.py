from __future__ import annotations

import polars as pl
import pytest
from nba_api.stats.endpoints import (
    BoxScoreAdvancedV2,
    BoxScoreFourFactorsV2,
    BoxScoreMiscV2,
    BoxScoreScoringV2,
    BoxScoreTraditionalV2,
    BoxScoreUsageV2,
    LeagueStandings,
    PlayByPlay,
)

from nbadb.extract.base import _canonicalize_endpoint_column_name, _to_snake_case
from nbadb.schemas.registry import get_input_schema

_CASES = (
    (
        "stg_box_score_traditional_v2_player",
        BoxScoreTraditionalV2,
        "PlayerStats",
    ),
    (
        "stg_box_score_traditional_v2_starter_bench",
        BoxScoreTraditionalV2,
        "TeamStarterBenchStats",
    ),
    ("stg_box_score_traditional_v2_team", BoxScoreTraditionalV2, "TeamStats"),
    ("stg_box_score_advanced_v2_player", BoxScoreAdvancedV2, "PlayerStats"),
    ("stg_box_score_advanced_v2_team", BoxScoreAdvancedV2, "TeamStats"),
    ("stg_box_score_misc_v2_player", BoxScoreMiscV2, "sqlPlayersMisc"),
    ("stg_box_score_misc_v2_team", BoxScoreMiscV2, "sqlTeamsMisc"),
    ("stg_box_score_scoring_v2_player", BoxScoreScoringV2, "sqlPlayersScoring"),
    ("stg_box_score_scoring_v2_team", BoxScoreScoringV2, "sqlTeamsScoring"),
    ("stg_box_score_usage_v2_player", BoxScoreUsageV2, "sqlPlayersUsage"),
    ("stg_box_score_usage_v2_team", BoxScoreUsageV2, "sqlTeamsUsage"),
    (
        "stg_box_score_four_factors_v2_player",
        BoxScoreFourFactorsV2,
        "sqlPlayersFourFactors",
    ),
    (
        "stg_box_score_four_factors_v2_team",
        BoxScoreFourFactorsV2,
        "sqlTeamsFourFactors",
    ),
    ("stg_play_by_play_legacy_video_available", PlayByPlay, "AvailableVideo"),
    ("stg_play_by_play_legacy", PlayByPlay, "PlayByPlay"),
    ("stg_league_standings_legacy", LeagueStandings, "Standings"),
)


@pytest.mark.parametrize("staging_key, endpoint_cls, result_set_name", _CASES)
def test_legacy_schema_matches_exact_pinned_provider_headers_without_coercion(
    staging_key: str,
    endpoint_cls: type,
    result_set_name: str,
) -> None:
    schema_cls = get_input_schema(staging_key)
    assert schema_cls is not None
    result_set_index = tuple(endpoint_cls.expected_data).index(result_set_name)
    provider_columns = [
        _canonicalize_endpoint_column_name(endpoint_cls.__name__, result_set_index, column)
        for column in endpoint_cls.expected_data[result_set_name]
    ]
    schema = schema_cls.to_schema()

    assert list(schema.columns) == provider_columns
    assert schema.coerce is False
    assert schema.strict is False
    assert schema.ordered is True

    frame = pl.DataFrame(
        {column: pl.Series(column, [None], dtype=pl.Null) for column in provider_columns}
    ).with_columns(pl.lit("001").alias(provider_columns[0]))
    validated = schema_cls.validate(frame)

    assert validated.columns == provider_columns
    assert validated.schema == frame.schema


def test_legacy_schema_preserves_additive_provider_fields() -> None:
    schema_cls = get_input_schema("stg_play_by_play_legacy")
    assert schema_cls is not None
    provider_columns = [_to_snake_case(column) for column in PlayByPlay.expected_data["PlayByPlay"]]
    frame = pl.DataFrame(
        {column: pl.Series(column, [None], dtype=pl.Null) for column in provider_columns}
    ).with_columns(
        pl.lit("001").alias(provider_columns[0]),
        pl.lit({"nested": [1, 2]}).alias("future_provider_field"),
    )

    validated = schema_cls.validate(frame)

    assert validated.columns == [*provider_columns, "future_provider_field"]
    assert validated["future_provider_field"].to_list() == [{"nested": [1, 2]}]
