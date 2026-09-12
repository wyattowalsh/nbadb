from __future__ import annotations

import pytest

from nbadb.orchestrate.player_directory_snapshot import (
    SNAPSHOT_AUTHORITY_STATUS,
    SNAPSHOT_CANONICAL_SHA256,
    SNAPSHOT_COMPLETE_THROUGH_SEASON,
    SNAPSHOT_ROW_COUNT,
    player_directory_snapshot_authority,
    player_ids_by_season_from_snapshot,
    require_player_directory_snapshot_authority,
)


def test_player_directory_snapshot_covers_historical_seed_window() -> None:
    with pytest.raises(RuntimeError, match="not extraction-authoritative"):
        player_ids_by_season_from_snapshot(["1946-47", "1947-48", "1964-65", "bad-season"])


def test_player_directory_snapshot_stops_at_declared_complete_season() -> None:
    with pytest.raises(RuntimeError, match="not extraction-authoritative"):
        player_ids_by_season_from_snapshot([SNAPSHOT_COMPLETE_THROUGH_SEASON, "2026-27"])


def test_player_directory_snapshot_integrity_is_stable_but_not_authoritative() -> None:
    authority = player_directory_snapshot_authority()

    assert authority["status"] == SNAPSHOT_AUTHORITY_STATUS == "blocked_pending_evidence"
    assert authority["row_count"] == SNAPSHOT_ROW_COUNT == 5_197
    assert authority["canonical_sha256"] == SNAPSHOT_CANONICAL_SHA256
    assert authority["integrity_verified"] is True
    assert authority["integrity_errors"] == []
    with pytest.raises(RuntimeError, match="not extraction-authoritative"):
        require_player_directory_snapshot_authority()
