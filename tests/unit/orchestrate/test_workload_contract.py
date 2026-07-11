from __future__ import annotations

import hashlib
import json
import threading
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
from io import BytesIO
from typing import TYPE_CHECKING

import polars as pl
import pytest

from nbadb.orchestrate.workload_contract import PlayerTeamSeasonWorkloadStore

if TYPE_CHECKING:
    from pathlib import Path

_PAIR = ("2024-25", "Regular Season")
_OTHER_PAIR = ("2025-26", "Regular Season")


def _store(tmp_path: Path) -> PlayerTeamSeasonWorkloadStore:
    return PlayerTeamSeasonWorkloadStore.from_duckdb_path(tmp_path / "planner.duckdb")


def _manifest(store: PlayerTeamSeasonWorkloadStore) -> dict[str, object]:
    manifest_path = store.manifest_path
    assert manifest_path is not None
    return json.loads(manifest_path.read_text(encoding="utf-8"))


def _write_manifest(store: PlayerTeamSeasonWorkloadStore, payload: dict[str, object]) -> None:
    manifest_path = store.manifest_path
    assert manifest_path is not None
    manifest_path.write_text(json.dumps(payload), encoding="utf-8")


def _one_param(
    *,
    player_id: int = 1,
    team_id: int = 10,
    pair: tuple[str, str] = _PAIR,
) -> dict[str, int | str]:
    return {
        "player_id": player_id,
        "team_id": team_id,
        "season": pair[0],
        "season_type": pair[1],
    }


def _upsert_one(
    store: PlayerTeamSeasonWorkloadStore,
    *,
    player_id: int = 1,
    team_id: int = 10,
    pair: tuple[str, str] = _PAIR,
) -> None:
    store.upsert(
        [_one_param(player_id=player_id, team_id=team_id, pair=pair)],
        seasons=[pair[0]],
        season_types=[pair[1]],
    )


def _write_self_consistent_generation(
    store: PlayerTeamSeasonWorkloadStore,
    frame: pl.DataFrame,
) -> Path:
    legacy_path = store.legacy_artifact_path
    assert legacy_path is not None
    buffer = BytesIO()
    frame.write_parquet(buffer)
    artifact_bytes = buffer.getvalue()
    digest = hashlib.sha256(artifact_bytes).hexdigest()
    generation_path = legacy_path.with_name(f"{legacy_path.stem}.{digest}.parquet")
    generation_path.write_bytes(artifact_bytes)

    manifest = _manifest(store)
    content = manifest["content"]
    assert isinstance(content, dict)
    content["path"] = generation_path.name
    content["sha256"] = digest
    _write_manifest(store, manifest)
    return generation_path


def _write_legacy_v3(
    store: PlayerTeamSeasonWorkloadStore,
    frame: pl.DataFrame,
    *,
    covered_pairs: list[dict[str, object]],
) -> bytes:
    legacy_path = store.legacy_artifact_path
    manifest_path = store.manifest_path
    assert legacy_path is not None
    assert manifest_path is not None
    frame.write_parquet(legacy_path)
    artifact_bytes = legacy_path.read_bytes()
    seasons = sorted({str(row["season"]) for row in covered_pairs})
    season_types = sorted({str(row["season_type"]) for row in covered_pairs})
    total_params = sum(int(row["row_count"]) for row in covered_pairs)
    manifest_path.write_text(
        json.dumps(
            {
                "artifact_version": 3,
                "artifact_kind": "player_team_season_workload",
                "artifact_path": str(legacy_path),
                "updated_at": datetime.now(UTC).isoformat(),
                "total_params": total_params,
                "covered_pairs": covered_pairs,
                "covered_seasons": seasons,
                "covered_season_types": season_types,
            }
        ),
        encoding="utf-8",
    )
    return artifact_bytes


def test_store_tracks_zero_row_covered_pairs_in_v4_generation(tmp_path: Path) -> None:
    store = _store(tmp_path)

    store.upsert([], seasons=[_PAIR[0]], season_types=[_PAIR[1]])

    coverage = store.load_coverage(seasons=[_PAIR[0]], season_types=[_PAIR[1]])
    assert coverage.counts_by_pair == {}
    assert coverage.covered_pairs == {_PAIR}
    assert coverage.invalid_pairs == set()

    artifact_path = store.artifact_path
    legacy_path = store.legacy_artifact_path
    assert artifact_path is not None
    assert legacy_path is not None
    assert artifact_path != legacy_path
    assert not legacy_path.exists()

    manifest = _manifest(store)
    assert manifest["artifact_version"] == 4
    assert manifest["artifact_kind"] == "player_team_season_workload"
    assert manifest["covered_pairs"] == [
        {"season": _PAIR[0], "season_type": _PAIR[1], "row_count": 0}
    ]
    content = manifest["content"]
    assert isinstance(content, dict)
    assert content["path"] == artifact_path.name
    assert content["sha256"] in artifact_path.name
    assert content["row_count"] == 1
    assert content["real_row_count"] == 0
    assert content["schema"] == [
        {"name": "player_id", "dtype": "Int64"},
        {"name": "team_id", "dtype": "Int64"},
        {"name": "season", "dtype": "String"},
        {"name": "season_type", "dtype": "String"},
    ]
    assert store.integrity_attestation() == {
        "manifest_version": 4,
        "generation_basename": artifact_path.name,
        "sha256": content["sha256"],
        "schema": content["schema"],
        "total_rows": 1,
        "real_rows": 0,
    }


def test_store_replaces_overlapping_scope_and_keeps_other_pairs(tmp_path: Path) -> None:
    store = _store(tmp_path)
    store.upsert(
        [
            _one_param(player_id=1, team_id=10),
            _one_param(player_id=2, team_id=20, pair=_OTHER_PAIR),
        ],
        seasons=[_PAIR[0], _OTHER_PAIR[0]],
        season_types=[_PAIR[1]],
    )

    store.upsert(
        [_one_param(player_id=3, team_id=30)],
        seasons=[_PAIR[0]],
        season_types=[_PAIR[1]],
    )

    assert store.load_params(season_types=[_PAIR[1]]) == [
        _one_param(player_id=3, team_id=30),
        _one_param(player_id=2, team_id=20, pair=_OTHER_PAIR),
    ]


def test_store_upsert_uses_explicit_covered_pairs(tmp_path: Path) -> None:
    store = _store(tmp_path)

    store.upsert(
        [_one_param(pair=_OTHER_PAIR)],
        seasons=[_PAIR[0], _OTHER_PAIR[0]],
        season_types=[_PAIR[1]],
        covered_pairs={_OTHER_PAIR},
    )

    coverage = store.load_coverage(seasons=[_PAIR[0], _OTHER_PAIR[0]], season_types=[_PAIR[1]])
    assert coverage.covered_pairs == {_OTHER_PAIR}
    assert coverage.counts_by_pair == {_OTHER_PAIR: 1}


def test_store_rejects_malformed_manifest_without_reconstruction(tmp_path: Path) -> None:
    store = _store(tmp_path)
    _upsert_one(store)
    generation = store.artifact_path
    manifest_path = store.manifest_path
    assert generation is not None
    assert manifest_path is not None
    original_generation = generation.read_bytes()

    manifest_path.write_text("{broken", encoding="utf-8")

    assert store.artifact_path is None
    assert store.integrity_attestation() is None
    assert store.load_params(seasons=[_PAIR[0]], season_types=[_PAIR[1]]) == []
    assert store.load_coverage().covered_pairs == set()
    assert generation.read_bytes() == original_generation
    assert manifest_path.read_text(encoding="utf-8") == "{broken"
    assert not list(tmp_path.glob("*.corrupt.*"))
    with pytest.raises(ValueError, match="invalid workload manifest"):
        _upsert_one(store, player_id=2, team_id=20, pair=_OTHER_PAIR)


def test_store_does_not_fallback_when_current_manifest_is_missing(tmp_path: Path) -> None:
    store = _store(tmp_path)
    _upsert_one(store)
    generation = store.artifact_path
    legacy_path = store.legacy_artifact_path
    manifest_path = store.manifest_path
    assert generation is not None
    assert legacy_path is not None
    assert manifest_path is not None
    assert generation != legacy_path

    manifest_path.unlink()

    assert generation.is_file()
    assert store.artifact_path is None
    assert store.integrity_attestation() is None
    assert store.load_params() == []
    assert store.legacy_artifact_path == legacy_path
    assert not legacy_path.exists()


def test_store_rejects_tampered_same_row_count_values(tmp_path: Path) -> None:
    store = _store(tmp_path)
    _upsert_one(store)
    generation = store.artifact_path
    assert generation is not None

    pl.DataFrame(
        [_one_param(player_id=999_999, team_id=999_998)],
        schema={
            "player_id": pl.Int64,
            "team_id": pl.Int64,
            "season": pl.Utf8,
            "season_type": pl.Utf8,
        },
    ).write_parquet(generation)

    assert store.artifact_path is None
    assert store.integrity_attestation() is None
    assert store.load_params() == []
    coverage = store.load_coverage()
    assert coverage.covered_pairs == set()
    assert coverage.invalid_pairs == {_PAIR}


def test_store_rejects_unsafe_generation_path(tmp_path: Path) -> None:
    store = _store(tmp_path)
    _upsert_one(store)
    manifest = _manifest(store)
    content = manifest["content"]
    assert isinstance(content, dict)
    content["path"] = f"../{content['path']}"
    _write_manifest(store, manifest)

    assert store.artifact_path is None
    assert store.load_params() == []
    assert store.load_coverage().covered_pairs == set()


def test_store_rejects_manifest_schema_mismatch(tmp_path: Path) -> None:
    store = _store(tmp_path)
    _upsert_one(store)
    manifest = _manifest(store)
    content = manifest["content"]
    assert isinstance(content, dict)
    schema = content["schema"]
    assert isinstance(schema, list)
    schema[0] = {"name": "player_id", "dtype": "Int32"}
    _write_manifest(store, manifest)

    assert store.artifact_path is None
    assert store.load_params() == []


def test_store_rejects_generation_schema_mismatch_with_valid_digest(tmp_path: Path) -> None:
    store = _store(tmp_path)
    _upsert_one(store)
    invalid_frame = pl.DataFrame(
        [_one_param()],
        schema={
            "player_id": pl.Int32,
            "team_id": pl.Int64,
            "season": pl.Utf8,
            "season_type": pl.Utf8,
        },
    )
    _write_self_consistent_generation(store, invalid_frame)

    assert store.artifact_path is None
    assert store.load_params() == []
    assert store.load_coverage().invalid_pairs == {_PAIR}


def test_store_rejects_invalid_sentinel_with_valid_digest(tmp_path: Path) -> None:
    store = _store(tmp_path)
    store.upsert([], seasons=[_PAIR[0]], season_types=[_PAIR[1]])
    invalid_frame = pl.DataFrame(
        [
            {
                "player_id": 0,
                "team_id": 1,
                "season": _PAIR[0],
                "season_type": _PAIR[1],
            }
        ],
        schema={
            "player_id": pl.Int64,
            "team_id": pl.Int64,
            "season": pl.Utf8,
            "season_type": pl.Utf8,
        },
    )
    _write_self_consistent_generation(store, invalid_frame)

    assert store.artifact_path is None
    assert store.load_coverage().invalid_pairs == {_PAIR}


def test_store_keeps_prior_generation_immutable(tmp_path: Path) -> None:
    store = _store(tmp_path)
    _upsert_one(store)
    first_generation = store.artifact_path
    assert first_generation is not None
    first_bytes = first_generation.read_bytes()

    _upsert_one(store, player_id=2, team_id=20, pair=_OTHER_PAIR)

    current_generation = store.artifact_path
    assert current_generation is not None
    assert current_generation != first_generation
    assert first_generation.is_file()
    assert first_generation.read_bytes() == first_bytes


def test_store_never_overwrites_corrupt_hash_named_generation(tmp_path: Path) -> None:
    source_dir = tmp_path / "source"
    source_dir.mkdir()
    source = _store(source_dir)
    _upsert_one(source)
    source_generation = source.artifact_path
    assert source_generation is not None
    digest = source_generation.stem.rsplit(".", 1)[-1]

    target_dir = tmp_path / "target"
    target_dir.mkdir()
    target = _store(target_dir)
    legacy_path = target.legacy_artifact_path
    assert legacy_path is not None
    corrupt_generation = legacy_path.with_name(f"{legacy_path.stem}.{digest}.parquet")
    corrupt_generation.write_bytes(b"not the hash-addressed parquet")

    with pytest.raises(OSError, match="digest collision or corruption"):
        _upsert_one(target)

    assert corrupt_generation.read_bytes() == b"not the hash-addressed parquet"
    assert target.manifest_path is not None
    assert not target.manifest_path.exists()


def test_store_promotes_valid_legacy_v3_exactly(tmp_path: Path) -> None:
    store = _store(tmp_path)
    legacy_frame = pl.DataFrame(
        [
            _one_param(),
            {
                "player_id": 0,
                "team_id": 0,
                "season": _OTHER_PAIR[0],
                "season_type": _OTHER_PAIR[1],
            },
        ],
        schema={
            "player_id": pl.Int64,
            "team_id": pl.Int64,
            "season": pl.Utf8,
            "season_type": pl.Utf8,
        },
    ).sort(["season", "season_type", "player_id", "team_id"])
    legacy_bytes = _write_legacy_v3(
        store,
        legacy_frame,
        covered_pairs=[
            {"season": _PAIR[0], "season_type": _PAIR[1], "row_count": 1},
            {"season": _OTHER_PAIR[0], "season_type": _OTHER_PAIR[1], "row_count": 0},
        ],
    )
    legacy_path = store.legacy_artifact_path
    assert legacy_path is not None
    assert store.artifact_path is None

    promoted = store.promote_legacy_v3()

    assert promoted is not None
    assert promoted != legacy_path
    assert promoted.is_file()
    assert legacy_path.read_bytes() == legacy_bytes
    assert store.promote_legacy_v3() == promoted
    assert store.load_params() == [_one_param()]
    coverage = store.load_coverage()
    assert coverage.covered_pairs == {_PAIR, _OTHER_PAIR}
    assert coverage.counts_by_pair == {_PAIR: 1}
    manifest = _manifest(store)
    assert manifest["artifact_version"] == 4
    assert manifest["provenance"] == "legacy_v3_promotion"


def test_store_fails_closed_on_partial_legacy_v3(tmp_path: Path) -> None:
    store = _store(tmp_path)
    legacy_frame = pl.DataFrame(
        [_one_param()],
        schema={
            "player_id": pl.Int64,
            "team_id": pl.Int64,
            "season": pl.Utf8,
            "season_type": pl.Utf8,
        },
    )
    _write_legacy_v3(
        store,
        legacy_frame,
        covered_pairs=[{"season": _PAIR[0], "season_type": _PAIR[1], "row_count": 1}],
    )
    manifest = _manifest(store)
    manifest.pop("covered_season_types")
    _write_manifest(store, manifest)
    manifest_before = store.manifest_path.read_bytes() if store.manifest_path is not None else b""

    assert store.promote_legacy_v3() is None
    assert store.artifact_path is None
    assert store.manifest_path is not None
    assert store.manifest_path.read_bytes() == manifest_before
    assert len(list(tmp_path.glob("*.parquet"))) == 1
    with pytest.raises(ValueError, match="explicit v3 promotion"):
        _upsert_one(store, player_id=2, team_id=20, pair=_OTHER_PAIR)


def test_store_rejects_legacy_v3_with_wrong_artifact_kind(tmp_path: Path) -> None:
    store = _store(tmp_path)
    legacy_frame = pl.DataFrame(
        [_one_param()],
        schema={
            "player_id": pl.Int64,
            "team_id": pl.Int64,
            "season": pl.Utf8,
            "season_type": pl.Utf8,
        },
    )
    _write_legacy_v3(
        store,
        legacy_frame,
        covered_pairs=[{"season": _PAIR[0], "season_type": _PAIR[1], "row_count": 1}],
    )
    manifest = _manifest(store)
    manifest["artifact_kind"] = "unrelated_workload"
    _write_manifest(store, manifest)
    manifest_path = store.manifest_path
    assert manifest_path is not None
    manifest_before = manifest_path.read_bytes()

    assert store.promote_legacy_v3() is None
    assert store.artifact_path is None
    assert manifest_path.read_bytes() == manifest_before
    assert len(list(tmp_path.glob("*.parquet"))) == 1


def test_concurrent_writers_leave_atomic_valid_pointer_and_immutable_generations(
    tmp_path: Path,
) -> None:
    store = _store(tmp_path)
    _upsert_one(store)
    initial_generation = store.artifact_path
    assert initial_generation is not None
    initial_bytes = initial_generation.read_bytes()
    barrier = threading.Barrier(8)

    def _write(index: int) -> None:
        concurrent_store = _store(tmp_path)
        barrier.wait()
        _upsert_one(
            concurrent_store,
            player_id=100 + index,
            team_id=200 + index,
        )

    with ThreadPoolExecutor(max_workers=8) as executor:
        futures = [executor.submit(_write, index) for index in range(8)]
        for future in futures:
            future.result()

    current_generation = store.artifact_path
    assert current_generation is not None
    assert initial_generation.read_bytes() == initial_bytes
    manifest = _manifest(store)
    content = manifest["content"]
    assert isinstance(content, dict)
    assert content["path"] == current_generation.name
    assert content["sha256"] == hashlib.sha256(current_generation.read_bytes()).hexdigest()
    assert store.load_coverage().covered_pairs == {_PAIR}
    params = store.load_params()
    assert len(params) == 1
    assert params[0]["player_id"] in range(100, 108)
    assert len(list(tmp_path.glob("*.player-team-season-workload.*.parquet"))) >= 2
