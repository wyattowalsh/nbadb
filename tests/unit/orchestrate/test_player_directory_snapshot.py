from __future__ import annotations

from nbadb.orchestrate.player_directory_snapshot import player_ids_by_season_from_snapshot


def test_player_directory_snapshot_covers_historical_seed_window() -> None:
    ids_by_season = player_ids_by_season_from_snapshot(
        ["1946-47", "1947-48", "1964-65", "bad-season"]
    )

    assert {season: len(ids) for season, ids in ids_by_season.items()} == {
        "1946-47": 161,
        "1947-48": 114,
        "1964-65": 117,
    }
    assert "bad-season" not in ids_by_season
