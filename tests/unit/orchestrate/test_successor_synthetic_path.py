from __future__ import annotations

from dataclasses import replace
from typing import TYPE_CHECKING

import pytest

from nbadb.orchestrate.orchestrator import PipelineResult
from nbadb.orchestrate.successor_composition import (
    ExactSuccessorComposition,
    build_exact_successor_composition,
)
from nbadb.orchestrate.successor_coordinator import (
    SuccessorCoordinatorPhase,
    _logical_call_bindings_sha256,
)
from nbadb.orchestrate.successor_crash_injection import DurablePlanningStep
from nbadb.orchestrate.successor_inventory import measure_installed_public_tree
from nbadb.orchestrate.successor_planner import (
    ConcreteSuccessorPlanningExecutor,
    deterministic_planning_generation_id,
)
from nbadb.orchestrate.successor_planning_driver import RequestDrivenSuccessorPlanningDriver
from nbadb.orchestrate.successor_planning_generation_contract import PlanningDispatchPhase
from nbadb.orchestrate.successor_planning_store import PlanningGenerationPhase
from nbadb.orchestrate.successor_publication_inventory import _CONTROL_RESOURCES
from nbadb.orchestrate.successor_update_contract import (
    SUCCESSOR_LIVE_UPDATE_ROOT_ENDPOINTS,
    DeltaDisposition,
    ObservedDeltaReceipt,
    UpdateScopeClosureEvidenceKind,
    require_live_and_scoreboard_update_delta_closure,
)
from tests.unit.orchestrate.test_successor_composition import (
    _config,
    _layout,
    _restore_budget,
    _restore_request,
)
from tests.unit.orchestrate.test_successor_coordinator import (
    _private,
    _transforms,
    _write_real_four_format_public_tree,
)
from tests.unit.orchestrate.test_successor_crash_injection import _install_once_crash
from tests.unit.orchestrate.test_successor_planning_driver import _Resolver, _SemanticRuntime

if TYPE_CHECKING:
    from pathlib import Path

    from nbadb.orchestrate.capture_session import PrivateGenerationIdentity
    from nbadb.orchestrate.successor_coordinator import SuccessorCoordinatorRequest
    from nbadb.orchestrate.successor_execution_plan import SuccessorExecutionPlan
    from nbadb.orchestrate.successor_planning_generation_contract import (
        PlanningGenerationManifest,
    )
    from nbadb.orchestrate.successor_update_contract import SuccessorUpdateTransaction

_NO_CHANGE_ENDPOINT = "common_all_players"
_LIVE_GAME_ID = "0022500001"


def _synthetic_request(public_root: Path) -> SuccessorCoordinatorRequest:
    request = _restore_request(public_root)
    return replace(
        request,
        candidate_admission=replace(
            request.candidate_admission,
            aggregate_capacity=replace(
                request.candidate_admission.aggregate_capacity,
                coordinator_checkpoint_max_bytes=64 * 1024 * 1024,
            ),
        ),
    )


def _install_planner(composition: ExactSuccessorComposition) -> dict[str, int]:
    executor = composition.coordinator._planning_executor
    assert type(executor) is ConcreteSuccessorPlanningExecutor
    inner = RequestDrivenSuccessorPlanningDriver(_SemanticRuntime(live_game_ids=(_LIVE_GAME_ID,)))
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

    executor._driver = _CountedDriver()  # type: ignore[method-assign]
    executor._private_generation_resolver = _Resolver()
    return driver_calls


def _receipts_from_plan(
    transaction: SuccessorUpdateTransaction,
    plan: SuccessorExecutionPlan,
) -> tuple[ObservedDeltaReceipt, ...]:
    from tests.unit.orchestrate.test_successor_coordinator import _digest

    receipts: list[ObservedDeltaReceipt] = []
    for dispatch in plan.dispatches:
        logical_root = _digest(f"logical:{dispatch.identity_sha256}")
        for scope in dispatch.requested_scopes:
            live = scope.endpoint_name in SUCCESSOR_LIVE_UPDATE_ROOT_ENDPOINTS
            no_change = (not live) and scope.endpoint_name == _NO_CHANGE_ENDPOINT
            prior = _digest(f"prior:{scope.identity_sha256}")
            persisted = prior if no_change else _digest(f"persisted:{scope.identity_sha256}")
            replacement = _digest(f"replacement:{scope.identity_sha256}")
            receipts.append(
                ObservedDeltaReceipt(
                    baseline_identity_sha256=transaction.baseline.identity_sha256,
                    update_intent_sha256=transaction.intent.identity_sha256,
                    source_sha=transaction.intent.source_sha,
                    requested_scope_sha256=scope.identity_sha256,
                    execution_dispatch_identity_sha256=dispatch.identity_sha256,
                    planning_dependency_identity_sha256s=(dispatch.dependency_identity_sha256s),
                    disposition=DeltaDisposition.OBSERVED,
                    logical_call_receipt_sha256=logical_root,
                    prior_persisted_content_sha256=prior,
                    source_scope_replacement_sha256=replacement,
                    persisted_content_sha256=persisted,
                    persisted_schema_sha256=_digest(f"schema:{scope.identity_sha256}"),
                    persisted_row_count=1,
                )
            )
    return tuple(receipts)


def _materialize_changed_public_tree(public_root: Path, *, as_of_utc: str) -> str:
    for path in public_root.rglob("*"):
        if not path.is_file():
            continue
        relative = path.relative_to(public_root).as_posix()
        if relative in _CONTROL_RESOURCES:
            continue
        if relative in {"nba.duckdb", "nba.sqlite"} or relative.startswith(("csv/", "parquet/")):
            continue
        path.unlink()
    _write_real_four_format_public_tree(public_root, as_of_utc=as_of_utc)
    return measure_installed_public_tree(public_root).installed_public_tree_sha256


class _PlanAwareRuntime:
    def __init__(
        self,
        owner: _PlanAwareRuntimeFactory,
        transaction: SuccessorUpdateTransaction,
        candidate_root: Path,
        execution_plan: SuccessorExecutionPlan,
    ) -> None:
        self.owner = owner
        self.transaction = transaction
        self.candidate_root = candidate_root
        self.execution_plan = execution_plan

    @property
    def planned_route_replacement_bindings_sha256(self) -> str:
        return self.execution_plan.planned_route_replacement_bindings_sha256

    @property
    def successor_delta_receipts(self) -> tuple[ObservedDeltaReceipt, ...]:
        assert self.owner.receipts is not None
        return self.owner.receipts

    @property
    def capture_identity(self) -> PrivateGenerationIdentity:
        assert self.owner.private is not None
        return self.owner.private

    @property
    def transform_output_attestations(self) -> object:
        assert self.owner.transforms is not None
        return self.owner.transforms

    async def run_daily(self) -> PipelineResult:
        return await self._run()

    async def run_monthly(self) -> PipelineResult:
        return await self._run()

    def restore_same_generation_execution(self) -> None:
        self.owner.restore_calls += 1

    async def _run(self) -> PipelineResult:
        self.owner.calls += 1
        if self.owner.receipts is None:
            self.owner.receipt_builds += 1
            self.owner.receipts = _receipts_from_plan(self.transaction, self.execution_plan)
            self.owner.private = _private(
                self.transaction.baseline,
                self.transaction.intent,
                self.owner.receipts,
            )
            self.owner.transforms = _transforms()
            if self.owner.crash_after_receipts:
                self.owner.crash_after_receipts = False
                raise RuntimeError("injected-update-execution-crash")
        if self.owner.public_tree_sha256 is None:
            self.owner.public_tree_sha256 = _materialize_changed_public_tree(
                self.candidate_root / "public",
                as_of_utc=self.transaction.intent.as_of_utc,
            )
        else:
            self.owner.replay_calls += 1
            current = measure_installed_public_tree(
                self.candidate_root / "public"
            ).installed_public_tree_sha256
            if current != self.owner.public_tree_sha256:
                raise AssertionError("no-change replay drifted the public tree identity")
        return PipelineResult()


class _PlanAwareRuntimeFactory:
    def __init__(self) -> None:
        self.calls = 0
        self.restore_calls = 0
        self.receipt_builds = 0
        self.replay_calls = 0
        self.crash_after_receipts = False
        self.receipts: tuple[ObservedDeltaReceipt, ...] | None = None
        self.private: PrivateGenerationIdentity | None = None
        self.transforms: object | None = None
        self.public_tree_sha256: str | None = None
        self.execution_plans: list[SuccessorExecutionPlan] = []

    def __call__(
        self,
        transaction: SuccessorUpdateTransaction,
        candidate_root: Path,
        execution_plan: SuccessorExecutionPlan,
    ) -> _PlanAwareRuntime:
        self.execution_plans.append(execution_plan)
        return _PlanAwareRuntime(self, transaction, candidate_root, execution_plan)


def _wire(
    composition: ExactSuccessorComposition,
    runtime_factory: _PlanAwareRuntimeFactory,
) -> dict[str, int]:
    driver_calls = _install_planner(composition)
    composition.coordinator._runtime_factory = runtime_factory  # type: ignore[method-assign]
    return driver_calls


def _assert_two_wave_live_box_plan(
    plan: SuccessorExecutionPlan,
    manifest: PlanningGenerationManifest,
) -> None:
    sealed = manifest.sealed_dispatches
    wave_0 = {
        dispatch.endpoint_name
        for dispatch in sealed
        if dispatch.phase is PlanningDispatchPhase.PLANNING_WAVE_0
    }
    wave_1 = {
        dispatch.endpoint_name
        for dispatch in sealed
        if dispatch.phase is PlanningDispatchPhase.PLANNING_WAVE_1
    }
    update = {
        dispatch.endpoint_name
        for dispatch in sealed
        if dispatch.phase is PlanningDispatchPhase.UPDATE
    }
    assert {"league_game_log", "live_score_board"} <= wave_0
    assert {"cume_stats_player_games", "cume_stats_team_games"} <= wave_1
    assert "live_box_score" in update
    box = tuple(
        dispatch for dispatch in plan.dispatches if dispatch.endpoint_name == "live_box_score"
    )
    assert len(box) == 1
    assert box[0].parameters["game_id"] == _LIVE_GAME_ID
    assert len(box[0].staging_route_ids) == 7
    assert len(box[0].requested_scopes) == 7
    assert len({route for dispatch in plan.dispatches for route in dispatch.staging_route_ids}) == (
        370
    )


def _assert_changed_live_box_receipts(
    plan: SuccessorExecutionPlan,
    receipts: tuple[ObservedDeltaReceipt, ...],
) -> None:
    box = next(
        dispatch for dispatch in plan.dispatches if dispatch.endpoint_name == "live_box_score"
    )
    box_receipts = tuple(
        receipt
        for receipt in receipts
        if receipt.execution_dispatch_identity_sha256 == box.identity_sha256
    )
    assert len(box_receipts) == 7
    assert len({receipt.logical_call_receipt_sha256 for receipt in box_receipts}) == 1
    assert all(
        receipt.prior_persisted_content_sha256 != receipt.persisted_content_sha256
        and receipt.source_scope_replacement_sha256 != receipt.logical_call_receipt_sha256
        for receipt in box_receipts
    )
    no_change = tuple(
        receipt
        for receipt, scope in (
            (
                receipt,
                next(
                    scope
                    for dispatch in plan.dispatches
                    for scope in dispatch.requested_scopes
                    if scope.identity_sha256 == receipt.requested_scope_sha256
                ),
            )
            for receipt in receipts
        )
        if scope.endpoint_name == _NO_CHANGE_ENDPOINT
    )
    assert no_change
    assert all(
        receipt.prior_persisted_content_sha256 == receipt.persisted_content_sha256
        for receipt in no_change
    )


async def test_synthetic_assured_baseline_two_wave_update_replay_and_crash_resume(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    paths = _layout(tmp_path)
    request = _synthetic_request(paths["baseline_public"])
    config = replace(
        _config(paths),
        fresh_planning_budget=lambda: _restore_budget(request),
    )
    runtime_factory = _PlanAwareRuntimeFactory()
    runtime_factory.crash_after_receipts = True
    _install_once_crash(monkeypatch, DurablePlanningStep.DISPATCH_SEAL)

    composition = build_exact_successor_composition(request=request, config=config)
    first_driver = _wire(composition, runtime_factory)
    with pytest.raises(RuntimeError, match="injected-crash-after-dispatch_seal"):
        await composition.run()

    planning_store = composition.coordinator._planning_executor._store
    crashed_planning = planning_store.load_and_verify(
        request.planning_request,
        deterministic_planning_generation_id(request.planning_request),
        budget=_restore_budget(request),
    )
    assert crashed_planning.phase is PlanningGenerationPhase.WAVE_1_COMMITTED
    assert first_driver["derive_wave"] > 0
    assert first_driver["execute_call"] > 0
    assert first_driver["seal_wave"] == 2
    assert first_driver["derive_manifest"] == 1
    assert runtime_factory.calls == 0
    requested = composition.topology.checkpoint_store.load()
    assert requested is not None
    assert requested.phase is SuccessorCoordinatorPhase.REQUESTED

    resumed = build_exact_successor_composition(request=request, config=config)
    second_driver = _wire(resumed, runtime_factory)
    with pytest.raises(RuntimeError, match="injected-update-execution-crash"):
        await resumed.run()

    executing = resumed.topology.checkpoint_store.load()
    assert executing is not None
    assert executing.phase is SuccessorCoordinatorPhase.EXECUTING
    assert executing.planning_evidence is not None
    assert executing.transaction is not None
    manifest = executing.planning_evidence.planning_generation_manifest
    plan = executing.planning_evidence.execution_plan
    transaction = executing.transaction
    plan.validate_against_manifest(manifest)
    _assert_two_wave_live_box_plan(plan, manifest)
    assert second_driver == {
        "derive_wave": 0,
        "execute_call": 0,
        "seal_wave": 0,
        "derive_manifest": 1,
    }
    assert runtime_factory.receipt_builds == 1
    assert runtime_factory.public_tree_sha256 is None
    assert runtime_factory.execution_plans == [plan]
    assert runtime_factory.receipts is not None

    candidate_root = resumed.topology.generation_store.candidate_path(transaction)
    runtime = runtime_factory(transaction, candidate_root, plan)
    completed = await runtime.run_daily()
    replayed = await runtime.run_daily()

    assert completed.failed_extractions == 0
    assert replayed.failed_extractions == 0
    assert runtime_factory.receipt_builds == 1
    assert runtime_factory.replay_calls == 1
    receipts = runtime.successor_delta_receipts
    _assert_changed_live_box_receipts(plan, receipts)
    require_live_and_scoreboard_update_delta_closure(
        transaction.intent.requested_scopes,
        observed_delta_receipts=receipts,
        evidence_kind=UpdateScopeClosureEvidenceKind.OBSERVED_DELTA_REPLACEMENT,
        sealed_live_game_ids=(_LIVE_GAME_ID,),
    )
    built = transaction.mark_built(observed_delta_receipts=receipts)
    assert built.build is not None
    assert {item.requested_scope_sha256 for item in built.build.observed_delta_receipts} == {
        item.requested_scope_sha256 for item in receipts
    }
    assert built.build.planned_route_replacement_bindings_sha256 == (
        plan.planned_route_replacement_bindings_sha256
    )
    assert (
        _logical_call_bindings_sha256(
            baseline=transaction.baseline,
            intent=transaction.intent,
            receipts=receipts,
        )
        == runtime.capture_identity.done_call_bindings_sha256
    )
    assert (
        runtime_factory.public_tree_sha256
        == measure_installed_public_tree(candidate_root / "public").installed_public_tree_sha256
    )
