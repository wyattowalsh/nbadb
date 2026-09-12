"""Weighting and authority semantics for team-season pace and efficiency."""

from __future__ import annotations

from typing import Any

import duckdb
import polars as pl
import pytest

from nbadb.schemas.star.agg_schemas import AggTeamPaceAndEfficiencySchema
from nbadb.transform.derived.agg_team_pace_and_efficiency import (
    AggTeamPaceAndEfficiencyTransformer,
)

_FACT_SCHEMA = {
    "game_id": pl.String,
    "team_id": pl.Int64,
    "min": pl.String,
    "pace": pl.Float64,
    "poss": pl.Float64,
    "off_rating": pl.Float64,
    "def_rating": pl.Float64,
    "net_rating": pl.Float64,
}

_GAME_SCHEMA = {
    "game_id": pl.String,
    "season_year": pl.String,
    "season_type": pl.String,
}


def _facts(rows: list[dict[str, Any]]) -> pl.DataFrame:
    defaults: dict[str, Any] = {
        "team_id": 1610612738,
        "min": "240:00",
        "pace": 100.0,
        "poss": 100.0,
        "off_rating": 110.0,
        "def_rating": 108.0,
        "net_rating": 2.0,
    }
    return pl.DataFrame([{**defaults, **row} for row in rows], schema=_FACT_SCHEMA)


def _games(rows: list[dict[str, Any]]) -> pl.DataFrame:
    defaults = {
        "season_year": "2024-25",
        "season_type": "Regular Season",
    }
    return pl.DataFrame([{**defaults, **row} for row in rows], schema=_GAME_SCHEMA)


def _run(facts: pl.DataFrame, games: pl.DataFrame) -> pl.DataFrame:
    conn = duckdb.connect()
    try:
        conn.register("fact_box_score_advanced_team", facts)
        conn.register("dim_game", games)
        transformer = AggTeamPaceAndEfficiencyTransformer()
        transformer._conn = conn
        return transformer.transform({})
    finally:
        conn.close()


def test_ratings_are_possession_weighted_and_pace_uses_overtime_exposure() -> None:
    facts = _facts(
        [
            {
                "game_id": "0022400001",
                "min": "240:00",
                "pace": 90.0,
                "poss": 90.0,
                "off_rating": 100.0,
                "def_rating": 110.0,
                "net_rating": 999.0,
            },
            {
                "game_id": "0022400002",
                "min": "265:00",
                "pace": 110.0 * 240.0 / 265.0,
                "poss": 110.0,
                "off_rating": 130.0,
                "def_rating": 100.0,
                "net_rating": -999.0,
            },
        ]
    )
    games = _games([{"game_id": "0022400001"}, {"game_id": "0022400002"}])

    row = _run(facts, games).row(0, named=True)

    assert row["gp"] == 2
    assert row["total_possessions"] == 200.0
    assert row["rating_covered_games"] == 2
    assert row["rating_possessions"] == 200.0
    assert row["pace_actual_minutes_games"] == 2
    assert row["pace_inferred_minutes_games"] == 0
    assert row["pace_covered_minutes"] == 101.0
    assert row["avg_pace"] == pytest.approx(240.0 * 200.0 / (240.0 + 265.0))
    assert row["avg_pace"] != pytest.approx(facts["pace"].mean())
    assert row["avg_ortg"] == 116.5
    assert row["avg_ortg"] != pytest.approx(facts["off_rating"].mean())
    assert row["avg_drtg"] == 104.5
    assert row["avg_drtg"] != pytest.approx(facts["def_rating"].mean())
    assert row["avg_net_rtg"] == 12.0
    assert row["avg_net_rtg"] != pytest.approx(facts["net_rating"].mean())


def test_pace_prefers_parsed_minutes_then_infers_missing_exposure() -> None:
    facts = _facts(
        [
            {
                "game_id": "0022400101",
                "min": "240",
                "pace": 999.0,
                "poss": 80.0,
            },
            {
                "game_id": "0022400102",
                "min": "unavailable",
                "pace": 96.0,
                "poss": 120.0,
            },
        ]
    )
    games = _games([{"game_id": "0022400101"}, {"game_id": "0022400102"}])

    row = _run(facts, games).row(0, named=True)

    assert row["pace_covered_games"] == 2
    assert row["pace_actual_minutes_games"] == 1
    assert row["pace_inferred_minutes_games"] == 1
    assert row["pace_covered_minutes"] == 108.0
    assert row["avg_pace"] == pytest.approx(48.0 * 200.0 / 108.0)
    assert row["avg_pace"] != pytest.approx(facts["pace"].mean())


def test_null_and_partial_rows_report_honest_coverage() -> None:
    facts = _facts(
        [
            {
                "game_id": "0022400201",
                "poss": 90.0,
                "off_rating": 100.0,
                "def_rating": 110.0,
            },
            {
                "game_id": "0022400202",
                "min": "265:00",
                "poss": 110.0,
                "off_rating": 130.0,
                "def_rating": None,
            },
            {
                "game_id": "0022400203",
                "poss": None,
                "off_rating": 140.0,
                "def_rating": 90.0,
            },
        ]
    )
    games = _games(
        [
            {"game_id": "0022400201"},
            {"game_id": "0022400202"},
            {"game_id": "0022400203"},
        ]
    )

    row = _run(facts, games).row(0, named=True)

    assert row["gp"] == 3
    assert row["total_possessions"] == 200.0
    assert row["rating_covered_games"] == 1
    assert row["rating_possessions"] == 90.0
    assert row["avg_ortg"] == 100.0
    assert row["avg_drtg"] == 110.0
    assert row["avg_net_rtg"] == -10.0
    assert row["pace_covered_games"] == 2
    assert row["pace_covered_minutes"] == 101.0


def test_team_season_and_season_type_are_independent_partitions() -> None:
    facts = _facts(
        [
            {"game_id": "regular-a", "team_id": 1},
            {"game_id": "playoff-a", "team_id": 1},
            {"game_id": "next-season-a", "team_id": 1},
            {"game_id": "regular-b", "team_id": 2},
        ]
    )
    games = _games(
        [
            {"game_id": "regular-a"},
            {"game_id": "playoff-a", "season_type": "Playoffs"},
            {"game_id": "next-season-a", "season_year": "2025-26"},
            {"game_id": "regular-b"},
        ]
    )

    result = _run(facts, games).sort(["team_id", "season_year", "season_type"])

    assert result.shape[0] == 4
    assert result["gp"].to_list() == [1, 1, 1, 1]
    assert set(result.select("team_id", "season_year", "season_type").iter_rows()) == {
        (1, "2024-25", "Regular Season"),
        (1, "2024-25", "Playoffs"),
        (1, "2025-26", "Regular Season"),
        (2, "2024-25", "Regular Season"),
    }


def test_exact_fact_and_dimension_duplicates_are_idempotent_and_schema_valid() -> None:
    facts = _facts(
        [
            {"game_id": "0022400301", "poss": 95.0},
            {"game_id": "0022400302", "poss": 105.0},
        ]
    )
    games = _games([{"game_id": "0022400301"}, {"game_id": "0022400302"}])

    result = _run(pl.concat([facts, facts]), pl.concat([games, games]))

    assert result.shape == (1, 15)
    assert result["gp"].item() == 2
    validated = AggTeamPaceAndEfficiencySchema.validate(result)
    assert isinstance(validated, pl.DataFrame)


def test_conflicting_team_game_rows_fail_closed() -> None:
    facts = _facts([{"game_id": "0022400401"}])
    # Provider net rating is not used in the output, but a disagreement still
    # means these are not exact source duplicates.
    conflict = facts.with_columns((pl.col("net_rating") + 1.0).alias("net_rating"))

    with pytest.raises(
        duckdb.InvalidInputException,
        match="conflicting team-game rows",
    ):
        _run(
            pl.concat([facts, conflict]),
            _games([{"game_id": "0022400401"}]),
        )


def test_conflicting_game_dimension_rows_fail_closed() -> None:
    facts = _facts([{"game_id": "0022400501"}])
    games = _games([{"game_id": "0022400501"}])
    conflict = games.with_columns(pl.lit("Playoffs").alias("season_type"))

    with pytest.raises(
        duckdb.InvalidInputException,
        match="conflicting game-dimension rows",
    ):
        _run(facts, pl.concat([games, conflict]))
