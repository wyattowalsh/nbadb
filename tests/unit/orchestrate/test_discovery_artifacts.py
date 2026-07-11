from __future__ import annotations

import hashlib
import json
import threading
from concurrent.futures import ThreadPoolExecutor
from io import BytesIO

import polars as pl
import pytest

import nbadb.orchestrate.discovery_artifacts as discovery_artifacts_module
from nbadb.orchestrate.discovery_artifacts import DiscoveryArtifactScope, DiscoveryArtifactStore


def _empty_game_frame() -> pl.DataFrame:
    return pl.DataFrame(
        {
            "game_id": pl.Series("game_id", [], dtype=pl.String),
            "game_date": pl.Series("game_date", [], dtype=pl.String),
        }
    )


def _manifest(store: DiscoveryArtifactStore, scope: DiscoveryArtifactScope) -> dict:
    return json.loads(store._manifest_path(scope).read_text(encoding="utf-8"))


def _generation_path(store: DiscoveryArtifactStore, scope: DiscoveryArtifactScope):
    manifest = _manifest(store, scope)
    root_dir = store._root_dir
    assert root_dir is not None
    return root_dir / manifest["content"]["path"]


def _write_legacy_v1(
    store: DiscoveryArtifactStore,
    scope: DiscoveryArtifactScope,
    frame: pl.DataFrame,
    *,
    row_count: int | None = None,
) -> None:
    artifact_path = store._artifact_path(scope)
    artifact_path.parent.mkdir(parents=True, exist_ok=True)
    frame.write_parquet(artifact_path)
    payload = {
        "artifact_kind": scope.kind,
        "artifact_version": 1,
        "scope": {
            "seasons": list(scope.seasons),
            "season_types": list(scope.season_types),
            "variant": scope.variant,
        },
        "artifact_path": str(artifact_path),
        "updated_at": "2026-07-11T00:00:00+00:00",
        "row_count": frame.height if row_count is None else row_count,
        "provenance": "legacy-test",
    }
    store._manifest_path(scope).write_text(json.dumps(payload), encoding="utf-8")


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
    artifact_path = _generation_path(store, scope)
    manifest = _manifest(store, scope)
    assert manifest == {
        "artifact_kind": "league_game_log",
        "artifact_version": 2,
        "content": {
            "format": "parquet",
            "path": artifact_path.name,
            "row_count": 1,
            "schema": [
                {"dtype": "String", "name": "game_id"},
                {"dtype": "String", "name": "game_date"},
            ],
            "sha256": hashlib.sha256(artifact_path.read_bytes()).hexdigest(),
        },
        "provenance": "test",
        "scope": {
            "kind": "league_game_log",
            "seasons": ["2024-25"],
            "season_types": ["Regular Season"],
            "variant": "default",
        },
        "updated_at": manifest["updated_at"],
    }


def test_discovery_artifact_store_round_trips_entity_ids(tmp_path) -> None:
    store = DiscoveryArtifactStore.from_duckdb_path(tmp_path / "planner.duckdb")
    scope = DiscoveryArtifactScope(
        kind="player_ids_all",
        seasons=("2024-25",),
        variant="historical",
    )

    store.upsert_ids(scope, [3, 1, 3, 2], provenance="test")

    assert store.load_ids(scope) == [1, 2, 3]


def test_discovery_artifact_store_rejects_frame_when_manifest_is_missing(tmp_path) -> None:
    store = DiscoveryArtifactStore.from_duckdb_path(tmp_path / "planner.duckdb")
    scope = DiscoveryArtifactScope(
        kind="league_game_log",
        seasons=("2024-25",),
        season_types=("Regular Season",),
    )
    store.upsert_frame(
        scope,
        pl.DataFrame({"game_id": ["001"], "game_date": ["2024-10-22"]}),
        provenance="test",
    )

    manifest_path = store._manifest_path(scope)
    manifest_path.unlink()

    assert store.load_game_log_frame(scope) is None


def test_discovery_artifact_store_rejects_corrupt_manifest(tmp_path) -> None:
    store = DiscoveryArtifactStore.from_duckdb_path(tmp_path / "planner.duckdb")
    scope = DiscoveryArtifactScope(
        kind="league_game_log",
        seasons=("2024-25",),
        season_types=("Regular Season",),
    )
    store.upsert_frame(scope, _empty_game_frame(), provenance="test-zero-row")
    store._manifest_path(scope).write_text("{not-json", encoding="utf-8")

    assert store.load_game_log_frame(scope) is None


def test_discovery_artifact_store_rejects_manifest_for_different_scope(tmp_path) -> None:
    store = DiscoveryArtifactStore.from_duckdb_path(tmp_path / "planner.duckdb")
    scope = DiscoveryArtifactScope(
        kind="league_game_log",
        seasons=("2024-25",),
        season_types=("Regular Season",),
    )
    store.upsert_frame(scope, _empty_game_frame(), provenance="test-zero-row")
    manifest_path = store._manifest_path(scope)
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["scope"]["season_types"] = ["Playoffs"]
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

    assert store.load_game_log_frame(scope) is None


def test_discovery_artifact_store_rejects_manifest_row_count_mismatch(tmp_path) -> None:
    store = DiscoveryArtifactStore.from_duckdb_path(tmp_path / "planner.duckdb")
    scope = DiscoveryArtifactScope(
        kind="league_game_log",
        seasons=("2024-25",),
        season_types=("Regular Season",),
    )
    store.upsert_frame(scope, _empty_game_frame(), provenance="test-zero-row")
    manifest_path = store._manifest_path(scope)
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["content"]["row_count"] = 1
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

    assert store.load_game_log_frame(scope) is None


def test_discovery_artifact_store_rejects_manifest_without_content_digest(tmp_path) -> None:
    store = DiscoveryArtifactStore.from_duckdb_path(tmp_path / "planner.duckdb")
    scope = DiscoveryArtifactScope(
        kind="player_ids_all",
        seasons=("2024-25",),
        variant="historical",
    )
    store.upsert_ids(scope, [], provenance="test-zero-row")
    manifest_path = store._manifest_path(scope)
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    del manifest["content"]["sha256"]
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

    assert (
        store.load_ids_for_seasons(
            kind="player_ids_all",
            seasons=("2024-25",),
            variant="historical",
        )
        is None
    )


def test_discovery_artifact_store_promotes_exact_legacy_player_scope(tmp_path) -> None:
    store = DiscoveryArtifactStore.from_duckdb_path(tmp_path / "planner.duckdb")
    scope = DiscoveryArtifactScope(
        kind="player_ids_all",
        seasons=("2024-25",),
        variant="historical",
    )
    frame = pl.DataFrame({"value": pl.Series("value", [1, 2], dtype=pl.Int64)})
    _write_legacy_v1(store, scope, frame)

    assert store.load_ids(scope) == [1, 2]
    manifest = _manifest(store, scope)
    assert manifest["artifact_version"] == 2
    assert manifest["provenance"] == "legacy-v1-promotion:legacy-test"
    assert _generation_path(store, scope).is_file()


def test_discovery_artifact_store_promotes_exact_legacy_game_scope(tmp_path) -> None:
    store = DiscoveryArtifactStore.from_duckdb_path(tmp_path / "planner.duckdb")
    scope = DiscoveryArtifactScope(
        kind="league_game_log",
        seasons=("2024-25",),
        season_types=("Regular Season",),
    )
    frame = pl.DataFrame({"game_id": ["001"], "game_date": ["2024-10-22"]})
    _write_legacy_v1(store, scope, frame)

    loaded = store.load_game_log_frame(scope)

    assert loaded is not None
    assert loaded.to_dicts() == frame.to_dicts()
    assert _manifest(store, scope)["artifact_version"] == 2


def test_discovery_artifact_store_never_promotes_legacy_aggregate_scope(tmp_path) -> None:
    store = DiscoveryArtifactStore.from_duckdb_path(tmp_path / "planner.duckdb")
    scope = DiscoveryArtifactScope(
        kind="player_ids_all",
        seasons=("2023-24", "2024-25"),
        variant="historical",
    )
    frame = pl.DataFrame({"value": pl.Series("value", [1, 2], dtype=pl.Int64)})
    _write_legacy_v1(store, scope, frame)

    assert store.load_frame(scope) is None
    assert _manifest(store, scope)["artifact_version"] == 1


def test_discovery_artifact_store_rejects_legacy_row_count_mismatch(tmp_path) -> None:
    store = DiscoveryArtifactStore.from_duckdb_path(tmp_path / "planner.duckdb")
    scope = DiscoveryArtifactScope(
        kind="player_ids_all",
        seasons=("2024-25",),
        variant="historical",
    )
    frame = pl.DataFrame({"value": pl.Series("value", [1], dtype=pl.Int64)})
    _write_legacy_v1(store, scope, frame, row_count=2)

    assert store.load_frame(scope) is None
    assert _manifest(store, scope)["artifact_version"] == 1


def test_discovery_artifact_store_rejects_legacy_filename_scope_mismatch(tmp_path) -> None:
    store = DiscoveryArtifactStore.from_duckdb_path(tmp_path / "planner.duckdb")
    scope = DiscoveryArtifactScope(
        kind="player_ids_all",
        seasons=("2024-25",),
        variant="historical",
    )
    frame = pl.DataFrame({"value": pl.Series("value", [1], dtype=pl.Int64)})
    _write_legacy_v1(store, scope, frame)
    manifest = _manifest(store, scope)
    manifest["artifact_path"] = "player_ids_all.wrong-scope-digest.parquet"
    store._manifest_path(scope).write_text(json.dumps(manifest), encoding="utf-8")

    assert store.load_frame(scope) is None
    assert _manifest(store, scope)["artifact_version"] == 1


def test_discovery_artifact_store_rejects_tampered_artifact_content(tmp_path) -> None:
    store = DiscoveryArtifactStore.from_duckdb_path(tmp_path / "planner.duckdb")
    scope = DiscoveryArtifactScope(
        kind="player_ids_all",
        seasons=("2024-25",),
        variant="historical",
    )
    store.upsert_ids(scope, [1], provenance="test")
    pl.DataFrame({"value": [2]}).write_parquet(_generation_path(store, scope))

    assert (
        store.load_ids_for_seasons(
            kind="player_ids_all",
            seasons=("2024-25",),
            variant="historical",
        )
        is None
    )


def test_discovery_artifact_store_retains_prior_pointer_when_manifest_swap_fails(
    tmp_path,
    monkeypatch,
) -> None:
    store = DiscoveryArtifactStore.from_duckdb_path(tmp_path / "planner.duckdb")
    scope = DiscoveryArtifactScope(
        kind="league_game_log",
        seasons=("2024-25",),
        season_types=("Regular Season",),
    )
    original = pl.DataFrame({"game_id": ["001"], "game_date": ["2024-10-22"]})
    replacement = pl.DataFrame({"game_id": ["002"], "game_date": ["2024-10-23"]})
    store.upsert_frame(scope, original, provenance="original")
    original_generation = _generation_path(store, scope)

    with monkeypatch.context() as patch_context:
        patch_context.setattr(
            discovery_artifacts_module,
            "atomic_write_text",
            lambda *_args, **_kwargs: (_ for _ in ()).throw(OSError("interrupted")),
        )
        with pytest.raises(OSError, match="interrupted"):
            store.upsert_frame(scope, replacement, provenance="replacement")

    loaded = store.load_frame(scope)
    assert loaded is not None
    assert loaded.to_dicts() == original.to_dicts()
    assert _generation_path(store, scope) == original_generation
    root_dir = store._root_dir
    assert root_dir is not None
    assert len(list(root_dir.glob(f"{scope.kind}.{scope.digest()}.*.parquet"))) == 2


def test_discovery_artifact_store_concurrent_writers_leave_valid_pointer(
    tmp_path,
    monkeypatch,
) -> None:
    store = DiscoveryArtifactStore.from_duckdb_path(tmp_path / "planner.duckdb")
    scope = DiscoveryArtifactScope(
        kind="league_game_log",
        seasons=("2024-25",),
        season_types=("Regular Season",),
    )
    first = pl.DataFrame({"game_id": ["001"], "game_date": ["2024-10-22"]})
    second = pl.DataFrame({"game_id": ["002"], "game_date": ["2024-10-23"]})
    real_atomic_write_text = discovery_artifacts_module.atomic_write_text
    manifest_barrier = threading.Barrier(2, timeout=5)

    def synchronized_manifest_swap(path, content) -> None:
        manifest_barrier.wait()
        real_atomic_write_text(path, content)

    monkeypatch.setattr(
        discovery_artifacts_module,
        "atomic_write_text",
        synchronized_manifest_swap,
    )
    with ThreadPoolExecutor(max_workers=2) as executor:
        futures = [
            executor.submit(store.upsert_frame, scope, first, provenance="first"),
            executor.submit(store.upsert_frame, scope, second, provenance="second"),
        ]
        for future in futures:
            future.result()

    loaded = store.load_frame(scope)
    assert loaded is not None
    assert loaded.to_dicts() in (first.to_dicts(), second.to_dicts())
    generation_path = _generation_path(store, scope)
    manifest = _manifest(store, scope)
    assert hashlib.sha256(generation_path.read_bytes()).hexdigest() == manifest["content"]["sha256"]


def test_discovery_artifact_store_rejects_unsafe_generation_pointer(tmp_path) -> None:
    store = DiscoveryArtifactStore.from_duckdb_path(tmp_path / "planner.duckdb")
    scope = DiscoveryArtifactScope(
        kind="player_ids_all",
        seasons=("2024-25",),
        variant="historical",
    )
    store.upsert_ids(scope, [1], provenance="test")
    manifest_path = store._manifest_path(scope)
    manifest = _manifest(store, scope)
    manifest["content"]["path"] = f"../{manifest['content']['path']}"
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

    assert store.load_frame(scope) is None


def test_discovery_artifact_store_rejects_self_consistent_wrong_kind_schema(tmp_path) -> None:
    store = DiscoveryArtifactStore.from_duckdb_path(tmp_path / "planner.duckdb")
    scope = DiscoveryArtifactScope(
        kind="league_game_log",
        seasons=("2024-25",),
        season_types=("Regular Season",),
    )
    store.upsert_frame(
        scope,
        pl.DataFrame({"game_id": ["001"], "game_date": ["2024-10-22"]}),
        provenance="test",
    )
    bad_frame = pl.DataFrame({"unrelated": ["value"]})
    buffer = BytesIO()
    bad_frame.write_parquet(buffer)
    bad_bytes = buffer.getvalue()
    bad_digest = hashlib.sha256(bad_bytes).hexdigest()
    bad_generation = store._generation_path(scope, bad_digest)
    bad_generation.write_bytes(bad_bytes)
    manifest = _manifest(store, scope)
    manifest["content"] = {
        "format": "parquet",
        "path": bad_generation.name,
        "row_count": 1,
        "schema": [{"name": "unrelated", "dtype": "String"}],
        "sha256": bad_digest,
    }
    store._manifest_path(scope).write_text(json.dumps(manifest), encoding="utf-8")

    assert store.load_frame(scope) is None


def test_discovery_artifact_store_rejects_untyped_zero_row_game_schema(tmp_path) -> None:
    store = DiscoveryArtifactStore.from_duckdb_path(tmp_path / "planner.duckdb")
    scope = DiscoveryArtifactScope(
        kind="league_game_log",
        seasons=("2024-25",),
        season_types=("Playoffs",),
    )

    with pytest.raises(ValueError, match="missing columns"):
        store.upsert_frame(scope, pl.DataFrame(), provenance="invalid-zero-row")


@pytest.mark.parametrize(
    ("frame", "message"),
    [
        (
            pl.DataFrame({"game_id": [None]}, schema={"game_id": pl.String}).with_columns(
                pl.lit("2024-10-22").alias("game_date")
            ),
            "game_id must contain non-empty values",
        ),
        (
            pl.DataFrame({"game_id": ["   "], "game_date": ["2024-10-22"]}),
            "game_id must contain non-empty values",
        ),
        (
            pl.DataFrame(
                {"game_id": ["0022400001"], "game_date": [None]},
                schema={"game_id": pl.String, "game_date": pl.String},
            ),
            "game_date must not contain nulls",
        ),
        (
            pl.DataFrame({"game_id": ["0022400001"], "game_date": [""]}),
            "game_date must contain non-empty values",
        ),
    ],
)
def test_discovery_artifact_store_rejects_invalid_game_values(
    tmp_path,
    frame: pl.DataFrame,
    message: str,
) -> None:
    store = DiscoveryArtifactStore.from_duckdb_path(tmp_path / "nba.duckdb")
    scope = DiscoveryArtifactScope(
        kind="league_game_log",
        seasons=("2024-25",),
        season_types=("Regular Season",),
    )

    with pytest.raises(ValueError, match=message):
        store.upsert_frame(scope, frame, provenance="invalid-values")


@pytest.mark.parametrize("value", [0, -1])
def test_discovery_artifact_store_rejects_nonpositive_identifiers(
    tmp_path,
    value: int,
) -> None:
    store = DiscoveryArtifactStore.from_duckdb_path(tmp_path / "nba.duckdb")
    scope = DiscoveryArtifactScope(
        kind="player_ids_all",
        seasons=("2024-25",),
        variant="historical",
    )

    with pytest.raises(ValueError, match="positive identifiers"):
        store.upsert_ids(scope, [value], provenance="invalid-values")


def test_discovery_artifact_store_reuses_combo_scoped_game_logs_for_narrower_scope(
    tmp_path,
) -> None:
    store = DiscoveryArtifactStore.from_duckdb_path(tmp_path / "planner.duckdb")
    store.upsert_game_log_combo_frames(
        {
            ("2024-25", "Regular Season"): pl.DataFrame(
                {"game_id": ["001"], "game_date": ["2024-10-22"]}
            ),
            ("2024-25", "Playoffs"): _empty_game_frame(),
        },
        provenance="partial-discovery",
    )

    loaded = store.load_game_log_frame(
        DiscoveryArtifactScope(
            kind="league_game_log",
            seasons=("2024-25",),
            season_types=("Regular Season",),
        )
    )

    assert loaded is not None
    assert loaded.to_dicts() == [{"game_id": "001", "game_date": "2024-10-22"}]


def test_game_log_cache_requires_every_exact_combo_including_zero_row_combos(tmp_path) -> None:
    store = DiscoveryArtifactStore.from_duckdb_path(tmp_path / "planner.duckdb")
    regular_scope = DiscoveryArtifactScope(
        kind="league_game_log",
        seasons=("2024-25",),
        season_types=("Regular Season",),
    )
    playoffs_scope = DiscoveryArtifactScope(
        kind="league_game_log",
        seasons=("2024-25",),
        season_types=("Playoffs",),
    )
    requested_scope = DiscoveryArtifactScope(
        kind="league_game_log",
        seasons=("2024-25",),
        season_types=("Regular Season", "Playoffs"),
    )
    store.upsert_frame(
        regular_scope,
        pl.DataFrame({"game_id": ["001"], "game_date": ["2024-10-22"]}),
        provenance="test",
    )

    assert store.load_game_log_frame(requested_scope) is None

    store.upsert_frame(playoffs_scope, _empty_game_frame(), provenance="test-zero-row")
    loaded = store.load_game_log_frame(requested_scope)

    assert loaded is not None
    assert loaded.to_dicts() == [{"game_id": "001", "game_date": "2024-10-22"}]


def test_game_log_cache_accepts_typed_zero_row_exact_scope(tmp_path) -> None:
    store = DiscoveryArtifactStore.from_duckdb_path(tmp_path / "planner.duckdb")
    scope = DiscoveryArtifactScope(
        kind="league_game_log",
        seasons=("2024-25",),
        season_types=("All Star",),
    )
    store.upsert_frame(scope, _empty_game_frame(), provenance="test-zero-row")

    loaded = store.load_game_log_frame(scope)

    assert loaded is not None
    assert loaded.is_empty()
    assert loaded.schema == {"game_id": pl.String, "game_date": pl.String}


def test_discovery_artifact_store_returns_none_when_unavailable() -> None:
    store = DiscoveryArtifactStore.from_duckdb_path(None)
    scope = DiscoveryArtifactScope(kind="league_game_log")

    assert store.load_frame(scope) is None


def test_discovery_artifact_store_unions_complete_per_season_ids(tmp_path) -> None:
    store = DiscoveryArtifactStore.from_duckdb_path(tmp_path / "planner.duckdb")
    store.upsert_ids(
        DiscoveryArtifactScope(
            kind="player_ids_all",
            seasons=("1946-47",),
            variant="historical",
        ),
        [3, 1],
        provenance="test",
    )
    store.upsert_ids(
        DiscoveryArtifactScope(
            kind="player_ids_all",
            seasons=("1947-48",),
            variant="historical",
        ),
        [3, 2],
        provenance="test",
    )

    assert store.load_ids_for_seasons(
        kind="player_ids_all",
        seasons=("1946-47", "1947-48"),
        variant="historical",
    ) == [1, 2, 3]


def test_discovery_artifact_store_requires_every_per_season_id_scope(tmp_path) -> None:
    store = DiscoveryArtifactStore.from_duckdb_path(tmp_path / "planner.duckdb")
    store.upsert_ids(
        DiscoveryArtifactScope(
            kind="player_ids_all",
            seasons=("1946-47",),
            variant="historical",
        ),
        [1],
        provenance="test",
    )

    assert (
        store.load_ids_for_seasons(
            kind="player_ids_all",
            seasons=("1946-47", "1947-48"),
            variant="historical",
        )
        is None
    )


def test_discovery_artifact_store_does_not_count_zero_row_player_scope_as_complete(
    tmp_path,
) -> None:
    store = DiscoveryArtifactStore.from_duckdb_path(tmp_path / "planner.duckdb")
    store.upsert_ids(
        DiscoveryArtifactScope(
            kind="player_ids_all",
            seasons=("1946-47",),
            variant="historical",
        ),
        [],
        provenance="test-zero-row",
    )
    store.upsert_ids(
        DiscoveryArtifactScope(
            kind="player_ids_all",
            seasons=("1947-48",),
            variant="historical",
        ),
        [2],
        provenance="test",
    )

    assert (
        store.load_ids_for_seasons(
            kind="player_ids_all",
            seasons=("1946-47", "1947-48"),
            variant="historical",
        )
        is None
    )
