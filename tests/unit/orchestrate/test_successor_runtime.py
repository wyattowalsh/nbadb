from __future__ import annotations

import asyncio
import os
from dataclasses import replace
from typing import TYPE_CHECKING, cast
from unittest.mock import MagicMock, patch

import duckdb
import pytest

from nbadb.contracts.staging_route_contract import staging_route_contract_bundle
from nbadb.core.config import NbaDbSettings
from nbadb.core.nba_api_provenance import expected_nba_api_provider_authority
from nbadb.extract.bronze import (
    PARSER_INPUT_REPRESENTATION,
    BronzeLimits,
    LogicalCallReceiptBinding,
    ParserInputContext,
    ResultSetReceipt,
    canonical_parameters_sha256,
    parent_occurrence_states_digest,
)
from nbadb.extract.registry import EndpointRegistry
from nbadb.orchestrate import successor_runtime as successor_runtime_module
from nbadb.orchestrate.capture_session import (
    CaptureRunScope,
    CaptureSessionState,
    PrivateCaptureSession,
    PrivateGenerationIdentity,
)
from nbadb.orchestrate.orchestrator import (
    Orchestrator,
    PipelineResult,
    SuccessorExecutionOutcome,
    TransformOutputAttestation,
)
from nbadb.orchestrate.orchestrator import (
    validate_successor_runtime_plan as _real_validate_successor_runtime_plan,
)
from nbadb.orchestrate.successor_execution_plan import (
    SealedUpdateExecutionDispatch,
    SuccessorExecutionPlan,
)
from nbadb.orchestrate.successor_inventory import measure_installed_public_tree
from nbadb.orchestrate.successor_planning_contract import finalize_successor_update_intent
from nbadb.orchestrate.successor_planning_generation_contract import (
    PlanningDispatchPhase,
    SealedProviderDispatch,
)
from nbadb.orchestrate.successor_runtime import (
    ExactPlanRuntimePipelineResult,
    ExactPlanRuntimeTerminalReceipt,
    ExactPlanRuntimeTerminalReceiptStore,
    ExactPlanSuccessorRuntime,
    ExactPlanSuccessorRuntimeFactory,
    _classified_live_transform_tables,
    _measure_public_stable_non_live_identity,
    _stable_non_live_identity,
)
from nbadb.orchestrate.successor_transform_authority import _attest_exact_tables
from nbadb.orchestrate.successor_update_contract import (
    CallMutability,
    DeltaDisposition,
    ObservedDeltaReceipt,
    RequestedRouteScope,
    SuccessorUpdateContractError,
    SuccessorUpdateIntent,
    SuccessorUpdateTransaction,
    canonical_json_bytes,
    canonical_sha256,
)
from nbadb.orchestrate.transformers import expected_transform_output_tables
from tests.unit.orchestrate.test_successor_coordinator import (
    _SOURCE_SHA,
    _baseline,
    _digest,
    _planning,
    _private,
    _receipts,
)

_EXPECTED_TRANSFORM_OUTPUT_COUNT = len(expected_transform_output_tables(include_live=True))

if TYPE_CHECKING:
    from pathlib import Path

    from nbadb.extract.nba_api_adapter import NbaApiCaptureContract


@pytest.fixture(autouse=True)
def _stub_current_staging_preflight(monkeypatch: pytest.MonkeyPatch) -> MagicMock:
    """Synthetic coordinator routes are not members of the production staging map."""

    validator = MagicMock(return_value=())
    monkeypatch.setattr(
        "nbadb.orchestrate.successor_runtime.validate_successor_runtime_plan",
        validator,
    )
    return validator


def test_terminal_pipeline_result_uses_schema_backed_transform_count(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "nbadb.orchestrate.transformers.expected_transform_output_tables",
        lambda *, include_live: frozenset({"fact_a", "fact_b", "fact_c"}),
    )
    complete = ExactPlanRuntimePipelineResult(
        tables_updated=3,
        rows_total=0,
        duration_seconds=0.0,
        failed_extractions=0,
        failed_loads=0,
        skipped_extractions=0,
        errors=(),
    )

    assert complete.tables_updated == 3
    with pytest.raises(SuccessorUpdateContractError, match="pipeline result is incomplete"):
        replace(complete, tables_updated=2)


def _harness(tmp_path: Path):
    public_root = (tmp_path / "candidate" / "public").resolve()
    public_root.mkdir(parents=True)
    (public_root / "nba.duckdb").write_bytes(b"checkpointed-public-database")
    (public_root / "nba.sqlite").write_bytes(b"checkpointed-public-sqlite")
    (public_root / "csv").mkdir()
    (public_root / "parquet").mkdir()
    baseline = replace(
        _baseline(public_root),
        provider_authority_sha256=expected_nba_api_provider_authority()["authority_sha256"],
    )
    planning = _planning(baseline)
    intent = finalize_successor_update_intent(planning)
    transaction = SuccessorUpdateTransaction.candidate(
        generation=238,
        baseline=baseline,
        intent=intent,
    )
    receipts = _receipts(baseline, planning)
    transforms = tuple(
        TransformOutputAttestation(
            table_name=table,
            row_count=0 if table == "agg_all_time_leaders" else 1,
            schema_sha256=_digest(f"schema:{table}"),
            content_sha256=_digest(f"content:{table}"),
        )
        for table in sorted(expected_transform_output_tables(include_live=True))
    )
    outcome = SuccessorExecutionOutcome(
        result=PipelineResult(
            tables_updated=_EXPECTED_TRANSFORM_OUTPUT_COUNT,
            rows_total=_EXPECTED_TRANSFORM_OUTPUT_COUNT - 1,
            duration_seconds=12.5,
            skipped_extractions=1,
        ),
        delta_receipts=receipts,
        transform_output_attestations=transforms,
        planned_route_replacement_bindings_sha256=(
            planning.execution_plan.planned_route_replacement_bindings_sha256
        ),
    )
    scope = CaptureRunScope(
        semantic_source_sha=_SOURCE_SHA,
        chain_id=baseline.chain_id,
        lane_id=transaction.generation_identity_sha256,
        workflow_run_id=123,
        workflow_run_attempt=1,
    )
    terminal = ExactPlanRuntimeTerminalReceipt.build(
        transaction=transaction,
        execution_plan=planning.execution_plan,
        capture_scope=scope,
        outcome=outcome,
        installed_public_tree_sha256=measure_installed_public_tree(
            public_root
        ).installed_public_tree_sha256,
    )
    identity = replace(
        _private(baseline, intent, receipts),
        chain_id=scope.chain_id,
        lane_id=scope.lane_id,
    )
    terminal_path = (tmp_path / "private" / "terminal" / "receipt.json").resolve()
    terminal_path.parent.mkdir(mode=0o700, parents=True)
    terminal_parent = terminal_path.parent.stat()
    store = ExactPlanRuntimeTerminalReceiptStore(
        terminal_path,
        forbidden_roots=(public_root, (tmp_path / "capture").resolve()),
        expected_parent_identity=(terminal_parent.st_dev, terminal_parent.st_ino),
        maximum_bytes=16 * 1024 * 1024,
    )
    return {
        "public_root": public_root,
        "transaction": transaction,
        "plan": planning.execution_plan,
        "outcome": outcome,
        "scope": scope,
        "terminal": terminal,
        "identity": identity,
        "terminal_path": terminal_path,
        "store": store,
    }


def _runtime(harness: dict[str, object], capture_session: object) -> ExactPlanSuccessorRuntime:
    public_root = cast("Path", harness["public_root"])
    candidate_root = public_root.parent
    candidate_stat = candidate_root.stat()
    public_stat = public_root.stat()
    scratch_root = (candidate_root.parent / "runtime-transform-scratch").resolve()
    scratch_root.mkdir(mode=0o700)
    scratch_root.chmod(0o700)
    scratch_stat = scratch_root.stat()
    registry = _registry_for_plan(cast("SuccessorExecutionPlan", harness["plan"]))
    return ExactPlanSuccessorRuntime(
        transaction=harness["transaction"],  # type: ignore[arg-type]
        execution_plan=harness["plan"],  # type: ignore[arg-type]
        candidate_root=candidate_root,
        candidate_public_root=public_root,
        expected_candidate_root_identity=(candidate_stat.st_dev, candidate_stat.st_ino),
        expected_candidate_public_identity=(public_stat.st_dev, public_stat.st_ino),
        candidate_max_bytes=16 * 1024 * 1024,
        registry=registry,
        registry_authority=registry.capture_authority(),
        transform_scratch_parent=scratch_root,
        expected_transform_scratch_identity=(scratch_stat.st_dev, scratch_stat.st_ino),
        transform_scratch_max_bytes=16 * 1024 * 1024,
        settings=NbaDbSettings(data_dir=public_root),
        capture_session=capture_session,  # type: ignore[arg-type]
        capture_scope=harness["scope"],  # type: ignore[arg-type]
        terminal_store=harness["store"],  # type: ignore[arg-type]
        estimated_checkpoint_bytes=4096,
        monotonic_deadline_seconds=1000.0,
        monotonic_clock=lambda: 100.0,
    )


def _factory(
    tmp_path: Path,
    harness: dict[str, object],
    *,
    scope_template: CaptureRunScope | None = None,
    terminal_receipt_max_bytes: int = 16 * 1024 * 1024,
    runtime_log_max_bytes: int = 16 * 1024 * 1024,
    candidate_max_bytes: int = 16 * 1024 * 1024,
) -> ExactPlanSuccessorRuntimeFactory:
    public_root = cast("Path", harness["public_root"])
    scope = cast("CaptureRunScope", harness["scope"])
    capture_base = (tmp_path / "factory-private" / "capture").resolve()
    terminal_base = (tmp_path / "factory-private" / "terminal").resolve()
    log_root = (tmp_path / "factory-private" / "logs").resolve()
    scratch_root = (tmp_path / "factory-private" / "transform-scratch").resolve()
    for path in (capture_base, terminal_base, log_root, scratch_root):
        path.mkdir(mode=0o700, parents=True)
        path.chmod(0o700)
    capture_stat = capture_base.stat()
    terminal_stat = terminal_base.stat()
    log_stat = log_root.stat()
    scratch_stat = scratch_root.stat()
    registry = _registry_for_plan(cast("SuccessorExecutionPlan", harness["plan"]))
    return ExactPlanSuccessorRuntimeFactory(
        base_settings=NbaDbSettings(data_dir=public_root),
        capture_scope_template=(scope_template or replace(scope, lane_id="capture-lane-template")),
        capture_limits=BronzeLimits(
            max_response_bytes=100_000,
            max_generation_stored_bytes=2_000_000,
            minimum_free_bytes=1,
            max_checkpoint_bytes=1_000_000,
            minimum_deadline_headroom_seconds=10.0,
        ),
        capture_base_root=capture_base,
        expected_capture_base_identity=(capture_stat.st_dev, capture_stat.st_ino),
        terminal_receipt_base_root=terminal_base,
        expected_terminal_receipt_base_identity=(terminal_stat.st_dev, terminal_stat.st_ino),
        log_dir=log_root,
        expected_log_root_identity=(log_stat.st_dev, log_stat.st_ino),
        registry=registry,
        registry_authority=registry.capture_authority(),
        transform_scratch_parent=scratch_root,
        expected_transform_scratch_identity=(scratch_stat.st_dev, scratch_stat.st_ino),
        transform_scratch_max_bytes=16 * 1024 * 1024,
        terminal_receipt_max_bytes=terminal_receipt_max_bytes,
        runtime_log_max_bytes=runtime_log_max_bytes,
        candidate_max_bytes=candidate_max_bytes,
        estimated_checkpoint_bytes=4096,
        monotonic_deadline_seconds=1000.0,
        monotonic_clock=lambda: 100.0,
    )


def _registry_for_plan(plan: SuccessorExecutionPlan) -> EndpointRegistry:
    registry = EndpointRegistry()
    for endpoint_name in sorted({dispatch.endpoint_name for dispatch in plan.dispatches}):
        extractor = type(
            f"Synthetic{endpoint_name.title().replace('_', '')}",
            (),
            {"endpoint_name": endpoint_name},
        )
        registry.register(extractor)  # type: ignore[arg-type]
    return registry


def _complete_logical_call(
    session: PrivateCaptureSession,
    *,
    endpoint_name: str = "league_game_log",
    params: dict[str, object] | None = None,
    context_override: ParserInputContext | None = None,
) -> tuple[LogicalCallReceiptBinding, NbaApiCaptureContract]:
    logical_params = params or {"season": "2025-26", "season_type": "Regular Season"}
    contract = session.contract_for(endpoint_name, logical_params)
    contract = contract.for_endpoint_contract("b" * 64)
    if context_override is not None:
        contract = replace(contract, context=context_override)

    request_context = contract.begin_request()
    captured = contract.sink.store_parser_input(
        '{"resultSets":[{"name":"LeagueGameLog","headers":[],"rowSet":[]}]}',
        representation=PARSER_INPUT_REPRESENTATION,
    )
    attempt_receipt = contract.sink.record_response_attempt(
        context=request_context,
        transport_kind="http_response",
        source_family="stats",
        endpoint_id="LeagueGameLog",
        endpoint_slug="leaguegamelog",
        parameters=logical_params,
        provider_authority_sha256=contract.provider_authority_sha256,
        contract_sha256=contract.endpoint_contract_sha256,
        status_code=200,
        captured=captured,
        outcome="success_empty",
        failure_class=None,
        root_exception_class=None,
        result_sets=(
            ResultSetReceipt(
                name="LeagueGameLog",
                provider_index=0,
                canonical_index=0,
                headers_sha256="c" * 64,
                row_count=0,
                json_path=None,
                container_kind="nba_api_result_set",
                container_count=1,
                missing_count=0,
                null_count=0,
                parent_observation_count=1,
                parent_occurrence_states_sha256=parent_occurrence_states_digest(("present",)),
                observed_field_orders_sha256="d" * 64,
                normalized_output_sha256="e" * 64,
            ),
        ),
    )
    contract.record_receipt(request_context, attempt_receipt, successful=True)
    snapshot = contract.receipt_snapshot()
    route = f"{endpoint_name}:stg_{endpoint_name}:0"
    logical_root = contract.sink.record_logical_call(
        context=contract.context,
        logical_endpoint_id=endpoint_name,
        logical_parameters=logical_params,
        provider_authority_sha256=contract.provider_authority_sha256,
        response_receipt_sha256s=snapshot.receipt_sha256s,
        successful_response_ordinals=snapshot.successful_response_ordinals,
        result_route_ids=(route,),
    )
    return (
        LogicalCallReceiptBinding(
            logical_call_receipt_sha256=logical_root,
            endpoint_name=endpoint_name,
            logical_parameters_sha256=canonical_parameters_sha256(logical_params),
            provider_authority_sha256=contract.provider_authority_sha256,
            result_route_ids=(route,),
        ),
        contract,
    )


def _multi_route_harness(harness: dict[str, object]) -> dict[str, object]:
    transaction = cast("SuccessorUpdateTransaction", harness["transaction"])
    original_plan = cast("SuccessorExecutionPlan", harness["plan"])
    bundle = staging_route_contract_bundle()
    route_ids = (
        "schedule:stg_schedule_weeks:1",
        "schedule:stg_schedule:0",
    )
    parameters = {"season": "2025-26"}
    scopes = tuple(
        RequestedRouteScope.from_parameters(
            endpoint_name="schedule",
            route_id=route_id,
            route_contract_sha256=bundle.by_route_id[route_id].contract_sha256,
            parameters=parameters,
            mutability=CallMutability.MUTABLE,
        )
        for route_id in route_ids
    )
    dispatch = SealedUpdateExecutionDispatch(
        order=0,
        sealed_dispatch=SealedProviderDispatch.from_parameters(
            phase=PlanningDispatchPhase.UPDATE,
            endpoint_name="schedule",
            requested_scope_identity_sha256s=tuple(scope.identity_sha256 for scope in scopes),
            parameters=parameters,
            pattern="season",
            staging_route_ids=route_ids,
            dependency_identity_sha256s=(_digest("schedule-planning-dependency"),),
        ),
        requested_scopes=scopes,
    )
    sorted_scopes = tuple(sorted(scopes, key=lambda scope: scope.identity_sha256))
    plan = replace(
        original_plan,
        requested_route_scopes_sha256=canonical_sha256(
            [scope.to_dict() for scope in sorted_scopes]
        ),
        dispatches=(dispatch,),
    )
    intent = SuccessorUpdateIntent(
        baseline_identity_sha256=transaction.baseline.identity_sha256,
        planning_generation_manifest_sha256=(
            transaction.intent.planning_generation_manifest_sha256
        ),
        successor_execution_plan_sha256=plan.identity_sha256,
        planned_route_replacement_bindings_sha256=(plan.planned_route_replacement_bindings_sha256),
        mode=transaction.intent.mode,
        source_sha=transaction.intent.source_sha,
        cutoff_utc=transaction.intent.cutoff_utc,
        as_of_utc=transaction.intent.as_of_utc,
        requested_scopes=scopes,
    )
    multi_transaction = SuccessorUpdateTransaction.candidate(
        generation=transaction.generation,
        baseline=transaction.baseline,
        intent=intent,
    )
    logical_root = _digest("one-schedule-logical-call")
    receipts = tuple(
        ObservedDeltaReceipt(
            baseline_identity_sha256=transaction.baseline.identity_sha256,
            update_intent_sha256=intent.identity_sha256,
            source_sha=intent.source_sha,
            requested_scope_sha256=scope.identity_sha256,
            execution_dispatch_identity_sha256=dispatch.identity_sha256,
            planning_dependency_identity_sha256s=(dispatch.dependency_identity_sha256s),
            disposition=DeltaDisposition.OBSERVED,
            logical_call_receipt_sha256=logical_root,
            prior_persisted_content_sha256=_digest(f"prior:{scope.route_id}"),
            source_scope_replacement_sha256=_digest(f"replacement:{scope.route_id}"),
            persisted_content_sha256=_digest(f"persisted:{scope.route_id}"),
            persisted_schema_sha256=_digest(f"schema:{scope.route_id}"),
            persisted_row_count=1,
        )
        for scope in scopes
    )
    outcome = replace(
        cast("SuccessorExecutionOutcome", harness["outcome"]),
        delta_receipts=receipts,
        planned_route_replacement_bindings_sha256=(plan.planned_route_replacement_bindings_sha256),
    )
    scope = replace(
        cast("CaptureRunScope", harness["scope"]),
        lane_id=multi_transaction.generation_identity_sha256,
    )
    terminal = ExactPlanRuntimeTerminalReceipt.build(
        transaction=multi_transaction,
        execution_plan=plan,
        capture_scope=scope,
        outcome=outcome,
        installed_public_tree_sha256=measure_installed_public_tree(
            cast("Path", harness["public_root"])
        ).installed_public_tree_sha256,
    )
    identity = replace(
        _private(transaction.baseline, intent, receipts),
        chain_id=scope.chain_id,
        lane_id=scope.lane_id,
    )
    return {
        **harness,
        "transaction": multi_transaction,
        "plan": plan,
        "outcome": outcome,
        "scope": scope,
        "terminal": terminal,
        "identity": identity,
    }


def _one_league_game_log_plan(harness: dict[str, object]) -> dict[str, object]:
    original_plan = cast("SuccessorExecutionPlan", harness["plan"])
    original_transaction = cast("SuccessorUpdateTransaction", harness["transaction"])
    bundle = staging_route_contract_bundle()
    route_id = "league_game_log:stg_league_game_log:0"
    parameters: dict[str, object] = {
        "season": "2025-26",
        "season_type": "Regular Season",
    }
    requested_scope = RequestedRouteScope.from_parameters(
        endpoint_name="league_game_log",
        route_id=route_id,
        route_contract_sha256=bundle.by_route_id[route_id].contract_sha256,
        parameters=parameters,
        mutability=CallMutability.MUTABLE,
    )
    dispatch = SealedUpdateExecutionDispatch(
        order=0,
        sealed_dispatch=SealedProviderDispatch.from_parameters(
            phase=PlanningDispatchPhase.UPDATE,
            endpoint_name="league_game_log",
            requested_scope_identity_sha256s=(requested_scope.identity_sha256,),
            parameters=parameters,
            pattern="season",
            staging_route_ids=(route_id,),
            dependency_identity_sha256s=(_digest("league-game-log-planning-dependency"),),
        ),
        requested_scopes=(requested_scope,),
    )
    plan = replace(
        original_plan,
        requested_route_scopes_sha256=canonical_sha256([requested_scope.to_dict()]),
        dispatches=(dispatch,),
    )
    original_intent = original_transaction.intent
    intent = SuccessorUpdateIntent(
        baseline_identity_sha256=original_transaction.baseline.identity_sha256,
        planning_generation_manifest_sha256=(original_intent.planning_generation_manifest_sha256),
        successor_execution_plan_sha256=plan.identity_sha256,
        planned_route_replacement_bindings_sha256=(plan.planned_route_replacement_bindings_sha256),
        mode=original_intent.mode,
        source_sha=original_intent.source_sha,
        cutoff_utc=original_intent.cutoff_utc,
        as_of_utc=original_intent.as_of_utc,
        requested_scopes=(requested_scope,),
    )
    transaction = SuccessorUpdateTransaction.candidate(
        generation=original_transaction.generation,
        baseline=original_transaction.baseline,
        intent=intent,
    )
    return {
        **harness,
        "transaction": transaction,
        "plan": plan,
        "requested_scope": requested_scope,
        "dispatch": dispatch,
        "logical_params": parameters,
    }


def test_terminal_receipt_round_trip_is_canonical_owner_only_and_immutable(
    tmp_path: Path,
) -> None:
    harness = _harness(tmp_path)
    store = harness["store"]
    terminal = harness["terminal"]
    assert isinstance(store, ExactPlanRuntimeTerminalReceiptStore)
    assert isinstance(terminal, ExactPlanRuntimeTerminalReceipt)

    store.write(terminal)
    restored = store.load()

    assert restored == terminal
    assert restored.canonical_bytes == terminal.canonical_bytes
    assert isinstance(restored.pipeline_result.errors, tuple)
    assert os.stat(harness["terminal_path"]).st_mode & 0o077 == 0  # type: ignore[arg-type]
    assert os.stat(str(harness["terminal_path"]) + ".lock").st_mode & 0o077 == 0


def test_terminal_store_pins_admitted_parent_after_path_substitution(tmp_path: Path) -> None:
    harness = _harness(tmp_path)
    store = cast("ExactPlanRuntimeTerminalReceiptStore", harness["store"])
    terminal = cast("ExactPlanRuntimeTerminalReceipt", harness["terminal"])
    terminal_path = cast("Path", harness["terminal_path"])
    parent = terminal_path.parent
    retained = parent.with_name("terminal-retained")
    parent.rename(retained)
    parent.mkdir(mode=0o700)

    store.write(terminal)

    assert list(parent.iterdir()) == []
    assert (retained / terminal_path.name).read_bytes() == terminal.canonical_bytes
    assert store.load() == terminal


def test_terminal_store_path_substitution_during_replace_never_writes_replacement(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    harness = _harness(tmp_path)
    store = cast("ExactPlanRuntimeTerminalReceiptStore", harness["store"])
    terminal = cast("ExactPlanRuntimeTerminalReceipt", harness["terminal"])
    terminal_path = cast("Path", harness["terminal_path"])
    parent = terminal_path.parent
    retained = parent.with_name("terminal-retained")
    original_replace = os.replace
    substituted = False

    def substitute_replace(*args: object, **kwargs: object) -> None:
        nonlocal substituted
        if not substituted:
            parent.rename(retained)
            parent.mkdir(mode=0o700)
            substituted = True
        original_replace(*args, **kwargs)

    monkeypatch.setattr("nbadb.orchestrate.successor_runtime.os.replace", substitute_replace)
    store.write(terminal)

    assert substituted is True
    assert list(parent.iterdir()) == []
    assert (retained / terminal_path.name).read_bytes() == terminal.canonical_bytes


def test_terminal_store_rejects_oversize_before_lock_and_preserves_receipt(
    tmp_path: Path,
) -> None:
    harness = _harness(tmp_path)
    store = cast("ExactPlanRuntimeTerminalReceiptStore", harness["store"])
    terminal = cast("ExactPlanRuntimeTerminalReceipt", harness["terminal"])
    terminal_path = cast("Path", harness["terminal_path"])
    store.write(terminal)
    original_bytes = terminal_path.read_bytes()
    original_inventory = tuple(sorted(path.name for path in terminal_path.parent.iterdir()))
    replacement = replace(
        terminal,
        pipeline_result=replace(
            terminal.pipeline_result,
            duration_seconds=terminal.pipeline_result.duration_seconds + 1.0,
        ),
    )
    store._maximum_bytes = len(replacement.canonical_bytes) - 1

    with (
        patch.object(
            store,
            "_open_lock",
            side_effect=AssertionError("oversize write must not open the lock"),
        ),
        pytest.raises(SuccessorUpdateContractError, match="maximum size"),
    ):
        store.write(replacement)

    assert terminal_path.read_bytes() == original_bytes
    assert tuple(sorted(path.name for path in terminal_path.parent.iterdir())) == (
        original_inventory
    )
    store._maximum_bytes = len(original_bytes)
    assert store.load() == terminal


def test_terminal_decoder_rejects_boolean_schema_alias(tmp_path: Path) -> None:
    terminal = _harness(tmp_path)["terminal"]
    assert isinstance(terminal, ExactPlanRuntimeTerminalReceipt)
    payload = terminal.to_dict()
    payload["schema_version"] = True

    with pytest.raises(SuccessorUpdateContractError, match="fields are invalid"):
        ExactPlanRuntimeTerminalReceipt.from_canonical_bytes(canonical_json_bytes(payload))


def test_terminal_decoder_hard_rejects_schema_v1(tmp_path: Path) -> None:
    terminal = _harness(tmp_path)["terminal"]
    assert isinstance(terminal, ExactPlanRuntimeTerminalReceipt)
    payload = terminal.to_dict()
    payload["schema_version"] = 1

    with pytest.raises(SuccessorUpdateContractError, match="fields are invalid"):
        ExactPlanRuntimeTerminalReceipt.from_canonical_bytes(canonical_json_bytes(payload))


def test_terminal_build_rejects_plan_binding_digest_drift(tmp_path: Path) -> None:
    harness = _harness(tmp_path)
    outcome = harness["outcome"]
    assert isinstance(outcome, SuccessorExecutionOutcome)

    with pytest.raises(SuccessorUpdateContractError, match="sealed execution plan"):
        ExactPlanRuntimeTerminalReceipt.build(
            transaction=harness["transaction"],  # type: ignore[arg-type]
            execution_plan=harness["plan"],  # type: ignore[arg-type]
            capture_scope=harness["scope"],  # type: ignore[arg-type]
            outcome=replace(
                outcome,
                planned_route_replacement_bindings_sha256="0" * 64,
            ),
            installed_public_tree_sha256="f" * 64,
        )


@pytest.mark.parametrize("mutation", ["missing_scope", "foreign_baseline"])
def test_terminal_build_rejects_incomplete_or_foreign_delta_authority(
    tmp_path: Path,
    mutation: str,
) -> None:
    harness = _harness(tmp_path)
    outcome = harness["outcome"]
    assert isinstance(outcome, SuccessorExecutionOutcome)
    if mutation == "missing_scope":
        receipts = outcome.delta_receipts[:-1]
    else:
        receipts = (replace(outcome.delta_receipts[0], baseline_identity_sha256="0" * 64),)
        receipts += outcome.delta_receipts[1:]

    with pytest.raises(SuccessorUpdateContractError, match="immutable transaction"):
        ExactPlanRuntimeTerminalReceipt.build(
            transaction=harness["transaction"],  # type: ignore[arg-type]
            execution_plan=harness["plan"],  # type: ignore[arg-type]
            capture_scope=harness["scope"],  # type: ignore[arg-type]
            outcome=replace(outcome, delta_receipts=receipts),
            installed_public_tree_sha256="f" * 64,
        )


def test_terminal_store_rejects_public_or_capture_overlap(tmp_path: Path) -> None:
    public = (tmp_path / "public").resolve()
    public.mkdir()
    with pytest.raises(SuccessorUpdateContractError, match="overlaps"):
        ExactPlanRuntimeTerminalReceiptStore(
            public / "receipt.json",
            forbidden_roots=(public,),
            expected_parent_identity=(public.stat().st_dev, public.stat().st_ino),
            maximum_bytes=4096,
        )


def test_terminal_store_detects_lock_inode_replacement(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    harness = _harness(tmp_path)
    store = harness["store"]
    terminal = harness["terminal"]
    terminal_path = harness["terminal_path"]
    assert isinstance(store, ExactPlanRuntimeTerminalReceiptStore)
    assert isinstance(terminal, ExactPlanRuntimeTerminalReceipt)
    store.write(terminal)
    lock_path = cast("Path", terminal_path).with_name(cast("Path", terminal_path).name + ".lock")
    replaced = False

    def replace_lock(_fd: int, _operation: int) -> None:
        nonlocal replaced
        if replaced:
            return
        replaced = True
        replacement = lock_path.with_name(lock_path.name + ".replacement")
        replacement.write_bytes(b"")
        os.chmod(replacement, 0o600)
        os.replace(replacement, lock_path)

    monkeypatch.setattr("nbadb.orchestrate.successor_runtime.fcntl.flock", replace_lock)
    with pytest.raises(SuccessorUpdateContractError, match="lock identity"):
        store.load()


def test_sealed_restore_never_constructs_orchestrator_or_mutates_public(
    tmp_path: Path,
) -> None:
    harness = _harness(tmp_path)
    store = harness["store"]
    terminal = harness["terminal"]
    identity = harness["identity"]
    assert isinstance(store, ExactPlanRuntimeTerminalReceiptStore)
    assert isinstance(terminal, ExactPlanRuntimeTerminalReceipt)
    store.write(terminal)
    capture = MagicMock()
    capture.restore_sealed_identity_if_present.return_value = identity
    capture.close.return_value = identity
    runtime = _runtime(harness, capture)

    with patch(
        "nbadb.orchestrate.successor_runtime.Orchestrator",
        side_effect=AssertionError("sealed recovery must not construct Orchestrator"),
    ):
        result = asyncio.run(runtime.run_daily())

    assert result.tables_updated == _EXPECTED_TRANSFORM_OUTPUT_COUNT
    assert runtime.capture_identity is identity
    assert runtime.successor_delta_receipts == terminal.delta_receipts
    assert len(runtime.transform_output_attestations) == _EXPECTED_TRANSFORM_OUTPUT_COUNT
    capture.admit.assert_not_called()
    capture.close.assert_called_once()


def test_max_sized_terminal_restores_one_sealed_multi_route_call(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    harness = _multi_route_harness(_harness(tmp_path))
    terminal = cast("ExactPlanRuntimeTerminalReceipt", harness["terminal"])
    store = cast("ExactPlanRuntimeTerminalReceiptStore", harness["store"])
    identity = harness["identity"]
    monkeypatch.setattr(
        "nbadb.orchestrate.successor_runtime.validate_successor_runtime_plan",
        _real_validate_successor_runtime_plan,
    )
    store._maximum_bytes = len(terminal.canonical_bytes)
    store.write(terminal)
    capture = MagicMock()
    capture.restore_sealed_identity_if_present.return_value = identity
    capture.close.return_value = identity
    runtime = _runtime(harness, capture)

    with patch(
        "nbadb.orchestrate.successor_runtime.Orchestrator",
        side_effect=AssertionError("sealed recovery must not construct Orchestrator"),
    ):
        result = asyncio.run(runtime.run_daily())

    assert result.tables_updated == _EXPECTED_TRANSFORM_OUTPUT_COUNT
    assert len(runtime.successor_delta_receipts) == 2
    assert len({receipt.logical_call_receipt_sha256 for receipt in terminal.delta_receipts}) == 1
    assert runtime.capture_identity is identity
    assert identity.done_call_count == 1  # type: ignore[union-attr]
    capture.admit.assert_not_called()
    capture.close.assert_called_once_with()


def test_sealed_restore_rejects_public_drift_without_orchestrator(tmp_path: Path) -> None:
    harness = _harness(tmp_path)
    store = harness["store"]
    terminal = harness["terminal"]
    identity = harness["identity"]
    public_root = cast("Path", harness["public_root"])
    assert isinstance(store, ExactPlanRuntimeTerminalReceiptStore)
    assert isinstance(terminal, ExactPlanRuntimeTerminalReceipt)
    store.write(terminal)
    (public_root / "nba.duckdb").write_bytes(b"drift")
    capture = MagicMock()
    capture.restore_sealed_identity_if_present.return_value = identity
    capture.close.return_value = identity
    runtime = _runtime(harness, capture)

    with (
        patch(
            "nbadb.orchestrate.successor_runtime.Orchestrator",
            side_effect=AssertionError("sealed recovery must not construct Orchestrator"),
        ),
        pytest.raises(SuccessorUpdateContractError, match="installed_public_tree_sha256"),
    ):
        asyncio.run(runtime.run_daily())

    capture.admit.assert_not_called()
    capture.close.assert_called_once()


def test_unsealed_execution_writes_terminal_before_sealing(tmp_path: Path) -> None:
    harness = _harness(tmp_path)
    capture = MagicMock()
    capture.restore_sealed_identity_if_present.return_value = None
    capture.state = CaptureSessionState.CREATED
    capture.inventory_unsealed_contexts.return_value = ()
    events: list[str] = []

    def admit(**_kwargs: object) -> None:
        capture.state = CaptureSessionState.ADMITTED
        events.append("admit")

    capture.admit.side_effect = admit
    identity = harness["identity"]
    store = harness["store"]
    assert isinstance(store, ExactPlanRuntimeTerminalReceiptStore)

    class FakeOrchestrator:
        def __init__(self, **_kwargs: object) -> None:
            events.append("orchestrator")

        async def execute_successor_plan(self, plan: object) -> SuccessorExecutionOutcome:
            assert plan is harness["plan"]
            events.append("execute")
            return harness["outcome"]  # type: ignore[return-value]

        def seal_successor_capture(self):
            store.load()
            events.append("seal")
            return identity

        def close(self) -> None:
            events.append("close")

    runtime = _runtime(harness, capture)
    with patch("nbadb.orchestrate.successor_runtime.Orchestrator", FakeOrchestrator):
        result = asyncio.run(runtime.run_daily())

    assert result.tables_updated == _EXPECTED_TRANSFORM_OUTPUT_COUNT
    assert events == ["admit", "orchestrator", "execute", "seal"]
    assert runtime.capture_identity is identity


def test_unsealed_execution_requires_all_four_publication_formats(tmp_path: Path) -> None:
    harness = _harness(tmp_path)
    public_root = cast("Path", harness["public_root"])
    (public_root / "nba.sqlite").unlink()
    capture = MagicMock()
    capture.restore_sealed_identity_if_present.return_value = None
    capture.state = CaptureSessionState.ADMITTED
    capture.inventory_unsealed_contexts.return_value = ()
    runtime = _runtime(harness, capture)

    class FakeOrchestrator:
        def __init__(self, **_kwargs: object) -> None:
            return None

        async def execute_successor_plan(self, plan: object) -> SuccessorExecutionOutcome:
            assert plan is harness["plan"]
            return harness["outcome"]  # type: ignore[return-value]

        def close(self) -> None:
            return None

    with (
        patch("nbadb.orchestrate.successor_runtime.Orchestrator", FakeOrchestrator),
        pytest.raises(
            SuccessorUpdateContractError,
            match="missing required publication formats",
        ),
    ):
        asyncio.run(runtime.run_daily())

    capture.seal.assert_not_called()


def test_unsealed_exact_plan_runtime_resume_does_not_readmit_or_widen(
    tmp_path: Path,
) -> None:
    harness = _harness(tmp_path)
    capture = MagicMock()
    capture.restore_sealed_identity_if_present.return_value = None
    capture.state = CaptureSessionState.ADMITTED
    capture.closed = False
    capture.inventory_unsealed_contexts.return_value = ()
    identity = harness["identity"]
    store = harness["store"]
    plan = harness["plan"]
    assert isinstance(store, ExactPlanRuntimeTerminalReceiptStore)
    events: list[str] = []
    executed_plans: list[object] = []

    class FakeOrchestrator:
        def __init__(self, **_kwargs: object) -> None:
            events.append("orchestrator")

        async def execute_successor_plan(self, executed_plan: object) -> SuccessorExecutionOutcome:
            executed_plans.append(executed_plan)
            assert executed_plan is plan
            events.append("execute")
            return harness["outcome"]  # type: ignore[return-value]

        def seal_successor_capture(self):
            store.load()
            events.append("seal")
            return identity

        def close(self) -> None:
            events.append("close")

    runtime = _runtime(harness, capture)
    original_plan_identity = cast("SuccessorExecutionPlan", plan).identity_sha256
    transaction = cast("SuccessorUpdateTransaction", harness["transaction"])
    original_scope_ids = tuple(
        scope.identity_sha256 for scope in transaction.intent.requested_scopes
    )
    with patch("nbadb.orchestrate.successor_runtime.Orchestrator", FakeOrchestrator):
        result = asyncio.run(runtime.run_daily())

    assert result.tables_updated == _EXPECTED_TRANSFORM_OUTPUT_COUNT
    assert events == ["orchestrator", "execute", "seal"]
    assert executed_plans == [plan]
    assert runtime._plan.identity_sha256 == original_plan_identity
    assert (
        tuple(scope.identity_sha256 for scope in runtime._transaction.intent.requested_scopes)
        == original_scope_ids
    )
    assert runtime.capture_identity is identity
    capture.admit.assert_not_called()
    capture.restore_completed_bindings.assert_not_called()


def test_no_change_replay_rejects_unclassified_public_drift(tmp_path: Path) -> None:
    harness = _harness(tmp_path)
    store = harness["store"]
    terminal = harness["terminal"]
    identity = harness["identity"]
    public_root = cast("Path", harness["public_root"])
    assert isinstance(store, ExactPlanRuntimeTerminalReceiptStore)
    assert isinstance(terminal, ExactPlanRuntimeTerminalReceipt)
    store.write(terminal)
    (public_root / "nba.duckdb").write_bytes(b"unclassified-public-drift")
    capture = MagicMock()
    capture.restore_sealed_identity_if_present.return_value = None
    capture.state = CaptureSessionState.ADMITTED
    capture.closed = False
    capture.seal.return_value = identity
    capture.close.return_value = identity
    runtime = _runtime(harness, capture)

    with (
        patch(
            "nbadb.orchestrate.successor_runtime.Orchestrator",
            side_effect=AssertionError("no-change replay must not construct Orchestrator"),
        ),
        pytest.raises(
            SuccessorUpdateContractError,
            match="unclassified public-tree drift",
        ),
    ):
        asyncio.run(runtime.run_daily())

    capture.admit.assert_not_called()
    capture.restore_completed_bindings.assert_not_called()
    capture.seal.assert_not_called()
    capture.close.assert_called_once()


def test_no_change_replay_allows_classified_live_public_drift(tmp_path: Path) -> None:
    harness = _harness(tmp_path)
    store = harness["store"]
    terminal = harness["terminal"]
    identity = harness["identity"]
    public_root = cast("Path", harness["public_root"])
    plan = harness["plan"]
    assert isinstance(store, ExactPlanRuntimeTerminalReceiptStore)
    assert isinstance(terminal, ExactPlanRuntimeTerminalReceipt)
    store.write(terminal)
    (public_root / "nba.duckdb").write_bytes(b"classified-live-public-drift")
    live = _classified_live_transform_tables()
    assert live
    expected_stable = _stable_non_live_identity(terminal.transform_output_attestations)
    live_only_drift = tuple(
        replace(item, content_sha256="a" * 64) if item.table_name in live else item
        for item in terminal.transform_output_attestations
    )
    assert _stable_non_live_identity(live_only_drift) == expected_stable
    assert expected_stable != canonical_sha256(
        [item.to_dict() for item in terminal.transform_output_attestations]
    )
    capture = MagicMock()
    capture.restore_sealed_identity_if_present.return_value = None
    capture.state = CaptureSessionState.ADMITTED
    capture.closed = False
    capture.seal.return_value = identity
    capture.close.return_value = identity
    runtime = _runtime(harness, capture)
    original_plan_identity = cast("SuccessorExecutionPlan", plan).identity_sha256

    with (
        patch(
            "nbadb.orchestrate.successor_runtime.Orchestrator",
            side_effect=AssertionError("no-change replay must not construct Orchestrator"),
        ),
        patch(
            "nbadb.orchestrate.successor_runtime._measure_public_stable_non_live_identity",
            return_value=expected_stable,
        ) as measure,
    ):
        result = asyncio.run(runtime.run_daily())

    assert result.tables_updated == _EXPECTED_TRANSFORM_OUTPUT_COUNT
    assert result == terminal.pipeline_result.to_pipeline_result()
    assert runtime.capture_identity is identity
    assert runtime.successor_delta_receipts == terminal.delta_receipts
    assert runtime._plan.identity_sha256 == original_plan_identity
    measure.assert_called_once()
    assert measure.call_args.args == (public_root / "nba.duckdb",)
    assert measure.call_args.kwargs == {
        "scratch_parent": runtime._transform_scratch_parent,
        "expected_scratch_identity": runtime._expected_transform_scratch_identity,
        "transform_scratch_max_bytes": runtime._transform_scratch_max_bytes,
    }
    capture.admit.assert_not_called()
    capture.restore_completed_bindings.assert_called_once()
    capture.seal.assert_called_once()
    capture.close.assert_called_once()


def test_no_change_replay_allows_classified_live_public_drift_with_real_duckdb_measure(
    tmp_path: Path,
) -> None:
    harness = _harness(tmp_path)
    store = harness["store"]
    original_terminal = harness["terminal"]
    identity = harness["identity"]
    public_root = cast("Path", harness["public_root"])
    plan = harness["plan"]
    assert isinstance(store, ExactPlanRuntimeTerminalReceiptStore)
    assert isinstance(original_terminal, ExactPlanRuntimeTerminalReceipt)
    duckdb_path = public_root / "nba.duckdb"
    capture = MagicMock()
    capture.restore_sealed_identity_if_present.return_value = None
    capture.state = CaptureSessionState.ADMITTED
    capture.closed = False
    capture.seal.return_value = identity
    capture.close.return_value = identity
    runtime = _runtime(harness, capture)
    original_plan_identity = cast("SuccessorExecutionPlan", plan).identity_sha256

    live = _classified_live_transform_tables()
    assert live
    all_tables = tuple(sorted(expected_transform_output_tables(include_live=True)))
    non_live = tuple(sorted(expected_transform_output_tables(include_live=False)))
    duckdb_path.unlink()
    creator = duckdb.connect(str(duckdb_path), read_only=False)
    try:
        for table in all_tables:
            creator.execute(f'CREATE TABLE "{table}" (id INTEGER)')
        creator.execute("CHECKPOINT")
    finally:
        creator.close()

    source = duckdb.connect(str(duckdb_path), read_only=True)
    try:
        source.execute("SET temp_directory = ?", [""])
        source.execute("SET max_temp_directory_size = ?", ["0B"])
        configured = source.execute(
            "SELECT current_setting('temp_directory'), current_setting('max_temp_directory_size')"
        ).fetchone()
        if configured != ("", "0 bytes"):
            raise AssertionError("public DuckDB spill could not be disabled")
        non_live_attestations = _attest_exact_tables(
            source,
            non_live,
            scratch_parent=runtime._transform_scratch_parent,
            expected_scratch_parent_identity=runtime._expected_transform_scratch_identity,
            transform_scratch_max_bytes=runtime._transform_scratch_max_bytes,
        )
    finally:
        source.close()

    original_live = tuple(
        item for item in original_terminal.transform_output_attestations if item.table_name in live
    )
    rebuilt_attestations = tuple(
        sorted(
            (*non_live_attestations, *original_live),
            key=lambda item: item.table_name,
        )
    )
    assert tuple(item.table_name for item in rebuilt_attestations) == all_tables
    outcome = replace(
        cast("SuccessorExecutionOutcome", harness["outcome"]),
        transform_output_attestations=rebuilt_attestations,
    )
    terminal = ExactPlanRuntimeTerminalReceipt.build(
        transaction=cast("SuccessorUpdateTransaction", harness["transaction"]),
        execution_plan=cast("SuccessorExecutionPlan", plan),
        capture_scope=cast("CaptureRunScope", harness["scope"]),
        outcome=outcome,
        installed_public_tree_sha256=measure_installed_public_tree(
            public_root
        ).installed_public_tree_sha256,
    )
    store.write(terminal)
    recorded_tree_sha = terminal.installed_public_tree_sha256
    expected_stable = _stable_non_live_identity(terminal.transform_output_attestations)

    live_table = sorted(live)[0]
    mutator = duckdb.connect(str(duckdb_path), read_only=False)
    try:
        mutator.execute(f'INSERT INTO "{live_table}" VALUES (1)')
        mutator.execute("CHECKPOINT")
    finally:
        mutator.close()
    mutated_tree_sha = measure_installed_public_tree(public_root).installed_public_tree_sha256
    assert mutated_tree_sha != recorded_tree_sha
    assert (
        successor_runtime_module._measure_public_stable_non_live_identity
        is _measure_public_stable_non_live_identity
    )

    with patch(
        "nbadb.orchestrate.successor_runtime.Orchestrator",
        side_effect=AssertionError("no-change replay must not construct Orchestrator"),
    ) as orchestrator_type:
        result = asyncio.run(runtime.run_daily())

    current_stable = _measure_public_stable_non_live_identity(
        duckdb_path,
        scratch_parent=runtime._transform_scratch_parent,
        expected_scratch_identity=runtime._expected_transform_scratch_identity,
        transform_scratch_max_bytes=runtime._transform_scratch_max_bytes,
    )
    assert current_stable == expected_stable
    assert (
        successor_runtime_module._measure_public_stable_non_live_identity
        is _measure_public_stable_non_live_identity
    )
    assert result.tables_updated == _EXPECTED_TRANSFORM_OUTPUT_COUNT
    assert result == terminal.pipeline_result.to_pipeline_result()
    assert runtime.capture_identity is identity
    assert runtime.successor_delta_receipts == terminal.delta_receipts
    assert runtime._plan.identity_sha256 == original_plan_identity
    orchestrator_type.assert_not_called()
    capture.admit.assert_not_called()
    capture.restore_completed_bindings.assert_called_once()
    capture.seal.assert_called_once()
    capture.close.assert_called_once()


def test_invalid_plan_fails_before_capture_restore_or_admission(tmp_path: Path) -> None:
    harness = _harness(tmp_path)
    capture = MagicMock()
    runtime = _runtime(harness, capture)
    runtime._plan = replace(runtime._plan, baseline_identity_sha256="0" * 64)

    with pytest.raises(SuccessorUpdateContractError, match="authority does not reconcile"):
        asyncio.run(runtime.run_daily())

    capture.restore_sealed_identity_if_present.assert_not_called()
    capture.admit.assert_not_called()


def test_duplicate_logical_calls_fail_before_every_runtime_side_effect(
    tmp_path: Path,
    _stub_current_staging_preflight: MagicMock,
) -> None:
    harness = _multi_route_harness(_harness(tmp_path))
    plan = cast("SuccessorExecutionPlan", harness["plan"])
    multi_route = plan.dispatches[0]
    duplicate_dispatches = tuple(
        SealedUpdateExecutionDispatch(
            order=order,
            sealed_dispatch=SealedProviderDispatch.from_parameters(
                phase=PlanningDispatchPhase.UPDATE,
                endpoint_name=multi_route.endpoint_name,
                requested_scope_identity_sha256s=(scope.identity_sha256,),
                parameters=multi_route.parameters,
                pattern=multi_route.pattern,
                staging_route_ids=(scope.route_id,),
                dependency_identity_sha256s=multi_route.dependency_identity_sha256s,
            ),
            requested_scopes=(scope,),
        )
        for order, scope in enumerate(multi_route.requested_scopes)
    )
    object.__setattr__(plan, "dispatches", duplicate_dispatches)
    capture = MagicMock()
    runtime = _runtime(harness, capture)

    with (
        patch("nbadb.orchestrate.successor_runtime.Orchestrator") as orchestrator_type,
        patch("nbadb.orchestrate.orchestrator.DBManager") as db_manager_type,
        patch("nbadb.orchestrate.orchestrator.PipelineJournal") as journal_type,
        patch("nbadb.orchestrate.orchestrator._global_registry.discover") as discover,
        pytest.raises(SuccessorUpdateContractError, match="logical provider call"),
    ):
        asyncio.run(runtime.run_daily())

    capture.restore_sealed_identity_if_present.assert_not_called()
    capture.admit.assert_not_called()
    _stub_current_staging_preflight.assert_not_called()
    orchestrator_type.assert_not_called()
    db_manager_type.assert_not_called()
    journal_type.assert_not_called()
    discover.assert_not_called()


@pytest.mark.parametrize(
    ("field_name", "value"),
    [
        ("chain_id", "foreign-chain"),
        ("lane_id", "0" * 64),
    ],
)
def test_capture_scope_is_generation_bound_before_restore_or_admission(
    tmp_path: Path,
    field_name: str,
    value: str,
) -> None:
    harness = _harness(tmp_path)
    capture = MagicMock()
    runtime = _runtime(harness, capture)
    runtime._capture_scope = replace(runtime._capture_scope, **{field_name: value})

    with pytest.raises(SuccessorUpdateContractError, match=f"capture_scope.{field_name}"):
        asyncio.run(runtime.run_daily())

    capture.restore_sealed_identity_if_present.assert_not_called()
    capture.admit.assert_not_called()


def test_factory_derives_capture_lane_from_candidate_generation(tmp_path: Path) -> None:
    harness = _harness(tmp_path)
    factory = _factory(tmp_path, harness)
    session = MagicMock()
    public_root = cast("Path", harness["public_root"])
    transaction = cast("SuccessorUpdateTransaction", harness["transaction"])

    with patch.object(
        PrivateCaptureSession,
        "create_under_authorized_base",
        return_value=session,
    ) as create_session:
        runtime = factory(
            transaction,
            public_root.parent,
            harness["plan"],  # type: ignore[arg-type]
        )

    derived_scope = create_session.call_args.kwargs["scope"]
    assert derived_scope.lane_id == transaction.generation_identity_sha256
    assert derived_scope.lane_id != "capture-lane-template"
    assert derived_scope.semantic_source_sha == transaction.intent.source_sha
    assert derived_scope.chain_id == transaction.baseline.chain_id
    assert runtime._capture_scope == derived_scope


def test_factory_reopened_created_session_restores_terminal_without_admit_or_orchestrator(
    tmp_path: Path,
) -> None:
    harness = _harness(tmp_path)
    factory = _factory(tmp_path, harness)
    terminal = cast("ExactPlanRuntimeTerminalReceipt", harness["terminal"])
    identity = harness["identity"]
    public_root = cast("Path", harness["public_root"])
    plan = cast("SuccessorExecutionPlan", harness["plan"])
    session = MagicMock()
    session.restore_sealed_identity_if_present.return_value = None
    session.state = CaptureSessionState.CREATED
    session.closed = False
    session.seal.return_value = identity
    session.close.return_value = identity

    def adopt() -> None:
        session.state = CaptureSessionState.ADMITTED

    session.adopt_unsealed_same_generation_writer.side_effect = adopt

    with patch.object(
        PrivateCaptureSession,
        "create_under_authorized_base",
        return_value=session,
    ):
        runtime = factory(
            harness["transaction"],  # type: ignore[arg-type]
            public_root.parent,
            plan,
        )

    assert runtime._capture_session is session
    assert session.state is CaptureSessionState.CREATED
    runtime._terminal_store.write(terminal)

    with patch(
        "nbadb.orchestrate.successor_runtime.Orchestrator",
        side_effect=AssertionError(
            "factory CREATED terminal restore must not construct Orchestrator"
        ),
    ):
        result = asyncio.run(runtime.run_daily())

    assert result.tables_updated == _EXPECTED_TRANSFORM_OUTPUT_COUNT
    assert result == terminal.pipeline_result.to_pipeline_result()
    assert runtime.capture_identity is identity
    assert runtime.successor_delta_receipts == terminal.delta_receipts
    assert runtime._plan.identity_sha256 == plan.identity_sha256
    session.admit.assert_not_called()
    session.adopt_unsealed_same_generation_writer.assert_called_once()
    session.restore_completed_bindings.assert_called_once()
    session.seal.assert_called_once()
    session.close.assert_called_once()


def test_factory_reopened_created_restores_real_bronze_bindings_without_orchestrator(
    tmp_path: Path,
) -> None:
    harness = _one_league_game_log_plan(_harness(tmp_path))
    factory = _factory(tmp_path, harness)
    public_root = cast("Path", harness["public_root"])
    transaction = cast("SuccessorUpdateTransaction", harness["transaction"])
    plan = cast("SuccessorExecutionPlan", harness["plan"])
    requested_scope = cast("RequestedRouteScope", harness["requested_scope"])
    dispatch = cast("SealedUpdateExecutionDispatch", harness["dispatch"])
    logical_params = cast("dict[str, object]", harness["logical_params"])
    public_digest = measure_installed_public_tree(public_root).installed_public_tree_sha256
    public_bytes = (public_root / "nba.duckdb").read_bytes()

    first = factory(transaction, public_root.parent, plan)
    first_session = first._capture_session
    assert first_session.state is CaptureSessionState.CREATED
    first_session.admit(
        estimated_checkpoint_bytes=first._estimated_checkpoint_bytes,
        monotonic_now_seconds=first._monotonic_clock(),
        monotonic_deadline_seconds=first._monotonic_deadline_seconds,
    )
    bronze_binding, _contract = _complete_logical_call(
        first_session,
        endpoint_name=requested_scope.endpoint_name,
        params=logical_params,
    )
    first_session.record_completed(bronze_binding)
    assert bronze_binding.logical_parameters_sha256 == requested_scope.scope_sha256
    assert bronze_binding.endpoint_name == requested_scope.endpoint_name
    assert bronze_binding.result_route_ids == (requested_scope.route_id,)
    assert (
        bronze_binding.provider_authority_sha256 == transaction.baseline.provider_authority_sha256
    )
    first_session.close()
    first._terminal_store.close()
    assert first_session.state is CaptureSessionState.INCOMPLETE
    assert first_session.closed

    outcome = replace(
        cast("SuccessorExecutionOutcome", harness["outcome"]),
        delta_receipts=(
            ObservedDeltaReceipt(
                baseline_identity_sha256=transaction.baseline.identity_sha256,
                update_intent_sha256=transaction.intent.identity_sha256,
                source_sha=transaction.intent.source_sha,
                requested_scope_sha256=requested_scope.identity_sha256,
                execution_dispatch_identity_sha256=dispatch.identity_sha256,
                planning_dependency_identity_sha256s=(dispatch.dependency_identity_sha256s),
                disposition=DeltaDisposition.OBSERVED,
                logical_call_receipt_sha256=bronze_binding.logical_call_receipt_sha256,
                prior_persisted_content_sha256=_digest("prior:league_game_log"),
                source_scope_replacement_sha256=_digest("replacement:league_game_log"),
                persisted_content_sha256=_digest("persisted:league_game_log"),
                persisted_schema_sha256=_digest("schema:league_game_log"),
                persisted_row_count=1,
            ),
        ),
        planned_route_replacement_bindings_sha256=(plan.planned_route_replacement_bindings_sha256),
    )
    terminal = ExactPlanRuntimeTerminalReceipt.build(
        transaction=transaction,
        execution_plan=plan,
        capture_scope=first._capture_scope,
        outcome=outcome,
        installed_public_tree_sha256=public_digest,
    )

    runtime = factory(transaction, public_root.parent, plan)
    session = runtime._capture_session
    assert session.state is CaptureSessionState.CREATED
    assert not isinstance(session, MagicMock)
    assert runtime._capture_scope == first._capture_scope
    runtime._terminal_store.write(terminal)

    with (
        patch(
            "nbadb.orchestrate.successor_runtime.Orchestrator",
            side_effect=AssertionError(
                "factory CREATED bronze restore must not construct Orchestrator"
            ),
        ),
        patch.object(session, "admit", wraps=session.admit) as admit,
        patch.object(
            session._store,
            "admit_capture",
            side_effect=AssertionError(
                "factory CREATED bronze restore must not call admit_capture"
            ),
        ),
        patch.object(
            session,
            "adopt_unsealed_same_generation_writer",
            wraps=session.adopt_unsealed_same_generation_writer,
        ) as adopt,
        patch.object(
            session,
            "restore_completed_bindings",
            wraps=session.restore_completed_bindings,
        ) as restore,
        patch.object(session, "seal", wraps=session.seal) as seal,
    ):
        result = asyncio.run(runtime.run_daily())

    assert result.tables_updated == _EXPECTED_TRANSFORM_OUTPUT_COUNT
    assert result == terminal.pipeline_result.to_pipeline_result()
    assert runtime.successor_delta_receipts == terminal.delta_receipts
    assert runtime._plan.identity_sha256 == plan.identity_sha256
    assert isinstance(runtime.capture_identity, PrivateGenerationIdentity)
    assert runtime.capture_identity.done_call_receipt_sha256s == (
        bronze_binding.logical_call_receipt_sha256,
    )
    assert runtime.capture_identity.done_call_count == 1
    restored = restore.call_args.args[0]
    assert tuple(restored) == (bronze_binding,)
    admit.assert_not_called()
    adopt.assert_called_once()
    restore.assert_called_once()
    seal.assert_called_once()
    assert session.state is CaptureSessionState.SEALED
    assert session.closed
    assert (public_root / "nba.duckdb").read_bytes() == public_bytes
    assert measure_installed_public_tree(public_root).installed_public_tree_sha256 == public_digest
    assert public_digest == terminal.installed_public_tree_sha256

    runtime._terminal_store.close()
    replay = factory(transaction, public_root.parent, plan)
    replay_session = replay._capture_session
    assert replay_session.state is CaptureSessionState.CREATED
    assert not isinstance(replay_session, MagicMock)
    with patch(
        "nbadb.orchestrate.successor_runtime.Orchestrator",
        side_effect=AssertionError(
            "no-change replay must not construct Orchestrator after factory seal"
        ),
    ) as orchestrator_type:
        replayed = asyncio.run(replay.run_daily())

    assert replayed == result
    assert replayed == terminal.pipeline_result.to_pipeline_result()
    assert replay.successor_delta_receipts == terminal.delta_receipts
    assert replay._plan.identity_sha256 == plan.identity_sha256
    assert isinstance(replay.capture_identity, PrivateGenerationIdentity)
    assert replay.capture_identity.done_call_receipt_sha256s == (
        bronze_binding.logical_call_receipt_sha256,
    )
    orchestrator_type.assert_not_called()
    assert replay_session.state is CaptureSessionState.SEALED
    assert replay_session.closed
    assert (public_root / "nba.duckdb").read_bytes() == public_bytes
    assert measure_installed_public_tree(public_root).installed_public_tree_sha256 == public_digest


def test_factory_reopens_exact_candidate_root_and_journal_progress(
    tmp_path: Path,
) -> None:
    from tests.unit.orchestrate.test_successor_execution_restore import (
        _seed_generation_journal,
    )

    harness = _one_league_game_log_plan(_harness(tmp_path))
    factory = _factory(tmp_path, harness)
    public_root = cast("Path", harness["public_root"])
    transaction = cast("SuccessorUpdateTransaction", harness["transaction"])
    plan = cast("SuccessorExecutionPlan", harness["plan"])
    requested_scope = cast("RequestedRouteScope", harness["requested_scope"])
    dispatch = cast("SealedUpdateExecutionDispatch", harness["dispatch"])
    logical_params = cast("dict[str, object]", harness["logical_params"])
    candidate_root = public_root.parent
    candidate_identity = (candidate_root.stat().st_dev, candidate_root.stat().st_ino)

    first = factory(transaction, candidate_root, plan)
    first_session = first._capture_session
    first_session.admit(
        estimated_checkpoint_bytes=first._estimated_checkpoint_bytes,
        monotonic_now_seconds=first._monotonic_clock(),
        monotonic_deadline_seconds=first._monotonic_deadline_seconds,
    )
    bronze_binding, _contract = _complete_logical_call(
        first_session,
        endpoint_name=requested_scope.endpoint_name,
        params=logical_params,
    )
    first_session.record_completed(bronze_binding)
    first_session.close()
    first._terminal_store.close()
    _seed_generation_journal(
        public_root,
        generation_identity_sha256=transaction.generation_identity_sha256,
        binding=bronze_binding,
    )

    runtime = factory(transaction, candidate_root, plan)
    session = runtime._capture_session
    assert (runtime._candidate_root.stat().st_dev, runtime._candidate_root.stat().st_ino) == (
        candidate_identity
    )
    assert runtime._preloaded_journal_attestations
    assert runtime._preloaded_journal_attestations[0].logical_call_receipt_sha256 == (
        bronze_binding.logical_call_receipt_sha256
    )
    assert session.state is CaptureSessionState.CREATED
    assert session.inventory_unsealed_contexts()

    events: list[str] = []

    def record_orchestrator(*_args: object, **_kwargs: object) -> object:
        events.append("orchestrator")
        raise AssertionError("restore must complete before constructing Orchestrator")

    with (
        patch.object(session, "admit", wraps=session.admit) as admit,
        patch.object(
            session,
            "adopt_unsealed_same_generation_writer",
            wraps=session.adopt_unsealed_same_generation_writer,
        ) as adopt,
        patch.object(
            session,
            "restore_completed_bindings",
            wraps=session.restore_completed_bindings,
        ) as restore,
        patch(
            "nbadb.orchestrate.successor_runtime.Orchestrator",
            side_effect=record_orchestrator,
        ),
        pytest.raises(AssertionError, match="restore must complete before"),
    ):
        asyncio.run(runtime.run_daily())

    assert events == ["orchestrator"]
    admit.assert_not_called()
    adopt.assert_called_once()
    restore.assert_called_once()
    restored = restore.call_args.args[0]
    assert tuple(item.logical_call_receipt_sha256 for item in restored) == (
        bronze_binding.logical_call_receipt_sha256,
    )
    assert runtime._restored_delta_receipts
    assert runtime._restored_delta_receipts[0].execution_dispatch_identity_sha256 == (
        dispatch.identity_sha256
    )
    assert session.state is CaptureSessionState.ADMITTED


def test_factory_incomplete_multi_route_journal_fails_before_capture_restore(
    tmp_path: Path,
) -> None:
    from tests.unit.orchestrate.test_successor_execution_restore import (
        _seed_generation_journal,
    )

    harness = _multi_route_harness(_harness(tmp_path))
    factory = _factory(tmp_path, harness)
    public_root = cast("Path", harness["public_root"])
    transaction = cast("SuccessorUpdateTransaction", harness["transaction"])
    plan = cast("SuccessorExecutionPlan", harness["plan"])
    dispatch = plan.dispatches[0]
    binding = LogicalCallReceiptBinding(
        logical_call_receipt_sha256="c" * 64,
        endpoint_name=dispatch.endpoint_name,
        logical_parameters_sha256=dispatch.parameters_sha256,
        provider_authority_sha256=transaction.baseline.provider_authority_sha256,
        result_route_ids=dispatch.staging_route_ids[:1],
    )
    _seed_generation_journal(
        public_root,
        generation_identity_sha256=transaction.generation_identity_sha256,
        binding=binding,
    )

    runtime = factory(transaction, public_root.parent, plan)
    session = runtime._capture_session
    with (
        patch.object(
            session,
            "restore_completed_bindings",
            wraps=session.restore_completed_bindings,
        ) as restore,
        patch("nbadb.orchestrate.successor_runtime.Orchestrator") as orchestrator_type,
        pytest.raises(SuccessorUpdateContractError, match="exactly cover"),
    ):
        asyncio.run(runtime.run_daily())

    orchestrator_type.assert_not_called()
    restore.assert_not_called()


def test_factory_rejects_invalid_journal_inventory_before_runtime_return(
    tmp_path: Path,
) -> None:
    harness = _one_league_game_log_plan(_harness(tmp_path))
    factory = _factory(tmp_path, harness)
    public_root = cast("Path", harness["public_root"])
    transaction = cast("SuccessorUpdateTransaction", harness["transaction"])
    plan = cast("SuccessorExecutionPlan", harness["plan"])
    duckdb_path = public_root / "nba.duckdb"
    duckdb_path.unlink()
    connection = duckdb.connect(str(duckdb_path))
    try:
        connection.execute(
            """
            CREATE TABLE _successor_staging_replacement_journal (
                successor_generation_sha256 VARCHAR NOT NULL,
                source_scope_sha256 VARCHAR NOT NULL,
                staging_key VARCHAR NOT NULL,
                canonical_frame_format VARCHAR NOT NULL,
                frame_content_hash_contract VARCHAR NOT NULL,
                frame_schema_hash_contract VARCHAR NOT NULL,
                prior_persisted_content_sha256 VARCHAR,
                persisted_content_sha256 VARCHAR NOT NULL,
                persisted_schema_sha256 VARCHAR NOT NULL,
                persisted_row_count BIGINT NOT NULL,
                logical_call_receipt_sha256 VARCHAR NOT NULL,
                provider_authority_sha256 VARCHAR NOT NULL,
                logical_parameters_sha256 VARCHAR NOT NULL,
                result_route_id VARCHAR NOT NULL,
                replacement_sha256 VARCHAR NOT NULL
            )
            """
        )
        connection.execute(
            """
            INSERT INTO _successor_staging_replacement_journal VALUES (
                ?, ?, 'stg_league_game_log',
                'arrow_ipc_stream_v2_pyarrow_v5', ?, ?, ?, ?, ?, 1, ?, ?, ?,
                'league_game_log:stg_league_game_log:0', ?
            )
            """,
            [
                transaction.generation_identity_sha256,
                "d" * 64,
                "e" * 64,
                "f" * 64,
                "1" * 64,
                "NOT-A-SHA",
                "2" * 64,
                "3" * 64,
                "4" * 64,
                "5" * 64,
                "6" * 64,
            ],
        )
    finally:
        connection.close()

    with pytest.raises(
        SuccessorUpdateContractError,
        match="restoration inventory is invalid",
    ):
        factory(transaction, public_root.parent, plan)


def test_factory_ignores_foreign_generation_journal_instead_of_adopting(
    tmp_path: Path,
) -> None:
    from tests.unit.orchestrate.test_successor_execution_restore import (
        _seed_generation_journal,
    )

    harness = _one_league_game_log_plan(_harness(tmp_path))
    factory = _factory(tmp_path, harness)
    public_root = cast("Path", harness["public_root"])
    transaction = cast("SuccessorUpdateTransaction", harness["transaction"])
    plan = cast("SuccessorExecutionPlan", harness["plan"])
    dispatch = cast("SealedUpdateExecutionDispatch", harness["dispatch"])
    binding = LogicalCallReceiptBinding(
        logical_call_receipt_sha256="e" * 64,
        endpoint_name=dispatch.endpoint_name,
        logical_parameters_sha256=dispatch.parameters_sha256,
        provider_authority_sha256=transaction.baseline.provider_authority_sha256,
        result_route_ids=dispatch.staging_route_ids,
    )
    _seed_generation_journal(
        public_root,
        generation_identity_sha256="0" * 64,
        binding=binding,
    )

    runtime = factory(transaction, public_root.parent, plan)
    session = runtime._capture_session
    assert runtime._preloaded_journal_attestations == ()
    assert session.state is CaptureSessionState.CREATED

    with (
        patch.object(session, "admit", wraps=session.admit) as admit,
        patch.object(
            session,
            "adopt_unsealed_same_generation_writer",
            wraps=session.adopt_unsealed_same_generation_writer,
        ) as adopt,
        patch(
            "nbadb.orchestrate.successor_runtime.Orchestrator",
            side_effect=AssertionError("foreign journal must not restore"),
        ),
        pytest.raises(AssertionError, match="foreign journal must not restore"),
    ):
        asyncio.run(runtime.run_daily())

    admit.assert_called_once()
    adopt.assert_not_called()
    assert runtime._restored_delta_receipts == ()


def test_factory_reopened_created_without_journal_or_bronze_admits_instead_of_adopting(
    tmp_path: Path,
) -> None:
    harness = _one_league_game_log_plan(_harness(tmp_path))
    factory = _factory(tmp_path, harness)
    public_root = cast("Path", harness["public_root"])
    runtime = factory(
        harness["transaction"],  # type: ignore[arg-type]
        public_root.parent,
        harness["plan"],  # type: ignore[arg-type]
    )
    session = runtime._capture_session
    assert session.state is CaptureSessionState.CREATED
    assert runtime._preloaded_journal_attestations == ()
    assert session.inventory_unsealed_contexts() == ()

    with (
        patch.object(session, "admit", wraps=session.admit) as admit,
        patch.object(
            session,
            "adopt_unsealed_same_generation_writer",
            wraps=session.adopt_unsealed_same_generation_writer,
        ) as adopt,
        patch(
            "nbadb.orchestrate.successor_runtime.Orchestrator",
            side_effect=AssertionError("fresh execution reached Orchestrator"),
        ),
        pytest.raises(AssertionError, match="fresh execution reached Orchestrator"),
    ):
        asyncio.run(runtime.run_daily())

    admit.assert_called_once()
    adopt.assert_not_called()
    assert runtime._restored_delta_receipts == ()
    assert session.state is CaptureSessionState.ADMITTED


def test_restore_same_generation_execution_uses_terminal_without_orchestrator(
    tmp_path: Path,
) -> None:
    harness = _harness(tmp_path)
    factory = _factory(tmp_path, harness)
    terminal = cast("ExactPlanRuntimeTerminalReceipt", harness["terminal"])
    identity = harness["identity"]
    public_root = cast("Path", harness["public_root"])
    plan = cast("SuccessorExecutionPlan", harness["plan"])
    session = MagicMock()
    session.restore_sealed_identity_if_present.return_value = None
    session.state = CaptureSessionState.CREATED
    session.closed = False
    session.seal.return_value = identity
    session.close.return_value = identity

    def adopt() -> None:
        session.state = CaptureSessionState.ADMITTED

    session.adopt_unsealed_same_generation_writer.side_effect = adopt

    with patch.object(
        PrivateCaptureSession,
        "create_under_authorized_base",
        return_value=session,
    ):
        runtime = factory(
            harness["transaction"],  # type: ignore[arg-type]
            public_root.parent,
            plan,
        )
    runtime._terminal_store.write(terminal)

    with patch(
        "nbadb.orchestrate.successor_runtime.Orchestrator",
        side_effect=AssertionError("executed restore must not construct Orchestrator"),
    ):
        runtime.restore_same_generation_execution()

    assert runtime.capture_identity is identity
    assert runtime.successor_delta_receipts == terminal.delta_receipts
    session.admit.assert_not_called()
    session.adopt_unsealed_same_generation_writer.assert_called_once()


@pytest.mark.parametrize(
    ("field_name", "value"),
    [
        ("terminal_receipt_max_bytes", True),
        ("terminal_receipt_max_bytes", 0),
        ("runtime_log_max_bytes", -1),
        ("runtime_log_max_bytes", 1 << 63),
        ("candidate_max_bytes", False),
        ("candidate_max_bytes", 0),
    ],
)
def test_factory_rejects_invalid_aggregate_byte_limits(
    tmp_path: Path,
    field_name: str,
    value: object,
) -> None:
    harness = _harness(tmp_path)

    with pytest.raises(SuccessorUpdateContractError, match="admission authority"):
        _factory(tmp_path, harness, **{field_name: value})  # type: ignore[arg-type]


def test_factory_rejects_candidate_over_cap_before_private_child_creation(
    tmp_path: Path,
) -> None:
    harness = _harness(tmp_path)
    public_root = cast("Path", harness["public_root"])
    candidate_bytes = measure_installed_public_tree(public_root).byte_count
    factory = _factory(
        tmp_path,
        harness,
        candidate_max_bytes=candidate_bytes - 1,
    )

    with (
        patch.object(
            PrivateCaptureSession,
            "create_under_authorized_base",
        ) as create_session,
        pytest.raises(SuccessorUpdateContractError, match="candidate public tree exceeds"),
    ):
        factory(
            harness["transaction"],  # type: ignore[arg-type]
            public_root.parent,
            harness["plan"],  # type: ignore[arg-type]
        )

    create_session.assert_not_called()
    assert not any(factory._terminal_base_root.iterdir())


def test_factory_rejects_log_root_over_cap_before_private_child_creation(
    tmp_path: Path,
) -> None:
    harness = _harness(tmp_path)
    public_root = cast("Path", harness["public_root"])
    factory = _factory(tmp_path, harness, runtime_log_max_bytes=3)
    (factory._log_dir / "runtime.log").write_bytes(b"four")

    with (
        patch.object(
            PrivateCaptureSession,
            "create_under_authorized_base",
        ) as create_session,
        pytest.raises(SuccessorUpdateContractError, match="runtime log root exceeds"),
    ):
        factory(
            harness["transaction"],  # type: ignore[arg-type]
            public_root.parent,
            harness["plan"],  # type: ignore[arg-type]
        )

    create_session.assert_not_called()
    assert not any(factory._terminal_base_root.iterdir())


def test_one_factory_derives_disjoint_private_authority_per_generation(tmp_path: Path) -> None:
    harness = _harness(tmp_path)
    factory = _factory(tmp_path, harness)
    public_root = cast("Path", harness["public_root"])
    first = cast("SuccessorUpdateTransaction", harness["transaction"])
    second = SuccessorUpdateTransaction.candidate(
        generation=first.generation + 1,
        baseline=first.baseline,
        intent=first.intent,
    )

    with patch.object(
        PrivateCaptureSession,
        "create_under_authorized_base",
    ) as create_session:
        first_runtime = factory(
            first,
            public_root.parent,
            harness["plan"],  # type: ignore[arg-type]
        )
        second_runtime = factory(
            second,
            public_root.parent,
            harness["plan"],  # type: ignore[arg-type]
        )

    first_capture_base = create_session.call_args_list[0].args[0]
    second_capture_base = create_session.call_args_list[1].args[0]
    first_generation_name = create_session.call_args_list[0].args[1]
    second_generation_name = create_session.call_args_list[1].args[1]
    assert first_capture_base == second_capture_base
    assert first_generation_name != second_generation_name
    assert first_generation_name == first.generation_identity_sha256
    assert second_generation_name == second.generation_identity_sha256
    assert first_runtime._terminal_store._path != second_runtime._terminal_store._path
    assert first_runtime._terminal_store._path.name == f"{first.generation_identity_sha256}.json"
    assert second_runtime._terminal_store._path.name == (
        f"{second.generation_identity_sha256}.json"
    )


@pytest.mark.parametrize("authority_index", [0, 1, 2])
def test_factory_rejects_private_root_substitution_before_child_creation(
    tmp_path: Path,
    authority_index: int,
) -> None:
    harness = _harness(tmp_path)
    factory = _factory(tmp_path, harness)
    path, _identity, label = factory._private_root_authorities[authority_index]
    retained = path.with_name(path.name + "-retained")
    path.rename(retained)
    path.mkdir(mode=0o700)
    public_root = cast("Path", harness["public_root"])

    with (
        patch.object(
            PrivateCaptureSession,
            "create_under_authorized_base",
        ) as create_session,
        pytest.raises(SuccessorUpdateContractError, match=label),
    ):
        factory(
            harness["transaction"],  # type: ignore[arg-type]
            public_root.parent,
            harness["plan"],  # type: ignore[arg-type]
        )

    create_session.assert_not_called()
    assert list(path.iterdir()) == []


@pytest.mark.parametrize("authority_index", [0, 1, 2])
def test_runtime_rechecks_private_root_before_restore_provider_or_write(
    tmp_path: Path,
    authority_index: int,
) -> None:
    harness = _harness(tmp_path)
    factory = _factory(tmp_path, harness)
    public_root = cast("Path", harness["public_root"])
    runtime = factory(
        harness["transaction"],  # type: ignore[arg-type]
        public_root.parent,
        harness["plan"],  # type: ignore[arg-type]
    )
    path, _identity, label = factory._private_root_authorities[authority_index]
    retained = path.with_name(path.name + "-retained")
    path.rename(retained)
    path.mkdir(mode=0o700)

    try:
        with (
            patch("nbadb.orchestrate.successor_runtime.Orchestrator") as orchestrator_type,
            pytest.raises(SuccessorUpdateContractError, match=label),
        ):
            asyncio.run(runtime.run_daily())
        orchestrator_type.assert_not_called()
        assert list(path.iterdir()) == []
    finally:
        runtime._capture_session.close()


@pytest.mark.parametrize("substitution", ["candidate", "public"])
def test_runtime_rechecks_candidate_tree_before_restore_provider_or_write(
    tmp_path: Path,
    substitution: str,
) -> None:
    harness = _harness(tmp_path)
    factory = _factory(tmp_path, harness)
    public_root = cast("Path", harness["public_root"])
    candidate_root = public_root.parent
    runtime = factory(
        harness["transaction"],  # type: ignore[arg-type]
        candidate_root,
        harness["plan"],  # type: ignore[arg-type]
    )
    target = candidate_root if substitution == "candidate" else public_root
    retained = target.with_name(target.name + "-retained")
    target.rename(retained)
    if substitution == "candidate":
        target.mkdir(mode=0o700)
        replacement_public = target / "public"
        replacement_public.mkdir(mode=0o700)
    else:
        target.mkdir(mode=0o700)
        replacement_public = target
    (replacement_public / "nba.duckdb").write_bytes(b"foreign")

    try:
        with (
            patch("nbadb.orchestrate.successor_runtime.Orchestrator") as orchestrator_type,
            pytest.raises(SuccessorUpdateContractError, match="candidate .*identity changed"),
        ):
            asyncio.run(runtime.run_daily())
        orchestrator_type.assert_not_called()
        assert (replacement_public / "nba.duckdb").read_bytes() == b"foreign"
    finally:
        runtime._capture_session.close()


@pytest.mark.parametrize(
    ("field_name", "value", "expected_error"),
    [
        ("semantic_source_sha", "a" * 40, "capture_scope.semantic_source_sha"),
        ("chain_id", "foreign-chain", "capture_scope.chain_id"),
    ],
)
def test_factory_rejects_foreign_scope_before_private_store_or_session_mutation(
    tmp_path: Path,
    field_name: str,
    value: str,
    expected_error: str,
) -> None:
    harness = _harness(tmp_path)
    scope = cast("CaptureRunScope", harness["scope"])
    factory = _factory(
        tmp_path,
        harness,
        scope_template=replace(scope, **{field_name: value}),
    )
    public_root = cast("Path", harness["public_root"])

    with (
        patch.object(
            PrivateCaptureSession,
            "create_under_authorized_base",
        ) as create_session,
        pytest.raises(SuccessorUpdateContractError, match=expected_error),
    ):
        factory(
            harness["transaction"],  # type: ignore[arg-type]
            public_root.parent,
            harness["plan"],  # type: ignore[arg-type]
        )

    create_session.assert_not_called()


def test_current_staging_preflight_fails_before_capture_restore_or_admission(
    tmp_path: Path,
    _stub_current_staging_preflight: MagicMock,
) -> None:
    harness = _harness(tmp_path)
    capture = MagicMock()
    runtime = _runtime(harness, capture)
    _stub_current_staging_preflight.side_effect = SuccessorUpdateContractError(
        "sealed route absent from current staging authority"
    )

    with pytest.raises(SuccessorUpdateContractError, match="current staging authority"):
        asyncio.run(runtime.run_daily())

    capture.restore_sealed_identity_if_present.assert_not_called()
    capture.admit.assert_not_called()


def _admitted_capture() -> MagicMock:
    session = MagicMock(spec=PrivateCaptureSession)
    session.closed = False
    session.state = CaptureSessionState.ADMITTED
    return session


def _successor_orchestrator(harness: dict[str, object]) -> Orchestrator:
    transaction = cast("SuccessorUpdateTransaction", harness["transaction"])
    registry = _registry_for_plan(cast("SuccessorExecutionPlan", harness["plan"]))
    return Orchestrator(
        settings=NbaDbSettings(data_dir=cast("Path", harness["public_root"])),
        capture_session=_admitted_capture(),
        successor_transaction=transaction,
        successor_registry=registry,
        successor_registry_authority=registry.capture_authority(),
    )


def test_extract_all_patterns_rejects_later_derived_successor_fanout(
    tmp_path: Path,
) -> None:
    harness = _harness(tmp_path)
    orch = _successor_orchestrator(harness)
    orch._successor_execution_plan = harness["plan"]  # type: ignore[assignment]
    runner = MagicMock()
    runner.run_pattern_result = MagicMock()

    with pytest.raises(
        SuccessorUpdateContractError,
        match="later-derived or out-of-manifest fan-out",
    ):
        asyncio.run(
            orch._extract_all_patterns(
                runner,
                plan=[],
                seasons=["2025-26"],
                game_ids=["0022400001", "0022400999"],
                player_ids=[],
                team_ids=[],
                current_team_ids=[],
                game_dates=[],
                player_team_season_params=[],
                game_log_df=MagicMock(),
                run_mode="daily",
            )
        )

    runner.run_pattern_result.assert_not_called()


def test_run_daily_rejects_later_derived_discovery_fanout_before_provider(
    tmp_path: Path,
) -> None:
    harness = _harness(tmp_path)
    orch = _successor_orchestrator(harness)
    orch._successor_execution_plan = harness["plan"]  # type: ignore[assignment]

    with (
        patch("nbadb.orchestrate.orchestrator.EntityDiscovery") as discovery_cls,
        patch("nbadb.orchestrate.orchestrator.DBManager") as db_cls,
        patch.object(orch, "_extract_all_patterns") as extract,
        patch.object(orch, "_persist_successor_live_snapshot") as live,
        pytest.raises(
            SuccessorUpdateContractError,
            match="later-derived or out-of-manifest fan-out",
        ),
    ):
        asyncio.run(orch._run_daily())

    discovery_cls.assert_not_called()
    db_cls.assert_not_called()
    extract.assert_not_called()
    live.assert_not_called()


def test_run_monthly_rejects_later_derived_discovery_fanout_before_provider(
    tmp_path: Path,
) -> None:
    harness = _harness(tmp_path)
    orch = _successor_orchestrator(harness)
    orch._successor_execution_plan = harness["plan"]  # type: ignore[assignment]

    with (
        patch("nbadb.orchestrate.orchestrator.EntityDiscovery") as discovery_cls,
        patch("nbadb.orchestrate.orchestrator.DBManager") as db_cls,
        patch.object(orch, "_extract_all_patterns") as extract,
        pytest.raises(
            SuccessorUpdateContractError,
            match="later-derived or out-of-manifest fan-out",
        ),
    ):
        asyncio.run(orch._run_monthly())

    discovery_cls.assert_not_called()
    db_cls.assert_not_called()
    extract.assert_not_called()


def test_bound_plan_rejects_later_derived_live_snapshot_fanout(
    tmp_path: Path,
) -> None:
    harness = _harness(tmp_path)
    orch = _successor_orchestrator(harness)
    orch._successor_execution_plan = harness["plan"]  # type: ignore[assignment]

    with (
        patch("nbadb.orchestrate.orchestrator.LiveSnapshotWarehouse") as warehouse_cls,
        pytest.raises(
            SuccessorUpdateContractError,
            match="later-derived or out-of-manifest fan-out",
        ),
    ):
        orch._extract_successor_live_snapshot()

    warehouse_cls.assert_not_called()
