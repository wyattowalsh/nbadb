"""Adversarial structural semantics for the shot-zone aggregate."""

from __future__ import annotations

import ast
import inspect
from typing import Any

import duckdb
import polars as pl
import pytest
from pandera.errors import SchemaError

from nbadb.schemas.star.agg_schemas import AggShotZonesSchema
from nbadb.transform.derived.agg_shot_zones import AggShotZonesTransformer

_OUTPUT_COLUMNS = [
    "player_id",
    "season_year",
    "season_type",
    "shot_zone_basic",
    "shot_zone_area",
    "shot_zone_range",
    "shot_event_count",
    "outcome_observed_attempt_count",
    "made_shot_count_of_observed_outcomes",
    "fg_pct_of_observed_outcomes",
    "distance_observed_attempt_count",
    "mean_observed_shot_distance",
]

_FACT_DTYPES = {
    "game_id": pl.String,
    "game_event_id": pl.Int64,
    "player_id": pl.Int64,
    "season_year": pl.String,
    "season_type": pl.String,
    "shot_zone_basic": pl.String,
    "shot_zone_area": pl.String,
    "shot_zone_range": pl.String,
    "shot_made_flag": pl.Int64,
    "shot_distance": pl.Float64,
    "provider_extra": pl.String,
}
_DIM_DTYPES = {
    "game_id": pl.String,
    "season_year": pl.String,
    "season_type": pl.String,
    "provider_extra": pl.String,
}


def _frame(rows: list[dict[str, object]], dtypes: dict[str, Any]) -> pl.DataFrame:
    if not rows:
        return pl.DataFrame(schema=dtypes)
    return pl.DataFrame(rows, schema_overrides=dtypes)


def _event_row(
    *,
    game_id: str | None = "regular-game",
    game_event_id: int | None = 1,
    **updates: object,
) -> dict[str, object]:
    row: dict[str, object] = {
        "game_id": game_id,
        "game_event_id": game_event_id,
        "player_id": 2544,
        "season_year": "2024-25",
        "season_type": "Regular Season",
        "shot_zone_basic": "Mid-Range",
        "shot_zone_area": "Center(C)",
        "shot_zone_range": "16-24 ft.",
        "shot_made_flag": 1,
        "shot_distance": 18.0,
        "provider_extra": "ignored-fact",
    }
    row.update(updates)
    return row


def _game_row(
    *,
    game_id: str | None = "regular-game",
    **updates: object,
) -> dict[str, object]:
    row: dict[str, object] = {
        "game_id": game_id,
        "season_year": "2024-25",
        "season_type": "Regular Season",
        "provider_extra": "ignored-dim",
    }
    row.update(updates)
    return row


def _run(
    facts: list[dict[str, object]],
    games: list[dict[str, object]],
) -> pl.DataFrame:
    transformer = AggShotZonesTransformer()
    conn = duckdb.connect()
    try:
        conn.register("fact_shot_chart", _frame(facts, _FACT_DTYPES))
        conn.register("dim_game", _frame(games, _DIM_DTYPES))
        transformer._conn = conn
        return transformer.transform({})
    finally:
        conn.close()


def _assert_transform_error(
    facts: list[dict[str, object]],
    games: list[dict[str, object]],
    match: str,
) -> None:
    with pytest.raises(duckdb.Error, match=match):
        _run(facts, games)


def _schema_row(**updates: object) -> dict[str, object]:
    row: dict[str, object] = {
        "player_id": 2544,
        "season_year": "2024-25",
        "season_type": "Regular Season",
        "shot_zone_basic": "Mid-Range",
        "shot_zone_area": "Center(C)",
        "shot_zone_range": "16-24 ft.",
        "shot_event_count": 4,
        "outcome_observed_attempt_count": 3,
        "made_shot_count_of_observed_outcomes": 2,
        "fg_pct_of_observed_outcomes": 2 / 3,
        "distance_observed_attempt_count": 3,
        "mean_observed_shot_distance": 18.0,
    }
    row.update(updates)
    return row


def test_contract_is_literal_explicit_and_excludes_lossy_sql_patterns() -> None:
    module_tree = ast.parse(inspect.getsource(AggShotZonesTransformer))
    sql_assignments = [
        node
        for node in ast.walk(module_tree)
        if isinstance(node, ast.AnnAssign)
        and isinstance(node.target, ast.Name)
        and node.target.id == "_SQL"
    ]
    assert len(sql_assignments) == 1
    assert isinstance(sql_assignments[0].value, ast.Constant)
    assert isinstance(sql_assignments[0].value.value, str)

    normalized_sql = " ".join(AggShotZonesTransformer._SQL.lower().split())
    assert AggShotZonesTransformer.output_table == "agg_shot_zones"
    assert AggShotZonesTransformer.depends_on == ["fact_shot_chart", "dim_game"]
    assert "select *" not in normalized_sql
    assert " distinct " not in f" {normalized_sql} "
    assert "coalesce(" not in normalized_sql
    assert "count(*) as outcome_observed_attempt_count" not in normalized_sql
    assert "count(shot_made_flag) as outcome_observed_attempt_count" in normalized_sql
    assert "event_identity_authority_missing" in normalized_sql
    assert "events.fact_season_type <> games.dim_season_type" in normalized_sql
    assert "season_type" in _OUTPUT_COLUMNS


def test_regular_season_and_playoffs_remain_separate_with_exact_output() -> None:
    facts = [
        _event_row(game_event_id=2, shot_made_flag=0, shot_distance=None),
        _event_row(game_event_id=1, shot_made_flag=1, shot_distance=5.0),
        _event_row(
            game_id="playoff-game",
            game_event_id=1,
            season_type="Playoffs",
            shot_made_flag=None,
            shot_distance=0.0,
        ),
    ]
    games = [
        _game_row(),
        _game_row(game_id="playoff-game", season_type="Playoffs"),
    ]

    result = _run(facts, games)

    assert result.columns == _OUTPUT_COLUMNS
    assert list(AggShotZonesSchema.to_schema().columns) == _OUTPUT_COLUMNS
    assert result.select("season_type").to_series().to_list() == [
        "Playoffs",
        "Regular Season",
    ]
    playoff, regular = result.to_dicts()
    assert playoff["shot_event_count"] == 1
    assert playoff["outcome_observed_attempt_count"] == 0
    assert playoff["made_shot_count_of_observed_outcomes"] == 0
    assert playoff["fg_pct_of_observed_outcomes"] is None
    assert playoff["distance_observed_attempt_count"] == 1
    assert playoff["mean_observed_shot_distance"] == pytest.approx(0.0)
    assert regular["shot_event_count"] == 2
    assert regular["outcome_observed_attempt_count"] == 2
    assert regular["made_shot_count_of_observed_outcomes"] == 1
    assert regular["fg_pct_of_observed_outcomes"] == pytest.approx(0.5)
    assert regular["distance_observed_attempt_count"] == 1
    assert regular["mean_observed_shot_distance"] == pytest.approx(5.0)
    assert AggShotZonesSchema.validate(result).to_dicts() == result.to_dicts()


def test_exact_projected_duplicates_and_extras_collapse_for_fact_and_dim() -> None:
    fact = _event_row()
    game = _game_row()

    result = _run(
        [fact, dict(fact), dict(fact, provider_extra="different")],
        [game, dict(game), dict(game, provider_extra="different")],
    )

    assert result.height == 1
    assert result.row(0, named=True)["shot_event_count"] == 1


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("player_id", 201935),
        ("season_year", "2023-24"),
        ("season_type", "Playoffs"),
        ("shot_zone_basic", "Restricted Area"),
        ("shot_zone_area", "Left Side(L)"),
        ("shot_zone_range", "Less Than 8 ft."),
        ("shot_made_flag", 0),
        ("shot_distance", 19.0),
        ("shot_made_flag", None),
        ("shot_distance", None),
    ],
)
def test_any_consumed_fact_conflict_for_one_event_identity_fails(
    field: str,
    value: object,
) -> None:
    original = _event_row()
    conflicting = dict(original)
    conflicting[field] = value

    _assert_transform_error(
        [original, conflicting],
        [_game_row()],
        "conflicting consumed fact tuple for event identity",
    )


def test_null_event_identity_fails_with_exact_authority_code() -> None:
    _assert_transform_error(
        [_event_row(game_event_id=None)],
        [_game_row()],
        "event_identity_authority_missing",
    )


@pytest.mark.parametrize(
    ("field", "value", "expected"),
    [
        ("game_id", None, "invalid game_id"),
        ("game_id", " ", "invalid game_id"),
        ("player_id", None, "invalid player_id"),
        ("player_id", 0, "invalid player_id"),
        ("player_id", -1, "invalid player_id"),
        ("season_year", None, "invalid season_year"),
        ("season_year", " ", "invalid season_year"),
        ("season_type", None, "invalid season_type"),
        ("season_type", " ", "invalid season_type"),
        ("shot_zone_basic", None, "invalid shot_zone_basic"),
        ("shot_zone_basic", " ", "invalid shot_zone_basic"),
        ("shot_zone_area", None, "invalid shot_zone_area"),
        ("shot_zone_area", " ", "invalid shot_zone_area"),
        ("shot_zone_range", None, "invalid shot_zone_range"),
        ("shot_zone_range", " ", "invalid shot_zone_range"),
    ],
)
def test_invalid_fact_identity_or_zone_fails(
    field: str,
    value: object,
    expected: str,
) -> None:
    event = _event_row()
    event[field] = value

    _assert_transform_error([event], [_game_row()], expected)


def test_missing_dim_game_fails() -> None:
    _assert_transform_error([_event_row()], [], "fact event is missing dim_game")


@pytest.mark.parametrize("field", ["season_year", "season_type"])
def test_conflicting_consumed_dim_tuple_fails(field: str) -> None:
    game = _game_row()
    conflicting = dict(game)
    conflicting[field] = "different"

    _assert_transform_error(
        [_event_row()],
        [game, conflicting],
        "conflicting consumed dim_game tuple",
    )


@pytest.mark.parametrize(
    ("field", "value", "expected"),
    [
        ("season_year", None, "dim_game has invalid season_year"),
        ("season_year", " ", "dim_game has invalid season_year"),
        ("season_type", None, "dim_game has invalid season_type"),
        ("season_type", " ", "dim_game has invalid season_type"),
    ],
)
def test_invalid_dim_scope_fails(field: str, value: object, expected: str) -> None:
    game = _game_row()
    game[field] = value

    _assert_transform_error([_event_row()], [game], expected)


def test_dim_only_game_is_ignored() -> None:
    result = _run([], [_game_row(game_id="future-game")])

    assert result.shape == (0, len(_OUTPUT_COLUMNS))
    assert result.columns == _OUTPUT_COLUMNS


@pytest.mark.parametrize(
    ("field", "value"),
    [("season_year", "2023-24"), ("season_type", "Playoffs")],
)
def test_fact_and_dim_season_scope_mismatch_fails(field: str, value: str) -> None:
    event = _event_row()
    event[field] = value

    _assert_transform_error(
        [event],
        [_game_row()],
        "fact and dim_game season scope differs",
    )


@pytest.mark.parametrize(
    ("outcomes", "observed", "made", "percentage"),
    [
        ([None], 0, 0, None),
        ([0], 1, 0, 0.0),
        ([1], 1, 1, 1.0),
        ([None, 0, 1], 2, 1, 0.5),
    ],
)
def test_outcome_coverage_distinguishes_unknown_miss_and_make(
    outcomes: list[int | None],
    observed: int,
    made: int,
    percentage: float | None,
) -> None:
    events = [
        _event_row(game_event_id=index + 1, shot_made_flag=outcome, shot_distance=None)
        for index, outcome in enumerate(outcomes)
    ]

    row = _run(events, [_game_row()]).row(0, named=True)

    assert row["shot_event_count"] == len(outcomes)
    assert row["outcome_observed_attempt_count"] == observed
    assert row["made_shot_count_of_observed_outcomes"] == made
    if percentage is None:
        assert row["fg_pct_of_observed_outcomes"] is None
    else:
        assert row["fg_pct_of_observed_outcomes"] == pytest.approx(percentage)


@pytest.mark.parametrize("invalid_outcome", [-1, 2])
def test_invalid_nonnull_outcome_fails(invalid_outcome: int) -> None:
    _assert_transform_error(
        [_event_row(shot_made_flag=invalid_outcome)],
        [_game_row()],
        "invalid shot_made_flag",
    )


@pytest.mark.parametrize(
    ("distances", "observed", "mean"),
    [
        ([None], 0, None),
        ([0.0], 1, 0.0),
        ([None, 0.0, 10.0], 2, 5.0),
    ],
)
def test_distance_coverage_distinguishes_unknown_and_zero(
    distances: list[float | None],
    observed: int,
    mean: float | None,
) -> None:
    events = [
        _event_row(game_event_id=index + 1, shot_made_flag=None, shot_distance=distance)
        for index, distance in enumerate(distances)
    ]

    row = _run(events, [_game_row()]).row(0, named=True)

    assert row["shot_event_count"] == len(distances)
    assert row["distance_observed_attempt_count"] == observed
    if mean is None:
        assert row["mean_observed_shot_distance"] is None
    else:
        assert row["mean_observed_shot_distance"] == pytest.approx(mean)


@pytest.mark.parametrize("invalid_distance", [-0.1, float("nan"), float("inf"), float("-inf")])
def test_invalid_nonnull_distance_fails(invalid_distance: float) -> None:
    _assert_transform_error(
        [_event_row(shot_distance=invalid_distance)],
        [_game_row()],
        "invalid shot_distance",
    )


def test_zone_values_are_not_normalized() -> None:
    event = _event_row(
        shot_zone_basic="  Mid-Range  ",
        shot_zone_area=" Left Side(L) ",
        shot_zone_range=" 16-24 ft. ",
    )

    row = _run([event], [_game_row()]).row(0, named=True)

    assert row["shot_zone_basic"] == "  Mid-Range  "
    assert row["shot_zone_area"] == " Left Side(L) "
    assert row["shot_zone_range"] == " 16-24 ft. "


def test_output_order_is_exact_and_deterministic_across_all_grain_keys() -> None:
    facts = [
        _event_row(player_id=2, game_event_id=3, shot_zone_basic="B"),
        _event_row(player_id=1, game_event_id=2, shot_zone_basic="Z"),
        _event_row(player_id=1, game_event_id=1, shot_zone_basic="A"),
    ]

    result = _run(facts, [_game_row()])

    assert result.select("player_id", "shot_zone_basic").rows() == [
        (1, "A"),
        (1, "Z"),
        (2, "B"),
    ]


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("player_id", 0),
        ("shot_event_count", 0),
        ("outcome_observed_attempt_count", 5),
        ("made_shot_count_of_observed_outcomes", 4),
        ("distance_observed_attempt_count", 5),
        ("fg_pct_of_observed_outcomes", -0.1),
        ("fg_pct_of_observed_outcomes", 1.1),
        ("fg_pct_of_observed_outcomes", float("nan")),
        ("fg_pct_of_observed_outcomes", float("inf")),
        ("mean_observed_shot_distance", -0.1),
        ("mean_observed_shot_distance", float("nan")),
        ("mean_observed_shot_distance", float("inf")),
    ],
)
def test_schema_rejects_invalid_counts_bounds_or_nonfinite_metric(
    field: str,
    value: object,
) -> None:
    with pytest.raises(SchemaError):
        AggShotZonesSchema.validate(pl.DataFrame([_schema_row(**{field: value})]))


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("season_year", " "),
        ("season_type", " "),
        ("shot_zone_basic", " "),
        ("shot_zone_area", " "),
        ("shot_zone_range", " "),
    ],
)
def test_schema_rejects_blank_grain_value(field: str, value: str) -> None:
    with pytest.raises(SchemaError, match="structural_keys_are_nonblank_and_unique"):
        AggShotZonesSchema.validate(pl.DataFrame([_schema_row(**{field: value})]))


def test_schema_rejects_duplicate_composite_grain() -> None:
    row = _schema_row()

    with pytest.raises(SchemaError, match="structural_keys_are_nonblank_and_unique"):
        AggShotZonesSchema.validate(pl.DataFrame([row, row]))


@pytest.mark.parametrize(
    ("updates", "expected_check"),
    [
        (
            {
                "outcome_observed_attempt_count": 0,
                "made_shot_count_of_observed_outcomes": 0,
                "fg_pct_of_observed_outcomes": 0.0,
            },
            "metric_nullability_matches_coverage",
        ),
        (
            {
                "outcome_observed_attempt_count": 1,
                "made_shot_count_of_observed_outcomes": 1,
                "fg_pct_of_observed_outcomes": None,
            },
            "metric_nullability_matches_coverage",
        ),
        (
            {"distance_observed_attempt_count": 0, "mean_observed_shot_distance": 0.0},
            "metric_nullability_matches_coverage",
        ),
        (
            {"distance_observed_attempt_count": 1, "mean_observed_shot_distance": None},
            "metric_nullability_matches_coverage",
        ),
    ],
)
def test_schema_binds_metric_nullability_to_coverage(
    updates: dict[str, object],
    expected_check: str,
) -> None:
    with pytest.raises(SchemaError, match=expected_check):
        AggShotZonesSchema.validate(pl.DataFrame([_schema_row(**updates)]))


def test_schema_does_not_claim_floating_arithmetic_reverification() -> None:
    row = _schema_row(
        shot_event_count=10,
        outcome_observed_attempt_count=5,
        made_shot_count_of_observed_outcomes=2,
        fg_pct_of_observed_outcomes=0.9,
        distance_observed_attempt_count=3,
        mean_observed_shot_distance=99.0,
    )

    validated = AggShotZonesSchema.validate(pl.DataFrame([row]))

    assert validated.row(0, named=True) == row
