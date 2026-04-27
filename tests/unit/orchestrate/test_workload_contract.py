from __future__ import annotations

import json

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

    manifest = json.loads(store.manifest_path.read_text(encoding="utf-8"))
    assert manifest["artifact_kind"] == "player_team_season_workload"
    assert manifest["covered_pairs"] == [{"season": "2024-25", "season_type": "Regular Season"}]


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


def test_store_ignores_corrupted_manifest_and_keeps_frame_data(tmp_path) -> None:
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
    repaired = json.loads(store.manifest_path.read_text(encoding="utf-8"))
    assert repaired["recovered_from_artifact"] is True
