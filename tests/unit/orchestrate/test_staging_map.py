from __future__ import annotations

import pytest

from nbadb.orchestrate.staging_map import (
    STAGING_MAP,
    get_all_staging_keys,
    get_by_pattern,
    get_by_staging_key,
    get_multi_entries,
)


class TestStagingMap:
    def test_map_has_expected_entry_count(self) -> None:
        # 52 season + 34 game + 16 date + 46 player + 23 team + 4 static
        assert len(STAGING_MAP) == 175

    def test_all_staging_keys_unique(self) -> None:
        keys = get_all_staging_keys()
        assert len(keys) == len(set(keys))

    def test_get_by_pattern_season(self) -> None:
        entries = get_by_pattern("season")
        assert len(entries) == 52
        assert all(e.param_pattern == "season" for e in entries)

    def test_get_by_pattern_game(self) -> None:
        entries = get_by_pattern("game")
        assert len(entries) == 34

    def test_get_by_pattern_player(self) -> None:
        assert len(get_by_pattern("player")) == 46

    def test_get_by_pattern_team(self) -> None:
        assert len(get_by_pattern("team")) == 23

    def test_get_by_pattern_static(self) -> None:
        assert len(get_by_pattern("static")) == 4

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
