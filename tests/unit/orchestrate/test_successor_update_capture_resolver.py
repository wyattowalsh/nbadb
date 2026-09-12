from __future__ import annotations

import hashlib
import shutil
from dataclasses import dataclass, replace
from pathlib import Path
from types import SimpleNamespace
from typing import cast

import pytest

from nbadb.core.errors import ExtractionError
from nbadb.core.nba_api_provenance import expected_nba_api_provider_authority
from nbadb.extract.bronze import BronzeLimits
from nbadb.orchestrate import successor_update_capture_resolver as resolver_module
from nbadb.orchestrate.capture_session import (
    CaptureRunScope,
    PrivateCaptureSession,
    PrivateGenerationIdentity,
)
from nbadb.orchestrate.successor_planning_contract import SuccessorPlanningRequest
from nbadb.orchestrate.successor_update_capture_resolver import (
    RetainedBronzeUpdateResolver,
    RetainedBronzeUpdateResolverError,
)
from nbadb.orchestrate.successor_update_contract import (
    BaselineAssuranceIdentity,
    CallMutability,
    DeltaDisposition,
    ObservedDeltaReceipt,
    PlannedRouteReplacementBinding,
    RequestedRouteScope,
    SuccessorUpdateIntent,
    SuccessorUpdateMode,
    SuccessorUpdateTransaction,
    UpdateScopeClosureEvidenceKind,
    canonical_sha256,
    planned_route_replacement_bindings_sha256,
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


def _private_directory(path: Path) -> Path:
    path.mkdir(parents=True, mode=0o700)
    path.chmod(0o700)
    return path.resolve()


def _baseline(
    provider_authority_sha256: str,
    *,
    installed_public_tree_bytes: int,
) -> BaselineAssuranceIdentity:
    return BaselineAssuranceIdentity(
        remote_dataset="maintainer/nbadb",
        remote_dataset_version=238,
        chain_id="full-initial-20260813",
        source_sha="a" * 40,
        coverage_fingerprint=_digest("coverage"),
        data_tree_fingerprint=_digest("data-tree"),
        remote_bundle_fingerprint_sha256=_digest("remote-bundle"),
        installed_public_tree_sha256=_digest("installed-tree"),
        installed_public_tree_bytes=installed_public_tree_bytes,
        assured_manifest_sha256=_digest("assured-manifest"),
        terminal_assurance_report_sha256=_digest("terminal-report"),
        private_baseline_receipt_sha256=_digest("private-baseline"),
        checkpoint_database_sha256=_digest("checkpoint-db"),
        checkpoint_report_sha256=_digest("checkpoint-report"),
        contract_blocked_evidence_sha256=_digest("blocked"),
        provider_authority_sha256=provider_authority_sha256,
    )


@dataclass(frozen=True, slots=True)
class _Harness:
    capture_base: Path
    public_root: Path
    limits: BronzeLimits
    transaction: SuccessorUpdateTransaction
    planning_request: SuccessorPlanningRequest
    scope: CaptureRunScope
    generation_root: Path
    private_identity: PrivateGenerationIdentity

    @property
    def public_identity(self) -> tuple[int, int]:
        observed = self.public_root.stat()
        return observed.st_dev, observed.st_ino

    def resolver(self) -> RetainedBronzeUpdateResolver:
        return RetainedBronzeUpdateResolver(self.capture_base, limits=self.limits)

    def verify(self) -> PrivateGenerationIdentity:
        return self.resolver().verify(
            transaction=self.transaction,
            planning_request=self.planning_request,
            candidate_public_root=self.public_root,
            expected_public_root_identity=self.public_identity,
            expected_identity=self.private_identity,
        )


def _harness(tmp_path: Path) -> _Harness:
    capture_base = _private_directory(tmp_path / "retained-update-bronze")
    public_root = (tmp_path / "candidate" / "public").resolve()
    public_root.mkdir(parents=True, mode=0o755)
    provider = expected_nba_api_provider_authority().get("authority_sha256")
    assert isinstance(provider, str)
    baseline = _baseline(
        provider,
        installed_public_tree_bytes=0,
    )
    scope_contract = RequestedRouteScope.from_parameters(
        endpoint_name="scoreboard_v3",
        route_id="scoreboard_v3:stg_scoreboard_games",
        route_contract_sha256=_digest("route-contract"),
        parameters={"game_date": "2026-08-13", "league_id": "00"},
        mutability=CallMutability.MUTABLE,
    )
    planning_request = SuccessorPlanningRequest(
        baseline_identity_sha256=baseline.identity_sha256,
        mode=SuccessorUpdateMode.DAILY,
        source_sha="b" * 40,
        cutoff_utc="2026-08-12T00:00:00Z",
        as_of_utc="2026-08-13T00:00:00Z",
        workflow_run_id=501,
        workflow_run_attempt=2,
        requested_planning_scopes=(scope_contract,),
    )
    intent = SuccessorUpdateIntent(
        baseline_identity_sha256=baseline.identity_sha256,
        planning_generation_manifest_sha256=_digest("planning-manifest"),
        successor_execution_plan_sha256=_digest("execution-plan"),
        planned_route_replacement_bindings_sha256=_digest("planned-route-bindings"),
        mode=planning_request.mode,
        source_sha=planning_request.source_sha,
        cutoff_utc=planning_request.cutoff_utc,
        as_of_utc=planning_request.as_of_utc,
        requested_scopes=(scope_contract,),
    )
    transaction = SuccessorUpdateTransaction.candidate(
        generation=7,
        baseline=baseline,
        intent=intent,
    )
    scope = CaptureRunScope(
        semantic_source_sha=transaction.intent.source_sha,
        chain_id=transaction.baseline.chain_id,
        lane_id=transaction.generation_identity_sha256,
        workflow_run_id=planning_request.workflow_run_id,
        workflow_run_attempt=planning_request.workflow_run_attempt,
    )
    limits = _limits()
    generation_root = capture_base / transaction.generation_identity_sha256
    session = PrivateCaptureSession(
        generation_root,
        limits=limits,
        public_roots=(public_root,),
        scope=scope,
    )
    session.admit(
        estimated_checkpoint_bytes=50_000,
        monotonic_now_seconds=100.0,
        monotonic_deadline_seconds=200.0,
    )
    private_identity = session.seal()
    session.close()
    return _Harness(
        capture_base=capture_base,
        public_root=public_root,
        limits=limits,
        transaction=transaction,
        planning_request=planning_request,
        scope=scope,
        generation_root=generation_root.resolve(),
        private_identity=private_identity,
    )


def test_resolver_freshly_reinventories_and_releases_exact_generation(
    tmp_path: Path,
) -> None:
    harness = _harness(tmp_path)

    first = harness.verify()
    second = harness.verify()

    assert first.canonical_bytes == harness.private_identity.canonical_bytes
    assert second.canonical_bytes == first.canonical_bytes
    generation_stat = harness.generation_root.stat()
    probe = PrivateCaptureSession.open_existing(
        harness.generation_root,
        limits=harness.limits,
        public_roots=(harness.public_root,),
        scope=harness.scope,
        expected_root_identity=(generation_stat.st_dev, generation_stat.st_ino),
    )
    assert probe.restore_sealed_identity_if_present() == harness.private_identity
    probe.close()


def test_resolver_derives_workflow_coordinates_from_persisted_request_before_open(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    harness = _harness(tmp_path)
    foreign_request = replace(harness.planning_request, workflow_run_attempt=3)
    opened = False

    def forbidden(*_args: object, **_kwargs: object) -> PrivateCaptureSession:
        nonlocal opened
        opened = True
        raise AssertionError("foreign scope must fail before opening retained Bronze")

    monkeypatch.setattr(PrivateCaptureSession, "open_existing", forbidden)

    with pytest.raises(
        RetainedBronzeUpdateResolverError,
        match="expected private generation differs",
    ):
        harness.resolver().verify(
            transaction=harness.transaction,
            planning_request=foreign_request,
            candidate_public_root=harness.public_root,
            expected_public_root_identity=harness.public_identity,
            expected_identity=harness.private_identity,
        )
    assert opened is False


@pytest.mark.parametrize(
    ("field_name", "value"),
    [
        ("mode", SuccessorUpdateMode.MONTHLY),
        ("source_sha", "c" * 40),
        ("cutoff_utc", "2026-08-11T00:00:00Z"),
        ("as_of_utc", "2026-08-14T00:00:00Z"),
    ],
)
def test_resolver_rejects_planning_request_that_differs_from_final_transaction(
    tmp_path: Path,
    field_name: str,
    value: object,
) -> None:
    harness = _harness(tmp_path)
    foreign_request = replace(harness.planning_request, **{field_name: value})

    with pytest.raises(RetainedBronzeUpdateResolverError, match="planning request differs"):
        harness.resolver().verify(
            transaction=harness.transaction,
            planning_request=foreign_request,
            candidate_public_root=harness.public_root,
            expected_public_root_identity=harness.public_identity,
            expected_identity=harness.private_identity,
        )


def test_resolver_rejects_forged_path_free_identity_after_fresh_inventory(
    tmp_path: Path,
) -> None:
    harness = _harness(tmp_path)
    forged = replace(harness.private_identity, manifest_sha256=_digest("forged-manifest"))

    with pytest.raises(RetainedBronzeUpdateResolverError, match="fresh Bronze identity differs"):
        harness.resolver().verify(
            transaction=harness.transaction,
            planning_request=harness.planning_request,
            candidate_public_root=harness.public_root,
            expected_public_root_identity=harness.public_identity,
            expected_identity=forged,
        )


def test_resolver_rejects_tampered_bronze_and_releases_lock(tmp_path: Path) -> None:
    harness = _harness(tmp_path)
    manifest = harness.generation_root / "manifest.json"
    manifest.write_bytes(manifest.read_bytes() + b"tamper")

    with pytest.raises(RetainedBronzeUpdateResolverError, match="generation is invalid"):
        harness.verify()

    with pytest.raises((ExtractionError, ValueError)) as raised:
        PrivateCaptureSession(
            harness.generation_root,
            limits=harness.limits,
            public_roots=(harness.public_root,),
            scope=harness.scope,
        )
    assert "already has a writer" not in str(raised.value)


def test_resolver_rejects_wrong_public_inode_before_bronze_open(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    harness = _harness(tmp_path)
    opened = False

    def forbidden(*_args: object, **_kwargs: object) -> PrivateCaptureSession:
        nonlocal opened
        opened = True
        raise AssertionError("wrong public inode must fail before retained Bronze opens")

    monkeypatch.setattr(PrivateCaptureSession, "open_existing", forbidden)

    with pytest.raises(RetainedBronzeUpdateResolverError, match="expected inode"):
        harness.resolver().verify(
            transaction=harness.transaction,
            planning_request=harness.planning_request,
            candidate_public_root=harness.public_root,
            expected_public_root_identity=(
                harness.public_identity[0],
                harness.public_identity[1] + 1,
            ),
            expected_identity=harness.private_identity,
        )
    assert opened is False


def test_resolver_detects_public_root_swap_after_fresh_restore(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    harness = _harness(tmp_path)
    original = PrivateCaptureSession.restore_sealed_identity_if_present

    def restore_then_swap(
        session: PrivateCaptureSession,
    ) -> PrivateGenerationIdentity | None:
        restored = original(session)
        harness.public_root.rename(tmp_path / "retained-public-root")
        harness.public_root.mkdir(mode=0o755)
        return restored

    monkeypatch.setattr(
        PrivateCaptureSession,
        "restore_sealed_identity_if_present",
        restore_then_swap,
    )

    with pytest.raises(RetainedBronzeUpdateResolverError, match="public root changed identity"):
        harness.verify()


def test_resolver_pins_generation_inode_across_preopen_path_swap(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    harness = _harness(tmp_path)
    sibling = harness.generation_root.with_name("valid-generation-sibling")
    shutil.copytree(harness.generation_root, sibling)
    held = harness.generation_root.with_name("held-generation")
    original = PrivateCaptureSession.open_existing
    swapped = False

    def open_with_sibling_at_canonical_path(
        cls: type[PrivateCaptureSession],
        root: Path | str,
        **kwargs: object,
    ) -> PrivateCaptureSession:
        nonlocal swapped
        canonical = Path(root)
        canonical.rename(held)
        sibling.rename(canonical)
        swapped = True
        try:
            return original(
                root,
                limits=cast("BronzeLimits", kwargs["limits"]),
                public_roots=cast("tuple[Path | str, ...]", kwargs["public_roots"]),
                scope=cast("CaptureRunScope", kwargs["scope"]),
                expected_root_identity=cast(
                    "tuple[int, int]",
                    kwargs["expected_root_identity"],
                ),
            )
        finally:
            canonical.rename(sibling)
            held.rename(canonical)

    monkeypatch.setattr(
        PrivateCaptureSession,
        "open_existing",
        classmethod(open_with_sibling_at_canonical_path),
    )

    with pytest.raises(RetainedBronzeUpdateResolverError, match="generation is invalid"):
        harness.verify()
    assert swapped is True


def test_resolver_rejects_nonprivate_or_overlapping_roots(tmp_path: Path) -> None:
    harness = _harness(tmp_path)
    harness.capture_base.chmod(0o750)
    with pytest.raises(RetainedBronzeUpdateResolverError, match="owner-only 0700"):
        harness.resolver()
    harness.capture_base.chmod(0o700)

    capture_stat = harness.capture_base.stat()
    with pytest.raises(RetainedBronzeUpdateResolverError, match="must be disjoint"):
        harness.resolver().verify(
            transaction=harness.transaction,
            planning_request=harness.planning_request,
            candidate_public_root=harness.capture_base,
            expected_public_root_identity=(capture_stat.st_dev, capture_stat.st_ino),
            expected_identity=harness.private_identity,
        )

    symlink = tmp_path / "capture-alias"
    symlink.symlink_to(harness.capture_base, target_is_directory=True)
    with pytest.raises(RetainedBronzeUpdateResolverError, match="aliases or symlink"):
        RetainedBronzeUpdateResolver(symlink.absolute(), limits=harness.limits)


def test_overlap_detection_walks_casefolded_ancestor_inodes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    capture = Path("/volume/private-capture")
    differently_cased_public = Path("/VOLUME/PRIVATE-CAPTURE/candidate/public")
    capture_identity = (7, 11)
    public_identity = (7, 19)
    identities = {
        differently_cased_public: public_identity,
        differently_cased_public.parent: (7, 18),
        differently_cased_public.parent.parent: capture_identity,
        differently_cased_public.parent.parent.parent: (7, 3),
        Path("/VOLUME"): (7, 3),
        Path("/"): (7, 2),
    }

    def casefolded_stat(path: Path, *, follow_symlinks: bool) -> object:
        assert follow_symlinks is False
        device, inode = identities.get(Path(path), (99, hash(Path(path))))
        return SimpleNamespace(st_dev=device, st_ino=inode)

    monkeypatch.setattr(resolver_module.os, "stat", casefolded_stat)

    assert resolver_module._overlaps(
        capture,
        differently_cased_public,
        capture_identity,
        public_identity,
    )


@pytest.mark.parametrize(
    "invalid",
    [None, (1,), (1, -1), (True, 2), [1, 2]],
)
def test_resolver_rejects_invalid_public_inode_contract(
    tmp_path: Path,
    invalid: object,
) -> None:
    harness = _harness(tmp_path)

    with pytest.raises(RetainedBronzeUpdateResolverError, match="device, inode"):
        harness.resolver().verify(
            transaction=harness.transaction,
            planning_request=harness.planning_request,
            candidate_public_root=harness.public_root,
            expected_public_root_identity=cast("tuple[int, int]", invalid),
            expected_identity=harness.private_identity,
        )


_SEALED_LIVE_GAME_ID = "0024090123"


def _planned_binding(scope: RequestedRouteScope) -> PlannedRouteReplacementBinding:
    return PlannedRouteReplacementBinding(
        requested_scope_sha256=scope.identity_sha256,
        execution_dispatch_identity_sha256=canonical_sha256(
            {
                "endpoint_name": scope.endpoint_name,
                "parameters_sha256": scope.scope_sha256,
            }
        ),
        planning_dependency_identity_sha256s=(
            canonical_sha256(
                {
                    "planning_dependency": scope.endpoint_name,
                    "parameters_sha256": scope.scope_sha256,
                }
            ),
        ),
    )


def _live_scope(
    endpoint_name: str,
    route_id: str,
    parameters: dict[str, object],
) -> RequestedRouteScope:
    return RequestedRouteScope.from_parameters(
        endpoint_name=endpoint_name,
        route_id=route_id,
        route_contract_sha256=_digest(route_id),
        parameters=parameters,
        mutability=CallMutability.MUTABLE,
    )


def _live_scopes() -> tuple[RequestedRouteScope, ...]:
    return (
        _live_scope("live_score_board", "live_score_board:stg_live_score_board:0", {}),
        _live_scope("live_odds", "live_odds:stg_live_odds:0", {}),
        _live_scope(
            "live_play_by_play",
            "live_play_by_play:stg_live_play_by_play:0",
            {"game_id": _SEALED_LIVE_GAME_ID},
        ),
        _live_scope(
            "live_box_score",
            "live_box_score:stg_live_box_score_game_details:0",
            {"game_id": _SEALED_LIVE_GAME_ID},
        ),
    )


def _live_transaction(
    harness: _Harness,
    scopes: tuple[RequestedRouteScope, ...],
) -> SuccessorUpdateTransaction:
    bindings = tuple(_planned_binding(scope) for scope in scopes)
    intent = SuccessorUpdateIntent(
        baseline_identity_sha256=harness.transaction.baseline.identity_sha256,
        planning_generation_manifest_sha256=_digest("planning-manifest"),
        successor_execution_plan_sha256=_digest("execution-plan"),
        planned_route_replacement_bindings_sha256=(
            planned_route_replacement_bindings_sha256(bindings)
        ),
        mode=harness.transaction.intent.mode,
        source_sha=harness.transaction.intent.source_sha,
        cutoff_utc=harness.transaction.intent.cutoff_utc,
        as_of_utc=harness.transaction.intent.as_of_utc,
        requested_scopes=scopes,
    )
    return SuccessorUpdateTransaction.candidate(
        generation=harness.transaction.generation,
        baseline=harness.transaction.baseline,
        intent=intent,
    )


def _live_receipts(
    transaction: SuccessorUpdateTransaction,
    scopes: tuple[RequestedRouteScope, ...],
) -> tuple[ObservedDeltaReceipt, ...]:
    receipts: list[ObservedDeltaReceipt] = []
    for index, scope in enumerate(scopes):
        binding = _planned_binding(scope)
        marker = f"{index + 1:x}"
        receipts.append(
            ObservedDeltaReceipt(
                baseline_identity_sha256=transaction.baseline.identity_sha256,
                update_intent_sha256=transaction.intent.identity_sha256,
                source_sha=transaction.intent.source_sha,
                requested_scope_sha256=scope.identity_sha256,
                execution_dispatch_identity_sha256=(binding.execution_dispatch_identity_sha256),
                planning_dependency_identity_sha256s=(binding.planning_dependency_identity_sha256s),
                disposition=DeltaDisposition.OBSERVED,
                logical_call_receipt_sha256=marker * 64,
                prior_persisted_content_sha256="0" * 64,
                source_scope_replacement_sha256=f"{(int(marker, 16) + 8):x}" * 64,
                persisted_content_sha256=f"{(int(marker, 16) + 1):x}" * 64,
                persisted_schema_sha256=f"{(int(marker, 16) + 2):x}" * 64,
                persisted_row_count=12,
            )
        )
    return tuple(receipts)


def test_resolver_does_not_treat_retained_bronze_as_live_update_closure(
    tmp_path: Path,
) -> None:
    harness = _harness(tmp_path)
    restored = harness.verify()
    assert restored.canonical_bytes == harness.private_identity.canonical_bytes
    assert (
        harness.resolver().require_update_replacement_delta_closure(
            transaction=harness.transaction,
            planning_request=harness.planning_request,
            evidence_kind=UpdateScopeClosureEvidenceKind.RETAINED_BRONZE_SEAL,
        )
        == ()
    )

    live_scopes = _live_scopes()
    live_transaction = _live_transaction(harness, live_scopes)
    with pytest.raises(
        RetainedBronzeUpdateResolverError,
        match="retained_bronze_seal cannot close",
    ):
        harness.resolver().require_update_replacement_delta_closure(
            transaction=live_transaction,
            planning_request=harness.planning_request,
            evidence_kind=UpdateScopeClosureEvidenceKind.RETAINED_BRONZE_SEAL,
        )


@pytest.mark.parametrize(
    "evidence_kind",
    [
        UpdateScopeClosureEvidenceKind.PLANNING_WAVE_CAPTURE,
        UpdateScopeClosureEvidenceKind.JOURNAL_COMPLETION,
        UpdateScopeClosureEvidenceKind.CAPTURE_COMPLETION,
    ],
)
def test_resolver_rejects_planning_journal_or_capture_as_live_closure(
    tmp_path: Path,
    evidence_kind: UpdateScopeClosureEvidenceKind,
) -> None:
    harness = _harness(tmp_path)
    live_scopes = _live_scopes()
    live_transaction = _live_transaction(harness, live_scopes)
    receipts = _live_receipts(live_transaction, live_scopes)

    with pytest.raises(
        RetainedBronzeUpdateResolverError,
        match=f"{evidence_kind.value} cannot close",
    ):
        harness.resolver().require_update_replacement_delta_closure(
            transaction=live_transaction,
            planning_request=harness.planning_request,
            observed_delta_receipts=receipts,
            sealed_live_game_ids=(_SEALED_LIVE_GAME_ID,),
            evidence_kind=evidence_kind,
        )


def test_resolver_closes_live_and_scoreboard_scopes_only_with_delta_receipts(
    tmp_path: Path,
) -> None:
    harness = _harness(tmp_path)
    live_scopes = _live_scopes()
    live_transaction = _live_transaction(harness, live_scopes)
    receipts = _live_receipts(live_transaction, live_scopes)

    closed = harness.resolver().require_update_replacement_delta_closure(
        transaction=live_transaction,
        planning_request=harness.planning_request,
        observed_delta_receipts=receipts,
        sealed_live_game_ids=(_SEALED_LIVE_GAME_ID,),
        evidence_kind=UpdateScopeClosureEvidenceKind.OBSERVED_DELTA_REPLACEMENT,
    )
    assert closed == tuple(sorted(receipts, key=lambda receipt: receipt.requested_scope_sha256))

    with pytest.raises(
        RetainedBronzeUpdateResolverError,
        match="typed-zero sealed live game",
    ):
        harness.resolver().require_update_replacement_delta_closure(
            transaction=live_transaction,
            planning_request=harness.planning_request,
            observed_delta_receipts=receipts,
            sealed_live_game_ids=(),
            evidence_kind=UpdateScopeClosureEvidenceKind.OBSERVED_DELTA_REPLACEMENT,
        )
    with pytest.raises(
        RetainedBronzeUpdateResolverError,
        match="not bound to the sealed live",
    ):
        harness.resolver().require_update_replacement_delta_closure(
            transaction=live_transaction,
            planning_request=harness.planning_request,
            observed_delta_receipts=receipts,
            sealed_live_game_ids=("0024090999",),
            evidence_kind=UpdateScopeClosureEvidenceKind.OBSERVED_DELTA_REPLACEMENT,
        )


def test_resolver_live_closure_still_requires_planning_request_match(
    tmp_path: Path,
) -> None:
    harness = _harness(tmp_path)
    live_scopes = _live_scopes()
    live_transaction = _live_transaction(harness, live_scopes)
    receipts = _live_receipts(live_transaction, live_scopes)
    foreign_request = replace(harness.planning_request, workflow_run_attempt=9)

    with pytest.raises(RetainedBronzeUpdateResolverError, match="planning request differs"):
        harness.resolver().require_update_replacement_delta_closure(
            transaction=live_transaction,
            planning_request=replace(foreign_request, source_sha="d" * 40),
            observed_delta_receipts=receipts,
            sealed_live_game_ids=(_SEALED_LIVE_GAME_ID,),
            evidence_kind=UpdateScopeClosureEvidenceKind.OBSERVED_DELTA_REPLACEMENT,
        )
