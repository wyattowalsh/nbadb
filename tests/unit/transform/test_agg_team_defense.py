"""Adversarial tests for the observed-game team-defense aggregate."""

from __future__ import annotations

import duckdb
import polars as pl
import pytest
from pandera.errors import SchemaError

from nbadb.schemas.star.agg_schemas import AggTeamDefenseSchema
from nbadb.transform.derived.agg_team_defense import AggTeamDefenseTransformer

_TEAM_ID = 1610612738

_OUTPUT_COLUMNS = [
    "team_id",
    "season_year",
    "season_type",
    "observed_game_count",
    "def_rating_coverage_game_count",
    "mean_observed_game_def_rating",
    "net_rating_coverage_game_count",
    "mean_observed_game_net_rating",
    "four_factors_observed_game_count",
    "opp_effective_field_goal_percentage_coverage_game_count",
    "mean_observed_game_opp_effective_field_goal_percentage",
    "opp_free_throw_attempt_rate_coverage_game_count",
    "mean_observed_game_opp_free_throw_attempt_rate",
    "opp_team_turnover_percentage_coverage_game_count",
    "mean_observed_game_opp_team_turnover_percentage",
    "opp_offensive_rebound_percentage_coverage_game_count",
    "mean_observed_game_opp_offensive_rebound_percentage",
    "hustle_observed_game_count",
    "contested_shots_coverage_game_count",
    "total_observed_game_contested_shots",
    "mean_observed_game_contested_shots",
    "deflections_coverage_game_count",
    "total_observed_game_deflections",
    "mean_observed_game_deflections",
    "loose_balls_recovered_coverage_game_count",
    "total_observed_game_loose_balls_recovered",
    "mean_observed_game_loose_balls_recovered",
    "charges_drawn_coverage_game_count",
    "total_observed_game_charges_drawn",
    "mean_observed_game_charges_drawn",
    "screen_assists_coverage_game_count",
    "total_observed_game_screen_assists",
    "mean_observed_game_screen_assists",
]

_ADVANCED_DTYPES = {
    "game_id": pl.String,
    "team_id": pl.Int64,
    "def_rating": pl.Float64,
    "net_rating": pl.Float64,
}
_FOUR_FACTORS_DTYPES = {
    "game_id": pl.String,
    "team_id": pl.Int64,
    "opp_effective_field_goal_percentage": pl.Float64,
    "opp_free_throw_attempt_rate": pl.Float64,
    "opp_team_turnover_percentage": pl.Float64,
    "opp_offensive_rebound_percentage": pl.Float64,
}
_HUSTLE_DTYPES = {
    "game_id": pl.String,
    "team_id": pl.Int64,
    "contested_shots": pl.Float64,
    "deflections": pl.Float64,
    "loose_balls_recovered": pl.Float64,
    "charges_drawn": pl.Float64,
    "screen_assists": pl.Float64,
}
_GAME_DTYPES = {
    "game_id": pl.String,
    "season_year": pl.String,
    "season_type": pl.String,
}


def _frame(rows: list[dict[str, object]], dtypes: dict[str, object]) -> pl.DataFrame:
    if not rows:
        return pl.DataFrame(schema=dtypes)
    return pl.DataFrame(rows, schema_overrides=dtypes)


def _advanced_row(**updates: object) -> dict[str, object]:
    row: dict[str, object] = {
        "game_id": "001",
        "team_id": _TEAM_ID,
        "def_rating": 105.0,
        "net_rating": 5.0,
    }
    row.update(updates)
    return row


def _four_factors_row(**updates: object) -> dict[str, object]:
    row: dict[str, object] = {
        "game_id": "001",
        "team_id": _TEAM_ID,
        "opp_effective_field_goal_percentage": 0.48,
        "opp_free_throw_attempt_rate": 0.22,
        "opp_team_turnover_percentage": 0.15,
        "opp_offensive_rebound_percentage": 0.24,
    }
    row.update(updates)
    return row


def _hustle_row(**updates: object) -> dict[str, object]:
    row: dict[str, object] = {
        "game_id": "001",
        "team_id": _TEAM_ID,
        "contested_shots": 40.0,
        "deflections": 10.0,
        "loose_balls_recovered": 6.0,
        "charges_drawn": 1.0,
        "screen_assists": 8.0,
    }
    row.update(updates)
    return row


def _game_row(**updates: object) -> dict[str, object]:
    row: dict[str, object] = {
        "game_id": "001",
        "season_year": "2024-25",
        "season_type": "Regular Season",
    }
    row.update(updates)
    return row


def _staging(
    *,
    advanced_rows: list[dict[str, object]] | None = None,
    four_factors_rows: list[dict[str, object]] | None = None,
    hustle_rows: list[dict[str, object]] | None = None,
    game_rows: list[dict[str, object]] | None = None,
) -> dict[str, pl.DataFrame]:
    return {
        "fact_box_score_advanced_team": _frame(
            [_advanced_row()] if advanced_rows is None else advanced_rows,
            _ADVANCED_DTYPES,
        ),
        "fact_box_score_four_factors_team": _frame(
            [_four_factors_row()] if four_factors_rows is None else four_factors_rows,
            _FOUR_FACTORS_DTYPES,
        ),
        "fact_team_game_hustle": _frame(
            [_hustle_row()] if hustle_rows is None else hustle_rows,
            _HUSTLE_DTYPES,
        ),
        "dim_game": _frame(
            [_game_row()] if game_rows is None else game_rows,
            _GAME_DTYPES,
        ),
    }


def _run(staging: dict[str, pl.DataFrame]) -> pl.DataFrame:
    transformer = AggTeamDefenseTransformer()
    conn = duckdb.connect()
    try:
        for table_name, frame in staging.items():
            conn.register(table_name, frame)
        transformer._conn = conn
        return transformer.transform({})
    finally:
        conn.close()


def test_exact_contract_dependencies_projection_and_no_ambiguous_names() -> None:
    assert AggTeamDefenseTransformer.output_table == "agg_team_defense"
    assert AggTeamDefenseTransformer.depends_on == [
        "fact_box_score_advanced_team",
        "fact_team_game_hustle",
        "fact_box_score_four_factors_team",
        "dim_game",
    ]
    normalized_sql = " ".join(AggTeamDefenseTransformer._SQL.lower().split())
    assert "select *" not in normalized_sql
    for removed_name in (
        " as gp",
        "avg_def_rating",
        "avg_net_rating",
        "avg_opp_efg_pct",
        "avg_contested_shots",
    ):
        assert removed_name not in normalized_sql
    assert "team defense source join multiplied game-team rows" in normalized_sql
    assert "team defense coverage count exceeds its denominator" in normalized_sql


def test_exact_observed_game_aggregation_presence_coverage_totals_and_schema() -> None:
    result = _run(
        _staging(
            advanced_rows=[
                _advanced_row(game_id="001", def_rating=100.0, net_rating=5.0, source_extra="drop"),
                _advanced_row(game_id="002", def_rating=None, net_rating=-1.0, source_extra="drop"),
                _advanced_row(
                    game_id="003", def_rating=110.0, net_rating=None, source_extra="drop"
                ),
            ],
            four_factors_rows=[
                _four_factors_row(game_id="001", source_extra="drop"),
                _four_factors_row(
                    game_id="002",
                    opp_effective_field_goal_percentage=None,
                    opp_free_throw_attempt_rate=None,
                    opp_team_turnover_percentage=None,
                    opp_offensive_rebound_percentage=None,
                    source_extra="drop",
                ),
            ],
            hustle_rows=[
                _hustle_row(game_id="001", source_extra="drop"),
                _hustle_row(
                    game_id="002",
                    contested_shots=None,
                    deflections=14.0,
                    loose_balls_recovered=None,
                    charges_drawn=3.0,
                    screen_assists=None,
                    source_extra="drop",
                ),
            ],
            game_rows=[
                _game_row(game_id="001", dim_extra="drop"),
                _game_row(game_id="002", dim_extra="drop"),
                _game_row(game_id="003", dim_extra="drop"),
            ],
        )
    )
    row = result.row(0, named=True)

    assert result.columns == _OUTPUT_COLUMNS
    assert list(AggTeamDefenseSchema.to_schema().columns) == _OUTPUT_COLUMNS
    assert AggTeamDefenseSchema.validate(result).to_dicts() == result.to_dicts()
    assert row["observed_game_count"] == 3
    assert row["def_rating_coverage_game_count"] == 2
    assert row["mean_observed_game_def_rating"] == pytest.approx(105.0)
    assert row["net_rating_coverage_game_count"] == 2
    assert row["mean_observed_game_net_rating"] == pytest.approx(2.0)
    assert row["four_factors_observed_game_count"] == 2
    assert row["hustle_observed_game_count"] == 2
    assert row["contested_shots_coverage_game_count"] == 1
    assert row["total_observed_game_contested_shots"] == pytest.approx(40.0)
    assert row["mean_observed_game_contested_shots"] == pytest.approx(40.0)
    assert row["deflections_coverage_game_count"] == 2
    assert row["total_observed_game_deflections"] == pytest.approx(24.0)
    assert row["mean_observed_game_deflections"] == pytest.approx(12.0)
    assert row["charges_drawn_coverage_game_count"] == 2
    assert row["total_observed_game_charges_drawn"] == pytest.approx(4.0)
    assert row["mean_observed_game_charges_drawn"] == pytest.approx(2.0)
    for column in (
        "total_observed_game_contested_shots",
        "total_observed_game_deflections",
        "total_observed_game_loose_balls_recovered",
        "total_observed_game_charges_drawn",
        "total_observed_game_screen_assists",
    ):
        assert result[column].dtype == pl.Float64


@pytest.mark.parametrize(
    ("provider_field", "coverage_field", "mean_field", "first_value"),
    [
        (
            "opp_effective_field_goal_percentage",
            "opp_effective_field_goal_percentage_coverage_game_count",
            "mean_observed_game_opp_effective_field_goal_percentage",
            0.48,
        ),
        (
            "opp_free_throw_attempt_rate",
            "opp_free_throw_attempt_rate_coverage_game_count",
            "mean_observed_game_opp_free_throw_attempt_rate",
            0.22,
        ),
        (
            "opp_team_turnover_percentage",
            "opp_team_turnover_percentage_coverage_game_count",
            "mean_observed_game_opp_team_turnover_percentage",
            0.15,
        ),
        (
            "opp_offensive_rebound_percentage",
            "opp_offensive_rebound_percentage_coverage_game_count",
            "mean_observed_game_opp_offensive_rebound_percentage",
            0.24,
        ),
    ],
)
def test_four_factors_field_symmetry(
    provider_field: str,
    coverage_field: str,
    mean_field: str,
    first_value: float,
) -> None:
    result = _run(
        _staging(
            advanced_rows=[_advanced_row(game_id="001"), _advanced_row(game_id="002")],
            four_factors_rows=[
                _four_factors_row(game_id="001", **{provider_field: first_value}),
                _four_factors_row(game_id="002", **{provider_field: None}),
            ],
            hustle_rows=[],
            game_rows=[_game_row(game_id="001"), _game_row(game_id="002")],
        )
    )
    row = result.row(0, named=True)

    assert row["four_factors_observed_game_count"] == 2
    assert row[coverage_field] == 1
    assert row[mean_field] == pytest.approx(first_value)


@pytest.mark.parametrize(
    ("provider_field", "coverage_field", "total_field", "mean_field", "first_value"),
    [
        (
            "contested_shots",
            "contested_shots_coverage_game_count",
            "total_observed_game_contested_shots",
            "mean_observed_game_contested_shots",
            40.0,
        ),
        (
            "deflections",
            "deflections_coverage_game_count",
            "total_observed_game_deflections",
            "mean_observed_game_deflections",
            10.0,
        ),
        (
            "loose_balls_recovered",
            "loose_balls_recovered_coverage_game_count",
            "total_observed_game_loose_balls_recovered",
            "mean_observed_game_loose_balls_recovered",
            6.0,
        ),
        (
            "charges_drawn",
            "charges_drawn_coverage_game_count",
            "total_observed_game_charges_drawn",
            "mean_observed_game_charges_drawn",
            1.0,
        ),
        (
            "screen_assists",
            "screen_assists_coverage_game_count",
            "total_observed_game_screen_assists",
            "mean_observed_game_screen_assists",
            8.0,
        ),
    ],
)
def test_hustle_field_symmetry(
    provider_field: str,
    coverage_field: str,
    total_field: str,
    mean_field: str,
    first_value: float,
) -> None:
    result = _run(
        _staging(
            advanced_rows=[_advanced_row(game_id="001"), _advanced_row(game_id="002")],
            four_factors_rows=[],
            hustle_rows=[
                _hustle_row(game_id="001", **{provider_field: first_value}),
                _hustle_row(game_id="002", **{provider_field: None}),
            ],
            game_rows=[_game_row(game_id="001"), _game_row(game_id="002")],
        )
    )
    row = result.row(0, named=True)

    assert row["hustle_observed_game_count"] == 2
    assert row[coverage_field] == 1
    assert row[total_field] == pytest.approx(first_value)
    assert row[mean_field] == pytest.approx(first_value)


def test_present_all_null_optional_rows_are_distinct_from_absent_rows() -> None:
    result = _run(
        _staging(
            advanced_rows=[_advanced_row(game_id="001"), _advanced_row(game_id="002")],
            four_factors_rows=[
                _four_factors_row(
                    game_id="001",
                    opp_effective_field_goal_percentage=None,
                    opp_free_throw_attempt_rate=None,
                    opp_team_turnover_percentage=None,
                    opp_offensive_rebound_percentage=None,
                )
            ],
            hustle_rows=[
                _hustle_row(
                    game_id="001",
                    contested_shots=None,
                    deflections=None,
                    loose_balls_recovered=None,
                    charges_drawn=None,
                    screen_assists=None,
                )
            ],
            game_rows=[_game_row(game_id="001"), _game_row(game_id="002")],
        )
    )
    row = result.row(0, named=True)

    assert row["four_factors_observed_game_count"] == 1
    assert row["opp_effective_field_goal_percentage_coverage_game_count"] == 0
    assert row["mean_observed_game_opp_effective_field_goal_percentage"] is None
    assert row["hustle_observed_game_count"] == 1
    assert row["contested_shots_coverage_game_count"] == 0
    assert row["total_observed_game_contested_shots"] is None
    assert row["mean_observed_game_contested_shots"] is None


def test_exact_duplicates_collapse_without_join_multiplication() -> None:
    advanced = _advanced_row()
    four_factors = _four_factors_row()
    hustle = _hustle_row()
    game = _game_row()
    result = _run(
        _staging(
            advanced_rows=[advanced, advanced.copy()],
            four_factors_rows=[four_factors, four_factors.copy()],
            hustle_rows=[hustle, hustle.copy()],
            game_rows=[game, game.copy()],
        )
    )
    row = result.row(0, named=True)

    assert row["observed_game_count"] == 1
    assert row["four_factors_observed_game_count"] == 1
    assert row["hustle_observed_game_count"] == 1
    assert row["total_observed_game_contested_shots"] == pytest.approx(40.0)


@pytest.mark.parametrize(
    ("source", "message"),
    [
        ("advanced", "conflicting advanced defense tuple"),
        ("four_factors", "conflicting four-factors defense tuple"),
        ("hustle", "conflicting hustle defense tuple"),
        ("game", "conflicting defense game dimension tuple"),
    ],
)
def test_whole_tuple_conflicts_fail_closed(source: str, message: str) -> None:
    kwargs: dict[str, list[dict[str, object]]] = {}
    if source == "advanced":
        kwargs["advanced_rows"] = [_advanced_row(), _advanced_row(def_rating=106.0)]
    elif source == "four_factors":
        kwargs["four_factors_rows"] = [
            _four_factors_row(),
            _four_factors_row(opp_free_throw_attempt_rate=0.31),
        ]
    elif source == "hustle":
        kwargs["hustle_rows"] = [_hustle_row(), _hustle_row(deflections=11.0)]
    else:
        kwargs["game_rows"] = [_game_row(), _game_row(season_type="Playoffs")]

    with pytest.raises(duckdb.Error, match=message):
        _run(_staging(**kwargs))


@pytest.mark.parametrize(
    ("source", "updates", "message"),
    [
        ("advanced", {"game_id": None}, "advanced defense source has invalid game_id"),
        ("advanced", {"game_id": ""}, "advanced defense source has invalid game_id"),
        ("advanced", {"team_id": None}, "advanced defense source has invalid team_id"),
        ("advanced", {"team_id": 0}, "advanced defense source has invalid team_id"),
        ("four_factors", {"game_id": None}, "four-factors defense source has invalid game_id"),
        ("four_factors", {"team_id": -1}, "four-factors defense source has invalid team_id"),
        ("hustle", {"game_id": "   "}, "hustle defense source has invalid game_id"),
        ("hustle", {"team_id": None}, "hustle defense source has invalid team_id"),
        ("game", {"game_id": None}, "defense game dimension has invalid game_id"),
        ("game", {"season_year": ""}, "defense game dimension has invalid season_year"),
        ("game", {"season_type": None}, "defense game dimension has invalid season_type"),
    ],
)
def test_invalid_source_identities_fail_closed(
    source: str,
    updates: dict[str, object],
    message: str,
) -> None:
    kwargs: dict[str, list[dict[str, object]]] = {}
    if source == "advanced":
        kwargs["advanced_rows"] = [_advanced_row(**updates)]
    elif source == "four_factors":
        kwargs["four_factors_rows"] = [_four_factors_row(**updates)]
    elif source == "hustle":
        kwargs["hustle_rows"] = [_hustle_row(**updates)]
    else:
        kwargs["game_rows"] = [_game_row(**updates)]

    with pytest.raises(duckdb.Error, match=message):
        _run(_staging(**kwargs))


def test_advanced_base_key_without_dimension_fails_closed() -> None:
    with pytest.raises(duckdb.Error, match="missing dim_game"):
        _run(_staging(game_rows=[]))


@pytest.mark.parametrize(
    ("source", "message"),
    [
        ("four_factors", "orphan four-factors defense game-team key"),
        ("hustle", "orphan hustle defense game-team key"),
    ],
)
def test_optional_orphan_game_team_keys_fail_closed(source: str, message: str) -> None:
    kwargs: dict[str, list[dict[str, object]]] = {
        "four_factors_rows": [],
        "hustle_rows": [],
        "game_rows": [_game_row(game_id="001"), _game_row(game_id="999")],
    }
    if source == "four_factors":
        kwargs["four_factors_rows"] = [_four_factors_row(game_id="999")]
    else:
        kwargs["hustle_rows"] = [_hustle_row(game_id="999")]

    with pytest.raises(duckdb.Error, match=message):
        _run(_staging(**kwargs))


def test_schema_rejects_coverage_count_above_its_denominator() -> None:
    result = _run(_staging())
    invalid = result.with_columns(
        pl.lit(2, dtype=pl.Int64).alias("contested_shots_coverage_game_count")
    )

    with pytest.raises(SchemaError, match="coverage_counts_do_not_exceed_denominators"):
        AggTeamDefenseSchema.validate(invalid)


def test_output_order_is_deterministic_by_exact_public_key() -> None:
    second_team = 1610612747
    result = _run(
        _staging(
            advanced_rows=[
                _advanced_row(game_id="002", team_id=second_team),
                _advanced_row(game_id="001", team_id=_TEAM_ID),
            ],
            four_factors_rows=[],
            hustle_rows=[],
            game_rows=[_game_row(game_id="002"), _game_row(game_id="001")],
        )
    )

    assert result.select("team_id", "season_year", "season_type").to_dicts() == [
        {
            "team_id": _TEAM_ID,
            "season_year": "2024-25",
            "season_type": "Regular Season",
        },
        {
            "team_id": second_team,
            "season_year": "2024-25",
            "season_type": "Regular Season",
        },
    ]
