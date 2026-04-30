from __future__ import annotations

import ast
from pathlib import Path

import pytest

from nbadb.core.types import SeasonType
from nbadb.orchestrate.staging_map import (
    STAGING_MAP,
    StagingEntry,
    get_all_staging_keys,
    get_by_pattern,
    get_by_staging_key,
    get_multi_entries,
)

_AUDITED_MISSING_ENDPOINTS = {
    "common_all_players",
    "gl_alum_box_score_similarity_score",
    "home_page_leaders",
    "home_page_v2",
    "league_dash_player_bio_stats",
    "play_by_play_v2",
    "player_career_by_college_rollup",
    "player_compare",
    "player_dashboard_game_splits",
    "player_dashboard_general_splits",
    "player_dashboard_last_n_games",
    "player_dashboard_shooting_splits",
    "player_dashboard_team_performance",
    "player_dashboard_year_over_year",
    "player_game_log",
    "player_game_logs",
    "player_game_streak_finder",
    "player_index",
    "shot_chart_lineup_detail",
    "team_and_players_vs_players",
    "team_game_log",
    "team_year_by_year_stats",
    "video_details",
    "video_details_asset",
}

_MULTI_ROUTE_REGRESSION_ROWS = {
    "stg_all_time": "all_time_leaders_grids",
    "stg_cume_player": "cume_stats_player",
    "stg_cume_team": "cume_stats_team",
    "stg_defense_hub_stat1": "defense_hub",
    "stg_homepage_leaders": "homepage_leaders",
    "stg_homepage_v2": "homepage_v2",
    "stg_leaders_tiles": "leaders_tiles",
    "stg_on_off": "team_player_on_off_summary",
    "stg_player_college_rollup": "player_college_rollup",
    "stg_player_compare": "player_compare",
    "stg_player_dash_game_splits": "player_dash_game_splits",
    "stg_player_dash_general_splits": "player_dash_general_splits",
    "stg_player_dash_last_n_games": "player_dash_last_n_games",
    "stg_player_dash_shooting_splits": "player_dash_shooting_splits",
    "stg_player_dash_team_perf": "player_dash_team_perf",
    "stg_player_dash_yoy": "player_dash_yoy",
    "stg_player_dashboard_clutch": "player_dashboard_clutch",
    "stg_player_vs_player": "player_vs_player",
    "stg_schedule_int": "schedule_int",
    "stg_schedule_int_broadcaster": "schedule_int",
    "stg_schedule_int_weeks": "schedule_int",
    "stg_team_and_players_vs": "team_and_players_vs",
    "stg_team_dash_general_splits": "team_dashboard_general_splits",
    "stg_team_dash_shooting_splits": "team_dashboard_shooting_splits",
    "stg_team_dashboard_on_off": "team_player_on_off_details",
    "stg_team_player_dashboard": "team_player_dashboard",
    "stg_team_vs_player": "team_vs_player",
}

_MULTI_ROUTE_NONZERO_INDICES = {
    "stg_player_dash_game_splits": 4,
    "stg_player_dash_general_splits": 3,
    "stg_player_dash_last_n_games": 5,
    "stg_player_dash_shooting_splits": 2,
    "stg_player_dash_yoy": 1,
    "stg_player_dashboard_clutch": 10,
    "stg_schedule_int_broadcaster": 2,
    "stg_schedule_int_weeks": 1,
}

_OVERALL_ONLY_MULTI_ENDPOINTS = {
    "player_dashboard_game_splits",
    "player_dashboard_general_splits",
    "player_dashboard_last_n_games",
    "player_dashboard_shooting_splits",
    "player_dashboard_year_over_year",
}


def _extractor_endpoint_names() -> set[str]:
    return set(_extractor_endpoint_metadata())


def _extractor_endpoint_metadata() -> dict[str, tuple[str, bool]]:
    extract_root = Path(__file__).resolve().parents[3] / "src" / "nbadb" / "extract"
    endpoint_metadata: dict[str, tuple[str, bool]] = {}

    for subdir in (extract_root / "stats", extract_root / "live"):
        for path in sorted(subdir.glob("*.py")):
            if path.name == "__init__.py":
                continue
            tree = ast.parse(path.read_text(encoding="utf-8"))
            for node in tree.body:
                if not isinstance(node, ast.ClassDef):
                    continue
                endpoint_name: str | None = None
                methods: set[str] = set()
                for stmt in node.body:
                    if isinstance(stmt, (ast.AsyncFunctionDef, ast.FunctionDef)):
                        methods.add(stmt.name)
                        continue
                    if isinstance(stmt, ast.Assign):
                        value = stmt.value
                        targets = stmt.targets
                    elif isinstance(stmt, ast.AnnAssign):
                        value = stmt.value
                        targets = [stmt.target]
                    else:
                        continue
                    if not isinstance(value, ast.Constant) or not isinstance(value.value, str):
                        continue
                    if any(
                        isinstance(target, ast.Name) and target.id == "endpoint_name"
                        for target in targets
                    ):
                        endpoint_name = value.value

                if endpoint_name is not None:
                    endpoint_metadata[endpoint_name] = (path.name, "extract_all" in methods)

    return endpoint_metadata


class TestStagingMap:
    def test_map_has_expected_entry_count(self) -> None:
        assert len(STAGING_MAP) == 414

    def test_all_staging_keys_unique(self) -> None:
        keys = get_all_staging_keys()
        assert len(keys) == len(set(keys))

    def test_get_by_pattern_season(self) -> None:
        entries = get_by_pattern("season")
        assert len(entries) == 90
        assert all(e.param_pattern == "season" for e in entries)
        assert any(e.endpoint_name == "player_career_by_college" for e in entries)

    def test_get_by_pattern_game(self) -> None:
        entries = get_by_pattern("game")
        assert len(entries) == 52

    def test_get_by_pattern_live(self) -> None:
        entries = get_by_pattern("live")
        assert len(entries) == 10
        assert {entry.endpoint_name for entry in entries} == {
            "live_box_score",
            "live_odds",
            "live_play_by_play",
            "live_score_board",
        }

    def test_get_by_pattern_player(self) -> None:
        assert len(get_by_pattern("player")) == 108

    def test_get_by_pattern_team(self) -> None:
        assert len(get_by_pattern("team")) == 16

    def test_get_by_pattern_player_season(self) -> None:
        entries = get_by_pattern("player_season")
        assert len(entries) == 8
        staging_keys = {entry.staging_key for entry in entries}
        assert staging_keys == {
            "stg_cume_player",
            "stg_cume_player_game_by_game",
            "stg_cume_player_games",
            "stg_cume_player_totals",
            "stg_gl_alum_box_score_similarity_score",
            "stg_player_game_log",
            "stg_player_fantasy_profile_last_five_games_avg",
            "stg_player_fantasy_profile_season_avg",
        }

    def test_get_by_pattern_player_team_season(self) -> None:
        entries = get_by_pattern("player_team_season")
        assert len(entries) == 30
        assert {entry.endpoint_name for entry in entries} == {
            "player_vs_player",
            "team_and_players_vs",
            "team_and_players_vs_players",
            "team_vs_player",
            "video_details",
            "video_details_asset",
        }

    def test_get_by_pattern_team_season(self) -> None:
        entries = get_by_pattern("team_season")
        assert len(entries) == 50
        names = {e.endpoint_name for e in entries}
        assert "common_team_roster" in names
        assert "cume_stats_team" in names
        assert "cume_stats_team_games" in names
        assert "team_dashboard_general_splits" in names
        assert "team_dashboard_shooting_splits" in names
        assert "team_dash_pt_pass" in names
        assert "team_dash_pt_reb" in names
        assert "team_dash_pt_shots" in names
        assert "team_game_log" in names
        assert "team_dash_lineups" in names
        assert "league_player_on_details" in names
        assert "team_player_dashboard" in names
        assert "team_player_on_off_details" in names
        assert "team_player_on_off_summary" in names

    def test_get_by_pattern_static(self) -> None:
        assert len(get_by_pattern("static")) == 33

    def test_get_by_pattern_date(self) -> None:
        assert len(get_by_pattern("date")) == 17

    @pytest.mark.parametrize(
        ("param_pattern", "expected_capability"),
        [
            ("season", "not_applicable"),
            ("player_season", "not_applicable"),
            ("team_season", "not_applicable"),
            ("player_team_season", "blocked"),
            ("game", "not_applicable"),
            ("live", "not_applicable"),
            ("player", "not_applicable"),
            ("team", "not_applicable"),
            ("static", "not_applicable"),
            ("date", "not_applicable"),
        ],
    )
    def test_staging_entry_defaults_season_type_capability_by_pattern(
        self,
        param_pattern: str,
        expected_capability: str,
    ) -> None:
        entry = StagingEntry("foo_endpoint", f"stg_{param_pattern}", param_pattern)

        assert entry.season_type_capability == expected_capability

    def test_staging_map_historical_entries_use_endpoint_aware_season_type_capability(
        self,
    ) -> None:
        historical_entries = {
            entry.staging_key: entry
            for entry in STAGING_MAP
            if entry.param_pattern in {"season", "player_season", "team_season"}
        }

        assert historical_entries
        assert {entry.season_type_capability for entry in historical_entries.values()} == {
            "not_applicable",
            "supported",
        }

        supported_entries = {
            "stg_league_game_log": (
                "Regular Season",
                "Playoffs",
                "Pre Season",
                "All Star",
            ),
            "stg_player_game_log": ("Regular Season", "Playoffs", "Pre Season", "All Star"),
            "stg_team_game_log": ("Regular Season", "Playoffs", "Pre Season", "All Star"),
        }
        for staging_key, expected_season_types in supported_entries.items():
            entry = historical_entries[staging_key]
            assert entry.season_type_capability == "supported"
            assert entry.supported_season_types == expected_season_types

        for staging_key in (
            "stg_schedule",
            "stg_draft",
            "stg_playoff_picture_east",
            "stg_draft_board",
        ):
            entry = historical_entries[staging_key]
            assert entry.season_type_capability == "not_applicable"
            assert entry.supported_season_types == ()

    def test_staging_map_player_team_season_entries_are_explicitly_supported(self) -> None:
        entries = get_by_pattern("player_team_season")

        assert entries
        capabilities = {entry.endpoint_name: entry.season_type_capability for entry in entries}
        supported_season_types = tuple(season_type.value for season_type in SeasonType)

        assert {
            endpoint_name: capability
            for endpoint_name, capability in capabilities.items()
            if capability == "supported"
        } == {
            "video_details": "supported",
            "video_details_asset": "supported",
            "player_vs_player": "supported",
            "team_and_players_vs": "supported",
            "team_and_players_vs_players": "supported",
            "team_vs_player": "supported",
        }

        for endpoint_name in (
            "player_vs_player",
            "team_and_players_vs",
            "team_and_players_vs_players",
            "team_vs_player",
        ):
            entry = next(entry for entry in entries if entry.endpoint_name == endpoint_name)
            assert entry.season_type_capability == "supported"
            assert entry.supported_season_types == supported_season_types

    def test_problem_endpoints_route_to_runnable_or_blocked_patterns(self) -> None:
        expected_patterns = {
            "stg_player_game_streak_finder": "season",
            "stg_team_streak_finder": "season",
            "stg_coaches": "team_season",
            "stg_team_info": "team_season",
            "stg_team_dash_general_splits": "team_season",
            "stg_team_dash_shooting_splits": "team_season",
            "stg_team_lineups": "team_season",
            "stg_team_lineups_overall": "team_season",
            "stg_team_game_logs_v2": "team_season",
            "stg_team_pt_pass": "team_season",
            "stg_team_pt_reb": "team_season",
            "stg_team_pt_shots": "team_season",
            "stg_team_player_dashboard": "team_season",
            "stg_team_dashboard_on_off": "team_season",
            "stg_on_off": "team_season",
            "stg_player_vs_player": "player_team_season",
            "stg_team_vs_player": "player_team_season",
            "stg_team_and_players_vs": "player_team_season",
            "stg_team_and_players_vs_players": "player_team_season",
        }

        for staging_key, expected_pattern in expected_patterns.items():
            entry = get_by_staging_key(staging_key)
            assert entry is not None
            assert entry.param_pattern == expected_pattern

    def test_staging_map_player_game_logs_v2_overrides_player_pattern_default(self) -> None:
        entry = get_by_staging_key("stg_player_game_logs_v2")

        assert entry is not None
        assert entry.season_type_capability == "supported"

    def test_staging_map_non_historical_patterns_are_not_applicable(self) -> None:
        non_historical_patterns = {"game", "live", "player", "team", "static", "date"}
        entries = [
            entry
            for entry in STAGING_MAP
            if entry.param_pattern in non_historical_patterns
            and entry.staging_key != "stg_player_game_logs_v2"
        ]

        assert entries
        assert {entry.season_type_capability for entry in entries} == {"not_applicable"}

    def test_get_by_staging_key_found(self) -> None:
        entry = get_by_staging_key("stg_league_game_log")
        assert entry is not None
        assert entry.endpoint_name == "league_game_log"

    def test_play_by_play_v2_has_min_season_guard(self) -> None:
        for staging_key in (
            "stg_play_by_play_v2",
            "stg_play_by_play_v2_video_available",
        ):
            entry = get_by_staging_key(staging_key)
            assert entry is not None
            assert entry.min_season == 1996

    def test_box_score_v3_game_packet_has_1996_min_season_guards(self) -> None:
        for staging_key in (
            "stg_box_score_advanced",
            "stg_box_score_scoring",
            "stg_box_score_usage",
            "stg_box_score_four_factors_player",
            "stg_box_score_advanced_team",
            "stg_box_score_scoring_team",
            "stg_box_score_usage_team",
            "stg_box_score_four_factors_team",
        ):
            entry = get_by_staging_key(staging_key)
            assert entry is not None
            assert entry.min_season == 1996

    def test_get_by_staging_key_not_found(self) -> None:
        assert get_by_staging_key("stg_nonexistent") is None

    def test_multi_entries_box_score_summary(self) -> None:
        multi = get_multi_entries()
        assert "box_score_summary" in multi
        bss = multi["box_score_summary"]
        # All 9 result sets: 0-8 (AvailableVideo, GameInfo, GameSummary,
        # InactivePlayers, LastMeeting, LineScore, Officials, OtherStats, SeasonSeries)
        assert len(bss) == 9
        indices = {e.result_set_index for e in bss}
        assert indices == {0, 1, 2, 3, 4, 5, 6, 7, 8}

    def test_officials_index_is_6(self) -> None:
        """HR-P-001: Officials result set is index 6, not 2."""
        entry = get_by_staging_key("stg_officials")
        assert entry is not None
        assert entry.result_set_index == 6

    def test_known_multi_result_regression_rows_use_expected_index(self) -> None:
        assert len(_MULTI_ROUTE_REGRESSION_ROWS) == 27

        for staging_key, endpoint_name in _MULTI_ROUTE_REGRESSION_ROWS.items():
            entry = get_by_staging_key(staging_key)
            assert entry is not None, f"{staging_key} missing from STAGING_MAP"
            assert entry.endpoint_name == endpoint_name
            assert entry.result_set_index == _MULTI_ROUTE_NONZERO_INDICES.get(staging_key, 0)
            assert entry.use_multi is True

    def test_multi_result_endpoints_do_not_mix_use_multi_flags(self) -> None:
        grouped: dict[str, list[object]] = {}
        for entry in STAGING_MAP:
            grouped.setdefault(entry.endpoint_name, []).append(entry)

        mixed_groups = {
            endpoint_name: [
                (entry.staging_key, entry.result_set_index, entry.use_multi) for entry in entries
            ]
            for endpoint_name, entries in grouped.items()
            if any(entry.use_multi for entry in entries)
            and not all(entry.use_multi for entry in entries)
        }

        assert mixed_groups == {}

    def test_multi_result_endpoints_include_an_index_zero_row(self) -> None:
        grouped: dict[str, list[object]] = {}
        for entry in STAGING_MAP:
            grouped.setdefault(entry.endpoint_name, []).append(entry)

        missing_index_zero = {
            endpoint_name: sorted(
                (entry.staging_key, entry.result_set_index) for entry in entries if entry.use_multi
            )
            for endpoint_name, entries in grouped.items()
            if any(entry.use_multi for entry in entries)
            and not any(entry.use_multi and entry.result_set_index == 0 for entry in entries)
            and endpoint_name not in _OVERALL_ONLY_MULTI_ENDPOINTS
        }

        assert missing_index_zero == {}

    def test_multi_result_endpoints_have_extract_all_support(self) -> None:
        extractor_metadata = _extractor_endpoint_metadata()
        missing_extract_all = {
            endpoint_name: extractor_metadata.get(endpoint_name, ("<missing extractor>", False))[0]
            for endpoint_name in sorted(
                {entry.endpoint_name for entry in STAGING_MAP if entry.use_multi}
            )
            if endpoint_name not in extractor_metadata or not extractor_metadata[endpoint_name][1]
        }

        assert missing_extract_all == {}

    def test_all_entries_have_stg_prefix(self) -> None:
        for e in STAGING_MAP:
            assert e.staging_key.startswith("stg_"), f"{e.staging_key} missing stg_ prefix"

    def test_frozen_dataclass(self) -> None:
        """StagingEntry should be immutable."""
        entry = STAGING_MAP[0]
        with pytest.raises(AttributeError):
            entry.endpoint_name = "changed"  # type: ignore[misc]

    def test_no_extractor_only_endpoints_remain_after_mapping(self) -> None:
        extractor_only = sorted(
            _extractor_endpoint_names() - {e.endpoint_name for e in STAGING_MAP}
        )
        assert extractor_only == []

    def test_audited_missing_endpoints_are_now_represented(self) -> None:
        staging_names = {e.endpoint_name for e in STAGING_MAP}
        assert sorted(_AUDITED_MISSING_ENDPOINTS - staging_names) == []
