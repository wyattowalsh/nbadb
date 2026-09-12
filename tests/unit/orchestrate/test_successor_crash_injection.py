from __future__ import annotations

import hashlib
import json
from typing import TYPE_CHECKING

import pytest

from nbadb.orchestrate import successor_crash_injection as crash_injection
from nbadb.orchestrate.successor_crash_injection import DurablePlanningStep
from nbadb.orchestrate.successor_generation_store import SuccessorGenerationStore
from nbadb.orchestrate.successor_planner import deterministic_planning_generation_id
from nbadb.orchestrate.successor_planning_driver import (
    PlanningMemberEnvelope,
    PlanningWaveSealRuntimeRequest,
)
from nbadb.orchestrate.successor_planning_generation_contract import PlanningDataMember
from nbadb.orchestrate.successor_planning_request_builder import (
    build_successor_planning_request,
)
from nbadb.orchestrate.successor_planning_runtime import ExtractorPlanningExactCallRuntime
from nbadb.orchestrate.successor_planning_semantic_contract import (
    PlanningSemanticDescriptor,
    PlanningSemanticKind,
)
from nbadb.orchestrate.successor_planning_store import (
    CommittedPlanningCall,
    CommittedPlanningMember,
    PlanningDatabaseSource,
    PlanningGenerationPhase,
    PlanningMemberSource,
    PlanningWaveAdmission,
    SuccessorPlanningStore,
    SuccessorPlanningStoreError,
)
from nbadb.orchestrate.successor_update_contract import (
    RequestedRouteScope,
    SuccessorUpdateMode,
)
from tests.unit.orchestrate.test_successor_generation_store import (
    _candidate,
    _promoted,
    _record_all,
)
from tests.unit.orchestrate.test_successor_planning_driver import (
    _BudgetFactory,
    _executor,
    _SemanticRuntime,
)
from tests.unit.orchestrate.test_successor_planning_runtime import (
    _config,
    _digest,
    _install_fake_league_provider,
    _league_exact_call,
)
from tests.unit.orchestrate.test_successor_planning_store import (
    _admission,
    _budget,
    _checkpoint_path,
    _dispatch,
    _new_harness,
    _new_unstarted_wave_0,
    _rewrite_checkpoint,
    _wave_authority,
    _write_source,
)

if TYPE_CHECKING:
    from pathlib import Path


def _install_once_crash(
    monkeypatch: pytest.MonkeyPatch,
    step: DurablePlanningStep,
    **match: object,
) -> list[tuple[DurablePlanningStep, dict[str, object]]]:
    observed: list[tuple[DurablePlanningStep, dict[str, object]]] = []

    def hook(found: DurablePlanningStep, **identity: object) -> None:
        observed.append((found, dict(identity)))
        if found is not step:
            return
        if match and any(identity.get(key) != value for key, value in match.items()):
            return
        if any(
            prior is step
            and (not match or all(payload.get(key) == value for key, value in match.items()))
            for prior, payload in observed[:-1]
        ):
            return
        raise RuntimeError(f"injected-crash-after-{step.value}")

    monkeypatch.setattr(crash_injection, "after_durable_step", hook)
    return observed


def _close_runtime_sessions(runtime: ExtractorPlanningExactCallRuntime) -> None:
    for session in tuple(runtime._sessions.values()):  # noqa: SLF001
        session.close()


def _member_files(root: Path) -> list[Path]:
    return sorted(path for path in root.rglob("member-*.json") if path.is_file())


def _planning_databases(root: Path) -> list[Path]:
    return sorted(path for path in root.rglob("planning.duckdb") if path.is_file())


async def test_crash_after_provider_capture_replays_same_generation_call(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    config = _config(tmp_path)
    first_runtime = ExtractorPlanningExactCallRuntime(config)
    exact = _league_exact_call(
        tmp_path,
        first_runtime,
        planning_generation_id="successor-planning-v2-crash-capture",
    )
    provider_calls: list[str] = []
    _install_fake_league_provider(
        monkeypatch,
        exact.dispatch,
        provider_calls=provider_calls,
    )
    _install_once_crash(monkeypatch, DurablePlanningStep.PROVIDER_CAPTURE)

    with pytest.raises(RuntimeError, match="injected-crash-after-provider_capture"):
        await first_runtime.execute_planning_call(exact)
    _close_runtime_sessions(first_runtime)

    capture_files = [path for path in config.capture_base.rglob("*") if path.is_file()]
    assert capture_files
    assert _member_files(exact.private_work_root) == []
    assert provider_calls == [exact.dispatch.identity_sha256]

    resume_runtime = ExtractorPlanningExactCallRuntime(config)
    execution = await resume_runtime.execute_planning_call(exact)

    assert provider_calls == [exact.dispatch.identity_sha256, exact.dispatch.identity_sha256]
    assert execution.members
    assert _member_files(exact.private_work_root)


async def test_crash_after_planning_duckdb_commit_replays_without_member_receipt(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    config = _config(tmp_path)
    first_runtime = ExtractorPlanningExactCallRuntime(config)
    exact = _league_exact_call(
        tmp_path,
        first_runtime,
        planning_generation_id="successor-planning-v2-crash-duckdb",
    )
    provider_calls: list[str] = []
    _install_fake_league_provider(
        monkeypatch,
        exact.dispatch,
        provider_calls=provider_calls,
    )
    _install_once_crash(monkeypatch, DurablePlanningStep.PLANNING_DUCKDB_COMMIT)

    with pytest.raises(RuntimeError, match="injected-crash-after-planning_duckdb_commit"):
        await first_runtime.execute_planning_call(exact)
    _close_runtime_sessions(first_runtime)

    assert _planning_databases(exact.private_work_root)
    assert _member_files(exact.private_work_root) == []

    resume_runtime = ExtractorPlanningExactCallRuntime(config)
    execution = await resume_runtime.execute_planning_call(exact)

    assert provider_calls == [exact.dispatch.identity_sha256, exact.dispatch.identity_sha256]
    assert execution.members
    assert _member_files(exact.private_work_root)


async def test_crash_after_member_receipt_is_not_store_completion(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    config = _config(tmp_path)
    first_runtime = ExtractorPlanningExactCallRuntime(config)
    exact = _league_exact_call(
        tmp_path,
        first_runtime,
        planning_generation_id="successor-planning-v2-crash-member",
    )
    provider_calls: list[str] = []
    _install_fake_league_provider(
        monkeypatch,
        exact.dispatch,
        provider_calls=provider_calls,
    )
    _install_once_crash(monkeypatch, DurablePlanningStep.MEMBER_RECEIPT)

    with pytest.raises(RuntimeError, match="injected-crash-after-member_receipt"):
        await first_runtime.execute_planning_call(exact)
    _close_runtime_sessions(first_runtime)

    crashed_members = _member_files(exact.private_work_root)
    assert crashed_members
    generations_root = config.planning_store_root / "generations"
    assert not generations_root.exists() or not any(generations_root.iterdir())

    resume_runtime = ExtractorPlanningExactCallRuntime(config)
    execution = await resume_runtime.execute_planning_call(exact)

    assert provider_calls == [exact.dispatch.identity_sha256, exact.dispatch.identity_sha256]
    assert execution.members[0].artifact.path.exists()
    assert execution.members[0].receipt_sha256


async def test_crash_after_private_seal_resume_restores_exact_bronze_identity(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    config = _config(tmp_path)
    first_runtime = ExtractorPlanningExactCallRuntime(config)
    exact = _league_exact_call(
        tmp_path,
        first_runtime,
        planning_generation_id="successor-planning-v2-crash-private-seal",
    )
    _install_fake_league_provider(monkeypatch, exact.dispatch)
    execution = await first_runtime.execute_planning_call(exact)
    scope = exact.requested_route_scopes[0]
    committed_member = CommittedPlanningMember(
        member=execution.members[0].member,
        receipt_sha256=execution.members[0].receipt_sha256,
        artifact_sha256=execution.members[0].artifact.sha256,
        artifact_bytes=execution.members[0].artifact.byte_count,
        object_domain_sha256=_digest("member-object"),
    )
    committed_call = CommittedPlanningCall(
        ordinal=0,
        wave_index=0,
        sealed_dispatch=exact.dispatch,
        requested_route_scopes=(scope,),
        members=(committed_member,),
        planning_database_sha256=execution.planning_database.artifact.sha256,
        planning_database_bytes=execution.planning_database.artifact.byte_count,
        planning_database_schema_sha256=execution.planning_database.schema_sha256,
        identity_sha256=_digest("committed-call"),
    )
    envelope = PlanningMemberEnvelope.from_canonical_bytes(
        execution.members[0].artifact.path.read_bytes()
    )
    seal_request = PlanningWaveSealRuntimeRequest(
        request=exact.request,
        planning_generation_id=exact.planning_generation_id,
        admission=PlanningWaveAdmission(
            wave_index=0,
            parent_wave_identity_sha256=None,
            requested_route_scopes=(scope,),
            sealed_dispatches=(exact.dispatch,),
        ),
        committed_calls=(committed_call,),
        member_envelopes=(envelope,),
        planning_database=execution.planning_database,
        private_work_root=exact.private_work_root,
    )
    _install_once_crash(monkeypatch, DurablePlanningStep.PRIVATE_SEAL)

    with pytest.raises(RuntimeError, match="injected-crash-after-private_seal"):
        await first_runtime.seal_planning_wave(seal_request)
    _close_runtime_sessions(first_runtime)

    resume_runtime = ExtractorPlanningExactCallRuntime(config)
    seal = await resume_runtime.seal_planning_wave(seal_request)
    reentered = await resume_runtime.seal_planning_wave(seal_request)

    assert seal.private_generation_identity == reentered.private_generation_identity
    assert seal.wave.identity_sha256 == reentered.wave.identity_sha256
    assert seal.private_generation_identity.done_call_count == 1


async def test_crash_after_call_completion_resume_skips_committed_dispatch(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    request, store, first_runtime, first = _executor(tmp_path)
    _install_once_crash(monkeypatch, DurablePlanningStep.CALL_COMPLETION)

    with pytest.raises(RuntimeError, match="injected-crash-after-call_completion"):
        await first(request)
    generation_id = deterministic_planning_generation_id(request)
    crashed = store.load_and_verify(request, generation_id, budget=_BudgetFactory()())
    assert crashed.phase is PlanningGenerationPhase.BUILDING
    assert len(crashed.committed_calls) == 1
    committed_dispatch = crashed.committed_calls[0].sealed_dispatch.identity_sha256
    committed_call = crashed.committed_calls[0].identity_sha256

    resume_runtime = _SemanticRuntime()
    _install_once_crash(
        monkeypatch,
        DurablePlanningStep.CALL_COMPLETION,
        committed_call_count=2,
    )
    _request_again, _store_again, _runtime_again, resumed = _executor(
        tmp_path,
        runtime=resume_runtime,
        store=store,
    )
    with pytest.raises(RuntimeError, match="injected-crash-after-call_completion"):
        await resumed(request)

    restored = store.load_and_verify(request, generation_id, budget=_BudgetFactory()())
    assert restored.committed_calls[0].identity_sha256 == committed_call
    assert restored.committed_calls[0].sealed_dispatch.identity_sha256 == committed_dispatch
    assert len(restored.committed_calls) == 2
    assert all(
        call.dispatch.identity_sha256 != committed_dispatch for call in resume_runtime.call_requests
    )


async def test_crash_after_private_seal_resume_does_not_replay_wave_zero(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    request, store, first_runtime, first = _executor(tmp_path)
    _install_once_crash(monkeypatch, DurablePlanningStep.PRIVATE_SEAL, wave_index=0)

    with pytest.raises(RuntimeError, match="injected-crash-after-private_seal"):
        await first(request)
    generation_id = deterministic_planning_generation_id(request)
    crashed = store.load_and_verify(request, generation_id, budget=_BudgetFactory()())
    assert crashed.phase is PlanningGenerationPhase.BUILDING
    assert crashed.committed_calls
    assert crashed.committed_waves == ()
    wave_zero_dispatches = {
        call.sealed_dispatch.identity_sha256
        for call in crashed.committed_calls
        if call.wave_index == 0
    }

    resume_runtime = _SemanticRuntime()
    _request_again, _store_again, _runtime_again, resumed = _executor(
        tmp_path,
        runtime=resume_runtime,
        store=store,
    )
    _install_once_crash(
        monkeypatch,
        DurablePlanningStep.POINTER_ADVANCE,
        pointer="planning_checkpoint",
        phase=PlanningGenerationPhase.WAVE_0_COMMITTED.value,
    )
    with pytest.raises(RuntimeError, match="injected-crash-after-pointer_advance"):
        await resumed(request)

    restored = store.load_and_verify(request, generation_id, budget=_BudgetFactory()())
    assert restored.phase is PlanningGenerationPhase.WAVE_0_COMMITTED
    assert {
        call.sealed_dispatch.identity_sha256
        for call in restored.committed_calls
        if call.wave_index == 0
    } == wave_zero_dispatches
    assert resume_runtime.call_requests == []


async def test_crash_after_wave_manifest_resume_adopts_objects_then_advances_pointer(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    harness = _new_harness(tmp_path)
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

    _install_once_crash(monkeypatch, DurablePlanningStep.WAVE_MANIFEST, wave_index=1)
    with pytest.raises(RuntimeError, match="injected-crash-after-wave_manifest"):
        harness.store.commit_wave(
            harness.request,
            harness.generation_id,
            wave=harness.wave_1,
            planning_database=harness.wave_1_database,
            private_generation_identity=harness.wave_1_private_generation_identity,
            completion_receipt=harness.wave_1_completion_receipt,
            budget=harness.budget,
        )
    crashed = harness.store.load_and_verify(
        harness.request, harness.generation_id, budget=harness.budget
    )
    assert crashed.phase is PlanningGenerationPhase.WAVE_0_COMMITTED
    assert crashed.committed_waves == before.committed_waves

    resumed = harness.store.commit_wave(
        harness.request,
        harness.generation_id,
        wave=harness.wave_1,
        planning_database=harness.wave_1_database,
        private_generation_identity=harness.wave_1_private_generation_identity,
        completion_receipt=harness.wave_1_completion_receipt,
        budget=harness.budget,
    )
    assert resumed.phase is PlanningGenerationPhase.WAVE_1_COMMITTED
    assert resumed.committed_waves[1] == harness.wave_1


async def test_crash_after_dispatch_seal_resume_adopts_staged_manifest(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    harness = _new_harness(tmp_path)
    manifest = harness.manifest()
    generation = harness.store.generation_path(harness.request, harness.generation_id)
    _install_once_crash(monkeypatch, DurablePlanningStep.DISPATCH_SEAL)

    with pytest.raises(RuntimeError, match="injected-crash-after-dispatch_seal"):
        harness.store.seal_generation(
            harness.request,
            harness.generation_id,
            manifest=manifest,
            budget=harness.budget,
        )
    crashed = harness.store.load_and_verify(
        harness.request, harness.generation_id, budget=harness.budget
    )
    assert crashed.phase is PlanningGenerationPhase.WAVE_1_COMMITTED
    assert crashed.manifest is None
    assert (generation / "planning-generation-manifest.json").read_bytes() == (
        manifest.canonical_bytes
    )

    sealed = harness.store.seal_generation(
        harness.request,
        harness.generation_id,
        manifest=manifest,
        budget=harness.budget,
    )
    assert sealed.phase is PlanningGenerationPhase.SEALED
    assert sealed.manifest == manifest


def _typed_zero_member(
    sources: Path,
    scope: RequestedRouteScope,
    as_of_utc: str,
) -> tuple[PlanningMemberSource, PlanningDatabaseSource]:
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
                partition={"as_of_utc": as_of_utc},
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
    return member, database


def test_crash_after_generation_pointer_resume_reloads_building(
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
    request = build_successor_planning_request(
        baseline_identity_sha256="a" * 64,
        mode=SuccessorUpdateMode.DAILY,
        source_sha="b" * 40,
        cutoff_utc="2026-08-01T00:00:00Z",
        as_of_utc="2026-08-02T00:00:00Z",
        workflow_run_id=17,
        workflow_run_attempt=1,
    )
    budget = _budget()
    _install_once_crash(
        monkeypatch,
        DurablePlanningStep.POINTER_ADVANCE,
        pointer="planning_generation",
    )
    with pytest.raises(RuntimeError, match="injected-crash-after-pointer_advance"):
        store.begin_generation(request, "generation", budget=budget)
    crashed = store.load_and_verify(request, "generation", budget=budget)
    assert crashed.phase is PlanningGenerationPhase.BUILDING
    resumed = store.begin_generation(request, "generation", budget=budget)
    assert resumed.phase is PlanningGenerationPhase.BUILDING
    assert resumed.revision == crashed.revision == 0


def test_crash_after_wave_admission_pointer_resume_keeps_admission(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store, request, scope, budget, _sources = _new_unstarted_wave_0(tmp_path)
    admission = _admission((scope,), wave_index=0)
    _install_once_crash(
        monkeypatch,
        DurablePlanningStep.POINTER_ADVANCE,
        pointer="planning_checkpoint",
        has_active_wave=True,
        committed_call_count=0,
    )
    with pytest.raises(RuntimeError, match="injected-crash-after-pointer_advance"):
        store.begin_wave(request, "generation", admission=admission, budget=budget)
    crashed = store.load_and_verify(request, "generation", budget=budget)
    assert crashed.active_wave == admission
    resumed = store.begin_wave(request, "generation", admission=admission, budget=budget)
    assert resumed.revision == crashed.revision
    assert resumed.active_wave == admission


def test_crash_after_call_pointer_resume_adopts_committed_call(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store, request, scope, budget, sources = _new_unstarted_wave_0(tmp_path)
    dispatch = _dispatch((scope,), wave_index=0)
    store.begin_wave(
        request,
        "generation",
        admission=_admission((scope,), wave_index=0, dispatches=(dispatch,)),
        budget=budget,
    )
    member, database = _typed_zero_member(sources, scope, request.as_of_utc)
    _install_once_crash(
        monkeypatch,
        DurablePlanningStep.POINTER_ADVANCE,
        pointer="planning_checkpoint",
        committed_call_count=1,
        committed_wave_count=0,
    )
    with pytest.raises(RuntimeError, match="injected-crash-after-pointer_advance"):
        store.commit_call(
            request,
            "generation",
            sealed_dispatch_identity_sha256=dispatch.identity_sha256,
            members=(member,),
            planning_database=database,
            budget=budget,
        )
    crashed = store.load_and_verify(request, "generation", budget=budget)
    assert len(crashed.committed_calls) == 1
    resumed = store.commit_call(
        request,
        "generation",
        sealed_dispatch_identity_sha256=dispatch.identity_sha256,
        members=(member,),
        planning_database=database,
        budget=budget,
    )
    assert resumed.committed_calls[0].identity_sha256 == crashed.committed_calls[0].identity_sha256


def test_crash_after_wave_pointer_resume_keeps_committed_wave(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store, request, scope, budget, sources = _new_unstarted_wave_0(tmp_path)
    dispatch = _dispatch((scope,), wave_index=0)
    admission = _admission((scope,), wave_index=0, dispatches=(dispatch,))
    store.begin_wave(request, "generation", admission=admission, budget=budget)
    member, database = _typed_zero_member(sources, scope, request.as_of_utc)
    store.commit_call(
        request,
        "generation",
        sealed_dispatch_identity_sha256=dispatch.identity_sha256,
        members=(member,),
        planning_database=database,
        budget=budget,
    )
    wave, private, receipt = _wave_authority(
        store,
        request,
        "generation",
        wave_index=0,
        admission=admission,
        planning_database=database,
        budget=budget,
    )
    _install_once_crash(
        monkeypatch,
        DurablePlanningStep.POINTER_ADVANCE,
        pointer="planning_checkpoint",
        phase=PlanningGenerationPhase.WAVE_0_COMMITTED.value,
    )
    with pytest.raises(RuntimeError, match="injected-crash-after-pointer_advance"):
        store.commit_wave(
            request,
            "generation",
            wave=wave,
            planning_database=database,
            private_generation_identity=private,
            completion_receipt=receipt,
            budget=budget,
        )
    crashed = store.load_and_verify(request, "generation", budget=budget)
    assert crashed.phase is PlanningGenerationPhase.WAVE_0_COMMITTED
    assert crashed.committed_waves[0] == wave
    resumed = store.commit_wave(
        request,
        "generation",
        wave=wave,
        planning_database=database,
        private_generation_identity=private,
        completion_receipt=receipt,
        budget=budget,
    )
    assert resumed.phase is PlanningGenerationPhase.WAVE_0_COMMITTED
    assert resumed.committed_waves[0] == wave


def test_crash_after_sealed_pointer_resume_keeps_manifest(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    harness = _new_harness(tmp_path)
    manifest = harness.manifest()
    _install_once_crash(
        monkeypatch,
        DurablePlanningStep.POINTER_ADVANCE,
        pointer="planning_checkpoint",
        phase=PlanningGenerationPhase.SEALED.value,
    )
    with pytest.raises(RuntimeError, match="injected-crash-after-pointer_advance"):
        harness.store.seal_generation(
            harness.request,
            harness.generation_id,
            manifest=manifest,
            budget=harness.budget,
        )
    crashed = harness.store.load_and_verify(
        harness.request, harness.generation_id, budget=harness.budget
    )
    assert crashed.phase is PlanningGenerationPhase.SEALED
    assert crashed.manifest == manifest
    resumed = harness.store.seal_generation(
        harness.request,
        harness.generation_id,
        manifest=manifest,
        budget=harness.budget,
    )
    assert resumed.phase is PlanningGenerationPhase.SEALED
    assert resumed.manifest == manifest


def test_crash_after_current_pointer_write_resume_is_idempotent(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        SuccessorGenerationStore,
        "_gate_publication_before_promote",
        lambda self, *args, **kwargs: None,
    )
    store = SuccessorGenerationStore(tmp_path / "store")
    promoted = _promoted(1, "current-pointer")
    candidate = _candidate(store, promoted)
    _record_all(store, candidate, promoted)
    _install_once_crash(
        monkeypatch,
        DurablePlanningStep.POINTER_ADVANCE,
        pointer="current",
    )

    with pytest.raises(RuntimeError, match="injected-crash-after-pointer_advance"):
        store.promote(candidate, promoted)
    pointer = store.read_current()
    assert pointer is not None
    assert pointer["current"]["generation"] == 1
    assert pointer["current"]["transaction_sha256"] == promoted.content_sha256

    resumed = store.promote(candidate, promoted)
    assert resumed == pointer
    assert store.read_current() == pointer


async def test_cross_generation_does_not_reuse_prior_committed_members(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    request_a, store, _runtime_a, first = _executor(tmp_path)
    _install_once_crash(monkeypatch, DurablePlanningStep.CALL_COMPLETION)
    with pytest.raises(RuntimeError, match="injected-crash-after-call_completion"):
        await first(request_a)
    generation_a = deterministic_planning_generation_id(request_a)
    snapshot_a = store.load_and_verify(request_a, generation_a, budget=_BudgetFactory()())
    assert snapshot_a.committed_calls
    member_a = snapshot_a.committed_calls[0].members[0].member.identity_sha256

    request_b = build_successor_planning_request(
        baseline_identity_sha256=hashlib.sha256(b"baseline").hexdigest(),
        mode=SuccessorUpdateMode.DAILY,
        source_sha="b" * 40,
        cutoff_utc="2026-08-12T00:00:00Z",
        as_of_utc="2026-08-14T00:00:00Z",
        workflow_run_id=731,
        workflow_run_attempt=4,
    )
    generation_b = deterministic_planning_generation_id(request_b)
    assert generation_a != generation_b
    with pytest.raises(SuccessorPlanningStoreError):
        store.load_and_verify(request_b, generation_a, budget=_BudgetFactory()())

    runtime_b = _SemanticRuntime()
    _install_once_crash(monkeypatch, DurablePlanningStep.CALL_COMPLETION)
    _request_unused, _store_unused, _runtime_unused, second = _executor(
        tmp_path,
        runtime=runtime_b,
        store=store,
    )
    with pytest.raises(RuntimeError, match="injected-crash-after-call_completion"):
        await second(request_b)

    assert runtime_b.call_requests
    snapshot_b = store.load_and_verify(request_b, generation_b, budget=_BudgetFactory()())
    assert snapshot_b.committed_calls
    assert snapshot_b.committed_calls[0].members[0].member.identity_sha256 != member_a
    assert snapshot_b.planning_generation_id == generation_b
    retained_a = store.load_and_verify(request_a, generation_a, budget=_BudgetFactory()())
    assert retained_a.committed_calls[0].members[0].member.identity_sha256 == member_a


def test_after_durable_step_rejects_non_enum_and_is_noop_by_default() -> None:
    crash_injection.after_durable_step(DurablePlanningStep.CALL_COMPLETION)
    with pytest.raises(TypeError, match="DurablePlanningStep"):
        crash_injection.after_durable_step("call_completion")  # type: ignore[arg-type]
