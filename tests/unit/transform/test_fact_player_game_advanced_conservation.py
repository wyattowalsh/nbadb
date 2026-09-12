from __future__ import annotations

import duckdb
import pandera.errors
import polars as pl
import pytest

from nbadb.schemas.star.fact_player_game_advanced import FactPlayerGameAdvancedSchema
from nbadb.transform.facts.fact_player_game_advanced import (
    FactPlayerGameAdvancedTransformer,
)


def _advanced_rows(**overrides: object) -> pl.DataFrame:
    payload: dict[str, object] = {
        "game_id": ["G1"],
        "player_id": [101],
        "team_id": [1],
        "min": ["PT30M30.00S"],
        "off_rating": [111.0],
        "def_rating": [104.0],
        "net_rating": [7.0],
        "ast_pct": [0.24],
        "ast_tov": [2.5],
        "ast_ratio": [18.0],
        "oreb_pct": [0.04],
        "dreb_pct": [0.19],
        "reb_pct": [0.12],
        "tov_pct": [0.09],
        "efg_pct": [0.58],
        "ts_pct": [0.61],
        "usg_pct": [0.28],
        "pace": [99.0],
        "pace_per40": [82.5],
        "poss": [51.0],
        "pie": [0.14],
        "e_off_rating": [112.0],
        "e_def_rating": [103.0],
        "e_net_rating": [9.0],
        "e_usg_pct": [0.29],
        "e_pace": [100.0],
    }
    payload.update(overrides)
    return pl.DataFrame(payload)


def _games(**overrides: object) -> pl.DataFrame:
    payload: dict[str, object] = {
        "game_id": ["G1"],
        "season_year": ["2024-25"],
    }
    payload.update(overrides)
    return pl.DataFrame(payload)


def _run(advanced: pl.DataFrame, games: pl.DataFrame) -> pl.DataFrame:
    conn = duckdb.connect()
    try:
        conn.register("stg_box_score_advanced", advanced)
        conn.register("dim_game", games)
        transformer = FactPlayerGameAdvancedTransformer()
        transformer._conn = conn
        return transformer.transform({})
    finally:
        conn.close()


def test_preserves_complete_provider_advanced_metric_surface() -> None:
    result = _run(_advanced_rows(), _games())

    assert result.shape == (1, 27)
    row = result.row(0, named=True)
    assert row["min"] == pytest.approx(30.5)
    assert row["season_year"] == "2024-25"
    assert row["ast_tov"] == pytest.approx(2.5)
    assert row["tov_pct"] == pytest.approx(0.09)
    assert row["pace_per40"] == pytest.approx(82.5)
    assert row["e_net_rating"] == pytest.approx(9.0)
    validated = FactPlayerGameAdvancedSchema.validate(result)
    assert validated.columns == result.columns


@pytest.mark.parametrize(
    ("provider_min", "expected"),
    [("30:30", 30.5), ("30.5", 30.5), ("unavailable", None)],
)
def test_minutes_parse_without_silent_numeric_truncation(
    provider_min: str,
    expected: float | None,
) -> None:
    result = _run(_advanced_rows(min=[provider_min]), _games())
    actual = result["min"][0]
    if expected is None:
        assert actual is None
    else:
        assert actual == pytest.approx(expected)


def test_exact_duplicate_provider_rows_are_idempotent() -> None:
    row = _advanced_rows()
    result = _run(pl.concat([row, row]), _games())
    assert result.shape[0] == 1


def test_conflicting_provider_rows_fail_closed() -> None:
    conflict = _advanced_rows(off_rating=[999.0])
    with pytest.raises(duckdb.InvalidInputException, match="conflicting player-game"):
        _run(pl.concat([_advanced_rows(), conflict]), _games())


def test_conflicting_game_dimension_rows_fail_closed() -> None:
    games = pl.concat([_games(), _games(season_year=["2023-24"])])
    with pytest.raises(duckdb.InvalidInputException, match="conflicting game-dimension"):
        _run(_advanced_rows(), games)


def test_schema_rejects_negative_provider_possessions() -> None:
    result = _run(_advanced_rows(poss=[-1.0]), _games())
    with pytest.raises(pandera.errors.SchemaError):
        FactPlayerGameAdvancedSchema.validate(result)
