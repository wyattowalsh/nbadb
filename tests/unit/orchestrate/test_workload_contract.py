from __future__ import annotations

import json

import polars as pl

from nbadb.orchestrate.workload_contract import PlayerTeamSeasonWorkloadStore


def test_store_tracks_zero_row_covered_pairs(tmp_path) -> None:
    store = PlayerTeamSeasonWorkloadStore.from_duckdb_path(tmp_path / "planner.duckdb")

    store.upsert(
        [],
        seasons=["2024-25"],
        season_types=["Regular Season"],
    )

    coverage = store.load_coverage(
        seasons=["2024-25"],
        season_types=["Regular Season"],
    )
    assert coverage.counts_by_pair == {}
    assert coverage.covered_pairs == {("2024-25", "Regular Season")}
    assert coverage.invalid_pairs == set()

    manifest = json.loads(store.manifest_path.read_text(encoding="utf-8"))
    assert manifest["artifact_kind"] == "player_team_season_workload"
    assert manifest["covered_pairs"] == [
        {"season": "2024-25", "season_type": "Regular Season", "row_count": 0}
    ]


def test_store_replaces_overlapping_scope_and_keeps_other_pairs(tmp_path) -> None:
    store = PlayerTeamSeasonWorkloadStore.from_duckdb_path(tmp_path / "planner.duckdb")
    store.upsert(
        [
            {
                "player_id": 1,
                "team_id": 10,
                "season": "2024-25",
                "season_type": "Regular Season",
            },
            {
                "player_id": 2,
                "team_id": 20,
                "season": "2025-26",
                "season_type": "Regular Season",
            },
        ],
        seasons=["2024-25", "2025-26"],
        season_types=["Regular Season"],
    )

    store.upsert(
        [
            {
                "player_id": 3,
                "team_id": 30,
                "season": "2024-25",
                "season_type": "Regular Season",
            }
        ],
        seasons=["2024-25"],
        season_types=["Regular Season"],
    )

    assert store.load_params(season_types=["Regular Season"]) == [
        {
            "player_id": 3,
            "team_id": 30,
            "season": "2024-25",
            "season_type": "Regular Season",
        },
        {
            "player_id": 2,
            "team_id": 20,
            "season": "2025-26",
            "season_type": "Regular Season",
        },
    ]


def test_store_upsert_uses_explicit_covered_pairs(tmp_path) -> None:
    store = PlayerTeamSeasonWorkloadStore.from_duckdb_path(tmp_path / "planner.duckdb")

    store.upsert(
        [
            {
                "player_id": 1,
                "team_id": 10,
                "season": "2025-26",
                "season_type": "Regular Season",
            }
        ],
        seasons=["2024-25", "2025-26"],
        season_types=["Regular Season"],
        covered_pairs={("2025-26", "Regular Season")},
    )

    coverage = store.load_coverage(seasons=["2024-25", "2025-26"], season_types=["Regular Season"])
    assert coverage.covered_pairs == {("2025-26", "Regular Season")}
    assert coverage.counts_by_pair == {("2025-26", "Regular Season"): 1}


def test_store_reads_corrupted_manifest_without_repairing_on_read(tmp_path) -> None:
    store = PlayerTeamSeasonWorkloadStore.from_duckdb_path(tmp_path / "planner.duckdb")
    store.upsert(
        [
            {
                "player_id": 1,
                "team_id": 10,
                "season": "2024-25",
                "season_type": "Regular Season",
            }
        ],
        seasons=["2024-25"],
        season_types=["Regular Season"],
    )

    store.manifest_path.write_text("{broken", encoding="utf-8")

    assert store.load_params(seasons=["2024-25"], season_types=["Regular Season"]) == [
        {
            "player_id": 1,
            "team_id": 10,
            "season": "2024-25",
            "season_type": "Regular Season",
        }
    ]
    coverage = store.load_coverage(seasons=["2024-25"], season_types=["Regular Season"])
    assert coverage.counts_by_pair == {("2024-25", "Regular Season"): 1}
    assert coverage.covered_pairs == {("2024-25", "Regular Season")}
    assert store.manifest_path.read_text(encoding="utf-8") == "{broken"
    assert not list(tmp_path.glob("*.corrupt.*"))


def test_store_repairs_corrupted_manifest_on_write_path(tmp_path) -> None:
    store = PlayerTeamSeasonWorkloadStore.from_duckdb_path(tmp_path / "planner.duckdb")
    store.upsert(
        [
            {
                "player_id": 1,
                "team_id": 10,
                "season": "2024-25",
                "season_type": "Regular Season",
            }
        ],
        seasons=["2024-25"],
        season_types=["Regular Season"],
    )

    store.manifest_path.write_text("{broken", encoding="utf-8")

    store.upsert(
        [
            {
                "player_id": 2,
                "team_id": 20,
                "season": "2025-26",
                "season_type": "Regular Season",
            }
        ],
        seasons=["2025-26"],
        season_types=["Regular Season"],
    )

    repaired = json.loads(store.manifest_path.read_text(encoding="utf-8"))
    assert repaired["covered_pairs"] == [
        {"season": "2024-25", "season_type": "Regular Season", "row_count": 1},
        {"season": "2025-26", "season_type": "Regular Season", "row_count": 1},
    ]


def test_store_recovers_zero_row_covered_pairs_from_artifact(tmp_path) -> None:
    store = PlayerTeamSeasonWorkloadStore.from_duckdb_path(tmp_path / "planner.duckdb")
    store.upsert(
        [],
        seasons=["2024-25"],
        season_types=["Regular Season"],
    )

    store.manifest_path.write_text("{broken", encoding="utf-8")

    assert store.load_params(seasons=["2024-25"], season_types=["Regular Season"]) == []
    coverage = store.load_coverage(seasons=["2024-25"], season_types=["Regular Season"])
    assert coverage.counts_by_pair == {}
    assert coverage.covered_pairs == {("2024-25", "Regular Season")}

    assert store.manifest_path.read_text(encoding="utf-8") == "{broken"


def test_store_rejects_declared_nonzero_pair_missing_from_parquet(tmp_path) -> None:
    store = PlayerTeamSeasonWorkloadStore.from_duckdb_path(tmp_path / "planner.duckdb")
    pair = ("2024-25", "Regular Season")
    store.upsert(
        [
            {
                "player_id": 1,
                "team_id": 10,
                "season": pair[0],
                "season_type": pair[1],
            }
        ],
        seasons=[pair[0]],
        season_types=[pair[1]],
    )
    assert store.artifact_path is not None
    pl.read_parquet(store.artifact_path).head(0).write_parquet(store.artifact_path)

    coverage = store.load_coverage(seasons=[pair[0]], season_types=[pair[1]])

    assert coverage.counts_by_pair == {}
    assert coverage.covered_pairs == set()
    assert coverage.invalid_pairs == {pair}


def test_store_rejects_zero_row_pair_without_explicit_sentinel(tmp_path) -> None:
    store = PlayerTeamSeasonWorkloadStore.from_duckdb_path(tmp_path / "planner.duckdb")
    pair = ("2024-25", "Regular Season")
    store.upsert([], seasons=[pair[0]], season_types=[pair[1]])
    assert store.artifact_path is not None
    pl.read_parquet(store.artifact_path).head(0).write_parquet(store.artifact_path)

    coverage = store.load_coverage(seasons=[pair[0]], season_types=[pair[1]])

    assert coverage.covered_pairs == set()
    assert coverage.invalid_pairs == {pair}
