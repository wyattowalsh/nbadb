from __future__ import annotations

import json
from pathlib import Path

import duckdb
import polars as pl
import pytest

from nbadb.core.config import NbaDbSettings


@pytest.fixture
def tmp_data_dir(tmp_path: Path) -> Path:
    return tmp_path / "data"


@pytest.fixture
def settings(tmp_data_dir: Path) -> NbaDbSettings:
    return NbaDbSettings(
        data_dir=tmp_data_dir,
        log_dir=tmp_data_dir / "logs",
    )


@pytest.fixture
def sample_player_df() -> pl.DataFrame:
    return pl.DataFrame({
        "player_id": [201566, 203507, 1629029],
        "player_name": [
            "Russell Westbrook",
            "Giannis Antetokounmpo",
            "Luka Doncic",
        ],
        "team_id": [1610612743, 1610612749, 1610612742],
        "pts": [18.4, 30.4, 33.9],
    })


@pytest.fixture
def sample_game_df() -> pl.DataFrame:
    return pl.DataFrame({
        "game_id": ["0022400001", "0022400002", "0022400003"],
        "game_date": ["2024-10-22", "2024-10-22", "2024-10-23"],
        "home_team_id": [1610612747, 1610612738, 1610612744],
        "visitor_team_id": [1610612750, 1610612752, 1610612746],
    })


@pytest.fixture
def sample_game_log_df() -> pl.DataFrame:
    return pl.DataFrame({
        "game_id": ["0022400001", "0022400002"],
        "game_date": ["2024-10-22", "2024-10-23"],
        "season_year": ["2024-25", "2024-25"],
        "season_type": ["Regular Season", "Regular Season"],
        "home_team_id": [1610612747, 1610612738],
        "visitor_team_id": [1610612750, 1610612752],
        "matchup": ["LAL vs. MIN", "BOS vs. NYK"],
    })


@pytest.fixture
def sample_box_score_df() -> pl.DataFrame:
    return pl.DataFrame({
        "game_id": ["0022400001", "0022400001"],
        "team_id": [1610612747, 1610612747],
        "player_id": [2544, 203507],
        "start_position": ["F", "F"],
        "min": [36.0, 34.0],
        "fgm": [10, 12],
        "fga": [20, 22],
        "fg_pct": [0.5, 0.545],
        "fg3m": [3, 2],
        "fg3a": [8, 5],
        "fg3_pct": [0.375, 0.4],
        "ftm": [5, 8],
        "fta": [6, 9],
        "ft_pct": [0.833, 0.889],
        "oreb": [1, 3],
        "dreb": [6, 8],
        "reb": [7, 11],
        "ast": [8, 5],
        "stl": [2, 1],
        "blk": [1, 2],
        "tov": [3, 2],
        "pf": [2, 3],
        "pts": [28, 34],
        "plus_minus": [12.0, 8.0],
    })


@pytest.fixture
def mock_duckdb_conn() -> duckdb.DuckDBPyConnection:
    return duckdb.connect()


@pytest.fixture
def fixture_loader() -> callable:
    def _load(name: str) -> dict:
        with open(Path(__file__).parent / "fixtures" / name) as f:
            return json.load(f)
    return _load
