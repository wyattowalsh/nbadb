from __future__ import annotations

import polars as pl

from nbadb.transform.dimensions.dim_game import DimGameTransformer


class TestDimGameTransformer:
    def test_class_attributes(self) -> None:
        assert DimGameTransformer.output_table == "dim_game"
        assert "stg_league_game_log" in DimGameTransformer.depends_on
        assert "stg_schedule" in DimGameTransformer.depends_on

    def test_basic_transform(self) -> None:
        game_log = pl.DataFrame(
            {
                "game_id": ["0022400001", "0022400002"],
                "game_date": ["2024-10-22", "2024-10-23"],
                "season_year": ["2024-25", "2024-25"],
                "season_type": ["Regular Season", "Regular Season"],
                "home_team_id": [1610612747, 1610612738],
                "visitor_team_id": [1610612750, 1610612752],
                "matchup": ["LAL vs. MIN", "BOS vs. NYK"],
            }
        )
        schedule = pl.DataFrame(
            {
                "game_id": ["0022400001", "0022400002"],
                "arena_name": ["Crypto.com Arena", "TD Garden"],
                "arena_city": ["Los Angeles", "Boston"],
            }
        )
        t = DimGameTransformer()
        result = t.transform(
            {
                "stg_league_game_log": game_log.lazy(),
                "stg_schedule": schedule.lazy(),
            }
        )
        assert result.shape[0] == 2
        assert "game_id" in result.columns
        assert "arena_name" in result.columns
        assert "arena_city" in result.columns

    def test_deduplicates_by_game_id(self) -> None:
        game_log = pl.DataFrame(
            {
                "game_id": ["001", "001"],
                "game_date": ["2024-10-22", "2024-10-22"],
                "season_year": ["2024-25", "2024-25"],
                "season_type": ["Regular Season", "Regular Season"],
                "home_team_id": [10, 10],
                "visitor_team_id": [20, 20],
                "matchup": ["A vs B", "A vs B"],
            }
        )
        schedule = pl.DataFrame(
            {
                "game_id": ["001"],
                "arena_name": ["Arena A"],
                "arena_city": ["City A"],
            }
        )
        t = DimGameTransformer()
        result = t.transform(
            {
                "stg_league_game_log": game_log.lazy(),
                "stg_schedule": schedule.lazy(),
            }
        )
        assert result.shape[0] == 1

    def test_left_join_preserves_games_without_schedule(self) -> None:
        game_log = pl.DataFrame(
            {
                "game_id": ["001", "002"],
                "game_date": ["2024-10-22", "2024-10-23"],
                "season_year": ["2024-25", "2024-25"],
                "season_type": ["Regular Season", "Regular Season"],
                "home_team_id": [10, 20],
                "visitor_team_id": [30, 40],
                "matchup": ["A vs B", "C vs D"],
            }
        )
        schedule = pl.DataFrame(
            {
                "game_id": ["001"],
                "arena_name": ["Arena A"],
                "arena_city": ["City A"],
            }
        )
        t = DimGameTransformer()
        result = t.transform(
            {
                "stg_league_game_log": game_log.lazy(),
                "stg_schedule": schedule.lazy(),
            }
        )
        assert result.shape[0] == 2
        game_002 = result.filter(pl.col("game_id") == "002")
        assert game_002["arena_name"][0] is None

    def test_output_sorted_by_date(self) -> None:
        game_log = pl.DataFrame(
            {
                "game_id": ["002", "001"],
                "game_date": ["2024-10-23", "2024-10-22"],
                "season_year": ["2024-25", "2024-25"],
                "season_type": ["Regular Season", "Regular Season"],
                "home_team_id": [20, 10],
                "visitor_team_id": [40, 30],
                "matchup": ["C vs D", "A vs B"],
            }
        )
        schedule = pl.DataFrame(
            {
                "game_id": ["001", "002"],
                "arena_name": ["Arena A", "Arena B"],
                "arena_city": ["City A", "City B"],
            }
        )
        t = DimGameTransformer()
        result = t.transform(
            {
                "stg_league_game_log": game_log.lazy(),
                "stg_schedule": schedule.lazy(),
            }
        )
        assert result["game_id"].to_list() == ["001", "002"]

    def test_immutable_fields_only(self) -> None:
        game_log = pl.DataFrame(
            {
                "game_id": ["001"],
                "game_date": ["2024-10-22"],
                "season_year": ["2024-25"],
                "season_type": ["Regular Season"],
                "home_team_id": [10],
                "visitor_team_id": [20],
                "matchup": ["A vs B"],
            }
        )
        schedule = pl.DataFrame(
            {
                "game_id": ["001"],
                "arena_name": ["Arena A"],
                "arena_city": ["City A"],
            }
        )
        t = DimGameTransformer()
        result = t.transform(
            {
                "stg_league_game_log": game_log.lazy(),
                "stg_schedule": schedule.lazy(),
            }
        )
        expected_cols = {
            "game_id",
            "game_date",
            "season_year",
            "season_type",
            "home_team_id",
            "visitor_team_id",
            "matchup",
            "arena_name",
            "arena_city",
        }
        assert set(result.columns) == expected_cols
