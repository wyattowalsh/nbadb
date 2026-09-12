from __future__ import annotations

import asyncio
import copy
import hashlib
import json
from dataclasses import replace
from typing import TYPE_CHECKING, Any

import pytest

from nbadb.orchestrate.capture_session import PrivateGenerationIdentity
from nbadb.orchestrate.orchestrator import PipelineResult
from nbadb.orchestrate.successor_assurance import SuccessorTransformOutputAttestation
from nbadb.orchestrate.successor_coordinator import (
    SuccessorAggregateCapacityContract,
    SuccessorAssuranceBuildInput,
    SuccessorCandidateAdmission,
    SuccessorCoordinator,
    SuccessorCoordinatorCheckpoint,
    SuccessorCoordinatorCheckpointStore,
    SuccessorCoordinatorError,
    SuccessorCoordinatorPhase,
    SuccessorCoordinatorRequest,
    _logical_call_bindings_sha256,
    _validate_private_generation,
    require_successor_downstream_publication,
)
from nbadb.orchestrate.successor_generation_store import (
    CURRENT_SUCCESSOR_GENERATION_NAME,
    SUCCESSOR_CANDIDATE_BASELINE_NAME,
    SUCCESSOR_TRANSACTION_NAME,
    SuccessorGenerationStore,
    SuccessorGenerationStoreError,
)
from nbadb.orchestrate.successor_inventory import measure_installed_public_tree
from nbadb.orchestrate.successor_planner import (
    ConcreteSuccessorPlanningExecutor,
    deterministic_planning_generation_id,
)
from nbadb.orchestrate.successor_planning_contract import (
    SuccessorPlanningEvidence,
    SuccessorPlanningRequest,
    build_successor_planning_evidence,
    finalize_successor_update_intent,
)
from nbadb.orchestrate.successor_planning_generation_contract import (
    PlanningDataMember,
    PlanningDispatchPhase,
    PlanningGenerationManifest,
    SealedProviderDispatch,
    SuccessorPlanningArtifactIdentity,
    canonical_planning_sha256,
)
from nbadb.orchestrate.successor_planning_semantic_contract import (
    PlanningSemanticDescriptor,
    PlanningSemanticKind,
)
from nbadb.orchestrate.successor_planning_store import (
    PlanningDatabaseSource,
    PlanningMemberSource,
    SuccessorPlanningStore,
)
from nbadb.orchestrate.successor_update_contract import (
    BaselineAssuranceIdentity,
    CallMutability,
    DeltaDisposition,
    ObservedDeltaReceipt,
    PlannedRouteReplacementBinding,
    RequestedRouteScope,
    SuccessorAssuranceIdentity,
    SuccessorGenerationState,
    SuccessorUpdateContractError,
    SuccessorUpdateIntent,
    SuccessorUpdateMode,
    SuccessorUpdateTransaction,
    canonical_json_bytes,
    canonical_sha256,
    planned_route_replacement_bindings_sha256,
)
from nbadb.orchestrate.transformers import expected_transform_output_tables
from tests.unit.orchestrate.test_successor_planner import _NeverDriver
from tests.unit.orchestrate.test_successor_planning_generation_contract import (
    _synthetic_manifest,
)
from tests.unit.orchestrate.test_successor_planning_store import (
    _admission,
    _dispatch,
    _wave_authority,
    _write_source,
)
from tests.unit.orchestrate.test_successor_planning_store import (
    _budget as _planning_store_budget,
)
from tests.unit.orchestrate.test_successor_planning_store import (
    _scope as _store_scope,
)

if TYPE_CHECKING:
    from collections.abc import Callable
    from pathlib import Path

    from nbadb.orchestrate.successor_execution_plan import SuccessorExecutionPlan

_SOURCE_SHA = "b" * 40


def _digest(label: str) -> str:
    return hashlib.sha256(label.encode()).hexdigest()


def _write_canonical_document(path: Path, payload: object) -> None:
    path.write_bytes(canonical_json_bytes(payload) + b"\n")


_MONOTONIC_EPOCH_SHA256 = _digest("monotonic-epoch")


def _inventory_digest(public_root: Path) -> str:
    return measure_installed_public_tree(public_root).installed_public_tree_sha256


def _write_real_four_format_public_tree(public: Path, *, as_of_utc: str) -> None:
    import sqlite3

    import duckdb
    import pyarrow as pa
    import pyarrow.parquet as pq

    from nbadb.orchestrate.successor_publication_inventory import (
        successor_publication_freshness_season,
    )

    season = successor_publication_freshness_season(as_of_utc)
    public.mkdir(parents=True, exist_ok=True)
    duckdb_path = public / "nba.duckdb"
    sqlite_path = public / "nba.sqlite"
    if duckdb_path.exists() or duckdb_path.is_symlink():
        duckdb_path.unlink()
    if sqlite_path.exists() or sqlite_path.is_symlink():
        sqlite_path.unlink()
    (public / "csv").mkdir(exist_ok=True)
    (public / "parquet" / "sample").mkdir(parents=True, exist_ok=True)

    connection = duckdb.connect(str(duckdb_path))
    try:
        connection.execute("CREATE TABLE sample (id BIGINT, label VARCHAR)")
        connection.execute("INSERT INTO sample VALUES (1, 'alpha')")
        connection.execute(
            """
            CREATE TABLE _pipeline_watermarks (
                table_name VARCHAR NOT NULL,
                watermark_type VARCHAR NOT NULL,
                watermark_value VARCHAR,
                last_updated TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                row_count_at_watermark BIGINT,
                PRIMARY KEY (table_name, watermark_type)
            )
            """
        )
        connection.execute(
            "INSERT INTO _pipeline_watermarks "
            "(table_name, watermark_type, watermark_value, row_count_at_watermark) "
            "VALUES ('sample', 'last_load', ?, 1)",
            [season],
        )
    finally:
        connection.close()

    sqlite = sqlite3.connect(sqlite_path)
    try:
        sqlite.execute("CREATE TABLE sample (id BIGINT, label VARCHAR)")
        sqlite.execute("INSERT INTO sample VALUES (1, 'alpha')")
        sqlite.commit()
    finally:
        sqlite.close()

    (public / "csv" / "sample.csv").write_text("id,label\n1,alpha\n", encoding="utf-8")
    pq.write_table(
        pa.table({"id": [1], "label": ["alpha"]}),
        public / "parquet" / "sample" / "sample.parquet",
    )


def _baseline(public_root: Path) -> BaselineAssuranceIdentity:
    public_measurement = measure_installed_public_tree(public_root)
    return BaselineAssuranceIdentity(
        remote_dataset="maintainer/nbadb",
        remote_dataset_version=237,
        chain_id="assured-parent",
        source_sha="a" * 40,
        coverage_fingerprint=_digest("coverage"),
        data_tree_fingerprint=_digest("baseline-tree"),
        remote_bundle_fingerprint_sha256=_digest("remote-bundle"),
        installed_public_tree_sha256=public_measurement.installed_public_tree_sha256,
        installed_public_tree_bytes=public_measurement.byte_count,
        assured_manifest_sha256=_digest("baseline-manifest"),
        terminal_assurance_report_sha256=_digest("baseline-report"),
        private_baseline_receipt_sha256=_digest("baseline-private"),
        checkpoint_database_sha256=_digest("baseline-db"),
        checkpoint_report_sha256=_digest("baseline-checkpoint"),
        contract_blocked_evidence_sha256=_digest("blocked"),
        provider_authority_sha256=_digest("provider"),
    )


def _capacity(
    baseline_installed_public_tree_bytes: int,
    **overrides: int,
) -> SuccessorAggregateCapacityContract:
    values = {
        "baseline_installed_public_tree_bytes": baseline_installed_public_tree_bytes,
        "planning_store_generation_max_bytes": 1,
        "planning_store_artifact_max_bytes": 1,
        "planning_store_control_max_bytes": 1,
        "planning_driver_database_max_bytes": 1,
        "planning_wave_count": 2,
        "planning_wave_capture_max_bytes": 1,
        "planning_wave_checkpoint_max_bytes": 1,
        "update_capture_max_bytes": 1,
        "update_checkpoint_max_bytes": 1,
        "candidate_max_bytes": 1_000_000,
        "rollback_reserve_bytes": 1,
        "coordinator_checkpoint_max_bytes": 1,
        "terminal_receipt_max_bytes": 1,
        "runtime_log_max_bytes": 1,
        "scan_database_snapshot_max_bytes": 1,
        "inventory_duckdb_snapshot_max_bytes": 1,
        "inventory_sqlite_snapshot_max_bytes": 1,
        "transform_scratch_max_bytes": 1,
        "assurance_control_max_bytes": 1,
        "minimum_free_bytes": 1,
    }
    values.update(overrides)
    return SuccessorAggregateCapacityContract(**values)


def _scope(label: str) -> RequestedRouteScope:
    return RequestedRouteScope.from_parameters(
        endpoint_name="fixture_endpoint",
        route_id=f"route.{label}",
        route_contract_sha256=_digest(f"contract:{label}"),
        parameters={"label": label},
        mutability=CallMutability.MUTABLE,
    )


def _planning(
    baseline: BaselineAssuranceIdentity,
    *,
    mode: SuccessorUpdateMode = SuccessorUpdateMode.DAILY,
) -> SuccessorPlanningEvidence:
    update_scopes = (
        _scope("changed"),
        _scope("no_change"),
        _scope("typed_zero"),
    )
    return build_successor_planning_evidence(
        planning_generation_manifest=_synthetic_manifest(
            baseline_identity_sha256=baseline.identity_sha256,
            mode=mode,
            source_sha=_SOURCE_SHA,
            cutoff_utc="2026-08-12T00:00:00Z",
            as_of_utc="2026-08-13T00:00:00Z",
            update_scopes=update_scopes,
        ),
    )


def _receipts(
    baseline: BaselineAssuranceIdentity,
    planning: SuccessorPlanningEvidence,
) -> tuple[ObservedDeltaReceipt, ...]:
    from nbadb.orchestrate.successor_planning_contract import finalize_successor_update_intent

    intent = finalize_successor_update_intent(planning)
    bindings_by_scope = {
        binding.requested_scope_sha256: binding
        for binding in planning.execution_plan.planned_route_replacement_bindings
    }
    result: list[ObservedDeltaReceipt] = []
    for scope in intent.requested_scopes:
        binding = bindings_by_scope[scope.identity_sha256]
        label = scope.route_id.removeprefix("route.")
        typed_zero = label == "typed_zero"
        prior = _digest(f"prior:{label}")
        persisted = prior if label == "no_change" else _digest(f"persisted:{label}")
        result.append(
            ObservedDeltaReceipt(
                baseline_identity_sha256=baseline.identity_sha256,
                update_intent_sha256=intent.identity_sha256,
                source_sha=intent.source_sha,
                requested_scope_sha256=scope.identity_sha256,
                execution_dispatch_identity_sha256=(binding.execution_dispatch_identity_sha256),
                planning_dependency_identity_sha256s=(binding.planning_dependency_identity_sha256s),
                disposition=(
                    DeltaDisposition.TYPED_ZERO if typed_zero else DeltaDisposition.OBSERVED
                ),
                logical_call_receipt_sha256=_digest(f"call:{label}"),
                prior_persisted_content_sha256=prior,
                source_scope_replacement_sha256=_digest(f"replacement:{label}"),
                persisted_content_sha256=persisted,
                persisted_schema_sha256=_digest(f"schema:{label}"),
                persisted_row_count=0 if typed_zero else 1,
                typed_zero_reason_code="no_rows" if typed_zero else None,
            )
        )
    return tuple(result)


def _private(
    baseline: BaselineAssuranceIdentity,
    intent: SuccessorUpdateIntent,
    receipts: tuple[ObservedDeltaReceipt, ...],
    *,
    provider_authority_sha256: str | None = None,
) -> PrivateGenerationIdentity:
    logical_root_count = len({receipt.logical_call_receipt_sha256 for receipt in receipts})
    return PrivateGenerationIdentity(
        manifest_sha256=_digest("update-private-manifest"),
        provider_authority_sha256=(provider_authority_sha256 or baseline.provider_authority_sha256),
        semantic_source_sha=_SOURCE_SHA,
        chain_id="successor-chain",
        lane_id="update",
        workflow_run_id=123,
        workflow_run_attempt=1,
        artifact_count=logical_root_count * 3,
        done_call_count=logical_root_count,
        done_call_receipt_sha256s=tuple(
            sorted({receipt.logical_call_receipt_sha256 for receipt in receipts})
        ),
        done_call_bindings_sha256=_logical_call_bindings_sha256(
            baseline=baseline,
            intent=intent,
            receipts=receipts,
        ),
        done_attempt_count=logical_root_count,
        done_blob_count=logical_root_count,
        orphan_call_count=0,
        orphan_attempt_count=0,
        orphan_blob_count=0,
        stored_bytes=4096,
    )


def _transforms() -> tuple[SuccessorTransformOutputAttestation, ...]:
    return tuple(
        SuccessorTransformOutputAttestation(
            table_name=table,
            row_count=0 if table == "agg_all_time_leaders" else 1,
            schema_sha256=_digest(f"transform-schema:{table}"),
            content_sha256=_digest(f"transform-content:{table}"),
        )
        for table in sorted(expected_transform_output_tables(include_live=True))
    )


class _PlanningExecutor:
    def __init__(self, evidence: SuccessorPlanningEvidence) -> None:
        self.evidence = evidence
        self.calls = 0
        self.verify_calls = 0
        self.verify_error: BaseException | None = None
        self.failure: BaseException | None = None

    async def __call__(self, request: SuccessorPlanningRequest) -> SuccessorPlanningEvidence:
        self.calls += 1
        if self.failure is not None:
            raise self.failure
        assert request.to_dict() == self.evidence.request.to_dict()
        return self.evidence

    def verify(
        self,
        request: SuccessorPlanningRequest,
        evidence: SuccessorPlanningEvidence,
    ) -> SuccessorPlanningEvidence:
        self.verify_calls += 1
        if self.verify_error is not None:
            raise self.verify_error
        assert request.to_dict() == self.evidence.request.to_dict()
        assert evidence.to_dict() == self.evidence.to_dict()
        return self.evidence


class _FakeMonotonicClock:
    def __init__(self, now: float = 100.0) -> None:
        self.now = now
        self.calls = 0

    def __call__(self) -> float:
        self.calls += 1
        return self.now


class _SequenceMonotonicClock:
    def __init__(self, values: list[float]) -> None:
        self.values = values
        self.calls = 0

    def __call__(self) -> float:
        value = self.values[self.calls]
        self.calls += 1
        return value


class _FakeMonotonicEpochAuthority:
    def __init__(self, epoch_sha256: str = _MONOTONIC_EPOCH_SHA256) -> None:
        self.epoch_sha256 = epoch_sha256
        self.calls = 0

    def __call__(self) -> str:
        self.calls += 1
        return self.epoch_sha256


class _Runtime:
    def __init__(
        self,
        owner: _RuntimeFactory,
        candidate_root: Path,
        *,
        receipts: tuple[ObservedDeltaReceipt, ...],
        private: object,
        transforms: tuple[SuccessorTransformOutputAttestation, ...],
    ) -> None:
        self.owner = owner
        self.candidate_root = candidate_root
        self.successor_delta_receipts = receipts
        self.capture_identity: object = private
        self.transform_output_attestations = transforms

    @property
    def planned_route_replacement_bindings_sha256(self) -> str:
        self.owner.binding_digest_reads += 1
        if self.owner.binding_digest_sequence:
            return self.owner.binding_digest_sequence.pop(0)
        return self.owner.planned_route_replacement_bindings_sha256

    async def run_daily(self) -> PipelineResult:
        return await self._run()

    async def run_monthly(self) -> PipelineResult:
        return await self._run()

    def restore_same_generation_execution(self) -> None:
        self.owner.restore_calls += 1

    async def _run(self) -> PipelineResult:
        self.owner.calls += 1
        failure = self.owner.failures.pop(0) if self.owner.failures else None
        if failure is not None:
            raise failure
        public = self.candidate_root / "public"
        if self.owner.omit_publication_formats:
            public.mkdir(parents=True, exist_ok=True)
            (public / "nba.duckdb").write_bytes(self.owner.output_bytes)
            return self.owner.pipeline_result
        _write_real_four_format_public_tree(
            public,
            as_of_utc=self.owner.intent.as_of_utc,
        )
        if self.owner.corrupt_csv_row_count:
            (public / "csv" / "sample.csv").write_text(
                "id,label\n1,alpha\n2,beta\n",
                encoding="utf-8",
            )
        return self.owner.pipeline_result


class _RuntimeFactory:
    def __init__(
        self,
        baseline: BaselineAssuranceIdentity,
        planning: SuccessorPlanningEvidence,
    ) -> None:
        receipts = _receipts(baseline, planning)
        self.intent = finalize_successor_update_intent(planning)
        self.intent_plan = planning.execution_plan
        self.planned_route_replacement_bindings_sha256 = (
            planning.planned_route_replacement_bindings_sha256
        )
        self.binding_digest_sequence: list[str] = []
        self.binding_digest_reads = 0
        self.receipts = receipts
        self.private: object = _private(baseline, self.intent, receipts)
        self.transforms = _transforms()
        self.pipeline_result = PipelineResult()
        self.output_bytes = b"successor-data"
        self.failures: list[BaseException] = []
        self.calls = 0
        self.restore_calls = 0
        self.candidate_roots: list[Path] = []
        self.execution_plans: list[SuccessorExecutionPlan] = []
        self.omit_publication_formats = False
        self.corrupt_csv_row_count = False

    def __call__(
        self,
        transaction: SuccessorUpdateTransaction,
        candidate_root: Path,
        execution_plan: SuccessorExecutionPlan,
    ) -> _Runtime:
        assert transaction.intent.source_sha == _SOURCE_SHA
        assert execution_plan.to_dict() == self.intent_plan.to_dict()
        self.execution_plans.append(execution_plan)
        self.candidate_roots.append(candidate_root)
        return _Runtime(
            self,
            candidate_root,
            receipts=self.receipts,
            private=self.private,
            transforms=self.transforms,
        )


class _AssuranceBuilder:
    def __init__(self, inventory_digest: Callable[[Path], str]) -> None:
        self.inventory_digest = inventory_digest
        self.calls = 0
        self.public_digest_override: str | None = None
        self.failure: BaseException | None = None

    async def __call__(
        self,
        build_input: SuccessorAssuranceBuildInput,
    ) -> SuccessorAssuranceIdentity:
        self.calls += 1
        if self.failure is not None:
            raise self.failure
        (build_input.candidate_root / "public" / "terminal-assurance-report.json").write_text(
            "{}\n"
        )
        assert build_input.transaction.build is not None
        assert (
            build_input.planned_route_replacement_bindings_sha256
            == build_input.transaction.build.planned_route_replacement_bindings_sha256
        )
        public_digest = self.public_digest_override or self.inventory_digest(
            build_input.candidate_root / "public"
        )
        return SuccessorAssuranceIdentity(
            baseline_identity_sha256=build_input.baseline.identity_sha256,
            update_intent_sha256=build_input.transaction.intent.identity_sha256,
            source_sha=build_input.transaction.intent.source_sha,
            generation=build_input.transaction.generation,
            requested_scopes_sha256=build_input.transaction.intent.requested_scopes_sha256,
            observed_delta_receipts_sha256=(
                build_input.transaction.build.observed_delta_receipts_sha256
            ),
            planned_route_replacement_bindings_sha256=(
                build_input.planned_route_replacement_bindings_sha256
            ),
            transform_inventory_sha256=canonical_sha256(
                [item.to_dict() for item in build_input.transform_outputs]
            ),
            scan_report_sha256=_digest("scan"),
            publication_resource_inventory_sha256=_digest("publication-resources"),
            installed_public_tree_sha256=public_digest,
            private_generation_receipt_sha256=(
                build_input.update_private_generation.identity_sha256
            ),
            successor_data_tree_fingerprint=_digest("successor-tree"),
            successor_assured_manifest_sha256=_digest("successor-manifest"),
            successor_validation_report_sha256=_digest("successor-validation"),
        )


class _PauseBeforeAssuring(SuccessorCoordinatorCheckpointStore):
    block = True

    def write(self, checkpoint: Any) -> None:
        if self.block and checkpoint.phase is SuccessorCoordinatorPhase.ASSURING:
            raise RuntimeError("injected-before-assurance")
        super().write(checkpoint)


class _PauseBeforeBuilt(SuccessorCoordinatorCheckpointStore):
    block = True

    def write(self, checkpoint: Any) -> None:
        if self.block and checkpoint.phase is SuccessorCoordinatorPhase.BUILT:
            raise RuntimeError("injected-before-built")
        super().write(checkpoint)


def _harness(
    tmp_path: Path,
    *,
    checkpoint_store: SuccessorCoordinatorCheckpointStore | None = None,
    mode: SuccessorUpdateMode = SuccessorUpdateMode.DAILY,
    monotonic_clock: Callable[[], float] | None = None,
    monotonic_epoch_authority: Callable[[], str] | None = None,
    **capacity_overrides: int,
) -> tuple[
    SuccessorCoordinatorRequest,
    SuccessorCoordinator,
    _PlanningExecutor,
    _RuntimeFactory,
    _AssuranceBuilder,
    SuccessorGenerationStore,
    SuccessorCoordinatorCheckpointStore,
]:
    public = tmp_path / "baseline-public"
    public.mkdir(parents=True)
    (public / "nba.duckdb").write_bytes(b"baseline-data")
    baseline = _baseline(public)
    planning = _planning(baseline, mode=mode)
    planner = _PlanningExecutor(planning)
    runtime = _RuntimeFactory(baseline, planning)
    assurance = _AssuranceBuilder(_inventory_digest)
    generation_store = SuccessorGenerationStore(tmp_path / "generation-store")
    store = checkpoint_store or SuccessorCoordinatorCheckpointStore(
        tmp_path / "coordinator-checkpoint.json"
    )
    request = SuccessorCoordinatorRequest(
        baseline=baseline,
        planning_request=planning.request,
        generation=1,
        baseline_public_root=public,
        candidate_admission=SuccessorCandidateAdmission(
            aggregate_capacity=_capacity(
                baseline.installed_public_tree_bytes,
                **capacity_overrides,
            ),
            monotonic_deadline_seconds=1000.0,
            minimum_pre_provider_headroom_seconds=20.0,
            minimum_deadline_headroom_seconds=10.0,
            monotonic_epoch_sha256=_MONOTONIC_EPOCH_SHA256,
        ),
    )
    coordinator = SuccessorCoordinator(
        generation_store=generation_store,
        checkpoint_store=store,
        planning_executor=planner,
        runtime_factory=runtime,
        assurance_builder=assurance,
        installed_public_tree_digest=_inventory_digest,
        monotonic_epoch_authority=(monotonic_epoch_authority or _FakeMonotonicEpochAuthority()),
        monotonic_clock=monotonic_clock or _FakeMonotonicClock(),
    )
    return request, coordinator, planner, runtime, assurance, generation_store, store


def _fresh_coordinator(
    planner: _PlanningExecutor,
    runtime: _RuntimeFactory,
    assurance: _AssuranceBuilder,
    generation_store: SuccessorGenerationStore,
    checkpoint_store: SuccessorCoordinatorCheckpointStore,
    *,
    monotonic_clock: Callable[[], float] | None = None,
    monotonic_epoch_authority: Callable[[], str] | None = None,
) -> SuccessorCoordinator:
    return SuccessorCoordinator(
        generation_store=generation_store,
        checkpoint_store=checkpoint_store,
        planning_executor=planner,
        runtime_factory=runtime,
        assurance_builder=assurance,
        installed_public_tree_digest=_inventory_digest,
        monotonic_epoch_authority=(monotonic_epoch_authority or _FakeMonotonicEpochAuthority()),
        monotonic_clock=monotonic_clock or _FakeMonotonicClock(),
    )


class _RetainedWaveAuthorityResolver:
    def verify(self, **kwargs: object) -> PrivateGenerationIdentity:
        authority = kwargs["authority"]
        identity = getattr(authority, "private_generation_identity", None)
        if not isinstance(identity, PrivateGenerationIdentity):
            raise AssertionError("planning store authority is missing a private generation")
        return identity


class _StoreBackedPlanningExecutor:
    """Concrete store-backed planner with the phase-machine counters tests assert."""

    def __init__(
        self,
        executor: ConcreteSuccessorPlanningExecutor,
        evidence: SuccessorPlanningEvidence,
    ) -> None:
        self._executor = executor
        self.evidence = evidence
        self.calls = 0
        self.verify_calls = 0
        self.verify_error: BaseException | None = None

    async def __call__(self, request: SuccessorPlanningRequest) -> SuccessorPlanningEvidence:
        self.calls += 1
        verified = await self._executor(request)
        self.evidence = verified
        return verified

    def verify(
        self,
        request: SuccessorPlanningRequest,
        evidence: SuccessorPlanningEvidence,
    ) -> SuccessorPlanningEvidence:
        self.verify_calls += 1
        if self.verify_error is not None:
            raise self.verify_error
        return self._executor.verify(request, evidence)


def _seal_compact_store_planning(
    tmp_path: Path,
    baseline: BaselineAssuranceIdentity,
    *,
    mode: SuccessorUpdateMode,
) -> tuple[ConcreteSuccessorPlanningExecutor, SuccessorPlanningEvidence, Path]:
    """Seal one compact two-wave generation the concrete executor can reload."""

    public_root = tmp_path / "baseline-public"
    store_root = (tmp_path / "private-planning").resolve()
    sources = tmp_path / "private-sources"
    sources.mkdir(mode=0o700)
    sources.chmod(0o700)
    work = tmp_path / "planning-work"
    work.mkdir(mode=0o700)
    work.chmod(0o700)
    store = SuccessorPlanningStore(
        store_root,
        public_roots=(public_root.resolve(),),
        monotonic_clock=lambda: 100.0,
    )
    wave_0_scope = _store_scope(
        "1",
        endpoint="scoreboard_v3",
        route="scoreboard_v3:stg_scoreboard_games",
        parameters={"game_date": "2026-08-01", "league_id": "00"},
    )
    wave_1_scope = _store_scope(
        "2",
        endpoint="cume_stats_player_games",
        route="cume_stats_player_games:stg_cume_player_games",
        parameters={
            "player_id": 2544,
            "season": "2025-26",
            "season_type": "Regular Season",
        },
    )
    request = SuccessorPlanningRequest(
        baseline_identity_sha256=baseline.identity_sha256,
        mode=mode,
        source_sha=_SOURCE_SHA,
        cutoff_utc="2026-08-12T00:00:00Z",
        as_of_utc="2026-08-13T00:00:00Z",
        workflow_run_id=17,
        workflow_run_attempt=1,
        requested_planning_scopes=(wave_0_scope,),
    )
    generation_id = deterministic_planning_generation_id(request)
    budget = _planning_store_budget()
    store.begin_generation(request, generation_id, budget=budget)
    wave_0_dispatch = _dispatch((wave_0_scope,), wave_index=0, pattern="scoreboard_v3")
    store.begin_wave(
        request,
        generation_id,
        admission=_admission((wave_0_scope,), wave_index=0, dispatches=(wave_0_dispatch,)),
        budget=budget,
    )
    wave_0_member_artifact = _write_source(sources / "live-game-ids.json", b"[]")
    wave_0_member = PlanningDataMember(
        member_id="live_game_ids",
        wave_index=0,
        producing_scope_sha256=wave_0_scope.identity_sha256,
        schema_sha256="3" * 64,
        content_sha256=wave_0_member_artifact.sha256,
        row_count=0,
        semantic=PlanningSemanticDescriptor.from_partition(
            semantic_kind=PlanningSemanticKind.ACTIVE_LIVE_GAME_IDS,
            partition={"as_of_utc": request.as_of_utc},
            semantic_schema_sha256="3" * 64,
            semantic_content_sha256=wave_0_member_artifact.sha256,
            value_count=0,
            typed_zero_reason_code="scoreboard_complete_empty",
        ),
        typed_zero_reason_code="scoreboard_complete_empty",
    )
    wave_0_member_source = PlanningMemberSource(
        member=wave_0_member,
        receipt_sha256="4" * 64,
        artifact=wave_0_member_artifact,
    )
    wave_0_database = PlanningDatabaseSource(
        artifact=_write_source(sources / "planning-wave-0.duckdb", b"DUCKDB-WAVE-0"),
        schema_sha256="5" * 64,
    )
    store.commit_call(
        request,
        generation_id,
        sealed_dispatch_identity_sha256=wave_0_dispatch.identity_sha256,
        members=(wave_0_member_source,),
        planning_database=wave_0_database,
        budget=budget,
    )
    wave_0_admission = _admission((wave_0_scope,), wave_index=0, dispatches=(wave_0_dispatch,))
    wave_0, wave_0_private, wave_0_receipt = _wave_authority(
        store,
        request,
        generation_id,
        wave_index=0,
        admission=wave_0_admission,
        planning_database=wave_0_database,
        budget=budget,
    )
    store.commit_wave(
        request,
        generation_id,
        wave=wave_0,
        planning_database=wave_0_database,
        private_generation_identity=wave_0_private,
        completion_receipt=wave_0_receipt,
        budget=budget,
    )
    wave_1_dispatch = _dispatch(
        (wave_1_scope,),
        wave_index=1,
        dependency_identity_sha256s=(wave_0_member.identity_sha256,),
        pattern="cume_stats_player_games",
    )
    wave_1_admission = _admission(
        (wave_1_scope,),
        wave_index=1,
        parent_wave_identity_sha256=wave_0.identity_sha256,
        dispatches=(wave_1_dispatch,),
    )
    store.begin_wave(request, generation_id, admission=wave_1_admission, budget=budget)
    wave_1_member_artifact = _write_source(
        sources / "player-foundation.json",
        b'{"game_ids":["0022600001"]}',
    )
    wave_1_member = PlanningDataMember(
        member_id="player_cume_foundation",
        wave_index=1,
        producing_scope_sha256=wave_1_scope.identity_sha256,
        schema_sha256="8" * 64,
        content_sha256=wave_1_member_artifact.sha256,
        row_count=1,
        semantic=PlanningSemanticDescriptor.from_partition(
            semantic_kind=PlanningSemanticKind.PLAYER_CUME_FOUNDATION_GAME_IDS,
            partition={
                "player_id": 2544,
                "season": "2025-26",
                "season_type": "Regular Season",
            },
            semantic_schema_sha256="8" * 64,
            semantic_content_sha256=wave_1_member_artifact.sha256,
            value_count=1,
        ),
    )
    wave_1_member_source = PlanningMemberSource(
        member=wave_1_member,
        receipt_sha256="9" * 64,
        artifact=wave_1_member_artifact,
    )
    wave_1_database = PlanningDatabaseSource(
        artifact=_write_source(sources / "planning-wave-1.duckdb", b"DUCKDB-WAVE-1"),
        schema_sha256="c" * 64,
    )
    store.commit_call(
        request,
        generation_id,
        sealed_dispatch_identity_sha256=wave_1_dispatch.identity_sha256,
        members=(wave_1_member_source,),
        planning_database=wave_1_database,
        budget=budget,
    )
    wave_1, wave_1_private, wave_1_receipt = _wave_authority(
        store,
        request,
        generation_id,
        wave_index=1,
        admission=wave_1_admission,
        planning_database=wave_1_database,
        budget=budget,
        parent_wave_identity_sha256=wave_0.identity_sha256,
    )
    store.commit_wave(
        request,
        generation_id,
        wave=wave_1,
        planning_database=wave_1_database,
        private_generation_identity=wave_1_private,
        completion_receipt=wave_1_receipt,
        budget=budget,
    )
    members = tuple(
        sorted(
            (wave_0_member_source.member, wave_1_member_source.member),
            key=lambda item: item.identity_sha256,
        )
    )
    update_dispatches = (
        SealedProviderDispatch.from_parameters(
            phase=PlanningDispatchPhase.UPDATE,
            endpoint_name=wave_0_scope.endpoint_name,
            requested_scope_identity_sha256s=(wave_0_scope.identity_sha256,),
            parameters=wave_0_scope.parameters,
            pattern="scoreboard_v3",
            staging_route_ids=(wave_0_scope.route_id,),
            dependency_identity_sha256s=(wave_0_member.identity_sha256,),
        ),
        SealedProviderDispatch.from_parameters(
            phase=PlanningDispatchPhase.UPDATE,
            endpoint_name=wave_1_scope.endpoint_name,
            requested_scope_identity_sha256s=(wave_1_scope.identity_sha256,),
            parameters=wave_1_scope.parameters,
            pattern="cume_stats_player_games",
            staging_route_ids=(wave_1_scope.route_id,),
            dependency_identity_sha256s=(wave_1_member.identity_sha256,),
        ),
    )
    dispatches = (wave_0_dispatch, wave_1_dispatch, *update_dispatches)
    scopes = tuple(sorted((wave_0_scope, wave_1_scope), key=lambda scope: scope.identity_sha256))
    artifact_identity = SuccessorPlanningArtifactIdentity(
        planning_request_sha256=request.identity_sha256,
        planning_generation_id=generation_id,
        planning_database_sha256=wave_1_database.artifact.sha256,
        planning_database_bytes=wave_1_database.artifact.byte_count,
        planning_database_schema_sha256=wave_1_database.schema_sha256,
        member_inventory_sha256=canonical_planning_sha256([member.to_dict() for member in members]),
        private_generation_identity_sha256=canonical_planning_sha256(
            [
                wave_0.private_generation_identity_sha256,
                wave_1.private_generation_identity_sha256,
            ]
        ),
        wave_inventory_sha256=canonical_planning_sha256([wave_0.to_dict(), wave_1.to_dict()]),
        planning_manifest_sha256="0" * 64,
        sealed_dispatch_inventory_sha256=canonical_planning_sha256(
            [dispatch.to_dict() for dispatch in dispatches]
        ),
    )
    manifest = PlanningGenerationManifest.seal(
        request=request,
        artifact_identity=artifact_identity,
        waves=(wave_0, wave_1),
        members=members,
        requested_route_scopes=scopes,
        sealed_dispatches=dispatches,
    )
    sealed = store.seal_generation(
        request,
        generation_id,
        manifest=manifest,
        budget=budget,
    )
    assert sealed.phase.name == "SEALED"
    work_stat = work.stat()
    executor = ConcreteSuccessorPlanningExecutor(
        store,
        _NeverDriver(),
        _RetainedWaveAuthorityResolver(),
        _planning_store_budget,
        planning_driver_database_max_bytes=4 * 1024 * 1024,
        planning_work_root=work.resolve(),
        expected_planning_work_root_identity=(work_stat.st_dev, work_stat.st_ino),
    )
    executor._require_current_request = staticmethod(lambda _request: None)  # type: ignore[method-assign]
    evidence = build_successor_planning_evidence(planning_generation_manifest=manifest)
    evidence.execution_plan.validate_against_manifest(manifest)
    return executor, evidence, store_root


def _store_backed_harness(
    tmp_path: Path,
    *,
    mode: SuccessorUpdateMode = SuccessorUpdateMode.DAILY,
) -> tuple[
    SuccessorCoordinatorRequest,
    SuccessorCoordinator,
    _StoreBackedPlanningExecutor,
    _RuntimeFactory,
    SuccessorCoordinatorCheckpointStore,
    Path,
]:
    public = tmp_path / "baseline-public"
    public.mkdir(parents=True)
    (public / "nba.duckdb").write_bytes(b"baseline-data")
    baseline = _baseline(public)
    inner, planning, store_root = _seal_compact_store_planning(
        tmp_path,
        baseline,
        mode=mode,
    )
    planner = _StoreBackedPlanningExecutor(inner, planning)
    runtime = _RuntimeFactory(baseline, planning)
    assurance = _AssuranceBuilder(_inventory_digest)
    generation_store = SuccessorGenerationStore(tmp_path / "generation-store")
    checkpoint_store = SuccessorCoordinatorCheckpointStore(tmp_path / "coordinator-checkpoint.json")
    request = SuccessorCoordinatorRequest(
        baseline=baseline,
        planning_request=planning.request,
        generation=1,
        baseline_public_root=public,
        candidate_admission=SuccessorCandidateAdmission(
            aggregate_capacity=_capacity(baseline.installed_public_tree_bytes),
            monotonic_deadline_seconds=1000.0,
            minimum_pre_provider_headroom_seconds=20.0,
            minimum_deadline_headroom_seconds=10.0,
            monotonic_epoch_sha256=_MONOTONIC_EPOCH_SHA256,
        ),
    )
    coordinator = SuccessorCoordinator(
        generation_store=generation_store,
        checkpoint_store=checkpoint_store,
        planning_executor=planner,
        runtime_factory=runtime,
        assurance_builder=assurance,
        installed_public_tree_digest=_inventory_digest,
        monotonic_epoch_authority=_FakeMonotonicEpochAuthority(),
        monotonic_clock=_FakeMonotonicClock(),
    )
    return request, coordinator, planner, runtime, checkpoint_store, store_root


def test_aggregate_capacity_contract_is_path_free_canonical_schema_v1() -> None:
    contract = _capacity(13)
    payload = contract.to_dict()

    assert payload["schema_version"] == 1
    assert payload["kind"] == "successor_aggregate_capacity_contract"
    assert SuccessorAggregateCapacityContract.from_dict(payload) == contract
    assert contract.update_private_generation_max_bytes == 2
    assert not any("path" in field_name or "device" in field_name for field_name in payload)


@pytest.mark.parametrize(
    "field_name",
    SuccessorAggregateCapacityContract._bound_field_names(),
)
@pytest.mark.parametrize("value", [False, 0, 1 << 63])
def test_aggregate_capacity_contract_rejects_noncanonical_bounds(
    field_name: str,
    value: object,
) -> None:
    with pytest.raises(SuccessorCoordinatorError, match="positive signed-63-bit"):
        replace(_capacity(13), **{field_name: value})


def test_aggregate_capacity_contract_rejects_old_schema_field_and_checked_sum_overflow() -> None:
    payload = _capacity(13).to_dict()
    old_schema = dict(payload)
    old_schema["schema_version"] = 0
    with pytest.raises(SuccessorCoordinatorError, match="schema is invalid"):
        SuccessorAggregateCapacityContract.from_dict(old_schema)

    old_field = dict(payload)
    old_field["private_generation_estimated_bytes"] = 1
    with pytest.raises(SuccessorCoordinatorError, match="fields are invalid"):
        SuccessorAggregateCapacityContract.from_dict(old_field)

    with pytest.raises(SuccessorCoordinatorError, match="exactly 2"):
        replace(_capacity(13), planning_wave_count=3)

    individually_valid = _capacity(
        13,
        update_capture_max_bytes=(1 << 63) - 1,
        update_checkpoint_max_bytes=1,
    )
    with pytest.raises(SuccessorCoordinatorError, match="exceeds signed-63-bit"):
        _ = individually_valid.update_private_generation_max_bytes


def test_candidate_admission_hard_cuts_old_fields_and_requires_pre_provider_headroom() -> None:
    admission = SuccessorCandidateAdmission(
        aggregate_capacity=_capacity(13),
        monotonic_deadline_seconds=1000.0,
        minimum_pre_provider_headroom_seconds=20.0,
        minimum_deadline_headroom_seconds=10.0,
        monotonic_epoch_sha256=_MONOTONIC_EPOCH_SHA256,
    )
    assert SuccessorCandidateAdmission.from_dict(admission.to_dict()) == admission

    old_payload = admission.to_dict()
    old_payload["private_generation_estimated_bytes"] = 1
    with pytest.raises(SuccessorCoordinatorError, match="fields are invalid"):
        SuccessorCandidateAdmission.from_dict(old_payload)

    with pytest.raises(SuccessorCoordinatorError, match="must be at least"):
        replace(
            admission,
            minimum_pre_provider_headroom_seconds=9.0,
        )


def test_request_rejects_aggregate_baseline_byte_tamper(tmp_path: Path) -> None:
    public = tmp_path / "baseline-public"
    public.mkdir()
    (public / "nba.duckdb").write_bytes(b"baseline")
    baseline = _baseline(public)
    planning = _planning(baseline)
    admission = SuccessorCandidateAdmission(
        aggregate_capacity=_capacity(baseline.installed_public_tree_bytes + 1),
        monotonic_deadline_seconds=1000.0,
        minimum_pre_provider_headroom_seconds=20.0,
        minimum_deadline_headroom_seconds=10.0,
        monotonic_epoch_sha256=_MONOTONIC_EPOCH_SHA256,
    )

    with pytest.raises(SuccessorCoordinatorError, match="baseline byte count differs"):
        SuccessorCoordinatorRequest(
            baseline=baseline,
            planning_request=planning.request,
            generation=1,
            baseline_public_root=public,
            candidate_admission=admission,
        )


def test_one_logical_call_closes_multiple_exact_route_receipts(tmp_path: Path) -> None:
    public = tmp_path / "baseline-public"
    public.mkdir()
    (public / "nba.duckdb").write_bytes(b"baseline")
    baseline = _baseline(public)
    scopes = tuple(
        RequestedRouteScope.from_parameters(
            endpoint_name="fixture_multi",
            route_id=f"fixture_multi:stg_route_{index}:{index}",
            route_contract_sha256=_digest(f"multi-contract:{index}"),
            parameters={"season": "2025-26"},
            mutability=CallMutability.MUTABLE,
        )
        for index in range(2)
    )
    dispatch_identity_sha256 = _digest("multi-dispatch")
    dependency_identity_sha256s = (
        _digest("multi-dependency-a"),
        _digest("multi-dependency-b"),
    )
    bindings = tuple(
        PlannedRouteReplacementBinding(
            requested_scope_sha256=scope.identity_sha256,
            execution_dispatch_identity_sha256=dispatch_identity_sha256,
            planning_dependency_identity_sha256s=dependency_identity_sha256s,
        )
        for scope in scopes
    )
    intent = SuccessorUpdateIntent(
        baseline_identity_sha256=baseline.identity_sha256,
        planning_generation_manifest_sha256=_digest("multi-planning-manifest"),
        successor_execution_plan_sha256=_digest("multi-execution-plan"),
        planned_route_replacement_bindings_sha256=(
            planned_route_replacement_bindings_sha256(bindings)
        ),
        mode=SuccessorUpdateMode.DAILY,
        source_sha=_SOURCE_SHA,
        cutoff_utc="2026-08-12T00:00:00Z",
        as_of_utc="2026-08-13T00:00:00Z",
        requested_scopes=scopes,
    )
    root = _digest("one-multi-route-call")
    receipts = tuple(
        ObservedDeltaReceipt(
            baseline_identity_sha256=baseline.identity_sha256,
            update_intent_sha256=intent.identity_sha256,
            source_sha=intent.source_sha,
            requested_scope_sha256=scope.identity_sha256,
            execution_dispatch_identity_sha256=dispatch_identity_sha256,
            planning_dependency_identity_sha256s=dependency_identity_sha256s,
            disposition=DeltaDisposition.OBSERVED,
            logical_call_receipt_sha256=root,
            prior_persisted_content_sha256=_digest(f"prior:{index}"),
            source_scope_replacement_sha256=_digest(f"replacement:{index}"),
            persisted_content_sha256=_digest(f"persisted:{index}"),
            persisted_schema_sha256=_digest(f"schema:{index}"),
            persisted_row_count=1,
        )
        for index, scope in enumerate(scopes)
    )
    private = PrivateGenerationIdentity(
        manifest_sha256=_digest("multi-private"),
        provider_authority_sha256=baseline.provider_authority_sha256,
        semantic_source_sha=intent.source_sha,
        chain_id="successor-chain",
        lane_id="update",
        workflow_run_id=123,
        workflow_run_attempt=1,
        artifact_count=3,
        done_call_count=1,
        done_call_receipt_sha256s=(root,),
        done_call_bindings_sha256=_logical_call_bindings_sha256(
            baseline=baseline,
            intent=intent,
            receipts=receipts,
        ),
        done_attempt_count=1,
        done_blob_count=1,
        orphan_call_count=0,
        orphan_attempt_count=0,
        orphan_blob_count=0,
        stored_bytes=4096,
    )

    _validate_private_generation(
        private,
        baseline=baseline,
        intent=intent,
        receipts=receipts,
    )
    with pytest.raises(SuccessorCoordinatorError, match="done_call_bindings_sha256"):
        _validate_private_generation(
            replace(private, done_call_bindings_sha256=_digest("foreign-binding")),
            baseline=baseline,
            intent=intent,
            receipts=receipts,
        )


@pytest.mark.parametrize("mode", [SuccessorUpdateMode.DAILY, SuccessorUpdateMode.MONTHLY])
async def test_changed_no_change_and_typed_zero_generation_promotes_atomically(
    tmp_path: Path,
    mode: SuccessorUpdateMode,
) -> None:
    request, coordinator, planner, runtime, assurance, store, checkpoint_store = _harness(
        tmp_path,
        mode=mode,
    )

    result = await coordinator.run(request)

    assert result.checkpoint.phase is SuccessorCoordinatorPhase.PROMOTED
    assert result.transaction.promoted_assurance == result.checkpoint.assurance
    coordinator.require_downstream_publication()
    require_successor_downstream_publication(
        checkpoint=result.checkpoint,
        current_pointer=result.current_pointer,
    )
    assert planner.calls == runtime.calls == assurance.calls == 1
    assert runtime.execution_plans == [planner.evidence.execution_plan]
    assert result.transaction.build is not None
    receipts = result.transaction.build.observed_delta_receipts
    assert sum(item.disposition is DeltaDisposition.TYPED_ZERO for item in receipts) == 1
    assert (
        sum(
            item.prior_persisted_content_sha256 == item.persisted_content_sha256
            for item in receipts
        )
        == 1
    )
    assert len(result.checkpoint.transform_outputs) == len(
        expected_transform_output_tables(include_live=True)
    )
    assert store.read_current() == result.current_pointer
    assert checkpoint_store.load() == result.checkpoint
    checkpoint_payload = json.loads(result.checkpoint.canonical_bytes)
    assert checkpoint_payload["schema_version"] == 7
    assert checkpoint_payload["planned_route_replacement_bindings_sha256"] == (
        planner.evidence.planned_route_replacement_bindings_sha256
    )
    assert checkpoint_payload["candidate_admission"] == request.candidate_admission.to_dict()
    assert "monotonic_now_seconds" not in checkpoint_payload["candidate_admission"]
    assert (
        checkpoint_payload["candidate_admission"]["monotonic_epoch_sha256"]
        == _MONOTONIC_EPOCH_SHA256
    )
    previous_schema = dict(checkpoint_payload)
    previous_schema["schema_version"] = 6
    with pytest.raises(SuccessorCoordinatorError, match="checkpoint schema is invalid"):
        SuccessorCoordinatorCheckpoint.from_dict(previous_schema)


async def test_promoted_run_collects_retired_generations_once_after_promote(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    request, coordinator, _planner, _runtime, _assurance, store, _checkpoint_store = _harness(
        tmp_path
    )
    observed: list[str] = []
    original_promote = store.promote
    original_collect = store.collect_retired_generations

    def recording_promote(*args: Any, **kwargs: Any) -> object:
        observed.append("promote")
        return original_promote(*args, **kwargs)

    def recording_collect(*args: Any, **kwargs: Any) -> tuple[str, ...]:
        observed.append("collect")
        return original_collect(*args, **kwargs)

    monkeypatch.setattr(store, "promote", recording_promote)
    monkeypatch.setattr(store, "collect_retired_generations", recording_collect)

    result = await coordinator.run(request)

    assert result.checkpoint.phase is SuccessorCoordinatorPhase.PROMOTED
    assert result.current_pointer is not None
    assert store.read_current() == result.current_pointer
    assert observed == ["promote", "collect"]
    assert original_collect() == ()


async def test_retired_generation_collection_error_fails_closed(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    request, coordinator, _planner, _runtime, _assurance, store, checkpoint_store = _harness(
        tmp_path
    )

    def failing_collect(*args: Any, **kwargs: Any) -> tuple[str, ...]:
        raise SuccessorGenerationStoreError("injected-retired-generation-collection-failure")

    monkeypatch.setattr(store, "collect_retired_generations", failing_collect)

    with pytest.raises(
        SuccessorCoordinatorError,
        match="retired generation collection failed after durable promotion",
    ):
        await coordinator.run(request)

    assert store.read_current() is not None
    checkpoint = checkpoint_store.load()
    assert checkpoint is not None
    assert checkpoint.phase is SuccessorCoordinatorPhase.PROMOTED


async def test_promote_fails_closed_when_publication_formats_are_missing(
    tmp_path: Path,
) -> None:
    request, coordinator, _planner, runtime, _assurance, store, checkpoint_store = _harness(
        tmp_path
    )
    runtime.omit_publication_formats = True

    with pytest.raises(
        SuccessorGenerationStoreError,
        match="missing required publication format",
    ):
        await coordinator.run(request)

    assert store.read_current() is None
    checkpoint = checkpoint_store.load()
    assert checkpoint is not None
    assert checkpoint.phase is SuccessorCoordinatorPhase.TRANSACTION_PROMOTED


async def test_promote_fails_closed_when_four_format_parity_mismatches(
    tmp_path: Path,
) -> None:
    request, coordinator, _planner, runtime, _assurance, store, checkpoint_store = _harness(
        tmp_path
    )
    runtime.corrupt_csv_row_count = True

    with pytest.raises(
        SuccessorGenerationStoreError,
        match="publication inventory failed",
    ):
        await coordinator.run(request)

    assert store.read_current() is None
    checkpoint = checkpoint_store.load()
    assert checkpoint is not None
    assert checkpoint.phase is SuccessorCoordinatorPhase.TRANSACTION_PROMOTED


@pytest.mark.parametrize(
    ("mutation", "message"),
    [
        (
            lambda payload: payload.pop("planned_route_replacement_bindings_sha256"),
            "checkpoint fields are invalid",
        ),
        (
            lambda payload: payload.__setitem__("planned_route_replacement_bindings_sha256", True),
            "lowercase SHA-256",
        ),
        (
            lambda payload: payload.__setitem__(
                "planned_route_replacement_bindings_sha256", _digest("foreign-checkpoint")
            ),
            "route replacement binding authority differs",
        ),
    ],
)
async def test_checkpoint_schema7_rejects_missing_typed_or_foreign_route_binding_digest(
    tmp_path: Path,
    mutation: Callable[[dict[str, Any]], object],
    message: str,
) -> None:
    request, coordinator, _planner, _runtime, _assurance, _store, _checkpoint_store = _harness(
        tmp_path
    )
    result = await coordinator.run(request)
    payload = json.loads(result.checkpoint.canonical_bytes)
    mutation(payload)

    with pytest.raises(SuccessorCoordinatorError, match=message):
        SuccessorCoordinatorCheckpoint.from_dict(payload)


def test_checkpoint_route_binding_digest_is_absent_only_before_planned(tmp_path: Path) -> None:
    public = tmp_path / "baseline-public"
    public.mkdir()
    (public / "nba.duckdb").write_bytes(b"baseline")
    baseline = _baseline(public)
    planning = _planning(baseline)
    admission = SuccessorCandidateAdmission(
        aggregate_capacity=_capacity(baseline.installed_public_tree_bytes),
        monotonic_deadline_seconds=1000.0,
        minimum_pre_provider_headroom_seconds=20.0,
        minimum_deadline_headroom_seconds=10.0,
        monotonic_epoch_sha256=_MONOTONIC_EPOCH_SHA256,
    )
    requested = SuccessorCoordinatorCheckpoint(
        phase=SuccessorCoordinatorPhase.REQUESTED,
        baseline=baseline,
        planning_request=planning.request,
        generation=1,
        candidate_admission=admission,
    )
    assert requested.planned_route_replacement_bindings_sha256 is None

    with pytest.raises(SuccessorCoordinatorError, match="binding phase is invalid"):
        replace(
            requested,
            phase=SuccessorCoordinatorPhase.PLANNED,
            planning_evidence=planning,
        )
    with pytest.raises(SuccessorCoordinatorError, match="binding phase is invalid"):
        replace(
            requested,
            planned_route_replacement_bindings_sha256=(
                planning.planned_route_replacement_bindings_sha256
            ),
        )


async def test_runtime_route_binding_relabel_fails_inside_candidate_mutation_before_effects(
    tmp_path: Path,
) -> None:
    request, coordinator, _planner, runtime, assurance, store, checkpoint_store = _harness(tmp_path)
    runtime.planned_route_replacement_bindings_sha256 = _digest("foreign-runtime")

    with pytest.raises(
        SuccessorCoordinatorError,
        match="runtime route replacement binding authority differs",
    ):
        await coordinator.run(request)

    checkpoint = checkpoint_store.load()
    assert checkpoint is not None
    assert checkpoint.phase is SuccessorCoordinatorPhase.EXECUTING
    assert runtime.calls == assurance.calls == 0
    assert runtime.binding_digest_reads == 1
    assert store.read_current() is None


async def test_runtime_route_binding_drift_after_provider_fails_before_checkpoint_executed(
    tmp_path: Path,
) -> None:
    request, coordinator, planner, runtime, assurance, store, checkpoint_store = _harness(tmp_path)
    expected = planner.evidence.planned_route_replacement_bindings_sha256
    runtime.binding_digest_sequence = [expected, _digest("runtime-post-provider-relabel")]

    with pytest.raises(
        SuccessorCoordinatorError,
        match="runtime route replacement binding authority differs",
    ):
        await coordinator.run(request)

    checkpoint = checkpoint_store.load()
    assert checkpoint is not None
    assert checkpoint.phase is SuccessorCoordinatorPhase.EXECUTING
    assert runtime.calls == 1
    assert assurance.calls == 0
    assert runtime.binding_digest_reads == 2
    assert store.read_current() is None


async def test_self_consistent_receipt_binding_relabel_never_reaches_executed_checkpoint(
    tmp_path: Path,
) -> None:
    request, coordinator, _planner, runtime, assurance, store, checkpoint_store = _harness(tmp_path)
    foreign_dependencies = (_digest("foreign-self-consistent-dependency"),)
    runtime.receipts = tuple(
        replace(
            receipt,
            execution_dispatch_identity_sha256=_digest(
                f"foreign-self-consistent-dispatch:{receipt.requested_scope_sha256}"
            ),
            planning_dependency_identity_sha256s=foreign_dependencies,
        )
        for receipt in runtime.receipts
    )
    runtime.private = _private(request.baseline, runtime.intent, runtime.receipts)

    with pytest.raises(
        SuccessorUpdateContractError,
        match="observed planned route replacement bindings differ from the sealed plan",
    ):
        await coordinator.run(request)

    checkpoint = checkpoint_store.load()
    assert checkpoint is not None
    assert checkpoint.phase is SuccessorCoordinatorPhase.EXECUTING
    assert runtime.calls == 1
    assert assurance.calls == 0
    assert store.read_current() is None


async def test_exception_resumes_same_executing_transaction_without_replanning(
    tmp_path: Path,
) -> None:
    epoch_authority = _FakeMonotonicEpochAuthority()
    request, coordinator, planner, runtime, assurance, store, checkpoint_store = _harness(
        tmp_path,
        monotonic_epoch_authority=epoch_authority,
    )
    runtime.failures.append(RuntimeError("injected-runtime-crash"))

    with pytest.raises(RuntimeError, match="injected-runtime-crash"):
        await coordinator.run(request)
    checkpoint = checkpoint_store.load()
    assert checkpoint is not None
    assert checkpoint.phase is SuccessorCoordinatorPhase.EXECUTING
    assert store.read_current() is None

    result = await coordinator.run(request)
    assert result.checkpoint.phase is SuccessorCoordinatorPhase.PROMOTED
    assert planner.calls == 1
    assert planner.verify_calls == 2
    assert runtime.calls == 2
    assert runtime.restore_calls == 0
    assert assurance.calls == 1
    assert epoch_authority.calls == 2


async def test_executed_resume_restores_runtime_state_without_reexecution(
    tmp_path: Path,
) -> None:
    checkpoint_store = _PauseBeforeBuilt(tmp_path / "coordinator-checkpoint.json")
    request, coordinator, planner, runtime, assurance, store, persisted = _harness(
        tmp_path,
        checkpoint_store=checkpoint_store,
    )

    with pytest.raises(RuntimeError, match="injected-before-built"):
        await coordinator.run(request)
    checkpoint = persisted.load()
    assert checkpoint is not None
    assert checkpoint.phase is SuccessorCoordinatorPhase.EXECUTED
    assert runtime.calls == 1
    assert runtime.restore_calls == 0
    first_candidate = runtime.candidate_roots[-1]

    checkpoint_store.block = False
    result = await coordinator.run(request)

    assert result.checkpoint.phase is SuccessorCoordinatorPhase.PROMOTED
    assert planner.calls == 1
    assert runtime.calls == 1
    assert runtime.restore_calls == 1
    assert runtime.candidate_roots[-1] == first_candidate
    assert first_candidate.exists()
    assert assurance.calls == 1
    assert store.read_current() == result.current_pointer


async def test_executed_resume_rejects_restored_receipt_drift(
    tmp_path: Path,
) -> None:
    checkpoint_store = _PauseBeforeBuilt(tmp_path / "coordinator-checkpoint.json")
    request, coordinator, planner, runtime, assurance, store, persisted = _harness(
        tmp_path,
        checkpoint_store=checkpoint_store,
    )
    with pytest.raises(RuntimeError, match="injected-before-built"):
        await coordinator.run(request)
    prior_calls = runtime.calls
    drifted = replace(
        runtime.receipts[0],
        persisted_content_sha256=_digest("executed-receipt-drift"),
    )
    runtime.receipts = (drifted, *runtime.receipts[1:])

    with pytest.raises(
        SuccessorCoordinatorError,
        match="restored replacement receipts differ from the executed checkpoint",
    ):
        await coordinator.run(request)

    assert runtime.calls == prior_calls
    assert runtime.restore_calls == 1
    assert planner.calls == 1
    assert assurance.calls == 0
    assert store.read_current() is None


async def test_cross_run_resume_reuses_persisted_planning_capture_coordinates(
    tmp_path: Path,
) -> None:
    request, coordinator, planner, runtime, assurance, store, checkpoint_store = _harness(tmp_path)
    runtime.failures.append(RuntimeError("injected-runtime-crash"))

    with pytest.raises(RuntimeError, match="injected-runtime-crash"):
        await coordinator.run(request)
    checkpoint = checkpoint_store.load()
    assert checkpoint is not None
    assert checkpoint.phase is SuccessorCoordinatorPhase.EXECUTING

    for field_name in ("workflow_run_id", "workflow_run_attempt"):
        drifted_planning_request = replace(
            request.planning_request,
            **{
                field_name: getattr(request.planning_request, field_name) + 1,
            },
        )
        with pytest.raises(SuccessorCoordinatorError, match="resume request differs"):
            await coordinator.run(replace(request, planning_request=drifted_planning_request))

    persisted_request = SuccessorPlanningRequest.from_dict(checkpoint.planning_request.to_dict())
    result = await coordinator.run(replace(request, planning_request=persisted_request))

    assert result.checkpoint.phase is SuccessorCoordinatorPhase.PROMOTED
    assert result.checkpoint.planning_request == persisted_request
    assert planner.calls == 1
    assert runtime.calls == 2
    assert assurance.calls == 1
    assert store.read_current() == result.current_pointer


async def test_resume_rejects_cross_epoch_drift_before_clock_or_candidate_mutation(
    tmp_path: Path,
) -> None:
    clock = _FakeMonotonicClock()
    epoch_authority = _FakeMonotonicEpochAuthority()
    request, coordinator, planner, runtime, assurance, store, checkpoint_store = _harness(
        tmp_path,
        monotonic_clock=clock,
        monotonic_epoch_authority=epoch_authority,
    )
    runtime.failures.append(RuntimeError("injected-runtime-crash"))

    with pytest.raises(RuntimeError, match="injected-runtime-crash"):
        await coordinator.run(request)
    checkpoint = checkpoint_store.load()
    assert checkpoint is not None
    assert checkpoint.phase is SuccessorCoordinatorPhase.EXECUTING
    prior_clock_calls = clock.calls

    epoch_authority.epoch_sha256 = _digest("next-monotonic-epoch")
    with pytest.raises(SuccessorCoordinatorError, match="monotonic epoch differs"):
        await coordinator.run(request)

    assert clock.calls == prior_clock_calls
    assert planner.calls == 1
    assert runtime.calls == 1
    assert assurance.calls == 0
    assert store.read_current() is None


async def test_resume_rejects_missing_durable_planning_generation_before_runtime(
    tmp_path: Path,
) -> None:
    request, coordinator, planner, runtime, assurance, store, checkpoint_store = _harness(tmp_path)
    runtime.failures.append(RuntimeError("injected-runtime-crash"))

    with pytest.raises(RuntimeError, match="injected-runtime-crash"):
        await coordinator.run(request)
    checkpoint = checkpoint_store.load()
    assert checkpoint is not None
    assert checkpoint.phase is SuccessorCoordinatorPhase.EXECUTING
    prior_runtime_calls = runtime.calls
    planner.verify_error = FileNotFoundError("planning generation missing")

    with pytest.raises(
        SuccessorCoordinatorError,
        match="durable planning generation could not be reverified",
    ):
        await coordinator.run(request)

    assert planner.calls == 1
    assert planner.verify_calls == 2
    assert runtime.calls == prior_runtime_calls
    assert assurance.calls == 0
    assert store.read_current() is None


async def test_resume_rejects_relabeling_admission_to_current_foreign_epoch(
    tmp_path: Path,
) -> None:
    clock = _FakeMonotonicClock()
    epoch_authority = _FakeMonotonicEpochAuthority()
    request, coordinator, planner, runtime, assurance, store, checkpoint_store = _harness(
        tmp_path,
        monotonic_clock=clock,
        monotonic_epoch_authority=epoch_authority,
    )
    runtime.failures.append(RuntimeError("injected-runtime-crash"))
    with pytest.raises(RuntimeError, match="injected-runtime-crash"):
        await coordinator.run(request)

    foreign_epoch = _digest("next-monotonic-epoch")
    epoch_authority.epoch_sha256 = foreign_epoch
    drifted_request = replace(
        request,
        candidate_admission=replace(
            request.candidate_admission,
            monotonic_epoch_sha256=foreign_epoch,
        ),
    )
    prior_clock_calls = clock.calls
    prior_epoch_calls = epoch_authority.calls
    with pytest.raises(SuccessorCoordinatorError, match="resume admission differs"):
        await coordinator.run(drifted_request)

    assert clock.calls == prior_clock_calls
    assert epoch_authority.calls == prior_epoch_calls
    assert planner.calls == 1
    assert runtime.calls == 1
    assert assurance.calls == 0
    assert checkpoint_store.load() is not None
    assert store.read_current() is None


async def test_initial_epoch_mismatch_fails_before_clock_planning_or_checkpoint(
    tmp_path: Path,
) -> None:
    clock = _FakeMonotonicClock()
    epoch_authority = _FakeMonotonicEpochAuthority(_digest("foreign-monotonic-epoch"))
    request, coordinator, planner, runtime, assurance, store, checkpoint_store = _harness(
        tmp_path,
        monotonic_clock=clock,
        monotonic_epoch_authority=epoch_authority,
    )

    with pytest.raises(SuccessorCoordinatorError, match="monotonic epoch differs"):
        await coordinator.run(request)

    assert clock.calls == 0
    assert planner.calls == runtime.calls == assurance.calls == 0
    assert checkpoint_store.load() is None
    assert store.read_current() is None


async def test_resume_hours_later_rejects_expired_headroom_before_candidate_mutation(
    tmp_path: Path,
) -> None:
    clock = _FakeMonotonicClock()
    request, coordinator, planner, runtime, assurance, store, checkpoint_store = _harness(
        tmp_path,
        monotonic_clock=clock,
    )
    runtime.failures.append(RuntimeError("injected-runtime-crash"))

    with pytest.raises(RuntimeError, match="injected-runtime-crash"):
        await coordinator.run(request)
    checkpoint = checkpoint_store.load()
    assert checkpoint is not None
    assert checkpoint.phase is SuccessorCoordinatorPhase.EXECUTING
    assert runtime.calls == 1

    clock.now = 995.0
    with pytest.raises(SuccessorCoordinatorError, match="deadline headroom is insufficient"):
        await coordinator.run(request)

    assert planner.calls == 1
    assert runtime.calls == 1
    assert assurance.calls == 0
    assert store.read_current() is None


async def test_initial_expired_headroom_fails_before_planning_or_checkpoint(
    tmp_path: Path,
) -> None:
    clock = _FakeMonotonicClock(now=995.0)
    request, coordinator, planner, runtime, assurance, store, checkpoint_store = _harness(
        tmp_path,
        monotonic_clock=clock,
    )

    with pytest.raises(SuccessorCoordinatorError, match="deadline headroom is insufficient"):
        await coordinator.run(request)

    assert planner.calls == runtime.calls == assurance.calls == 0
    assert checkpoint_store.load() is None
    assert store.read_current() is None


async def test_pre_provider_headroom_is_rechecked_immediately_before_planning(
    tmp_path: Path,
) -> None:
    clock = _SequenceMonotonicClock([979.0, 981.0])
    request, coordinator, planner, runtime, assurance, store, checkpoint_store = _harness(
        tmp_path,
        monotonic_clock=clock,
    )

    with pytest.raises(SuccessorCoordinatorError, match="deadline headroom is insufficient"):
        await coordinator.run(request)

    checkpoint = checkpoint_store.load()
    assert checkpoint is not None
    assert checkpoint.phase is SuccessorCoordinatorPhase.REQUESTED
    assert clock.calls == 2
    assert planner.calls == runtime.calls == assurance.calls == 0
    assert store.read_current() is None


async def test_each_store_admission_receives_a_fresh_monotonic_measurement(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    clock = _SequenceMonotonicClock([100.0, 110.0, 120.0, 130.0, 140.0, 150.0])
    request, coordinator, _planner, _runtime, _assurance, store, _checkpoint_store = _harness(
        tmp_path,
        monotonic_clock=clock,
    )
    observed_store_now: list[float] = []
    original_prepare = store.prepare_candidate_from_baseline

    def recording_prepare(*args: Any, **kwargs: Any) -> Path:
        observed_store_now.append(kwargs["monotonic_now_seconds"])
        return original_prepare(*args, **kwargs)

    monkeypatch.setattr(store, "prepare_candidate_from_baseline", recording_prepare)

    await coordinator.run(request)

    assert clock.calls == 6
    assert observed_store_now == [120.0, 130.0]


async def test_resume_rejects_immutable_candidate_admission_drift(
    tmp_path: Path,
) -> None:
    request, coordinator, planner, runtime, assurance, store, checkpoint_store = _harness(tmp_path)
    runtime.failures.append(RuntimeError("injected-runtime-crash"))
    with pytest.raises(RuntimeError, match="injected-runtime-crash"):
        await coordinator.run(request)

    drifted_request = replace(
        request,
        candidate_admission=replace(
            request.candidate_admission,
            aggregate_capacity=replace(
                request.candidate_admission.aggregate_capacity,
                candidate_max_bytes=(
                    request.candidate_admission.aggregate_capacity.candidate_max_bytes + 1
                ),
            ),
        ),
    )
    with pytest.raises(SuccessorCoordinatorError, match="resume admission differs"):
        await coordinator.run(drifted_request)

    checkpoint = checkpoint_store.load()
    assert checkpoint is not None
    assert checkpoint.candidate_admission == request.candidate_admission
    assert planner.calls == 1
    assert runtime.calls == 1
    assert assurance.calls == 0
    assert store.read_current() is None


async def test_resume_rejects_baseline_identity_drift(tmp_path: Path) -> None:
    request, coordinator, planner, runtime, assurance, store, checkpoint_store = _harness(tmp_path)
    runtime.failures.append(RuntimeError("injected-runtime-crash"))
    with pytest.raises(RuntimeError, match="injected-runtime-crash"):
        await coordinator.run(request)

    drifted_baseline = replace(
        request.baseline,
        remote_dataset_version=request.baseline.remote_dataset_version + 1,
    )
    drifted_request = replace(
        request,
        baseline=drifted_baseline,
        planning_request=replace(
            request.planning_request,
            baseline_identity_sha256=drifted_baseline.identity_sha256,
        ),
    )
    with pytest.raises(SuccessorCoordinatorError, match="resume baseline differs"):
        await coordinator.run(drifted_request)

    assert planner.calls == 1
    assert runtime.calls == 1
    assert assurance.calls == 0
    assert checkpoint_store.load() is not None
    assert store.read_current() is None


async def test_resume_rejects_baseline_tree_drift(tmp_path: Path) -> None:
    request, coordinator, planner, runtime, assurance, store, checkpoint_store = _harness(tmp_path)
    runtime.failures.append(RuntimeError("injected-runtime-crash"))
    with pytest.raises(RuntimeError, match="injected-runtime-crash"):
        await coordinator.run(request)

    (request.baseline_public_root / "nba.duckdb").write_bytes(b"mutated-baseline")
    with pytest.raises(
        SuccessorCoordinatorError,
        match="resume baseline installed public tree differs",
    ):
        await coordinator.run(request)

    assert planner.calls == 1
    assert runtime.calls == 1
    assert assurance.calls == 0
    assert checkpoint_store.load() is not None
    assert store.read_current() is None


async def test_resume_rejects_intent_drift(tmp_path: Path) -> None:
    request, coordinator, planner, runtime, assurance, store, checkpoint_store = _harness(tmp_path)
    runtime.failures.append(RuntimeError("injected-runtime-crash"))
    with pytest.raises(RuntimeError, match="injected-runtime-crash"):
        await coordinator.run(request)

    checkpoint = checkpoint_store.load()
    assert checkpoint is not None
    assert checkpoint.transaction is not None
    assert checkpoint.intent is not None
    candidate_root = store.candidate_path(checkpoint.transaction)
    stored = store.load_transaction(candidate_root)
    drifted = SuccessorUpdateTransaction.candidate(
        generation=stored.generation,
        baseline=stored.baseline,
        intent=replace(stored.intent, as_of_utc="2026-08-14T00:00:00Z"),
    )
    _write_canonical_document(candidate_root / SUCCESSOR_TRANSACTION_NAME, drifted.to_dict())

    with pytest.raises(SuccessorCoordinatorError, match="resume intent differs"):
        await coordinator.run(request)

    assert planner.calls == 1
    assert runtime.calls == 1
    assert assurance.calls == 0
    assert store.read_current() is None


async def test_resume_rejects_receipt_inventory_drift(tmp_path: Path) -> None:
    request, coordinator, planner, runtime, assurance, store, checkpoint_store = _harness(tmp_path)
    assurance.failure = RuntimeError("injected-assurance-crash")
    with pytest.raises(RuntimeError, match="injected-assurance-crash"):
        await coordinator.run(request)

    checkpoint = checkpoint_store.load()
    assert checkpoint is not None
    assert checkpoint.phase is SuccessorCoordinatorPhase.ASSURING
    assert checkpoint.transaction is not None
    candidate_root = store.candidate_path(checkpoint.transaction)
    stored = store.load_transaction(candidate_root)
    assert stored.build is not None
    drifted_receipts = tuple(
        replace(
            receipt,
            persisted_content_sha256=_digest(f"drifted-receipt:{receipt.requested_scope_sha256}"),
        )
        for receipt in stored.build.observed_delta_receipts
    )
    drifted = SuccessorUpdateTransaction.candidate(
        generation=stored.generation,
        baseline=stored.baseline,
        intent=stored.intent,
    ).mark_built(observed_delta_receipts=drifted_receipts)
    _write_canonical_document(candidate_root / SUCCESSOR_TRANSACTION_NAME, drifted.to_dict())
    assurance.failure = None

    with pytest.raises(SuccessorCoordinatorError, match="resume receipt inventory differs"):
        await coordinator.run(request)

    assert planner.calls == 1
    assert runtime.calls == 1
    assert assurance.calls == 1
    assert store.read_current() is None


async def test_resume_rejects_current_pointer_drift(tmp_path: Path) -> None:
    request, coordinator, planner, runtime, assurance, store, checkpoint_store = _harness(tmp_path)
    runtime.failures.append(RuntimeError("injected-runtime-crash"))
    with pytest.raises(RuntimeError, match="injected-runtime-crash"):
        await coordinator.run(request)

    _write_canonical_document(
        store.root / CURRENT_SUCCESSOR_GENERATION_NAME,
        {
            "schema_version": 2,
            "current": {
                "generation": 1,
                "candidate_name": "generation-00000001-" + ("ab" * 8),
                "transaction_sha256": _digest("foreign-current-transaction"),
                "assurance_sha256": _digest("foreign-current-assurance"),
                "data_tree_fingerprint": _digest("foreign-current-tree"),
                "installed_public_tree_sha256": _digest("foreign-current-installed"),
                "private_generation_receipt_sha256": _digest("foreign-current-private"),
            },
            "previous": None,
        },
    )
    with pytest.raises(SuccessorCoordinatorError, match="resume current pointer differs"):
        await coordinator.run(request)

    assert planner.calls == 1
    assert runtime.calls == 1
    assert assurance.calls == 0
    assert checkpoint_store.load() is not None
    assert store.pointer_path.name == CURRENT_SUCCESSOR_GENERATION_NAME


class _PauseBeforePromoted(SuccessorCoordinatorCheckpointStore):
    block = True

    def write(self, checkpoint: Any) -> None:
        if self.block and checkpoint.phase is SuccessorCoordinatorPhase.PROMOTED:
            raise RuntimeError("injected-before-promoted")
        super().write(checkpoint)


async def test_resume_rejects_current_pointer_identity_drift_after_promotion(
    tmp_path: Path,
) -> None:
    checkpoint_store = _PauseBeforePromoted(tmp_path / "coordinator-checkpoint.json")
    request, coordinator, planner, runtime, assurance, store, _store = _harness(
        tmp_path,
        checkpoint_store=checkpoint_store,
    )
    with pytest.raises(RuntimeError, match="injected-before-promoted"):
        await coordinator.run(request)

    checkpoint = checkpoint_store.load()
    pointer = store.read_current()
    assert checkpoint is not None
    assert pointer is not None
    assert checkpoint.phase is SuccessorCoordinatorPhase.TRANSACTION_PROMOTED

    tampered = copy.deepcopy(pointer)
    tampered["current"]["transaction_sha256"] = _digest("foreign-promoted-pointer")
    _write_canonical_document(store.pointer_path, tampered)
    checkpoint_store.block = False

    with pytest.raises(SuccessorCoordinatorError, match="resume current pointer differs"):
        await coordinator.run(request)

    assert planner.calls == 1
    assert runtime.calls == 1
    assert assurance.calls == 1
    with pytest.raises(SuccessorGenerationStoreError):
        store.read_current()


async def test_resume_preserves_exact_promoted_transaction_and_current_pointer(
    tmp_path: Path,
) -> None:
    checkpoint_store = _PauseBeforePromoted(tmp_path / "coordinator-checkpoint.json")
    request, coordinator, planner, runtime, assurance, store, _store = _harness(
        tmp_path,
        checkpoint_store=checkpoint_store,
        candidate_max_bytes=64_000_000,
    )
    with pytest.raises(RuntimeError, match="injected-before-promoted"):
        await coordinator.run(request)

    pointer = store.read_current()
    checkpoint = checkpoint_store.load()
    assert checkpoint is not None
    assert pointer is not None
    assert checkpoint.phase is SuccessorCoordinatorPhase.TRANSACTION_PROMOTED
    checkpoint_store.block = False

    result = await coordinator.run(request)

    assert result.checkpoint.phase is SuccessorCoordinatorPhase.PROMOTED
    assert result.transaction.to_dict() == checkpoint.transaction.to_dict()
    assert result.current_pointer == pointer
    assert store.read_current() == pointer
    assert planner.calls == 1
    assert runtime.calls == 1
    assert assurance.calls == 1


async def test_checkpoint_decoder_rejects_same_count_foreign_private_root(
    tmp_path: Path,
) -> None:
    checkpoint_store = _PauseBeforeAssuring(tmp_path / "coordinator-checkpoint.json")
    request, coordinator, _planner, _runtime, _assurance, _store, _checkpoint_store = _harness(
        tmp_path,
        checkpoint_store=checkpoint_store,
    )
    with pytest.raises(RuntimeError, match="injected-before-assurance"):
        await coordinator.run(request)
    checkpoint = checkpoint_store.load()
    assert checkpoint is not None
    payload = json.loads(checkpoint.canonical_bytes)
    private = payload["update_private_generation"]
    assert isinstance(private, dict)
    roots = private["done_call_receipt_sha256s"]
    assert isinstance(roots, list)
    roots[0] = _digest("foreign-logical-call-root")
    roots.sort()
    private["done_call_receipts_sha256"] = canonical_sha256(roots)

    with pytest.raises(SuccessorCoordinatorError, match="logical-call roots differ"):
        SuccessorCoordinatorCheckpoint.from_dict(payload)


async def test_checkpoint_rejects_plan_intent_build_and_receipt_binding_drift(
    tmp_path: Path,
) -> None:
    checkpoint_store = _PauseBeforeAssuring(tmp_path / "coordinator-checkpoint.json")
    request, coordinator, _planner, _runtime, _assurance, _store, _checkpoint_store = _harness(
        tmp_path,
        checkpoint_store=checkpoint_store,
    )
    with pytest.raises(RuntimeError, match="injected-before-assurance"):
        await coordinator.run(request)
    checkpoint = checkpoint_store.load()
    assert checkpoint is not None
    assert checkpoint.phase is SuccessorCoordinatorPhase.BUILT
    original = json.loads(checkpoint.canonical_bytes)
    foreign = _digest("foreign-checkpoint-binding")

    checkpoint_only = copy.deepcopy(original)
    checkpoint_only["planned_route_replacement_bindings_sha256"] = foreign
    with pytest.raises(SuccessorCoordinatorError, match="authority differs"):
        SuccessorCoordinatorCheckpoint.from_dict(checkpoint_only)

    plan = copy.deepcopy(original)
    plan["planning_evidence"]["planned_route_replacement_bindings_sha256"] = foreign
    with pytest.raises(SuccessorCoordinatorError, match="checkpoint is invalid"):
        SuccessorCoordinatorCheckpoint.from_dict(plan)

    intent = copy.deepcopy(original)
    intent["intent"]["planned_route_replacement_bindings_sha256"] = foreign
    with pytest.raises(SuccessorCoordinatorError, match="checkpoint finalized intent differs"):
        SuccessorCoordinatorCheckpoint.from_dict(intent)

    build = copy.deepcopy(original)
    build["transaction"]["build"]["planned_route_replacement_bindings_sha256"] = foreign
    with pytest.raises(SuccessorCoordinatorError, match="checkpoint is invalid"):
        SuccessorCoordinatorCheckpoint.from_dict(build)

    receipts = copy.deepcopy(original)
    for receipt in receipts["observed_delta_receipts"]:
        receipt["execution_dispatch_identity_sha256"] = foreign
    with pytest.raises(SuccessorCoordinatorError, match="checkpoint is invalid"):
        SuccessorCoordinatorCheckpoint.from_dict(receipts)


async def test_assurance_input_rejects_foreign_route_binding_before_builder_effects(
    tmp_path: Path,
) -> None:
    checkpoint_store = _PauseBeforeAssuring(tmp_path / "coordinator-checkpoint.json")
    request, coordinator, _planner, _runtime, assurance, store, _checkpoint_store = _harness(
        tmp_path,
        checkpoint_store=checkpoint_store,
    )
    with pytest.raises(RuntimeError, match="injected-before-assurance"):
        await coordinator.run(request)
    checkpoint = checkpoint_store.load()
    assert checkpoint is not None
    assert checkpoint.transaction is not None
    assert checkpoint.planning_evidence is not None
    assert checkpoint.update_private_generation is not None
    assert checkpoint.candidate_installed_public_tree_sha256 is not None

    with pytest.raises(SuccessorCoordinatorError, match="assurance planned route"):
        SuccessorAssuranceBuildInput(
            candidate_root=store.candidate_path(checkpoint.transaction),
            baseline=checkpoint.baseline,
            planning_evidence=checkpoint.planning_evidence,
            execution_plan=checkpoint.planning_evidence.execution_plan,
            planned_route_replacement_bindings_sha256=_digest("foreign-assurance-input"),
            transaction=checkpoint.transaction,
            update_private_generation=checkpoint.update_private_generation,
            transform_outputs=checkpoint.transform_outputs,
            execution_installed_public_tree_sha256=(
                checkpoint.candidate_installed_public_tree_sha256
            ),
        )
    assert assurance.calls == 0


@pytest.mark.parametrize(
    "failure",
    [
        PipelineResult(failed_extractions=1),
        PipelineResult(failed_loads=1),
        PipelineResult(errors=["incomplete"]),
    ],
)
async def test_incomplete_result_never_promotes(
    tmp_path: Path,
    failure: PipelineResult,
) -> None:
    request, coordinator, _planner, runtime, _assurance, store, checkpoint_store = _harness(
        tmp_path
    )
    runtime.pipeline_result = failure

    with pytest.raises(SuccessorCoordinatorError, match="pipeline result is incomplete"):
        await coordinator.run(request)
    checkpoint = checkpoint_store.load()
    assert checkpoint is not None
    assert checkpoint.phase is SuccessorCoordinatorPhase.EXECUTING
    assert store.read_current() is None
    _assert_downstream_publication_blocked(coordinator, store, checkpoint_store)


def _assert_downstream_publication_blocked(
    coordinator: SuccessorCoordinator,
    store: SuccessorGenerationStore,
    checkpoint_store: SuccessorCoordinatorCheckpointStore,
) -> None:
    with pytest.raises(
        SuccessorCoordinatorError,
        match="blocks scan, export, and upload",
    ):
        require_successor_downstream_publication(
            checkpoint=checkpoint_store.load(),
            current_pointer=store.read_current(),
        )
    with pytest.raises(
        SuccessorCoordinatorError,
        match="blocks scan, export, and upload",
    ):
        coordinator.require_downstream_publication()
    assert store.read_current() is None


async def test_cancellation_never_promotes(tmp_path: Path) -> None:
    request, coordinator, planner, runtime, assurance, store, checkpoint_store = _harness(tmp_path)
    runtime.failures.append(asyncio.CancelledError())

    with pytest.raises(asyncio.CancelledError):
        await coordinator.run(request)
    checkpoint = checkpoint_store.load()
    assert checkpoint is not None
    assert checkpoint.phase is SuccessorCoordinatorPhase.EXECUTING
    assert planner.calls == 1
    assert runtime.calls == 1
    assert assurance.calls == 0
    _assert_downstream_publication_blocked(coordinator, store, checkpoint_store)


async def test_keyboard_interrupt_never_promotes(tmp_path: Path) -> None:
    request, coordinator, planner, runtime, assurance, store, checkpoint_store = _harness(tmp_path)
    runtime.failures.append(KeyboardInterrupt())

    with pytest.raises(KeyboardInterrupt):
        await coordinator.run(request)
    checkpoint = checkpoint_store.load()
    assert checkpoint is not None
    assert checkpoint.phase is SuccessorCoordinatorPhase.EXECUTING
    assert planner.calls == 1
    assert runtime.calls == 1
    assert assurance.calls == 0
    _assert_downstream_publication_blocked(coordinator, store, checkpoint_store)


async def test_planning_cancellation_blocks_scan_export_upload(tmp_path: Path) -> None:
    request, coordinator, planner, runtime, assurance, store, checkpoint_store = _harness(tmp_path)
    planner.failure = asyncio.CancelledError()

    with pytest.raises(asyncio.CancelledError):
        await coordinator.run(request)
    checkpoint = checkpoint_store.load()
    assert checkpoint is not None
    assert checkpoint.phase is SuccessorCoordinatorPhase.REQUESTED
    assert planner.calls == 1
    assert runtime.calls == 0
    assert assurance.calls == 0
    _assert_downstream_publication_blocked(coordinator, store, checkpoint_store)


async def test_assurance_cancellation_blocks_scan_export_upload(tmp_path: Path) -> None:
    request, coordinator, planner, runtime, assurance, store, checkpoint_store = _harness(tmp_path)
    assurance.failure = asyncio.CancelledError()

    with pytest.raises(asyncio.CancelledError):
        await coordinator.run(request)
    checkpoint = checkpoint_store.load()
    assert checkpoint is not None
    assert checkpoint.phase is SuccessorCoordinatorPhase.ASSURING
    assert planner.calls == 1
    assert runtime.calls == 1
    assert assurance.calls == 1
    _assert_downstream_publication_blocked(coordinator, store, checkpoint_store)


def test_missing_checkpoint_blocks_scan_export_upload(tmp_path: Path) -> None:
    _request, coordinator, _planner, _runtime, _assurance, store, checkpoint_store = _harness(
        tmp_path
    )
    assert checkpoint_store.load() is None
    _assert_downstream_publication_blocked(coordinator, store, checkpoint_store)


async def test_capture_output_and_assurance_drift_fail_closed(tmp_path: Path) -> None:
    request, coordinator, _planner, runtime, assurance, store, _checkpoint_store = _harness(
        tmp_path
    )
    runtime.private = _private(
        request.baseline,
        runtime.intent,
        runtime.receipts,
        provider_authority_sha256=_digest("foreign-provider"),
    )
    with pytest.raises(SuccessorCoordinatorError, match="provider_authority_sha256"):
        await coordinator.run(request)
    assert store.read_current() is None

    request2, coordinator2, _planner2, runtime2, _assurance2, store2, _store2 = _harness(
        tmp_path / "outputs"
    )
    runtime2.transforms = runtime2.transforms[:-1]
    with pytest.raises(SuccessorCoordinatorError, match="transform output inventory"):
        await coordinator2.run(request2)
    assert store2.read_current() is None

    request3, coordinator3, _planner3, _runtime3, assurance3, store3, _store3 = _harness(
        tmp_path / "assurance"
    )
    assurance3.public_digest_override = _digest("foreign-public")
    with pytest.raises(SuccessorCoordinatorError, match="installed public tree differs"):
        await coordinator3.run(request3)
    assert store3.read_current() is None


async def test_resume_rejects_request_and_safe_candidate_drift(tmp_path: Path) -> None:
    checkpoint_store = _PauseBeforeAssuring(tmp_path / "coordinator-checkpoint.json")
    request, coordinator, _planner, _runtime, _assurance, store, _store = _harness(
        tmp_path,
        checkpoint_store=checkpoint_store,
    )
    with pytest.raises(RuntimeError, match="injected-before-assurance"):
        await coordinator.run(request)
    checkpoint = checkpoint_store.load()
    assert checkpoint is not None
    assert checkpoint.phase is SuccessorCoordinatorPhase.BUILT

    changed_request = replace(request, generation=2)
    with pytest.raises(SuccessorCoordinatorError, match="resume request differs"):
        await coordinator.run(changed_request)

    assert checkpoint.transaction is not None
    candidate = store.candidate_path(checkpoint.transaction)
    (candidate / "public" / "foreign-byte").write_bytes(b"drift")
    checkpoint_store.block = False
    with pytest.raises(Exception, match="installed public tree differs from resume authority"):
        await coordinator.run(request)
    assert store.read_current() is None


def test_checkpoint_store_rejects_noncanonical_and_symlink_state(tmp_path: Path) -> None:
    store = SuccessorCoordinatorCheckpointStore(tmp_path / "checkpoint.json")
    (tmp_path / "checkpoint.json").write_text('{"not":"canonical"}')
    with pytest.raises(SuccessorCoordinatorError):
        store.load()

    (tmp_path / "checkpoint.json").unlink()
    target = tmp_path / "target.json"
    target.write_text("{}\n")
    (tmp_path / "checkpoint.json").symlink_to(target)
    with pytest.raises(SuccessorCoordinatorError, match="opened safely"):
        store.load()


class _PauseBeforeExecuting(SuccessorCoordinatorCheckpointStore):
    block = True

    def write(self, checkpoint: Any) -> None:
        if self.block and checkpoint.phase is SuccessorCoordinatorPhase.EXECUTING:
            raise RuntimeError("injected-before-executing")
        super().write(checkpoint)


async def test_resume_rejects_durable_state_ahead_of_checkpoint_phase(
    tmp_path: Path,
) -> None:
    checkpoint_store = _PauseBeforeExecuting(tmp_path / "coordinator-checkpoint.json")
    request, coordinator, planner, runtime, assurance, store, persisted = _harness(
        tmp_path,
        checkpoint_store=checkpoint_store,
    )
    with pytest.raises(RuntimeError, match="injected-before-executing"):
        await coordinator.run(request)

    checkpoint = persisted.load()
    assert checkpoint is not None
    assert checkpoint.phase is SuccessorCoordinatorPhase.CANDIDATE
    assert checkpoint.transaction is not None
    assert checkpoint.transaction.state is SuccessorGenerationState.CANDIDATE
    reloaded = SuccessorCoordinatorCheckpointStore(persisted.path).load()
    assert reloaded == checkpoint

    candidate_root = store.candidate_path(checkpoint.transaction)
    built = checkpoint.transaction.mark_built(observed_delta_receipts=runtime.receipts)
    store.record_transaction(candidate_root, built)
    assert store.load_transaction(candidate_root).state is SuccessorGenerationState.BUILT

    resumed = _fresh_coordinator(planner, runtime, assurance, store, persisted)
    with pytest.raises(
        SuccessorCoordinatorError,
        match="durable transaction or admission is ahead of or differs from the restored phase",
    ):
        await resumed.run(request)

    assert planner.calls == 1
    assert planner.verify_calls == 1
    assert runtime.calls == 0
    assert assurance.calls == 0
    assert persisted.load() == checkpoint
    assert store.read_current() is None


async def test_resume_rejects_durable_admission_that_differs_from_restored_phase(
    tmp_path: Path,
) -> None:
    request, coordinator, planner, runtime, assurance, store, checkpoint_store = _harness(tmp_path)
    runtime.failures.append(RuntimeError("injected-runtime-crash"))
    with pytest.raises(RuntimeError, match="injected-runtime-crash"):
        await coordinator.run(request)

    checkpoint = checkpoint_store.load()
    assert checkpoint is not None
    assert checkpoint.phase is SuccessorCoordinatorPhase.EXECUTING
    assert checkpoint.transaction is not None
    candidate_root = store.candidate_path(checkpoint.transaction)
    admission_path = candidate_root / SUCCESSOR_CANDIDATE_BASELINE_NAME
    admission = json.loads(admission_path.read_bytes())
    admission["baseline_identity_sha256"] = _digest("foreign-durable-admission")
    _write_canonical_document(admission_path, admission)
    persisted = SuccessorCoordinatorCheckpointStore(checkpoint_store.path).load()
    assert persisted == checkpoint

    resumed = _fresh_coordinator(planner, runtime, assurance, store, checkpoint_store)
    with pytest.raises(
        SuccessorCoordinatorError,
        match="durable transaction or admission is ahead of or differs from the restored phase",
    ):
        await resumed.run(request)

    assert planner.calls == 1
    assert planner.verify_calls == 1
    assert runtime.calls == 1
    assert assurance.calls == 0
    assert checkpoint_store.load() == checkpoint
    assert store.read_current() is None


async def test_resume_rejects_stale_checkpoint_after_persist_reload_when_durable_state_is_ahead(
    tmp_path: Path,
) -> None:
    checkpoint_store = _PauseBeforeExecuting(tmp_path / "coordinator-checkpoint.json")
    request, coordinator, planner, runtime, assurance, store, persisted = _harness(
        tmp_path,
        checkpoint_store=checkpoint_store,
    )
    with pytest.raises(RuntimeError, match="injected-before-executing"):
        await coordinator.run(request)

    checkpoint = persisted.load()
    assert checkpoint is not None
    assert checkpoint.phase is SuccessorCoordinatorPhase.CANDIDATE
    assert checkpoint.transaction is not None
    stale = SuccessorCoordinatorCheckpoint(
        phase=SuccessorCoordinatorPhase.REQUESTED,
        baseline=checkpoint.baseline,
        planning_request=checkpoint.planning_request,
        generation=checkpoint.generation,
        candidate_admission=checkpoint.candidate_admission,
    )
    persisted.path.write_bytes(stale.canonical_bytes)
    reloaded = SuccessorCoordinatorCheckpointStore(persisted.path).load()
    assert reloaded == stale
    assert store.candidate_path(checkpoint.transaction).is_dir()

    resumed = _fresh_coordinator(planner, runtime, assurance, store, persisted)
    with pytest.raises(
        SuccessorCoordinatorError,
        match="durable transaction or admission is ahead of or differs from the restored phase",
    ):
        await resumed.run(request)

    assert planner.calls == 1
    assert planner.verify_calls == 1
    assert runtime.calls == 0
    assert assurance.calls == 0
    assert persisted.load() == stale
    assert store.read_current() is None


async def test_store_backed_resume_restores_sealed_planning_generation_and_manifest(
    tmp_path: Path,
) -> None:
    request, coordinator, planner, runtime, checkpoint_store, store_root = _store_backed_harness(
        tmp_path
    )
    runtime.failures.append(RuntimeError("injected-runtime-crash"))

    with pytest.raises(RuntimeError, match="injected-runtime-crash"):
        await coordinator.run(request)
    checkpoint = checkpoint_store.load()
    assert checkpoint is not None
    assert checkpoint.phase is SuccessorCoordinatorPhase.EXECUTING
    assert planner.calls == 1
    assert planner.verify_calls == 1
    assert runtime.execution_plans == [planner.evidence.execution_plan]
    assert runtime.calls == 1

    result = await coordinator.run(request)

    assert result.checkpoint.phase is SuccessorCoordinatorPhase.PROMOTED
    assert planner.calls == 1
    assert planner.verify_calls == 2
    assert runtime.calls == 2
    assert runtime.execution_plans == [
        planner.evidence.execution_plan,
        planner.evidence.execution_plan,
    ]
    assert result.checkpoint.planning_evidence is not None
    assert result.checkpoint.planning_evidence.to_dict() == planner.evidence.to_dict()
    assert store_root.is_dir()


async def test_store_backed_resume_rejects_planning_generation_byte_drift_before_runtime(
    tmp_path: Path,
) -> None:
    request, coordinator, planner, runtime, checkpoint_store, store_root = _store_backed_harness(
        tmp_path
    )
    runtime.failures.append(RuntimeError("injected-runtime-crash"))

    with pytest.raises(RuntimeError, match="injected-runtime-crash"):
        await coordinator.run(request)
    prior_runtime_calls = runtime.calls
    checkpoint = checkpoint_store.load()
    assert checkpoint is not None
    assert checkpoint.phase is SuccessorCoordinatorPhase.EXECUTING

    mutated = 0
    for path in store_root.rglob("*"):
        if path.is_file() and path.stat().st_size > 0:
            path.chmod(0o600)
            path.write_bytes(path.read_bytes() + b"x")
            mutated += 1
            break
    assert mutated == 1

    with pytest.raises(
        SuccessorCoordinatorError,
        match="durable planning generation could not be reverified",
    ):
        await coordinator.run(request)

    assert planner.calls == 1
    assert planner.verify_calls == 2
    assert runtime.calls == prior_runtime_calls
    assert checkpoint_store.load() == checkpoint
