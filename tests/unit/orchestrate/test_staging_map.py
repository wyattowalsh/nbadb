from __future__ import annotations

import pytest

from nbadb.orchestrate.staging_map import (
    STAGING_MAP,
    StagingEntry,
    get_all_staging_keys,
    get_by_pattern,
    get_by_staging_key,
    get_multi_entries,
)


class TestStagingMap:
    def test_map_has_expected_entry_count(self) -> None:
        # 13 season + 16 game + 2 date + 6 player + 4 team + 2 static
        assert len(STAGING_MAP) == 43

    def test_all_staging_keys_unique(self) -> None:
        keys = get_all_staging_keys()
        assert len(keys) == len(set(keys))

    def test_get_by_pattern_season(self) -> None:
        entries = get_by_pattern("season")
        assert len(entries) == 13
        assert all(e.param_pattern == "season" for e in entries)

    def test_get_by_pattern_game(self) -> None:
        entries = get_by_pattern("game")
        assert len(entries) == 16

    def test_get_by_pattern_player(self) -> None:
        assert len(get_by_pattern("player")) == 6

    def test_get_by_pattern_team(self) -> None:
        assert len(get_by_pattern("team")) == 4

    def test_get_by_pattern_static(self) -> None:
        assert len(get_by_pattern("static")) == 2

    def test_get_by_pattern_date(self) -> None:
        assert len(get_by_pattern("date")) == 2

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
        assert len(bss) == 2
        indices = {e.result_set_index for e in bss}
        assert indices == {5, 6}  # line_score=5, officials=6

    def test_officials_index_is_6(self) -> None:
        """HR-P-001: Officials result set is index 6, not 2."""
        entry = get_by_staging_key("stg_officials")
        assert entry is not None
        assert entry.result_set_index == 6

    def test_all_entries_have_stg_prefix(self) -> None:
        for e in STAGING_MAP:
            assert e.staging_key.startswith("stg_"), (
                f"{e.staging_key} missing stg_ prefix"
            )

    def test_frozen_dataclass(self) -> None:
        """StagingEntry should be immutable."""
        entry = STAGING_MAP[0]
        with pytest.raises(AttributeError):
            entry.endpoint_name = "changed"  # type: ignore[misc]
