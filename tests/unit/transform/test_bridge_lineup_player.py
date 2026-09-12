from __future__ import annotations

import polars as pl
import pytest

from nbadb.schemas.star.bridge_lineup_player import BridgeLineupPlayerSchema
from nbadb.transform.facts.bridge_lineup_player import BridgeLineupPlayerTransformer


def _lineups(
    group_ids: list[str | None],
    *,
    team_ids: list[int] | None = None,
    seasons: list[str] | None = None,
) -> pl.LazyFrame:
    return pl.DataFrame(
        {
            "group_id": group_ids,
            "team_id": team_ids or [1] * len(group_ids),
            "season_year": seasons or ["2024-25"] * len(group_ids),
        },
        schema={
            "group_id": pl.String,
            "team_id": pl.Int64,
            "season_year": pl.String,
        },
    ).lazy()


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

    def test_same_group_id_across_teams_not_dropped(self) -> None:
        """Regression: same group_id for different teams must produce rows for each team."""
        staging = {
            "stg_lineup": pl.DataFrame(
                {
                    "group_id": [
                        "101-102-103-104-105",
                        "101-102-103-104-105",
                    ],
                    "team_id": [1, 2],
                    "season_year": ["2024-25", "2024-25"],
                }
            ).lazy(),
        }

        t = BridgeLineupPlayerTransformer()
        result = t.transform(staging)

        # 5 players x 2 teams = 10 rows, NOT 5
        assert result.shape[0] == 10

        for tid in (1, 2):
            team_rows = result.filter(pl.col("team_id") == tid)
            assert team_rows.shape[0] == 5
            assert sorted(team_rows["player_id"].to_list()) == [101, 102, 103, 104, 105]

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


def test_admits_one_to_five_players_and_preserves_token_positions() -> None:
    result = BridgeLineupPlayerTransformer().transform(
        {"stg_lineup": _lineups(["101", "203-202-201", "301-302-303-304-305"])}
    )

    assert result.columns == [
        "group_id",
        "player_id",
        "team_id",
        "position_in_lineup",
        "season_year",
    ]
    assert result.height == 9
    middle = result.filter(pl.col("group_id") == "203-202-201").sort("position_in_lineup")
    assert middle["player_id"].to_list() == [203, 202, 201]
    assert middle["position_in_lineup"].to_list() == [1, 2, 3]
    assert BridgeLineupPlayerSchema.validate(result).to_dicts() == result.to_dicts()
    assert list(BridgeLineupPlayerSchema.to_schema().columns) == result.columns


@pytest.mark.parametrize(
    "group_id",
    [
        None,
        "",
        "1-",
        "1--2",
        "1-0",
        "1-two",
        "9223372036854775808",
        "1-2-3-4-5-6",
        "1-2-1",
        "1-01",
    ],
)
def test_invalid_group_fails_before_duplicate_collapse(group_id: str | None) -> None:
    with pytest.raises(ValueError, match="1-5 unique positive Int64"):
        BridgeLineupPlayerTransformer().transform({"stg_lineup": _lineups([group_id, group_id])})


def test_identical_rows_collapse_within_and_across_sources() -> None:
    duplicate = _lineups(["101-102-103", "101-102-103"])

    result = BridgeLineupPlayerTransformer().transform(
        {"stg_lineup": duplicate, "stg_team_lineups": duplicate}
    )

    assert result.to_dicts() == [
        {
            "group_id": "101-102-103",
            "player_id": player_id,
            "team_id": 1,
            "position_in_lineup": position,
            "season_year": "2024-25",
        }
        for position, player_id in enumerate((101, 102, 103), start=1)
    ]


def test_same_group_player_edges_remain_distinct_across_team_and_season() -> None:
    result = BridgeLineupPlayerTransformer().transform(
        {
            "stg_lineup": _lineups(
                ["101-102", "101-102", "101-102"],
                team_ids=[1, 2, 1],
                seasons=["2024-25", "2024-25", "2023-24"],
            )
        }
    )

    assert result.height == 6
    assert set(result.select("team_id", "season_year").iter_rows()) == {
        (1, "2023-24"),
        (1, "2024-25"),
        (2, "2024-25"),
    }
    assert (
        result.unique(subset=["group_id", "player_id", "team_id", "season_year"]).height
        == result.height
    )
