from __future__ import annotations

import hashlib
import os
import stat
import time
from pathlib import Path

import pytest

from nbadb.orchestrate.successor_coordinator import (
    SuccessorAggregateCapacityContract,
    SuccessorCandidateAdmission,
    SuccessorCoordinatorCheckpoint,
    SuccessorCoordinatorCheckpointStore,
    SuccessorCoordinatorPhase,
)
from nbadb.orchestrate.successor_generation_store import (
    SuccessorGenerationStore,
    SuccessorGenerationStoreError,
)
from nbadb.orchestrate.successor_inventory import measure_installed_public_tree
from nbadb.orchestrate.successor_planner import deterministic_planning_generation_id
from nbadb.orchestrate.successor_planning_contract import SuccessorPlanningRequest
from nbadb.orchestrate.successor_planning_store import (
    PlanningStoreBudget,
    SuccessorPlanningStore,
)
from nbadb.orchestrate.successor_private_planning_retention import (
    PrivatePlanningPlacementKind,
    PrivatePlanningPublicationReceipt,
    PrivatePlanningRetentionError,
    collect_unreferenced_private_planning_state,
    provision_private_planning_storage,
    require_private_planning_storage,
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


def _digest(label: str) -> str:
    return hashlib.sha256(label.encode()).hexdigest()


def _budget() -> PlanningStoreBudget:
    return PlanningStoreBudget(
        generation_max_bytes=16 * 1024 * 1024,
        artifact_max_bytes=4 * 1024 * 1024,
        control_max_bytes=2 * 1024 * 1024,
        minimum_free_bytes=1,
        monotonic_deadline_seconds=1_000.0,
        minimum_deadline_headroom_seconds=100.0,
    )


def _scope(label: str) -> RequestedRouteScope:
    return RequestedRouteScope.from_parameters(
        endpoint_name="scoreboard_v3",
        route_id=f"scoreboard.{label}",
        route_contract_sha256=_digest(f"contract:{label}"),
        parameters={"label": label},
        mutability=CallMutability.MUTABLE,
    )


def _planning_request(label: str = "keep") -> SuccessorPlanningRequest:
    return SuccessorPlanningRequest(
        baseline_identity_sha256=_digest(f"baseline:{label}"),
        mode=SuccessorUpdateMode.DAILY,
        source_sha="b" * 40,
        cutoff_utc="2026-08-01T00:00:00Z",
        as_of_utc="2026-08-02T00:00:00Z",
        workflow_run_id=17,
        workflow_run_attempt=1,
        requested_planning_scopes=(_scope(label),),
    )


def _mode(path: Path) -> int:
    return stat.S_IMODE(os.stat(path, follow_symlinks=False).st_mode)


def _public_root(tmp_path: Path) -> Path:
    public = tmp_path / "public"
    public.mkdir()
    (public / "dataset.duckdb").write_bytes(b"public")
    return public.resolve()


def _provisioned_store(
    tmp_path: Path,
    *,
    with_captures: bool = False,
) -> tuple[SuccessorPlanningStore, Path, Path | None, Path | None]:
    public = _public_root(tmp_path)
    placement = provision_private_planning_storage(
        planning_store_root=(tmp_path / "private-planning").resolve(),
        public_roots=(public,),
        monotonic_clock=lambda: 100.0,
        planning_capture_root=(
            (tmp_path / "private-planning-capture").resolve() if with_captures else None
        ),
        update_capture_root=(
            (tmp_path / "private-update-capture").resolve() if with_captures else None
        ),
    )
    store = SuccessorPlanningStore(
        placement.planning_store_root,
        public_roots=(public,),
        monotonic_clock=lambda: 100.0,
    )
    return (
        store,
        public,
        placement.planning_capture_root,
        placement.update_capture_root,
    )


def _capacity(baseline_bytes: int) -> SuccessorAggregateCapacityContract:
    return SuccessorAggregateCapacityContract(
        baseline_installed_public_tree_bytes=baseline_bytes,
        planning_store_generation_max_bytes=1,
        planning_store_artifact_max_bytes=1,
        planning_store_control_max_bytes=1,
        planning_driver_database_max_bytes=1,
        planning_wave_count=2,
        planning_wave_capture_max_bytes=1,
        planning_wave_checkpoint_max_bytes=1,
        update_capture_max_bytes=1,
        update_checkpoint_max_bytes=1,
        candidate_max_bytes=1_000_000,
        rollback_reserve_bytes=1,
        coordinator_checkpoint_max_bytes=1,
        terminal_receipt_max_bytes=1,
        runtime_log_max_bytes=1,
        scan_database_snapshot_max_bytes=1,
        inventory_duckdb_snapshot_max_bytes=1,
        inventory_sqlite_snapshot_max_bytes=1,
        transform_scratch_max_bytes=1,
        assurance_control_max_bytes=1,
        minimum_free_bytes=1,
    )


def _requested_checkpoint(
    *,
    public_root: Path,
    planning_request: SuccessorPlanningRequest,
) -> tuple[SuccessorCoordinatorCheckpoint, SuccessorPlanningRequest]:
    measured = measure_installed_public_tree(public_root)
    baseline = BaselineAssuranceIdentity(
        remote_dataset="maintainer/nbadb",
        remote_dataset_version=237,
        chain_id="assured-parent",
        source_sha="a" * 40,
        coverage_fingerprint=_digest("coverage"),
        data_tree_fingerprint=_digest("tree"),
        remote_bundle_fingerprint_sha256=_digest("remote"),
        installed_public_tree_sha256=measured.installed_public_tree_sha256,
        installed_public_tree_bytes=measured.byte_count,
        assured_manifest_sha256=_digest("manifest"),
        terminal_assurance_report_sha256=_digest("report"),
        private_baseline_receipt_sha256=_digest("baseline-private"),
        checkpoint_database_sha256=_digest("db"),
        checkpoint_report_sha256=_digest("checkpoint"),
        contract_blocked_evidence_sha256=_digest("blocked"),
        provider_authority_sha256=_digest("provider"),
    )
    request = SuccessorPlanningRequest(
        baseline_identity_sha256=baseline.identity_sha256,
        mode=planning_request.mode,
        source_sha=planning_request.source_sha,
        cutoff_utc=planning_request.cutoff_utc,
        as_of_utc=planning_request.as_of_utc,
        workflow_run_id=planning_request.workflow_run_id,
        workflow_run_attempt=planning_request.workflow_run_attempt,
        requested_planning_scopes=planning_request.requested_planning_scopes,
    )
    return (
        SuccessorCoordinatorCheckpoint(
            phase=SuccessorCoordinatorPhase.REQUESTED,
            baseline=baseline,
            planning_request=request,
            generation=1,
            candidate_admission=SuccessorCandidateAdmission(
                aggregate_capacity=_capacity(baseline.installed_public_tree_bytes),
                monotonic_deadline_seconds=1000.0,
                minimum_pre_provider_headroom_seconds=20.0,
                minimum_deadline_headroom_seconds=10.0,
                monotonic_epoch_sha256=_digest("monotonic-epoch"),
            ),
        ),
        request,
    )


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


def _promoted(
    generation: int,
    marker: str,
    *,
    planning_generation_manifest_sha256: str,
    private_baseline_receipt_sha256: str,
    private_generation_receipt_sha256: str,
) -> SuccessorUpdateTransaction:
    baseline = BaselineAssuranceIdentity(
        remote_dataset="maintainer/nbadb",
        remote_dataset_version=237,
        chain_id="full-initial",
        source_sha="a" * 40,
        coverage_fingerprint="1" * 64,
        data_tree_fingerprint="2" * 64,
        remote_bundle_fingerprint_sha256="b" * 64,
        installed_public_tree_sha256="3" * 64,
        installed_public_tree_bytes=len(b"synthetic-baseline-public"),
        assured_manifest_sha256="4" * 64,
        terminal_assurance_report_sha256="5" * 64,
        private_baseline_receipt_sha256=private_baseline_receipt_sha256,
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
    planned_bindings = planned_route_replacement_bindings_sha256(
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
        planning_generation_manifest_sha256=planning_generation_manifest_sha256,
        successor_execution_plan_sha256="1" * 64,
        planned_route_replacement_bindings_sha256=planned_bindings,
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
        private_generation_receipt_sha256=private_generation_receipt_sha256,
        successor_data_tree_fingerprint="7" * 64,
        successor_assured_manifest_sha256="8" * 64,
        successor_validation_report_sha256="9" * 64,
    )
    return built.mark_validated(assurance).promote()


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


def _candidate(store: SuccessorGenerationStore, transaction: SuccessorUpdateTransaction) -> Path:
    candidate = store.candidate_path(transaction)
    (candidate / "public").mkdir(parents=True)
    (candidate / "public" / "nba.duckdb").write_bytes(b"candidate")
    return candidate


@pytest.fixture(autouse=True)
def _bypass_publication_gate(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        SuccessorGenerationStore,
        "_gate_publication_before_promote",
        lambda self, *args, **kwargs: None,
    )


def test_provision_creates_owner_only_planning_layout(tmp_path: Path) -> None:
    public = _public_root(tmp_path)
    placement = provision_private_planning_storage(
        planning_store_root=(tmp_path / "private-planning").resolve(),
        public_roots=(public,),
        monotonic_clock=lambda: 100.0,
        planning_capture_root=(tmp_path / "private-planning-capture").resolve(),
        update_capture_root=(tmp_path / "private-update-capture").resolve(),
        placement_kind=PrivatePlanningPlacementKind.FIXTURE,
        encryption_at_rest_attested=False,
    )
    assert placement.kind is PrivatePlanningPlacementKind.FIXTURE
    assert placement.application_encryption is False
    assert placement.encryption_at_rest_attested is False
    assert _mode(placement.planning_store_root) == 0o700
    assert _mode(placement.planning_store_root / "objects") == 0o700
    assert _mode(placement.planning_store_root / "generations") == 0o700
    assert _mode(placement.planning_store_root / ".successor-planning-store.lock") == 0o600
    assert placement.planning_capture_root is not None
    assert placement.update_capture_root is not None
    assert _mode(placement.planning_capture_root) == 0o700
    assert _mode(placement.update_capture_root) == 0o700
    required = require_private_planning_storage(
        planning_store_root=placement.planning_store_root,
        public_roots=(public,),
        monotonic_clock=lambda: 100.0,
        planning_capture_root=placement.planning_capture_root,
        update_capture_root=placement.update_capture_root,
    )
    assert required.planning_store_root == placement.planning_store_root
    assert required.identity_sha256 == placement.identity_sha256


def test_provision_rejects_relative_symlink_overlap_and_group_readable(
    tmp_path: Path,
) -> None:
    public = _public_root(tmp_path)
    with pytest.raises(PrivatePlanningRetentionError, match="must be an absolute Path"):
        provision_private_planning_storage(
            planning_store_root=Path("relative-planning"),
            public_roots=(public,),
            monotonic_clock=lambda: 100.0,
        )

    alias_parent = tmp_path / "alias-parent"
    alias_parent.mkdir()
    target = tmp_path / "real-planning"
    target.mkdir()
    linked = alias_parent / "linked"
    linked.symlink_to(target)
    with pytest.raises(PrivatePlanningRetentionError, match="symlink"):
        provision_private_planning_storage(
            planning_store_root=linked,
            public_roots=(public,),
            monotonic_clock=lambda: 100.0,
        )

    nested = public / "nested-private"
    with pytest.raises(PrivatePlanningRetentionError, match="must not overlap a public tree"):
        provision_private_planning_storage(
            planning_store_root=nested,
            public_roots=(public,),
            monotonic_clock=lambda: 100.0,
        )

    shared = tmp_path / "shared-planning"
    shared.mkdir(mode=0o755)
    shared.chmod(0o755)
    with pytest.raises(PrivatePlanningRetentionError, match="owner-only mode 0700"):
        provision_private_planning_storage(
            planning_store_root=shared.resolve(),
            public_roots=(public,),
            monotonic_clock=lambda: 100.0,
        )


def test_production_placement_requires_encryption_attestation(tmp_path: Path) -> None:
    public = _public_root(tmp_path)
    with pytest.raises(
        PrivatePlanningRetentionError,
        match="encryption-at-rest attestation",
    ):
        provision_private_planning_storage(
            planning_store_root=(tmp_path / "prod-planning").resolve(),
            public_roots=(public,),
            monotonic_clock=lambda: 100.0,
            placement_kind=PrivatePlanningPlacementKind.PRODUCTION,
            encryption_at_rest_attested=False,
        )
    placement = provision_private_planning_storage(
        planning_store_root=(tmp_path / "prod-planning").resolve(),
        public_roots=(public,),
        monotonic_clock=lambda: 100.0,
        placement_kind=PrivatePlanningPlacementKind.PRODUCTION,
        encryption_at_rest_attested=True,
    )
    assert placement.kind is PrivatePlanningPlacementKind.PRODUCTION
    assert placement.encryption_at_rest_attested is True
    assert placement.application_encryption is False


def test_require_rejects_unprovisioned_owner_only_directory(tmp_path: Path) -> None:
    public = _public_root(tmp_path)
    empty = tmp_path / "empty-private"
    empty.mkdir(mode=0o700)
    empty.chmod(0o700)
    with pytest.raises(PrivatePlanningRetentionError, match="lock cannot be acquired"):
        require_private_planning_storage(
            planning_store_root=empty.resolve(),
            public_roots=(public,),
            monotonic_clock=lambda: 100.0,
        )


def test_gc_deletes_unreferenced_planning_generation_and_retains_named_identity(
    tmp_path: Path,
) -> None:
    store, _public, _capture, _update = _provisioned_store(tmp_path)
    kept_request = _planning_request("keep")
    dropped_request = _planning_request("drop")
    kept = store.begin_generation(kept_request, "keep-generation", budget=_budget())
    dropped = store.begin_generation(dropped_request, "drop-generation", budget=_budget())
    generation_store = SuccessorGenerationStore(tmp_path / "generation-store")
    checkpoint_store = SuccessorCoordinatorCheckpointStore(tmp_path / "checkpoint.json")
    report = collect_unreferenced_private_planning_state(
        planning_store=store,
        generation_store=generation_store,
        checkpoint_store=checkpoint_store,
        budget=_budget(),
        unresolved_publication_receipts=(
            PrivatePlanningPublicationReceipt(
                planning_generation_identity_sha256=kept.generation_identity_sha256,
            ),
        ),
    )
    assert report.deleted_planning_generation_identity_sha256s == (
        dropped.generation_identity_sha256,
    )
    assert report.retained_planning_generation_identity_sha256s == (
        kept.generation_identity_sha256,
    )
    assert not store.generation_path(dropped_request, "drop-generation").exists()
    assert store.generation_path(kept_request, "keep-generation").is_dir()
    assert all(len(item) == 64 for item in report.deleted_planning_generation_identity_sha256s)


def test_gc_retains_current_and_previous_receipts_and_collects_older(
    tmp_path: Path,
) -> None:
    store, _public, _capture, _update = _provisioned_store(tmp_path)
    older = store.begin_generation(_planning_request("older"), "older", budget=_budget())
    previous = store.begin_generation(_planning_request("previous"), "previous", budget=_budget())
    current = store.begin_generation(_planning_request("current"), "current", budget=_budget())
    generation_store = SuccessorGenerationStore(tmp_path / "generation-store")
    first = _promoted(
        1,
        "a",
        planning_generation_manifest_sha256=older.generation_identity_sha256,
        private_baseline_receipt_sha256=_digest("baseline-a"),
        private_generation_receipt_sha256=_digest("update-a"),
    )
    first_root = _candidate(generation_store, first)
    _record_all(generation_store, first_root, first)
    generation_store.promote(first_root, first)
    second = _promoted(
        2,
        "b",
        planning_generation_manifest_sha256=previous.generation_identity_sha256,
        private_baseline_receipt_sha256=_digest("baseline-b"),
        private_generation_receipt_sha256=_digest("update-b"),
    )
    second_root = _candidate(generation_store, second)
    _record_all(generation_store, second_root, second)
    generation_store.promote(second_root, second)
    third = _promoted(
        3,
        "c",
        planning_generation_manifest_sha256=current.generation_identity_sha256,
        private_baseline_receipt_sha256=_digest("baseline-c"),
        private_generation_receipt_sha256=_digest("update-c"),
    )
    third_root = _candidate(generation_store, third)
    _record_all(generation_store, third_root, third)
    generation_store.promote(third_root, third)
    report = collect_unreferenced_private_planning_state(
        planning_store=store,
        generation_store=generation_store,
        checkpoint_store=SuccessorCoordinatorCheckpointStore(tmp_path / "checkpoint.json"),
        budget=_budget(),
    )
    assert older.generation_identity_sha256 in report.deleted_planning_generation_identity_sha256s
    assert previous.generation_identity_sha256 in (
        report.retained_planning_generation_identity_sha256s
    )
    assert current.generation_identity_sha256 in (
        report.retained_planning_generation_identity_sha256s
    )
    assert store.generation_path(_planning_request("previous"), "previous").is_dir()
    assert store.generation_path(_planning_request("current"), "current").is_dir()
    assert not store.generation_path(_planning_request("older"), "older").exists()


def test_gc_retains_unresolved_checkpoint_and_publication_receipts(
    tmp_path: Path,
) -> None:
    store, public, _capture, _update = _provisioned_store(tmp_path)
    checkpoint, live_request = _requested_checkpoint(
        public_root=public,
        planning_request=_planning_request("live"),
    )
    live_id = deterministic_planning_generation_id(live_request)
    live = store.begin_generation(live_request, live_id, budget=_budget())
    extra = store.begin_generation(_planning_request("extra"), "extra", budget=_budget())
    named = store.begin_generation(_planning_request("named"), "named", budget=_budget())
    assert (
        store.generation_identity(checkpoint.planning_request, live_id)
        == live.generation_identity_sha256
    )
    checkpoint_store = SuccessorCoordinatorCheckpointStore(tmp_path / "checkpoint.json")
    checkpoint_store.write(checkpoint)
    report = collect_unreferenced_private_planning_state(
        planning_store=store,
        generation_store=SuccessorGenerationStore(tmp_path / "generation-store"),
        checkpoint_store=checkpoint_store,
        budget=_budget(),
        unresolved_publication_receipts=(
            PrivatePlanningPublicationReceipt(
                planning_generation_identity_sha256=named.generation_identity_sha256,
            ),
        ),
    )
    assert extra.generation_identity_sha256 in report.deleted_planning_generation_identity_sha256s
    assert live.generation_identity_sha256 in report.retained_planning_generation_identity_sha256s
    assert named.generation_identity_sha256 in report.retained_planning_generation_identity_sha256s


def test_gc_refuses_candidate_public_generation(tmp_path: Path) -> None:
    store, _public, _capture, _update = _provisioned_store(tmp_path)
    kept = store.begin_generation(_planning_request("keep"), "keep", budget=_budget())
    generation_store = SuccessorGenerationStore(tmp_path / "generation-store")
    first = _promoted(
        1,
        "a",
        planning_generation_manifest_sha256=kept.generation_identity_sha256,
        private_baseline_receipt_sha256=_digest("baseline-a"),
        private_generation_receipt_sha256=_digest("update-a"),
    )
    first_root = _candidate(generation_store, first)
    _record_all(generation_store, first_root, first)
    generation_store.promote(first_root, first)
    pending = _promoted(
        2,
        "b",
        planning_generation_manifest_sha256=_digest("pending-manifest"),
        private_baseline_receipt_sha256=_digest("baseline-b"),
        private_generation_receipt_sha256=_digest("update-b"),
    )
    pending_root = _candidate(generation_store, pending)
    candidate, _, _, _ = _states(pending)
    generation_store.record_transaction(pending_root, candidate)
    with pytest.raises(
        PrivatePlanningRetentionError,
        match="candidate, executing, or unassured",
    ):
        collect_unreferenced_private_planning_state(
            planning_store=store,
            generation_store=generation_store,
            checkpoint_store=SuccessorCoordinatorCheckpointStore(tmp_path / "checkpoint.json"),
            budget=_budget(),
        )
    assert store.generation_path(_planning_request("keep"), "keep").is_dir()


def test_gc_does_not_delete_referenced_generation_because_of_age(tmp_path: Path) -> None:
    store, _public, _capture, _update = _provisioned_store(tmp_path)
    kept = store.begin_generation(_planning_request("keep"), "keep", budget=_budget())
    generation_path = store.generation_path(_planning_request("keep"), "keep")
    old = time.time() - (400 * 24 * 60 * 60)
    os.utime(generation_path, (old, old))
    report = collect_unreferenced_private_planning_state(
        planning_store=store,
        generation_store=SuccessorGenerationStore(tmp_path / "generation-store"),
        checkpoint_store=SuccessorCoordinatorCheckpointStore(tmp_path / "checkpoint.json"),
        budget=_budget(),
        unresolved_publication_receipts=(
            PrivatePlanningPublicationReceipt(
                planning_generation_identity_sha256=kept.generation_identity_sha256,
            ),
        ),
    )
    assert report.deleted_planning_generation_identity_sha256s == ()
    assert generation_path.is_dir()


def test_gc_collects_unpublished_tmp_generation_unreferenced_object_and_bronze(
    tmp_path: Path,
) -> None:
    store, _public, capture_root, update_root = _provisioned_store(tmp_path, with_captures=True)
    assert capture_root is not None
    assert update_root is not None
    kept = store.begin_generation(_planning_request("keep"), "keep-generation", budget=_budget())
    orphan_object = store.objects_root / "member" / ("ab" * 32)
    orphan_object.write_bytes(b"orphan-object")
    orphan_object.chmod(0o400)
    tmp_generation = store.generations_root / f".generation-{'cd' * 32}.1.deadbeef.tmp"
    tmp_generation.mkdir(mode=0o700)
    (tmp_generation / "request.json").write_bytes(b"{}")
    retained_bronze = capture_root / "keep-generation"
    retained_bronze.mkdir(mode=0o700)
    orphan_bronze = capture_root / "orphan-bronze"
    orphan_bronze.mkdir(mode=0o700)
    (orphan_bronze / "blob").write_bytes(b"parser-input")
    update_orphan = update_root / ("ef" * 32)
    update_orphan.mkdir(mode=0o700)
    report = collect_unreferenced_private_planning_state(
        planning_store=store,
        generation_store=SuccessorGenerationStore(tmp_path / "generation-store"),
        checkpoint_store=SuccessorCoordinatorCheckpointStore(tmp_path / "checkpoint.json"),
        budget=_budget(),
        planning_capture_root=capture_root,
        update_capture_root=update_root,
        unresolved_publication_receipts=(
            PrivatePlanningPublicationReceipt(
                planning_generation_identity_sha256=kept.generation_identity_sha256,
                planning_generation_id="keep-generation",
            ),
        ),
    )
    assert not tmp_generation.exists()
    assert not orphan_object.exists()
    assert not orphan_bronze.exists()
    assert not update_orphan.exists()
    assert retained_bronze.is_dir()
    assert ("ab" * 32) in report.deleted_planning_object_sha256s
    assert ("ef" * 32) in report.deleted_bronze_generation_identity_sha256s
    assert hashlib.sha256(b"orphan-bronze").hexdigest() in (
        report.deleted_bronze_generation_identity_sha256s
    )


def test_retained_private_receipts_require_previous_directory(
    tmp_path: Path,
) -> None:
    store = SuccessorGenerationStore(tmp_path / "generation-store")
    first = _promoted(
        1,
        "a",
        planning_generation_manifest_sha256=_digest("one"),
        private_baseline_receipt_sha256=_digest("baseline-a"),
        private_generation_receipt_sha256=_digest("update-a"),
    )
    first_root = _candidate(store, first)
    _record_all(store, first_root, first)
    store.promote(first_root, first)
    second = _promoted(
        2,
        "b",
        planning_generation_manifest_sha256=_digest("two"),
        private_baseline_receipt_sha256=_digest("baseline-b"),
        private_generation_receipt_sha256=_digest("update-b"),
    )
    second_root = _candidate(store, second)
    _record_all(store, second_root, second)
    store.promote(second_root, second)
    for root, dir_names, file_names in os.walk(first_root, topdown=True, followlinks=False):
        root_path = Path(root)
        os.chmod(root_path, 0o700)
        for name in (*dir_names, *file_names):
            child = root_path / name
            os.chmod(child, 0o700 if child.is_dir() else 0o600)
    for root, dir_names, file_names in os.walk(first_root, topdown=False, followlinks=False):
        root_path = Path(root)
        for name in file_names:
            (root_path / name).unlink()
        for name in dir_names:
            (root_path / name).rmdir()
    first_root.rmdir()
    with pytest.raises(SuccessorGenerationStoreError, match="retained previous generation"):
        store.retained_private_receipts()
