from __future__ import annotations

import fcntl
import hashlib
import json
import os
import platform
import shutil
from contextlib import contextmanager
from dataclasses import replace
from typing import TYPE_CHECKING, Any

import duckdb
import pytest

import nbadb.orchestrate.successor_planning_driver as planning_driver_module
from nbadb.contracts.staging_route_contract import staging_route_contract_bundle
from nbadb.extract.bronze import LogicalCallReceiptBinding
from nbadb.orchestrate.capture_session import CaptureRunScope, PrivateGenerationIdentity
from nbadb.orchestrate.successor_planner import (
    ConcreteSuccessorPlanningExecutor,
    PlanningCallExecution,
    PlanningWaveSeal,
    deterministic_planning_generation_id,
)
from nbadb.orchestrate.successor_planning_driver import (
    PlanningExactCallRuntimeRequest,
    PlanningMemberEnvelope,
    PlanningProgramDriverError,
    PlanningWaveSealRuntimeRequest,
    RequestDrivenSuccessorPlanningDriver,
)
from nbadb.orchestrate.successor_planning_generation_contract import (
    PlanningDataMember,
    PlanningDispatchPhase,
    SuccessorPlanningWave,
)
from nbadb.orchestrate.successor_planning_program_compiler import (
    PlanningSemanticMemberAuthority,
    install_successor_planning_semantic_schema,
    successor_planning_database_schema_sha256,
    successor_planning_semantic_write_transaction,
    write_successor_planning_semantic_partition,
)
from nbadb.orchestrate.successor_planning_request_builder import (
    build_successor_planning_request,
)
from nbadb.orchestrate.successor_planning_semantic_contract import PlanningSemanticKind
from nbadb.orchestrate.successor_planning_store import (
    CommittedPlanningWaveAuthority,
    PlanningArtifactSource,
    PlanningDatabaseSource,
    PlanningGenerationPhase,
    PlanningMemberSource,
    PlanningStoreBudget,
    SuccessorPlanningStore,
)
from nbadb.orchestrate.successor_planning_wave_receipt import (
    PlanningWaveCallBinding,
    PlanningWaveCompletionReceipt,
    PlanningWaveMemberBinding,
)
from nbadb.orchestrate.successor_update_contract import SuccessorUpdateMode

if TYPE_CHECKING:
    from pathlib import Path


def _digest(label: str) -> str:
    return hashlib.sha256(label.encode()).hexdigest()


def _source(path: Path, encoded: bytes) -> PlanningArtifactSource:
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    path.write_bytes(encoded)
    path.chmod(0o600)
    return PlanningArtifactSource(
        path=path.resolve(),
        sha256=hashlib.sha256(encoded).hexdigest(),
        byte_count=len(encoded),
    )


def _database_source(path: Path) -> PlanningDatabaseSource:
    connection = duckdb.connect(str(path), read_only=True)
    try:
        schema = successor_planning_database_schema_sha256(connection)
    finally:
        connection.close()
    encoded = path.read_bytes()
    return PlanningDatabaseSource(
        artifact=PlanningArtifactSource(
            path=path.resolve(),
            sha256=hashlib.sha256(encoded).hexdigest(),
            byte_count=len(encoded),
        ),
        schema_sha256=schema,
    )


def _request(mode: SuccessorUpdateMode):
    return build_successor_planning_request(
        baseline_identity_sha256=_digest("baseline"),
        mode=mode,
        source_sha="b" * 40,
        cutoff_utc="2026-08-12T00:00:00Z",
        as_of_utc="2026-08-13T00:00:00Z",
        workflow_run_id=731,
        workflow_run_attempt=4,
    )


class _BudgetFactory:
    def __call__(self) -> PlanningStoreBudget:
        return PlanningStoreBudget(
            # The MONTHLY fixture retains about 135 MiB across 65 distinct,
            # crash-resumable database snapshots.  Keep test capacity well
            # above that measured authority without changing production policy.
            generation_max_bytes=512 * 1024 * 1024,
            artifact_max_bytes=64 * 1024 * 1024,
            control_max_bytes=8 * 1024 * 1024,
            minimum_free_bytes=1,
            monotonic_deadline_seconds=1_000.0,
            minimum_deadline_headroom_seconds=100.0,
        )


class _Resolver:
    def verify(
        self,
        *,
        request: Any,
        planning_generation_id: str,
        authority: CommittedPlanningWaveAuthority,
    ) -> PrivateGenerationIdentity:
        assert request.identity_sha256 == authority.completion_receipt.planning_request_sha256
        assert planning_generation_id == authority.completion_receipt.planning_generation_id
        return PrivateGenerationIdentity.from_canonical_bytes(
            authority.private_generation_identity.canonical_bytes
        )


def _logical_bindings_sha256(bindings: tuple[LogicalCallReceiptBinding, ...]) -> str:
    return hashlib.sha256(
        json.dumps(
            [
                {
                    "endpoint_name": binding.endpoint_name,
                    "logical_call_receipt_sha256": binding.logical_call_receipt_sha256,
                    "logical_parameters_sha256": binding.logical_parameters_sha256,
                    "provider_authority_sha256": binding.provider_authority_sha256,
                    "result_route_ids": list(binding.result_route_ids),
                }
                for binding in bindings
            ],
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=True,
            allow_nan=False,
        ).encode()
    ).hexdigest()


class _SemanticRuntime:
    def __init__(
        self,
        *,
        live_game_ids: tuple[str, ...] = ("0022500001",),
        typed_zero_foundations: bool = False,
        fail_call_once: bool = False,
        fail_seal_wave_once: int | None = None,
        forge_envelope_generation: bool = False,
        forge_output_schema: bool = False,
    ) -> None:
        self.live_game_ids = live_game_ids
        self.typed_zero_foundations = typed_zero_foundations
        self.fail_call_once = fail_call_once
        self.fail_seal_wave_once = fail_seal_wave_once
        self.forge_envelope_generation = forge_envelope_generation
        self.forge_output_schema = forge_output_schema
        self.call_requests: list[PlanningExactCallRuntimeRequest] = []
        self.seal_requests: list[PlanningWaveSealRuntimeRequest] = []

    def _semantic_outputs(
        self,
        request: PlanningExactCallRuntimeRequest,
        scope: Any,
    ) -> tuple[
        tuple[
            PlanningSemanticKind,
            dict[str, object],
            list[dict[str, object]],
            str | None,
        ],
        ...,
    ]:
        parameters = scope.parameters
        if scope.endpoint_name == "league_game_log":
            year = int(parameters["season"][:4])
            return (
                (
                    PlanningSemanticKind.GAME_DATE_INDEX,
                    {
                        "season": parameters["season"],
                        "season_type": parameters["season_type"],
                    },
                    [
                        {
                            "game_date": f"{year + 1:04d}-08-12",
                            "game_id": f"002{year % 100:02d}00001",
                        }
                    ],
                    None,
                ),
            )
        if scope.endpoint_name == "player_game_logs":
            return (
                (
                    PlanningSemanticKind.PLAYER_TEAM_SEASON_AFFILIATION,
                    {
                        "season": parameters["season"],
                        "season_type": parameters["season_type"],
                    },
                    [{"player_id": 2544, "team_id": 1610612747}],
                    None,
                ),
            )
        if scope.endpoint_name == "common_all_players":
            return (
                (
                    PlanningSemanticKind.SEASON_PLAYER_UNIVERSE,
                    {
                        "season": parameters["season"],
                        "current_only": bool(parameters["is_only_current_season"]),
                    },
                    [{"player_id": 2544}],
                    None,
                ),
            )
        if scope.endpoint_name == "common_team_years":
            seasons = sorted(
                {
                    str(item.parameters["season"])
                    for item in request.request.requested_planning_scopes
                    if item.endpoint_name == "league_game_log"
                }
            )
            return tuple(
                (
                    PlanningSemanticKind.SEASON_TEAM_UNIVERSE,
                    {"season": season},
                    [{"team_id": 1610612747}],
                    None,
                )
                for season in seasons
            ) + (
                (
                    PlanningSemanticKind.CURRENT_TEAM_UNIVERSE,
                    {"as_of_utc": request.request.as_of_utc},
                    [{"team_id": 1610612747}],
                    None,
                ),
                (
                    PlanningSemanticKind.AUXILIARY_NO_DERIVED_DATA,
                    {},
                    [],
                    "no_derived_semantic_values",
                ),
            )
        if scope.endpoint_name == "live_score_board":
            values = [{"game_id": game_id} for game_id in self.live_game_ids]
            return (
                (
                    PlanningSemanticKind.ACTIVE_LIVE_GAME_IDS,
                    {"as_of_utc": request.request.as_of_utc},
                    values,
                    None if values else "provider_success_empty",
                ),
            )
        if scope.endpoint_name == "cume_stats_player_games":
            values = [] if self.typed_zero_foundations else [{"game_id": "0022500001"}]
            return (
                (
                    PlanningSemanticKind.PLAYER_CUME_FOUNDATION_GAME_IDS,
                    dict(parameters),
                    values,
                    None if values else "complete_empty",
                ),
            )
        if scope.endpoint_name == "cume_stats_team_games":
            values = [] if self.typed_zero_foundations else [{"game_id": "0022500001"}]
            return (
                (
                    PlanningSemanticKind.TEAM_CUME_FOUNDATION_GAME_IDS,
                    dict(parameters),
                    values,
                    None if values else "complete_empty",
                ),
            )
        raise AssertionError(scope.endpoint_name)

    async def execute_planning_call(
        self,
        request: PlanningExactCallRuntimeRequest,
    ) -> PlanningCallExecution:
        self.call_requests.append(request)
        if self.fail_call_once:
            self.fail_call_once = False
            raise RuntimeError("injected-planning-call-crash")
        database_path = request.private_work_root / (
            f"planning-{len(self.call_requests)}-{request.dispatch.identity_sha256}.duckdb"
        )
        if request.input_planning_database is None:
            connection = duckdb.connect(str(database_path))
            install_successor_planning_semantic_schema(connection)
        else:
            shutil.copyfile(request.input_planning_database.artifact.path, database_path)
            database_path.chmod(0o600)
            connection = duckdb.connect(str(database_path))
        logical_receipt = _digest(f"logical:{request.dispatch.identity_sha256}")
        pending: list[tuple[Any, Any]] = []
        try:
            with successor_planning_semantic_write_transaction(connection) as transaction:
                for scope in request.requested_route_scopes:
                    for kind, partition, values, reason in self._semantic_outputs(request, scope):
                        descriptor = write_successor_planning_semantic_partition(
                            transaction,
                            producing_scope=scope,
                            semantic_kind=kind,
                            partition=partition,
                            values=values,
                            typed_zero_reason_code=reason,
                        )
                        pending.append((scope, descriptor))
            connection.execute("CHECKPOINT")
        finally:
            connection.close()
        database_path.chmod(0o600)
        database = _database_source(database_path)
        if self.forge_output_schema:
            database = replace(database, schema_sha256="f" * 64)
        members: list[PlanningMemberSource] = []
        for scope, descriptor in pending:
            member_id = f"member-{request.wave_index}-{descriptor.identity_sha256[:32]}"
            envelope = PlanningMemberEnvelope(
                planning_request_sha256=request.request.identity_sha256,
                planning_generation_id=(
                    "forged-generation"
                    if self.forge_envelope_generation
                    else request.planning_generation_id
                ),
                wave_index=request.wave_index,
                producing_scope=scope,
                input_planning_database_sha256=(
                    None
                    if request.input_planning_database is None
                    else request.input_planning_database.artifact.sha256
                ),
                output_planning_database_sha256=database.artifact.sha256,
                logical_call_receipt_sha256=logical_receipt,
                provider_authority_sha256=request.provider_authority_sha256,
                member_id=member_id,
                semantic=descriptor,
            )
            artifact = _source(
                request.private_work_root / f"{member_id}.json",
                envelope.canonical_bytes,
            )
            member = PlanningDataMember(
                member_id=member_id,
                wave_index=request.wave_index,
                producing_scope_sha256=scope.identity_sha256,
                schema_sha256=PlanningMemberEnvelope.schema_sha256,
                content_sha256=artifact.sha256,
                row_count=descriptor.value_count,
                semantic=descriptor,
                typed_zero_reason_code=descriptor.typed_zero_reason_code,
            )
            members.append(
                PlanningMemberSource(
                    member=member,
                    receipt_sha256=logical_receipt,
                    artifact=artifact,
                )
            )
        return PlanningCallExecution(
            members=tuple(sorted(members, key=lambda item: item.member.identity_sha256)),
            planning_database=database,
        )

    async def seal_planning_wave(
        self,
        request: PlanningWaveSealRuntimeRequest,
    ) -> PlanningWaveSeal:
        self.seal_requests.append(request)
        admission = request.admission
        if self.fail_seal_wave_once == admission.wave_index:
            self.fail_seal_wave_once = None
            raise RuntimeError(f"injected-seal-wave-{admission.wave_index}-crash")
        members = tuple(
            sorted(
                (member for call in request.committed_calls for member in call.members),
                key=lambda member: member.member.identity_sha256,
            )
        )
        provider_authority = staging_route_contract_bundle().provider_authority_sha256
        logical_bindings = tuple(
            sorted(
                (
                    LogicalCallReceiptBinding(
                        logical_call_receipt_sha256=call.members[0].receipt_sha256,
                        endpoint_name=call.sealed_dispatch.endpoint_name,
                        logical_parameters_sha256=call.sealed_dispatch.parameters_sha256,
                        provider_authority_sha256=provider_authority,
                        result_route_ids=tuple(sorted(call.sealed_dispatch.staging_route_ids)),
                    )
                    for call in request.committed_calls
                ),
                key=lambda item: item.logical_call_receipt_sha256,
            )
        )
        private_identity = PrivateGenerationIdentity(
            manifest_sha256=_digest(f"private:{admission.wave_index}:{admission.identity_sha256}"),
            provider_authority_sha256=provider_authority,
            semantic_source_sha=request.request.source_sha,
            chain_id=request.planning_generation_id,
            lane_id=f"planning-wave-{admission.wave_index}",
            workflow_run_id=request.request.workflow_run_id,
            workflow_run_attempt=request.request.workflow_run_attempt,
            artifact_count=max(1, len(request.committed_calls) * 3),
            done_call_count=len(request.committed_calls),
            done_call_receipt_sha256s=tuple(
                binding.logical_call_receipt_sha256 for binding in logical_bindings
            ),
            done_call_bindings_sha256=_logical_bindings_sha256(logical_bindings),
            done_attempt_count=len(request.committed_calls),
            done_blob_count=len(members),
            orphan_call_count=0,
            orphan_attempt_count=0,
            orphan_blob_count=0,
            stored_bytes=sum(member.artifact_bytes for member in members),
        )
        calls = tuple(
            PlanningWaveCallBinding(
                ordinal=ordinal,
                sealed_dispatch_identity_sha256=call.sealed_dispatch.identity_sha256,
                committed_call_identity_sha256=call.identity_sha256,
                logical_call_receipt_sha256=call.members[0].receipt_sha256,
                member_identity_sha256s=tuple(
                    member.member.identity_sha256 for member in call.members
                ),
            )
            for ordinal, call in enumerate(request.committed_calls)
        )
        member_bindings = tuple(
            PlanningWaveMemberBinding(
                member=member.member,
                logical_call_receipt_sha256=member.receipt_sha256,
            )
            for member in members
        )
        completion = PlanningWaveCompletionReceipt(
            planning_request_sha256=request.request.identity_sha256,
            planning_generation_id=request.planning_generation_id,
            wave_index=admission.wave_index,
            parent_wave_identity_sha256=admission.parent_wave_identity_sha256,
            wave_admission_identity_sha256=admission.identity_sha256,
            sealed_dispatch_identity_sha256s=tuple(
                dispatch.identity_sha256 for dispatch in admission.sealed_dispatches
            ),
            committed_calls=calls,
            requested_scope_identity_sha256s=admission.requested_scope_identity_sha256s,
            completed_scope_identity_sha256s=admission.requested_scope_identity_sha256s,
            members=member_bindings,
            logical_call_bindings=logical_bindings,
            capture_scope=CaptureRunScope(
                semantic_source_sha=request.request.source_sha,
                chain_id=private_identity.chain_id,
                lane_id=private_identity.lane_id,
                workflow_run_id=request.request.workflow_run_id,
                workflow_run_attempt=request.request.workflow_run_attempt,
            ),
            private_generation_identity=private_identity,
            planning_database_sha256=request.planning_database.artifact.sha256,
            planning_database_bytes=request.planning_database.artifact.byte_count,
            planning_database_schema_sha256=request.planning_database.schema_sha256,
        )
        wave = SuccessorPlanningWave(
            wave_index=admission.wave_index,
            parent_wave_identity_sha256=admission.parent_wave_identity_sha256,
            requested_scope_identity_sha256s=admission.requested_scope_identity_sha256s,
            completed_scope_identity_sha256s=admission.requested_scope_identity_sha256s,
            member_identity_sha256s=tuple(member.member.identity_sha256 for member in members),
            member_receipt_sha256s=tuple(member.receipt_sha256 for member in members),
            private_generation_identity_sha256=hashlib.sha256(
                private_identity.canonical_bytes
            ).hexdigest(),
            completion_receipt_sha256=hashlib.sha256(completion.canonical_bytes).hexdigest(),
        )
        return PlanningWaveSeal(
            wave=wave,
            private_generation_identity=private_identity,
            completion_receipt=completion,
        )


def _executor(
    tmp_path: Path,
    *,
    mode: SuccessorUpdateMode = SuccessorUpdateMode.DAILY,
    runtime: _SemanticRuntime | None = None,
    store: SuccessorPlanningStore | None = None,
):
    public = tmp_path / "public"
    public.mkdir(exist_ok=True)
    planning_store = store or SuccessorPlanningStore(
        (tmp_path / "private-store").resolve(),
        public_roots=(public.resolve(),),
        monotonic_clock=lambda: 100.0,
    )
    exact_runtime = runtime or _SemanticRuntime()
    planning_work_root = (tmp_path / "private-work").resolve()
    planning_work_root.mkdir(mode=0o700, exist_ok=True)
    planning_work_root.chmod(0o700)
    planning_work_stat = planning_work_root.stat()
    executor = ConcreteSuccessorPlanningExecutor(
        planning_store,
        RequestDrivenSuccessorPlanningDriver(exact_runtime),
        _Resolver(),
        _BudgetFactory(),
        10_000_000,
        planning_work_root,
        (planning_work_stat.st_dev, planning_work_stat.st_ino),
    )
    return _request(mode), planning_store, exact_runtime, executor


@pytest.mark.parametrize("mode", [SuccessorUpdateMode.DAILY, SuccessorUpdateMode.MONTHLY])
async def test_daily_and_monthly_build_exact_store_backed_semantic_programs(
    tmp_path: Path,
    mode: SuccessorUpdateMode,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    request, store, runtime, executor = _executor(tmp_path, mode=mode)
    original_export = store.export_driver_context
    export_calls = 0

    def counted_export(*args: object, **kwargs: object):
        nonlocal export_calls
        export_calls += 1
        return original_export(*args, **kwargs)

    monkeypatch.setattr(store, "export_driver_context", counted_export)

    evidence = await executor(request)

    manifest = evidence.planning_generation_manifest
    snapshot = store.load_and_verify(
        request,
        deterministic_planning_generation_id(request),
        budget=_BudgetFactory()(),
    )
    assert snapshot.phase is PlanningGenerationPhase.SEALED
    budget = _BudgetFactory()()
    retained_private_bytes = sum(
        path.stat().st_size for path in store.root.rglob("*") if path.is_file()
    )
    assert retained_private_bytes < budget.generation_max_bytes // 2
    assert max(call.planning_database_bytes for call in snapshot.committed_calls) < (
        budget.artifact_max_bytes
    )
    assert deterministic_planning_generation_id(request).startswith("successor-planning-v2-")
    assert tuple(wave.wave_index for wave in manifest.waves) == (0, 1)
    assert runtime.call_requests and runtime.seal_requests
    assert all(member.semantic.value_count == member.row_count for member in manifest.members)
    phases = {dispatch.phase for dispatch in manifest.sealed_dispatches}
    assert phases == {
        PlanningDispatchPhase.PLANNING_WAVE_0,
        PlanningDispatchPhase.PLANNING_WAVE_1,
        PlanningDispatchPhase.UPDATE,
    }
    update = tuple(
        dispatch
        for dispatch in manifest.sealed_dispatches
        if dispatch.phase is PlanningDispatchPhase.UPDATE
    )
    assert all(dispatch.dependency_identity_sha256s for dispatch in update)
    expected_route_count = 370 if mode is SuccessorUpdateMode.DAILY else 403
    assert len({route for dispatch in update for route in dispatch.staging_route_ids}) == (
        expected_route_count
    )
    evidence.execution_plan.validate_against_manifest(manifest)
    assert export_calls <= 3 * len(runtime.call_requests) + 12


async def test_typed_zero_live_and_foundations_suppress_only_dependents(tmp_path: Path) -> None:
    runtime = _SemanticRuntime(live_game_ids=(), typed_zero_foundations=True)
    request, _store, _runtime, executor = _executor(tmp_path, runtime=runtime)

    evidence = await executor(request)

    update = tuple(
        dispatch
        for dispatch in evidence.planning_generation_manifest.sealed_dispatches
        if dispatch.phase is PlanningDispatchPhase.UPDATE
    )
    endpoints = {dispatch.endpoint_name for dispatch in update}
    assert {"live_score_board", "cume_stats_player_games", "cume_stats_team_games"} <= endpoints
    assert {
        "live_odds",
        "live_play_by_play",
        "live_box_score",
        "cume_stats_player",
        "cume_stats_team",
    }.isdisjoint(endpoints)
    assert any(
        member.typed_zero_reason_code is not None
        for member in evidence.planning_generation_manifest.members
    )


async def test_crash_resume_uses_store_semantics_without_repeating_committed_calls(
    tmp_path: Path,
) -> None:
    first_runtime = _SemanticRuntime(fail_seal_wave_once=0)
    request, store, _runtime, first = _executor(tmp_path, runtime=first_runtime)
    with pytest.raises(RuntimeError, match="seal-wave-0"):
        await first(request)
    committed = store.load_and_verify(
        request,
        deterministic_planning_generation_id(request),
        budget=_BudgetFactory()(),
    ).committed_calls
    assert committed

    resumed_runtime = _SemanticRuntime(fail_seal_wave_once=1)
    _request_again, _store_again, _runtime_again, resumed = _executor(
        tmp_path,
        runtime=resumed_runtime,
        store=store,
    )
    with pytest.raises(RuntimeError, match="seal-wave-1"):
        await resumed(request)
    assert resumed_runtime.call_requests
    assert all(call.wave_index == 1 for call in resumed_runtime.call_requests)


async def test_output_database_schema_drift_fails_before_store_commit(tmp_path: Path) -> None:
    runtime = _SemanticRuntime(forge_output_schema=True)
    request, store, _runtime, executor = _executor(tmp_path, runtime=runtime)

    with pytest.raises(PlanningProgramDriverError, match="schema differs"):
        await executor(request)

    snapshot = store.load_and_verify(
        request,
        deterministic_planning_generation_id(request),
        budget=_BudgetFactory()(),
    )
    assert snapshot.committed_calls == ()


async def test_member_envelope_drift_fails_before_store_commit(tmp_path: Path) -> None:
    runtime = _SemanticRuntime(forge_envelope_generation=True)
    request, store, _runtime, executor = _executor(tmp_path, runtime=runtime)

    with pytest.raises(PlanningProgramDriverError, match="differs from request"):
        await executor(request)

    snapshot = store.load_and_verify(
        request,
        deterministic_planning_generation_id(request),
        budget=_BudgetFactory()(),
    )
    assert snapshot.committed_calls == ()


def test_member_envelope_schema_v2_is_semantic_only_and_canonical() -> None:
    request = _request(SuccessorUpdateMode.DAILY)
    scope = next(
        scope
        for scope in request.requested_planning_scopes
        if scope.endpoint_name == "live_score_board"
    )
    connection = duckdb.connect(":memory:")
    install_successor_planning_semantic_schema(connection)
    with successor_planning_semantic_write_transaction(connection) as transaction:
        descriptor = write_successor_planning_semantic_partition(
            transaction,
            producing_scope=scope,
            semantic_kind=PlanningSemanticKind.ACTIVE_LIVE_GAME_IDS,
            partition={"as_of_utc": request.as_of_utc},
            values=[],
            typed_zero_reason_code="provider_success_empty",
        )
    connection.close()
    envelope = PlanningMemberEnvelope(
        planning_request_sha256=request.identity_sha256,
        planning_generation_id="successor-planning-v2-test",
        wave_index=0,
        producing_scope=scope,
        input_planning_database_sha256=None,
        output_planning_database_sha256=_digest("database"),
        logical_call_receipt_sha256=_digest("receipt"),
        provider_authority_sha256=(
            staging_route_contract_bundle().by_route_id[scope.route_id].provider_authority_sha256
        ),
        member_id="semantic-member",
        semantic=descriptor,
    )

    assert PlanningMemberEnvelope.schema_version == 2
    assert PlanningMemberEnvelope.from_canonical_bytes(envelope.canonical_bytes) == envelope
    assert not {
        "ordered_values",
        "derived_programs",
        "cume_workloads",
        "observed_row_count",
        "member_kind",
    }.intersection(envelope.to_dict())
    with pytest.raises(PlanningProgramDriverError, match="not canonical"):
        PlanningMemberEnvelope.from_canonical_bytes(b" " + envelope.canonical_bytes)


async def test_engine_open_file_swap_back_is_rejected_before_semantic_use(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    first_runtime = _SemanticRuntime(fail_seal_wave_once=0)
    request, store, _runtime, first = _executor(tmp_path, runtime=first_runtime)
    with pytest.raises(RuntimeError, match="seal-wave-0"):
        await first(request)
    original = planning_driver_module._connect_planning_database_read_only

    def swap_then_connect(path: Path):
        saved = path.with_name("planning-original.saved")
        foreign = path.with_name("planning-foreign.duckdb")
        shutil.copyfile(path, foreign)
        foreign.chmod(0o600)
        foreign_connection = duckdb.connect(str(foreign))
        try:
            foreign_connection.execute("CREATE TABLE foreign_marker(value VARCHAR)")
            foreign_connection.execute("INSERT INTO foreign_marker VALUES ('foreign')")
            foreign_connection.execute("CHECKPOINT")
        finally:
            foreign_connection.close()
        foreign.chmod(0o600)
        os.replace(path, saved)
        os.replace(foreign, path)
        try:
            connection = original(path)
        finally:
            os.replace(path, foreign)
            os.replace(saved, path)
        return connection

    monkeypatch.setattr(
        planning_driver_module,
        "_connect_planning_database_read_only",
        swap_then_connect,
    )
    runtime = _SemanticRuntime()
    _again, _store, _runtime, resumed = _executor(tmp_path, runtime=runtime, store=store)

    with pytest.raises(
        PlanningProgramDriverError,
        match="did not open exactly the held planning database inode",
    ):
        await resumed(request)
    assert runtime.call_requests == []


async def test_engine_open_ancestor_swap_back_is_rejected_before_semantic_use(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    first_runtime = _SemanticRuntime(fail_seal_wave_once=0)
    request, store, _runtime, first = _executor(tmp_path, runtime=first_runtime)
    with pytest.raises(RuntimeError, match="seal-wave-0"):
        await first(request)
    original = planning_driver_module._connect_planning_database_read_only

    def swap_parent_then_connect(path: Path):
        parent = path.parent
        saved = parent.with_name(parent.name + "-saved")
        foreign = parent.with_name(parent.name + "-foreign")
        foreign.mkdir(mode=0o700)
        shutil.copyfile(path, foreign / path.name)
        (foreign / path.name).chmod(0o600)
        foreign_connection = duckdb.connect(str(foreign / path.name))
        try:
            foreign_connection.execute("CREATE TABLE foreign_marker(value VARCHAR)")
            foreign_connection.execute("INSERT INTO foreign_marker VALUES ('foreign')")
            foreign_connection.execute("CHECKPOINT")
        finally:
            foreign_connection.close()
        (foreign / path.name).chmod(0o600)
        os.replace(parent, saved)
        os.replace(foreign, parent)
        try:
            connection = original(parent / path.name)
        finally:
            os.replace(parent, foreign)
            os.replace(saved, parent)
        return connection

    monkeypatch.setattr(
        planning_driver_module,
        "_connect_planning_database_read_only",
        swap_parent_then_connect,
    )
    runtime = _SemanticRuntime()
    _again, _store, _runtime, resumed = _executor(tmp_path, runtime=runtime, store=store)

    with pytest.raises(
        PlanningProgramDriverError,
        match="did not open exactly the held planning database inode",
    ):
        await resumed(request)
    assert runtime.call_requests == []


async def test_caller_shared_lock_cannot_mask_foreign_engine_inode(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    first_runtime = _SemanticRuntime(fail_seal_wave_once=0)
    request, store, _runtime, first = _executor(tmp_path, runtime=first_runtime)
    with pytest.raises(RuntimeError, match="seal-wave-0"):
        await first(request)
    original_hold = planning_driver_module._hold_private_regular_file
    original_connect = planning_driver_module._connect_planning_database_read_only
    connect_called = False

    @contextmanager
    def hold_with_attacker_shared_lock(*, private_work_root: Path, path: Path):
        with original_hold(private_work_root=private_work_root, path=path) as held:
            attacker = os.open(path, os.O_RDONLY)
            try:
                fcntl.flock(attacker, fcntl.LOCK_SH | fcntl.LOCK_NB)
                yield held
            finally:
                fcntl.flock(attacker, fcntl.LOCK_UN)
                os.close(attacker)

    def must_not_connect(path: Path):
        nonlocal connect_called
        connect_called = True
        return original_connect(path)

    monkeypatch.setattr(
        planning_driver_module,
        "_hold_private_regular_file",
        hold_with_attacker_shared_lock,
    )
    monkeypatch.setattr(
        planning_driver_module,
        "_connect_planning_database_read_only",
        must_not_connect,
    )
    runtime = _SemanticRuntime()
    _again, _store, _runtime, resumed = _executor(tmp_path, runtime=runtime, store=store)

    with pytest.raises(PlanningProgramDriverError, match="exclusive preflight"):
        await resumed(request)
    assert connect_called is False
    assert runtime.call_requests == []


@pytest.mark.skipif(platform.system() != "Linux", reason="Linux record-lock contract")
def test_linux_real_duckdb_engine_fd_and_record_lock_are_accepted(tmp_path: Path) -> None:
    root = tmp_path / "binding-root"
    root.mkdir(mode=0o700)
    database_path = root / "planning.duckdb"
    connection = duckdb.connect(str(database_path))
    request = _request(SuccessorUpdateMode.DAILY)
    scope = next(
        scope
        for scope in request.requested_planning_scopes
        if scope.endpoint_name == "live_score_board"
    )
    try:
        install_successor_planning_semantic_schema(connection)
        with successor_planning_semantic_write_transaction(connection) as transaction:
            descriptor = write_successor_planning_semantic_partition(
                transaction,
                producing_scope=scope,
                semantic_kind=PlanningSemanticKind.ACTIVE_LIVE_GAME_IDS,
                partition={"as_of_utc": request.as_of_utc},
                values=[{"game_id": "0022500001"}],
                typed_zero_reason_code=None,
            )
        connection.execute("CHECKPOINT")
    finally:
        connection.close()
    database_path.chmod(0o600)
    source = _database_source(database_path)
    member = PlanningDataMember(
        member_id="linux-real-engine-member",
        wave_index=0,
        producing_scope_sha256=scope.identity_sha256,
        schema_sha256=PlanningMemberEnvelope.schema_sha256,
        content_sha256=_digest("linux-real-engine-envelope"),
        row_count=descriptor.value_count,
        semantic=descriptor,
        typed_zero_reason_code=descriptor.typed_zero_reason_code,
    )
    authority = PlanningSemanticMemberAuthority(
        member=member,
        producing_scope=scope,
        logical_call_receipt_sha256=_digest("linux-real-engine-receipt"),
        provider_authority_sha256=(
            staging_route_contract_bundle().by_route_id[scope.route_id].provider_authority_sha256
        ),
    )

    with planning_driver_module._bound_semantic_registry(
        source=source,
        private_work_root=root,
        authorities=(authority,),
    ) as registry:
        assert len(registry) == 1
        assert registry[0].authority == authority
        assert registry[0].values == ({"game_id": "0022500001"},)


async def test_sealed_verify_never_invokes_runtime(tmp_path: Path) -> None:
    request, store, _runtime, executor = _executor(tmp_path)
    evidence = await executor(request)
    verifying_runtime = _SemanticRuntime(fail_call_once=True, fail_seal_wave_once=0)
    planning_work_root = (tmp_path / "verify-work").resolve()
    planning_work_root.mkdir(mode=0o700)
    planning_work_stat = planning_work_root.stat()
    verifier = ConcreteSuccessorPlanningExecutor(
        store,
        RequestDrivenSuccessorPlanningDriver(verifying_runtime),
        _Resolver(),
        _BudgetFactory(),
        10_000_000,
        planning_work_root,
        (planning_work_stat.st_dev, planning_work_stat.st_ino),
    )

    assert verifier.verify(request, evidence) == evidence
    assert verifying_runtime.call_requests == []
    assert verifying_runtime.seal_requests == []
