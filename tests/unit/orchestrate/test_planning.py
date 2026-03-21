from __future__ import annotations

from unittest.mock import MagicMock, patch

from nbadb.orchestrate.planning import build_extraction_plan

_GET_BY_PATTERN = "nbadb.orchestrate.planning.get_by_pattern"


def _entry(endpoint_name: str):
    entry = MagicMock()
    entry.endpoint_name = endpoint_name
    return entry


class TestBuildExtractionPlan:
    def test_builds_expected_default_patterns_in_priority_order(self) -> None:
        static_entries = [_entry("franchise_history")]
        season_entries = [_entry("league_game_log"), _entry("league_standings")]
        game_entries = [_entry("box_score_traditional")]
        player_entries = [_entry("common_player_info")]
        team_entries = [_entry("common_team_roster")]
        date_entries = [_entry("scoreboard_v2")]

        def _entries(pattern: str):
            mapping = {
                "static": static_entries,
                "season": season_entries,
                "game": game_entries,
                "player": player_entries,
                "team": team_entries,
                "player_season": [],
                "player_team_season": [],
                "team_season": [],
                "date": date_entries,
            }
            return mapping[pattern]

        with patch(_GET_BY_PATTERN, side_effect=_entries):
            plan = build_extraction_plan(
                seasons=["2024-25"],
                game_ids=["0022400001"],
                player_ids=[201939],
                team_ids=[1610612744],
                game_dates=["2024-10-22"],
            )

        assert [item.pattern for item in plan] == [
            "static",
            "season",
            "game",
            "player",
            "team",
            "date",
        ]
        assert plan[0].task_count == 1
        assert plan[1].entries == [season_entries[1]]
        assert plan[1].params == [{"season": "2024-25", "season_type": "Regular Season"}]
        assert plan[2].params == [{"game_id": "0022400001"}]
        assert plan[3].params == [{"player_id": 201939}]
        assert plan[4].params == [{"team_id": 1610612744}]
        assert plan[5].params == [{"game_date": "2024-10-22"}]

    def test_skips_static_when_disabled(self) -> None:
        def _entries(pattern: str):
            return [_entry(pattern)]

        with patch(_GET_BY_PATTERN, side_effect=_entries):
            plan = build_extraction_plan(
                seasons=["2024-25"],
                game_ids=[],
                player_ids=[],
                team_ids=[],
                game_dates=[],
                include_static=False,
            )

        assert [item.pattern for item in plan] == ["season"]

    def test_builds_cross_product_patterns_and_player_team_season_passthrough(self) -> None:
        player_season_entries = [_entry("player_game_log")]
        team_season_entries = [_entry("team_game_log")]
        player_team_season_entries = [_entry("video_details")]
        params = [
            {"player_id": 201939, "team_id": 1610612744, "season": "2024-25"},
            {"player_id": 2544, "team_id": 1610612747, "season": "2025-26"},
        ]

        def _entries(pattern: str):
            mapping = {
                "static": [],
                "season": [],
                "game": [],
                "player": [],
                "team": [],
                "player_season": player_season_entries,
                "player_team_season": player_team_season_entries,
                "team_season": team_season_entries,
                "date": [],
            }
            return mapping[pattern]

        with patch(_GET_BY_PATTERN, side_effect=_entries):
            plan = build_extraction_plan(
                seasons=["2024-25", "2025-26"],
                game_ids=[],
                player_ids=[201939, 2544],
                team_ids=[1610612744],
                game_dates=[],
                player_team_season_params=params,
            )

        by_pattern = {item.pattern: item for item in plan}
        assert by_pattern["player_season"].params == [
            {"player_id": 201939, "season": "2024-25"},
            {"player_id": 201939, "season": "2025-26"},
            {"player_id": 2544, "season": "2024-25"},
            {"player_id": 2544, "season": "2025-26"},
        ]
        assert by_pattern["team_season"].params == [
            {"team_id": 1610612744, "season": "2024-25"},
            {"team_id": 1610612744, "season": "2025-26"},
        ]
        assert by_pattern["player_team_season"].params == params

    def test_honors_explicit_season_types(self) -> None:
        season_entries = [_entry("league_game_log"), _entry("league_standings")]

        def _entries(pattern: str):
            return season_entries if pattern == "season" else []

        with patch(_GET_BY_PATTERN, side_effect=_entries):
            plan = build_extraction_plan(
                seasons=["2024-25"],
                game_ids=[],
                player_ids=[],
                team_ids=[],
                game_dates=[],
                season_types=["Regular Season", "Playoffs"],
            )

        assert len(plan) == 1
        assert plan[0].params == [
            {"season": "2024-25", "season_type": "Regular Season"},
            {"season": "2024-25", "season_type": "Playoffs"},
        ]
