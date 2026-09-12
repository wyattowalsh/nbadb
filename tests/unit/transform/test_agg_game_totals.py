"""Adversarial structural tests for the per-game totals aggregate."""

from __future__ import annotations

from typing import Any

import duckdb
import polars as pl
import pytest
from pandera.errors import SchemaError

from nbadb.schemas.star.agg_schemas import AggGameTotalsSchema
from nbadb.transform.derived.agg_game_totals import AggGameTotalsTransformer

_OUTPUT_COLUMNS = [
    "game_id",
    "game_date",
    "season_year",
    "season_type",
    "home_team_id",
    "away_team_id",
    "home_pts",
    "away_pts",
    "total_pts",
    "home_reb",
    "away_reb",
    "home_ast",
    "away_ast",
    "home_fg_pct",
    "away_fg_pct",
]

_FACT_DTYPES = {
    "game_id": pl.String,
    "team_id": pl.Int64,
    "pts": pl.Int64,
    "reb": pl.Int64,
    "ast": pl.Int64,
    "fgm": pl.Int64,
    "fga": pl.Int64,
    "provider_extra": pl.String,
}
_BRIDGE_DTYPES = {
    "game_id": pl.String,
    "team_id": pl.Int64,
    "side": pl.String,
    "provider_extra": pl.String,
}
_DIM_DTYPES = {
    "game_id": pl.String,
    "game_date": pl.String,
    "season_year": pl.String,
    "season_type": pl.String,
    "home_team_id": pl.Int64,
    "visitor_team_id": pl.Int64,
    "provider_extra": pl.String,
}


def _frame(rows: list[dict[str, object]], dtypes: dict[str, Any]) -> pl.DataFrame:
    if not rows:
        return pl.DataFrame(schema=dtypes)
    return pl.DataFrame(rows, schema_overrides=dtypes)


def _fact_row(
    *,
    game_id: str | None = "0001",
    team_id: int | None = 10,
    **updates: object,
) -> dict[str, object]:
    is_home = team_id == 10
    row: dict[str, object] = {
        "game_id": game_id,
        "team_id": team_id,
        "pts": 110 if is_home else 102,
        "reb": 40 if is_home else 38,
        "ast": 25 if is_home else 22,
        "fgm": 40 if is_home else 35,
        "fga": 85 if is_home else 80,
        "provider_extra": "ignored-fact",
    }
    row.update(updates)
    return row


def _bridge_row(
    *,
    game_id: str | None = "0001",
    team_id: int | None = 10,
    side: str | None = "home",
    **updates: object,
) -> dict[str, object]:
    row: dict[str, object] = {
        "game_id": game_id,
        "team_id": team_id,
        "side": side,
        "provider_extra": "ignored-bridge",
    }
    row.update(updates)
    return row


def _dim_row(
    *,
    game_id: str | None = "0001",
    home_team_id: int | None = 10,
    visitor_team_id: int | None = 20,
    **updates: object,
) -> dict[str, object]:
    row: dict[str, object] = {
        "game_id": game_id,
        "game_date": "2024-01-15",
        "season_year": "2023-24",
        "season_type": "Regular Season",
        "home_team_id": home_team_id,
        "visitor_team_id": visitor_team_id,
        "provider_extra": "ignored-dim",
    }
    row.update(updates)
    return row


def _sources(
    *,
    game_id: str = "0001",
    home_team_id: int = 10,
    away_team_id: int = 20,
    dim_home_team_id: int | None = 10,
    dim_visitor_team_id: int | None = 20,
) -> tuple[list[dict[str, object]], list[dict[str, object]], list[dict[str, object]]]:
    return (
        [
            _fact_row(game_id=game_id, team_id=home_team_id),
            _fact_row(game_id=game_id, team_id=away_team_id),
        ],
        [
            _bridge_row(game_id=game_id, team_id=home_team_id, side="home"),
            _bridge_row(game_id=game_id, team_id=away_team_id, side="away"),
        ],
        [
            _dim_row(
                game_id=game_id,
                home_team_id=dim_home_team_id,
                visitor_team_id=dim_visitor_team_id,
            )
        ],
    )


def _run(
    facts: list[dict[str, object]],
    bridges: list[dict[str, object]],
    games: list[dict[str, object]],
) -> pl.DataFrame:
    transformer = AggGameTotalsTransformer()
    conn = duckdb.connect()
    try:
        conn.register("fact_team_game", _frame(facts, _FACT_DTYPES))
        conn.register("bridge_game_team", _frame(bridges, _BRIDGE_DTYPES))
        conn.register("dim_game", _frame(games, _DIM_DTYPES))
        transformer._conn = conn
        return transformer.transform({})
    finally:
        conn.close()


def _assert_transform_error(
    facts: list[dict[str, object]],
    bridges: list[dict[str, object]],
    games: list[dict[str, object]],
    match: str,
) -> None:
    with pytest.raises(duckdb.Error, match=match):
        _run(facts, bridges, games)


def _schema_row(**updates: object) -> dict[str, object]:
    row: dict[str, object] = {
        "game_id": "0001",
        "game_date": "2024-01-15",
        "season_year": "2023-24",
        "season_type": "Regular Season",
        "home_team_id": 10,
        "away_team_id": 20,
        "home_pts": 110,
        "away_pts": 102,
        "total_pts": 212,
        "home_reb": 40,
        "away_reb": 38,
        "home_ast": 25,
        "away_ast": 22,
        "home_fg_pct": 40 / 85,
        "away_fg_pct": 35 / 80,
    }
    row.update(updates)
    return row


def test_exact_contract_dependencies_projection_and_guard_surface() -> None:
    assert AggGameTotalsTransformer.output_table == "agg_game_totals"
    assert AggGameTotalsTransformer.depends_on == [
        "fact_team_game",
        "bridge_game_team",
        "dim_game",
    ]

    normalized_sql = " ".join(AggGameTotalsTransformer._SQL.lower().split())
    assert "select *" not in normalized_sql
    assert "candidate_games" in normalized_sql
    assert "select game_id from fact_by_game union select game_id from bridge_by_game" in (
        normalized_sql
    )
    assert "coalesce(" not in normalized_sql
    assert "conflicting consumed fact tuple for game-team" in normalized_sql
    assert "fact and bridge team sets differ" in normalized_sql
    assert "conflicting consumed dim_game tuple" in normalized_sql


def test_multiple_games_are_one_row_each_ordered_and_schema_exact() -> None:
    facts_2, bridges_2, games_2 = _sources(game_id="0002")
    games_2[0].update(game_date="2024-01-16")
    facts_1, bridges_1, games_1 = _sources(game_id="0001")

    result = _run(facts_2 + facts_1, bridges_2 + bridges_1, games_2 + games_1)

    assert result.columns == _OUTPUT_COLUMNS
    assert list(AggGameTotalsSchema.to_schema().columns) == _OUTPUT_COLUMNS
    assert result["game_id"].to_list() == ["0001", "0002"]
    assert result.schema["game_id"] == pl.String
    assert result.height == 2
    assert AggGameTotalsSchema.validate(result).to_dicts() == result.to_dicts()
    assert result.row(0, named=True) == {
        "game_id": "0001",
        "game_date": "2024-01-15",
        "season_year": "2023-24",
        "season_type": "Regular Season",
        "home_team_id": 10,
        "away_team_id": 20,
        "home_pts": 110,
        "away_pts": 102,
        "total_pts": 212,
        "home_reb": 40,
        "away_reb": 38,
        "home_ast": 25,
        "away_ast": 22,
        "home_fg_pct": pytest.approx(40 / 85),
        "away_fg_pct": pytest.approx(35 / 80),
    }


def test_exact_duplicates_and_unconsumed_extras_collapse_in_every_source() -> None:
    facts, bridges, games = _sources()
    duplicate_facts = [dict(row, provider_extra="different") for row in facts]
    duplicate_bridges = [dict(row, provider_extra="different") for row in bridges]
    duplicate_games = [dict(games[0], provider_extra="different")]

    result = _run(
        facts + duplicate_facts + [dict(facts[0])],
        bridges + duplicate_bridges + [dict(bridges[0])],
        games + duplicate_games + [dict(games[0])],
    )

    assert result.height == 1
    assert result.row(0, named=True)["total_pts"] == 212


@pytest.mark.parametrize("field", ["pts", "reb", "ast", "fgm", "fga"])
def test_each_consumed_fact_value_conflict_fails(field: str) -> None:
    facts, bridges, games = _sources()
    conflicting = dict(facts[0])
    conflicting[field] = int(conflicting[field]) + 1

    _assert_transform_error(
        facts + [conflicting],
        bridges,
        games,
        "conflicting consumed fact tuple",
    )


@pytest.mark.parametrize("field", ["pts", "reb", "ast", "fgm", "fga"])
def test_each_consumed_fact_null_vs_known_conflict_fails(field: str) -> None:
    facts, bridges, games = _sources()
    conflicting = dict(facts[0])
    conflicting[field] = None

    _assert_transform_error(
        facts + [conflicting],
        bridges,
        games,
        "conflicting consumed fact tuple",
    )


@pytest.mark.parametrize("invalid_team_id", [None, 0, -1])
def test_invalid_fact_team_key_fails(invalid_team_id: int | None) -> None:
    facts, bridges, games = _sources()
    facts[0]["team_id"] = invalid_team_id

    _assert_transform_error(facts, bridges, games, "fact source has invalid key")


@pytest.mark.parametrize("side", [None, "neutral", "Home"])
def test_unknown_null_or_case_variant_bridge_side_fails(side: str | None) -> None:
    facts, bridges, games = _sources()
    bridges[0]["side"] = side

    _assert_transform_error(facts, bridges, games, "bridge source has invalid side")


@pytest.mark.parametrize("invalid_team_id", [None, 0, -1])
def test_invalid_bridge_team_key_fails(invalid_team_id: int | None) -> None:
    facts, bridges, games = _sources()
    bridges[0]["team_id"] = invalid_team_id

    _assert_transform_error(facts, bridges, games, "bridge source has invalid key")


def test_same_bridge_team_on_both_sides_fails() -> None:
    facts, bridges, games = _sources()
    bridges[1]["team_id"] = 10

    _assert_transform_error(facts, bridges, games, "one team to both sides")


@pytest.mark.parametrize("duplicated_side", ["home", "away"])
def test_multiple_teams_for_one_bridge_side_fails(duplicated_side: str) -> None:
    facts, bridges, games = _sources()
    bridges.append(
        _bridge_row(
            team_id=30,
            side=duplicated_side,
        )
    )

    _assert_transform_error(facts, bridges, games, "multiple teams for one side")


@pytest.mark.parametrize("retained_side", ["home", "away"])
def test_incomplete_bridge_pair_fails(retained_side: str) -> None:
    facts, bridges, games = _sources()
    bridges = [row for row in bridges if row["side"] == retained_side]

    _assert_transform_error(facts, bridges, games, "does not have an exact side pair")


@pytest.mark.parametrize(
    ("case", "expected"),
    [
        ("fact_only", "missing bridge_game_team"),
        ("bridge_only", "missing fact_team_game"),
        ("one_fact_side", "fact source does not have exactly two teams"),
        ("third_fact_team", "fact source does not have exactly two teams"),
        ("different_fact_pair", "fact and bridge team sets differ"),
        ("missing_dim", "candidate is missing dim_game"),
    ],
)
def test_candidate_denominator_gaps_fail_closed(case: str, expected: str) -> None:
    facts, bridges, games = _sources()
    if case == "fact_only":
        bridges = []
    elif case == "bridge_only":
        facts = []
    elif case == "one_fact_side":
        facts = facts[:1]
    elif case == "third_fact_team":
        facts.append(_fact_row(team_id=30))
    elif case == "different_fact_pair":
        facts[1] = _fact_row(team_id=30)
    elif case == "missing_dim":
        games = []
    else:  # pragma: no cover - parametrization is the exhaustive case authority
        raise AssertionError(case)

    _assert_transform_error(facts, bridges, games, expected)


def test_dim_only_future_game_is_not_a_candidate() -> None:
    result = _run([], [], [_dim_row(game_id="future")])

    assert result.shape == (0, len(_OUTPUT_COLUMNS))
    assert result.columns == _OUTPUT_COLUMNS


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("game_date", "2024-02-01"),
        ("season_year", "2024-25"),
        ("season_type", "Playoffs"),
        ("home_team_id", 30),
        ("visitor_team_id", 30),
    ],
)
def test_each_consumed_dim_conflict_fails(field: str, value: object) -> None:
    facts, bridges, games = _sources()
    conflicting = dict(games[0])
    conflicting[field] = value

    _assert_transform_error(
        facts,
        bridges,
        games + [conflicting],
        "conflicting consumed dim_game tuple",
    )


@pytest.mark.parametrize(
    ("dim_home_team_id", "dim_visitor_team_id"),
    [(10, 20), (None, None)],
)
def test_exact_or_fully_unavailable_dim_team_pair_is_admitted(
    dim_home_team_id: int | None,
    dim_visitor_team_id: int | None,
) -> None:
    facts, bridges, games = _sources(
        dim_home_team_id=dim_home_team_id,
        dim_visitor_team_id=dim_visitor_team_id,
    )

    result = _run(facts, bridges, games)

    assert result.select("home_team_id", "away_team_id").row(0) == (10, 20)


@pytest.mark.parametrize(
    ("dim_home_team_id", "dim_visitor_team_id"),
    [(10, None), (None, 20)],
)
def test_partial_optional_dim_team_pair_fails(
    dim_home_team_id: int | None,
    dim_visitor_team_id: int | None,
) -> None:
    facts, bridges, games = _sources(
        dim_home_team_id=dim_home_team_id,
        dim_visitor_team_id=dim_visitor_team_id,
    )

    _assert_transform_error(facts, bridges, games, "partial optional team pair")


@pytest.mark.parametrize(
    ("dim_home_team_id", "dim_visitor_team_id", "expected"),
    [
        (20, 10, "dim_game and bridge team pairs differ"),
        (10, 30, "dim_game and bridge team pairs differ"),
        (10, 10, "dim_game assigns one team to both sides"),
    ],
)
def test_swapped_different_or_equal_dim_team_pair_fails(
    dim_home_team_id: int,
    dim_visitor_team_id: int,
    expected: str,
) -> None:
    facts, bridges, games = _sources(
        dim_home_team_id=dim_home_team_id,
        dim_visitor_team_id=dim_visitor_team_id,
    )

    _assert_transform_error(facts, bridges, games, expected)


@pytest.mark.parametrize(
    ("field", "value", "expected"),
    [
        ("game_date", None, "invalid game_date"),
        ("game_date", " ", "invalid game_date"),
        ("season_year", None, "invalid season_year"),
        ("season_year", " ", "invalid season_year"),
        ("season_type", " ", "blank season_type"),
    ],
)
def test_invalid_required_or_blank_dim_value_fails(
    field: str,
    value: object,
    expected: str,
) -> None:
    facts, bridges, games = _sources()
    games[0][field] = value

    _assert_transform_error(facts, bridges, games, expected)


@pytest.mark.parametrize(
    ("home_pts", "away_pts", "expected_total"),
    [
        (110, 102, 212),
        (0, 0, 0),
        (None, 102, None),
        (110, None, None),
        (None, None, None),
    ],
)
def test_total_points_preserves_zero_and_requires_both_inputs(
    home_pts: int | None,
    away_pts: int | None,
    expected_total: int | None,
) -> None:
    facts, bridges, games = _sources()
    facts[0]["pts"] = home_pts
    facts[1]["pts"] = away_pts

    row = _run(facts, bridges, games).row(0, named=True)

    assert row["home_pts"] == home_pts
    assert row["away_pts"] == away_pts
    assert row["total_pts"] == expected_total


@pytest.mark.parametrize("side_index", [0, 1])
@pytest.mark.parametrize(
    ("fgm", "fga", "expected"),
    [
        (0, 10, 0.0),
        (5, 10, 0.5),
        (None, 10, None),
        (5, None, None),
        (5, 0, None),
        (0, 0, None),
    ],
)
def test_field_goal_percentage_is_side_local_and_denominator_guarded(
    side_index: int,
    fgm: int | None,
    fga: int | None,
    expected: float | None,
) -> None:
    facts, bridges, games = _sources()
    facts[side_index]["fgm"] = fgm
    facts[side_index]["fga"] = fga

    row = _run(facts, bridges, games).row(0, named=True)
    metric = "home_fg_pct" if side_index == 0 else "away_fg_pct"
    other_metric = "away_fg_pct" if side_index == 0 else "home_fg_pct"

    assert row[metric] == pytest.approx(expected) if expected is not None else row[metric] is None
    assert row[other_metric] is not None


def test_nullable_and_zero_box_score_fields_are_preserved_independently() -> None:
    facts, bridges, games = _sources()
    facts[0].update(reb=0, ast=None)
    facts[1].update(reb=None, ast=0)

    row = _run(facts, bridges, games).row(0, named=True)

    assert row["home_reb"] == 0
    assert row["away_reb"] is None
    assert row["home_ast"] is None
    assert row["away_ast"] == 0


def test_schema_allows_nullable_metrics_and_season_type() -> None:
    row = _schema_row(
        season_type=None,
        home_pts=None,
        away_pts=None,
        total_pts=None,
        home_reb=None,
        away_reb=None,
        home_ast=None,
        away_ast=None,
        home_fg_pct=None,
        away_fg_pct=None,
    )

    result = AggGameTotalsSchema.validate(pl.DataFrame([row]))

    assert result.row(0, named=True) == row


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("game_id", " "),
        ("game_date", " "),
        ("season_year", " "),
        ("season_type", " "),
        ("home_team_id", None),
        ("away_team_id", None),
        ("away_team_id", 10),
        ("home_fg_pct", -0.01),
        ("home_fg_pct", 1.01),
        ("away_fg_pct", -0.01),
        ("away_fg_pct", 1.01),
    ],
)
def test_schema_rejects_invalid_structural_or_percentage_value(
    field: str,
    value: object,
) -> None:
    with pytest.raises(SchemaError):
        AggGameTotalsSchema.validate(pl.DataFrame([_schema_row(**{field: value})]))


def test_schema_rejects_duplicate_game_identity() -> None:
    row = _schema_row()

    with pytest.raises(SchemaError):
        AggGameTotalsSchema.validate(pl.DataFrame([row, row]))


def test_schema_does_not_claim_arithmetic_reverification() -> None:
    row = _schema_row(total_pts=1, home_fg_pct=0.25, away_fg_pct=0.75)

    validated = AggGameTotalsSchema.validate(pl.DataFrame([row]))

    assert validated.row(0, named=True) == row
