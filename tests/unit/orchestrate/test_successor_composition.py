from __future__ import annotations

import asyncio
import hashlib
import json
import os
import shutil
from dataclasses import replace
from types import SimpleNamespace
from typing import TYPE_CHECKING, Any

import pytest

from nbadb.contracts.staging_route_contract import staging_route_contract_bundle
from nbadb.core.artifact_identity import (
    ASSURED_ARTIFACT_MANIFEST_NAME,
    build_assured_artifact_manifest,
)
from nbadb.core.config import NbaDbSettings
from nbadb.core.nba_api_provenance import expected_nba_api_provider_authority
from nbadb.extract.bronze import BronzeLimits
from nbadb.extract.raw_request_capture import RawRequestCaptureContextV2
from nbadb.extract.registry import EndpointRegistry
from nbadb.orchestrate.capture_session import CaptureRunScope
from nbadb.orchestrate.scanner import ScanReport
from nbadb.orchestrate.successor_composition import (
    ExactSuccessorComposition,
    ExactSuccessorCompositionConfig,
    ExactSuccessorCompositionError,
    ExactSuccessorTopologyAuthority,
    _BoundSuccessorCoordinatorCheckpointStore,
    _is_exact_promoted_reentry,
    build_exact_successor_composition,
    build_production_successor_w2_authority_resources,
)
from nbadb.orchestrate.successor_coordinator import (
    SuccessorAggregateCapacityContract,
    SuccessorCandidateAdmission,
    SuccessorCoordinatorCheckpoint,
    SuccessorCoordinatorCheckpointStore,
    SuccessorCoordinatorError,
    SuccessorCoordinatorPhase,
    SuccessorCoordinatorRequest,
    require_successor_downstream_publication,
)
from nbadb.orchestrate.successor_generation_store import (
    CURRENT_SUCCESSOR_GENERATION_NAME,
    SUCCESSOR_TRANSACTION_NAME,
    SuccessorGenerationStore,
    SuccessorGenerationStoreError,
)
from nbadb.orchestrate.successor_inventory import measure_installed_public_tree
from nbadb.orchestrate.successor_planner import ConcreteSuccessorPlanningExecutor
from nbadb.orchestrate.successor_planning_capture_resolver import (
    RetainedBronzePlanningResolver,
)
from nbadb.orchestrate.successor_planning_driver import RequestDrivenSuccessorPlanningDriver
from nbadb.orchestrate.successor_planning_request_builder import (
    build_successor_planning_request,
)
from nbadb.orchestrate.successor_planning_runtime import (
    ExactPlanningRuntimeError,
    ExtractorPlanningExactCallRuntime,
    unavailable_live_plan_binding_factory,
)
from nbadb.orchestrate.successor_planning_store import PlanningStoreBudget, SuccessorPlanningStore
from nbadb.orchestrate.successor_runtime import ExactPlanSuccessorRuntimeFactory
from nbadb.orchestrate.successor_update_contract import (
    BaselineAssuranceIdentity,
    SuccessorUpdateMode,
    canonical_sha256,
)
from nbadb.orchestrate.w2_source_call_preparation import W2SourceCallPreparationRuntime
from tests.unit.orchestrate.test_successor_coordinator import _harness
from tests.unit.orchestrate.test_successor_generation_store import (
    _candidate,
    _candidate_for_baseline,
    _prepare,
    _promoted,
    _record_all,
    _states,
)
from tests.unit.orchestrate.test_successor_planning_driver import (
    _Resolver,
    _SemanticRuntime,
)
from tests.unit.orchestrate.test_successor_planning_runtime import (
    _w2_resources,
)

if TYPE_CHECKING:
    from pathlib import Path


def _digest(label: str) -> str:
    return hashlib.sha256(label.encode()).hexdigest()


def _mkdir_private(path: Path) -> Path:
    path.mkdir(mode=0o700, parents=True)
    path.chmod(0o700)
    return path.resolve()


def _limits() -> BronzeLimits:
    return BronzeLimits(
        max_response_bytes=1_000_000,
        max_generation_stored_bytes=100_000_000,
        minimum_free_bytes=1,
        max_receipt_bytes=1_000_000,
        max_receipt_count=10_000,
        max_checkpoint_bytes=10_000_000,
        minimum_deadline_headroom_seconds=10.0,
    )


def _budget() -> PlanningStoreBudget:
    return PlanningStoreBudget(
        generation_max_bytes=100_000_000,
        artifact_max_bytes=10_000_000,
        control_max_bytes=10_000_000,
        minimum_free_bytes=1,
        monotonic_deadline_seconds=1_000.0,
        minimum_deadline_headroom_seconds=10.0,
    )


def _capacity(
    baseline_installed_public_tree_bytes: int,
    *,
    candidate_max_bytes: int = 1_000_000_000,
) -> SuccessorAggregateCapacityContract:
    return SuccessorAggregateCapacityContract(
        baseline_installed_public_tree_bytes=baseline_installed_public_tree_bytes,
        planning_store_generation_max_bytes=100_000_000,
        planning_store_artifact_max_bytes=10_000_000,
        planning_store_control_max_bytes=10_000_000,
        planning_driver_database_max_bytes=10_000_000,
        planning_wave_count=2,
        planning_wave_capture_max_bytes=100_000_000,
        planning_wave_checkpoint_max_bytes=10_000_000,
        update_capture_max_bytes=100_000_000,
        update_checkpoint_max_bytes=10_000_000,
        candidate_max_bytes=candidate_max_bytes,
        rollback_reserve_bytes=1,
        coordinator_checkpoint_max_bytes=10_000_000,
        terminal_receipt_max_bytes=1_000_000,
        runtime_log_max_bytes=10_000_000,
        scan_database_snapshot_max_bytes=candidate_max_bytes,
        inventory_duckdb_snapshot_max_bytes=candidate_max_bytes,
        inventory_sqlite_snapshot_max_bytes=candidate_max_bytes,
        transform_scratch_max_bytes=candidate_max_bytes,
        assurance_control_max_bytes=64 * 1024 * 1024,
        minimum_free_bytes=1,
    )


def _passing_scan(_connection: object) -> ScanReport:
    return ScanReport(findings=[], tables_scanned=0, checks_run=0, duration_seconds=0.0)


def _planning_registry() -> EndpointRegistry:
    registry = EndpointRegistry()
    for endpoint_name in sorted(
        {route.endpoint_name for route in staging_route_contract_bundle().routes}
    ):
        extractor = type(
            f"Synthetic{endpoint_name.title().replace('_', '')}",
            (),
            {"endpoint_name": endpoint_name},
        )
        registry.register(extractor)  # ty: ignore[invalid-argument-type]
    return registry


def _layout(tmp_path: Path) -> dict[str, Path]:
    root = tmp_path.resolve()
    generation_store = _mkdir_private(root / "generation-store")
    _mkdir_private(generation_store / "generations")
    paths = {
        "root": root,
        "generation_store": generation_store,
        "checkpoint_parent": _mkdir_private(root / "checkpoint"),
        "planning_store": _mkdir_private(root / "planning-store"),
        "planning_work": _mkdir_private(root / "planning-work"),
        "planning_capture": _mkdir_private(root / "planning-capture"),
        "body_blob": _mkdir_private(root / "body-blob"),
        "declared_bodyless_packet": _mkdir_private(root / "declared-bodyless-packet"),
        "update_capture": _mkdir_private(root / "update-capture"),
        "update_receipts": _mkdir_private(root / "update-receipts"),
        "runtime_logs": _mkdir_private(root / "runtime-logs"),
        "assurance_scratch": _mkdir_private(root / "assurance-scratch"),
    }
    public = root / "baseline-public"
    public.mkdir(mode=0o755)
    public.chmod(0o755)
    (public / "baseline.bin").write_bytes(b"exact-full-baseline")
    (public / "nba.duckdb").write_bytes(b"synthetic-checkpoint-database")
    (public / "nba.sqlite").write_bytes(b"synthetic-checkpoint-sqlite")
    for format_dir in ("csv", "parquet"):
        (public / format_dir).mkdir(mode=0o755)
    paths["baseline_public"] = public.resolve()
    return paths


def _baseline(public_root: Path) -> BaselineAssuranceIdentity:
    provider = expected_nba_api_provider_authority()
    blocked = {"schema_version": 1, "contract_blocked_lanes": []}
    chain_id = "full-initial-20260813"
    source_sha = "a" * 40
    coverage_fingerprint = _digest("coverage")
    checkpoint_database_sha256 = hashlib.sha256(
        (public_root / "nba.duckdb").read_bytes()
    ).hexdigest()
    checkpoint_report = {
        "chain_id": chain_id,
        "source_sha": source_sha,
        "coverage_fingerprint": coverage_fingerprint,
        "artifact_name": f"full-extraction-checkpoint-{chain_id}-iter-1",
        "checkpoint_generation": 1,
        "database_sha256": checkpoint_database_sha256,
        "contract_blocked_lane_count": 0,
        "contract_blocked_evidence": blocked,
        "contract_blocked_evidence_sha256": canonical_sha256(blocked),
        "provider_authority": provider,
        "provider_authority_sha256": provider["authority_sha256"],
        "terminal_ready": True,
        "active_lane_count": 0,
        "run_id": "123456",
        "included_lane_ids": ["synthetic-full-baseline"],
        "included_lane_coverage_hashes": {
            "synthetic-full-baseline": _digest("synthetic-lane-coverage")
        },
        "included_run_ids": ["123456"],
        "complete_lane_count": 1,
        "manifest_lane_count": 1,
        "skipped_lane_count": 0,
        "missing_lane_ids": [],
        "skipped_complete_lane_ids": [],
        "current_lane_attestation_failures": [],
        "workload_contract_errors": [],
    }
    checkpoint_report_sha256 = hashlib.sha256(
        json.dumps(checkpoint_report, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    terminal = {
        "schema_version": 3,
        "chain_id": chain_id,
        "source_sha": source_sha,
        "coverage_fingerprint": coverage_fingerprint,
        "checkpoint_artifact_name": checkpoint_report["artifact_name"],
        "checkpoint_generation": 1,
        "checkpoint_database_sha256": checkpoint_database_sha256,
        "checkpoint_report_sha256": checkpoint_report_sha256,
        "checkpoint_report": checkpoint_report,
        "contract_blocked_lane_count": 0,
        "contract_blocked_evidence": blocked,
        "contract_blocked_evidence_sha256": canonical_sha256(blocked),
        "provider_authority": provider,
        "provider_authority_sha256": provider["authority_sha256"],
    }
    terminal_bytes = (json.dumps(terminal, indent=2, sort_keys=True) + "\n").encode()
    (public_root / "terminal-assurance-report.json").write_bytes(terminal_bytes)
    build_assured_artifact_manifest(
        public_root,
        chain_id=chain_id,
        source_sha=source_sha,
        coverage_fingerprint=coverage_fingerprint,
    )
    manifest_bytes = (public_root / ASSURED_ARTIFACT_MANIFEST_NAME).read_bytes()
    installed_tree = measure_installed_public_tree(public_root)
    return BaselineAssuranceIdentity(
        remote_dataset="maintainer/nbadb",
        remote_dataset_version=1,
        chain_id=chain_id,
        source_sha=source_sha,
        coverage_fingerprint=coverage_fingerprint,
        data_tree_fingerprint=json.loads(manifest_bytes)["data_tree_fingerprint"],
        remote_bundle_fingerprint_sha256=_digest("remote-bundle"),
        installed_public_tree_sha256=installed_tree.installed_public_tree_sha256,
        installed_public_tree_bytes=installed_tree.byte_count,
        assured_manifest_sha256=hashlib.sha256(manifest_bytes).hexdigest(),
        terminal_assurance_report_sha256=hashlib.sha256(terminal_bytes).hexdigest(),
        private_baseline_receipt_sha256=_digest("private-baseline"),
        checkpoint_database_sha256=checkpoint_database_sha256,
        checkpoint_report_sha256=checkpoint_report_sha256,
        contract_blocked_evidence_sha256=canonical_sha256(blocked),
        provider_authority_sha256=str(provider["authority_sha256"]),
    )


def _request(
    public_root: Path,
    *,
    generation: int = 1,
    mode: SuccessorUpdateMode = SuccessorUpdateMode.DAILY,
) -> SuccessorCoordinatorRequest:
    baseline = _baseline(public_root)
    planning_request = build_successor_planning_request(
        baseline_identity_sha256=baseline.identity_sha256,
        mode=mode,
        source_sha="b" * 40,
        cutoff_utc="2026-08-12T00:00:00Z",
        as_of_utc="2026-08-13T00:00:00Z",
        workflow_run_id=731,
        workflow_run_attempt=1,
    )
    return SuccessorCoordinatorRequest(
        baseline=baseline,
        planning_request=planning_request,
        generation=generation,
        baseline_public_root=public_root,
        candidate_admission=SuccessorCandidateAdmission(
            aggregate_capacity=_capacity(baseline.installed_public_tree_bytes),
            monotonic_deadline_seconds=1_000.0,
            minimum_pre_provider_headroom_seconds=10.0,
            minimum_deadline_headroom_seconds=10.0,
            monotonic_epoch_sha256=_digest("monotonic-epoch"),
        ),
    )


def _config(paths: dict[str, Path]) -> ExactSuccessorCompositionConfig:
    baseline_public = paths["baseline_public"]
    return ExactSuccessorCompositionConfig(
        generation_store_root=paths["generation_store"],
        checkpoint_path=paths["checkpoint_parent"] / "coordinator.json",
        planning_store_root=paths["planning_store"],
        planning_work_root=paths["planning_work"],
        planning_capture_root=paths["planning_capture"],
        body_blob_root=paths["body_blob"],
        declared_bodyless_packet_root=paths["declared_bodyless_packet"],
        update_capture_root=paths["update_capture"],
        update_terminal_receipt_root=paths["update_receipts"],
        runtime_log_root=paths["runtime_logs"],
        assurance_scratch_root=paths["assurance_scratch"],
        settings=NbaDbSettings(
            data_dir=baseline_public,
            duckdb_path=baseline_public / "nba.duckdb",
            sqlite_path=baseline_public / "nba.sqlite",
            log_dir=paths["runtime_logs"],
        ),
        planning_registry=_planning_registry(),
        capture_limits=_limits(),
        fresh_planning_budget=_budget,
        monotonic_epoch_authority=lambda: _digest("monotonic-epoch"),
        contract_blocked_evidence={"schema_version": 1, "contract_blocked_lanes": []},
        w2_authority_resources=_w2_resources(paths["planning_store"].parent),
        monotonic_clock=lambda: 1.0,
        free_bytes_probe=lambda _descriptor: 10_000_000_000,
        scan_function=_passing_scan,
    )


def _restore_request(public_root: Path) -> SuccessorCoordinatorRequest:
    request = _request(public_root)
    return replace(
        request,
        candidate_admission=replace(
            request.candidate_admission,
            aggregate_capacity=replace(
                request.candidate_admission.aggregate_capacity,
                planning_store_generation_max_bytes=512 * 1024 * 1024,
                planning_store_artifact_max_bytes=64 * 1024 * 1024,
                planning_driver_database_max_bytes=64 * 1024 * 1024,
            ),
        ),
    )


def _restore_budget(request: SuccessorCoordinatorRequest) -> PlanningStoreBudget:
    capacity = request.candidate_admission.aggregate_capacity
    return PlanningStoreBudget(
        generation_max_bytes=capacity.planning_store_generation_max_bytes,
        artifact_max_bytes=capacity.planning_store_artifact_max_bytes,
        control_max_bytes=capacity.planning_store_control_max_bytes,
        minimum_free_bytes=capacity.minimum_free_bytes,
        monotonic_deadline_seconds=request.candidate_admission.monotonic_deadline_seconds,
        minimum_deadline_headroom_seconds=(
            request.candidate_admission.minimum_pre_provider_headroom_seconds
        ),
    )


def _install_semantic_store_planner(
    composition: ExactSuccessorComposition,
) -> tuple[_SemanticRuntime, dict[str, int], dict[str, int]]:
    executor = composition.coordinator._planning_executor
    assert type(executor) is ConcreteSuccessorPlanningExecutor
    runtime = _SemanticRuntime()
    inner = RequestDrivenSuccessorPlanningDriver(runtime)
    driver_calls = {
        "derive_wave": 0,
        "execute_call": 0,
        "seal_wave": 0,
        "derive_manifest": 0,
    }

    class _CountedDriver:
        async def derive_wave(self, *args: object, **kwargs: object) -> object:
            driver_calls["derive_wave"] += 1
            return await inner.derive_wave(*args, **kwargs)

        async def execute_call(self, *args: object, **kwargs: object) -> object:
            driver_calls["execute_call"] += 1
            return await inner.execute_call(*args, **kwargs)

        async def seal_wave(self, *args: object, **kwargs: object) -> object:
            driver_calls["seal_wave"] += 1
            return await inner.seal_wave(*args, **kwargs)

        async def derive_manifest(self, *args: object, **kwargs: object) -> object:
            driver_calls["derive_manifest"] += 1
            return await inner.derive_manifest(*args, **kwargs)

    verify_calls = {"count": 0}
    original_verify = executor.verify

    def counting_verify(*args: object, **kwargs: object) -> object:
        verify_calls["count"] += 1
        return original_verify(*args, **kwargs)

    executor._driver = _CountedDriver()
    executor._private_generation_resolver = _Resolver()
    executor.verify = counting_verify
    return runtime, driver_calls, verify_calls


def _record_and_crash_runtime_factory(
    composition: ExactSuccessorComposition,
    recorded_plans: list[object],
) -> None:
    def crashing_factory(
        _transaction: object,
        _candidate_root: object,
        execution_plan: object,
    ) -> object:
        recorded_plans.append(execution_plan)
        raise RuntimeError("injected-runtime-crash")

    composition.coordinator._runtime_factory = crashing_factory  # ty: ignore[invalid-assignment]


def test_build_composes_frozen_live_components_without_persistence(tmp_path: Path) -> None:
    paths = _layout(tmp_path)
    request = _request(paths["baseline_public"])
    config = _config(paths)

    composition = build_exact_successor_composition(request=request, config=config)
    executor = composition.coordinator._planning_executor
    runtime_factory = composition.coordinator._runtime_factory

    assert composition.request is request
    assert composition.topology.request is request
    assert type(executor) is ConcreteSuccessorPlanningExecutor
    assert type(executor._store) is SuccessorPlanningStore
    assert type(executor._driver) is RequestDrivenSuccessorPlanningDriver
    assert type(executor._private_generation_resolver) is RetainedBronzePlanningResolver
    assert type(executor._driver._runtime) is ExtractorPlanningExactCallRuntime
    assert type(runtime_factory) is ExactPlanSuccessorRuntimeFactory
    assert not config.checkpoint_path.exists()
    assert list((config.generation_store_root / "generations").iterdir()) == []
    assert not (config.generation_store_root / ".successor-generation.lock").exists()


async def test_composition_cancellation_blocks_downstream_scan_export_upload(
    tmp_path: Path,
) -> None:
    paths = _layout(tmp_path)
    request = _request(paths["baseline_public"])
    scan_calls: list[object] = []

    def tracking_scan(connection: object) -> ScanReport:
        scan_calls.append(connection)
        return _passing_scan(connection)

    config = replace(_config(paths), scan_function=tracking_scan)
    composition = build_exact_successor_composition(request=request, config=config)

    async def cancel(_request: SuccessorCoordinatorRequest) -> object:
        raise asyncio.CancelledError()

    composition.coordinator.run = cancel  # ty: ignore[invalid-assignment]
    with pytest.raises(asyncio.CancelledError):
        await composition.run()

    assert scan_calls == []
    assert not (config.generation_store_root / CURRENT_SUCCESSOR_GENERATION_NAME).exists()
    with pytest.raises(SuccessorCoordinatorError, match="blocks scan, export, and upload"):
        composition.coordinator.require_downstream_publication()
    with pytest.raises(SuccessorCoordinatorError, match="blocks scan, export, and upload"):
        require_successor_downstream_publication(
            checkpoint=None,
            current_pointer=None,
        )


def test_before_planning_effects_authority_rechecks_aggregate_capacity(
    tmp_path: Path,
) -> None:
    paths = _layout(tmp_path)
    request = _request(paths["baseline_public"])
    config = _config(paths)
    composition = build_exact_successor_composition(request=request, config=config)
    planning_executor = composition.coordinator._planning_executor
    assert type(planning_executor) is ConcreteSuccessorPlanningExecutor
    planning_runtime = planning_executor._driver._runtime
    assert type(planning_runtime) is ExtractorPlanningExactCallRuntime
    planning_runtime.config.require_before_planning_effects_authority()

    displaced = paths["root"] / "planning-capture-displaced"
    config.planning_capture_root.rename(displaced)
    _mkdir_private(config.planning_capture_root)

    with pytest.raises(ExactPlanningRuntimeError, match="before-effects authority rejected"):
        planning_runtime.config.require_before_planning_effects_authority()


async def test_rebuilt_composition_restores_exact_planning_generation_and_sealed_plan(
    tmp_path: Path,
) -> None:
    paths = _layout(tmp_path)
    request = _restore_request(paths["baseline_public"])
    config = replace(
        _config(paths),
        fresh_planning_budget=lambda: _restore_budget(request),
    )
    composition = build_exact_successor_composition(request=request, config=config)
    _semantic, first_driver_calls, first_verify_calls = _install_semantic_store_planner(composition)
    recorded_plans: list[object] = []
    _record_and_crash_runtime_factory(composition, recorded_plans)

    with pytest.raises(RuntimeError, match="injected-runtime-crash"):
        await composition.run()

    checkpoint = composition.topology.checkpoint_store.load()
    assert checkpoint is not None
    assert checkpoint.phase is SuccessorCoordinatorPhase.EXECUTING
    assert checkpoint.planning_evidence is not None
    assert first_driver_calls["derive_wave"] > 0
    assert first_driver_calls["execute_call"] > 0
    assert first_driver_calls["seal_wave"] == 2
    assert first_driver_calls["derive_manifest"] == 1
    assert first_verify_calls["count"] == 1
    assert recorded_plans == [checkpoint.planning_evidence.execution_plan]
    sealed_evidence = checkpoint.planning_evidence
    sealed_plan = sealed_evidence.execution_plan
    sealed_plan.validate_against_manifest(sealed_evidence.planning_generation_manifest)

    resumed = build_exact_successor_composition(request=request, config=config)
    _resume_semantic, resume_driver_calls, resume_verify_calls = _install_semantic_store_planner(
        resumed
    )
    resumed_plans: list[object] = []
    _record_and_crash_runtime_factory(resumed, resumed_plans)

    with pytest.raises(RuntimeError, match="injected-runtime-crash"):
        await resumed.run()

    resumed_checkpoint = resumed.topology.checkpoint_store.load()
    assert resumed_checkpoint is not None
    assert resumed_checkpoint.phase is SuccessorCoordinatorPhase.EXECUTING
    assert resume_driver_calls == {
        "derive_wave": 0,
        "execute_call": 0,
        "seal_wave": 0,
        "derive_manifest": 0,
    }
    assert resume_verify_calls["count"] == 1
    assert resumed_checkpoint.planning_evidence is not None
    assert resumed_checkpoint.planning_evidence.to_dict() == sealed_evidence.to_dict()
    assert resumed_plans == [sealed_plan]
    verified = resumed.coordinator._planning_executor.verify(
        request.planning_request,
        sealed_evidence,
    )
    assert verified.to_dict() == sealed_evidence.to_dict()
    assert verified.execution_plan.to_dict() == sealed_plan.to_dict()


async def test_rebuilt_composition_rejects_planning_generation_byte_drift_before_runtime(
    tmp_path: Path,
) -> None:
    paths = _layout(tmp_path)
    request = _restore_request(paths["baseline_public"])
    config = replace(
        _config(paths),
        fresh_planning_budget=lambda: _restore_budget(request),
    )
    composition = build_exact_successor_composition(request=request, config=config)
    _install_semantic_store_planner(composition)
    recorded_plans: list[object] = []
    _record_and_crash_runtime_factory(composition, recorded_plans)

    with pytest.raises(RuntimeError, match="injected-runtime-crash"):
        await composition.run()
    prior_runtime_calls = len(recorded_plans)
    checkpoint = composition.topology.checkpoint_store.load()
    assert checkpoint is not None
    assert checkpoint.phase is SuccessorCoordinatorPhase.EXECUTING

    mutated = 0
    for path in paths["planning_store"].rglob("*"):
        if path.is_file() and path.stat().st_size > 0:
            path.chmod(0o600)
            path.write_bytes(path.read_bytes() + b"x")
            mutated += 1
            break
    assert mutated == 1

    with pytest.raises(
        ExactSuccessorCompositionError,
        match="planning store existing bytes could not be measured",
    ):
        build_exact_successor_composition(request=request, config=config)

    assert len(recorded_plans) == prior_runtime_calls
    assert composition.topology.checkpoint_store.load() == checkpoint
    assert not (config.generation_store_root / CURRENT_SUCCESSOR_GENERATION_NAME).exists()


@pytest.mark.parametrize(
    "overlapping_field",
    ("planning_capture_root", "body_blob_root", "declared_bodyless_packet_root"),
)
def test_private_root_overlap_fails_before_checkpoint_or_candidate_write(
    tmp_path: Path,
    overlapping_field: str,
) -> None:
    paths = _layout(tmp_path)
    request = _request(paths["baseline_public"])
    config = replace(
        _config(paths),
        **{overlapping_field: paths["planning_store"]},
    )

    with pytest.raises(ExactSuccessorCompositionError, match="must be disjoint"):
        build_exact_successor_composition(request=request, config=config)

    assert not config.checkpoint_path.exists()
    assert list((config.generation_store_root / "generations").iterdir()) == []


def test_unpointed_baseline_inside_generation_store_fails_before_write(tmp_path: Path) -> None:
    paths = _layout(tmp_path)
    internal = paths["generation_store"] / "generations" / "unpointed" / "public"
    internal.mkdir(parents=True)
    (internal / "baseline.bin").write_bytes(b"unpointed")
    (internal / "nba.duckdb").write_bytes(b"unpointed-checkpoint")
    internal = internal.resolve()
    request = _request(internal)
    config = _config({**paths, "baseline_public": internal})

    with pytest.raises(ExactSuccessorCompositionError, match="external baseline"):
        build_exact_successor_composition(request=request, config=config)

    assert not config.checkpoint_path.exists()
    assert not (config.generation_store_root / ".successor-generation.lock").exists()
    generations = config.generation_store_root / "generations"
    assert sorted(path.name for path in generations.iterdir()) == ["unpointed"]


def test_reentry_rechecks_private_inode_before_coordinator_checkpoint(tmp_path: Path) -> None:
    paths = _layout(tmp_path)
    request = _request(paths["baseline_public"])
    config = _config(paths)
    composition = build_exact_successor_composition(request=request, config=config)
    displaced = paths["root"] / "planning-capture-displaced"
    config.planning_capture_root.rename(displaced)
    _mkdir_private(config.planning_capture_root)

    with pytest.raises(
        ExactSuccessorCompositionError,
        match="planning capture capacity root changed identity",
    ):
        asyncio.run(composition.run())

    assert not config.checkpoint_path.exists()
    assert list((config.generation_store_root / "generations").iterdir()) == []


def test_reentry_rechecks_scoped_planning_registry_authority(tmp_path: Path) -> None:
    paths = _layout(tmp_path)
    request = _request(paths["baseline_public"])
    config = _config(paths)
    composition = build_exact_successor_composition(request=request, config=config)
    replacement = type(
        "ReplacementLeagueGameLog",
        (),
        {"endpoint_name": "league_game_log"},
    )
    config.planning_registry.register(replacement)  # ty: ignore[invalid-argument-type]

    with pytest.raises(ExactSuccessorCompositionError, match="registry authority differs"):
        asyncio.run(composition.run())

    assert not config.checkpoint_path.exists()
    assert list((config.generation_store_root / "generations").iterdir()) == []


def test_build_requires_complete_update_route_registry_before_persistence(
    tmp_path: Path,
) -> None:
    paths = _layout(tmp_path)
    request = _request(paths["baseline_public"])
    config = _config(paths)
    config.planning_registry._extractors.pop("video_status")

    with pytest.raises(ExactSuccessorCompositionError, match="complete staging-route"):
        build_exact_successor_composition(request=request, config=config)

    assert not config.checkpoint_path.exists()
    assert list((config.generation_store_root / "generations").iterdir()) == []


def test_reentry_rechecks_update_only_registry_authority_before_persistence(
    tmp_path: Path,
) -> None:
    paths = _layout(tmp_path)
    request = _request(paths["baseline_public"])
    config = _config(paths)
    composition = build_exact_successor_composition(request=request, config=config)
    replacement = type(
        "ForeignVideoStatus",
        (),
        {"endpoint_name": "video_status"},
    )
    config.planning_registry.register(replacement)  # ty: ignore[invalid-argument-type]

    with pytest.raises(ExactSuccessorCompositionError, match="registry authority differs"):
        asyncio.run(composition.run())

    assert not config.checkpoint_path.exists()
    assert list((config.generation_store_root / "generations").iterdir()) == []


def test_run_rechecks_fresh_planning_budget_before_store_or_checkpoint_write(
    tmp_path: Path,
) -> None:
    paths = _layout(tmp_path)
    request = _request(paths["baseline_public"])
    calls = 0

    def drifting_budget() -> PlanningStoreBudget:
        nonlocal calls
        calls += 1
        budget = _budget()
        if calls >= 4:
            return replace(
                budget,
                monotonic_deadline_seconds=budget.monotonic_deadline_seconds + 1,
            )
        return budget

    config = replace(_config(paths), fresh_planning_budget=drifting_budget)
    composition = build_exact_successor_composition(request=request, config=config)

    with pytest.raises(ExactSuccessorCompositionError, match="deadline differs"):
        asyncio.run(composition.run())

    assert calls == 4
    assert not config.checkpoint_path.exists()
    assert list((config.generation_store_root / "generations").iterdir()) == []
    assert not (config.generation_store_root / ".successor-generation-store.lock").exists()


def test_adulterated_planning_request_fails_before_any_persistence(tmp_path: Path) -> None:
    paths = _layout(tmp_path)
    request = _request(paths["baseline_public"])
    planning = replace(
        request.planning_request,
        requested_planning_scopes=request.planning_request.requested_planning_scopes[:-1],
    )
    request = replace(request, planning_request=planning)
    config = _config(paths)

    with pytest.raises(ValueError, match="differs from the exact derived inventory"):
        build_exact_successor_composition(request=request, config=config)

    assert not config.checkpoint_path.exists()
    assert list((config.generation_store_root / "generations").iterdir()) == []
    assert not list(config.planning_capture_root.iterdir())


@pytest.mark.parametrize("authority", ["provider", "blocked"])
def test_inherited_control_drift_fails_before_any_persistence(
    tmp_path: Path,
    authority: str,
) -> None:
    paths = _layout(tmp_path)
    request = _request(paths["baseline_public"])
    config = _config(paths)
    if authority == "provider":
        baseline = replace(
            request.baseline,
            provider_authority_sha256=_digest("foreign-provider"),
        )
        planning_request = build_successor_planning_request(
            baseline_identity_sha256=baseline.identity_sha256,
            mode=SuccessorUpdateMode.DAILY,
            source_sha="b" * 40,
            cutoff_utc="2026-08-12T00:00:00Z",
            as_of_utc="2026-08-13T00:00:00Z",
            workflow_run_id=731,
            workflow_run_attempt=1,
        )
        request = replace(
            request,
            baseline=baseline,
            planning_request=planning_request,
        )
        message = "provider authority differs"
    else:
        config = replace(
            config,
            contract_blocked_evidence={
                "schema_version": 1,
                "contract_blocked_lanes": [],
                "unexpected": True,
            },
        )
        message = "contract-blocked lane evidence is invalid"

    with pytest.raises(ExactSuccessorCompositionError, match=message):
        build_exact_successor_composition(request=request, config=config)

    assert not config.checkpoint_path.exists()
    assert list((config.generation_store_root / "generations").iterdir()) == []
    assert not list(config.planning_capture_root.iterdir())


@pytest.mark.parametrize("control", ["missing_manifest", "tampered_report"])
def test_baseline_control_drift_fails_before_any_persistence(
    tmp_path: Path,
    control: str,
) -> None:
    paths = _layout(tmp_path)
    request = _request(paths["baseline_public"])
    config = _config(paths)
    if control == "missing_manifest":
        (paths["baseline_public"] / ASSURED_ARTIFACT_MANIFEST_NAME).unlink()
    else:
        (paths["baseline_public"] / "terminal-assurance-report.json").write_bytes(
            b'{"schema_version":3}\n'
        )

    with pytest.raises(ExactSuccessorCompositionError, match="baseline"):
        build_exact_successor_composition(request=request, config=config)

    assert not config.checkpoint_path.exists()
    assert list((config.generation_store_root / "generations").iterdir()) == []
    assert not list(config.planning_capture_root.iterdir())


def test_paired_baseline_control_read_rejects_first_name_substitution(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    paths = _layout(tmp_path)
    request = _request(paths["baseline_public"])
    config = _config(paths)
    report = paths["baseline_public"] / "terminal-assurance-report.json"
    displaced = paths["root"] / "displaced-terminal-assurance-report.json"
    real_open = os.open
    real_read = os.read
    swapped = False
    report_open_count = 0
    paired_report_descriptor = -1
    paired_manifest_descriptor = -1

    def swapping_open(
        path: str | bytes | os.PathLike[str] | os.PathLike[bytes],
        flags: int,
        mode: int = 0o777,
        *,
        dir_fd: int | None = None,
    ) -> int:
        nonlocal paired_manifest_descriptor, paired_report_descriptor, report_open_count
        descriptor = real_open(path, flags, mode, dir_fd=dir_fd)
        if path == "terminal-assurance-report.json" and dir_fd is not None:
            report_open_count += 1
            if report_open_count == 2:
                paired_report_descriptor = descriptor
        elif (
            path == ASSURED_ARTIFACT_MANIFEST_NAME
            and dir_fd is not None
            and paired_report_descriptor >= 0
        ):
            paired_manifest_descriptor = descriptor
        return descriptor

    def swapping_read(descriptor: int, byte_count: int) -> bytes:
        nonlocal swapped
        if descriptor == paired_manifest_descriptor and not swapped:
            payload = report.read_bytes()
            report.rename(displaced)
            report.write_bytes(payload)
            swapped = True
        return real_read(descriptor, byte_count)

    monkeypatch.setattr(os, "open", swapping_open)
    monkeypatch.setattr(os, "read", swapping_read)
    with pytest.raises(ExactSuccessorCompositionError, match="paired control read"):
        build_exact_successor_composition(request=request, config=config)

    assert swapped
    assert not config.checkpoint_path.exists()
    assert list((config.generation_store_root / "generations").iterdir()) == []


def test_missing_pointer_rejects_promoted_checkpoint_authority(tmp_path: Path) -> None:
    paths = _layout(tmp_path)
    request = _request(paths["baseline_public"])
    config = _config(paths)
    composition = build_exact_successor_composition(request=request, config=config)

    class _PromotedCheckpointStore:
        path = config.checkpoint_path

        @staticmethod
        def load() -> SimpleNamespace:
            return SimpleNamespace(
                phase=SuccessorCoordinatorPhase.PROMOTED,
                baseline=request.baseline,
                planning_request=request.planning_request,
                candidate_admission=request.candidate_admission,
                generation=request.generation,
            )

    topology = replace(
        composition.topology,
        checkpoint_store=_PromotedCheckpointStore(),
    )
    with pytest.raises(ExactSuccessorCompositionError, match="installed current pointer"):
        topology.require_current()

    assert not config.checkpoint_path.exists()
    assert list((config.generation_store_root / "generations").iterdir()) == []


def test_missing_pointer_rejects_foreign_in_progress_checkpoint(tmp_path: Path) -> None:
    paths = _layout(tmp_path)
    request = _request(paths["baseline_public"])
    config = _config(paths)
    composition = build_exact_successor_composition(request=request, config=config)

    class _ForeignCheckpointStore:
        path = config.checkpoint_path

        @staticmethod
        def load() -> SimpleNamespace:
            return SimpleNamespace(
                phase=SuccessorCoordinatorPhase.REQUESTED,
                baseline=request.baseline,
                planning_request=request.planning_request,
                candidate_admission=request.candidate_admission,
                generation=request.generation + 1,
            )

    topology = replace(
        composition.topology,
        checkpoint_store=_ForeignCheckpointStore(),
    )
    with pytest.raises(ExactSuccessorCompositionError, match="unpointed checkpoint differs"):
        topology.require_current()

    assert not config.checkpoint_path.exists()
    assert list((config.generation_store_root / "generations").iterdir()) == []


def test_missing_pointer_admits_exact_transaction_promoted_checkpoint(tmp_path: Path) -> None:
    paths = _layout(tmp_path)
    request = _request(paths["baseline_public"])
    config = _config(paths)
    composition = build_exact_successor_composition(request=request, config=config)

    class _ExactCheckpointStore:
        path = config.checkpoint_path

        @staticmethod
        def load() -> SimpleNamespace:
            return SimpleNamespace(
                phase=SuccessorCoordinatorPhase.TRANSACTION_PROMOTED,
                baseline=request.baseline,
                planning_request=request.planning_request,
                candidate_admission=request.candidate_admission,
                generation=request.generation,
            )

    topology = replace(
        composition.topology,
        checkpoint_store=_ExactCheckpointStore(),
    )
    topology.require_current()

    assert not config.checkpoint_path.exists()
    assert list((config.generation_store_root / "generations").iterdir()) == []


def test_promoted_reentry_requires_exact_candidate_admission(tmp_path: Path) -> None:
    promoted = _promoted(1, "admission")
    planning_request = build_successor_planning_request(
        baseline_identity_sha256=promoted.baseline.identity_sha256,
        mode=SuccessorUpdateMode.DAILY,
        source_sha="b" * 40,
        cutoff_utc="2026-08-12T00:00:00Z",
        as_of_utc="2026-08-13T00:00:00Z",
        workflow_run_id=731,
        workflow_run_attempt=1,
    )
    admission = SuccessorCandidateAdmission(
        aggregate_capacity=_capacity(
            promoted.baseline.installed_public_tree_bytes,
            candidate_max_bytes=1_000_000,
        ),
        monotonic_deadline_seconds=1_000.0,
        minimum_pre_provider_headroom_seconds=10.0,
        minimum_deadline_headroom_seconds=10.0,
        monotonic_epoch_sha256=_digest("admission-epoch"),
    )
    request = SuccessorCoordinatorRequest(
        baseline=promoted.baseline,
        planning_request=planning_request,
        generation=1,
        baseline_public_root=tmp_path,
        candidate_admission=admission,
    )
    assurance = promoted.promoted_assurance
    current = {
        "generation": 1,
        "candidate_name": SuccessorGenerationStore.candidate_name(promoted),
        "transaction_sha256": promoted.content_sha256,
        "assurance_sha256": assurance.identity_sha256,
        "data_tree_fingerprint": assurance.successor_data_tree_fingerprint,
        "installed_public_tree_sha256": assurance.installed_public_tree_sha256,
        "private_generation_receipt_sha256": assurance.private_generation_receipt_sha256,
    }
    checkpoint = SimpleNamespace(
        phase=SuccessorCoordinatorPhase.PROMOTED,
        transaction=promoted,
        assurance=assurance,
        baseline=promoted.baseline,
        planning_request=planning_request,
        candidate_admission=admission,
        generation=1,
        candidate_installed_public_tree_sha256=assurance.installed_public_tree_sha256,
    )

    assert _is_exact_promoted_reentry(checkpoint, request, current)  # ty: ignore[invalid-argument-type]
    drifted = replace(
        request,
        candidate_admission=replace(
            admission,
            monotonic_deadline_seconds=admission.monotonic_deadline_seconds + 1,
        ),
    )
    assert not _is_exact_promoted_reentry(
        checkpoint,  # ty: ignore[invalid-argument-type]
        drifted,
        current,
    )


class _CrashAfterPointerCheckpointStore(SuccessorCoordinatorCheckpointStore):
    crash = True

    def write(self, checkpoint: Any) -> None:
        if self.crash and checkpoint.phase is SuccessorCoordinatorPhase.PROMOTED:
            raise RuntimeError("injected-after-pointer")
        super().write(checkpoint)


async def test_checkpoint_parent_swap_during_planning_cannot_advance_replacement(
    tmp_path: Path,
) -> None:
    checkpoint_parent = _mkdir_private(tmp_path / "checkpoint-parent")
    checkpoint_path = checkpoint_parent / "coordinator.json"
    checkpoint_stat = checkpoint_parent.stat()
    checkpoint_store = _BoundSuccessorCoordinatorCheckpointStore(
        checkpoint_path,
        expected_parent_identity=(checkpoint_stat.st_dev, checkpoint_stat.st_ino),
        max_bytes=10_000_000,
    )
    request, coordinator, planner, _runtime, _assurance, store, _unused = _harness(
        tmp_path / "harness",
        checkpoint_store=checkpoint_store,
    )
    entered = asyncio.Event()
    release = asyncio.Event()

    class _PausedPlanner:
        async def __call__(self, planning_request: Any) -> Any:
            entered.set()
            await release.wait()
            return await planner(planning_request)

        def verify(self, planning_request: Any, evidence: Any) -> Any:
            return planner.verify(planning_request, evidence)

    coordinator._planning_executor = _PausedPlanner()  # ty: ignore[invalid-assignment]
    task = asyncio.create_task(coordinator.run(request))
    await entered.wait()
    requested_bytes = checkpoint_path.read_bytes()
    displaced = tmp_path / "displaced-checkpoint-parent"
    checkpoint_parent.rename(displaced)
    replacement = _mkdir_private(checkpoint_parent)
    replacement_checkpoint = replacement / checkpoint_path.name
    replacement_checkpoint.write_bytes(requested_bytes)
    replacement_checkpoint.chmod(0o600)
    release.set()

    with pytest.raises(SuccessorCoordinatorError, match="checkpoint parent changed identity"):
        await task

    assert replacement_checkpoint.read_bytes() == requested_bytes
    assert not list(replacement.glob(".*.tmp"))
    assert not store.pointer_path.exists()
    assert not store.generations_root.exists()


def test_pointer_installed_transaction_promoted_checkpoint_resumes_to_closed(
    tmp_path: Path,
) -> None:
    checkpoint_store = _CrashAfterPointerCheckpointStore(tmp_path / "coordinator.json")
    request, coordinator, _planner, _runtime, _assurance, store, _unused = _harness(
        tmp_path,
        checkpoint_store=checkpoint_store,
        candidate_max_bytes=2_000_000,
    )

    with pytest.raises(RuntimeError, match="injected-after-pointer"):
        asyncio.run(coordinator.run(request))
    checkpoint = checkpoint_store.load()
    pointer = store.read_current()
    assert checkpoint is not None
    assert pointer is not None
    assert checkpoint.phase is SuccessorCoordinatorPhase.TRANSACTION_PROMOTED
    assert _is_exact_promoted_reentry(checkpoint, request, pointer["current"])

    checkpoint_store.crash = False
    result = asyncio.run(coordinator.run(request))
    assert result.checkpoint.phase is SuccessorCoordinatorPhase.PROMOTED
    assert store.read_current() == result.current_pointer


@pytest.mark.parametrize(
    "field",
    ["transaction_sha256", "assurance_sha256", "data_tree_fingerprint"],
)
def test_predecessor_reference_is_reconstructed_from_promoted_transaction(
    tmp_path: Path,
    field: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        SuccessorGenerationStore,
        "_gate_publication_before_promote",
        lambda self, *args, **kwargs: None,
    )
    store = SuccessorGenerationStore(tmp_path / "store")
    promoted = _promoted(1, "predecessor")
    candidate = _candidate(store, promoted)
    _record_all(store, candidate, promoted)
    pointer = store.promote(candidate, promoted)
    assurance = promoted.promoted_assurance
    provider = expected_nba_api_provider_authority()
    baseline = replace(
        promoted.baseline,
        data_tree_fingerprint=assurance.successor_data_tree_fingerprint,
        installed_public_tree_sha256=assurance.installed_public_tree_sha256,
        private_baseline_receipt_sha256=assurance.private_generation_receipt_sha256,
        provider_authority_sha256=str(provider["authority_sha256"]),
    )
    planning_request = build_successor_planning_request(
        baseline_identity_sha256=baseline.identity_sha256,
        mode=SuccessorUpdateMode.DAILY,
        source_sha="b" * 40,
        cutoff_utc="2026-08-12T00:00:00Z",
        as_of_utc="2026-08-13T00:00:00Z",
        workflow_run_id=731,
        workflow_run_attempt=1,
    )
    request = SuccessorCoordinatorRequest(
        baseline=baseline,
        planning_request=planning_request,
        generation=2,
        baseline_public_root=candidate / "public",
        candidate_admission=SuccessorCandidateAdmission(
            aggregate_capacity=_capacity(
                baseline.installed_public_tree_bytes,
                candidate_max_bytes=1_000_000,
            ),
            monotonic_deadline_seconds=1_000.0,
            minimum_pre_provider_headroom_seconds=10.0,
            minimum_deadline_headroom_seconds=10.0,
            monotonic_epoch_sha256=_digest("predecessor-epoch"),
        ),
    )
    planning_registry = _planning_registry()
    topology = ExactSuccessorTopologyAuthority(
        request=request,
        generation_store=store,
        checkpoint_store=SuccessorCoordinatorCheckpointStore(
            tmp_path / "predecessor-checkpoint.json"
        ),
        private_roots=(),
        generation_store_authority=SimpleNamespace(),  # ty: ignore[invalid-argument-type]
        generations_authority=SimpleNamespace(),  # ty: ignore[invalid-argument-type]
        baseline_authority=SimpleNamespace(path=candidate / "public"),  # ty: ignore[invalid-argument-type]
        update_capture_authority=SimpleNamespace(),  # ty: ignore[invalid-argument-type]
        update_terminal_receipt_authority=SimpleNamespace(),  # ty: ignore[invalid-argument-type]
        runtime_log_authority=SimpleNamespace(),  # ty: ignore[invalid-argument-type]
        assurance_scratch_authority=SimpleNamespace(),  # ty: ignore[invalid-argument-type]
        contract_blocked_evidence={},
        planning_registry=planning_registry,
        planning_registry_authority=planning_registry.capture_authority(("common_all_players",)),
        update_registry_authority=planning_registry.capture_authority(),
        fresh_planning_budget=_budget,
        aggregate_capacity_authority=SimpleNamespace(),  # ty: ignore[invalid-argument-type]
        planning_store_authority=SimpleNamespace(),  # ty: ignore[invalid-argument-type]
        planning_work_authority=SimpleNamespace(),  # ty: ignore[invalid-argument-type]
        planning_capture_authority=SimpleNamespace(),  # ty: ignore[invalid-argument-type]
    )
    tampered = dict(pointer["current"])
    tampered[field] = _digest(f"tampered-{field}")

    with pytest.raises(ExactSuccessorCompositionError, match="stored promoted authority"):
        topology._require_baseline_reference(tampered, label="previous baseline")


class _GateTopology:
    def __init__(self, store: SuccessorGenerationStore) -> None:
        self.generation_store = store
        self.control_calls = 0
        self.current_calls = 0

    def require_baseline_controls_current(self) -> None:
        self.control_calls += 1

    def require_fresh_planning_budget(self) -> None:
        return None

    def require_aggregate_capacity(self, _stage: str) -> None:
        return None

    def require_current(self) -> None:
        self.require_baseline_controls_current()
        self.current_calls += 1


class _GateCoordinator:
    def __init__(
        self,
        *,
        entered: asyncio.Event | None = None,
        release: asyncio.Event | None = None,
    ) -> None:
        self.entered = entered
        self.release = release
        self.calls = 0

    async def run(self, _request: Any) -> SimpleNamespace:
        self.calls += 1
        if self.entered is not None:
            self.entered.set()
        if self.release is not None:
            await self.release.wait()
        transaction = _promoted(1, "gate")
        checkpoint = object.__new__(SuccessorCoordinatorCheckpoint)
        object.__setattr__(checkpoint, "phase", SuccessorCoordinatorPhase.PROMOTED)
        object.__setattr__(checkpoint, "transaction", transaction)
        object.__setattr__(checkpoint, "assurance", transaction.promoted_assurance)
        return SimpleNamespace(
            checkpoint=checkpoint,
            current_pointer={"current": {"generation": 1}},
        )


async def test_task_gate_serializes_separate_compositions_for_one_store_root(
    tmp_path: Path,
) -> None:
    store = SuccessorGenerationStore(_mkdir_private(tmp_path / "store"))
    _mkdir_private(store.generations_root)
    first_topology = _GateTopology(store)
    second_topology = _GateTopology(SuccessorGenerationStore(store.root))
    entered = asyncio.Event()
    release = asyncio.Event()
    first_coordinator = _GateCoordinator(entered=entered, release=release)
    second_coordinator = _GateCoordinator()
    first = ExactSuccessorComposition(
        request=SimpleNamespace(),  # ty: ignore[invalid-argument-type]
        coordinator=first_coordinator,  # ty: ignore[invalid-argument-type]
        topology=first_topology,  # ty: ignore[invalid-argument-type]
    )
    second = ExactSuccessorComposition(
        request=SimpleNamespace(),  # ty: ignore[invalid-argument-type]
        coordinator=second_coordinator,  # ty: ignore[invalid-argument-type]
        topology=second_topology,  # ty: ignore[invalid-argument-type]
    )

    first_task = asyncio.create_task(first.run())
    await entered.wait()
    second_task = asyncio.create_task(second.run())
    await asyncio.sleep(0)
    assert second_topology.control_calls == 0
    assert second_topology.current_calls == 0
    assert second_coordinator.calls == 0

    release.set()
    await asyncio.gather(first_task, second_task)
    assert second_topology.control_calls == 1
    assert second_topology.current_calls == 1
    assert second_coordinator.calls == 1


@pytest.mark.parametrize(
    ("root_identity", "generations_identity"),
    [
        (True, (1, 2)),
        ([1, 2], (1, 2)),
        ((1, False), (1, 2)),
        ((1,), (1, 2)),
        ((1, 2), None),
    ],
)
def test_bound_generation_store_rejects_malformed_constructor_identities(
    tmp_path: Path,
    root_identity: object,
    generations_identity: object,
) -> None:
    with pytest.raises(SuccessorGenerationStoreError, match="bound generation store"):
        SuccessorGenerationStore(
            tmp_path / "store",
            expected_root_identity=root_identity,  # ty: ignore[invalid-argument-type]
            expected_generations_identity=generations_identity,  # ty: ignore[invalid-argument-type]
        )


def test_bound_generation_store_rejects_foreign_inode_before_lock_write(
    tmp_path: Path,
) -> None:
    root = _mkdir_private(tmp_path / "store")
    generations = _mkdir_private(root / "generations")
    root_stat = root.stat()
    generations_stat = generations.stat()
    store = SuccessorGenerationStore(
        root,
        expected_root_identity=(root_stat.st_dev, root_stat.st_ino + 1),
        expected_generations_identity=(generations_stat.st_dev, generations_stat.st_ino),
    )

    with (
        pytest.raises(SuccessorGenerationStoreError, match="identity changed"),
        store.transaction_authority(),
    ):
        pytest.fail("foreign inode entered transaction authority")

    assert not (root / ".successor-generation-store.lock").exists()


def test_bound_generation_store_rejects_prelock_root_substitution(tmp_path: Path) -> None:
    root = _mkdir_private(tmp_path / "store")
    generations = _mkdir_private(root / "generations")
    root_stat = root.stat()
    generations_stat = generations.stat()
    store = SuccessorGenerationStore(
        root,
        expected_root_identity=(root_stat.st_dev, root_stat.st_ino),
        expected_generations_identity=(generations_stat.st_dev, generations_stat.st_ino),
    )
    root.rename(tmp_path / "displaced-store")
    replacement = _mkdir_private(root)
    _mkdir_private(replacement / "generations")

    with (
        pytest.raises(SuccessorGenerationStoreError, match="identity changed"),
        store.transaction_authority(),
    ):
        pytest.fail("substituted root entered transaction authority")

    assert not (replacement / ".successor-generation-store.lock").exists()


def test_bound_generation_store_pins_root_before_descriptor_relative_lock_write(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = _mkdir_private(tmp_path / "store")
    generations = _mkdir_private(root / "generations")
    root_stat = root.stat()
    generations_stat = generations.stat()
    store = SuccessorGenerationStore(
        root,
        expected_root_identity=(root_stat.st_dev, root_stat.st_ino),
        expected_generations_identity=(generations_stat.st_dev, generations_stat.st_ino),
    )
    displaced = tmp_path / "displaced-store"
    replacement: Path | None = None
    real_open = os.open
    swapped = False

    def swapping_open(
        path: str | bytes | os.PathLike[str] | os.PathLike[bytes],
        flags: int,
        mode: int = 0o777,
        *,
        dir_fd: int | None = None,
    ) -> int:
        nonlocal replacement, swapped
        if path == ".successor-generation-store.lock" and dir_fd is not None and not swapped:
            root.rename(displaced)
            replacement = _mkdir_private(root)
            _mkdir_private(replacement / "generations")
            swapped = True
        return real_open(path, flags, mode, dir_fd=dir_fd)

    monkeypatch.setattr(os, "open", swapping_open)
    with (
        pytest.raises(SuccessorGenerationStoreError, match="identity changed"),
        store.transaction_authority(),
    ):
        pytest.fail("substituted root entered transaction authority")

    assert swapped
    assert replacement is not None
    assert not (replacement / ".successor-generation-store.lock").exists()
    assert (displaced / ".successor-generation-store.lock").is_file()


def test_bound_generation_store_rechecks_held_context_substitution(tmp_path: Path) -> None:
    root = _mkdir_private(tmp_path / "store")
    generations = _mkdir_private(root / "generations")
    root_stat = root.stat()
    generations_stat = generations.stat()
    store = SuccessorGenerationStore(
        root,
        expected_root_identity=(root_stat.st_dev, root_stat.st_ino),
        expected_generations_identity=(generations_stat.st_dev, generations_stat.st_ino),
    )

    with (
        pytest.raises(SuccessorGenerationStoreError, match="identity changed"),
        store.transaction_authority(),
    ):
        generations.rename(root / "displaced-generations")
        _mkdir_private(generations)


def test_bound_generation_store_transaction_write_stays_on_retained_candidate(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = _mkdir_private(tmp_path / "store")
    generations = _mkdir_private(root / "generations")
    root_stat = root.stat()
    generations_stat = generations.stat()
    store = SuccessorGenerationStore(
        root,
        expected_root_identity=(root_stat.st_dev, root_stat.st_ino),
        expected_generations_identity=(generations_stat.st_dev, generations_stat.st_ino),
    )
    promoted = _promoted(1, "descriptor-write")
    candidate = _candidate(store, promoted)
    candidate_transaction, built, _validated, _promoted_transaction = _states(promoted)
    store.record_transaction(candidate, candidate_transaction)
    initial_bytes = (candidate / SUCCESSOR_TRANSACTION_NAME).read_bytes()
    displaced = tmp_path / "displaced-store"
    replacement: Path | None = None
    swapped = False
    real_atomic_write = SuccessorGenerationStore._atomic_write_relative

    def swapping_atomic_write(
        parent_descriptor: int,
        name: str,
        encoded: bytes,
    ) -> None:
        nonlocal replacement, swapped
        if name == SUCCESSOR_TRANSACTION_NAME and not swapped:
            root.rename(displaced)
            shutil.copytree(displaced, root)
            replacement = root
            swapped = True
        real_atomic_write(parent_descriptor, name, encoded)

    monkeypatch.setattr(
        SuccessorGenerationStore,
        "_atomic_write_relative",
        staticmethod(swapping_atomic_write),
    )
    with (
        pytest.raises(SuccessorGenerationStoreError, match="identity changed"),
        store.transaction_authority(),
    ):
        store.record_transaction(candidate, built)

    assert swapped
    assert replacement is not None
    replacement_transaction = (
        replacement / "generations" / candidate.name / SUCCESSOR_TRANSACTION_NAME
    )
    displaced_transaction = displaced / "generations" / candidate.name / SUCCESSOR_TRANSACTION_NAME
    assert replacement_transaction.read_bytes() == initial_bytes
    assert displaced_transaction.read_bytes() != initial_bytes
    assert json.loads(displaced_transaction.read_bytes())["state"] == "built"
    assert not list(replacement_transaction.parent.glob(".*.tmp"))


def test_bound_generation_store_candidate_copy_stays_under_retained_generations(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    baseline = tmp_path / "baseline"
    baseline.mkdir()
    (baseline / "nba.duckdb").write_bytes(b"baseline")
    root = _mkdir_private(tmp_path / "store")
    generations = _mkdir_private(root / "generations")
    root_stat = root.stat()
    generations_stat = generations.stat()
    store = SuccessorGenerationStore(
        root,
        expected_root_identity=(root_stat.st_dev, root_stat.st_ino),
        expected_generations_identity=(generations_stat.st_dev, generations_stat.st_ino),
    )
    transaction = _candidate_for_baseline(baseline)
    displaced = tmp_path / "displaced-store"
    replacement: Path | None = None
    real_copy = store._copy_inventory_files_relative

    def swapping_copy(
        source_root: Path,
        destination_descriptor: int,
        inventory: list[dict[str, Any]],
    ) -> None:
        nonlocal replacement
        if replacement is None:
            root.rename(displaced)
            replacement = _mkdir_private(root)
            _mkdir_private(replacement / "generations")
        real_copy(source_root, destination_descriptor, inventory)

    monkeypatch.setattr(store, "_copy_inventory_files_relative", swapping_copy)
    with (
        pytest.raises(SuccessorGenerationStoreError, match="identity"),
        store.transaction_authority(),
    ):
        _prepare(store, baseline, transaction)

    assert replacement is not None
    assert list((replacement / "generations").iterdir()) == []
    assert not (replacement / ".successor-generation-store.lock").exists()
    displaced_entries = list((displaced / "generations").iterdir())
    assert [entry.name for entry in displaced_entries] == [store.candidate_name(transaction)]
    assert (displaced_entries[0] / "public" / "nba.duckdb").read_bytes() == b"baseline"


def test_production_w2_authority_resources_build_all_real_factories(
    tmp_path: Path,
) -> None:
    paths = _layout(tmp_path)
    resources = build_production_successor_w2_authority_resources(
        body_blob_root=paths["body_blob"],
        declared_bodyless_packet_root=paths["declared_bodyless_packet"],
    )
    scope = CaptureRunScope(
        semantic_source_sha="b" * 40,
        chain_id="chain-1",
        lane_id="lane-1",
        workflow_run_id=731,
        workflow_run_attempt=1,
    )
    cases = {
        "league_game_log": {"season": "2025-26", "season_type": "Regular Season"},
        "player_game_logs": {"season": "2025-26", "season_type": "Regular Season"},
        "common_all_players": {"season": "2025-26", "is_only_current_season": 1},
        "common_team_years": {},
    }
    for endpoint_name, parameters in cases.items():
        context = resources.raw_request_context_factory(scope, endpoint_name, dict(parameters))
        assert isinstance(context, RawRequestCaptureContextV2)
        assert context.source_sha == scope.semantic_source_sha
        assert context.run_id == scope.workflow_run_id
        assert context.run_attempt == scope.workflow_run_attempt
        assert context.chain_id == scope.chain_id
        assert context.lane_id == scope.lane_id
        assert len(context.provider_calls) == 1
    runtime = resources.w2_preparation_runtime_factory(scope)
    assert isinstance(runtime, W2SourceCallPreparationRuntime)
    assert not runtime.known_secrets
    with pytest.raises(ExactPlanningRuntimeError, match="unavailable"):
        resources.live_plan_binding_factory(scope, None, None, None)
    assert resources.live_plan_binding_factory is unavailable_live_plan_binding_factory


def test_production_w2_authority_resources_reject_insecure_store_roots(
    tmp_path: Path,
) -> None:
    paths = _layout(tmp_path)
    insecure = tmp_path / "insecure"
    insecure.mkdir(mode=0o755)
    with pytest.raises(ExactSuccessorCompositionError, match="0700"):
        build_production_successor_w2_authority_resources(
            body_blob_root=insecure,
            declared_bodyless_packet_root=paths["declared_bodyless_packet"],
        )
