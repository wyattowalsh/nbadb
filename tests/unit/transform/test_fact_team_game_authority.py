"""Authority and duplicate-handling tests for ``fact_team_game``."""

from __future__ import annotations

import duckdb
import polars as pl
import pytest

from nbadb.schemas.star.fact_team_game import FactTeamGameSchema
from nbadb.transform.facts.fact_team_game import FactTeamGameTransformer


def _official_team_stats() -> pl.DataFrame:
    return pl.DataFrame(
        {
            "game_id": ["0022400001", "0022400001"],
            "team_id": [1610612737, 1610612738],
            "fgm": [41.0, 39.0],
            "fga": [89.0, 87.0],
            # Deliberately do not derive percentages from the fixture totals.
            "fg_pct": [0.471, 0.452],
            "fg3m": [13.0, 11.0],
            "fg3a": [36.0, 34.0],
            "fg3_pct": [0.371, 0.331],
            "ftm": [19.0, 17.0],
            "fta": [23.0, 21.0],
            "ft_pct": [0.831, 0.819],
            "oreb": [12.0, 9.0],
            "dreb": [31.0, 30.0],
            "reb": [43.0, 39.0],
            "ast": [27.0, 25.0],
            "stl": [8.0, 7.0],
            "blk": [6.0, 5.0],
            "tov": [13.0, 12.0],
            "pf": [18.0, 20.0],
            "pts": [114.0, 106.0],
        }
    )


def _line_score() -> pl.DataFrame:
    return pl.DataFrame(
        {
            "game_id": ["0022400001", "0022400001"],
            "team_id": [1610612737, 1610612738],
            "pts_qtr1": [28, 25],
            "pts_qtr2": [29, 27],
            "pts_qtr3": [30, 26],
            "pts_qtr4": [27, 28],
        }
    )


def _dim_game() -> pl.DataFrame:
    return pl.DataFrame(
        {
            "game_id": ["0022400001"],
            "season_year": ["2024-25"],
        }
    )


def _player_rows_that_disagree() -> pl.DataFrame:
    """Player totals are diagnostic only and intentionally disagree with TeamStats."""
    return pl.DataFrame(
        {
            "game_id": ["0022400001", "0022400001"],
            "player_id": [1, 2],
            "team_id": [1610612737, 1610612738],
            "fgm": [1, 2],
            "fga": [2, 3],
            "fg3m": [0, 1],
            "fg3a": [1, 1],
            "ftm": [0, 0],
            "fta": [0, 0],
            "oreb": [0, 0],
            "dreb": [1, 1],
            "reb": [1, 1],
            "ast": [1, 1],
            "stl": [0, 0],
            "blk": [0, 0],
            "tov": [0, 0],
            "pf": [0, 0],
            "pts": [2, 5],
        }
    )


def _run(
    *,
    team_stats: pl.DataFrame | None = None,
    line_score: pl.DataFrame | None = None,
    dim_game: pl.DataFrame | None = None,
) -> pl.DataFrame:
    conn = duckdb.connect()
    try:
        conn.register(
            "stg_box_score_traditional_team",
            team_stats if team_stats is not None else _official_team_stats(),
        )
        conn.register(
            "stg_box_score_traditional",
            _player_rows_that_disagree(),
        )
        conn.register(
            "stg_line_score",
            line_score if line_score is not None else _line_score(),
        )
        conn.register(
            "dim_game",
            dim_game if dim_game is not None else _dim_game(),
        )
        transformer = FactTeamGameTransformer()
        transformer._conn = conn
        return transformer.transform({})
    finally:
        conn.close()


def test_official_team_stats_are_authoritative() -> None:
    result = _run().sort("team_id")

    assert FactTeamGameTransformer.depends_on == [
        "stg_box_score_traditional_team",
        "stg_line_score",
        "dim_game",
    ]
    assert result["pts"].to_list() == [114.0, 106.0]
    assert result["reb"].to_list() == [43.0, 39.0]
    assert result["fg_pct"].to_list() == [0.471, 0.452]


def test_exact_source_duplicates_are_idempotent_and_schema_valid() -> None:
    result = _run(
        team_stats=pl.concat([_official_team_stats(), _official_team_stats()]),
        line_score=pl.concat([_line_score(), _line_score()]),
    ).sort("team_id")

    assert result.shape == (2, 25)
    validated = FactTeamGameSchema.validate(result)
    assert isinstance(validated, pl.DataFrame)
    assert validated["game_id"].to_list() == ["0022400001", "0022400001"]


def test_conflicting_official_team_rows_fail_closed() -> None:
    conflicting = _official_team_stats().head(1).with_columns(pl.lit(115.0).alias("pts"))

    with pytest.raises(
        duckdb.InvalidInputException,
        match="conflicting official TeamStats rows",
    ):
        _run(team_stats=pl.concat([_official_team_stats(), conflicting]))


def test_conflicting_line_score_rows_fail_closed() -> None:
    conflicting = _line_score().head(1).with_columns((pl.col("pts_qtr1") + 1).alias("pts_qtr1"))

    with pytest.raises(
        duckdb.InvalidInputException,
        match="conflicting LineScore rows",
    ):
        _run(line_score=pl.concat([_line_score(), conflicting]))


def test_missing_dim_game_keeps_rows_with_null_season() -> None:
    result = _run(dim_game=_dim_game().clear())

    assert result.shape[0] == 2
    assert result["season_year"].null_count() == 2
