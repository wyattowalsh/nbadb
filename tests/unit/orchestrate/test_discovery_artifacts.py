from __future__ import annotations

import polars as pl

from nbadb.orchestrate.discovery_artifacts import DiscoveryArtifactScope, DiscoveryArtifactStore


def test_discovery_artifact_store_round_trips_scoped_game_logs(tmp_path) -> None:
    store = DiscoveryArtifactStore.from_duckdb_path(tmp_path / "planner.duckdb")
    scope = DiscoveryArtifactScope(
        kind="league_game_log",
        seasons=("2024-25",),
        season_types=("Regular Season",),
    )
    frame = pl.DataFrame({"game_id": ["001"], "game_date": ["2024-10-22"]})

    store.upsert_frame(scope, frame, provenance="test")

    loaded = store.load_frame(scope)
    assert loaded is not None
    assert loaded.to_dicts() == frame.to_dicts()


def test_discovery_artifact_store_round_trips_entity_ids(tmp_path) -> None:
    store = DiscoveryArtifactStore.from_duckdb_path(tmp_path / "planner.duckdb")
    scope = DiscoveryArtifactScope(
        kind="player_ids_all",
        seasons=("2024-25",),
        variant="historical",
    )

    store.upsert_ids(scope, [3, 1, 3, 2], provenance="test")

    assert store.load_ids(scope) == [1, 2, 3]
