from __future__ import annotations

import hashlib
import json
import os
import shutil
import stat
import subprocess
import sys
import threading
from dataclasses import dataclass, fields, replace
from pathlib import PurePath
from types import SimpleNamespace
from typing import TYPE_CHECKING, Any, cast

import pytest

if TYPE_CHECKING:
    from pathlib import Path

from nbadb.extract.bronze import LogicalCallReceiptBinding
from nbadb.orchestrate.capture_session import CaptureRunScope, PrivateGenerationIdentity
from nbadb.orchestrate.successor_planning_contract import SuccessorPlanningRequest
from nbadb.orchestrate.successor_planning_generation_contract import (
    PlanningDataMember,
    PlanningDispatchPhase,
    PlanningGenerationManifest,
    SealedProviderDispatch,
    SuccessorPlanningArtifactIdentity,
    SuccessorPlanningWave,
    canonical_planning_json_bytes,
    canonical_planning_sha256,
)
from nbadb.orchestrate.successor_planning_semantic_contract import (
    PlanningSemanticDescriptor,
    PlanningSemanticKind,
)
from nbadb.orchestrate.successor_planning_store import (
    PlanningArtifactSource,
    PlanningDatabaseSource,
    PlanningGenerationPhase,
    PlanningMemberSource,
    PlanningStoreBudget,
    PlanningWaveAdmission,
    SuccessorPlanningStore,
    SuccessorPlanningStoreError,
)
from nbadb.orchestrate.successor_planning_wave_receipt import (
    PlanningWaveCallBinding,
    PlanningWaveCompletionReceipt,
    PlanningWaveMemberBinding,
)
from nbadb.orchestrate.successor_update_contract import (
    CallMutability,
    RequestedRouteScope,
    SuccessorUpdateMode,
)


def _sha256(encoded: bytes) -> str:
    return hashlib.sha256(encoded).hexdigest()


def _write_source(path: Path, encoded: bytes) -> PlanningArtifactSource:
    path.write_bytes(encoded)
    path.chmod(0o600)
    return PlanningArtifactSource(
        path=path.resolve(), sha256=_sha256(encoded), byte_count=len(encoded)
    )


def _scope(
    marker: str,
    *,
    endpoint: str,
    route: str,
    parameters: dict[str, Any],
) -> RequestedRouteScope:
    return RequestedRouteScope.from_parameters(
        endpoint_name=endpoint,
        route_id=route,
        route_contract_sha256=marker * 64,
        parameters=parameters,
        mutability=CallMutability.MUTABLE,
    )


def _dispatch(
    scopes: tuple[RequestedRouteScope, ...],
    *,
    wave_index: int,
    dependency_identity_sha256s: tuple[str, ...] = (),
    pattern: str | None = None,
) -> SealedProviderDispatch:
    first = scopes[0]
    assert all(
        scope.endpoint_name == first.endpoint_name and scope.parameters == first.parameters
        for scope in scopes
    )
    return SealedProviderDispatch.from_parameters(
        phase=(
            PlanningDispatchPhase.PLANNING_WAVE_0
            if wave_index == 0
            else PlanningDispatchPhase.PLANNING_WAVE_1
        ),
        endpoint_name=first.endpoint_name,
        requested_scope_identity_sha256s=tuple(scope.identity_sha256 for scope in scopes),
        parameters=first.parameters,
        pattern=pattern or first.endpoint_name,
        staging_route_ids=tuple(scope.route_id for scope in scopes),
        dependency_identity_sha256s=dependency_identity_sha256s,
    )


def _admission(
    scopes: tuple[RequestedRouteScope, ...],
    *,
    wave_index: int,
    parent_wave_identity_sha256: str | None = None,
    dispatches: tuple[SealedProviderDispatch, ...] | None = None,
) -> PlanningWaveAdmission:
    canonical_scopes = tuple(sorted(scopes, key=lambda scope: scope.identity_sha256))
    return PlanningWaveAdmission(
        wave_index=wave_index,
        parent_wave_identity_sha256=parent_wave_identity_sha256,
        requested_route_scopes=canonical_scopes,
        sealed_dispatches=dispatches
        if dispatches is not None
        else (
            _dispatch(
                scopes,
                wave_index=wave_index,
                dependency_identity_sha256s=(() if wave_index == 0 else ("f" * 64,)),
            ),
        ),
    )


def _budget(**overrides: int | float) -> PlanningStoreBudget:
    values: dict[str, int | float] = {
        "generation_max_bytes": 16 * 1024 * 1024,
        "artifact_max_bytes": 4 * 1024 * 1024,
        "control_max_bytes": 2 * 1024 * 1024,
        "minimum_free_bytes": 1,
        "monotonic_deadline_seconds": 1_000.0,
        "minimum_deadline_headroom_seconds": 100.0,
    }
    values.update(overrides)
    return PlanningStoreBudget(**values)  # type: ignore[arg-type]


def _logical_bindings_sha256(bindings: tuple[LogicalCallReceiptBinding, ...]) -> str:
    return _sha256(
        canonical_planning_json_bytes(
            [
                {
                    "endpoint_name": binding.endpoint_name,
                    "logical_call_receipt_sha256": binding.logical_call_receipt_sha256,
                    "logical_parameters_sha256": binding.logical_parameters_sha256,
                    "provider_authority_sha256": binding.provider_authority_sha256,
                    "result_route_ids": list(binding.result_route_ids),
                }
                for binding in bindings
            ]
        )
    )


def _wave_authority(
    store: SuccessorPlanningStore,
    request: SuccessorPlanningRequest,
    generation_id: str,
    *,
    wave_index: int,
    admission: PlanningWaveAdmission,
    planning_database: PlanningDatabaseSource,
    budget: PlanningStoreBudget,
    parent_wave_identity_sha256: str | None = None,
) -> tuple[SuccessorPlanningWave, PrivateGenerationIdentity, PlanningWaveCompletionReceipt]:
    snapshot = store.load_and_verify(request, generation_id, budget=budget)
    calls = tuple(call for call in snapshot.committed_calls if call.wave_index == wave_index)
    provider = _sha256(f"provider-wave-{wave_index}".encode())
    logical_bindings = tuple(
        sorted(
            (
                LogicalCallReceiptBinding(
                    logical_call_receipt_sha256=call.members[0].receipt_sha256,
                    endpoint_name=call.sealed_dispatch.endpoint_name,
                    logical_parameters_sha256=call.sealed_dispatch.parameters_sha256,
                    provider_authority_sha256=provider,
                    result_route_ids=tuple(sorted(call.sealed_dispatch.staging_route_ids)),
                )
                for call in calls
            ),
            key=lambda item: item.logical_call_receipt_sha256,
        )
    )
    private = PrivateGenerationIdentity(
        manifest_sha256=_sha256(f"bronze-manifest-{wave_index}".encode()),
        provider_authority_sha256=provider,
        semantic_source_sha=request.source_sha,
        chain_id="planning-test-chain",
        lane_id=f"planning-wave-{wave_index}",
        workflow_run_id=request.workflow_run_id,
        workflow_run_attempt=request.workflow_run_attempt,
        artifact_count=max(1, len(calls) * 3),
        done_call_count=len(calls),
        done_call_receipt_sha256s=tuple(
            sorted(binding.logical_call_receipt_sha256 for binding in logical_bindings)
        ),
        done_call_bindings_sha256=_logical_bindings_sha256(logical_bindings),
        done_attempt_count=len(calls),
        done_blob_count=sum(len(call.members) for call in calls),
        orphan_call_count=0,
        orphan_attempt_count=0,
        orphan_blob_count=0,
        stored_bytes=4096,
    )
    committed_calls = tuple(
        PlanningWaveCallBinding(
            ordinal=ordinal,
            sealed_dispatch_identity_sha256=call.sealed_dispatch.identity_sha256,
            committed_call_identity_sha256=call.identity_sha256,
            logical_call_receipt_sha256=call.members[0].receipt_sha256,
            member_identity_sha256s=tuple(member.member.identity_sha256 for member in call.members),
        )
        for ordinal, call in enumerate(calls)
    )
    members = tuple(
        PlanningWaveMemberBinding(
            member=member.member,
            logical_call_receipt_sha256=member.receipt_sha256,
        )
        for member in sorted(
            (member for call in calls for member in call.members),
            key=lambda item: item.member.identity_sha256,
        )
    )
    receipt = PlanningWaveCompletionReceipt(
        planning_request_sha256=request.identity_sha256,
        planning_generation_id=generation_id,
        wave_index=wave_index,
        parent_wave_identity_sha256=parent_wave_identity_sha256,
        wave_admission_identity_sha256=admission.identity_sha256,
        sealed_dispatch_identity_sha256s=tuple(
            dispatch.identity_sha256 for dispatch in admission.sealed_dispatches
        ),
        committed_calls=committed_calls,
        requested_scope_identity_sha256s=admission.requested_scope_identity_sha256s,
        completed_scope_identity_sha256s=admission.requested_scope_identity_sha256s,
        members=members,
        logical_call_bindings=logical_bindings,
        capture_scope=CaptureRunScope(
            semantic_source_sha=request.source_sha,
            chain_id=private.chain_id,
            lane_id=private.lane_id,
            workflow_run_id=private.workflow_run_id,
            workflow_run_attempt=private.workflow_run_attempt,
        ),
        private_generation_identity=private,
        planning_database_sha256=planning_database.artifact.sha256,
        planning_database_bytes=planning_database.artifact.byte_count,
        planning_database_schema_sha256=planning_database.schema_sha256,
    )
    wave_members = tuple(member.member for member in members)
    wave = SuccessorPlanningWave(
        wave_index=wave_index,
        parent_wave_identity_sha256=parent_wave_identity_sha256,
        requested_scope_identity_sha256s=admission.requested_scope_identity_sha256s,
        completed_scope_identity_sha256s=admission.requested_scope_identity_sha256s,
        member_identity_sha256s=tuple(member.identity_sha256 for member in wave_members),
        member_receipt_sha256s=tuple(member.logical_call_receipt_sha256 for member in members),
        private_generation_identity_sha256=_sha256(private.canonical_bytes),
        completion_receipt_sha256=_sha256(receipt.canonical_bytes),
    )
    return wave, private, receipt


@dataclass(slots=True)
class _Harness:
    store: SuccessorPlanningStore
    public_root: Path
    sources_root: Path
    request: SuccessorPlanningRequest
    generation_id: str
    budget: PlanningStoreBudget
    wave_0_scope: RequestedRouteScope
    wave_1_scope: RequestedRouteScope
    wave_0_dispatch: SealedProviderDispatch
    wave_1_dispatch: SealedProviderDispatch
    wave_0_member_source: PlanningMemberSource
    wave_1_member_source: PlanningMemberSource
    wave_0_database: PlanningDatabaseSource
    wave_1_database: PlanningDatabaseSource
    wave_0: SuccessorPlanningWave
    wave_1: SuccessorPlanningWave
    wave_0_private_generation_identity: PrivateGenerationIdentity
    wave_1_private_generation_identity: PrivateGenerationIdentity
    wave_0_completion_receipt: PlanningWaveCompletionReceipt
    wave_1_completion_receipt: PlanningWaveCompletionReceipt

    def manifest(self) -> PlanningGenerationManifest:
        members = tuple(
            sorted(
                (self.wave_0_member_source.member, self.wave_1_member_source.member),
                key=lambda item: item.identity_sha256,
            )
        )
        dispatches = (
            self.wave_0_dispatch,
            self.wave_1_dispatch,
            SealedProviderDispatch.from_parameters(
                phase=PlanningDispatchPhase.UPDATE,
                endpoint_name=self.wave_0_scope.endpoint_name,
                requested_scope_identity_sha256s=(self.wave_0_scope.identity_sha256,),
                parameters=self.wave_0_scope.parameters,
                pattern="scoreboard_v3",
                staging_route_ids=(self.wave_0_scope.route_id,),
                dependency_identity_sha256s=(self.wave_0_member_source.member.identity_sha256,),
            ),
            SealedProviderDispatch.from_parameters(
                phase=PlanningDispatchPhase.UPDATE,
                endpoint_name=self.wave_1_scope.endpoint_name,
                requested_scope_identity_sha256s=(self.wave_1_scope.identity_sha256,),
                parameters=self.wave_1_scope.parameters,
                pattern="cume_stats_player_games",
                staging_route_ids=(self.wave_1_scope.route_id,),
                dependency_identity_sha256s=(self.wave_1_member_source.member.identity_sha256,),
            ),
        )
        scopes = tuple(
            sorted(
                (self.wave_0_scope, self.wave_1_scope),
                key=lambda item: item.identity_sha256,
            )
        )
        artifact_identity = SuccessorPlanningArtifactIdentity(
            planning_request_sha256=self.request.identity_sha256,
            planning_generation_id=self.generation_id,
            planning_database_sha256=self.wave_1_database.artifact.sha256,
            planning_database_bytes=self.wave_1_database.artifact.byte_count,
            planning_database_schema_sha256=self.wave_1_database.schema_sha256,
            member_inventory_sha256=canonical_planning_sha256(
                [member.to_dict() for member in members]
            ),
            private_generation_identity_sha256=canonical_planning_sha256(
                [
                    self.wave_0.private_generation_identity_sha256,
                    self.wave_1.private_generation_identity_sha256,
                ]
            ),
            wave_inventory_sha256=canonical_planning_sha256(
                [self.wave_0.to_dict(), self.wave_1.to_dict()]
            ),
            planning_manifest_sha256="0" * 64,
            sealed_dispatch_inventory_sha256=canonical_planning_sha256(
                [dispatch.to_dict() for dispatch in dispatches]
            ),
        )
        return PlanningGenerationManifest.seal(
            request=self.request,
            artifact_identity=artifact_identity,
            waves=(self.wave_0, self.wave_1),
            members=members,
            requested_route_scopes=scopes,
            sealed_dispatches=dispatches,
        )


def _new_harness(tmp_path: Path, *, shared_wave_0_bytes: bool = False) -> _Harness:
    tmp_path.mkdir(parents=True, exist_ok=True)
    public_root = tmp_path / "public"
    public_root.mkdir()
    (public_root / "dataset.duckdb").write_bytes(b"public")
    sources = tmp_path / "private-sources"
    sources.mkdir(mode=0o700)
    store = SuccessorPlanningStore(
        (tmp_path / "private-planning").resolve(),
        public_roots=(public_root.resolve(),),
        monotonic_clock=lambda: 100.0,
    )
    wave_0_scope = _scope(
        "1",
        endpoint="scoreboard_v3",
        route="scoreboard_v3:stg_scoreboard_games",
        parameters={"game_date": "2026-08-01", "league_id": "00"},
    )
    wave_1_scope = _scope(
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
        baseline_identity_sha256="a" * 64,
        mode=SuccessorUpdateMode.DAILY,
        source_sha="b" * 40,
        cutoff_utc="2026-08-01T00:00:00Z",
        as_of_utc="2026-08-02T00:00:00Z",
        workflow_run_id=17,
        workflow_run_attempt=1,
        requested_planning_scopes=(wave_0_scope,),
    )
    generation_id = "planning-generation-0001"
    budget = _budget()
    store.begin_generation(request, generation_id, budget=budget)
    wave_0_dispatch = _dispatch(
        (wave_0_scope,),
        wave_index=0,
        pattern="scoreboard_v3",
    )
    wave_0_admission = _admission(
        (wave_0_scope,),
        wave_index=0,
        dispatches=(wave_0_dispatch,),
    )
    store.begin_wave(
        request,
        generation_id,
        admission=wave_0_admission,
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
    wave_0_database_artifact = _write_source(
        sources / "planning-wave-0.duckdb",
        b"[]" if shared_wave_0_bytes else b"DUCKDB-WAVE-0",
    )
    wave_0_database = PlanningDatabaseSource(
        artifact=wave_0_database_artifact,
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
    store.begin_wave(
        request,
        generation_id,
        admission=wave_1_admission,
        budget=budget,
    )

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
    return _Harness(
        store=store,
        public_root=public_root,
        sources_root=sources,
        request=request,
        generation_id=generation_id,
        budget=budget,
        wave_0_scope=wave_0_scope,
        wave_1_scope=wave_1_scope,
        wave_0_dispatch=wave_0_dispatch,
        wave_1_dispatch=wave_1_dispatch,
        wave_0_member_source=wave_0_member_source,
        wave_1_member_source=wave_1_member_source,
        wave_0_database=wave_0_database,
        wave_1_database=wave_1_database,
        wave_0=wave_0,
        wave_1=wave_1,
        wave_0_private_generation_identity=wave_0_private,
        wave_1_private_generation_identity=wave_1_private,
        wave_0_completion_receipt=wave_0_receipt,
        wave_1_completion_receipt=wave_1_receipt,
    )


def _seal(harness: _Harness) -> PlanningGenerationManifest:
    manifest = harness.manifest()
    snapshot = harness.store.seal_generation(
        harness.request,
        harness.generation_id,
        manifest=manifest,
        budget=harness.budget,
    )
    assert snapshot.phase is PlanningGenerationPhase.SEALED
    return manifest


def _checkpoint_path(harness: _Harness) -> Path:
    return harness.store.generation_path(harness.request, harness.generation_id) / "checkpoint.json"


def _expected_generation_logical_bytes(harness: _Harness) -> int:
    generation = harness.store.generation_path(harness.request, harness.generation_id)
    checkpoint_bytes = (generation / "checkpoint.json").read_bytes()
    checkpoint = json.loads(checkpoint_bytes)
    references: dict[tuple[str, str], int] = {}

    def add(raw: object) -> None:
        if raw is None:
            return
        assert isinstance(raw, dict)
        artifact = cast("dict[str, object]", raw)
        raw_bytes = artifact["bytes"]
        assert type(raw_bytes) is int
        references[(str(artifact["kind"]), str(artifact["sha256"]))] = raw_bytes

    for call in checkpoint["committed_calls"]:
        for member in call["members"]:
            add(member["artifact"])
        add(call["database"]["artifact"])
    for wave in checkpoint["committed_waves"]:
        add(wave["artifact"])
        add(wave["database"]["artifact"])
        add(wave["private_generation_identity"])
        add(wave["completion_receipt"])
    for field_name in (
        "member_inventory",
        "wave_inventory",
        "sealed_dispatch_inventory",
    ):
        add(checkpoint[field_name])
    if checkpoint["manifest"] is not None:
        add(checkpoint["manifest"]["artifact"])
    manifest = generation / "planning-generation-manifest.json"
    return (
        (generation / "request.json").stat().st_size
        + len(checkpoint_bytes)
        + (manifest.stat().st_size if manifest.exists() else 0)
        + sum(references.values())
    )


def _planning_root_descriptor(root: Path) -> int:
    return os.open(
        root,
        os.O_RDONLY | getattr(os, "O_DIRECTORY", 0) | getattr(os, "O_NOFOLLOW", 0),
    )


def _rewrite_checkpoint(path: Path, payload: dict[str, object]) -> None:
    path.write_bytes(canonical_planning_json_bytes(payload))


def _rewind_to_wave_0_committed(harness: _Harness) -> None:
    checkpoint = json.loads(_checkpoint_path(harness).read_text())
    checkpoint["phase"] = PlanningGenerationPhase.WAVE_0_COMMITTED.value
    checkpoint["revision"] = 3
    checkpoint["active_wave"] = None
    checkpoint["committed_calls"] = checkpoint["committed_calls"][:1]
    checkpoint["committed_waves"] = checkpoint["committed_waves"][:1]
    checkpoint["current_database"] = checkpoint["committed_calls"][0]["database"]
    _rewrite_checkpoint(_checkpoint_path(harness), checkpoint)


def _new_unstarted_wave_0(
    tmp_path: Path,
) -> tuple[
    SuccessorPlanningStore,
    SuccessorPlanningRequest,
    RequestedRouteScope,
    PlanningStoreBudget,
    Path,
]:
    public = tmp_path / "public"
    public.mkdir()
    sources = tmp_path / "sources"
    sources.mkdir(mode=0o700)
    scope = _scope(
        "1",
        endpoint="scoreboard_v3",
        route="scoreboard_v3:stg_scoreboard_games",
        parameters={"game_date": "2026-08-01", "league_id": "00"},
    )
    request = SuccessorPlanningRequest(
        baseline_identity_sha256="a" * 64,
        mode=SuccessorUpdateMode.DAILY,
        source_sha="b" * 40,
        cutoff_utc="2026-08-01T00:00:00Z",
        as_of_utc="2026-08-02T00:00:00Z",
        workflow_run_id=17,
        workflow_run_attempt=1,
        requested_planning_scopes=(scope,),
    )
    store = SuccessorPlanningStore(
        (tmp_path / "private").resolve(),
        public_roots=(public.resolve(),),
        monotonic_clock=lambda: 100.0,
    )
    budget = _budget()
    store.begin_generation(request, "generation", budget=budget)
    return store, request, scope, budget, sources


def test_wave_admission_crash_is_atomic_and_exact_rebegin_is_idempotent(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store, request, scope, budget, _sources = _new_unstarted_wave_0(tmp_path)
    admission = _admission((scope,), wave_index=0)
    original = store._commit_checkpoint
    monkeypatch.setattr(
        store,
        "_commit_checkpoint",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(RuntimeError("admission crash")),
    )

    with pytest.raises(RuntimeError, match="admission crash"):
        store.begin_wave(
            request,
            "generation",
            admission=admission,
            budget=budget,
        )
    assert store.load_and_verify(request, "generation", budget=budget).active_wave is None

    monkeypatch.setattr(store, "_commit_checkpoint", original)
    admitted = store.begin_wave(
        request,
        "generation",
        admission=admission,
        budget=budget,
    )
    resumed = store.begin_wave(
        request,
        "generation",
        admission=admission,
        budget=budget,
    )
    assert admitted.active_wave == admission
    assert resumed.revision == admitted.revision == 1
    assert resumed.active_wave is not None
    assert resumed.active_wave.identity_sha256 == admission.identity_sha256


def test_wave_admission_rejects_order_scope_drift_and_checkpoint_tamper(
    tmp_path: Path,
) -> None:
    store, request, scope, budget, _sources = _new_unstarted_wave_0(tmp_path)
    drift_scope = _scope(
        "e",
        endpoint=scope.endpoint_name,
        route=scope.route_id,
        parameters={"game_date": "2026-08-03", "league_id": "00"},
    )
    with pytest.raises(SuccessorPlanningStoreError, match="cannot begin"):
        store.begin_wave(
            request,
            "generation",
            admission=_admission(
                (scope,),
                wave_index=1,
                parent_wave_identity_sha256="f" * 64,
            ),
            budget=budget,
        )
    with pytest.raises(SuccessorPlanningStoreError, match="differ from the exact planning"):
        store.begin_wave(
            request,
            "generation",
            admission=_admission((drift_scope,), wave_index=0),
            budget=budget,
        )

    admission = _admission((scope,), wave_index=0)
    store.begin_wave(request, "generation", admission=admission, budget=budget)
    with pytest.raises(SuccessorPlanningStoreError, match="active planning wave differs"):
        store.begin_wave(
            request,
            "generation",
            admission=_admission((drift_scope,), wave_index=0),
            budget=budget,
        )

    checkpoint_path = store.generation_path(request, "generation") / "checkpoint.json"
    checkpoint = json.loads(checkpoint_path.read_text())
    checkpoint["active_wave"]["identity_sha256"] = "0" * 64
    _rewrite_checkpoint(checkpoint_path, checkpoint)
    with pytest.raises(SuccessorPlanningStoreError, match="admission identity differs"):
        store.load_and_verify(request, "generation", budget=budget)


def test_wave_admission_v2_retains_plural_dependencies_and_rejects_old_shapes() -> None:
    scope = _scope(
        "1",
        endpoint="cume_stats_player_games",
        route="cume_stats_player_games:stg_cume_player_games",
        parameters={
            "player_id": 2544,
            "season": "2025-26",
            "season_type": "Regular Season",
        },
    )
    dependencies = ("1" * 64, "2" * 64)
    admission = _admission(
        (scope,),
        wave_index=1,
        parent_wave_identity_sha256="a" * 64,
        dispatches=(
            _dispatch(
                (scope,),
                wave_index=1,
                dependency_identity_sha256s=dependencies,
            ),
        ),
    )

    restored = PlanningWaveAdmission.from_dict(admission.to_dict())
    assert restored.sealed_dispatches[0].dependency_identity_sha256s == dependencies

    old_schema = admission.to_dict()
    old_schema["schema_version"] = 1
    with pytest.raises(SuccessorPlanningStoreError, match="schema"):
        PlanningWaveAdmission.from_dict(old_schema)

    scalar_shape = admission.to_dict()
    scalar_dispatches = scalar_shape["sealed_dispatches"]
    assert isinstance(scalar_dispatches, list)
    scalar_dispatch = scalar_dispatches[0]
    assert isinstance(scalar_dispatch, dict)
    scalar_dispatch["dependency_identity_sha256"] = scalar_dispatch.pop(
        "dependency_identity_sha256s"
    )[0]
    with pytest.raises(SuccessorPlanningStoreError, match="nested authority"):
        PlanningWaveAdmission.from_dict(scalar_shape)

    reordered = admission.to_dict()
    reordered_dispatches = reordered["sealed_dispatches"]
    assert isinstance(reordered_dispatches, list)
    reordered_dispatch = reordered_dispatches[0]
    assert isinstance(reordered_dispatch, dict)
    reordered_dispatch["dependency_identity_sha256s"] = list(reversed(dependencies))
    with pytest.raises(SuccessorPlanningStoreError, match="nested authority"):
        PlanningWaveAdmission.from_dict(reordered)


def test_calls_and_wave_commit_require_exact_active_admission(tmp_path: Path) -> None:
    store, request, scope, budget, sources = _new_unstarted_wave_0(tmp_path)
    drift_scope = _scope(
        "e",
        endpoint=scope.endpoint_name,
        route=scope.route_id,
        parameters={"game_date": "2026-08-03", "league_id": "00"},
    )
    artifact = _write_source(sources / "live-game-ids.json", b"[]")
    database = PlanningDatabaseSource(
        artifact=_write_source(sources / "planning.duckdb", b"DB"),
        schema_sha256="5" * 64,
    )

    def member_source(producing_scope_sha256: str) -> PlanningMemberSource:
        return PlanningMemberSource(
            member=PlanningDataMember(
                member_id="live_game_ids",
                wave_index=0,
                producing_scope_sha256=producing_scope_sha256,
                schema_sha256="3" * 64,
                content_sha256=artifact.sha256,
                row_count=0,
                semantic=PlanningSemanticDescriptor.from_partition(
                    semantic_kind=PlanningSemanticKind.ACTIVE_LIVE_GAME_IDS,
                    partition={"as_of_utc": request.as_of_utc},
                    semantic_schema_sha256="3" * 64,
                    semantic_content_sha256=artifact.sha256,
                    value_count=0,
                    typed_zero_reason_code="scoreboard_complete_empty",
                ),
                typed_zero_reason_code="scoreboard_complete_empty",
            ),
            receipt_sha256="4" * 64,
            artifact=artifact,
        )

    valid_member = member_source(scope.identity_sha256)
    dispatch = _dispatch((scope,), wave_index=0)
    with pytest.raises(SuccessorPlanningStoreError, match="durable wave admission"):
        store.commit_call(
            request,
            "generation",
            sealed_dispatch_identity_sha256=dispatch.identity_sha256,
            members=(valid_member,),
            planning_database=database,
            budget=budget,
        )

    admission = _admission((scope,), wave_index=0, dispatches=(dispatch,))
    store.begin_wave(request, "generation", admission=admission, budget=budget)
    with pytest.raises(SuccessorPlanningStoreError, match="do not exactly cover"):
        store.commit_call(
            request,
            "generation",
            sealed_dispatch_identity_sha256=dispatch.identity_sha256,
            members=(member_source("e" * 64),),
            planning_database=database,
            budget=budget,
        )
    store.commit_call(
        request,
        "generation",
        sealed_dispatch_identity_sha256=dispatch.identity_sha256,
        members=(valid_member,),
        planning_database=database,
        budget=budget,
    )

    wave, private_identity, completion_receipt = _wave_authority(
        store,
        request,
        "generation",
        wave_index=0,
        admission=admission,
        planning_database=database,
        budget=budget,
    )
    private_domain_sha256 = canonical_planning_sha256(
        {
            "domain": "nbadb.successor-planning-store.object.private_generation_identity.v2",
            "sha256": _sha256(private_identity.canonical_bytes),
            "bytes": len(private_identity.canonical_bytes),
        }
    )
    with pytest.raises(SuccessorPlanningStoreError, match="raw canonical bytes"):
        store.commit_wave(
            request,
            "generation",
            wave=replace(
                wave,
                private_generation_identity_sha256=private_domain_sha256,
            ),
            planning_database=database,
            private_generation_identity=private_identity,
            completion_receipt=completion_receipt,
            budget=budget,
        )

    database_drift_receipt = replace(
        completion_receipt,
        planning_database_schema_sha256="f" * 64,
    )
    with pytest.raises(SuccessorPlanningStoreError, match="planning database differs"):
        store.commit_wave(
            request,
            "generation",
            wave=replace(
                wave,
                completion_receipt_sha256=_sha256(database_drift_receipt.canonical_bytes),
            ),
            planning_database=database,
            private_generation_identity=private_identity,
            completion_receipt=database_drift_receipt,
            budget=budget,
        )

    foreign_root = "a" * 64
    foreign_binding = replace(
        completion_receipt.logical_call_bindings[0],
        logical_call_receipt_sha256=foreign_root,
    )
    foreign_bindings = (foreign_binding,)
    foreign_private = replace(
        private_identity,
        done_call_receipt_sha256s=(foreign_root,),
        done_call_bindings_sha256=_logical_bindings_sha256(foreign_bindings),
    )
    foreign_receipt = replace(
        completion_receipt,
        committed_calls=(
            replace(
                completion_receipt.committed_calls[0],
                logical_call_receipt_sha256=foreign_root,
            ),
        ),
        members=tuple(
            replace(member, logical_call_receipt_sha256=foreign_root)
            for member in completion_receipt.members
        ),
        logical_call_bindings=foreign_bindings,
        private_generation_identity=foreign_private,
    )
    with pytest.raises(SuccessorPlanningStoreError, match="stored member receipts"):
        store.commit_wave(
            request,
            "generation",
            wave=replace(
                wave,
                private_generation_identity_sha256=_sha256(foreign_private.canonical_bytes),
                completion_receipt_sha256=_sha256(foreign_receipt.canonical_bytes),
            ),
            planning_database=database,
            private_generation_identity=foreign_private,
            completion_receipt=foreign_receipt,
            budget=budget,
        )

    foreign_execution_private = replace(
        private_identity,
        workflow_run_id=request.workflow_run_id + 1,
    )
    foreign_execution_receipt = replace(
        completion_receipt,
        capture_scope=replace(
            completion_receipt.capture_scope,
            workflow_run_id=request.workflow_run_id + 1,
        ),
        private_generation_identity=foreign_execution_private,
    )
    with pytest.raises(
        SuccessorPlanningStoreError,
        match="capture execution differs",
    ):
        store.commit_wave(
            request,
            "generation",
            wave=replace(
                wave,
                private_generation_identity_sha256=_sha256(
                    foreign_execution_private.canonical_bytes
                ),
                completion_receipt_sha256=_sha256(foreign_execution_receipt.canonical_bytes),
            ),
            planning_database=database,
            private_generation_identity=foreign_execution_private,
            completion_receipt=foreign_execution_receipt,
            budget=budget,
        )

    with pytest.raises(SuccessorPlanningStoreError, match="differs from its durable admission"):
        store.commit_wave(
            request,
            "generation",
            wave=replace(
                wave,
                requested_scope_identity_sha256s=("e" * 64,),
                completed_scope_identity_sha256s=("e" * 64,),
            ),
            planning_database=database,
            private_generation_identity=private_identity,
            completion_receipt=completion_receipt,
            budget=budget,
        )
    committed = store.commit_wave(
        request,
        "generation",
        wave=wave,
        planning_database=database,
        private_generation_identity=private_identity,
        completion_receipt=completion_receipt,
        budget=budget,
    )
    assert committed.active_wave is None
    assert (
        store.begin_wave(
            request,
            "generation",
            admission=admission,
            budget=budget,
        ).revision
        == committed.revision
    )
    with pytest.raises(SuccessorPlanningStoreError, match="admission differs"):
        store.begin_wave(
            request,
            "generation",
            admission=_admission((drift_scope,), wave_index=0),
            budget=budget,
        )


def test_committed_call_retry_is_exact_without_an_active_wave(tmp_path: Path) -> None:
    harness = _new_harness(tmp_path)
    before = harness.store.load_and_verify(
        harness.request, harness.generation_id, budget=harness.budget
    )

    exact = harness.store.commit_call(
        harness.request,
        harness.generation_id,
        sealed_dispatch_identity_sha256=harness.wave_0_dispatch.identity_sha256,
        members=(harness.wave_0_member_source,),
        planning_database=harness.wave_0_database,
        budget=harness.budget,
    )

    assert exact.revision == before.revision
    assert exact.active_wave is None
    drifted = PlanningMemberSource(
        member=harness.wave_0_member_source.member,
        receipt_sha256="f" * 64,
        artifact=harness.wave_0_member_source.artifact,
    )
    with pytest.raises(SuccessorPlanningStoreError, match="differs from its committed"):
        harness.store.commit_call(
            harness.request,
            harness.generation_id,
            sealed_dispatch_identity_sha256=harness.wave_0_dispatch.identity_sha256,
            members=(drifted,),
            planning_database=harness.wave_0_database,
            budget=harness.budget,
        )

    outside_member = PlanningMemberSource(
        member=PlanningDataMember(
            member_id="outside_scope",
            wave_index=1,
            producing_scope_sha256="f" * 64,
            schema_sha256=harness.wave_1_member_source.member.schema_sha256,
            content_sha256=harness.wave_1_member_source.artifact.sha256,
            row_count=1,
            semantic=harness.wave_1_member_source.member.semantic,
        ),
        receipt_sha256="2" * 64,
        artifact=harness.wave_1_member_source.artifact,
    )
    with pytest.raises(SuccessorPlanningStoreError, match="durable wave admission"):
        harness.store.commit_call(
            harness.request,
            harness.generation_id,
            sealed_dispatch_identity_sha256="0" * 64,
            members=(outside_member,),
            planning_database=harness.wave_1_database,
            budget=harness.budget,
        )


def test_committed_wave_retry_reverifies_exact_database_source(tmp_path: Path) -> None:
    harness = _new_harness(tmp_path)
    before = harness.store.load_and_verify(
        harness.request, harness.generation_id, budget=harness.budget
    )

    exact = harness.store.commit_wave(
        harness.request,
        harness.generation_id,
        wave=harness.wave_0,
        planning_database=harness.wave_0_database,
        private_generation_identity=harness.wave_0_private_generation_identity,
        completion_receipt=harness.wave_0_completion_receipt,
        budget=harness.budget,
    )

    assert exact.revision == before.revision
    with pytest.raises(SuccessorPlanningStoreError, match="database differs"):
        harness.store.commit_wave(
            harness.request,
            harness.generation_id,
            wave=harness.wave_0,
            planning_database=PlanningDatabaseSource(
                artifact=harness.wave_0_database.artifact,
                schema_sha256="f" * 64,
            ),
            private_generation_identity=harness.wave_0_private_generation_identity,
            completion_receipt=harness.wave_0_completion_receipt,
            budget=harness.budget,
        )
    with pytest.raises(SuccessorPlanningStoreError, match="opened safely"):
        harness.store.commit_wave(
            harness.request,
            harness.generation_id,
            wave=harness.wave_0,
            planning_database=PlanningDatabaseSource(
                artifact=PlanningArtifactSource(
                    path=(harness.sources_root / "missing.duckdb").resolve(),
                    sha256=harness.wave_0_database.artifact.sha256,
                    byte_count=harness.wave_0_database.artifact.byte_count,
                ),
                schema_sha256=harness.wave_0_database.schema_sha256,
            ),
            private_generation_identity=harness.wave_0_private_generation_identity,
            completion_receipt=harness.wave_0_completion_receipt,
            budget=harness.budget,
        )
    drifted_artifact = _write_source(
        harness.sources_root / "drifted-wave-0.duckdb",
        harness.wave_0_database.artifact.path.read_bytes(),
    )
    drifted_artifact.path.write_bytes(b"different")
    with pytest.raises(SuccessorPlanningStoreError, match="byte count|digest"):
        harness.store.commit_wave(
            harness.request,
            harness.generation_id,
            wave=harness.wave_0,
            planning_database=PlanningDatabaseSource(
                artifact=drifted_artifact,
                schema_sha256=harness.wave_0_database.schema_sha256,
            ),
            private_generation_identity=harness.wave_0_private_generation_identity,
            completion_receipt=harness.wave_0_completion_receipt,
            budget=harness.budget,
        )


def test_full_store_seal_and_resume_rehashes_all_private_authority(tmp_path: Path) -> None:
    harness = _new_harness(tmp_path, shared_wave_0_bytes=True)
    manifest = _seal(harness)

    restored = harness.store.load_and_verify(
        harness.request,
        harness.generation_id,
        budget=harness.budget,
    )

    assert restored.manifest == manifest
    assert restored.revision == 7
    assert [call.wave_index for call in restored.committed_calls] == [0, 1]
    assert restored.committed_waves == (harness.wave_0, harness.wave_1)
    assert tuple(
        authority.private_generation_identity for authority in restored.committed_wave_authorities
    ) == (
        harness.wave_0_private_generation_identity,
        harness.wave_1_private_generation_identity,
    )
    assert tuple(
        authority.completion_receipt for authority in restored.committed_wave_authorities
    ) == (
        harness.wave_0_completion_receipt,
        harness.wave_1_completion_receipt,
    )
    assert all(
        not any(isinstance(getattr(authority, field.name), PurePath) for field in fields(authority))
        for authority in restored.committed_wave_authorities
    )
    assert all(
        authority.private_generation_identity_sha256
        != authority.private_generation_identity_object_domain_sha256
        and authority.completion_receipt_sha256 != authority.completion_receipt_object_domain_sha256
        for authority in restored.committed_wave_authorities
    )
    assert restored.committed_wave_admissions[0].sealed_dispatches == (harness.wave_0_dispatch,)
    assert restored.planning_database_sha256 == harness.wave_1_database.artifact.sha256
    assert (
        restored.committed_calls[0].members[0].artifact_sha256
        == restored.committed_calls[0].planning_database_sha256
    )
    assert (
        restored.committed_calls[0].members[0].object_domain_sha256
        != json.loads(_checkpoint_path(harness).read_text())["committed_calls"][0]["database"][
            "artifact"
        ]["domain_sha256"]
    )
    assert stat_mode(harness.store.root) == 0o700
    assert (
        stat_mode(harness.store.objects_root / "database" / restored.planning_database_sha256)
        == 0o400
    )
    checkpoint_text = _checkpoint_path(harness).read_text()
    assert "monotonic" not in checkpoint_text
    assert str(tmp_path) not in checkpoint_text


def stat_mode(path: Path) -> int:
    return os.stat(path, follow_symlinks=False).st_mode & 0o777


def test_resume_requires_exact_request_and_generation_pair(tmp_path: Path) -> None:
    harness = _new_harness(tmp_path)
    changed = SuccessorPlanningRequest(
        baseline_identity_sha256="f" * 64,
        mode=harness.request.mode,
        source_sha=harness.request.source_sha,
        cutoff_utc=harness.request.cutoff_utc,
        as_of_utc=harness.request.as_of_utc,
        workflow_run_id=harness.request.workflow_run_id,
        workflow_run_attempt=harness.request.workflow_run_attempt,
        requested_planning_scopes=harness.request.requested_planning_scopes,
    )

    with pytest.raises(SuccessorPlanningStoreError, match="planning generation"):
        harness.store.load_and_verify(changed, harness.generation_id, budget=harness.budget)
    with pytest.raises(SuccessorPlanningStoreError, match="planning generation"):
        harness.store.load_and_verify(
            harness.request,
            "different-generation",
            budget=harness.budget,
        )


def test_call_crash_leaves_only_prior_checkpoint_and_exact_retry_adopts_objects(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    public = tmp_path / "public"
    public.mkdir()
    sources = tmp_path / "sources"
    sources.mkdir()
    scope = _scope(
        "1",
        endpoint="scoreboard_v3",
        route="scoreboard_v3:stg_scoreboard_games",
        parameters={"game_date": "2026-08-01"},
    )
    request = SuccessorPlanningRequest(
        baseline_identity_sha256="a" * 64,
        mode=SuccessorUpdateMode.DAILY,
        source_sha="b" * 40,
        cutoff_utc="2026-08-01T00:00:00Z",
        as_of_utc="2026-08-02T00:00:00Z",
        workflow_run_id=17,
        workflow_run_attempt=1,
        requested_planning_scopes=(scope,),
    )
    store = SuccessorPlanningStore(
        (tmp_path / "private").resolve(),
        public_roots=(public.resolve(),),
        monotonic_clock=lambda: 100.0,
    )
    budget = _budget()
    store.begin_generation(request, "generation", budget=budget)
    dispatch = _dispatch((scope,), wave_index=0)
    store.begin_wave(
        request,
        "generation",
        admission=_admission((scope,), wave_index=0, dispatches=(dispatch,)),
        budget=budget,
    )
    artifact = _write_source(sources / "member.json", b"[]")
    member = PlanningMemberSource(
        member=PlanningDataMember(
            member_id="live_game_ids",
            wave_index=0,
            producing_scope_sha256=scope.identity_sha256,
            schema_sha256="3" * 64,
            content_sha256=artifact.sha256,
            row_count=0,
            semantic=PlanningSemanticDescriptor.from_partition(
                semantic_kind=PlanningSemanticKind.ACTIVE_LIVE_GAME_IDS,
                partition={"as_of_utc": request.as_of_utc},
                semantic_schema_sha256="3" * 64,
                semantic_content_sha256=artifact.sha256,
                value_count=0,
                typed_zero_reason_code="complete_empty",
            ),
            typed_zero_reason_code="complete_empty",
        ),
        receipt_sha256="4" * 64,
        artifact=artifact,
    )
    database = PlanningDatabaseSource(
        artifact=_write_source(sources / "planning.duckdb", b"DB"),
        schema_sha256="5" * 64,
    )
    original = store._commit_checkpoint
    monkeypatch.setattr(
        store,
        "_commit_checkpoint",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(RuntimeError("crash")),
    )
    with pytest.raises(RuntimeError, match="crash"):
        store.commit_call(
            request,
            "generation",
            sealed_dispatch_identity_sha256=dispatch.identity_sha256,
            members=(member,),
            planning_database=database,
            budget=budget,
        )
    assert store.load_and_verify(request, "generation", budget=budget).committed_calls == ()

    monkeypatch.setattr(store, "_commit_checkpoint", original)
    resumed = store.commit_call(
        request,
        "generation",
        sealed_dispatch_identity_sha256=dispatch.identity_sha256,
        members=(member,),
        planning_database=database,
        budget=budget,
    )
    assert len(resumed.committed_calls) == 1


def test_wave_and_manifest_crash_windows_resume_only_prior_boundaries(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    harness = _new_harness(tmp_path)
    generation = harness.store.generation_path(harness.request, harness.generation_id)
    checkpoint = json.loads(_checkpoint_path(harness).read_text())
    checkpoint["phase"] = PlanningGenerationPhase.WAVE_0_COMMITTED.value
    checkpoint["revision"] = 5
    checkpoint["committed_waves"] = checkpoint["committed_waves"][:1]
    checkpoint["active_wave"] = _admission(
        (harness.wave_1_scope,),
        wave_index=1,
        parent_wave_identity_sha256=harness.wave_0.identity_sha256,
        dispatches=(harness.wave_1_dispatch,),
    ).to_dict()
    _rewrite_checkpoint(_checkpoint_path(harness), checkpoint)
    before = harness.store.load_and_verify(
        harness.request, harness.generation_id, budget=harness.budget
    )
    assert before.phase is PlanningGenerationPhase.WAVE_0_COMMITTED

    original = harness.store._commit_checkpoint
    monkeypatch.setattr(
        harness.store,
        "_commit_checkpoint",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(RuntimeError("wave crash")),
    )
    with pytest.raises(RuntimeError, match="wave crash"):
        harness.store.commit_wave(
            harness.request,
            harness.generation_id,
            wave=harness.wave_1,
            planning_database=harness.wave_1_database,
            private_generation_identity=harness.wave_1_private_generation_identity,
            completion_receipt=harness.wave_1_completion_receipt,
            budget=harness.budget,
        )
    assert (
        harness.store.load_and_verify(
            harness.request, harness.generation_id, budget=harness.budget
        ).phase
        is PlanningGenerationPhase.WAVE_0_COMMITTED
    )
    monkeypatch.setattr(harness.store, "_commit_checkpoint", original)
    harness.store.commit_wave(
        harness.request,
        harness.generation_id,
        wave=harness.wave_1,
        planning_database=harness.wave_1_database,
        private_generation_identity=harness.wave_1_private_generation_identity,
        completion_receipt=harness.wave_1_completion_receipt,
        budget=harness.budget,
    )

    manifest = harness.manifest()
    monkeypatch.setattr(
        harness.store,
        "_commit_checkpoint",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(RuntimeError("seal crash")),
    )
    with pytest.raises(RuntimeError, match="seal crash"):
        harness.store.seal_generation(
            harness.request,
            harness.generation_id,
            manifest=manifest,
            budget=harness.budget,
        )
    staged = harness.store.load_and_verify(
        harness.request, harness.generation_id, budget=harness.budget
    )
    assert staged.phase is PlanningGenerationPhase.WAVE_1_COMMITTED
    assert staged.manifest is None
    assert (
        generation / "planning-generation-manifest.json"
    ).read_bytes() == manifest.canonical_bytes

    monkeypatch.setattr(harness.store, "_commit_checkpoint", original)
    sealed = harness.store.seal_generation(
        harness.request,
        harness.generation_id,
        manifest=manifest,
        budget=harness.budget,
    )
    assert sealed.phase is PlanningGenerationPhase.SEALED


@pytest.mark.parametrize(
    "target",
    [
        "member",
        "database",
        "private_generation_identity",
        "wave_completion_receipt",
        "manifest",
    ],
)
def test_load_rehashes_and_rejects_tampered_bytes(tmp_path: Path, target: str) -> None:
    harness = _new_harness(tmp_path)
    _seal(harness)
    snapshot = harness.store.load_and_verify(
        harness.request, harness.generation_id, budget=harness.budget
    )
    if target == "member":
        path = (
            harness.store.objects_root
            / "member"
            / snapshot.committed_calls[0].members[0].artifact_sha256
        )
    elif target == "database":
        assert snapshot.planning_database_sha256 is not None
        path = harness.store.objects_root / "database" / snapshot.planning_database_sha256
    elif target in {"private_generation_identity", "wave_completion_receipt"}:
        authority = snapshot.committed_wave_authorities[0]
        digest = (
            authority.private_generation_identity_sha256
            if target == "private_generation_identity"
            else authority.completion_receipt_sha256
        )
        path = harness.store.objects_root / target / digest
    else:
        path = (
            harness.store.generation_path(harness.request, harness.generation_id)
            / "planning-generation-manifest.json"
        )
    path.chmod(0o600)
    path.write_bytes(b"tampered")

    with pytest.raises(
        SuccessorPlanningStoreError,
        match="digest|byte count|bytes|immutable|manifest",
    ):
        harness.store.load_and_verify(harness.request, harness.generation_id, budget=harness.budget)


def test_cross_kind_same_byte_reference_cannot_satisfy_member(tmp_path: Path) -> None:
    harness = _new_harness(tmp_path, shared_wave_0_bytes=True)
    checkpoint_path = _checkpoint_path(harness)
    checkpoint = json.loads(checkpoint_path.read_text())
    member_ref = checkpoint["committed_calls"][0]["members"][0]["artifact"]
    database_ref = checkpoint["committed_calls"][0]["database"]["artifact"]
    assert member_ref["sha256"] == database_ref["sha256"]
    checkpoint["committed_calls"][0]["members"][0]["artifact"] = database_ref
    call = checkpoint["committed_calls"][0]
    body = {key: value for key, value in call.items() if key != "call_identity_sha256"}
    call["call_identity_sha256"] = canonical_planning_sha256(
        {"domain": "nbadb.successor-planning-store.call.v2", **body}
    )
    _rewrite_checkpoint(checkpoint_path, checkpoint)

    with pytest.raises(SuccessorPlanningStoreError, match="member object authority"):
        harness.store.load_and_verify(harness.request, harness.generation_id, budget=harness.budget)


@pytest.mark.parametrize(
    "target",
    ["checkpoint_schema", "generation_domain", "object_domain", "call_domain", "admission_domain"],
)
def test_store_v2_rejects_old_v1_persisted_authority(tmp_path: Path, target: str) -> None:
    harness = _new_harness(tmp_path / target)
    checkpoint_path = _checkpoint_path(harness)
    checkpoint = json.loads(checkpoint_path.read_text())
    if target == "checkpoint_schema":
        checkpoint["schema_version"] = 1
    elif target == "generation_domain":
        checkpoint["generation_identity_sha256"] = canonical_planning_sha256(
            {
                "domain": "nbadb.successor-planning-store.generation.v1",
                "planning_request_sha256": harness.request.identity_sha256,
                "planning_generation_id": harness.generation_id,
            }
        )
    elif target == "object_domain":
        call = checkpoint["committed_calls"][0]
        reference = call["members"][0]["artifact"]
        reference["domain_sha256"] = canonical_planning_sha256(
            {
                "domain": "nbadb.successor-planning-store.object.member.v1",
                "sha256": reference["sha256"],
                "bytes": reference["bytes"],
            }
        )
        body = {key: value for key, value in call.items() if key != "call_identity_sha256"}
        call["call_identity_sha256"] = canonical_planning_sha256(
            {"domain": "nbadb.successor-planning-store.call.v2", **body}
        )
    elif target == "call_domain":
        call = checkpoint["committed_calls"][0]
        body = {key: value for key, value in call.items() if key != "call_identity_sha256"}
        call["call_identity_sha256"] = canonical_planning_sha256(
            {"domain": "nbadb.successor-planning-store.call.v1", **body}
        )
    else:
        admission = checkpoint["committed_waves"][0]["admission"]
        admission["identity_sha256"] = canonical_planning_sha256(
            {
                "domain": "nbadb.successor-planning-store.wave-admission.v1",
                "wave_index": admission["wave_index"],
                "parent_wave_identity_sha256": admission["parent_wave_identity_sha256"],
                "requested_route_scopes": admission["requested_route_scopes"],
                "sealed_dispatches": admission["sealed_dispatches"],
            }
        )
    _rewrite_checkpoint(checkpoint_path, checkpoint)

    with pytest.raises(SuccessorPlanningStoreError):
        harness.store.load_and_verify(
            harness.request,
            harness.generation_id,
            budget=harness.budget,
        )


def test_store_rejects_rehashed_nested_semantic_member_tamper(tmp_path: Path) -> None:
    harness = _new_harness(tmp_path)
    checkpoint_path = _checkpoint_path(harness)
    checkpoint = json.loads(checkpoint_path.read_text())
    call = checkpoint["committed_calls"][0]
    member_record = call["members"][0]
    member_payload = member_record["member"]
    member_payload["semantic"]["semantic_content_sha256"] = "f" * 64
    tampered_member = PlanningDataMember.from_dict(member_payload)
    member_record["member_identity_sha256"] = tampered_member.identity_sha256
    body = {key: value for key, value in call.items() if key != "call_identity_sha256"}
    call["call_identity_sha256"] = canonical_planning_sha256(
        {"domain": "nbadb.successor-planning-store.call.v2", **body}
    )
    checkpoint["committed_waves"][0]["call_identity_sha256s"][0] = call["call_identity_sha256"]
    _rewrite_checkpoint(checkpoint_path, checkpoint)

    with pytest.raises(SuccessorPlanningStoreError, match="wave member inventory differs"):
        harness.store.load_and_verify(
            harness.request,
            harness.generation_id,
            budget=harness.budget,
        )


def test_symlink_fifo_special_paths_and_public_overlap_fail_closed(tmp_path: Path) -> None:
    public = tmp_path / "public"
    public.mkdir()
    with pytest.raises(SuccessorPlanningStoreError, match="overlap"):
        SuccessorPlanningStore(
            (public / "private-planning").resolve(),
            public_roots=(public.resolve(),),
            monotonic_clock=lambda: 100.0,
        )

    harness = _new_harness(tmp_path / "isolated")
    snapshot = harness.store.load_and_verify(
        harness.request, harness.generation_id, budget=harness.budget
    )
    member_path = (
        harness.store.objects_root
        / "member"
        / snapshot.committed_calls[0].members[0].artifact_sha256
    )
    member_path.unlink()
    member_path.symlink_to(harness.wave_0_member_source.artifact.path)
    with pytest.raises(SuccessorPlanningStoreError, match="opened safely|regular"):
        harness.store.load_and_verify(harness.request, harness.generation_id, budget=harness.budget)

    member_path.unlink()
    os.mkfifo(member_path, 0o600)
    with pytest.raises(SuccessorPlanningStoreError, match="regular"):
        harness.store.load_and_verify(harness.request, harness.generation_id, budget=harness.budget)


def test_public_overlap_rejects_alternate_case_ancestor(tmp_path: Path) -> None:
    public = tmp_path / "PublicTree"
    public.mkdir()
    alternate_case_child = tmp_path / "publictree" / "private-planning"

    with pytest.raises(SuccessorPlanningStoreError, match="overlap"):
        SuccessorPlanningStore(
            alternate_case_child.absolute(),
            public_roots=(public.resolve(),),
            monotonic_clock=lambda: 100.0,
        )


def test_immutable_control_publication_is_atomic_and_no_overwrite(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    harness = _new_harness(tmp_path)
    target = harness.store.root / "atomic-control-probe"
    original_link = os.link
    with harness.store._exclusive_store_lock():
        monkeypatch.setattr(
            "nbadb.orchestrate.successor_planning_store.os.link",
            lambda *_args, **_kwargs: (_ for _ in ()).throw(OSError("link crash")),
        )
        with pytest.raises(SuccessorPlanningStoreError, match="cannot be published"):
            harness.store._publish_new_regular_no_replace(target, b"partial")
        assert not target.exists()
        assert not tuple(harness.store.root.glob(f".{target.name}.*.tmp"))

        monkeypatch.setattr(
            "nbadb.orchestrate.successor_planning_store.os.link",
            original_link,
        )
        harness.store._publish_new_regular_no_replace(target, b"complete")
        with pytest.raises(SuccessorPlanningStoreError, match="cannot be published"):
            harness.store._publish_new_regular_no_replace(target, b"replacement")
    assert target.read_bytes() == b"complete"


def test_manifest_seal_never_uses_direct_final_file_creation(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    harness = _new_harness(tmp_path)
    monkeypatch.setattr(
        harness.store,
        "_write_new_regular",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("direct final creation")),
    )

    manifest = _seal(harness)

    assert (
        harness.store.generation_path(harness.request, harness.generation_id)
        / "planning-generation-manifest.json"
    ).read_bytes() == manifest.canonical_bytes


def test_injected_generation_path_and_symlink_checkpoint_are_rejected(tmp_path: Path) -> None:
    harness = _new_harness(tmp_path)
    generation = harness.store.generation_path(harness.request, harness.generation_id)
    injected = generation / "unexpected"
    injected.write_bytes(b"x")
    with pytest.raises(SuccessorPlanningStoreError, match="unexpected paths"):
        harness.store.load_and_verify(harness.request, harness.generation_id, budget=harness.budget)
    injected.unlink()
    checkpoint = _checkpoint_path(harness)
    original = checkpoint.read_bytes()
    checkpoint.unlink()
    external = tmp_path / "external-checkpoint"
    external.write_bytes(original)
    checkpoint.symlink_to(external)
    with pytest.raises(SuccessorPlanningStoreError, match="opened safely"):
        harness.store.load_and_verify(harness.request, harness.generation_id, budget=harness.budget)


def test_caller_limits_deadline_and_free_space_are_fail_closed(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    harness = _new_harness(tmp_path)
    monkeypatch.setattr(harness.store, "_monotonic_clock", lambda: 950.0)
    with pytest.raises(SuccessorPlanningStoreError, match="deadline headroom"):
        harness.store.load_and_verify(
            harness.request,
            harness.generation_id,
            budget=_budget(
                monotonic_deadline_seconds=1_000.0,
                minimum_deadline_headroom_seconds=51.0,
            ),
        )
    monkeypatch.setattr(harness.store, "_monotonic_clock", lambda: 100.0)
    with pytest.raises(OSError, match="artifact_max_bytes"):
        harness.store.load_and_verify(
            harness.request,
            harness.generation_id,
            budget=_budget(artifact_max_bytes=1),
        )
    with pytest.raises(OSError, match="generation_max_bytes"):
        harness.store.load_and_verify(
            harness.request,
            harness.generation_id,
            budget=_budget(generation_max_bytes=1),
        )
    monkeypatch.setattr(
        "nbadb.orchestrate.successor_planning_store.shutil.disk_usage",
        lambda _path: SimpleNamespace(free=0),
    )
    with pytest.raises(OSError, match="insufficient private planning capacity"):
        harness.store.load_and_verify(harness.request, harness.generation_id, budget=harness.budget)


def test_thread_and_process_locks_serialize_public_operations(tmp_path: Path) -> None:
    harness = _new_harness(tmp_path)
    thread_entered = threading.Event()
    thread_finished = threading.Event()

    def threaded_load() -> None:
        thread_entered.set()
        harness.store.load_and_verify(harness.request, harness.generation_id, budget=harness.budget)
        thread_finished.set()

    with harness.store._exclusive_store_lock():
        thread = threading.Thread(target=threaded_load)
        thread.start()
        assert thread_entered.wait(1)
        assert not thread_finished.wait(0.1)
    thread.join(timeout=2)
    assert thread_finished.is_set()

    lock_path = harness.store.root / ".successor-planning-store.lock"
    script = (
        "import fcntl,os,sys;"
        "fd=os.open(sys.argv[1],os.O_RDWR);"
        "fcntl.flock(fd,fcntl.LOCK_EX);"
        "print('ready',flush=True);"
        "sys.stdin.readline();"
        "fcntl.flock(fd,fcntl.LOCK_UN);"
        "os.close(fd)"
    )
    process = subprocess.Popen(
        [sys.executable, "-c", script, str(lock_path)],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        text=True,
    )
    assert process.stdout is not None
    assert process.stdout.readline().strip() == "ready"
    process_finished = threading.Event()
    clock_sampled = threading.Event()
    harness.store._monotonic_clock = lambda: clock_sampled.set() or 100.0

    def process_blocked_load() -> None:
        harness.store.load_and_verify(harness.request, harness.generation_id, budget=harness.budget)
        process_finished.set()

    process_thread = threading.Thread(target=process_blocked_load)
    process_thread.start()
    assert not process_finished.wait(0.1)
    assert not clock_sampled.is_set()
    assert process.stdin is not None
    process.stdin.write("release\n")
    process.stdin.flush()
    process.wait(timeout=2)
    process_thread.join(timeout=2)
    assert process_finished.is_set()
    assert clock_sampled.is_set()


def test_lock_inode_replacement_fails_current_and_concurrent_operations(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    harness = _new_harness(tmp_path)
    lock_path = harness.store.root / ".successor-planning-store.lock"
    replaced = threading.Event()
    release_first = threading.Event()
    original_load = harness.store._load_and_verify_locked
    replacement_guard = threading.Lock()
    replacement_done = False

    def replacing_load(
        request: SuccessorPlanningRequest,
        generation_id: str,
        *,
        budget: PlanningStoreBudget,
    ) -> object:
        nonlocal replacement_done
        result = original_load(request, generation_id, budget=budget)
        with replacement_guard:
            replace_now = not replacement_done
            replacement_done = True
        if replace_now:
            lock_path.unlink()
            descriptor = os.open(lock_path, os.O_RDWR | os.O_CREAT | os.O_EXCL, 0o600)
            os.close(descriptor)
            replaced.set()
            assert release_first.wait(2)
        return result

    monkeypatch.setattr(harness.store, "_load_and_verify_locked", replacing_load)
    outcomes: list[str] = []

    def load(label: str) -> None:
        try:
            harness.store.load_and_verify(
                harness.request,
                harness.generation_id,
                budget=harness.budget,
            )
        except SuccessorPlanningStoreError:
            outcomes.append(f"{label}:rejected")
        else:
            outcomes.append(f"{label}:entered")

    first = threading.Thread(target=load, args=("first",))
    first.start()
    assert replaced.wait(2)
    second = threading.Thread(target=load, args=("second",))
    second.start()
    second.join(timeout=2)
    assert not second.is_alive()
    assert "second:rejected" in outcomes
    release_first.set()
    first.join(timeout=2)
    second.join(timeout=2)

    assert sorted(outcomes) == ["first:rejected", "second:rejected"]


def test_root_replacement_is_rejected_before_control_mutation(tmp_path: Path) -> None:
    harness = _new_harness(tmp_path)
    displaced = tmp_path / "displaced-private-planning"
    probe = harness.store.root / "must-not-be-created"

    with harness.store._exclusive_store_lock():
        os.rename(harness.store.root, displaced)
        harness.store.root.mkdir(mode=0o700)
        try:
            with pytest.raises(SuccessorPlanningStoreError, match="root identity changed"):
                harness.store._write_new_regular(probe, b"unsafe")
            assert not probe.exists()
        finally:
            harness.store.root.rmdir()
            os.rename(displaced, harness.store.root)


def test_canonical_checkpoint_revision_tamper_is_rejected(tmp_path: Path) -> None:
    harness = _new_harness(tmp_path)
    checkpoint_path = _checkpoint_path(harness)
    checkpoint = json.loads(checkpoint_path.read_text())
    checkpoint["revision"] = 999
    _rewrite_checkpoint(checkpoint_path, checkpoint)

    with pytest.raises(SuccessorPlanningStoreError, match="revision differs"):
        harness.store.load_and_verify(harness.request, harness.generation_id, budget=harness.budget)


def test_noncanonical_checkpoint_bytes_are_rejected(tmp_path: Path) -> None:
    harness = _new_harness(tmp_path)
    checkpoint_path = _checkpoint_path(harness)
    checkpoint = json.loads(checkpoint_path.read_text())
    checkpoint_path.write_text(json.dumps(checkpoint, indent=2))

    with pytest.raises(SuccessorPlanningStoreError, match="not canonical"):
        harness.store.load_and_verify(harness.request, harness.generation_id, budget=harness.budget)


def test_multi_route_call_crash_resume_and_committed_retry_are_atomic(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    public = tmp_path / "public"
    public.mkdir()
    sources = tmp_path / "sources"
    sources.mkdir(mode=0o700)
    parameters = {"game_date": "2026-08-01", "league_id": "00"}
    scopes = (
        _scope(
            "1",
            endpoint="scoreboard_v3",
            route="scoreboard_v3:stg_scoreboard_games",
            parameters=parameters,
        ),
        _scope(
            "2",
            endpoint="scoreboard_v3",
            route="scoreboard_v3:stg_scoreboard_periods",
            parameters=parameters,
        ),
    )
    request = SuccessorPlanningRequest(
        baseline_identity_sha256="a" * 64,
        mode=SuccessorUpdateMode.DAILY,
        source_sha="b" * 40,
        cutoff_utc="2026-08-01T00:00:00Z",
        as_of_utc="2026-08-02T00:00:00Z",
        workflow_run_id=17,
        workflow_run_attempt=1,
        requested_planning_scopes=tuple(sorted(scopes, key=lambda scope: scope.identity_sha256)),
    )
    store = SuccessorPlanningStore(
        (tmp_path / "private").resolve(),
        public_roots=(public.resolve(),),
        monotonic_clock=lambda: 100.0,
    )
    budget = _budget()
    dispatch = _dispatch(
        tuple(reversed(scopes)),
        wave_index=0,
        pattern="scoreboard_v3",
    )
    admission = _admission(scopes, wave_index=0, dispatches=(dispatch,))
    store.begin_generation(request, "generation", budget=budget)
    store.begin_wave(request, "generation", admission=admission, budget=budget)

    member_sources: list[PlanningMemberSource] = []
    for index, scope in enumerate(scopes):
        artifact = _write_source(sources / f"member-{index}.json", f"[{index}]".encode())
        member_sources.append(
            PlanningMemberSource(
                member=PlanningDataMember(
                    member_id=f"scoreboard_route_{index}",
                    wave_index=0,
                    producing_scope_sha256=scope.identity_sha256,
                    schema_sha256=str(index + 3) * 64,
                    content_sha256=artifact.sha256,
                    row_count=1,
                    semantic=PlanningSemanticDescriptor.from_partition(
                        semantic_kind=PlanningSemanticKind.AUXILIARY_NO_DERIVED_DATA,
                        partition={},
                        semantic_schema_sha256=str(index + 3) * 64,
                        semantic_content_sha256=artifact.sha256,
                        value_count=1,
                    ),
                ),
                receipt_sha256="5" * 64,
                artifact=artifact,
            )
        )
    members = tuple(sorted(member_sources, key=lambda source: source.member.identity_sha256))
    database = PlanningDatabaseSource(
        artifact=_write_source(sources / "planning.duckdb", b"MULTI-ROUTE-DB"),
        schema_sha256="7" * 64,
    )
    original_commit = store._commit_checkpoint
    monkeypatch.setattr(
        store,
        "_commit_checkpoint",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(RuntimeError("call crash")),
    )
    with pytest.raises(RuntimeError, match="call crash"):
        store.commit_call(
            request,
            "generation",
            sealed_dispatch_identity_sha256=dispatch.identity_sha256,
            members=members,
            planning_database=database,
            budget=budget,
        )
    crashed = store.load_and_verify(request, "generation", budget=budget)
    assert crashed.active_wave == admission
    assert crashed.committed_calls == ()

    monkeypatch.setattr(store, "_commit_checkpoint", original_commit)
    committed_call = store.commit_call(
        request,
        "generation",
        sealed_dispatch_identity_sha256=dispatch.identity_sha256,
        members=members,
        planning_database=database,
        budget=budget,
    )
    assert committed_call.committed_calls[0].sealed_dispatch == dispatch
    assert committed_call.committed_calls[0].requested_route_scopes == tuple(reversed(scopes))
    wave, private_identity, completion_receipt = _wave_authority(
        store,
        request,
        "generation",
        wave_index=0,
        admission=admission,
        planning_database=database,
        budget=budget,
    )
    after_wave = store.commit_wave(
        request,
        "generation",
        wave=wave,
        planning_database=database,
        private_generation_identity=private_identity,
        completion_receipt=completion_receipt,
        budget=budget,
    )
    retried = store.commit_call(
        request,
        "generation",
        sealed_dispatch_identity_sha256=dispatch.identity_sha256,
        members=members,
        planning_database=database,
        budget=budget,
    )
    assert retried.revision == after_wave.revision
    assert retried.active_wave is None
    assert len(retried.committed_calls) == 1

    wave_1_scope = _scope(
        "8",
        endpoint="cume_stats_player_games",
        route="cume_stats_player_games:stg_cume_player_games",
        parameters={
            "player_id": 2544,
            "season": "2025-26",
            "season_type": "Regular Season",
        },
    )
    dependencies = tuple(sorted(member.member.identity_sha256 for member in members))
    wave_1_dispatch = _dispatch(
        (wave_1_scope,),
        wave_index=1,
        dependency_identity_sha256s=dependencies,
    )
    wave_1_admission = _admission(
        (wave_1_scope,),
        wave_index=1,
        parent_wave_identity_sha256=wave.identity_sha256,
        dispatches=(wave_1_dispatch,),
    )
    active_wave_1 = store.begin_wave(
        request,
        "generation",
        admission=wave_1_admission,
        budget=budget,
    )
    assert active_wave_1.active_wave is not None
    assert (
        active_wave_1.active_wave.sealed_dispatches[0].dependency_identity_sha256s == dependencies
    )

    wave_1_artifact = _write_source(sources / "wave-1-member.json", b'["0022600001"]')
    wave_1_member = PlanningMemberSource(
        member=PlanningDataMember(
            member_id="player_cume_foundation",
            wave_index=1,
            producing_scope_sha256=wave_1_scope.identity_sha256,
            schema_sha256="9" * 64,
            content_sha256=wave_1_artifact.sha256,
            row_count=1,
            semantic=PlanningSemanticDescriptor.from_partition(
                semantic_kind=PlanningSemanticKind.PLAYER_CUME_FOUNDATION_GAME_IDS,
                partition={
                    "player_id": 2544,
                    "season": "2025-26",
                    "season_type": "Regular Season",
                },
                semantic_schema_sha256="9" * 64,
                semantic_content_sha256=wave_1_artifact.sha256,
                value_count=1,
            ),
        ),
        receipt_sha256="a" * 64,
        artifact=wave_1_artifact,
    )
    wave_1_database = PlanningDatabaseSource(
        artifact=_write_source(sources / "planning-wave-1.duckdb", b"MULTI-DEPENDENCY-WAVE-1"),
        schema_sha256="b" * 64,
    )
    store.commit_call(
        request,
        "generation",
        sealed_dispatch_identity_sha256=wave_1_dispatch.identity_sha256,
        members=(wave_1_member,),
        planning_database=wave_1_database,
        budget=budget,
    )
    wave_1, wave_1_private, wave_1_receipt = _wave_authority(
        store,
        request,
        "generation",
        wave_index=1,
        admission=wave_1_admission,
        planning_database=wave_1_database,
        budget=budget,
        parent_wave_identity_sha256=wave.identity_sha256,
    )
    committed_wave_1 = store.commit_wave(
        request,
        "generation",
        wave=wave_1,
        planning_database=wave_1_database,
        private_generation_identity=wave_1_private,
        completion_receipt=wave_1_receipt,
        budget=budget,
    )
    assert (
        committed_wave_1.committed_wave_admissions[1]
        .sealed_dispatches[0]
        .dependency_identity_sha256s
        == dependencies
    )


def test_admitted_dispatch_program_order_and_scope_ownership_are_exact(
    tmp_path: Path,
) -> None:
    store, initial_request, first, budget, _sources = _new_unstarted_wave_0(tmp_path)
    second = _scope(
        "2",
        endpoint=first.endpoint_name,
        route="scoreboard_v3:stg_scoreboard_periods",
        parameters=first.parameters,
    )
    request = replace(
        initial_request,
        requested_planning_scopes=tuple(
            sorted((first, second), key=lambda scope: scope.identity_sha256)
        ),
    )
    store.begin_generation(request, "two-scope-generation", budget=budget)
    first_dispatch = _dispatch((first,), wave_index=0)
    second_dispatch = _dispatch((second,), wave_index=0)
    admission = _admission(
        (first, second),
        wave_index=0,
        dispatches=(first_dispatch, second_dispatch),
    )
    store.begin_wave(
        request,
        "two-scope-generation",
        admission=admission,
        budget=budget,
    )
    with pytest.raises(SuccessorPlanningStoreError, match="active planning wave differs"):
        store.begin_wave(
            request,
            "two-scope-generation",
            admission=_admission(
                (first, second),
                wave_index=0,
                dispatches=(second_dispatch, first_dispatch),
            ),
            budget=budget,
        )
    with pytest.raises(SuccessorPlanningStoreError, match="more than one dispatch"):
        _admission(
            (first, second),
            wave_index=0,
            dispatches=(first_dispatch, first_dispatch, second_dispatch),
        )


def test_wave_1_dependency_and_generation_member_ids_are_exact(tmp_path: Path) -> None:
    harness = _new_harness(tmp_path)
    _rewind_to_wave_0_committed(harness)
    bad_dispatch = _dispatch(
        (harness.wave_1_scope,),
        wave_index=1,
        dependency_identity_sha256s=tuple(
            sorted(("0" * 64, harness.wave_0_member_source.member.identity_sha256))
        ),
    )
    with pytest.raises(SuccessorPlanningStoreError, match="exact committed wave 0 member"):
        harness.store.begin_wave(
            harness.request,
            harness.generation_id,
            admission=_admission(
                (harness.wave_1_scope,),
                wave_index=1,
                parent_wave_identity_sha256=harness.wave_0.identity_sha256,
                dispatches=(bad_dispatch,),
            ),
            budget=harness.budget,
        )

    harness.store.begin_wave(
        harness.request,
        harness.generation_id,
        admission=_admission(
            (harness.wave_1_scope,),
            wave_index=1,
            parent_wave_identity_sha256=harness.wave_0.identity_sha256,
            dispatches=(harness.wave_1_dispatch,),
        ),
        budget=harness.budget,
    )
    duplicate_id_member = replace(
        harness.wave_1_member_source.member,
        member_id=harness.wave_0_member_source.member.member_id,
    )
    with pytest.raises(SuccessorPlanningStoreError, match="member ids.*globally unique"):
        harness.store.commit_call(
            harness.request,
            harness.generation_id,
            sealed_dispatch_identity_sha256=harness.wave_1_dispatch.identity_sha256,
            members=(
                PlanningMemberSource(
                    member=duplicate_id_member,
                    receipt_sha256=harness.wave_1_member_source.receipt_sha256,
                    artifact=harness.wave_1_member_source.artifact,
                ),
            ),
            planning_database=harness.wave_1_database,
            budget=harness.budget,
        )


def test_manifest_cannot_regroup_or_reorder_persisted_planning_program(
    tmp_path: Path,
) -> None:
    harness = _new_harness(tmp_path)
    original = harness.manifest()
    drifted_wave_0 = _dispatch(
        (harness.wave_0_scope,),
        wave_index=0,
        pattern="drifted_scoreboard_program",
    )
    drifted_dispatches = (drifted_wave_0, *original.sealed_dispatches[1:])
    drifted_identity = replace(
        original.artifact_identity,
        planning_manifest_sha256="0" * 64,
        sealed_dispatch_inventory_sha256=canonical_planning_sha256(
            [dispatch.to_dict() for dispatch in drifted_dispatches]
        ),
    )
    drifted_manifest = PlanningGenerationManifest.seal(
        request=original.request,
        artifact_identity=drifted_identity,
        waves=original.waves,
        members=original.members,
        requested_route_scopes=original.requested_route_scopes,
        sealed_dispatches=drifted_dispatches,
    )
    with pytest.raises(SuccessorPlanningStoreError, match="dispatch program differs"):
        harness.store.seal_generation(
            harness.request,
            harness.generation_id,
            manifest=drifted_manifest,
            budget=harness.budget,
        )


def test_manifest_may_seal_member_derived_update_only_scope(tmp_path: Path) -> None:
    harness = _new_harness(tmp_path)
    original = harness.manifest()
    update_only_scope = _scope(
        "3",
        endpoint="scoreboard_v3",
        route="scoreboard_v3:stg_scoreboard_games",
        parameters={"game_date": "2026-08-02", "league_id": "00"},
    )
    update_only_dispatch = SealedProviderDispatch.from_parameters(
        phase=PlanningDispatchPhase.UPDATE,
        endpoint_name=update_only_scope.endpoint_name,
        requested_scope_identity_sha256s=(update_only_scope.identity_sha256,),
        parameters=update_only_scope.parameters,
        pattern="scoreboard_v3",
        staging_route_ids=(update_only_scope.route_id,),
        dependency_identity_sha256s=(harness.wave_0_member_source.member.identity_sha256,),
    )
    scopes = tuple(
        sorted(
            (*original.requested_route_scopes, update_only_scope),
            key=lambda item: item.identity_sha256,
        )
    )
    dispatches = (*original.sealed_dispatches, update_only_dispatch)
    identity = replace(
        original.artifact_identity,
        planning_manifest_sha256="0" * 64,
        sealed_dispatch_inventory_sha256=canonical_planning_sha256(
            [dispatch.to_dict() for dispatch in dispatches]
        ),
    )
    manifest = PlanningGenerationManifest.seal(
        request=original.request,
        artifact_identity=identity,
        waves=original.waves,
        members=original.members,
        requested_route_scopes=scopes,
        sealed_dispatches=dispatches,
    )

    snapshot = harness.store.seal_generation(
        harness.request,
        harness.generation_id,
        manifest=manifest,
        budget=harness.budget,
    )

    assert snapshot.phase is PlanningGenerationPhase.SEALED
    assert snapshot.manifest == manifest


def test_descriptor_backed_member_read_and_database_copy_are_exact(tmp_path: Path) -> None:
    harness = _new_harness(tmp_path)
    snapshot = harness.store.load_and_verify(
        harness.request,
        harness.generation_id,
        budget=harness.budget,
    )
    call = snapshot.committed_calls[0]
    member = call.members[0]
    assert (
        harness.store.read_committed_member_bytes(
            harness.request,
            harness.generation_id,
            call_identity_sha256=call.identity_sha256,
            member_identity_sha256=member.member.identity_sha256,
            max_bytes=member.artifact_bytes,
            budget=harness.budget,
        )
        == harness.wave_0_member_source.artifact.path.read_bytes()
    )

    destination_parent = tmp_path / "database-copy"
    destination_parent.mkdir(mode=0o700)
    destination = (destination_parent / "planning.duckdb").resolve()
    copied = harness.store.copy_current_database(
        harness.request,
        harness.generation_id,
        planning_database_sha256=harness.wave_1_database.artifact.sha256,
        planning_database_bytes=harness.wave_1_database.artifact.byte_count,
        planning_database_schema_sha256=harness.wave_1_database.schema_sha256,
        destination=destination,
        budget=harness.budget,
    )
    assert copied.schema_sha256 == harness.wave_1_database.schema_sha256
    assert copied.artifact.path == destination
    assert destination.read_bytes() == harness.wave_1_database.artifact.path.read_bytes()
    with pytest.raises(SuccessorPlanningStoreError, match="already exists"):
        harness.store.copy_current_database(
            harness.request,
            harness.generation_id,
            planning_database_sha256=harness.wave_1_database.artifact.sha256,
            planning_database_bytes=harness.wave_1_database.artifact.byte_count,
            planning_database_schema_sha256=harness.wave_1_database.schema_sha256,
            destination=destination,
            budget=harness.budget,
        )


def test_existing_generation_logical_bytes_is_zero_only_for_pristine_absence(
    tmp_path: Path,
) -> None:
    harness = _new_harness(tmp_path / "authority")
    pristine = tmp_path / "pristine-store"
    pristine.mkdir(mode=0o700)
    pristine.chmod(0o700)
    store = SuccessorPlanningStore(
        pristine.resolve(),
        public_roots=(harness.public_root.resolve(),),
        monotonic_clock=lambda: 100.0,
    )
    descriptor = _planning_root_descriptor(pristine)
    try:
        assert (
            store.existing_generation_logical_bytes(
                harness.request,
                harness.generation_id,
                root_descriptor=descriptor,
                budget=harness.budget,
            )
            == 0
        )
    finally:
        os.close(descriptor)
    assert tuple(pristine.iterdir()) == ()


def test_existing_generation_logical_bytes_matches_partial_and_sealed_formula(
    tmp_path: Path,
) -> None:
    harness = _new_harness(tmp_path)
    descriptor = _planning_root_descriptor(harness.store.root)
    try:
        assert harness.store.existing_generation_logical_bytes(
            harness.request,
            harness.generation_id,
            root_descriptor=descriptor,
            budget=harness.budget,
        ) == _expected_generation_logical_bytes(harness)
        _seal(harness)
        expected = _expected_generation_logical_bytes(harness)
        assert (
            harness.store.existing_generation_logical_bytes(
                harness.request,
                harness.generation_id,
                root_descriptor=descriptor,
                budget=harness.budget,
            )
            == expected
        )
        assert (
            harness.store.existing_generation_logical_bytes(
                harness.request,
                harness.generation_id,
                root_descriptor=descriptor,
                budget=harness.budget,
            )
            == expected
        )
    finally:
        os.close(descriptor)


def test_existing_generation_logical_bytes_rejects_foreign_partial_and_tampered_state(
    tmp_path: Path,
) -> None:
    harness = _new_harness(tmp_path)
    foreign = tmp_path / "foreign-root"
    foreign.mkdir(mode=0o700)
    foreign.chmod(0o700)
    foreign_descriptor = _planning_root_descriptor(foreign)
    try:
        with pytest.raises(SuccessorPlanningStoreError, match="capacity root"):
            harness.store.existing_generation_logical_bytes(
                harness.request,
                harness.generation_id,
                root_descriptor=foreign_descriptor,
                budget=harness.budget,
            )
    finally:
        os.close(foreign_descriptor)

    descriptor = _planning_root_descriptor(harness.store.root)
    try:
        missing_generation_id = "missing-but-partial"
        missing_name = harness.store.generation_path(
            harness.request,
            missing_generation_id,
        ).name
        partial = harness.store.generations_root / f".{missing_name}.crash"
        partial.mkdir(mode=0o700)
        with pytest.raises(SuccessorPlanningStoreError, match="unverified partial state"):
            harness.store.existing_generation_logical_bytes(
                harness.request,
                missing_generation_id,
                root_descriptor=descriptor,
                budget=harness.budget,
            )
        partial.rmdir()

        checkpoint = _checkpoint_path(harness)
        checkpoint.write_bytes(checkpoint.read_bytes() + b"\n")
        with pytest.raises(SuccessorPlanningStoreError, match="canonical|checkpoint"):
            harness.store.existing_generation_logical_bytes(
                harness.request,
                harness.generation_id,
                root_descriptor=descriptor,
                budget=harness.budget,
            )
    finally:
        os.close(descriptor)


def test_driver_context_export_batches_members_database_and_two_full_verifications(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    harness = _new_harness(tmp_path)
    destination_parent = tmp_path / "driver-context"
    destination_parent.mkdir(mode=0o700)
    destination = (destination_parent / "planning.duckdb").resolve()
    original = harness.store._load_and_verify_locked
    full_loads = 0

    def counted(*args: Any, **kwargs: Any):
        nonlocal full_loads
        full_loads += 1
        return original(*args, **kwargs)

    monkeypatch.setattr(harness.store, "_load_and_verify_locked", counted)

    exported = harness.store.export_driver_context(
        harness.request,
        harness.generation_id,
        destination=destination,
        planning_database_max_bytes=harness.budget.artifact_max_bytes,
        budget=harness.budget,
    )

    assert full_loads == 2  # one initial authority and one final exact equality reload
    assert exported.snapshot.phase is PlanningGenerationPhase.WAVE_1_COMMITTED
    assert tuple(
        (call_identity, member_identity)
        for call_identity, member_identity, _encoded in exported.committed_member_bytes
    ) == tuple(
        (call.identity_sha256, member.member.identity_sha256)
        for call in exported.snapshot.committed_calls
        for member in call.members
    )
    assert tuple(encoded for _call, _member, encoded in exported.committed_member_bytes) == (
        harness.wave_0_member_source.artifact.path.read_bytes(),
        harness.wave_1_member_source.artifact.path.read_bytes(),
    )
    assert exported.planning_database is not None
    assert exported.planning_database.artifact.path == destination
    assert destination.read_bytes() == harness.wave_1_database.artifact.path.read_bytes()


def test_driver_context_export_rejects_member_tamper_before_database_publication(
    tmp_path: Path,
) -> None:
    harness = _new_harness(tmp_path)
    snapshot = harness.store.load_and_verify(
        harness.request,
        harness.generation_id,
        budget=harness.budget,
    )
    member = snapshot.committed_calls[0].members[0]
    object_path = harness.store.objects_root / "member" / member.artifact_sha256
    object_path.chmod(0o600)
    object_path.write_bytes(b"tampered")
    object_path.chmod(0o400)
    destination_parent = tmp_path / "driver-context"
    destination_parent.mkdir(mode=0o700)
    destination = (destination_parent / "planning.duckdb").resolve()

    with pytest.raises(SuccessorPlanningStoreError, match="byte count|digest"):
        harness.store.export_driver_context(
            harness.request,
            harness.generation_id,
            destination=destination,
            planning_database_max_bytes=harness.budget.artifact_max_bytes,
            budget=harness.budget,
        )

    assert not destination.exists()


def test_driver_context_export_enforces_member_artifact_budget(tmp_path: Path) -> None:
    harness = _new_harness(tmp_path)
    destination_parent = tmp_path / "driver-context"
    destination_parent.mkdir(mode=0o700)
    destination = (destination_parent / "planning.duckdb").resolve()
    tiny = replace(harness.budget, artifact_max_bytes=1)

    with pytest.raises(OSError, match="artifact_max_bytes"):
        harness.store.export_driver_context(
            harness.request,
            harness.generation_id,
            destination=destination,
            planning_database_max_bytes=tiny.artifact_max_bytes,
            budget=tiny,
        )

    assert not destination.exists()


def test_driver_context_export_rejects_oversized_input_before_publication(
    tmp_path: Path,
) -> None:
    harness = _new_harness(tmp_path)
    destination_parent = tmp_path / "driver-context"
    destination_parent.mkdir(mode=0o700)
    destination = (destination_parent / "planning.duckdb").resolve()
    assert harness.wave_1_database.artifact.byte_count > 1

    with pytest.raises(OSError, match="planning_database_max_bytes"):
        harness.store.export_driver_context(
            harness.request,
            harness.generation_id,
            destination=destination,
            planning_database_max_bytes=(harness.wave_1_database.artifact.byte_count - 1),
            budget=harness.budget,
        )

    assert not destination.exists()


def test_driver_context_export_enforces_cumulative_generation_budget(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    harness = _new_harness(tmp_path)
    snapshot = harness.store.load_and_verify(
        harness.request,
        harness.generation_id,
        budget=harness.budget,
    )
    assert snapshot.planning_database_bytes is not None
    exported_bytes = snapshot.planning_database_bytes + sum(
        member.artifact_bytes for call in snapshot.committed_calls for member in call.members
    )
    assert exported_bytes > 1
    destination_parent = tmp_path / "driver-context"
    destination_parent.mkdir(mode=0o700)
    destination = (destination_parent / "planning.duckdb").resolve()
    monkeypatch.setattr(
        harness.store,
        "_load_and_verify_locked",
        lambda *_args, **_kwargs: snapshot,
    )

    with pytest.raises(OSError, match="driver context export exceeds generation_max_bytes"):
        harness.store.export_driver_context(
            harness.request,
            harness.generation_id,
            destination=destination,
            planning_database_max_bytes=harness.budget.artifact_max_bytes,
            budget=replace(harness.budget, generation_max_bytes=exported_bytes - 1),
        )

    assert not destination.exists()


def test_driver_context_export_removes_exact_database_when_final_reload_drifts(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    harness = _new_harness(tmp_path)
    destination_parent = tmp_path / "driver-context"
    destination_parent.mkdir(mode=0o700)
    destination = (destination_parent / "planning.duckdb").resolve()
    original = harness.store._load_and_verify_locked
    full_loads = 0

    def drifted(*args: Any, **kwargs: Any):
        nonlocal full_loads
        full_loads += 1
        snapshot = original(*args, **kwargs)
        if full_loads == 2:
            return replace(snapshot, revision=snapshot.revision + 1)
        return snapshot

    monkeypatch.setattr(harness.store, "_load_and_verify_locked", drifted)

    with pytest.raises(SuccessorPlanningStoreError, match="changed during driver context export"):
        harness.store.export_driver_context(
            harness.request,
            harness.generation_id,
            destination=destination,
            planning_database_max_bytes=harness.budget.artifact_max_bytes,
            budget=harness.budget,
        )

    assert full_loads == 2
    assert not destination.exists()


def test_driver_context_export_refuses_to_remove_replaced_database_after_drift(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    harness = _new_harness(tmp_path)
    destination_parent = tmp_path / "driver-context"
    destination_parent.mkdir(mode=0o700)
    destination = (destination_parent / "planning.duckdb").resolve()
    original = harness.store._load_and_verify_locked
    full_loads = 0

    def replace_destination(*args: Any, **kwargs: Any):
        nonlocal full_loads
        full_loads += 1
        snapshot = original(*args, **kwargs)
        if full_loads == 2:
            destination.unlink()
            destination.write_bytes(b"foreign replacement")
            destination.chmod(0o600)
            return replace(snapshot, revision=snapshot.revision + 1)
        return snapshot

    monkeypatch.setattr(harness.store, "_load_and_verify_locked", replace_destination)

    with pytest.raises(
        SuccessorPlanningStoreError,
        match="exact database cleanup was refused",
    ):
        harness.store.export_driver_context(
            harness.request,
            harness.generation_id,
            destination=destination,
            planning_database_max_bytes=harness.budget.artifact_max_bytes,
            budget=harness.budget,
        )

    assert full_loads == 2
    assert destination.read_bytes() == b"foreign replacement"


def test_public_verified_read_models_are_pathless(tmp_path: Path) -> None:
    harness = _new_harness(tmp_path)
    snapshot = harness.store.load_and_verify(
        harness.request,
        harness.generation_id,
        budget=harness.budget,
    )
    read_models = (
        snapshot,
        *snapshot.committed_calls,
        *(member for call in snapshot.committed_calls for member in call.members),
    )
    for model in read_models:
        assert all(not isinstance(getattr(model, field.name), PurePath) for field in fields(model))
    assert str(harness.store.root) not in repr(snapshot)


@pytest.mark.parametrize("target", ["member", "database"])
def test_descriptor_backed_reads_reject_replacement_after_snapshot(
    tmp_path: Path,
    target: str,
) -> None:
    harness = _new_harness(tmp_path)
    snapshot = harness.store.load_and_verify(
        harness.request,
        harness.generation_id,
        budget=harness.budget,
    )
    if target == "member":
        call = snapshot.committed_calls[0]
        member = call.members[0]
        object_path = harness.store.objects_root / "member" / member.artifact_sha256
    else:
        assert snapshot.planning_database_sha256 is not None
        object_path = harness.store.objects_root / "database" / snapshot.planning_database_sha256
    object_path.unlink()
    object_path.symlink_to(harness.wave_0_member_source.artifact.path)

    with pytest.raises(SuccessorPlanningStoreError, match="opened safely|regular|digest"):
        if target == "member":
            harness.store.read_committed_member_bytes(
                harness.request,
                harness.generation_id,
                call_identity_sha256=call.identity_sha256,
                member_identity_sha256=member.member.identity_sha256,
                max_bytes=member.artifact_bytes,
                budget=harness.budget,
            )
        else:
            destination_parent = tmp_path / "copy"
            destination_parent.mkdir(mode=0o700)
            harness.store.copy_current_database(
                harness.request,
                harness.generation_id,
                planning_database_sha256=harness.wave_1_database.artifact.sha256,
                planning_database_bytes=harness.wave_1_database.artifact.byte_count,
                planning_database_schema_sha256=harness.wave_1_database.schema_sha256,
                destination=(destination_parent / "planning.duckdb").resolve(),
                budget=harness.budget,
            )


def test_database_copy_failure_leaves_published_final_and_removes_only_temp(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    harness = _new_harness(tmp_path)
    destination_parent = tmp_path / "copy"
    destination_parent.mkdir(mode=0o700)
    destination = (destination_parent / "planning.duckdb").resolve()
    original_link = os.link
    original_unlink = os.unlink
    linked = False

    def recording_link(*args: Any, **kwargs: Any) -> None:
        nonlocal linked
        original_link(*args, **kwargs)
        if kwargs.get("dst_dir_fd") is not None and args[1] == destination.name:
            linked = True

    original_assert = harness.store._assert_locked_identity

    def failing_after_link() -> None:
        if linked:
            raise SuccessorPlanningStoreError("post-link identity failure")
        original_assert()

    def refusing_final_unlink(*args: Any, **kwargs: Any) -> None:
        if kwargs.get("dir_fd") is not None and args[0] == destination.name:
            raise AssertionError("published final must never be unlinked during cleanup")
        original_unlink(*args, **kwargs)

    monkeypatch.setattr(
        "nbadb.orchestrate.successor_planning_store.os.link",
        recording_link,
    )
    monkeypatch.setattr(harness.store, "_assert_locked_identity", failing_after_link)
    monkeypatch.setattr(
        "nbadb.orchestrate.successor_planning_store.os.unlink",
        refusing_final_unlink,
    )
    with pytest.raises(SuccessorPlanningStoreError, match="post-link identity failure"):
        harness.store.copy_current_database(
            harness.request,
            harness.generation_id,
            planning_database_sha256=harness.wave_1_database.artifact.sha256,
            planning_database_bytes=harness.wave_1_database.artifact.byte_count,
            planning_database_schema_sha256=harness.wave_1_database.schema_sha256,
            destination=destination,
            budget=harness.budget,
        )
    assert destination.read_bytes() == harness.wave_1_database.artifact.path.read_bytes()
    assert not tuple(destination_parent.glob(".*.tmp"))


def test_database_copy_rejects_final_name_swap_without_deleting_attacker(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    harness = _new_harness(tmp_path)
    destination_parent = tmp_path / "copy-swap"
    destination_parent.mkdir(mode=0o700)
    destination = (destination_parent / "planning.duckdb").resolve()
    attacker = b"ATTACKER-REPLACEMENT"
    original_link = os.link

    def swapping_link(*args: Any, **kwargs: Any) -> None:
        original_link(*args, **kwargs)
        destination_parent_fd = kwargs.get("dst_dir_fd")
        if destination_parent_fd is not None and args[1] == destination.name:
            os.unlink(destination.name, dir_fd=destination_parent_fd)
            descriptor = os.open(
                destination.name,
                os.O_WRONLY | os.O_CREAT | os.O_EXCL,
                0o600,
                dir_fd=destination_parent_fd,
            )
            try:
                assert os.write(descriptor, attacker) == len(attacker)
                os.fsync(descriptor)
            finally:
                os.close(descriptor)

    monkeypatch.setattr(
        "nbadb.orchestrate.successor_planning_store.os.link",
        swapping_link,
    )
    with pytest.raises(
        SuccessorPlanningStoreError,
        match="exact published private inode|changed",
    ):
        harness.store.copy_current_database(
            harness.request,
            harness.generation_id,
            planning_database_sha256=harness.wave_1_database.artifact.sha256,
            planning_database_bytes=harness.wave_1_database.artifact.byte_count,
            planning_database_schema_sha256=harness.wave_1_database.schema_sha256,
            destination=destination,
            budget=harness.budget,
        )
    assert destination.read_bytes() == attacker
    assert not tuple(destination_parent.glob(".*.tmp"))


def test_verified_checkpoint_swap_before_mutation_fails_without_revision_change(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store, request, scope, budget, _sources = _new_unstarted_wave_0(tmp_path)
    generation_id = "generation"
    checkpoint_path = store.generation_path(request, generation_id) / "checkpoint.json"
    checkpoint_bytes = checkpoint_path.read_bytes()
    dispatch = _dispatch((scope,), wave_index=0, pattern="scoreboard_v3")
    admission = _admission(
        (scope,),
        wave_index=0,
        dispatches=(dispatch,),
    )
    original_load_state = store._load_state
    swapped = False

    def swapping_load_state(*args: Any, **kwargs: Any) -> Any:
        nonlocal swapped
        state = original_load_state(*args, **kwargs)
        replacement = checkpoint_path.with_name("checkpoint-replacement.json")
        replacement.write_bytes(checkpoint_bytes)
        replacement.chmod(0o600)
        os.replace(replacement, checkpoint_path)
        swapped = True
        return state

    monkeypatch.setattr(store, "_load_state", swapping_load_state)
    with pytest.raises(
        SuccessorPlanningStoreError,
        match="verified mutation authority|changed",
    ):
        store.begin_wave(
            request,
            generation_id,
            admission=admission,
            budget=budget,
        )
    assert swapped
    assert checkpoint_path.read_bytes() == checkpoint_bytes
    snapshot = store.load_and_verify(request, generation_id, budget=budget)
    assert snapshot.revision == 0
    assert snapshot.active_wave is None


def test_checkpoint_final_name_swap_after_replace_cannot_report_success(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store, request, scope, budget, _sources = _new_unstarted_wave_0(tmp_path)
    generation_id = "generation"
    checkpoint_path = store.generation_path(request, generation_id) / "checkpoint.json"
    original_checkpoint = checkpoint_path.read_bytes()
    dispatch = _dispatch((scope,), wave_index=0, pattern="scoreboard_v3")
    admission = _admission(
        (scope,),
        wave_index=0,
        dispatches=(dispatch,),
    )
    original_replace = os.replace

    def swapping_replace(*args: Any, **kwargs: Any) -> None:
        original_replace(*args, **kwargs)
        destination_parent_fd = kwargs.get("dst_dir_fd")
        if destination_parent_fd is not None and args[1] == "checkpoint.json":
            os.unlink("checkpoint.json", dir_fd=destination_parent_fd)
            descriptor = os.open(
                "checkpoint.json",
                os.O_WRONLY | os.O_CREAT | os.O_EXCL,
                0o600,
                dir_fd=destination_parent_fd,
            )
            try:
                assert os.write(descriptor, original_checkpoint) == len(original_checkpoint)
                os.fsync(descriptor)
            finally:
                os.close(descriptor)

    monkeypatch.setattr(
        "nbadb.orchestrate.successor_planning_store.os.replace",
        swapping_replace,
    )
    with pytest.raises(
        SuccessorPlanningStoreError,
        match="exact published private inode|changed",
    ):
        store.begin_wave(
            request,
            generation_id,
            admission=admission,
            budget=budget,
        )
    assert checkpoint_path.read_bytes() == original_checkpoint
    snapshot = store.load_and_verify(request, generation_id, budget=budget)
    assert snapshot.revision == 0
    assert snapshot.active_wave is None


def test_generation_directory_swap_during_checkpoint_replace_fails_closed(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store, request, scope, budget, _sources = _new_unstarted_wave_0(tmp_path)
    generation_id = "generation"
    generation = store.generation_path(request, generation_id)
    request_bytes = (generation / "request.json").read_bytes()
    checkpoint_bytes = (generation / "checkpoint.json").read_bytes()
    displaced = generation.with_name(f"{generation.name}-displaced")
    dispatch = _dispatch((scope,), wave_index=0, pattern="scoreboard_v3")
    admission = _admission(
        (scope,),
        wave_index=0,
        dispatches=(dispatch,),
    )
    original_replace = os.replace
    swapped = False

    def swapping_generation_replace(*args: Any, **kwargs: Any) -> None:
        nonlocal swapped
        if not swapped and args[1] == "checkpoint.json":
            os.rename(generation, displaced)
            generation.mkdir(mode=0o700)
            (generation / "request.json").write_bytes(request_bytes)
            (generation / "request.json").chmod(0o600)
            (generation / "checkpoint.json").write_bytes(checkpoint_bytes)
            (generation / "checkpoint.json").chmod(0o600)
            swapped = True
        original_replace(*args, **kwargs)

    monkeypatch.setattr(
        "nbadb.orchestrate.successor_planning_store.os.replace",
        swapping_generation_replace,
    )
    with pytest.raises(SuccessorPlanningStoreError, match="directory.*changed"):
        store.begin_wave(
            request,
            generation_id,
            admission=admission,
            budget=budget,
        )
    assert swapped
    assert (generation / "checkpoint.json").read_bytes() == checkpoint_bytes
    snapshot = store.load_and_verify(request, generation_id, budget=budget)
    assert snapshot.revision == 0
    assert snapshot.active_wave is None


def test_generation_directory_swap_after_checkpoint_fsync_fails_postcondition(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store, request, scope, budget, _sources = _new_unstarted_wave_0(tmp_path)
    generation_id = "generation"
    generation = store.generation_path(request, generation_id)
    displaced = generation.with_name(f"{generation.name}-displaced-after-fsync")
    replacement = generation.with_name(f"{generation.name}-replacement-after-fsync")
    admission = _admission((scope,), wave_index=0)
    original_fsync_directory = store._fsync_directory
    swapped = False

    def swapping_fsync_directory(path: Path) -> None:
        nonlocal swapped
        original_fsync_directory(path)
        if swapped or path != generation:
            return
        shutil.copytree(generation, replacement)
        os.rename(generation, displaced)
        os.rename(replacement, generation)
        swapped = True

    monkeypatch.setattr(store, "_fsync_directory", swapping_fsync_directory)
    with pytest.raises(
        SuccessorPlanningStoreError,
        match="mutation authority|changed while held",
    ):
        store.begin_wave(
            request,
            generation_id,
            admission=admission,
            budget=budget,
        )
    assert swapped
    assert generation.stat().st_ino != displaced.stat().st_ino
    snapshot = store.load_and_verify(request, generation_id, budget=budget)
    assert snapshot.revision == 1
    assert snapshot.active_wave == admission


def test_initial_generation_swap_after_parent_fsync_fails_postcondition(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    public = tmp_path / "public"
    public.mkdir()
    store = SuccessorPlanningStore(
        (tmp_path / "private").resolve(),
        public_roots=(public.resolve(),),
        monotonic_clock=lambda: 100.0,
    )
    scope = _scope(
        "1",
        endpoint="scoreboard_v3",
        route="scoreboard_v3:stg_scoreboard_games",
        parameters={"game_date": "2026-08-01", "league_id": "00"},
    )
    request = SuccessorPlanningRequest(
        baseline_identity_sha256="a" * 64,
        mode=SuccessorUpdateMode.DAILY,
        source_sha="b" * 40,
        cutoff_utc="2026-08-01T00:00:00Z",
        as_of_utc="2026-08-02T00:00:00Z",
        workflow_run_id=17,
        workflow_run_attempt=1,
        requested_planning_scopes=(scope,),
    )
    generation_id = "generation"
    generation = store.generation_path(request, generation_id)
    displaced = generation.with_name(f"{generation.name}-displaced-after-fsync")
    replacement = generation.with_name(f"{generation.name}-replacement-after-fsync")
    original_fsync_directory = store._fsync_directory
    swapped = False

    def swapping_fsync_directory(path: Path) -> None:
        nonlocal swapped
        original_fsync_directory(path)
        if swapped or path != store.generations_root or not generation.exists():
            return
        shutil.copytree(generation, replacement)
        os.rename(generation, displaced)
        os.rename(replacement, generation)
        swapped = True

    monkeypatch.setattr(store, "_fsync_directory", swapping_fsync_directory)
    with pytest.raises(
        SuccessorPlanningStoreError,
        match="published planning generation changed while held",
    ):
        store.begin_generation(request, generation_id, budget=_budget())
    assert swapped
    assert generation.stat().st_ino != displaced.stat().st_ino
    snapshot = store.load_and_verify(request, generation_id, budget=_budget())
    assert snapshot.revision == 0
    assert snapshot.phase is PlanningGenerationPhase.BUILDING


def test_member_object_post_link_swap_fails_without_false_commit(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store, request, scope, budget, sources = _new_unstarted_wave_0(tmp_path)
    dispatch = _dispatch((scope,), wave_index=0, pattern="scoreboard_v3")
    admission = _admission((scope,), wave_index=0, dispatches=(dispatch,))
    store.begin_wave(request, "generation", admission=admission, budget=budget)
    member_artifact = _write_source(sources / "member.json", b"[]")
    member = PlanningDataMember(
        member_id="live_game_ids",
        wave_index=0,
        producing_scope_sha256=scope.identity_sha256,
        schema_sha256="3" * 64,
        content_sha256=member_artifact.sha256,
        row_count=0,
        semantic=PlanningSemanticDescriptor.from_partition(
            semantic_kind=PlanningSemanticKind.ACTIVE_LIVE_GAME_IDS,
            partition={"as_of_utc": request.as_of_utc},
            semantic_schema_sha256="3" * 64,
            semantic_content_sha256=member_artifact.sha256,
            value_count=0,
            typed_zero_reason_code="scoreboard_complete_empty",
        ),
        typed_zero_reason_code="scoreboard_complete_empty",
    )
    member_source = PlanningMemberSource(
        member=member,
        receipt_sha256="4" * 64,
        artifact=member_artifact,
    )
    database = PlanningDatabaseSource(
        artifact=_write_source(sources / "planning.duckdb", b"DUCKDB"),
        schema_sha256="5" * 64,
    )
    target = store.objects_root / "member" / member_artifact.sha256
    attacker = b"ATTACKER-OBJECT"
    original_link = os.link
    swapped = False

    def swapping_object_link(*args: Any, **kwargs: Any) -> None:
        nonlocal swapped
        original_link(*args, **kwargs)
        destination_parent_fd = kwargs.get("dst_dir_fd")
        if swapped or destination_parent_fd is None or args[1] != member_artifact.sha256:
            return
        os.unlink(args[1], dir_fd=destination_parent_fd)
        descriptor = os.open(
            args[1],
            os.O_WRONLY | os.O_CREAT | os.O_EXCL,
            0o600,
            dir_fd=destination_parent_fd,
        )
        try:
            assert os.write(descriptor, attacker) == len(attacker)
            os.fchmod(descriptor, 0o400)
            os.fsync(descriptor)
        finally:
            os.close(descriptor)
        swapped = True

    monkeypatch.setattr(
        "nbadb.orchestrate.successor_planning_store.os.link",
        swapping_object_link,
    )
    with pytest.raises(
        SuccessorPlanningStoreError,
        match="exact published private inode",
    ):
        store.commit_call(
            request,
            "generation",
            sealed_dispatch_identity_sha256=dispatch.identity_sha256,
            members=(member_source,),
            planning_database=database,
            budget=budget,
        )
    assert swapped
    assert target.read_bytes() == attacker
    assert not tuple(target.parent.glob(f".{member_artifact.sha256}.*.tmp"))
    snapshot = store.load_and_verify(request, "generation", budget=budget)
    assert snapshot.revision == 1
    assert not snapshot.committed_calls

    with pytest.raises(SuccessorPlanningStoreError, match="byte count differs|digest"):
        store.commit_call(
            request,
            "generation",
            sealed_dispatch_identity_sha256=dispatch.identity_sha256,
            members=(member_source,),
            planning_database=database,
            budget=budget,
        )


def test_manifest_final_name_swap_does_not_seal_generation(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    harness = _new_harness(tmp_path)
    generation = harness.store.generation_path(harness.request, harness.generation_id)
    manifest_path = generation / "planning-generation-manifest.json"
    manifest = harness.manifest()
    attacker = b"ATTACKER-MANIFEST"
    original_link = os.link

    def swapping_manifest_link(*args: Any, **kwargs: Any) -> None:
        original_link(*args, **kwargs)
        destination_parent_fd = kwargs.get("dst_dir_fd")
        if destination_parent_fd is not None and args[1] == "planning-generation-manifest.json":
            os.unlink(args[1], dir_fd=destination_parent_fd)
            descriptor = os.open(
                args[1],
                os.O_WRONLY | os.O_CREAT | os.O_EXCL,
                0o600,
                dir_fd=destination_parent_fd,
            )
            try:
                assert os.write(descriptor, attacker) == len(attacker)
                os.fsync(descriptor)
            finally:
                os.close(descriptor)

    monkeypatch.setattr(
        "nbadb.orchestrate.successor_planning_store.os.link",
        swapping_manifest_link,
    )
    with pytest.raises(
        SuccessorPlanningStoreError,
        match="exact published private inode|changed",
    ):
        harness.store.seal_generation(
            harness.request,
            harness.generation_id,
            manifest=manifest,
            budget=harness.budget,
        )
    checkpoint = json.loads(_checkpoint_path(harness).read_text())
    assert checkpoint["phase"] == PlanningGenerationPhase.WAVE_1_COMMITTED.value
    assert checkpoint["manifest"] is None
    assert manifest_path.read_bytes() == attacker


def test_initial_control_name_swap_never_publishes_corrupt_generation(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    public = tmp_path / "public"
    public.mkdir()
    store = SuccessorPlanningStore(
        (tmp_path / "private").resolve(),
        public_roots=(public.resolve(),),
        monotonic_clock=lambda: 100.0,
    )
    scope = _scope(
        "1",
        endpoint="scoreboard_v3",
        route="scoreboard_v3:stg_scoreboard_games",
        parameters={"game_date": "2026-08-01", "league_id": "00"},
    )
    request = SuccessorPlanningRequest(
        baseline_identity_sha256="a" * 64,
        mode=SuccessorUpdateMode.DAILY,
        source_sha="b" * 40,
        cutoff_utc="2026-08-01T00:00:00Z",
        as_of_utc="2026-08-02T00:00:00Z",
        workflow_run_id=17,
        workflow_run_attempt=1,
        requested_planning_scopes=(scope,),
    )
    generation_id = "generation"
    generation = store.generation_path(request, generation_id)
    original_fsync = os.fsync
    swapped = False

    def swapping_fsync(descriptor: int) -> None:
        nonlocal swapped
        original_fsync(descriptor)
        if swapped:
            return
        opened = os.fstat(descriptor)
        if not stat.S_ISREG(opened.st_mode):
            return
        candidates = tuple(store.generations_root.glob(".*.tmp/request.json"))
        if len(candidates) != 1:
            return
        path = candidates[0]
        observed = path.stat(follow_symlinks=False)
        if (opened.st_dev, opened.st_ino) != (observed.st_dev, observed.st_ino):
            return
        replacement = path.with_name("request-attacker.json")
        replacement.write_bytes(b"ATTACKER-REQUEST")
        replacement.chmod(0o600)
        os.replace(replacement, path)
        swapped = True

    monkeypatch.setattr(
        "nbadb.orchestrate.successor_planning_store.os.fsync",
        swapping_fsync,
    )
    with pytest.raises(
        SuccessorPlanningStoreError,
        match="exact published private inode|changed|cannot be created safely",
    ):
        store.begin_generation(request, generation_id, budget=_budget())
    assert swapped
    assert not generation.exists()
    abandoned = tuple(store.generations_root.glob(".*.tmp"))
    assert len(abandoned) == 1
    assert (abandoned[0] / "request.json").read_bytes() == b"ATTACKER-REQUEST"


def test_store_owned_writes_fail_on_zero_progress(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    harness = _new_harness(tmp_path)
    target = harness.store.root / "zero-progress-control"
    monkeypatch.setattr(
        "nbadb.orchestrate.successor_planning_store.os.write",
        lambda *_args, **_kwargs: 0,
    )
    with (
        harness.store._exclusive_store_lock(),
        pytest.raises(SuccessorPlanningStoreError, match="no progress"),
    ):
        harness.store._publish_new_regular_no_replace(target, b"never-published")
    assert not target.exists()
