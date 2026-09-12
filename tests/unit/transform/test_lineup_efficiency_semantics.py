"""Metric-local authority and structural semantics for lineup efficiency."""

from __future__ import annotations

import itertools
from typing import Any

import duckdb
import polars as pl
import pytest
from pandera.errors import SchemaError

from nbadb.schemas.star.agg_schemas import AggLineupEfficiencySchema
from nbadb.schemas.star.fact_lineup_stats import FactLineupStatsSchema
from nbadb.transform.derived.agg_lineup_efficiency import (
    AggLineupEfficiencyTransformer,
)
from nbadb.transform.facts.fact_lineup_stats import FactLineupStatsTransformer

_LINEUP_SCHEMA = {
    "group_set": pl.String,
    "group_id": pl.String,
    "group_name": pl.String,
    "team_id": pl.Int64,
    "gp": pl.Int64,
    "w": pl.Int64,
    "l": pl.Int64,
    "w_pct": pl.Float64,
    "min": pl.Float64,
    "fgm": pl.Int64,
    "fga": pl.Int64,
    "fg_pct": pl.Float64,
    "fg3m": pl.Int64,
    "fg3a": pl.Int64,
    "fg3_pct": pl.Float64,
    "ftm": pl.Int64,
    "fta": pl.Int64,
    "ft_pct": pl.Float64,
    "oreb": pl.Int64,
    "dreb": pl.Int64,
    "reb": pl.Int64,
    "ast": pl.Int64,
    "tov": pl.Int64,
    "stl": pl.Int64,
    "blk": pl.Int64,
    "blka": pl.Int64,
    "pf": pl.Int64,
    "pfd": pl.Int64,
    "pts": pl.Int64,
    "plus_minus": pl.Float64,
    "season_year": pl.String,
    "season_type": pl.String,
}

_DEFAULT_LINEUP: dict[str, Any] = {
    "group_set": "Lineups",
    "group_id": "1-2-3-4-5",
    "group_name": "Player 1 - Player 2 - Player 3 - Player 4 - Player 5",
    "team_id": 1610612738,
    "gp": 34,
    "w": 22,
    "l": 12,
    "w_pct": 0.99,
    "min": 315.4,
    "fgm": 128,
    "fga": 250,
    "fg_pct": 0.99,
    "fg3m": 51,
    "fg3a": 130,
    "fg3_pct": 0.99,
    "ftm": 44,
    "fta": 56,
    "ft_pct": 0.99,
    "oreb": 31,
    "dreb": 92,
    "reb": 123,
    "ast": 78,
    "tov": 29,
    "stl": 18,
    "blk": 11,
    "blka": 9,
    "pf": 52,
    "pfd": 47,
    "pts": 351,
    "plus_minus": 42.0,
    "season_year": "2024-25",
    "season_type": "Regular Season",
}

_FACT_SCHEMA = {
    "group_id": pl.String,
    "team_id": pl.Int64,
    "season_year": pl.String,
    "season_type": pl.String,
    "lineup_source": pl.String,
    "lineup_source_count": pl.Int64,
    "lineup_source_coverage": pl.String,
    "gp": pl.Int64,
    "w": pl.Int64,
    "l": pl.Int64,
    "min": pl.Float64,
    "fgm": pl.Int64,
    "fga": pl.Int64,
    "fg3m": pl.Int64,
    "fg3a": pl.Int64,
    "ftm": pl.Int64,
    "fta": pl.Int64,
    "oreb": pl.Int64,
    "dreb": pl.Int64,
    "reb": pl.Int64,
    "ast": pl.Int64,
    "tov": pl.Int64,
    "stl": pl.Int64,
    "blk": pl.Int64,
    "blka": pl.Int64,
    "pf": pl.Int64,
    "pfd": pl.Int64,
    "pts": pl.Int64,
    "plus_minus": pl.Float64,
    # Deliberately unconsumed fields prove projection precedes DISTINCT.
    "group_name": pl.String,
    "net_rating": pl.Float64,
    "provider_extra": pl.String,
}

_DEFAULT_FACT: dict[str, Any] = {
    "group_id": "1-2-3-4-5",
    "team_id": 1610612738,
    "season_year": "2024-25",
    "season_type": "Regular Season",
    "lineup_source": "league",
    "lineup_source_count": 1,
    "lineup_source_coverage": "league",
    "gp": 34,
    "w": 22,
    "l": 12,
    "min": 315.4,
    "fgm": 128,
    "fga": 250,
    "fg3m": 51,
    "fg3a": 130,
    "ftm": 44,
    "fta": 56,
    "oreb": 31,
    "dreb": 92,
    "reb": 123,
    "ast": 78,
    "tov": 29,
    "stl": 18,
    "blk": 11,
    "blka": 9,
    "pf": 52,
    "pfd": 47,
    "pts": 351,
    "plus_minus": 42.0,
    "group_name": "unconsumed-name",
    "net_rating": None,
    "provider_extra": "unconsumed-extra",
}

_CONSUMED_NONKEY_FIELDS = (
    "lineup_source",
    "lineup_source_count",
    "lineup_source_coverage",
    "gp",
    "w",
    "l",
    "min",
    "fgm",
    "fga",
    "fg3m",
    "fg3a",
    "ftm",
    "fta",
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
)

_COVERAGE_METRIC_PAIRS = (
    ("gp_covered_observations", "total_gp"),
    ("minutes_covered_observations", "total_min"),
    ("estimated_possessions_covered_observations", "estimated_possessions"),
    ("win_pct_covered_observations", "win_pct"),
    ("fg_pct_covered_observations", "fg_pct"),
    ("fg3_pct_covered_observations", "fg3_pct"),
    ("ft_pct_covered_observations", "ft_pct"),
    ("efg_pct_covered_observations", "efg_pct"),
    ("ts_pct_covered_observations", "ts_pct"),
    ("fg3a_per_fga_covered_observations", "fg3a_per_fga"),
    ("fta_per_fga_covered_observations", "fta_per_fga"),
    ("ast_tov_ratio_covered_observations", "ast_tov_ratio"),
    ("pts_per48_covered_observations", "pts_per48"),
    ("reb_per48_covered_observations", "reb_per48"),
    ("ast_per48_covered_observations", "ast_per48"),
    ("tov_per48_covered_observations", "tov_per48"),
    ("stl_per48_covered_observations", "stl_per48"),
    ("blk_per48_covered_observations", "blk_per48"),
    ("plus_minus_per48_covered_observations", "plus_minus_per48"),
    ("estimated_off_rating_covered_observations", "estimated_off_rating"),
    ("estimated_def_rating_covered_observations", "estimated_def_rating"),
    ("estimated_net_rating_covered_observations", "estimated_net_rating"),
)

_EXPECTED_COLUMNS = (
    "group_id",
    "team_id",
    "season_year",
    "season_type",
    "lineup_source",
    "lineup_source_count",
    "lineup_source_coverage",
    "canonical_observation_count",
    *(coverage for coverage, _metric in _COVERAGE_METRIC_PAIRS),
    "total_gp",
    "total_w",
    "total_l",
    "total_min",
    "total_fgm",
    "total_fga",
    "total_fg3m",
    "total_fg3a",
    "total_ftm",
    "total_fta",
    "total_oreb",
    "total_dreb",
    "total_reb",
    "total_ast",
    "total_tov",
    "total_stl",
    "total_blk",
    "total_blka",
    "total_pf",
    "total_pfd",
    "total_pts",
    "total_plus_minus",
    "win_pct",
    "fg_pct",
    "fg3_pct",
    "ft_pct",
    "efg_pct",
    "ts_pct",
    "fg3a_per_fga",
    "fta_per_fga",
    "ast_tov_ratio",
    "estimated_possessions",
    "pts_per48",
    "reb_per48",
    "ast_per48",
    "tov_per48",
    "stl_per48",
    "blk_per48",
    "plus_minus_per48",
    "estimated_off_rating",
    "estimated_def_rating",
    "estimated_net_rating",
)

_ALLOWED_SOURCE_TUPLES = (
    ("league", 1, "league"),
    ("team", 1, "team"),
    ("league", 2, "league+team"),
)
_INVALID_SOURCE_TUPLES = tuple(
    item
    for item in itertools.product(
        ("league", "team"),
        (1, 2),
        ("league", "team", "league+team"),
    )
    if item not in _ALLOWED_SOURCE_TUPLES
) + (("foreign", 1, "league"),)


def _lineups(rows: list[dict[str, Any]]) -> pl.DataFrame:
    return pl.DataFrame(
        [{**_DEFAULT_LINEUP, **row} for row in rows],
        schema=_LINEUP_SCHEMA,
    )


def _empty_lineups() -> pl.DataFrame:
    return pl.DataFrame(schema=_LINEUP_SCHEMA)


def _facts(rows: list[dict[str, Any]]) -> pl.DataFrame:
    return pl.DataFrame(
        [{**_DEFAULT_FACT, **row} for row in rows],
        schema=_FACT_SCHEMA,
    )


def _run_fact(league: pl.DataFrame, team: pl.DataFrame) -> pl.DataFrame:
    conn = duckdb.connect()
    try:
        conn.register("stg_lineup", league)
        conn.register("stg_team_lineups", team)
        transformer = FactLineupStatsTransformer()
        transformer._conn = conn
        return transformer.transform({})
    finally:
        conn.close()


def _run_agg(facts: pl.DataFrame) -> pl.DataFrame:
    conn = duckdb.connect()
    try:
        conn.register("fact_lineup_stats", facts)
        transformer = AggLineupEfficiencyTransformer()
        transformer._conn = conn
        return transformer.transform({})
    finally:
        conn.close()


def _validated_output(row: dict[str, Any]) -> pl.DataFrame:
    return AggLineupEfficiencySchema.validate(pl.DataFrame([row]))


def test_fact_prefers_league_copy_and_records_agreeing_source_coverage() -> None:
    result = _run_fact(_lineups([{}, {}]), _lineups([{}]))
    row = result.row(0, named=True)

    assert result.height == 1
    assert row["lineup_source"] == "league"
    assert row["lineup_source_count"] == 2
    assert row["lineup_source_coverage"] == "league+team"
    assert row["net_rating"] is None
    assert set(result.columns) == set(FactLineupStatsSchema.to_schema().columns)
    assert isinstance(FactLineupStatsSchema.validate(result), pl.DataFrame)


def test_fact_uses_team_copy_when_league_copy_is_absent() -> None:
    row = _run_fact(_empty_lineups(), _lineups([{}])).row(0, named=True)

    assert (row["lineup_source"], row["lineup_source_count"], row["lineup_source_coverage"]) == (
        "team",
        1,
        "team",
    )


def test_fact_preserves_provider_group_id_and_season_type_partitions() -> None:
    result = _run_fact(
        _lineups(
            [
                {"group_id": "5-1-4-2-3"},
                {"group_id": "5-1-4-2-3", "season_type": "Playoffs"},
            ]
        ),
        _empty_lineups(),
    )

    assert result.height == 2
    assert set(result["group_id"]) == {"5-1-4-2-3"}
    assert set(result["season_type"]) == {"Regular Season", "Playoffs"}


def test_fact_conflicting_source_copies_fail_closed() -> None:
    with pytest.raises(duckdb.InvalidInputException, match="conflicting lineup rows"):
        _run_fact(_lineups([{}]), _lineups([{"pts": 352}]))


@pytest.mark.parametrize(
    ("lineup_source", "lineup_source_count", "lineup_source_coverage"),
    _ALLOWED_SOURCE_TUPLES,
)
def test_aggregate_admits_each_exact_source_tuple(
    lineup_source: str,
    lineup_source_count: int,
    lineup_source_coverage: str,
) -> None:
    result = _run_agg(
        _facts(
            [
                {
                    "lineup_source": lineup_source,
                    "lineup_source_count": lineup_source_count,
                    "lineup_source_coverage": lineup_source_coverage,
                }
            ]
        )
    )

    assert result.select("lineup_source", "lineup_source_count", "lineup_source_coverage").row(
        0
    ) == (lineup_source, lineup_source_count, lineup_source_coverage)


@pytest.mark.parametrize(
    ("lineup_source", "lineup_source_count", "lineup_source_coverage"),
    _INVALID_SOURCE_TUPLES,
)
def test_aggregate_rejects_every_other_bounded_source_tuple(
    lineup_source: str,
    lineup_source_count: int,
    lineup_source_coverage: str,
) -> None:
    with pytest.raises(duckdb.InvalidInputException, match="invalid canonical source tuple"):
        _run_agg(
            _facts(
                [
                    {
                        "lineup_source": lineup_source,
                        "lineup_source_count": lineup_source_count,
                        "lineup_source_coverage": lineup_source_coverage,
                    }
                ]
            )
        )


def test_aggregate_exact_duplicates_collapse_before_direct_projection() -> None:
    result = _run_agg(_facts([{}, {}, {}]))

    assert result.height == 1
    assert result["canonical_observation_count"].item() == 1
    assert result["total_pts"].item() == 351


@pytest.mark.parametrize("field", _CONSUMED_NONKEY_FIELDS)
def test_every_consumed_field_null_vs_value_conflict_fails_closed(field: str) -> None:
    conflict = {field: None}

    with pytest.raises(duckdb.InvalidInputException, match="conflicting consumed fields"):
        _run_agg(_facts([{}, conflict]))


def test_unconsumed_provider_extras_do_not_create_false_conflicts() -> None:
    result = _run_agg(
        _facts(
            [
                {},
                {
                    "group_name": "different-but-unconsumed",
                    "net_rating": 99.0,
                    "provider_extra": "different-extra",
                },
            ]
        )
    )

    assert result.height == 1
    assert result["canonical_observation_count"].item() == 1


@pytest.mark.parametrize(
    "updates",
    [
        {"group_id": None},
        {"group_id": "   "},
        {"team_id": None},
        {"team_id": 0},
        {"team_id": -1},
        {"season_year": None},
        {"season_year": " "},
        {"season_type": None},
        {"season_type": "\t"},
    ],
)
def test_aggregate_rejects_null_blank_or_nonpositive_keys(updates: dict[str, Any]) -> None:
    with pytest.raises(duckdb.InvalidInputException, match="null, blank, or nonpositive key"):
        _run_agg(_facts([updates]))


def test_aggregate_keeps_four_key_partitions_and_exact_deterministic_order() -> None:
    rows = [
        {"group_id": "b", "team_id": 2, "season_year": "2024-25", "season_type": "B"},
        {"group_id": "a", "team_id": 2, "season_year": "2024-25", "season_type": "A"},
        {"group_id": "a", "team_id": 1, "season_year": "2025-26", "season_type": "A"},
        {"group_id": "a", "team_id": 1, "season_year": "2024-25", "season_type": "B"},
        {"group_id": "a", "team_id": 1, "season_year": "2024-25", "season_type": "A"},
    ]

    result = _run_agg(_facts(rows))

    assert result.select("group_id", "team_id", "season_year", "season_type").rows() == [
        ("a", 1, "2024-25", "A"),
        ("a", 1, "2024-25", "B"),
        ("a", 1, "2025-26", "A"),
        ("a", 2, "2024-25", "A"),
        ("b", 2, "2024-25", "B"),
    ]


def test_formula_goldens_are_metric_local_and_use_explicit_floating_division() -> None:
    row = _run_agg(_facts([{}])).row(0, named=True)
    possessions = 250 + 0.44 * 56 - 31 + 29

    assert row["canonical_observation_count"] == 1
    assert row["win_pct"] == pytest.approx(22 / 34)
    assert row["fg_pct"] == pytest.approx(128 / 250)
    assert row["fg3_pct"] == pytest.approx(51 / 130)
    assert row["ft_pct"] == pytest.approx(44 / 56)
    assert row["efg_pct"] == pytest.approx((128 + 0.5 * 51) / 250)
    assert row["ts_pct"] == pytest.approx(351 / (2 * (250 + 0.44 * 56)))
    assert row["fg3a_per_fga"] == pytest.approx(130 / 250)
    assert row["fta_per_fga"] == pytest.approx(56 / 250)
    assert row["ast_tov_ratio"] == pytest.approx(78 / 29)
    assert row["estimated_possessions"] == pytest.approx(possessions)
    assert row["pts_per48"] == pytest.approx(48 * 351 / 315.4)
    assert row["reb_per48"] == pytest.approx(48 * 123 / 315.4)
    assert row["ast_per48"] == pytest.approx(48 * 78 / 315.4)
    assert row["tov_per48"] == pytest.approx(48 * 29 / 315.4)
    assert row["stl_per48"] == pytest.approx(48 * 18 / 315.4)
    assert row["blk_per48"] == pytest.approx(48 * 11 / 315.4)
    assert row["plus_minus_per48"] == pytest.approx(48 * 42 / 315.4)
    assert row["estimated_off_rating"] == pytest.approx(100 * 351 / possessions)
    assert row["estimated_def_rating"] == pytest.approx(100 * (351 - 42) / possessions)
    assert row["estimated_net_rating"] == pytest.approx(100 * 42 / possessions)


@pytest.mark.parametrize(
    ("missing_input", "retained_metrics", "nulled_metrics"),
    [
        ("ftm", ("efg_pct", "ts_pct"), ("ft_pct",)),
        ("plus_minus", ("estimated_off_rating",), ("estimated_def_rating", "estimated_net_rating")),
        ("blk", ("pts_per48", "reb_per48"), ("blk_per48",)),
        ("fg3a", ("efg_pct",), ("fg3_pct", "fg3a_per_fga")),
        ("fgm", ("ts_pct",), ("fg_pct", "efg_pct")),
        (
            "pts",
            ("estimated_net_rating",),
            ("ts_pct", "pts_per48", "estimated_off_rating", "estimated_def_rating"),
        ),
    ],
)
def test_missing_input_dependency_isolation(
    missing_input: str,
    retained_metrics: tuple[str, ...],
    nulled_metrics: tuple[str, ...],
) -> None:
    baseline = _run_agg(_facts([{}])).row(0, named=True)
    row = _run_agg(_facts([{missing_input: None}])).row(0, named=True)

    for metric in retained_metrics:
        assert row[metric] == pytest.approx(baseline[metric])
        assert row[f"{metric}_covered_observations"] == 1
    for metric in nulled_metrics:
        assert row[metric] is None
        assert row[f"{metric}_covered_observations"] == 0


@pytest.mark.parametrize(
    ("updates", "metrics"),
    [
        ({"gp": 0}, ("win_pct",)),
        ({"fga": 0}, ("fg_pct", "efg_pct", "fg3a_per_fga", "fta_per_fga")),
        ({"fg3a": 0}, ("fg3_pct",)),
        ({"fta": 0}, ("ft_pct",)),
        ({"fga": 0, "fta": 0, "oreb": 0, "tov": 0}, ("ts_pct",)),
        ({"tov": 0}, ("ast_tov_ratio",)),
        (
            {"min": 0.0},
            (
                "pts_per48",
                "reb_per48",
                "ast_per48",
                "tov_per48",
                "stl_per48",
                "blk_per48",
                "plus_minus_per48",
            ),
        ),
        (
            {"fga": 0, "fta": 0, "oreb": 0, "tov": 0},
            ("estimated_off_rating", "estimated_def_rating", "estimated_net_rating"),
        ),
    ],
)
def test_zero_or_nonpositive_denominator_yields_null_and_zero_local_coverage(
    updates: dict[str, Any],
    metrics: tuple[str, ...],
) -> None:
    row = _run_agg(_facts([updates])).row(0, named=True)

    for metric in metrics:
        assert row[metric] is None
        assert row[f"{metric}_covered_observations"] == 0


@pytest.mark.parametrize(
    ("updates", "metric"),
    [
        ({"w": 0}, "win_pct"),
        ({"fgm": 0}, "fg_pct"),
        ({"fg3m": 0}, "fg3_pct"),
        ({"ftm": 0}, "ft_pct"),
        ({"fgm": 0, "fg3m": 0}, "efg_pct"),
        ({"pts": 0}, "ts_pct"),
        ({"fg3a": 0}, "fg3a_per_fga"),
        ({"fta": 0}, "fta_per_fga"),
        ({"ast": 0}, "ast_tov_ratio"),
        ({"pts": 0}, "pts_per48"),
        ({"reb": 0}, "reb_per48"),
        ({"ast": 0}, "ast_per48"),
        ({"tov": 0}, "tov_per48"),
        ({"stl": 0}, "stl_per48"),
        ({"blk": 0}, "blk_per48"),
        ({"plus_minus": 0.0}, "plus_minus_per48"),
        ({"pts": 0}, "estimated_off_rating"),
        ({"pts": 42, "plus_minus": 42.0}, "estimated_def_rating"),
        ({"plus_minus": 0.0}, "estimated_net_rating"),
    ],
)
def test_zero_numerator_with_positive_denominator_is_covered_zero(
    updates: dict[str, Any],
    metric: str,
) -> None:
    row = _run_agg(_facts([updates])).row(0, named=True)

    assert row[metric] == pytest.approx(0.0)
    assert row[f"{metric}_covered_observations"] == 1


def test_zero_estimated_possessions_is_valid_but_cannot_cover_ratings() -> None:
    row = _run_agg(_facts([{"fga": 0, "fta": 0, "oreb": 0, "tov": 0}])).row(0, named=True)

    assert row["estimated_possessions"] == 0.0
    assert row["estimated_possessions_covered_observations"] == 1
    for metric in ("estimated_off_rating", "estimated_def_rating", "estimated_net_rating"):
        assert row[metric] is None
        assert row[f"{metric}_covered_observations"] == 0


def test_negative_estimated_possessions_forces_a_deterministic_error() -> None:
    with pytest.raises(duckdb.InvalidInputException, match="negative estimated possessions"):
        _run_agg(_facts([{"fga": 1, "fta": 0, "oreb": 100, "tov": 0}]))


def test_null_inputs_preserve_totals_and_every_local_metric_unknown() -> None:
    nulls = {
        field: None
        for field in _CONSUMED_NONKEY_FIELDS
        if field
        not in {
            "lineup_source",
            "lineup_source_count",
            "lineup_source_coverage",
        }
    }
    row = _run_agg(_facts([nulls])).row(0, named=True)

    assert row["canonical_observation_count"] == 1
    for coverage, metric in _COVERAGE_METRIC_PAIRS:
        assert row[coverage] == 0
        assert row[metric] is None
    assert row["total_w"] is None
    assert row["total_l"] is None
    assert row["total_plus_minus"] is None


@pytest.fixture
def valid_output_row() -> dict[str, Any]:
    return _run_agg(_facts([{}])).row(0, named=True)


@pytest.mark.parametrize(("coverage", "metric"), _COVERAGE_METRIC_PAIRS)
def test_schema_rejects_zero_coverage_with_nonnull_metric(
    valid_output_row: dict[str, Any],
    coverage: str,
    metric: str,
) -> None:
    row = {**valid_output_row, coverage: 0}

    with pytest.raises(SchemaError, match="metric_nullability_matches_local_coverage"):
        _validated_output(row)


@pytest.mark.parametrize(("coverage", "metric"), _COVERAGE_METRIC_PAIRS)
def test_schema_rejects_positive_coverage_with_null_metric(
    valid_output_row: dict[str, Any],
    coverage: str,
    metric: str,
) -> None:
    row = {**valid_output_row, metric: None}

    with pytest.raises(SchemaError, match="metric_nullability_matches_local_coverage"):
        _validated_output(row)


@pytest.mark.parametrize(
    ("source", "count", "coverage"),
    _INVALID_SOURCE_TUPLES,
)
def test_schema_rejects_noncanonical_source_tuple(
    valid_output_row: dict[str, Any],
    source: str,
    count: int,
    coverage: str,
) -> None:
    row = {
        **valid_output_row,
        "lineup_source": source,
        "lineup_source_count": count,
        "lineup_source_coverage": coverage,
    }

    with pytest.raises(SchemaError):
        _validated_output(row)


@pytest.mark.parametrize("canonical_count", [0, 2])
def test_schema_rejects_noncanonical_observation_count(
    valid_output_row: dict[str, Any], canonical_count: int
) -> None:
    with pytest.raises(SchemaError):
        _validated_output({**valid_output_row, "canonical_observation_count": canonical_count})


def test_schema_rejects_duplicate_composite_output_key(
    valid_output_row: dict[str, Any],
) -> None:
    with pytest.raises(SchemaError, match="structural_keys_are_nonblank_and_unique"):
        AggLineupEfficiencySchema.validate(pl.DataFrame([valid_output_row, valid_output_row]))


@pytest.mark.parametrize("value", [float("inf"), float("-inf"), float("nan")])
def test_schema_rejects_nonfinite_nullable_numeric_output(
    valid_output_row: dict[str, Any], value: float
) -> None:
    with pytest.raises(SchemaError, match="nullable_float_outputs_are_finite"):
        _validated_output({**valid_output_row, "estimated_net_rating": value})


def test_schema_does_not_claim_arithmetic_equality(
    valid_output_row: dict[str, Any],
) -> None:
    result = _validated_output(
        {
            **valid_output_row,
            "win_pct": 0.123456,
            "estimated_net_rating": -999.0,
        }
    )

    assert isinstance(result, pl.DataFrame)


def test_transform_and_schema_freeze_the_same_exact_ordered_projection() -> None:
    result = _run_agg(_facts([{}]))
    schema_columns = tuple(AggLineupEfficiencySchema.to_schema().columns)

    assert tuple(result.columns) == _EXPECTED_COLUMNS
    assert schema_columns == _EXPECTED_COLUMNS
    assert isinstance(AggLineupEfficiencySchema.validate(result), pl.DataFrame)


def test_old_shared_coverage_attempt_and_provider_fields_are_absent() -> None:
    result_columns = set(_run_agg(_facts([{}])).columns)
    schema_columns = set(AggLineupEfficiencySchema.to_schema().columns)
    forbidden = {
        "shooting_covered_observations",
        "rating_covered_observations",
        "per48_covered_observations",
        "provider_net_rating_covered_observations",
        "avg_net_rating",
        "three_point_attempt_rate",
        "free_throw_attempt_rate",
    }

    assert forbidden.isdisjoint(result_columns)
    assert forbidden.isdisjoint(schema_columns)
    assert "SUM(" not in AggLineupEfficiencyTransformer._SQL.upper()
    assert "ANY_VALUE(" not in AggLineupEfficiencyTransformer._SQL.upper()
    assert "MIN(" not in AggLineupEfficiencyTransformer._SQL.upper()
    assert "MAX(" not in AggLineupEfficiencyTransformer._SQL.upper()
