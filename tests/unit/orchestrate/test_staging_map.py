from __future__ import annotations

import ast
from pathlib import Path

import pytest

from nbadb.orchestrate.staging_map import (
    STAGING_MAP,
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
    stats_dir = Path(__file__).resolve().parents[3] / "src" / "nbadb" / "extract" / "stats"
    endpoint_metadata: dict[str, tuple[str, bool]] = {}

    for path in sorted(stats_dir.glob("*.py")):
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
        assert len(STAGING_MAP) == 402

    def test_all_staging_keys_unique(self) -> None:
        keys = get_all_staging_keys()
        assert len(keys) == len(set(keys))

    def test_get_by_pattern_season(self) -> None:
        entries = get_by_pattern("season")
        assert len(entries) == 86
        assert all(e.param_pattern == "season" for e in entries)

    def test_get_by_pattern_game(self) -> None:
        entries = get_by_pattern("game")
        assert len(entries) == 51

    def test_get_by_pattern_player(self) -> None:
        assert len(get_by_pattern("player")) == 125

    def test_get_by_pattern_team(self) -> None:
        assert len(get_by_pattern("team")) == 83

    def test_get_by_pattern_player_season(self) -> None:
        entries = get_by_pattern("player_season")
        assert len(entries) == 4
        staging_keys = {entry.staging_key for entry in entries}
        assert staging_keys == {
            "stg_gl_alum_box_score_similarity_score",
            "stg_player_game_log",
            "stg_player_fantasy_profile_last_five_games_avg",
            "stg_player_fantasy_profile_season_avg",
        }

    def test_get_by_pattern_player_team_season(self) -> None:
        entries = get_by_pattern("player_team_season")
        assert len(entries) == 2
        assert {entry.endpoint_name for entry in entries} == {
            "video_details",
            "video_details_asset",
        }

    def test_get_by_pattern_team_season(self) -> None:
        entries = get_by_pattern("team_season")
        assert len(entries) == 2
        names = {e.endpoint_name for e in entries}
        assert "team_game_log" in names
        assert "league_player_on_details" in names

    def test_get_by_pattern_static(self) -> None:
        assert len(get_by_pattern("static")) == 32

    def test_get_by_pattern_date(self) -> None:
        assert len(get_by_pattern("date")) == 17

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
        assert len(_MULTI_ROUTE_REGRESSION_ROWS) == 26

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
