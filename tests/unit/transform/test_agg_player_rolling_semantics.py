"""Past-only and partition semantics for ``agg_player_rolling``."""

from __future__ import annotations

import duckdb
import polars as pl
import pytest

from nbadb.schemas.star.agg_schemas import AggPlayerRollingSchema
from nbadb.transform.derived.agg_player_rolling import AggPlayerRollingTransformer


def _run(facts: pl.DataFrame, games: pl.DataFrame) -> pl.DataFrame:
    conn = duckdb.connect()
    try:
        conn.register("fact_player_game_traditional", facts)
        conn.register("dim_game", games)
        transformer = AggPlayerRollingTransformer()
        transformer._conn = conn
        return transformer.transform({})
    finally:
        conn.close()


def _facts(
    game_ids: list[str],
    *,
    points: list[int],
    team_ids: list[int] | None = None,
    season_years: list[str] | None = None,
) -> pl.DataFrame:
    row_count = len(game_ids)
    return pl.DataFrame(
        {
            "game_id": game_ids,
            "player_id": [2544] * row_count,
            "team_id": team_ids or [1610612747] * row_count,
            "season_year": season_years or ["2024-25"] * row_count,
            "pts": points,
            "reb": [value // 2 for value in points],
            "ast": [value // 5 for value in points],
        }
    )


def _games(
    game_ids: list[str],
    *,
    dates: list[str] | None = None,
    season_years: list[str] | None = None,
    season_types: list[str] | None = None,
) -> pl.DataFrame:
    row_count = len(game_ids)
    return pl.DataFrame(
        {
            "game_id": game_ids,
            "game_date": dates or [f"2024-11-{index + 1:02d}" for index in range(row_count)],
            "season_year": season_years or ["2024-25"] * row_count,
            "season_type": season_types or ["Regular Season"] * row_count,
        }
    )


def test_windows_use_only_strictly_prior_games_and_allow_short_history() -> None:
    game_ids = [f"002240000{index}" for index in range(1, 7)]
    result = _run(
        _facts(game_ids, points=[10, 20, 30, 40, 50, 600]),
        _games(game_ids),
    ).sort(["game_date", "game_id"])

    first = result.row(0, named=True)
    assert first["pts_roll5"] is None
    assert first["pts_roll10"] is None
    assert first["pts_roll20"] is None

    second = result.row(1, named=True)
    assert second["pts_roll5"] == 10.0
    assert second["reb_roll5"] == 5.0
    assert second["ast_roll5"] == 2.0

    sixth = result.row(5, named=True)
    assert sixth["pts_roll5"] == 30.0
    assert sixth["pts_roll10"] == 30.0
    assert sixth["pts_roll20"] == 30.0
    assert 600.0 not in [sixth["pts_roll5"], sixth["pts_roll10"], sixth["pts_roll20"]]

    validated = AggPlayerRollingSchema.validate(result)
    assert isinstance(validated, pl.DataFrame)


def test_same_date_games_are_ordered_by_game_id_not_input_order() -> None:
    input_ids = ["0022400003", "0022400001", "0022400002"]
    facts = _facts(input_ids, points=[30, 10, 20])
    games = _games(
        input_ids,
        dates=["2024-11-01", "2024-11-01", "2024-11-01"],
    )

    by_game = {row["game_id"]: row for row in _run(facts, games).iter_rows(named=True)}

    assert by_game["0022400001"]["pts_roll5"] is None
    assert by_game["0022400002"]["pts_roll5"] == 10.0
    assert by_game["0022400003"]["pts_roll5"] == 15.0


def test_team_season_and_season_type_changes_reset_history() -> None:
    game_ids = [f"00-context-{index}" for index in range(1, 7)]
    facts = _facts(
        game_ids,
        points=[10, 20, 30, 40, 50, 60],
        team_ids=[1, 1, 1, 2, 2, 2],
        season_years=["2023-24", "2023-24", "2024-25", "2024-25", "2024-25", "2024-25"],
    )
    games = _games(
        game_ids,
        season_years=["2023-24", "2023-24", "2024-25", "2024-25", "2024-25", "2024-25"],
        season_types=[
            "Regular Season",
            "Regular Season",
            "Regular Season",
            "Regular Season",
            "Playoffs",
            "Playoffs",
        ],
    )

    by_game = {row["game_id"]: row for row in _run(facts, games).iter_rows(named=True)}

    assert by_game["00-context-2"]["pts_roll5"] == 10.0
    assert by_game["00-context-3"]["pts_roll5"] is None  # new season
    assert by_game["00-context-4"]["pts_roll5"] is None  # new team
    assert by_game["00-context-5"]["pts_roll5"] is None  # new season type
    assert by_game["00-context-6"]["pts_roll5"] == 50.0


def test_exact_duplicate_game_rows_do_not_change_windows() -> None:
    game_ids = ["0022400101", "0022400102"]
    facts = _facts(game_ids, points=[10, 20])
    games = _games(game_ids)

    result = _run(
        pl.concat([facts, facts]),
        pl.concat([games, games]),
    ).sort(["game_date", "game_id"])

    assert result.shape[0] == 2
    assert result["pts_roll5"].to_list() == [None, 10.0]


def test_conflicting_player_game_rows_fail_closed() -> None:
    game_ids = ["0022400201", "0022400202"]
    facts = _facts(game_ids, points=[10, 20])
    conflict = facts.head(1).with_columns((pl.col("pts") + 1).alias("pts"))

    with pytest.raises(
        duckdb.InvalidInputException,
        match="conflicting player-game rows",
    ):
        _run(pl.concat([facts, conflict]), _games(game_ids))


def test_conflicting_game_dimension_rows_fail_closed() -> None:
    game_ids = ["0022400301", "0022400302"]
    games = _games(game_ids)
    conflict = games.head(1).with_columns(pl.lit("2024-12-31").alias("game_date"))

    with pytest.raises(
        duckdb.InvalidInputException,
        match="conflicting game-dimension rows",
    ):
        _run(_facts(game_ids, points=[10, 20]), pl.concat([games, conflict]))


def test_fact_and_dimension_season_mismatch_fails_closed() -> None:
    game_ids = ["0022400401"]
    facts = _facts(game_ids, points=[10], season_years=["2023-24"])
    games = _games(game_ids, season_years=["2024-25"])

    with pytest.raises(
        duckdb.InvalidInputException,
        match="fact and game-dimension seasons disagree",
    ):
        _run(facts, games)
