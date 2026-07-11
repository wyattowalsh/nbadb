from __future__ import annotations

import hashlib
import importlib.util
import json
from pathlib import Path
from typing import TYPE_CHECKING

import polars as pl
import pytest

from nbadb.orchestrate.discovery_artifacts import DiscoveryArtifactScope, DiscoveryArtifactStore
from nbadb.orchestrate.workload_contract import PlayerTeamSeasonWorkloadStore

if TYPE_CHECKING:
    from types import ModuleType

_SCRIPT_PATH = (
    Path(__file__).resolve().parents[3] / ".github" / "scripts" / "verify_discovery_bundle.py"
)


def _load_module() -> ModuleType:
    spec = importlib.util.spec_from_file_location("verify_discovery_bundle", _SCRIPT_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _scope_row(scope: DiscoveryArtifactScope) -> dict[str, object]:
    return {
        "kind": scope.kind,
        "seasons": list(scope.seasons),
        "season_types": list(scope.season_types),
        "variant": scope.variant,
        "scope_digest": scope.digest(),
    }


def _artifact_row(duckdb_path: Path, scope: DiscoveryArtifactScope) -> dict[str, object]:
    root = duckdb_path.with_name(f"{duckdb_path.stem}.discovery-artifacts")
    manifest_path = root / f"{scope.kind}.{scope.digest()}.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    content = manifest["content"]
    return {
        **_scope_row(scope),
        "artifact_path": str(root / content["path"]),
        "manifest_path": str(manifest_path),
        "content_sha256": content["sha256"],
    }


def _build_complete_bundle(
    tmp_path: Path,
) -> tuple[Path, Path, Path, DiscoveryArtifactScope, DiscoveryArtifactScope]:
    duckdb_path = tmp_path / "nba.duckdb"
    summary_path = tmp_path / "discovery-seed-summary.json"
    manifest_path = tmp_path / "discovery-manifest.json"
    manifest = {
        "github_matrix": {
            "include": [
                {
                    "patterns": "player_season,game,player_team_season",
                    "season_start": 2024,
                    "season_end": 2024,
                    "season_types": "Regular Season",
                    "resume_only": False,
                }
            ]
        }
    }
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    manifest_sha256 = hashlib.sha256(manifest_path.read_bytes()).hexdigest()
    player_scope = DiscoveryArtifactScope(
        kind="player_ids_all",
        seasons=("2024-25",),
        season_types=(),
        variant="historical",
    )
    game_scope = DiscoveryArtifactScope(
        kind="league_game_log",
        seasons=("2024-25",),
        season_types=("Regular Season",),
    )

    discovery_store = DiscoveryArtifactStore.from_duckdb_path(duckdb_path)
    discovery_store.upsert_ids(player_scope, [2544], provenance="test")
    discovery_store.upsert_frame(
        game_scope,
        pl.DataFrame(
            {
                "game_id": ["0022400001"],
                "game_date": ["2024-10-22"],
            }
        ),
        provenance="test",
    )

    workload_store = PlayerTeamSeasonWorkloadStore.from_duckdb_path(duckdb_path)
    workload_store.upsert(
        [
            {
                "player_id": 2544,
                "team_id": 1610612747,
                "season": "2024-25",
                "season_type": "Regular Season",
            }
        ],
        seasons=["2024-25"],
        season_types=["Regular Season"],
        covered_pairs={("2024-25", "Regular Season")},
    )
    assert workload_store.artifact_path is not None
    assert workload_store.manifest_path is not None
    workload_integrity = workload_store.integrity_attestation()
    assert workload_integrity is not None

    exact_count = 3
    summary = {
        "summary_schema_version": 2,
        "manifest_path": str(manifest_path),
        "manifest_sha256": manifest_sha256,
        "status": "complete",
        "phase": "complete",
        "checkpoint_sequence": 8,
        "deadline_seconds": 5400.0,
        "failure_type": None,
        "failure_types": [],
        "failure_count": 0,
        "scope_count": 1,
        "game_combo_count": 1,
        "player_team_season_pair_count": 1,
        "player_team_season_unique_season_count": 1,
        "total_scope_count": 3,
        "requested_exact_unit_count": exact_count,
        "covered_exact_unit_count": exact_count,
        "missing_exact_unit_count": 0,
        "coverage": {
            "requested": {
                "player_scope_count": 1,
                "player_season_count": 1,
                "game_combo_count": 1,
                "player_team_season_pair_count": 1,
                "exact_unit_count": exact_count,
            },
            "covered": {
                "player_scope_count": 1,
                "player_season_count": 1,
                "game_combo_count": 1,
                "player_team_season_pair_count": 1,
                "exact_unit_count": exact_count,
            },
            "missing": {
                "player_scope_count": 0,
                "player_season_count": 0,
                "game_combo_count": 0,
                "player_team_season_pair_count": 0,
                "exact_unit_count": 0,
            },
        },
        "requested_units": {
            "player_scopes": [_scope_row(player_scope)],
            "player_seasons": [{"season": "2024-25"}],
            "game_combos": [{"season": "2024-25", "season_type": "Regular Season"}],
            "player_team_season_pairs": [{"season": "2024-25", "season_type": "Regular Season"}],
        },
        "artifacts": {
            "discovery_artifact_dir": str(
                duckdb_path.with_name(f"{duckdb_path.stem}.discovery-artifacts")
            ),
            "player_scope_artifacts": [_artifact_row(duckdb_path, player_scope)],
            "player_season_artifacts": [_artifact_row(duckdb_path, player_scope)],
            "game_combo_artifacts": [_artifact_row(duckdb_path, game_scope)],
            "player_team_season_workload": {
                "artifact_path": str(workload_store.artifact_path),
                "manifest_path": str(workload_store.manifest_path),
                "covered_pair_count": 1,
                "covered_pairs": [{"season": "2024-25", "season_type": "Regular Season"}],
                "integrity": workload_integrity,
            },
        },
    }
    summary_path.write_text(json.dumps(summary), encoding="utf-8")
    return summary_path, manifest_path, duckdb_path, player_scope, game_scope


def test_verifier_accepts_a_complete_integrity_checked_bundle(tmp_path: Path) -> None:
    module = _load_module()
    summary_path, manifest_path, duckdb_path, _player_scope, _game_scope = _build_complete_bundle(
        tmp_path
    )

    counts = module.verify_discovery_bundle(
        summary_path=summary_path,
        manifest_path=manifest_path,
        duckdb_path=duckdb_path,
    )

    assert counts == {
        "player_scopes": 1,
        "player_seasons": 1,
        "game_combos": 1,
        "player_team_season_pairs": 1,
        "exact_units": 3,
    }


@pytest.mark.parametrize("missing_kind", ["player", "game"])
def test_verifier_rejects_a_missing_discovery_scope(
    tmp_path: Path,
    missing_kind: str,
) -> None:
    module = _load_module()
    summary_path, manifest_path, duckdb_path, player_scope, game_scope = _build_complete_bundle(
        tmp_path
    )
    scope = player_scope if missing_kind == "player" else game_scope
    scope_manifest_path = (
        duckdb_path.with_name(f"{duckdb_path.stem}.discovery-artifacts")
        / f"{scope.kind}.{scope.digest()}.json"
    )
    scope_manifest_path.unlink()

    with pytest.raises(module.DiscoveryBundleVerificationError, match="missing or invalid"):
        module.verify_discovery_bundle(
            summary_path=summary_path,
            manifest_path=manifest_path,
            duckdb_path=duckdb_path,
        )


def test_verifier_rejects_an_absent_workload_pair(tmp_path: Path) -> None:
    module = _load_module()
    summary_path, manifest_path, duckdb_path, _player_scope, _game_scope = _build_complete_bundle(
        tmp_path
    )
    workload_store = PlayerTeamSeasonWorkloadStore.from_duckdb_path(duckdb_path)
    assert workload_store.artifact_path is not None
    assert workload_store.manifest_path is not None
    workload_store.artifact_path.unlink()
    workload_store.manifest_path.unlink()

    with pytest.raises(module.DiscoveryBundleVerificationError, match="workload artifact pair"):
        module.verify_discovery_bundle(
            summary_path=summary_path,
            manifest_path=manifest_path,
            duckdb_path=duckdb_path,
        )


def test_verifier_rejects_zero_row_player_coverage(tmp_path: Path) -> None:
    module = _load_module()
    summary_path, manifest_path, duckdb_path, player_scope, _game_scope = _build_complete_bundle(
        tmp_path
    )
    DiscoveryArtifactStore.from_duckdb_path(duckdb_path).upsert_ids(
        player_scope,
        [],
        provenance="empty-regression",
    )

    with pytest.raises(module.DiscoveryBundleVerificationError, match="player-ID.*empty"):
        module.verify_discovery_bundle(
            summary_path=summary_path,
            manifest_path=manifest_path,
            duckdb_path=duckdb_path,
        )


def test_verifier_rejects_same_row_count_workload_content_tampering(tmp_path: Path) -> None:
    module = _load_module()
    summary_path, manifest_path, duckdb_path, _player_scope, _game_scope = _build_complete_bundle(
        tmp_path
    )
    workload_store = PlayerTeamSeasonWorkloadStore.from_duckdb_path(duckdb_path)
    generation_path = workload_store.artifact_path
    assert generation_path is not None
    frame = pl.read_parquet(generation_path).with_columns(
        pl.when(pl.col("player_id") > 0)
        .then(pl.lit(999999))
        .otherwise(pl.col("player_id"))
        .alias("player_id")
    )
    frame.write_parquet(generation_path)

    with pytest.raises(module.DiscoveryBundleVerificationError, match="workload artifact"):
        module.verify_discovery_bundle(
            summary_path=summary_path,
            manifest_path=manifest_path,
            duckdb_path=duckdb_path,
        )


def test_verifier_rejects_a_summary_generation_digest_mismatch(tmp_path: Path) -> None:
    module = _load_module()
    summary_path, manifest_path, duckdb_path, _player_scope, _game_scope = _build_complete_bundle(
        tmp_path
    )
    summary = json.loads(summary_path.read_text(encoding="utf-8"))
    summary["artifacts"]["game_combo_artifacts"][0]["content_sha256"] = "0" * 64
    summary_path.write_text(json.dumps(summary), encoding="utf-8")

    with pytest.raises(module.DiscoveryBundleVerificationError, match="content digest mismatch"):
        module.verify_discovery_bundle(
            summary_path=summary_path,
            manifest_path=manifest_path,
            duckdb_path=duckdb_path,
        )


def test_verifier_rejects_summary_claims_with_missing_coverage(tmp_path: Path) -> None:
    module = _load_module()
    summary_path, manifest_path, duckdb_path, _player_scope, _game_scope = _build_complete_bundle(
        tmp_path
    )
    summary = json.loads(summary_path.read_text(encoding="utf-8"))
    summary["coverage"]["missing"]["game_combo_count"] = 1
    summary_path.write_text(json.dumps(summary), encoding="utf-8")

    with pytest.raises(module.DiscoveryBundleVerificationError, match="must be zero"):
        module.verify_discovery_bundle(
            summary_path=summary_path,
            manifest_path=manifest_path,
            duckdb_path=duckdb_path,
        )


def test_verifier_rejects_self_consistent_empty_summary_for_nonempty_manifest(
    tmp_path: Path,
) -> None:
    module = _load_module()
    summary_path, manifest_path, duckdb_path, _player_scope, _game_scope = _build_complete_bundle(
        tmp_path
    )
    summary = json.loads(summary_path.read_text(encoding="utf-8"))
    empty_counts = {
        "player_scope_count": 0,
        "player_season_count": 0,
        "game_combo_count": 0,
        "player_team_season_pair_count": 0,
        "exact_unit_count": 0,
    }
    summary.update(
        {
            "scope_count": 0,
            "game_combo_count": 0,
            "player_team_season_pair_count": 0,
            "player_team_season_unique_season_count": 0,
            "total_scope_count": 0,
            "requested_exact_unit_count": 0,
            "covered_exact_unit_count": 0,
            "missing_exact_unit_count": 0,
            "coverage": {
                "requested": dict(empty_counts),
                "covered": dict(empty_counts),
                "missing": dict(empty_counts),
            },
            "requested_units": {
                "player_scopes": [],
                "player_seasons": [],
                "game_combos": [],
                "player_team_season_pairs": [],
            },
            "artifacts": {
                "discovery_artifact_dir": str(
                    duckdb_path.with_name(f"{duckdb_path.stem}.discovery-artifacts")
                ),
                "player_scope_artifacts": [],
                "player_season_artifacts": [],
                "game_combo_artifacts": [],
                "player_team_season_workload": None,
            },
        }
    )
    summary_path.write_text(json.dumps(summary), encoding="utf-8")

    with pytest.raises(module.DiscoveryBundleVerificationError, match="lane manifest"):
        module.verify_discovery_bundle(
            summary_path=summary_path,
            manifest_path=manifest_path,
            duckdb_path=duckdb_path,
        )


def test_verifier_rejects_self_consistent_empty_summary_and_manifest(tmp_path: Path) -> None:
    module = _load_module()
    summary_path, manifest_path, duckdb_path, _player_scope, _game_scope = _build_complete_bundle(
        tmp_path
    )
    manifest_path.write_text(json.dumps({"github_matrix": {"include": []}}), encoding="utf-8")
    summary = json.loads(summary_path.read_text(encoding="utf-8"))
    empty_counts = {
        "player_scope_count": 0,
        "player_season_count": 0,
        "game_combo_count": 0,
        "player_team_season_pair_count": 0,
        "exact_unit_count": 0,
    }
    summary.update(
        {
            "manifest_sha256": hashlib.sha256(manifest_path.read_bytes()).hexdigest(),
            "scope_count": 0,
            "game_combo_count": 0,
            "player_team_season_pair_count": 0,
            "player_team_season_unique_season_count": 0,
            "total_scope_count": 0,
            "requested_exact_unit_count": 0,
            "covered_exact_unit_count": 0,
            "missing_exact_unit_count": 0,
            "coverage": {
                "requested": dict(empty_counts),
                "covered": dict(empty_counts),
                "missing": dict(empty_counts),
            },
            "requested_units": {
                "player_scopes": [],
                "player_seasons": [],
                "game_combos": [],
                "player_team_season_pairs": [],
            },
            "artifacts": {
                "discovery_artifact_dir": str(
                    duckdb_path.with_name(f"{duckdb_path.stem}.discovery-artifacts")
                ),
                "player_scope_artifacts": [],
                "player_season_artifacts": [],
                "game_combo_artifacts": [],
                "player_team_season_workload": None,
            },
        }
    )
    summary_path.write_text(json.dumps(summary), encoding="utf-8")

    with pytest.raises(module.DiscoveryBundleVerificationError, match="no matrix lanes"):
        module.verify_discovery_bundle(
            summary_path=summary_path,
            manifest_path=manifest_path,
            duckdb_path=duckdb_path,
        )
