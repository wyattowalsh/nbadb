from __future__ import annotations

import errno
import hashlib
import json
import os
import stat
import threading
from dataclasses import replace
from types import SimpleNamespace
from typing import TYPE_CHECKING, Any

import pytest

import nbadb.orchestrate.successor_generation_store as generation_store_module
from nbadb.core.artifact_identity import (
    build_assured_artifact_manifest,
    inventory_regular_tree,
)
from nbadb.kaggle.client import KaggleClient
from nbadb.orchestrate.successor_baseline import (
    baseline_identity_from_verified_publication,
)
from nbadb.orchestrate.successor_inventory import measure_installed_public_tree
from nbadb.orchestrate.successor_publication_inventory import (
    successor_publication_freshness_season,
)
from nbadb.orchestrate.transformers import expected_transform_output_tables

if TYPE_CHECKING:
    from pathlib import Path

from nbadb.orchestrate.successor_generation_store import (
    CURRENT_SUCCESSOR_GENERATION_NAME,
    SUCCESSOR_CANDIDATE_BASELINE_NAME,
    SUCCESSOR_TRANSACTION_NAME,
    SuccessorGenerationStore,
    SuccessorGenerationStoreError,
)
from nbadb.orchestrate.successor_update_contract import (
    BaselineAssuranceIdentity,
    CallMutability,
    DeltaDisposition,
    ObservedDeltaReceipt,
    PlannedRouteReplacementBinding,
    RequestedRouteScope,
    SuccessorAssuranceIdentity,
    SuccessorUpdateIntent,
    SuccessorUpdateMode,
    SuccessorUpdateTransaction,
    canonical_json_bytes,
    planned_route_replacement_bindings_sha256,
)


def _promoted(
    generation: int,
    marker: str,
    *,
    baseline_installed_public_tree_sha256: str = "3" * 64,
    baseline_installed_public_tree_bytes: int = len(b"synthetic-baseline-public"),
) -> SuccessorUpdateTransaction:
    baseline = BaselineAssuranceIdentity(
        remote_dataset="maintainer/nbadb",
        remote_dataset_version=237,
        chain_id="full-initial",
        source_sha="a" * 40,
        coverage_fingerprint="1" * 64,
        data_tree_fingerprint="2" * 64,
        remote_bundle_fingerprint_sha256="b" * 64,
        installed_public_tree_sha256=baseline_installed_public_tree_sha256,
        installed_public_tree_bytes=baseline_installed_public_tree_bytes,
        assured_manifest_sha256="4" * 64,
        terminal_assurance_report_sha256="5" * 64,
        private_baseline_receipt_sha256="6" * 64,
        checkpoint_database_sha256="7" * 64,
        checkpoint_report_sha256="8" * 64,
        contract_blocked_evidence_sha256="9" * 64,
        provider_authority_sha256="a" * 64,
    )
    scope = RequestedRouteScope.from_parameters(
        endpoint_name="scoreboard",
        route_id=f"scoreboard.{marker}",
        route_contract_sha256="b" * 64,
        parameters={"marker": marker},
        mutability=CallMutability.MUTABLE,
    )
    dispatch_identity = "0" * 64
    planning_dependencies = ("c" * 64,)
    planned_bindings_sha256 = planned_route_replacement_bindings_sha256(
        (
            PlannedRouteReplacementBinding(
                requested_scope_sha256=scope.identity_sha256,
                execution_dispatch_identity_sha256=dispatch_identity,
                planning_dependency_identity_sha256s=planning_dependencies,
            ),
        )
    )
    intent = SuccessorUpdateIntent(
        baseline_identity_sha256=baseline.identity_sha256,
        planning_generation_manifest_sha256="0" * 64,
        successor_execution_plan_sha256="1" * 64,
        planned_route_replacement_bindings_sha256=planned_bindings_sha256,
        mode=SuccessorUpdateMode.DAILY,
        source_sha="c" * 40,
        cutoff_utc="2026-08-12T00:00:00Z",
        as_of_utc="2026-08-13T00:00:00Z",
        requested_scopes=(scope,),
    )
    receipt = ObservedDeltaReceipt(
        baseline_identity_sha256=baseline.identity_sha256,
        update_intent_sha256=intent.identity_sha256,
        source_sha=intent.source_sha,
        requested_scope_sha256=scope.identity_sha256,
        execution_dispatch_identity_sha256=dispatch_identity,
        planning_dependency_identity_sha256s=planning_dependencies,
        disposition=DeltaDisposition.OBSERVED,
        logical_call_receipt_sha256="d" * 64,
        prior_persisted_content_sha256="e" * 64,
        source_scope_replacement_sha256="f" * 64,
        persisted_content_sha256="1" * 64,
        persisted_schema_sha256="2" * 64,
        persisted_row_count=1,
    )
    built = SuccessorUpdateTransaction.candidate(
        generation=generation,
        baseline=baseline,
        intent=intent,
    ).mark_built(observed_delta_receipts=(receipt,))
    assert built.build is not None
    assurance = SuccessorAssuranceIdentity(
        baseline_identity_sha256=baseline.identity_sha256,
        update_intent_sha256=intent.identity_sha256,
        source_sha=intent.source_sha,
        generation=generation,
        requested_scopes_sha256=intent.requested_scopes_sha256,
        observed_delta_receipts_sha256=built.build.observed_delta_receipts_sha256,
        planned_route_replacement_bindings_sha256=(
            built.build.planned_route_replacement_bindings_sha256
        ),
        transform_inventory_sha256="3" * 64,
        scan_report_sha256="4" * 64,
        publication_resource_inventory_sha256="5" * 64,
        installed_public_tree_sha256=_candidate_public_tree_sha256(),
        private_generation_receipt_sha256="6" * 64,
        successor_data_tree_fingerprint="7" * 64,
        successor_assured_manifest_sha256="8" * 64,
        successor_validation_report_sha256="9" * 64,
    )
    return built.mark_validated(assurance).promote()


def _candidate(store: SuccessorGenerationStore, transaction: SuccessorUpdateTransaction) -> Path:
    candidate = store.candidate_path(transaction)
    (candidate / "public").mkdir(parents=True)
    (candidate / "public" / "nba.duckdb").write_bytes(b"candidate")
    return candidate


def _states(
    promoted: SuccessorUpdateTransaction,
) -> tuple[
    SuccessorUpdateTransaction,
    SuccessorUpdateTransaction,
    SuccessorUpdateTransaction,
    SuccessorUpdateTransaction,
]:
    assert promoted.build is not None
    assert promoted.assurance is not None
    candidate = SuccessorUpdateTransaction.candidate(
        generation=promoted.generation,
        baseline=promoted.baseline,
        intent=promoted.intent,
    )
    built = candidate.mark_built(observed_delta_receipts=promoted.build.observed_delta_receipts)
    validated = built.mark_validated(promoted.assurance)
    return candidate, built, validated, promoted


def _record_all(
    store: SuccessorGenerationStore,
    candidate_root: Path,
    promoted: SuccessorUpdateTransaction,
) -> None:
    candidate, built, validated, promoted = _states(promoted)
    store.record_transaction(candidate_root, candidate)
    store.record_transaction(candidate_root, built)
    store.record_transaction(candidate_root, validated)
    store.record_promoted_candidate(candidate_root, promoted)


def _candidate_public_tree_sha256() -> str:
    inventory = {
        "digest_domain": "nbadb.installed-public-tree.v2",
        "directories": [],
        "files": [
            {
                "path": "nba.duckdb",
                "bytes": len(b"candidate"),
                "sha256": hashlib.sha256(b"candidate").hexdigest(),
            }
        ],
    }
    return hashlib.sha256(canonical_json_bytes(inventory)).hexdigest()


def _installed_public_tree_sha256(root: Path) -> str:
    return measure_installed_public_tree(root).installed_public_tree_sha256


def _write_current_pointer(store: SuccessorGenerationStore, payload: object) -> None:
    if isinstance(payload, bytes):
        store.pointer_path.write_bytes(payload)
        return
    store.pointer_path.write_bytes(canonical_json_bytes(payload) + b"\n")


def _candidate_for_baseline(
    baseline_public_root: Path,
    *,
    generation: int = 1,
    marker: str = "a",
) -> SuccessorUpdateTransaction:
    baseline_measurement = measure_installed_public_tree(baseline_public_root)
    promoted = _promoted(
        generation,
        marker,
        baseline_installed_public_tree_sha256=(baseline_measurement.installed_public_tree_sha256),
        baseline_installed_public_tree_bytes=baseline_measurement.byte_count,
    )
    candidate, _, _, _ = _states(promoted)
    return candidate


_PUBLICATION_GATE_TESTS = {
    "test_promote_rejects_missing_format_and_parity_or_freshness_failure",
    "test_promote_fails_closed_when_real_inventory_rejects_incomplete_four_format_tree",
    "test_promote_accepts_real_four_format_tree_with_matching_inventory_and_freshness",
}


@pytest.fixture(autouse=True)
def _bypass_publication_gate_for_installed_tree_leaves(
    request: pytest.FixtureRequest,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    if request.node.name.split("[", 1)[0] in _PUBLICATION_GATE_TESTS:
        return
    monkeypatch.setattr(
        SuccessorGenerationStore,
        "_gate_publication_before_promote",
        lambda self, *args, **kwargs: None,
    )


def _prepare(
    store: SuccessorGenerationStore,
    baseline_public_root: Path,
    transaction: SuccessorUpdateTransaction,
    **overrides: object,
) -> Path:
    arguments: dict[str, Any] = {
        "candidate_max_bytes": 1024 * 1024,
        "private_generation_estimated_bytes": 4096,
        "rollback_reserve_bytes": 4096,
        "minimum_free_bytes": 4096,
        "monotonic_now_seconds": 100.0,
        "monotonic_deadline_seconds": 200.0,
        "minimum_deadline_headroom_seconds": 30.0,
    }
    arguments.update(overrides)
    return store.prepare_candidate_from_baseline(
        baseline_public_root,
        transaction,
        **arguments,
    )


def test_promote_atomically_records_current_and_retains_previous(tmp_path: Path) -> None:
    store = SuccessorGenerationStore(tmp_path / "store")
    first = _promoted(1, "a")
    first_root = _candidate(store, first)
    _record_all(store, first_root, first)
    transaction_path = first_root / SUCCESSOR_TRANSACTION_NAME
    pointer = store.promote(first_root, first)

    assert transaction_path.name == SUCCESSOR_TRANSACTION_NAME
    assert pointer["current"]["generation"] == 1
    assert pointer["previous"] is None
    assert store.promote(first_root, first) == pointer

    second = _promoted(2, "b")
    second_root = _candidate(store, second)
    _record_all(store, second_root, second)
    second_pointer = store.promote(second_root, second)

    assert second_pointer["current"]["generation"] == 2
    assert second_pointer["previous"] == pointer["current"]
    assert first_root.is_dir()
    assert second_root.is_dir()
    encoded = (tmp_path / "store" / CURRENT_SUCCESSOR_GENERATION_NAME).read_bytes()
    assert (
        encoded
        == json.dumps(
            second_pointer,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=True,
            allow_nan=False,
        ).encode()
        + b"\n"
    )


def test_promotion_rejects_candidate_mutation_after_assurance(tmp_path: Path) -> None:
    store = SuccessorGenerationStore(tmp_path / "store")
    transaction = _promoted(1, "a")
    candidate = _candidate(store, transaction)
    _record_all(store, candidate, transaction)
    (candidate / "public" / "nba.duckdb").write_bytes(b"mutated-after-assurance")

    with pytest.raises(
        SuccessorGenerationStoreError,
        match="differs from promotion assurance",
    ):
        store.promote(candidate, transaction)

    assert store.read_current() is None


def test_idempotent_promotion_reverifies_frozen_public_bytes(tmp_path: Path) -> None:
    store = SuccessorGenerationStore(tmp_path / "store")
    transaction = _promoted(1, "a")
    candidate = _candidate(store, transaction)
    _record_all(store, candidate, transaction)
    store.promote(candidate, transaction)
    public_file = candidate / "public" / "nba.duckdb"
    public_file.chmod(0o600)
    public_file.write_bytes(b"post-promotion-drift")

    with pytest.raises(
        SuccessorGenerationStoreError,
        match="differs from pointer authority",
    ):
        store.promote(candidate, transaction)

    with pytest.raises(
        SuccessorGenerationStoreError,
        match="differs from pointer authority",
    ):
        store.read_current()


def test_current_read_rejects_empty_directory_injection_after_promotion(tmp_path: Path) -> None:
    store = SuccessorGenerationStore(tmp_path / "store")
    transaction = _promoted(1, "a")
    candidate = _candidate(store, transaction)
    (candidate / "public" / "partitions" / "empty").mkdir(parents=True)
    transaction = replace(
        transaction,
        assurance=replace(
            transaction.promoted_assurance,
            installed_public_tree_sha256=_installed_public_tree_sha256(candidate / "public"),
        ),
    )
    _record_all(store, candidate, transaction)
    pointer = store.promote(candidate, transaction)

    public_root = candidate / "public"
    assert not stat.S_IMODE((public_root / "partitions").stat().st_mode) & 0o222
    assert not stat.S_IMODE((public_root / "partitions" / "empty").stat().st_mode) & 0o222
    public_root.chmod(0o700)
    injected = public_root / "injected-empty"
    injected.mkdir()
    public_root.chmod(0o500)

    with pytest.raises(
        SuccessorGenerationStoreError,
        match="differs from pointer authority",
    ):
        store.read_current()
    assert store.pointer_path.exists()
    assert pointer["current"]["installed_public_tree_sha256"] == (
        transaction.promoted_assurance.installed_public_tree_sha256
    )


def test_current_read_rejects_reversed_freeze_even_without_byte_drift(tmp_path: Path) -> None:
    store = SuccessorGenerationStore(tmp_path / "store")
    transaction = _promoted(1, "a")
    candidate = _candidate(store, transaction)
    _record_all(store, candidate, transaction)
    store.promote(candidate, transaction)

    public_file = candidate / "public" / "nba.duckdb"
    public_file.chmod(0o600)

    with pytest.raises(
        SuccessorGenerationStoreError,
        match="cooperative freeze has been reversed",
    ):
        store.read_current()


def test_promotion_window_blocks_store_writer_then_rejects_frozen_mutation(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store = SuccessorGenerationStore(tmp_path / "store")
    transaction = _promoted(1, "a")
    candidate = _candidate(store, transaction)
    _record_all(store, candidate, transaction)
    freeze_reached = threading.Event()
    mutation_started = threading.Event()
    mutation_finished = threading.Event()
    release_promotion = threading.Event()
    promotion_finished = threading.Event()
    mutation_errors: list[Exception] = []
    promotion_errors: list[Exception] = []
    original_freeze = store._freeze_public_tree

    def pausing_freeze(
        root: Path,
        *,
        inventory: list[dict[str, Any]],
        directories: tuple[str, ...],
    ) -> None:
        original_freeze(root, inventory=inventory, directories=directories)
        freeze_reached.set()
        assert mutation_started.wait(timeout=2)
        assert not mutation_finished.wait(timeout=0.1)
        assert release_promotion.wait(timeout=2)

    monkeypatch.setattr(store, "_freeze_public_tree", pausing_freeze)

    def promote() -> None:
        try:
            store.promote(candidate, transaction)
        except Exception as exc:  # pragma: no cover - asserted below
            promotion_errors.append(exc)
        finally:
            promotion_finished.set()

    def mutate() -> None:
        assert freeze_reached.wait(timeout=2)
        mutation_started.set()
        try:
            with store.candidate_mutation(candidate, transaction) as public:
                (public / "nba.duckdb").write_bytes(b"forbidden")
        except Exception as exc:
            mutation_errors.append(exc)
        finally:
            mutation_finished.set()

    promotion_thread = threading.Thread(target=promote)
    mutation_thread = threading.Thread(target=mutate)
    promotion_thread.start()
    mutation_thread.start()
    assert mutation_started.wait(timeout=2)
    assert not mutation_finished.wait(timeout=0.1)
    release_promotion.set()
    assert promotion_finished.wait(timeout=2)
    assert mutation_finished.wait(timeout=2)
    promotion_thread.join()
    mutation_thread.join()

    assert promotion_errors == []
    assert len(mutation_errors) == 1
    assert isinstance(mutation_errors[0], SuccessorGenerationStoreError)
    assert "public bytes are frozen" in str(mutation_errors[0])
    assert (candidate / "public" / "nba.duckdb").read_bytes() == b"candidate"


@pytest.mark.skipif(os.name != "posix", reason="flock support is POSIX-only")
def test_store_lock_rejects_replaced_path_after_flock(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fcntl = pytest.importorskip("fcntl")
    store = SuccessorGenerationStore(tmp_path / "store")
    store.root.mkdir(parents=True)
    lock_path = store.root / ".successor-generation-store.lock"
    original_flock = fcntl.flock
    replaced = False

    def replacing_flock(descriptor: int, operation: int) -> None:
        nonlocal replaced
        original_flock(descriptor, operation)
        if operation == fcntl.LOCK_EX and not replaced:
            replaced = True
            lock_path.unlink()
            lock_path.write_bytes(b"replacement")

    monkeypatch.setattr(fcntl, "flock", replacing_flock)

    with (
        pytest.raises(
            SuccessorGenerationStoreError,
            match="lock changed after acquisition",
        ),
        store._exclusive_store_lock(),
    ):
        pytest.fail("replaced lock path must not become store authority")

    assert replaced is True


def test_candidate_transaction_is_immutable_and_must_match_promotion(tmp_path: Path) -> None:
    store = SuccessorGenerationStore(tmp_path / "store")
    transaction = _promoted(1, "a")
    candidate = _candidate(store, transaction)
    _record_all(store, candidate, transaction)
    transaction_path = candidate / SUCCESSOR_TRANSACTION_NAME
    transaction_path.write_text("{}\n", encoding="utf-8")

    with pytest.raises(SuccessorGenerationStoreError, match="transaction is invalid"):
        store.record_promoted_candidate(candidate, transaction)
    with pytest.raises(SuccessorGenerationStoreError, match="does not match"):
        store.promote(candidate, transaction)


def test_promotion_requires_exact_path_promoted_state_and_sequential_generation(
    tmp_path: Path,
) -> None:
    empty_store = SuccessorGenerationStore(tmp_path / "empty-store")
    invalid_initial = _promoted(3, "initial-c")
    invalid_initial_root = _candidate(empty_store, invalid_initial)
    _record_all(empty_store, invalid_initial_root, invalid_initial)
    invalid_initial_mode = (invalid_initial_root / "public" / "nba.duckdb").stat().st_mode
    with pytest.raises(SuccessorGenerationStoreError, match="generation one"):
        empty_store.promote(invalid_initial_root, invalid_initial)
    assert (invalid_initial_root / "public" / "nba.duckdb").stat().st_mode == invalid_initial_mode

    store = SuccessorGenerationStore(tmp_path / "store")
    first = _promoted(1, "a")
    first_root = _candidate(store, first)
    _record_all(store, first_root, first)
    store.promote(first_root, first)

    with pytest.raises(SuccessorGenerationStoreError, match="canonical transaction identity"):
        store.record_promoted_candidate(first_root.parent / "other", first)

    candidate_state = replace(first, state=first.state.CANDIDATE, build=None, assurance=None)
    with pytest.raises(SuccessorGenerationStoreError, match="only a validated promoted"):
        store.record_promoted_candidate(first_root, candidate_state)

    third = _promoted(3, "c")
    third_root = _candidate(store, third)
    _record_all(store, third_root, third)
    third_mode = (third_root / "public" / "nba.duckdb").stat().st_mode
    with pytest.raises(SuccessorGenerationStoreError, match="exactly one"):
        store.promote(third_root, third)
    assert (third_root / "public" / "nba.duckdb").stat().st_mode == third_mode


def test_pointer_rejects_noncanonical_tamper_and_candidate_symlink(tmp_path: Path) -> None:
    store = SuccessorGenerationStore(tmp_path / "store")
    transaction = _promoted(1, "a")
    candidate = _candidate(store, transaction)
    _record_all(store, candidate, transaction)
    store.promote(candidate, transaction)
    store.pointer_path.write_text(
        json.dumps(store.read_current(), indent=2) + "\n",
        encoding="utf-8",
    )
    with pytest.raises(SuccessorGenerationStoreError, match="not canonical"):
        store.read_current()

    other_store = SuccessorGenerationStore(tmp_path / "symlink-store")
    other_store.generations_root.mkdir(parents=True)
    target = tmp_path / "outside"
    (target / "public").mkdir(parents=True)
    other_store.candidate_path(transaction).symlink_to(target, target_is_directory=True)
    with pytest.raises(SuccessorGenerationStoreError, match="regular generation directory"):
        other_store.record_promoted_candidate(
            other_store.candidate_path(transaction),
            transaction,
        )


def test_transaction_resume_requires_stable_identity_and_each_state(tmp_path: Path) -> None:
    store = SuccessorGenerationStore(tmp_path / "store")
    promoted = _promoted(1, "a")
    candidate_root = _candidate(store, promoted)
    candidate, built, validated, promoted = _states(promoted)

    store.record_transaction(candidate_root, candidate)
    assert store.load_transaction(candidate_root) == candidate
    with pytest.raises(SuccessorGenerationStoreError, match="exactly one transition"):
        store.record_transaction(candidate_root, validated)
    store.record_transaction(candidate_root, built)
    assert store.load_transaction(candidate_root) == built
    store.record_transaction(candidate_root, validated)
    store.record_transaction(candidate_root, promoted)
    assert store.load_transaction(candidate_root) == promoted

    other = _promoted(1, "b")
    with pytest.raises(SuccessorGenerationStoreError, match="canonical transaction identity"):
        store.record_transaction(candidate_root, other)


def test_control_file_reads_reject_symlinks_without_dereferencing(tmp_path: Path) -> None:
    store = SuccessorGenerationStore(tmp_path / "store")
    promoted = _promoted(1, "a")
    candidate_root = _candidate(store, promoted)
    candidate, _, _, _ = _states(promoted)
    external = tmp_path / "external-transaction.json"
    external.write_text(
        json.dumps(candidate.to_dict(), sort_keys=True, separators=(",", ":")) + "\n",
        encoding="utf-8",
    )
    (candidate_root / SUCCESSOR_TRANSACTION_NAME).symlink_to(external)

    with pytest.raises(SuccessorGenerationStoreError, match="cannot be read safely"):
        store.load_transaction(candidate_root)


@pytest.mark.skipif(not hasattr(os, "mkfifo"), reason="FIFO support is POSIX-only")
def test_control_file_reads_reject_fifo_without_blocking(tmp_path: Path) -> None:
    store = SuccessorGenerationStore(tmp_path / "store")
    store.root.mkdir(parents=True)
    os.mkfifo(store.pointer_path)

    with pytest.raises(SuccessorGenerationStoreError, match="must be a regular file"):
        store.read_current()


def test_prepare_candidate_copies_exact_baseline_and_zero_delta_resume_is_idempotent(
    tmp_path: Path,
) -> None:
    baseline = tmp_path / "baseline-public"
    (baseline / "csv").mkdir(parents=True)
    (baseline / "parquet" / "empty-partition").mkdir(parents=True)
    (baseline / "nba.duckdb").write_bytes(b"baseline-database")
    (baseline / "csv" / "dim_team.csv").write_bytes(b"team_id\n1\n")
    baseline_inventory = inventory_regular_tree(baseline)
    baseline_inode = (baseline / "nba.duckdb").stat().st_ino
    transaction = _candidate_for_baseline(baseline)
    store = SuccessorGenerationStore(tmp_path / "store")

    candidate = _prepare(store, baseline, transaction)
    resumed = _prepare(store, baseline, transaction)

    assert resumed == candidate
    assert inventory_regular_tree(candidate / "public") == baseline_inventory
    assert (candidate / "public" / "parquet" / "empty-partition").is_dir()
    assert (candidate / "public" / "nba.duckdb").stat().st_ino != baseline_inode
    assert store.load_transaction(candidate) == transaction
    baseline_authority = json.loads((candidate / SUCCESSOR_CANDIDATE_BASELINE_NAME).read_bytes())
    assert baseline_authority == {
        "schema_version": 2,
        "kind": "successor_candidate_baseline",
        "generation": transaction.generation,
        "generation_identity_sha256": transaction.generation_identity_sha256,
        "baseline_identity_sha256": transaction.baseline.identity_sha256,
        "baseline_installed_public_tree_sha256": (
            transaction.baseline.installed_public_tree_sha256
        ),
        "baseline_public_file_count": 2,
        "baseline_public_bytes": 27,
    }
    persisted = (candidate / SUCCESSOR_CANDIDATE_BASELINE_NAME).read_bytes() + (
        candidate / SUCCESSOR_TRANSACTION_NAME
    ).read_bytes()
    assert str(tmp_path).encode() not in persisted
    assert inventory_regular_tree(baseline) == baseline_inventory
    assert store.read_current() is None


def test_prepare_candidate_requires_explicit_capacity_and_deadline_headroom(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    baseline = tmp_path / "baseline-public"
    baseline.mkdir()
    (baseline / "nba.duckdb").write_bytes(b"baseline")
    transaction = _candidate_for_baseline(baseline)
    store = SuccessorGenerationStore(tmp_path / "store")

    with pytest.raises(
        SuccessorGenerationStoreError,
        match="deadline headroom is insufficient",
    ):
        _prepare(
            store,
            baseline,
            transaction,
            monotonic_now_seconds=100.0,
            monotonic_deadline_seconds=120.0,
            minimum_deadline_headroom_seconds=21.0,
        )
    assert not store.candidate_path(transaction).exists()

    candidate_max_bytes = 64 * 1024
    required = candidate_max_bytes + 11 + 13 + 17
    monkeypatch.setattr(
        generation_store_module.shutil,
        "disk_usage",
        lambda _path: SimpleNamespace(free=required - 1),
    )
    with pytest.raises(OSError) as error:
        _prepare(
            store,
            baseline,
            transaction,
            candidate_max_bytes=candidate_max_bytes,
            private_generation_estimated_bytes=11,
            rollback_reserve_bytes=13,
            minimum_free_bytes=17,
        )
    assert error.value.errno == errno.ENOSPC
    assert not store.candidate_path(transaction).exists()
    assert not any(store.generations_root.iterdir())


@pytest.mark.parametrize(
    "field_name,bad_value",
    [
        ("candidate_max_bytes", 0),
        ("private_generation_estimated_bytes", False),
        ("rollback_reserve_bytes", -1),
        ("minimum_free_bytes", 0),
        ("monotonic_now_seconds", float("nan")),
        ("monotonic_deadline_seconds", float("inf")),
        ("minimum_deadline_headroom_seconds", 0.0),
    ],
)
def test_prepare_candidate_rejects_missing_or_nonpositive_admission_evidence(
    tmp_path: Path,
    field_name: str,
    bad_value: object,
) -> None:
    baseline = tmp_path / "baseline-public"
    baseline.mkdir()
    (baseline / "nba.duckdb").write_bytes(b"baseline")
    transaction = _candidate_for_baseline(baseline)

    with pytest.raises(ValueError, match=field_name):
        _prepare(
            SuccessorGenerationStore(tmp_path / "store"),
            baseline,
            transaction,
            **{field_name: bad_value},
        )


def test_prepare_candidate_rejects_symlink_and_fifo_baseline_members(
    tmp_path: Path,
) -> None:
    external = tmp_path / "external"
    external.write_bytes(b"outside")
    symlink_baseline = tmp_path / "symlink-baseline"
    symlink_baseline.mkdir()
    (symlink_baseline / "nba.duckdb").write_bytes(b"baseline")
    (symlink_baseline / "escape").symlink_to(external)
    symlink_transaction = _promoted(1, "a")
    symlink_candidate, _, _, _ = _states(symlink_transaction)

    with pytest.raises(SuccessorGenerationStoreError, match="inventoried safely"):
        _prepare(
            SuccessorGenerationStore(tmp_path / "symlink-store"),
            symlink_baseline,
            symlink_candidate,
        )
    assert external.read_bytes() == b"outside"

    if not hasattr(os, "mkfifo"):
        return
    fifo_baseline = tmp_path / "fifo-baseline"
    fifo_baseline.mkdir()
    (fifo_baseline / "nba.duckdb").write_bytes(b"baseline")
    os.mkfifo(fifo_baseline / "blocked")
    fifo_transaction = _promoted(1, "b")
    fifo_candidate, _, _, _ = _states(fifo_transaction)
    with pytest.raises(SuccessorGenerationStoreError, match="inventoried safely"):
        _prepare(
            SuccessorGenerationStore(tmp_path / "fifo-store"),
            fifo_baseline,
            fifo_candidate,
        )


def test_prepare_candidate_resume_requires_exact_partial_delta_inventory(
    tmp_path: Path,
) -> None:
    baseline = tmp_path / "baseline-public"
    baseline.mkdir()
    (baseline / "nba.duckdb").write_bytes(b"baseline")
    transaction = _candidate_for_baseline(baseline)
    store = SuccessorGenerationStore(tmp_path / "store")
    candidate = _prepare(store, baseline, transaction)
    (candidate / "public" / "nba.duckdb").write_bytes(b"successor-delta")
    partial_inventory_sha256 = _installed_public_tree_sha256(candidate / "public")

    with pytest.raises(
        SuccessorGenerationStoreError,
        match="differs from resume authority",
    ):
        _prepare(store, baseline, transaction)
    assert (
        _prepare(
            store,
            baseline,
            transaction,
            expected_resume_installed_public_tree_sha256=partial_inventory_sha256,
        )
        == candidate
    )
    with pytest.raises(
        SuccessorGenerationStoreError,
        match="differs from resume authority",
    ):
        _prepare(
            store,
            baseline,
            transaction,
            expected_resume_installed_public_tree_sha256="f" * 64,
        )
    assert (baseline / "nba.duckdb").read_bytes() == b"baseline"


def test_real_kaggle_snapshot_domains_flow_through_baseline_and_candidate_copy(
    tmp_path: Path,
) -> None:
    staged_public = tmp_path / "kaggle-staged-public"
    staged_public.mkdir()
    client = KaggleClient()
    (staged_public / "payload.bin").write_bytes(b"public-payload")
    (staged_public / "terminal-assurance-report.json").write_bytes(b"{}\n")
    metadata = {
        "id": client._dataset,
        "resources": [
            {"path": "assured-artifact-manifest.json"},
            {"path": "payload.bin"},
            {"path": "terminal-assurance-report.json"},
        ],
    }
    (staged_public / "dataset-metadata.json").write_text(
        json.dumps(metadata, sort_keys=True, separators=(",", ":")) + "\n",
        encoding="utf-8",
    )
    build_assured_artifact_manifest(
        staged_public,
        chain_id="full-initial-20260813",
        source_sha="a" * 40,
        coverage_fingerprint="2" * 64,
    )

    snapshot = client._snapshot_upload_bundle(staged_public)
    assert snapshot["provenance"] is not None
    snapshot["terminal_assurance"] = {
        "chain_id": "full-initial-20260813",
        "source_sha": "a" * 40,
        "coverage_fingerprint": "2" * 64,
        "checkpoint_database_sha256": "4" * 64,
        "checkpoint_report_sha256": "5" * 64,
        "contract_blocked_evidence_sha256": "6" * 64,
        "provider_authority_sha256": "7" * 64,
    }
    baseline = baseline_identity_from_verified_publication(
        snapshot,
        remote_dataset_version=238,
        private_baseline_receipt_sha256="b" * 64,
    )

    assert baseline.remote_bundle_fingerprint_sha256 == snapshot["fingerprint"]
    assert (
        baseline.installed_public_tree_sha256
        == measure_installed_public_tree(staged_public).installed_public_tree_sha256
    )
    assert baseline.remote_bundle_fingerprint_sha256 != baseline.installed_public_tree_sha256

    scope = RequestedRouteScope.from_parameters(
        endpoint_name="scoreboard",
        route_id="scoreboard.real-snapshot",
        route_contract_sha256="c" * 64,
        parameters={"snapshot": "real"},
        mutability=CallMutability.MUTABLE,
    )
    intent = SuccessorUpdateIntent(
        baseline_identity_sha256=baseline.identity_sha256,
        planning_generation_manifest_sha256="d" * 64,
        successor_execution_plan_sha256="e" * 64,
        planned_route_replacement_bindings_sha256="f" * 64,
        mode=SuccessorUpdateMode.DAILY,
        source_sha="e" * 40,
        cutoff_utc="2026-08-12T00:00:00Z",
        as_of_utc="2026-08-13T00:00:00Z",
        requested_scopes=(scope,),
    )
    transaction = SuccessorUpdateTransaction.candidate(
        generation=1,
        baseline=baseline,
        intent=intent,
    )
    store = SuccessorGenerationStore(tmp_path / "store")
    candidate = _prepare(store, staged_public, transaction)

    assert inventory_regular_tree(candidate / "public") == inventory_regular_tree(staged_public)
    assert (
        measure_installed_public_tree(candidate / "public").installed_public_tree_sha256
        == baseline.installed_public_tree_sha256
    )


def test_prepare_candidate_rejects_root_drift_and_existing_path_collision(
    tmp_path: Path,
) -> None:
    baseline = tmp_path / "baseline-public"
    baseline.mkdir()
    (baseline / "nba.duckdb").write_bytes(b"baseline")
    transaction = _candidate_for_baseline(baseline)
    store = SuccessorGenerationStore(tmp_path / "store")
    candidate = _prepare(store, baseline, transaction)
    unexpected = candidate / "unreceipted-state.json"
    unexpected.write_bytes(b"{}\n")

    with pytest.raises(
        SuccessorGenerationStoreError,
        match="unexpected or missing root entries",
    ):
        _prepare(store, baseline, transaction)
    assert unexpected.read_bytes() == b"{}\n"

    other_transaction = _candidate_for_baseline(baseline, generation=2, marker="b")
    collision = store.candidate_path(other_transaction)
    collision.write_bytes(b"preexisting")
    with pytest.raises(
        SuccessorGenerationStoreError,
        match="regular generation directory",
    ):
        _prepare(store, baseline, other_transaction)
    assert collision.read_bytes() == b"preexisting"


def test_prepare_candidate_detects_baseline_mutation_during_copy_and_leaves_no_authority(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    baseline = tmp_path / "baseline-public"
    baseline.mkdir()
    (baseline / "nba.duckdb").write_bytes(b"baseline")
    transaction = _candidate_for_baseline(baseline)
    store = SuccessorGenerationStore(tmp_path / "store")
    original_copy = store._copy_inventory_files

    def mutate_after_copy(
        source_root: Path,
        destination_root: Path,
        inventory: list[dict[str, Any]],
    ) -> None:
        original_copy(source_root, destination_root, inventory)
        (source_root / "nba.duckdb").write_bytes(b"changed")

    monkeypatch.setattr(store, "_copy_inventory_files", mutate_after_copy)
    with pytest.raises(SuccessorGenerationStoreError, match="changed while copying"):
        _prepare(store, baseline, transaction)

    assert not store.candidate_path(transaction).exists()
    assert store.read_current() is None
    assert any(path.name.endswith(".tmp") for path in store.generations_root.iterdir())


def test_prepare_candidate_ignores_crash_temp_and_retains_prior_generation(
    tmp_path: Path,
) -> None:
    store = SuccessorGenerationStore(tmp_path / "store")
    prior = _promoted(1, "a")
    prior_root = _candidate(store, prior)
    _record_all(store, prior_root, prior)
    prior_pointer = store.promote(prior_root, prior)
    pointer_bytes = store.pointer_path.read_bytes()

    baseline = tmp_path / "baseline-public"
    baseline.mkdir()
    (baseline / "nba.duckdb").write_bytes(b"baseline")
    transaction = _candidate_for_baseline(baseline, generation=2, marker="b")
    stale_temp = store.generations_root / f".{store.candidate_name(transaction)}.crashed.tmp"
    stale_temp.mkdir()
    (stale_temp / "partial").write_bytes(b"not authority")

    candidate = _prepare(store, baseline, transaction)

    assert candidate.is_dir()
    assert stale_temp.is_dir()
    assert prior_root.is_dir()
    assert store.pointer_path.read_bytes() == pointer_bytes
    assert store.read_current() == prior_pointer


def test_copy_resume_promote_reject_non_installed_tree_digest_domains(
    tmp_path: Path,
) -> None:
    baseline = tmp_path / "baseline-public"
    baseline.mkdir()
    (baseline / "nba.duckdb").write_bytes(b"baseline")
    store = SuccessorGenerationStore(tmp_path / "store")
    candidate_tx = _candidate_for_baseline(baseline)
    remote_bundle = candidate_tx.baseline.remote_bundle_fingerprint_sha256
    assert remote_bundle != candidate_tx.baseline.installed_public_tree_sha256

    foreign_baseline = replace(
        candidate_tx.baseline,
        installed_public_tree_sha256=remote_bundle,
    )
    foreign_intent = replace(
        candidate_tx.intent,
        baseline_identity_sha256=foreign_baseline.identity_sha256,
    )
    foreign_candidate = SuccessorUpdateTransaction.candidate(
        generation=candidate_tx.generation,
        baseline=foreign_baseline,
        intent=foreign_intent,
    )
    with pytest.raises(
        SuccessorGenerationStoreError,
        match="does not match transaction authority",
    ):
        _prepare(store, baseline, foreign_candidate)
    assert not store.candidate_path(foreign_candidate).exists()

    _prepare(store, baseline, candidate_tx)
    with pytest.raises(
        SuccessorGenerationStoreError,
        match="differs from resume authority",
    ):
        _prepare(
            store,
            baseline,
            candidate_tx,
            expected_resume_installed_public_tree_sha256=remote_bundle,
        )

    promoted = _promoted(1, "a")
    publication_digest = promoted.promoted_assurance.publication_resource_inventory_sha256
    assert publication_digest != promoted.promoted_assurance.installed_public_tree_sha256
    swapped = replace(
        promoted,
        assurance=replace(
            promoted.promoted_assurance,
            installed_public_tree_sha256=publication_digest,
        ),
    )
    candidate_root = _candidate(store, swapped)
    _record_all(store, candidate_root, swapped)
    with pytest.raises(
        SuccessorGenerationStoreError,
        match="differs from promotion assurance",
    ):
        store.promote(candidate_root, swapped)
    assert store.read_current() is None


def test_prepare_candidate_rejects_omitted_empty_directory_topology(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    baseline = tmp_path / "baseline-public"
    (baseline / "csv").mkdir(parents=True)
    (baseline / "parquet" / "empty-partition").mkdir(parents=True)
    (baseline / "nba.duckdb").write_bytes(b"duckdb")
    (baseline / "nba.sqlite").write_bytes(b"sqlite")
    (baseline / "csv" / "dim_team.csv").write_bytes(b"team_id\n1\n")
    transaction = _candidate_for_baseline(baseline)
    store = SuccessorGenerationStore(tmp_path / "store")
    original = store._copy_inventory_directories

    def omit_empty(destination_root: Path, directories: tuple[str, ...]) -> None:
        original(
            destination_root,
            tuple(path for path in directories if path != "parquet/empty-partition"),
        )

    monkeypatch.setattr(store, "_copy_inventory_directories", omit_empty)
    with pytest.raises(
        SuccessorGenerationStoreError,
        match="does not match the admitted baseline",
    ):
        _prepare(store, baseline, transaction)
    assert not store.candidate_path(transaction).exists()
    assert store.read_current() is None


def test_promote_rejects_empty_directory_topology_drift(tmp_path: Path) -> None:
    store = SuccessorGenerationStore(tmp_path / "store")
    transaction = _promoted(1, "a")
    candidate = _candidate(store, transaction)
    empty = candidate / "public" / "partitions" / "empty"
    empty.mkdir(parents=True)
    transaction = replace(
        transaction,
        assurance=replace(
            transaction.promoted_assurance,
            installed_public_tree_sha256=_installed_public_tree_sha256(candidate / "public"),
        ),
    )
    _record_all(store, candidate, transaction)

    injected = candidate / "public" / "injected-empty"
    injected.mkdir()
    with pytest.raises(
        SuccessorGenerationStoreError,
        match="differs from promotion assurance",
    ):
        store.promote(candidate, transaction)
    injected.rmdir()

    empty.rmdir()
    with pytest.raises(
        SuccessorGenerationStoreError,
        match="differs from promotion assurance",
    ):
        store.promote(candidate, transaction)
    assert store.read_current() is None


def test_current_read_rejects_empty_directory_removal_after_promotion(
    tmp_path: Path,
) -> None:
    store = SuccessorGenerationStore(tmp_path / "store")
    transaction = _promoted(1, "a")
    candidate = _candidate(store, transaction)
    empty = candidate / "public" / "partitions" / "empty"
    empty.mkdir(parents=True)
    transaction = replace(
        transaction,
        assurance=replace(
            transaction.promoted_assurance,
            installed_public_tree_sha256=_installed_public_tree_sha256(candidate / "public"),
        ),
    )
    _record_all(store, candidate, transaction)
    store.promote(candidate, transaction)

    (candidate / "public" / "partitions").chmod(0o700)
    empty.rmdir()
    (candidate / "public" / "partitions").chmod(0o500)

    with pytest.raises(
        SuccessorGenerationStoreError,
        match="differs from pointer authority",
    ):
        store.read_current()


def test_current_read_rejects_reversed_directory_freeze(tmp_path: Path) -> None:
    store = SuccessorGenerationStore(tmp_path / "store")
    transaction = _promoted(1, "a")
    candidate = _candidate(store, transaction)
    empty = candidate / "public" / "partitions" / "empty"
    empty.mkdir(parents=True)
    transaction = replace(
        transaction,
        assurance=replace(
            transaction.promoted_assurance,
            installed_public_tree_sha256=_installed_public_tree_sha256(candidate / "public"),
        ),
    )
    _record_all(store, candidate, transaction)
    store.promote(candidate, transaction)

    empty.chmod(0o700)

    with pytest.raises(
        SuccessorGenerationStoreError,
        match="cooperative freeze has been reversed",
    ):
        store.read_current()


def test_read_current_remeasures_topology_under_store_lock(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store = SuccessorGenerationStore(tmp_path / "store")
    transaction = _promoted(1, "a")
    candidate = _candidate(store, transaction)
    _record_all(store, candidate, transaction)
    store.promote(candidate, transaction)

    depths: list[int] = []
    original = generation_store_module.measure_installed_public_tree

    def locked_measure(*args: object, **kwargs: object) -> object:
        depths.append(int(getattr(store._lock_state, "depth", 0)))
        return original(*args, **kwargs)

    monkeypatch.setattr(
        generation_store_module,
        "measure_installed_public_tree",
        locked_measure,
    )
    pointer = store.read_current()

    assert pointer is not None
    assert pointer["current"]["installed_public_tree_sha256"] == (
        transaction.promoted_assurance.installed_public_tree_sha256
    )
    assert depths
    assert all(depth >= 1 for depth in depths)


def test_current_read_rejects_same_size_file_mutation_after_promotion(tmp_path: Path) -> None:
    store = SuccessorGenerationStore(tmp_path / "store")
    transaction = _promoted(1, "a")
    candidate = _candidate(store, transaction)
    _record_all(store, candidate, transaction)
    store.promote(candidate, transaction)

    public_file = candidate / "public" / "nba.duckdb"
    original = public_file.read_bytes()
    mutated = b"C" * len(original)
    assert mutated != original
    public_file.chmod(0o600)
    public_file.write_bytes(mutated)
    public_file.chmod(0o400)

    with pytest.raises(
        SuccessorGenerationStoreError,
        match="differs from pointer authority",
    ):
        store.read_current()


def test_current_read_rejects_symlink_and_special_file_injection_after_promotion(
    tmp_path: Path,
) -> None:
    store = SuccessorGenerationStore(tmp_path / "store")
    transaction = _promoted(1, "a")
    candidate = _candidate(store, transaction)
    _record_all(store, candidate, transaction)
    store.promote(candidate, transaction)

    public_root = candidate / "public"
    outside = tmp_path / "outside.bin"
    outside.write_bytes(b"secret")
    public_root.chmod(0o700)
    (public_root / "escape").symlink_to(outside)
    public_root.chmod(0o500)

    with pytest.raises(
        SuccessorGenerationStoreError,
        match="cannot be inventoried safely",
    ):
        store.read_current()

    public_root.chmod(0o700)
    (public_root / "escape").unlink()
    if hasattr(os, "mkfifo"):
        os.mkfifo(public_root / "blocked")
        public_root.chmod(0o500)
        with pytest.raises(
            SuccessorGenerationStoreError,
            match="cannot be inventoried safely",
        ):
            store.read_current()


def test_current_read_rejects_pointer_reference_that_differs_from_stored_transaction(
    tmp_path: Path,
) -> None:
    store = SuccessorGenerationStore(tmp_path / "store")
    transaction = _promoted(1, "a")
    candidate = _candidate(store, transaction)
    _record_all(store, candidate, transaction)
    pointer = store.promote(candidate, transaction)
    tampered = json.loads(json.dumps(pointer))
    tampered["current"]["transaction_sha256"] = "f" * 64
    _write_current_pointer(store, tampered)

    with pytest.raises(
        SuccessorGenerationStoreError,
        match="differs from stored authority",
    ):
        store.read_current()


def test_current_read_rejects_pointer_tree_digest_that_differs_from_transaction_assurance(
    tmp_path: Path,
) -> None:
    store = SuccessorGenerationStore(tmp_path / "store")
    transaction = _promoted(1, "a")
    candidate = _candidate(store, transaction)
    _record_all(store, candidate, transaction)
    pointer = store.promote(candidate, transaction)
    tampered = json.loads(json.dumps(pointer))
    tampered["current"]["installed_public_tree_sha256"] = "0" * 64
    _write_current_pointer(store, tampered)

    with pytest.raises(
        SuccessorGenerationStoreError,
        match="differs from transaction assurance",
    ):
        store.read_current()


def test_current_read_rejects_demoted_stored_transaction_after_promotion(
    tmp_path: Path,
) -> None:
    store = SuccessorGenerationStore(tmp_path / "store")
    promoted = _promoted(1, "a")
    candidate = _candidate(store, promoted)
    _record_all(store, candidate, promoted)
    store.promote(candidate, promoted)
    _candidate_state, _built, validated, _promoted_state = _states(promoted)
    (candidate / SUCCESSOR_TRANSACTION_NAME).write_bytes(
        canonical_json_bytes(validated.to_dict()) + b"\n"
    )

    with pytest.raises(
        SuccessorGenerationStoreError,
        match="only a validated promoted successor transaction may become current",
    ):
        store.read_current()


@pytest.mark.parametrize(
    ("payload", "match"),
    [
        (b"{not-json\n", "not valid JSON"),
        ([], "unsupported schema"),
        (
            {
                "schema_version": 2,
                "current": {
                    "generation": 1,
                    "candidate_name": "generation-00000001-aaaaaaaaaaaaaaaa",
                    "transaction_sha256": "a" * 64,
                    "assurance_sha256": "b" * 64,
                    "data_tree_fingerprint": "c" * 64,
                    "installed_public_tree_sha256": "d" * 64,
                    "private_generation_receipt_sha256": "e" * 64,
                },
                "previous": None,
                "extra": True,
            },
            "invalid fields",
        ),
        (
            {
                "schema_version": 1,
                "current": {
                    "generation": 1,
                    "candidate_name": "generation-00000001-aaaaaaaaaaaaaaaa",
                    "transaction_sha256": "a" * 64,
                    "assurance_sha256": "b" * 64,
                    "data_tree_fingerprint": "c" * 64,
                    "installed_public_tree_sha256": "d" * 64,
                    "private_generation_receipt_sha256": "e" * 64,
                },
                "previous": None,
            },
            "unsupported schema",
        ),
    ],
)
def test_current_read_rejects_noncanonical_or_unsupported_pointer_payload(
    tmp_path: Path,
    payload: object,
    match: str,
) -> None:
    store = SuccessorGenerationStore(tmp_path / "store")
    transaction = _promoted(1, "a")
    candidate = _candidate(store, transaction)
    _record_all(store, candidate, transaction)
    store.promote(candidate, transaction)
    _write_current_pointer(store, payload)

    with pytest.raises(SuccessorGenerationStoreError, match=match):
        store.read_current()


def test_current_read_rejects_invalid_previous_reference_without_adopting_current(
    tmp_path: Path,
) -> None:
    store = SuccessorGenerationStore(tmp_path / "store")
    transaction = _promoted(1, "a")
    candidate = _candidate(store, transaction)
    _record_all(store, candidate, transaction)
    pointer = store.promote(candidate, transaction)
    tampered = json.loads(json.dumps(pointer))
    tampered["previous"] = {
        "generation": 0,
        "candidate_name": "generation-00000000-aaaaaaaaaaaaaaaa",
        "transaction_sha256": "a" * 64,
        "assurance_sha256": "b" * 64,
        "data_tree_fingerprint": "c" * 64,
        "installed_public_tree_sha256": "d" * 64,
        "private_generation_receipt_sha256": "e" * 64,
    }
    _write_current_pointer(store, tampered)

    with pytest.raises(
        SuccessorGenerationStoreError,
        match="previous successor generation must be a positive integer",
    ):
        store.read_current()


def _rebind_promoted(
    transaction: SuccessorUpdateTransaction,
    public_root: Path,
) -> SuccessorUpdateTransaction:
    return replace(
        transaction,
        assurance=replace(
            transaction.promoted_assurance,
            installed_public_tree_sha256=_installed_public_tree_sha256(public_root),
        ),
    )


def _write_last_load_watermarks(
    public_root: Path,
    *,
    season: str,
    tables: tuple[str, ...] | None = None,
) -> None:
    import duckdb

    names = tables or tuple(sorted(expected_transform_output_tables(include_live=True)))
    connection = duckdb.connect(str(public_root / "nba.duckdb"))
    try:
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS _pipeline_watermarks (
                table_name VARCHAR NOT NULL,
                watermark_type VARCHAR NOT NULL,
                watermark_value VARCHAR,
                last_updated TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                row_count_at_watermark BIGINT,
                PRIMARY KEY (table_name, watermark_type)
            )
            """
        )
        connection.execute("DELETE FROM _pipeline_watermarks")
        for table in names:
            connection.execute(
                "INSERT INTO _pipeline_watermarks "
                "(table_name, watermark_type, watermark_value, row_count_at_watermark) "
                "VALUES (?, 'last_load', ?, 1)",
                [table, season],
            )
    finally:
        connection.close()


def _promoted_four_format_candidate(
    tmp_path: Path,
    *,
    marker: str = "four-format",
    season: str | None = None,
    mutate_csv: str | None = None,
    drop_csv: bool = False,
) -> tuple[SuccessorGenerationStore, Path, SuccessorUpdateTransaction]:
    import polars as pl

    baseline = tmp_path / f"baseline-{marker}"
    baseline.mkdir(parents=True)
    (baseline / "marker.txt").write_bytes(b"baseline")
    store = SuccessorGenerationStore(tmp_path / f"store-{marker}")
    candidate_transaction = _candidate_for_baseline(baseline, marker=marker)
    candidate = _prepare(store, baseline, candidate_transaction)
    public = store.materialize_candidate_public_formats(
        candidate,
        candidate_transaction,
        {"sample": pl.DataFrame({"id": [1], "label": ["alpha"]})},
    )
    leftover = public / "marker.txt"
    if leftover.exists():
        leftover.unlink()
    expected_season = successor_publication_freshness_season(candidate_transaction.intent.as_of_utc)
    _write_last_load_watermarks(
        public,
        season=expected_season if season is None else season,
        tables=("sample",),
    )
    if drop_csv:
        (public / "csv" / "sample.csv").unlink()
    if mutate_csv is not None:
        (public / "csv" / "sample.csv").write_text(mutate_csv, encoding="utf-8")
    promoted = _rebind_promoted(
        _promoted(
            1,
            marker,
            baseline_installed_public_tree_sha256=(
                candidate_transaction.baseline.installed_public_tree_sha256
            ),
            baseline_installed_public_tree_bytes=(
                candidate_transaction.baseline.installed_public_tree_bytes
            ),
        ),
        public,
    )
    _record_all(store, candidate, promoted)
    return store, candidate, promoted


def test_candidate_public_tree_materializes_all_four_formats(tmp_path: Path) -> None:
    import sqlite3

    import duckdb
    import polars as pl

    baseline = tmp_path / "baseline"
    baseline.mkdir()
    (baseline / "marker.txt").write_bytes(b"baseline")
    store = SuccessorGenerationStore(tmp_path / "store")
    transaction = _candidate_for_baseline(baseline)
    candidate = _prepare(store, baseline, transaction)

    public = store.materialize_candidate_public_formats(
        candidate,
        transaction,
        {"sample": pl.DataFrame({"id": [1], "label": ["alpha"]})},
    )

    assert public == candidate / "public"
    assert (public / "nba.duckdb").is_file()
    assert (public / "nba.sqlite").is_file()
    assert (public / "csv" / "sample.csv").is_file()
    assert (public / "parquet" / "sample" / "sample.parquet").is_file()
    duck = duckdb.connect(str(public / "nba.duckdb"), read_only=True)
    try:
        assert duck.execute("SELECT id, label FROM sample").fetchall() == [(1, "alpha")]
    finally:
        duck.close()
    sqlite = sqlite3.connect(public / "nba.sqlite")
    try:
        assert sqlite.execute("SELECT id, label FROM sample").fetchall() == [(1, "alpha")]
    finally:
        sqlite.close()
    assert "alpha" in (public / "csv" / "sample.csv").read_text(encoding="utf-8")


def test_candidate_format_materialization_is_idempotent_and_stays_on_candidate(
    tmp_path: Path,
) -> None:
    import sqlite3

    import duckdb
    import polars as pl

    baseline = tmp_path / "baseline"
    baseline.mkdir()
    baseline_marker = baseline / "marker.txt"
    baseline_marker.write_bytes(b"baseline")
    baseline_bytes = baseline_marker.read_bytes()
    store = SuccessorGenerationStore(tmp_path / "store")
    current_transaction = _promoted(1, "current")
    current_root = _candidate(store, current_transaction)
    _record_all(store, current_root, current_transaction)
    store.promote(current_root, current_transaction)
    current_public = (current_root / "public" / "nba.duckdb").read_bytes()

    transaction = _candidate_for_baseline(baseline, generation=2, marker="next")
    candidate = _prepare(store, baseline, transaction)
    tables = {"sample": pl.DataFrame({"id": [1], "label": ["alpha"]})}
    first = store.materialize_candidate_public_formats(candidate, transaction, tables)
    second = store.materialize_candidate_public_formats(candidate, transaction, tables)

    assert first == second == candidate / "public"
    assert first.is_relative_to(candidate)
    assert not first.is_relative_to(current_root)
    assert (current_root / "public" / "nba.duckdb").read_bytes() == current_public
    assert baseline_marker.read_bytes() == baseline_bytes
    pointer = store.read_current()
    assert pointer is not None
    assert pointer["current"]["candidate_name"] == store.candidate_name(current_transaction)
    duck = duckdb.connect(str(first / "nba.duckdb"), read_only=True)
    try:
        assert duck.execute("SELECT id, label FROM sample").fetchall() == [(1, "alpha")]
    finally:
        duck.close()
    sqlite = sqlite3.connect(first / "nba.sqlite")
    try:
        assert sqlite.execute("SELECT id, label FROM sample").fetchall() == [(1, "alpha")]
    finally:
        sqlite.close()


def test_materialize_candidate_public_formats_rejects_invalid_tables_and_loader_failure(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import polars as pl

    baseline = tmp_path / "baseline"
    baseline.mkdir()
    (baseline / "marker.txt").write_bytes(b"baseline")
    store = SuccessorGenerationStore(tmp_path / "store")
    transaction = _candidate_for_baseline(baseline)
    candidate = _prepare(store, baseline, transaction)
    valid = {"sample": pl.DataFrame({"id": [1]})}

    with pytest.raises(SuccessorGenerationStoreError, match="at least one table"):
        store.materialize_candidate_public_formats(candidate, transaction, {})
    with pytest.raises(SuccessorGenerationStoreError, match="table name is invalid"):
        store.materialize_candidate_public_formats(
            candidate,
            transaction,
            {"not a table": pl.DataFrame({"id": [1]})},
        )
    with pytest.raises(SuccessorGenerationStoreError, match="not a DataFrame"):
        store.materialize_candidate_public_formats(
            candidate,
            transaction,
            {"sample": {"id": [1]}},  # type: ignore[dict-item]
        )

    def failing_loader(*args: object, **kwargs: object) -> None:
        raise RuntimeError("loader exploded")

    monkeypatch.setattr("nbadb.load.multi.create_multi_loader", failing_loader)
    with pytest.raises(SuccessorGenerationStoreError, match="create_multi_loader failed"):
        store.materialize_candidate_public_formats(candidate, transaction, valid)

    assert not (candidate / "public" / "nba.sqlite").exists()
    assert not (candidate / "public" / "csv").exists()
    assert not (candidate / "public" / "parquet").exists()


def test_materialize_candidate_public_formats_rejects_promoted_current(
    tmp_path: Path,
) -> None:
    import polars as pl

    store = SuccessorGenerationStore(tmp_path / "store")
    transaction = _promoted(1, "a")
    candidate = _candidate(store, transaction)
    _record_all(store, candidate, transaction)
    store.promote(candidate, transaction)
    current_bytes = (candidate / "public" / "nba.duckdb").read_bytes()

    with pytest.raises(SuccessorGenerationStoreError, match="frozen"):
        store.materialize_candidate_public_formats(
            candidate,
            transaction,
            {"sample": pl.DataFrame({"id": [1]})},
        )

    assert (candidate / "public" / "nba.duckdb").read_bytes() == current_bytes
    assert not (candidate / "public" / "nba.sqlite").exists()


def test_promote_rejects_missing_format_and_parity_or_freshness_failure(
    tmp_path: Path,
) -> None:
    store = SuccessorGenerationStore(tmp_path / "store")

    missing = _promoted(1, "missing-format")
    missing_root = _candidate(store, missing)
    transaction = _rebind_promoted(missing, missing_root / "public")
    _record_all(store, missing_root, transaction)
    with pytest.raises(
        SuccessorGenerationStoreError,
        match="missing required publication format",
    ):
        store.promote(missing_root, transaction)
    assert store.read_current() is None

    parity_store, parity_root, parity = _promoted_four_format_candidate(
        tmp_path / "parity",
        marker="parity",
        mutate_csv="id,label\n1,alpha\n2,beta\n",
    )
    with pytest.raises(
        SuccessorGenerationStoreError,
        match="publication inventory failed",
    ):
        parity_store.promote(parity_root, parity)
    assert parity_store.read_current() is None

    freshness_store, freshness_root, freshness = _promoted_four_format_candidate(
        tmp_path / "freshness",
        marker="freshness",
        season="2024-25",
    )
    expected_season = successor_publication_freshness_season(freshness.intent.as_of_utc)
    assert expected_season == "2025-26"
    with pytest.raises(
        SuccessorGenerationStoreError,
        match="publication freshness failed",
    ):
        freshness_store.promote(freshness_root, freshness)
    assert freshness_store.read_current() is None


def test_gc_retains_current_and_previous_only_after_durable_success(
    tmp_path: Path,
) -> None:
    store = SuccessorGenerationStore(tmp_path / "store")
    first = _promoted(1, "a")
    first_root = _candidate(store, first)
    _record_all(store, first_root, first)
    store.promote(first_root, first)
    assert store.collect_retired_generations() == ()
    assert first_root.is_dir()

    second = _promoted(2, "b")
    second_root = _candidate(store, second)
    _record_all(store, second_root, second)
    store.promote(second_root, second)
    assert store.collect_retired_generations() == ()
    assert first_root.is_dir()
    assert second_root.is_dir()

    third = _promoted(3, "c")
    third_root = _candidate(store, third)
    _record_all(store, third_root, third)
    store.promote(third_root, third)
    collected = store.collect_retired_generations()
    assert collected == (first_root.name,)
    assert not first_root.exists()
    assert second_root.is_dir()
    assert third_root.is_dir()
    pointer = store.read_current()
    assert pointer is not None
    assert pointer["current"]["generation"] == 3
    assert pointer["previous"]["generation"] == 2

    fourth = _promoted(4, "d")
    fourth_root = _candidate(store, fourth)
    candidate, _, _, _ = _states(fourth)
    store.record_transaction(fourth_root, candidate)
    with pytest.raises(
        SuccessorGenerationStoreError,
        match="candidate, executing, or unassured",
    ):
        store.collect_retired_generations()
    assert second_root.is_dir()
    assert third_root.is_dir()
    assert fourth_root.is_dir()


def _prepared_candidate_for_materialize(
    tmp_path: Path,
) -> tuple[SuccessorGenerationStore, Path, SuccessorUpdateTransaction]:
    baseline = tmp_path / "baseline"
    baseline.mkdir()
    (baseline / "marker.txt").write_bytes(b"baseline")
    store = SuccessorGenerationStore(tmp_path / "store")
    transaction = _candidate_for_baseline(baseline)
    return store, _prepare(store, baseline, transaction), transaction


def test_materialize_candidate_public_formats_rejects_empty_or_invalid_tables(
    tmp_path: Path,
) -> None:
    import polars as pl

    store, candidate, transaction = _prepared_candidate_for_materialize(tmp_path)
    with pytest.raises(
        SuccessorGenerationStoreError,
        match="requires at least one table",
    ):
        store.materialize_candidate_public_formats(candidate, transaction, {})
    with pytest.raises(
        SuccessorGenerationStoreError,
        match="table name is invalid",
    ):
        store.materialize_candidate_public_formats(
            candidate,
            transaction,
            {"": pl.DataFrame({"id": [1]})},
        )
    assert store.read_current() is None
    assert not (candidate / "public" / "nba.sqlite").exists()


def test_materialize_candidate_public_formats_rejects_partial_supported_formats(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import polars as pl

    import nbadb.load.multi as multi_loader

    store, candidate, transaction = _prepared_candidate_for_materialize(tmp_path)
    monkeypatch.setattr(
        multi_loader,
        "SUPPORTED_FORMATS",
        frozenset({"duckdb", "sqlite"}),
    )
    with pytest.raises(
        SuccessorGenerationStoreError,
        match="requires DuckDB, SQLite, CSV, and Parquet",
    ):
        store.materialize_candidate_public_formats(
            candidate,
            transaction,
            {"sample": pl.DataFrame({"id": [1]})},
        )
    assert store.read_current() is None
    assert not (candidate / "public" / "nba.sqlite").exists()


def test_materialize_candidate_public_formats_fails_closed_when_loader_raises(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import polars as pl

    import nbadb.load.multi as multi_loader

    store, candidate, transaction = _prepared_candidate_for_materialize(tmp_path)

    def boom(*args: object, **kwargs: object) -> object:
        raise RuntimeError("loader exploded")

    monkeypatch.setattr(multi_loader, "create_multi_loader", boom)
    with pytest.raises(
        SuccessorGenerationStoreError,
        match="create_multi_loader failed to materialize the candidate public tree",
    ):
        store.materialize_candidate_public_formats(
            candidate,
            transaction,
            {"sample": pl.DataFrame({"id": [1], "label": ["alpha"]})},
        )
    assert store.read_current() is None
    assert not (candidate / "public" / "nba.sqlite").exists()
    assert not (candidate / "public" / "csv").exists()
    assert not (candidate / "public" / "parquet").exists()


def test_materialize_candidate_public_formats_rejects_missing_required_formats(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import polars as pl

    import nbadb.load.multi as multi_loader

    class SilentLoader:
        def load(self, table: str, df: object, mode: str = "replace") -> None:
            return None

    store, candidate, transaction = _prepared_candidate_for_materialize(tmp_path)
    monkeypatch.setattr(
        multi_loader,
        "create_multi_loader",
        lambda *args, **kwargs: SilentLoader(),
    )
    with pytest.raises(
        SuccessorGenerationStoreError,
        match="missing required publication format",
    ):
        store.materialize_candidate_public_formats(
            candidate,
            transaction,
            {"sample": pl.DataFrame({"id": [1], "label": ["alpha"]})},
        )
    assert store.read_current() is None
    assert not (candidate / "public" / "nba.sqlite").exists()
    assert not (candidate / "public" / "csv").exists()
    assert not (candidate / "public" / "parquet").exists()


def test_materialize_candidate_public_formats_rejects_promoted_state(
    tmp_path: Path,
) -> None:
    import polars as pl

    store = SuccessorGenerationStore(tmp_path / "store")
    transaction = _promoted(1, "a")
    candidate = _candidate(store, transaction)
    _record_all(store, candidate, transaction)
    with pytest.raises(
        SuccessorGenerationStoreError,
        match="public bytes are frozen",
    ):
        store.materialize_candidate_public_formats(
            candidate,
            transaction,
            {"sample": pl.DataFrame({"id": [1], "label": ["alpha"]})},
        )
    assert store.read_current() is None


def test_promote_fails_closed_when_real_inventory_rejects_incomplete_four_format_tree(
    tmp_path: Path,
) -> None:
    store, candidate, promoted = _promoted_four_format_candidate(
        tmp_path,
        marker="incomplete",
        drop_csv=True,
    )
    with pytest.raises(
        SuccessorGenerationStoreError,
        match="publication inventory failed",
    ):
        store.promote(candidate, promoted)
    assert store.read_current() is None
    assert not (store.root / CURRENT_SUCCESSOR_GENERATION_NAME).exists()


def test_promote_accepts_real_four_format_tree_with_matching_inventory_and_freshness(
    tmp_path: Path,
) -> None:
    store, candidate, promoted = _promoted_four_format_candidate(tmp_path)
    pointer = store.promote(candidate, promoted)

    assert pointer["current"]["generation"] == 1
    assert pointer["previous"] is None
    assert store.read_current() == pointer
    assert store.promote(candidate, promoted) == pointer
