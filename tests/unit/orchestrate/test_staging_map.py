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
    "home_page_leaders",
    "home_page_v2",
    "league_dash_player_bio_stats",
    "league_hustle_stats_player",
    "league_hustle_stats_team",
    "play_by_play_v2",
    "player_career_by_college_rollup",
    "player_compare",
    "player_dash_pt_defend",
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
}


def _extractor_endpoint_names() -> set[str]:
    stats_dir = Path(__file__).resolve().parents[3] / "src" / "nbadb" / "extract" / "stats"
    endpoint_names: set[str] = set()

    for path in sorted(stats_dir.glob("*.py")):
        if path.name == "__init__.py":
            continue
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in tree.body:
            if not isinstance(node, ast.ClassDef):
                continue
            for stmt in node.body:
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
                    endpoint_names.add(value.value)

    return endpoint_names


class TestStagingMap:
    def test_map_has_expected_entry_count(self) -> None:
        # 60 season + 35 game + 16 date + 56 player + 25 team +
        # 1 player_season + 2 team_season + 5 static
        assert len(STAGING_MAP) == 200

    def test_all_staging_keys_unique(self) -> None:
        keys = get_all_staging_keys()
        assert len(keys) == len(set(keys))

    def test_get_by_pattern_season(self) -> None:
        entries = get_by_pattern("season")
        assert len(entries) == 60
        assert all(e.param_pattern == "season" for e in entries)

    def test_get_by_pattern_game(self) -> None:
        entries = get_by_pattern("game")
        assert len(entries) == 35

    def test_get_by_pattern_player(self) -> None:
        assert len(get_by_pattern("player")) == 56

    def test_get_by_pattern_team(self) -> None:
        assert len(get_by_pattern("team")) == 25

    def test_get_by_pattern_player_season(self) -> None:
        entries = get_by_pattern("player_season")
        assert len(entries) == 1
        assert entries[0].endpoint_name == "player_game_log"

    def test_get_by_pattern_team_season(self) -> None:
        entries = get_by_pattern("team_season")
        assert len(entries) == 2
        names = {e.endpoint_name for e in entries}
        assert "team_game_log" in names
        assert "league_player_on_details" in names

    def test_get_by_pattern_static(self) -> None:
        assert len(get_by_pattern("static")) == 5

    def test_get_by_pattern_date(self) -> None:
        assert len(get_by_pattern("date")) == 16

    def test_get_by_staging_key_found(self) -> None:
        entry = get_by_staging_key("stg_league_game_log")
        assert entry is not None
        assert entry.endpoint_name == "league_game_log"

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

    def test_all_entries_have_stg_prefix(self) -> None:
        for e in STAGING_MAP:
            assert e.staging_key.startswith("stg_"), f"{e.staging_key} missing stg_ prefix"

    def test_frozen_dataclass(self) -> None:
        """StagingEntry should be immutable."""
        entry = STAGING_MAP[0]
        with pytest.raises(AttributeError):
            entry.endpoint_name = "changed"  # type: ignore[misc]

    def test_no_extractor_only_endpoints_remain_after_mapping(self) -> None:
        # gl_alum_box_score_similarity_score excluded: requires person1_id/person2_id
        _excluded = {"gl_alum_box_score_similarity_score"}
        extractor_only = sorted(
            _extractor_endpoint_names() - {e.endpoint_name for e in STAGING_MAP} - _excluded
        )
        assert extractor_only == []

    def test_audited_missing_endpoints_are_now_represented(self) -> None:
        staging_names = {e.endpoint_name for e in STAGING_MAP}
        assert sorted(_AUDITED_MISSING_ENDPOINTS - staging_names) == []
