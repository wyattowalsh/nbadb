from __future__ import annotations

import duckdb
import polars as pl

from nbadb.transform.facts.fact_team_game_log import FactTeamGameLogTransformer
from nbadb.transform.pipeline import _star_schema_map


def _frame(values: dict[str, object]) -> pl.DataFrame:
    return pl.DataFrame({key: [value] for key, value in values.items()})


def _run(transformer, staging: dict[str, pl.LazyFrame]) -> pl.DataFrame:
    conn = duckdb.connect()
    try:
        for key, val in staging.items():
            conn.register(key, val.collect())
        transformer._conn = conn
        return transformer.transform(staging)
    finally:
        conn.close()


def _assert_schema_valid(table: str, df: pl.DataFrame) -> None:
    schema_cls = _star_schema_map()[table]
    validated = schema_cls.validate(df)
    assert isinstance(validated, pl.DataFrame)


def _team_game_log_row() -> dict[str, object]:
    return {
        "season_id": "22024",
        "team_id": 1610612738,
        "team_abbreviation": "BOS",
        "team_name": "Boston Celtics",
        "game_id": "0022400001",
        "game_date": "2024-10-22",
        "matchup": "BOS vs. NYK",
        "wl": "W",
        "w": 1,
        "l": 0,
        "w_pct": 1.0,
        "min": 240.0,
        "fgm": 43.0,
        "fga": 88.0,
        "fg_pct": 0.489,
        "fg3m": 14.0,
        "fg3a": 39.0,
        "fg3_pct": 0.359,
        "ftm": 20.0,
        "fta": 24.0,
        "ft_pct": 0.833,
        "oreb": 10.0,
        "dreb": 34.0,
        "reb": 44.0,
        "ast": 28.0,
        "stl": 7.0,
        "blk": 5.0,
        "tov": 11.0,
        "pf": 18.0,
        "pts": 120.0,
        "plus_minus": 12.0,
        "video_available": 1,
    }


def test_team_game_log_schema_validates_transform_output() -> None:
    row = _team_game_log_row()
    staging = {
        "stg_team_game_logs_v2": _frame(row).lazy(),
        "stg_team_game_log": _frame(row).lazy(),
    }

    result = _run(FactTeamGameLogTransformer(), staging)

    assert result.shape == (1, len(row))
    _assert_schema_valid("fact_team_game_log", result)


def test_team_game_log_schema_is_discovered_without_init_exports() -> None:
    assert "fact_team_game_log" in _star_schema_map()
