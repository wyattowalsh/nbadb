from __future__ import annotations

import polars as pl

from nbadb.transform.facts.bridge_lineup_player import BridgeLineupPlayerTransformer


class TestBridgeLineupPlayer:
    def test_class_attrs(self) -> None:
        assert BridgeLineupPlayerTransformer.output_table == "bridge_lineup_player"
        assert BridgeLineupPlayerTransformer.depends_on == [
            "stg_lineup",
            "stg_team_lineups",
        ]

    def test_explodes_both_sources(self) -> None:
        staging = {
            "stg_lineup": pl.DataFrame(
                {
                    "group_id": ["101-102-103-104-105"],
                    "team_id": [1],
                    "season_year": ["2024-25"],
                }
            ).lazy(),
            "stg_team_lineups": pl.DataFrame(
                {
                    "group_id": ["201-202-203-204-205"],
                    "team_id": [2],
                    "season_year": ["2024-25"],
                }
            ).lazy(),
        }

        t = BridgeLineupPlayerTransformer()
        result = t.transform(staging)

        # 5 players x 2 lineups = 10 rows
        assert result.shape[0] == 10

    def test_position_in_lineup_range(self) -> None:
        staging = {
            "stg_lineup": pl.DataFrame(
                {
                    "group_id": ["101-102-103-104-105"],
                    "team_id": [1],
                    "season_year": ["2024-25"],
                }
            ).lazy(),
            "stg_team_lineups": pl.DataFrame(
                {
                    "group_id": ["201-202-203-204-205"],
                    "team_id": [2],
                    "season_year": ["2024-25"],
                }
            ).lazy(),
        }

        t = BridgeLineupPlayerTransformer()
        result = t.transform(staging)

        # Each lineup should have positions 1-5
        for gid in ["101-102-103-104-105", "201-202-203-204-205"]:
            lineup = result.filter(pl.col("group_id") == gid)
            positions = sorted(lineup["position_in_lineup"].to_list())
            assert positions == [1, 2, 3, 4, 5]

    def test_player_ids_parsed_correctly(self) -> None:
        staging = {
            "stg_lineup": pl.DataFrame(
                {
                    "group_id": ["101-102-103-104-105"],
                    "team_id": [1],
                    "season_year": ["2024-25"],
                }
            ).lazy(),
            "stg_team_lineups": pl.DataFrame(
                {
                    "group_id": ["201-202-203-204-205"],
                    "team_id": [2],
                    "season_year": ["2024-25"],
                }
            ).lazy(),
        }

        t = BridgeLineupPlayerTransformer()
        result = t.transform(staging)

        lineup1 = result.filter(pl.col("group_id") == "101-102-103-104-105")
        assert sorted(lineup1["player_id"].to_list()) == [101, 102, 103, 104, 105]
        assert lineup1["team_id"].unique().to_list() == [1]

        lineup2 = result.filter(pl.col("group_id") == "201-202-203-204-205")
        assert sorted(lineup2["player_id"].to_list()) == [201, 202, 203, 204, 205]
        assert lineup2["team_id"].unique().to_list() == [2]

    def test_deduplicates_across_sources(self) -> None:
        """Same group_id in both sources should not produce duplicates."""
        staging = {
            "stg_lineup": pl.DataFrame(
                {
                    "group_id": ["101-102-103-104-105"],
                    "team_id": [1],
                    "season_year": ["2024-25"],
                }
            ).lazy(),
            "stg_team_lineups": pl.DataFrame(
                {
                    "group_id": ["101-102-103-104-105"],
                    "team_id": [1],
                    "season_year": ["2024-25"],
                }
            ).lazy(),
        }

        t = BridgeLineupPlayerTransformer()
        result = t.transform(staging)

        assert result.shape[0] == 5

    def test_empty_sources_returns_empty(self) -> None:
        t = BridgeLineupPlayerTransformer()
        result = t.transform({})

        assert result.shape[0] == 0
        assert result.columns == [
            "group_id",
            "player_id",
            "team_id",
            "position_in_lineup",
            "season_year",
        ]

    def test_single_source_missing(self) -> None:
        staging = {
            "stg_lineup": pl.DataFrame(
                {
                    "group_id": ["101-102-103-104-105"],
                    "team_id": [1],
                    "season_year": ["2024-25"],
                }
            ).lazy(),
        }

        t = BridgeLineupPlayerTransformer()
        result = t.transform(staging)

        assert result.shape[0] == 5
        assert sorted(result["player_id"].to_list()) == [101, 102, 103, 104, 105]

    def test_same_group_id_across_seasons_not_dropped(self) -> None:
        """Regression: same group_id in different seasons must produce rows for each season."""
        staging = {
            "stg_lineup": pl.DataFrame(
                {
                    "group_id": [
                        "101-102-103-104-105",
                        "101-102-103-104-105",
                    ],
                    "team_id": [1, 1],
                    "season_year": ["2023-24", "2024-25"],
                }
            ).lazy(),
        }

        t = BridgeLineupPlayerTransformer()
        result = t.transform(staging)

        # 5 players x 2 seasons = 10 rows, NOT 5
        assert result.shape[0] == 10

        for season in ("2023-24", "2024-25"):
            season_rows = result.filter(pl.col("season_year") == season)
            assert season_rows.shape[0] == 5
            assert sorted(season_rows["player_id"].to_list()) == [101, 102, 103, 104, 105]

    def test_output_sorted(self) -> None:
        staging = {
            "stg_lineup": pl.DataFrame(
                {
                    "group_id": ["301-302-303-304-305", "101-102-103-104-105"],
                    "team_id": [3, 1],
                    "season_year": ["2024-25", "2024-25"],
                }
            ).lazy(),
        }

        t = BridgeLineupPlayerTransformer()
        result = t.transform(staging)

        # Should be sorted by group_id, then position_in_lineup
        assert result["group_id"][0] == "101-102-103-104-105"
        assert result["position_in_lineup"][0] == 1
