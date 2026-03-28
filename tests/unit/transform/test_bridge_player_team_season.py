from __future__ import annotations

import duckdb
import polars as pl

from nbadb.transform.facts.bridge_player_team_season import (
    BridgePlayerTeamSeasonTransformer,
)
from nbadb.transform.pipeline import _star_schema_map


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


class TestBridgePlayerTeamSeason:
    def test_class_attrs(self) -> None:
        t = BridgePlayerTeamSeasonTransformer
        assert t.output_table == "bridge_player_team_season"
        assert t.depends_on == ["stg_player_info"]

    def test_two_team_seasons(self) -> None:
        staging = {
            "stg_player_info": pl.DataFrame(
                {
                    "player_id": [101, 101],
                    "team_id": [1610612737, 1610612738],
                    "season": ["2023-24", "2024-25"],
                    "jersey_number": ["23", "7"],
                    "position": ["Guard", "Guard"],
                    "full_name": ["Test Player", "Test Player"],
                    "first_name": ["Test", "Test"],
                    "last_name": ["Player", "Player"],
                    "roster_status": ["Active", "Active"],
                    "height": ["6-3", "6-3"],
                    "weight": ["195", "195"],
                    "birth_date": ["1995-01-01", "1995-01-01"],
                    "country": ["USA", "USA"],
                    "draft_year": ["2017", "2017"],
                    "draft_round": ["1", "1"],
                    "draft_number": ["10", "10"],
                    "college_id": [None, None],
                    "from_year": [2017, 2017],
                    "to_year": [2025, 2025],
                }
            ).lazy(),
        }

        result = _run(BridgePlayerTeamSeasonTransformer(), staging)

        assert result.shape[0] == 2
        assert set(result["team_id"].to_list()) == {1610612737, 1610612738}
        assert set(result["season_year"].to_list()) == {"2023-24", "2024-25"}
        _assert_schema_valid("bridge_player_team_season", result)

    def test_nulls_filtered_out(self) -> None:
        staging = {
            "stg_player_info": pl.DataFrame(
                {
                    "player_id": [101, None],
                    "team_id": [1610612737, 1610612738],
                    "season": ["2023-24", "2024-25"],
                    "jersey_number": ["23", "7"],
                    "position": ["Guard", "Guard"],
                    "full_name": ["Test", "Test"],
                    "first_name": ["T", "T"],
                    "last_name": ["P", "P"],
                    "roster_status": ["Active", "Active"],
                    "height": ["6-3", "6-3"],
                    "weight": ["195", "195"],
                    "birth_date": ["1995-01-01", "1995-01-01"],
                    "country": ["USA", "USA"],
                    "draft_year": ["2017", "2017"],
                    "draft_round": ["1", "1"],
                    "draft_number": ["10", "10"],
                    "college_id": [None, None],
                    "from_year": [2017, 2017],
                    "to_year": [2025, 2025],
                }
            ).lazy(),
        }

        result = _run(BridgePlayerTeamSeasonTransformer(), staging)

        assert result.shape[0] == 1
        assert result["player_id"].to_list() == [101]


def test_schema_is_discovered() -> None:
    assert "bridge_player_team_season" in _star_schema_map()
