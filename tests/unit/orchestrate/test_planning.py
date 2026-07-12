from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

from nbadb.core.endpoint_coverage import EndpointCoverageGenerator
from nbadb.core.types import VIDEO_CONTEXT_MEASURES, SeasonType
from nbadb.orchestrate.extraction_contract import (
    FULL_EXTRACTION_EXCLUSIONS_BY_ENDPOINT,
    contract_blocking_rules_for_lane,
)
from nbadb.orchestrate.full_extraction_control import build_default_manifest, validate_manifest
from nbadb.orchestrate.planning import (
    PLAYER_TEAM_SEASON_WORKLOAD_ENDPOINTS,
    build_extraction_plan,
    executable_endpoint_routes,
)
from nbadb.orchestrate.seasons import season_range
from nbadb.orchestrate.staging_map import STAGING_MAP, get_by_pattern

_GET_BY_PATTERN = "nbadb.orchestrate.planning.get_by_pattern"
_DEFAULT_SEASON_TYPES = ("Regular Season", "Playoffs")


def test_player_team_season_routes_are_plannable_or_explicitly_excluded() -> None:
    routed_endpoints = {entry.endpoint_name for entry in get_by_pattern("player_team_season")}

    assert routed_endpoints <= (
        PLAYER_TEAM_SEASON_WORKLOAD_ENDPOINTS | FULL_EXTRACTION_EXCLUSIONS_BY_ENDPOINT.keys()
    )


def test_full_manifest_has_a_runtime_route_for_every_active_endpoint() -> None:
    project_root = Path(__file__).resolve().parents[3]
    support_rows = EndpointCoverageGenerator(
        project_root=project_root,
        staging_entries=list(STAGING_MAP),
    ).build_artifacts()["support_matrix"]
    lanes = build_default_manifest(support_matrix_rows=support_rows)
    validate_manifest(lanes)

    seasons = season_range()
    season_types = [season_type.value for season_type in SeasonType]
    workload_params = [
        {
            "player_id": 1,
            "team_id": 1,
            "season": season,
            "season_type": season_type,
        }
        for season in seasons
        for season_type in season_types
    ]
    plan = build_extraction_plan(
        seasons=seasons,
        game_ids=["001"],
        player_ids=[1],
        team_ids=[1],
        current_team_ids=[1],
        game_dates=["2025-01-01"],
        player_team_season_params=workload_params,
        season_types=season_types,
    )
    routes = {(entry.endpoint_name, item.pattern) for item in plan for entry in item.entries}
    capability_routes = executable_endpoint_routes()
    scheduled_routes = {
        (endpoint_name, pattern)
        for lane in lanes
        if not lane.resume_only
        for endpoint_name in lane.endpoints
        for pattern in lane.patterns
    }
    unresolved = [
        (lane.lane_id, endpoint_name, lane.patterns)
        for lane in lanes
        if not lane.resume_only
        for endpoint_name in lane.endpoints
        if not any((endpoint_name, pattern) in routes for pattern in lane.patterns)
    ]
    end_year = int(seasons[-1][:4])

    def has_supported_scope(endpoint_name: str, pattern: str) -> bool:
        if pattern in {"static", "player", "team"}:
            return not contract_blocking_rules_for_lane(
                endpoints=(endpoint_name,),
                patterns=(pattern,),
                season_start=None,
                season_end=None,
            )
        return any(
            not contract_blocking_rules_for_lane(
                endpoints=(endpoint_name,),
                patterns=(pattern,),
                season_start=year,
                season_end=year,
            )
            for year in range(1946, end_year + 1)
        )

    expected_scheduled_routes = {
        (endpoint_name, pattern)
        for endpoint_name, pattern in capability_routes
        if endpoint_name not in FULL_EXTRACTION_EXCLUSIONS_BY_ENDPOINT
        and has_supported_scope(endpoint_name, pattern)
    }

    assert len(lanes) > 256
    assert routes == capability_routes
    assert unresolved == []
    assert expected_scheduled_routes - scheduled_routes == set()
    assert {
        ("home_page_leaders", "season"),
        ("home_page_v2", "season"),
        ("player_game_logs", "season"),
        ("player_game_logs_v2", "player_season"),
        ("player_game_streak_finder", "season"),
        ("player_streak_finder", "player_season"),
        ("shot_chart_lineup_detail", "season"),
        ("team_year_by_year_stats", "team"),
    } <= scheduled_routes


def _entry(
    endpoint_name: str,
    *,
    season_type_capability: str = "supported",
    supported_season_types: tuple[str, ...] = _DEFAULT_SEASON_TYPES,
):
    entry = MagicMock()
    entry.endpoint_name = endpoint_name
    entry.season_type_capability = season_type_capability
    entry.supported_season_types = supported_season_types
    entry.min_season = None
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
        assert plan[1].params == [
            {"season": "2024-25", "season_type": "Regular Season"},
            {"season": "2024-25", "season_type": "Playoffs"},
        ]
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

    def test_builds_cross_product_patterns_and_expands_video_context_measures(self) -> None:
        player_season_entries = [_entry("player_game_log")]
        team_season_entries = [_entry("team_game_log")]
        player_team_season_entries = [_entry("video_details")]
        params = [
            {
                "player_id": 201939,
                "team_id": 1610612744,
                "season": "2024-25",
                "season_type": "Regular Season",
            },
            {
                "player_id": 2544,
                "team_id": 1610612747,
                "season": "2025-26",
                "season_type": "Playoffs",
            },
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
                season_types=["Regular Season", "Playoffs"],
            )

        by_pattern = {item.pattern: item for item in plan}
        assert by_pattern["player_season"].params == [
            {"player_id": 201939, "season": "2024-25", "season_type": "Regular Season"},
            {"player_id": 201939, "season": "2024-25", "season_type": "Playoffs"},
            {"player_id": 201939, "season": "2025-26", "season_type": "Regular Season"},
            {"player_id": 201939, "season": "2025-26", "season_type": "Playoffs"},
            {"player_id": 2544, "season": "2024-25", "season_type": "Regular Season"},
            {"player_id": 2544, "season": "2024-25", "season_type": "Playoffs"},
            {"player_id": 2544, "season": "2025-26", "season_type": "Regular Season"},
            {"player_id": 2544, "season": "2025-26", "season_type": "Playoffs"},
        ]
        assert by_pattern["team_season"].params == [
            {"team_id": 1610612744, "season": "2024-25", "season_type": "Regular Season"},
            {"team_id": 1610612744, "season": "2024-25", "season_type": "Playoffs"},
            {"team_id": 1610612744, "season": "2025-26", "season_type": "Regular Season"},
            {"team_id": 1610612744, "season": "2025-26", "season_type": "Playoffs"},
        ]
        video_params = by_pattern["player_team_season"].params
        assert len(video_params) == len(params) * len(VIDEO_CONTEXT_MEASURES)
        assert by_pattern["player_team_season"].task_count == len(video_params)
        assert {str(item["context_measure"]) for item in video_params} == set(
            VIDEO_CONTEXT_MEASURES
        )
        assert {
            (
                item["player_id"],
                item["team_id"],
                item["season"],
                item["season_type"],
            )
            for item in video_params
        } == {
            (
                item["player_id"],
                item["team_id"],
                item["season"],
                item["season_type"],
            )
            for item in params
        }

    def test_video_workload_deduplicates_and_classifies_pre_play_in_scopes(self) -> None:
        video_entries = [
            _entry(
                "video_details",
                supported_season_types=(SeasonType.PLAY_IN.value,),
            )
        ]
        unavailable = {
            "player_id": 1,
            "team_id": 10,
            "season": "2018-19",
            "season_type": SeasonType.PLAY_IN.value,
        }
        available = {
            "player_id": 2,
            "team_id": 20,
            "season": "2019-20",
            "season_type": SeasonType.PLAY_IN.value,
        }

        with patch(
            _GET_BY_PATTERN,
            side_effect=lambda pattern: video_entries if pattern == "player_team_season" else [],
        ):
            plan = build_extraction_plan(
                seasons=["2018-19", "2019-20"],
                game_ids=[],
                player_ids=[],
                team_ids=[],
                game_dates=[],
                player_team_season_params=[unavailable, available, dict(available)],
                season_types=[SeasonType.PLAY_IN.value],
            )

        assert len(plan) == 1
        assert len(plan[0].params) == len(VIDEO_CONTEXT_MEASURES)
        assert {
            (item["player_id"], item["team_id"], item["season"], item["season_type"])
            for item in plan[0].params
        } == {(2, 20, "2019-20", SeasonType.PLAY_IN.value)}

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

    def test_isolates_current_team_only_team_endpoints(self) -> None:
        team_entries = [
            _entry("common_team_roster"),
            _entry("team_details"),
            _entry("team_historical_leaders"),
            _entry("team_info_common"),
        ]

        def _entries(pattern: str):
            return team_entries if pattern == "team" else []

        with patch(_GET_BY_PATTERN, side_effect=_entries):
            plan = build_extraction_plan(
                seasons=[],
                game_ids=[],
                player_ids=[],
                team_ids=[10, 20, 30],
                current_team_ids=[20, 30],
                game_dates=[],
            )

        assert [item.label for item in plan] == ["team", "team (current)"]
        assert [entry.endpoint_name for entry in plan[0].entries] == ["common_team_roster"]
        assert plan[0].params == [{"team_id": 10}, {"team_id": 20}, {"team_id": 30}]
        assert [entry.endpoint_name for entry in plan[1].entries] == [
            "team_details",
            "team_historical_leaders",
            "team_info_common",
        ]
        assert plan[1].params == [{"team_id": 20}, {"team_id": 30}]
