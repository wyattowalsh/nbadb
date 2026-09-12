from __future__ import annotations

import hashlib
import shutil
from dataclasses import dataclass, replace
from pathlib import Path

import pytest

from nbadb.core.errors import ExtractionError
from nbadb.extract.bronze import (
    PARSER_INPUT_REPRESENTATION,
    BronzeLimits,
    LogicalCallReceiptBinding,
    ResultSetReceipt,
    canonical_parameters_sha256,
    parent_occurrence_states_digest,
)
from nbadb.orchestrate.capture_session import (
    CaptureRunScope,
    PrivateCaptureSession,
    PrivateGenerationIdentity,
    planning_wave_lane_id,
)
from nbadb.orchestrate.successor_planning_capture_resolver import (
    RetainedBronzePlanningResolver,
    RetainedBronzePlanningResolverError,
)
from nbadb.orchestrate.successor_planning_contract import SuccessorPlanningRequest
from nbadb.orchestrate.successor_planning_generation_contract import PlanningDataMember
from nbadb.orchestrate.successor_planning_semantic_contract import (
    PlanningSemanticDescriptor,
    PlanningSemanticKind,
)
from nbadb.orchestrate.successor_planning_store import CommittedPlanningWaveAuthority
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


def _digest(seed: str) -> str:
    return hashlib.sha256(seed.encode()).hexdigest()


def _limits() -> BronzeLimits:
    return BronzeLimits(
        max_response_bytes=100_000,
        max_generation_stored_bytes=2_000_000,
        minimum_free_bytes=1,
        max_receipt_bytes=100_000,
        max_receipt_count=1_000,
        max_checkpoint_bytes=1_000_000,
        minimum_deadline_headroom_seconds=10.0,
    )


def _private_dir(path: Path) -> Path:
    path.mkdir(parents=True, mode=0o700)
    path.chmod(0o700)
    return path.resolve()


@dataclass(frozen=True, slots=True)
class _Harness:
    capture_base: Path
    planning_root: Path
    public_root: Path
    generation_id: str
    wave_root: Path
    request: SuccessorPlanningRequest
    authority: CommittedPlanningWaveAuthority
    limits: BronzeLimits

    def resolver(self) -> RetainedBronzePlanningResolver:
        return RetainedBronzePlanningResolver(
            self.capture_base,
            limits=self.limits,
            public_roots=(self.public_root,),
            planning_store_root=self.planning_root,
        )


def _harness(
    tmp_path: Path,
    *,
    chain_id: str | None = None,
    lane_id: str | None = None,
) -> _Harness:
    capture_base = _private_dir(tmp_path / "retained-bronze")
    planning_root = _private_dir(tmp_path / "planning-store")
    public_root = (tmp_path / "public").resolve()
    public_root.mkdir(mode=0o755)
    generation_id = "successor-planning-v2-test"
    generation_root = _private_dir(capture_base / generation_id)
    wave_root = generation_root / "wave-0"
    route = "scoreboard_v3:stg_scoreboard_games"
    params = {"game_date": "2026-08-13", "league_id": "00"}
    requested_scope = RequestedRouteScope.from_parameters(
        endpoint_name="scoreboard_v3",
        route_id=route,
        route_contract_sha256=_digest("route-contract"),
        parameters=params,
        mutability=CallMutability.MUTABLE,
    )
    request = SuccessorPlanningRequest(
        baseline_identity_sha256=_digest("baseline"),
        mode=SuccessorUpdateMode.DAILY,
        source_sha="a" * 40,
        cutoff_utc="2026-08-12T00:00:00Z",
        as_of_utc="2026-08-13T00:00:00Z",
        workflow_run_id=17,
        workflow_run_attempt=1,
        requested_planning_scopes=(requested_scope,),
    )
    scope = CaptureRunScope(
        semantic_source_sha=request.source_sha,
        chain_id=generation_id if chain_id is None else chain_id,
        lane_id=planning_wave_lane_id(0) if lane_id is None else lane_id,
        workflow_run_id=17,
        workflow_run_attempt=1,
    )
    limits = _limits()
    session = PrivateCaptureSession(
        wave_root,
        limits=limits,
        public_roots=(public_root,),
        scope=scope,
    )
    session.admit(
        estimated_checkpoint_bytes=50_000,
        monotonic_now_seconds=100.0,
        monotonic_deadline_seconds=200.0,
    )
    contract = session.contract_for("scoreboard_v3", params).for_endpoint_contract(
        _digest("endpoint-contract")
    )
    request_context = contract.begin_request()
    captured = contract.sink.store_parser_input(
        '{"resultSets":[{"name":"GameHeader","headers":[],"rowSet":[]}]}',
        representation=PARSER_INPUT_REPRESENTATION,
    )
    attempt = contract.sink.record_response_attempt(
        context=request_context,
        transport_kind="http_response",
        source_family="stats",
        endpoint_id="ScoreboardV3",
        endpoint_slug="scoreboardv3",
        parameters=params,
        provider_authority_sha256=contract.provider_authority_sha256,
        contract_sha256=contract.endpoint_contract_sha256,
        status_code=200,
        captured=captured,
        outcome="success_empty",
        failure_class=None,
        root_exception_class=None,
        result_sets=(
            ResultSetReceipt(
                name="GameHeader",
                provider_index=0,
                canonical_index=0,
                headers_sha256=_digest("headers"),
                row_count=0,
                json_path=None,
                container_kind="nba_api_result_set",
                container_count=1,
                missing_count=0,
                null_count=0,
                parent_observation_count=1,
                parent_occurrence_states_sha256=parent_occurrence_states_digest(("present",)),
                observed_field_orders_sha256=_digest("field-orders"),
                normalized_output_sha256=_digest("normalized-output"),
            ),
        ),
    )
    contract.record_receipt(request_context, attempt, successful=True)
    snapshot = contract.receipt_snapshot()
    logical_root = contract.sink.record_logical_call(
        context=contract.context,
        logical_endpoint_id="scoreboard_v3",
        logical_parameters=params,
        provider_authority_sha256=contract.provider_authority_sha256,
        response_receipt_sha256s=snapshot.receipt_sha256s,
        successful_response_ordinals=snapshot.successful_response_ordinals,
        result_route_ids=(route,),
    )
    binding = LogicalCallReceiptBinding(
        logical_call_receipt_sha256=logical_root,
        endpoint_name="scoreboard_v3",
        logical_parameters_sha256=canonical_parameters_sha256(params),
        provider_authority_sha256=contract.provider_authority_sha256,
        result_route_ids=(route,),
    )
    session.record_completed(binding)
    private = session.seal()
    session.close()

    member = PlanningDataMember(
        member_id="live_game_ids",
        wave_index=0,
        producing_scope_sha256=requested_scope.identity_sha256,
        schema_sha256=_digest("member-schema"),
        content_sha256=_digest("member-content"),
        row_count=0,
        semantic=PlanningSemanticDescriptor.from_partition(
            semantic_kind=PlanningSemanticKind.ACTIVE_LIVE_GAME_IDS,
            partition={"as_of_utc": request.as_of_utc},
            semantic_schema_sha256=_digest("member-schema"),
            semantic_content_sha256=_digest("member-content"),
            value_count=0,
            typed_zero_reason_code="scoreboard_complete_empty",
        ),
        typed_zero_reason_code="scoreboard_complete_empty",
    )
    dispatch_id = _digest("sealed-dispatch")
    call_id = _digest("committed-call")
    receipt = PlanningWaveCompletionReceipt(
        planning_request_sha256=request.identity_sha256,
        planning_generation_id=generation_id,
        wave_index=0,
        parent_wave_identity_sha256=None,
        wave_admission_identity_sha256=_digest("wave-admission"),
        sealed_dispatch_identity_sha256s=(dispatch_id,),
        committed_calls=(
            PlanningWaveCallBinding(
                ordinal=0,
                sealed_dispatch_identity_sha256=dispatch_id,
                committed_call_identity_sha256=call_id,
                logical_call_receipt_sha256=logical_root,
                member_identity_sha256s=(member.identity_sha256,),
            ),
        ),
        requested_scope_identity_sha256s=(requested_scope.identity_sha256,),
        completed_scope_identity_sha256s=(requested_scope.identity_sha256,),
        members=(
            PlanningWaveMemberBinding(
                member=member,
                logical_call_receipt_sha256=logical_root,
            ),
        ),
        logical_call_bindings=(binding,),
        capture_scope=scope,
        private_generation_identity=private,
        planning_database_sha256=_digest("database"),
        planning_database_bytes=8192,
        planning_database_schema_sha256=_digest("database-schema"),
    )
    authority = CommittedPlanningWaveAuthority(
        wave_index=0,
        private_generation_identity=private,
        completion_receipt=receipt,
        private_generation_identity_sha256=_digest_bytes(private.canonical_bytes),
        private_generation_identity_bytes=len(private.canonical_bytes),
        private_generation_identity_object_domain_sha256=_digest("private-domain"),
        completion_receipt_sha256=_digest_bytes(receipt.canonical_bytes),
        completion_receipt_bytes=len(receipt.canonical_bytes),
        completion_receipt_object_domain_sha256=_digest("receipt-domain"),
    )
    return _Harness(
        capture_base=capture_base,
        planning_root=planning_root,
        public_root=public_root,
        generation_id=generation_id,
        wave_root=wave_root.resolve(),
        request=request,
        authority=authority,
        limits=limits,
    )


def _digest_bytes(encoded: bytes) -> str:
    return hashlib.sha256(encoded).hexdigest()


def test_resolver_rejects_update_execution_capture_ownership(tmp_path: Path) -> None:
    harness = _harness(
        tmp_path,
        chain_id="full-chain-001",
        lane_id="b" * 64,
    )

    with pytest.raises(
        RetainedBronzePlanningResolverError,
        match="update-execution or otherwise foreign capture ownership",
    ):
        harness.resolver().verify(
            request=harness.request,
            planning_generation_id=harness.generation_id,
            authority=harness.authority,
        )


def test_resolver_freshly_reinventories_exact_sealed_generation(tmp_path: Path) -> None:
    harness = _harness(tmp_path)

    first = harness.resolver().verify(
        request=harness.request,
        planning_generation_id=harness.generation_id,
        authority=harness.authority,
    )
    second = harness.resolver().verify(
        request=harness.request,
        planning_generation_id=harness.generation_id,
        authority=harness.authority,
    )

    assert first.canonical_bytes == harness.authority.private_generation_identity.canonical_bytes
    assert second == first


def test_resolver_rejects_missing_or_unsealed_root_and_releases_lock(tmp_path: Path) -> None:
    harness = _harness(tmp_path)
    manifest = harness.wave_root / "manifest.json"
    retained_manifest = manifest.read_bytes()
    manifest.unlink()

    with pytest.raises(
        RetainedBronzePlanningResolverError,
        match="retained planning Bronze generation is invalid",
    ):
        harness.resolver().verify(
            request=harness.request,
            planning_generation_id=harness.generation_id,
            authority=harness.authority,
        )
    probe = PrivateCaptureSession(
        harness.wave_root,
        limits=harness.limits,
        public_roots=(harness.public_root,),
        scope=harness.authority.completion_receipt.capture_scope,
    )
    probe.close()
    manifest.write_bytes(retained_manifest)

    harness.wave_root.rename(harness.wave_root.with_name("wave-held"))
    with pytest.raises(RetainedBronzePlanningResolverError, match="must exist"):
        harness.resolver().verify(
            request=harness.request,
            planning_generation_id=harness.generation_id,
            authority=harness.authority,
        )


def test_resolver_rejects_foreign_request_scope_before_opening_generation(
    tmp_path: Path,
) -> None:
    harness = _harness(tmp_path)
    foreign = replace(harness.request, source_sha="b" * 40)

    with pytest.raises(RetainedBronzePlanningResolverError, match="differs from request"):
        harness.resolver().verify(
            request=foreign,
            planning_generation_id=harness.generation_id,
            authority=harness.authority,
        )


@pytest.mark.parametrize(
    ("field_name", "value"),
    [("workflow_run_id", 18), ("workflow_run_attempt", 2)],
)
def test_resolver_binds_retained_capture_to_request_workflow_coordinates(
    tmp_path: Path,
    field_name: str,
    value: int,
) -> None:
    harness = _harness(tmp_path)
    foreign_request = replace(harness.request, **{field_name: value})
    foreign_receipt = replace(
        harness.authority.completion_receipt,
        planning_request_sha256=foreign_request.identity_sha256,
    )
    foreign_authority = replace(
        harness.authority,
        completion_receipt=foreign_receipt,
        completion_receipt_sha256=_digest_bytes(foreign_receipt.canonical_bytes),
        completion_receipt_bytes=len(foreign_receipt.canonical_bytes),
    )

    with pytest.raises(RetainedBronzePlanningResolverError, match="differs from request"):
        harness.resolver().verify(
            request=foreign_request,
            planning_generation_id=harness.generation_id,
            authority=foreign_authority,
        )


@pytest.mark.parametrize("target", ["manifest", "blob"])
def test_resolver_rejects_fresh_bronze_tampering_and_releases_lock(
    tmp_path: Path,
    target: str,
) -> None:
    harness = _harness(tmp_path)
    path = (
        harness.wave_root / "manifest.json"
        if target == "manifest"
        else next((harness.wave_root / "blobs").rglob("*.payload.gz"))
    )
    path.write_bytes(path.read_bytes() + b"tamper")

    with pytest.raises(RetainedBronzePlanningResolverError, match="generation is invalid"):
        harness.resolver().verify(
            request=harness.request,
            planning_generation_id=harness.generation_id,
            authority=harness.authority,
        )
    with pytest.raises(ExtractionError) as raised:
        PrivateCaptureSession(
            harness.wave_root,
            limits=harness.limits,
            public_roots=(harness.public_root,),
            scope=harness.authority.completion_receipt.capture_scope,
        )
    assert "already has a writer" not in str(raised.value)


def test_resolver_rejects_symlink_overlap_and_non_private_roots(tmp_path: Path) -> None:
    harness = _harness(tmp_path)
    symlink = tmp_path / "capture-link"
    symlink.symlink_to(harness.capture_base, target_is_directory=True)
    with pytest.raises(RetainedBronzePlanningResolverError, match="symlink"):
        RetainedBronzePlanningResolver(
            symlink.absolute(),
            limits=harness.limits,
            public_roots=(harness.public_root,),
            planning_store_root=harness.planning_root,
        )

    harness.capture_base.chmod(0o750)
    with pytest.raises(RetainedBronzePlanningResolverError, match="0700"):
        harness.resolver()
    harness.capture_base.chmod(0o700)

    with pytest.raises(RetainedBronzePlanningResolverError, match="disjoint"):
        RetainedBronzePlanningResolver(
            harness.capture_base,
            limits=harness.limits,
            public_roots=(harness.public_root,),
            planning_store_root=harness.capture_base / harness.generation_id,
        )

    with pytest.raises(RetainedBronzePlanningResolverError, match="disjoint"):
        RetainedBronzePlanningResolver(
            harness.capture_base,
            limits=harness.limits,
            public_roots=(harness.public_root, harness.public_root),
            planning_store_root=harness.planning_root,
        )


def test_resolver_rejects_capture_root_swap_after_fresh_inventory(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    harness = _harness(tmp_path)
    original = PrivateCaptureSession.restore_sealed_identity_if_present

    def restore_then_swap(
        session: PrivateCaptureSession,
    ) -> PrivateGenerationIdentity | None:
        restored = original(session)
        harness.capture_base.rename(tmp_path / "retained-bronze-swapped")
        _private_dir(harness.capture_base)
        return restored

    monkeypatch.setattr(
        PrivateCaptureSession,
        "restore_sealed_identity_if_present",
        restore_then_swap,
    )

    with pytest.raises(RetainedBronzePlanningResolverError, match="capture base changed identity"):
        harness.resolver().verify(
            request=harness.request,
            planning_generation_id=harness.generation_id,
            authority=harness.authority,
        )


def test_resolver_binds_restore_to_preopened_wave_inode_during_swap_back(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    harness = _harness(tmp_path)
    valid_sibling = harness.wave_root.with_name("wave-valid-sibling")
    shutil.copytree(harness.wave_root, valid_sibling)
    (harness.wave_root / "manifest.json").write_bytes(b"{}\n")
    held_invalid = harness.wave_root.with_name("wave-invalid-held")
    original = PrivateCaptureSession.open_existing
    swap_observed = False

    def open_while_valid_sibling_occupies_canonical_path(
        cls: type[PrivateCaptureSession],
        root: Path | str,
        **kwargs: object,
    ) -> PrivateCaptureSession:
        nonlocal swap_observed
        canonical = Path(root)
        canonical.rename(held_invalid)
        valid_sibling.rename(canonical)
        swap_observed = True
        try:
            return original(root, **kwargs)  # type: ignore[arg-type]
        finally:
            canonical.rename(valid_sibling)
            held_invalid.rename(canonical)

    monkeypatch.setattr(
        PrivateCaptureSession,
        "open_existing",
        classmethod(open_while_valid_sibling_occupies_canonical_path),
    )

    with pytest.raises(
        RetainedBronzePlanningResolverError,
        match="retained planning Bronze generation is invalid",
    ):
        harness.resolver().verify(
            request=harness.request,
            planning_generation_id=harness.generation_id,
            authority=harness.authority,
        )
    assert swap_observed is True
    assert (harness.wave_root / "manifest.json").read_bytes() == b"{}\n"
