from __future__ import annotations

from dataclasses import replace
from typing import TYPE_CHECKING, Any, cast

import pytest

if TYPE_CHECKING:
    from collections.abc import Callable

from nbadb.kaggle.release_control import (
    CI_WORKFLOW_PATH,
    REQUIRED_METADATA_CI_JOBS,
    CIDispatchReceipt,
    CIJobReceipt,
    CIRunReceipt,
    DurableLedgerState,
    MetadataHeadEvidence,
    PublicationSuccessProof,
    PublisherAuthority,
    PublisherRecoveryRequest,
    ReleaseAction,
    ReleaseControlError,
    ReleaseDecisionReason,
    ReleaseStateEvidence,
    decide_publication_recovery,
    validate_metadata_head,
)

_REPOSITORY = "wyattowalsh/nbadb"
_PUBLISH_WORKFLOW = ".github/workflows/full-extraction.yml"
_SOURCE_SHA = "a" * 40
_METADATA_HEAD_SHA = "b" * 40
_BUNDLE_SHA256 = "1" * 64
_INTENT_ID = "2" * 64


def _authority(
    *,
    repository: str = _REPOSITORY,
    workflow_path: str = _PUBLISH_WORKFLOW,
    run_id: int = 101,
    run_attempt: int = 1,
    publisher_job_id: int = 1001,
    source_sha: str = _SOURCE_SHA,
    assured_bundle_sha256: str = _BUNDLE_SHA256,
    intent_id: str = _INTENT_ID,
) -> PublisherAuthority:
    return PublisherAuthority(
        repository=repository,
        workflow_path=workflow_path,
        run_id=run_id,
        run_attempt=run_attempt,
        publisher_job_id=publisher_job_id,
        source_sha=source_sha,
        assured_bundle_sha256=assured_bundle_sha256,
        intent_id=intent_id,
    )


def _success(
    *,
    source_sha: str = _SOURCE_SHA,
    assured_bundle_sha256: str = _BUNDLE_SHA256,
    intent_id: str = _INTENT_ID,
    resolved_version: int = 42,
    publication_marker_sha256: str = "3" * 64,
    resource_inventory_sha256: str = "4" * 64,
    readback_fingerprint: str = "5" * 64,
    resolution_digest: str = "6" * 64,
) -> PublicationSuccessProof:
    return PublicationSuccessProof(
        source_sha=source_sha,
        assured_bundle_sha256=assured_bundle_sha256,
        intent_id=intent_id,
        resolved_version=resolved_version,
        publication_marker_sha256=publication_marker_sha256,
        resource_inventory_sha256=resource_inventory_sha256,
        readback_fingerprint=readback_fingerprint,
        resolution_digest=resolution_digest,
    )


def _evidence(
    state: DurableLedgerState,
    *,
    authority: PublisherAuthority | None = None,
    publisher_terminal: bool = True,
    writer_inventory_stable: bool = True,
    ledger_inventory_stable: bool = True,
    active_writers: tuple[PublisherAuthority, ...] = (),
    competing_writer_detected: bool = False,
    zero_active_replay_used: bool = False,
    durable_success: PublicationSuccessProof | None = None,
    remote_success: PublicationSuccessProof | None = None,
) -> ReleaseStateEvidence:
    return ReleaseStateEvidence(
        authority=authority or _authority(),
        ledger_state=state,
        publisher_terminal=publisher_terminal,
        writer_inventory_stable=writer_inventory_stable,
        ledger_inventory_stable=ledger_inventory_stable,
        active_writers=active_writers,
        competing_writer_detected=competing_writer_detected,
        zero_active_replay_used=zero_active_replay_used,
        durable_success=durable_success,
        remote_success=remote_success,
    )


def _request(
    *,
    target: PublisherAuthority | None = None,
    receipt_bound: bool = True,
    pending_takeover_durable: bool = False,
    request_kaggle_upload: bool = False,
) -> PublisherRecoveryRequest:
    return PublisherRecoveryRequest(
        target=target or _authority(),
        receipt_bound=receipt_bound,
        pending_takeover_durable=pending_takeover_durable,
        request_kaggle_upload=request_kaggle_upload,
    )


def _new_replay_target(**updates: object) -> PublisherAuthority:
    values: dict[str, object] = {
        "repository": _REPOSITORY,
        "workflow_path": _PUBLISH_WORKFLOW,
        "run_id": 202,
        "run_attempt": 1,
        "publisher_job_id": 2002,
        "source_sha": _SOURCE_SHA,
        "assured_bundle_sha256": _BUNDLE_SHA256,
        "intent_id": _INTENT_ID,
    }
    values.update(updates)
    return PublisherAuthority(**values)  # type: ignore[arg-type]


def test_absent_intent_admits_one_new_receipt_bound_zero_active_replay() -> None:
    decision = decide_publication_recovery(
        _evidence(DurableLedgerState.ABSENT),
        _request(target=_new_replay_target()),
    )

    assert decision.action is ReleaseAction.NEW_ZERO_ACTIVE_REPLAY
    assert decision.reason is ReleaseDecisionReason.PRE_INTENT_REPLAY_ALLOWED
    assert decision.kaggle_upload_allowed is False


@pytest.mark.parametrize(
    ("evidence", "recovery_request", "reason"),
    [
        (
            _evidence(DurableLedgerState.ABSENT, writer_inventory_stable=False),
            _request(target=_new_replay_target()),
            ReleaseDecisionReason.INVENTORY_NOT_STABLE,
        ),
        (
            _evidence(DurableLedgerState.ABSENT, ledger_inventory_stable=False),
            _request(target=_new_replay_target()),
            ReleaseDecisionReason.INVENTORY_NOT_STABLE,
        ),
        (
            _evidence(DurableLedgerState.ABSENT, publisher_terminal=False),
            _request(target=_new_replay_target()),
            ReleaseDecisionReason.PUBLISHER_NOT_TERMINAL,
        ),
        (
            _evidence(
                DurableLedgerState.ABSENT,
                active_writers=(_authority(run_id=303, publisher_job_id=3003),),
            ),
            _request(target=_new_replay_target()),
            ReleaseDecisionReason.ACTIVE_WRITER_EXISTS,
        ),
        (
            _evidence(DurableLedgerState.ABSENT, competing_writer_detected=True),
            _request(target=_new_replay_target()),
            ReleaseDecisionReason.COMPETING_WRITER_EXISTS,
        ),
        (
            _evidence(DurableLedgerState.ABSENT),
            _request(target=_new_replay_target(), receipt_bound=False),
            ReleaseDecisionReason.RECOVERY_RECEIPT_NOT_BOUND,
        ),
        (
            _evidence(DurableLedgerState.ABSENT, zero_active_replay_used=True),
            _request(target=_new_replay_target()),
            ReleaseDecisionReason.ZERO_ACTIVE_REPLAY_ALREADY_USED,
        ),
        (
            _evidence(DurableLedgerState.ABSENT),
            _request(target=_new_replay_target(run_id=101)),
            ReleaseDecisionReason.RECOVERY_IS_NOT_A_NEW_RUN,
        ),
        (
            _evidence(DurableLedgerState.ABSENT),
            _request(target=_new_replay_target(publisher_job_id=1001)),
            ReleaseDecisionReason.RECOVERY_IS_NOT_A_NEW_RUN,
        ),
        (
            _evidence(DurableLedgerState.ABSENT),
            _request(target=_new_replay_target(), request_kaggle_upload=True),
            ReleaseDecisionReason.DURABLE_INTENT_REQUIRED,
        ),
        (
            _evidence(DurableLedgerState.ABSENT, remote_success=_success()),
            _request(target=_new_replay_target()),
            ReleaseDecisionReason.SUCCESS_EVIDENCE_INCONSISTENT,
        ),
    ],
)
def test_pre_intent_replay_blocks_every_unsafe_precondition(
    evidence: ReleaseStateEvidence,
    recovery_request: PublisherRecoveryRequest,
    reason: ReleaseDecisionReason,
) -> None:
    decision = decide_publication_recovery(evidence, recovery_request)

    assert decision.action is ReleaseAction.BLOCKED
    assert decision.reason is reason
    assert decision.kaggle_upload_allowed is False


@pytest.mark.parametrize(
    "target",
    [
        _new_replay_target(repository="someone/else"),
        _new_replay_target(workflow_path=".github/workflows/daily-update.yml"),
        _new_replay_target(source_sha="b" * 40),
        _new_replay_target(assured_bundle_sha256="7" * 64),
        _new_replay_target(intent_id="8" * 64),
    ],
)
def test_pre_intent_replay_rejects_cross_semantic_provenance(
    target: PublisherAuthority,
) -> None:
    decision = decide_publication_recovery(
        _evidence(DurableLedgerState.ABSENT),
        _request(target=target),
    )

    assert decision.action is ReleaseAction.BLOCKED
    assert decision.reason is ReleaseDecisionReason.RECOVERY_PROVENANCE_MISMATCH


def test_pending_intent_allows_only_durable_cross_run_takeover_claim() -> None:
    target = _new_replay_target()
    decision = decide_publication_recovery(
        _evidence(DurableLedgerState.PENDING),
        _request(
            target=target,
            pending_takeover_durable=True,
            request_kaggle_upload=True,
        ),
    )

    assert decision.action is ReleaseAction.CLAIM_PENDING_TAKEOVER
    assert decision.reason is ReleaseDecisionReason.PENDING_TAKEOVER_DURABLY_CLAIMABLE
    assert decision.kaggle_upload_allowed is True


def test_pending_intent_blocks_upload_without_durable_takeover() -> None:
    decision = decide_publication_recovery(
        _evidence(DurableLedgerState.PENDING),
        _request(target=_new_replay_target(), request_kaggle_upload=True),
    )

    assert decision.action is ReleaseAction.BLOCKED
    assert decision.reason is ReleaseDecisionReason.PENDING_TAKEOVER_REQUIRED
    assert decision.kaggle_upload_allowed is False


def test_pending_intent_with_exact_remote_success_is_read_only_reconciliation() -> None:
    evidence = _evidence(DurableLedgerState.PENDING, remote_success=_success())

    decision = decide_publication_recovery(evidence, _request())
    upload_attempt = decide_publication_recovery(
        evidence,
        _request(request_kaggle_upload=True),
    )

    assert decision.action is ReleaseAction.RECONCILE_WITHOUT_UPLOAD
    assert decision.kaggle_upload_allowed is False
    assert upload_attempt.action is ReleaseAction.BLOCKED
    assert upload_attempt.reason is ReleaseDecisionReason.PUBLICATION_ALREADY_SUCCEEDED


def test_in_progress_intent_is_reconciliation_only() -> None:
    evidence = _evidence(DurableLedgerState.IN_PROGRESS)

    decision = decide_publication_recovery(evidence, _request())
    upload_attempt = decide_publication_recovery(
        evidence,
        _request(request_kaggle_upload=True),
    )

    assert decision.action is ReleaseAction.RECONCILE_WITHOUT_UPLOAD
    assert decision.kaggle_upload_allowed is False
    assert upload_attempt.action is ReleaseAction.BLOCKED
    assert upload_attempt.reason is ReleaseDecisionReason.RECONCILIATION_ONLY


@pytest.mark.parametrize(
    "target",
    [
        _authority(source_sha="b" * 40),
        _authority(assured_bundle_sha256="7" * 64),
        _authority(intent_id="8" * 64),
    ],
)
@pytest.mark.parametrize(
    "state",
    [DurableLedgerState.PENDING, DurableLedgerState.IN_PROGRESS],
)
def test_durable_intent_rejects_cross_semantic_provenance(
    state: DurableLedgerState,
    target: PublisherAuthority,
) -> None:
    decision = decide_publication_recovery(_evidence(state), _request(target=target))

    assert decision.action is ReleaseAction.BLOCKED
    assert decision.reason is ReleaseDecisionReason.RECOVERY_PROVENANCE_MISMATCH


@pytest.mark.parametrize(
    "target",
    [_authority(run_id=102), _authority(run_attempt=2), _authority(publisher_job_id=1002)],
)
def test_in_progress_allows_cross_run_no_upload_reconciliation(
    target: PublisherAuthority,
) -> None:
    decision = decide_publication_recovery(
        _evidence(DurableLedgerState.IN_PROGRESS),
        _request(target=target),
    )

    assert decision.action is ReleaseAction.RECONCILE_WITHOUT_UPLOAD
    assert decision.kaggle_upload_allowed is False


def test_durable_and_remote_success_continue_post_publication_only() -> None:
    success = _success()
    evidence = _evidence(
        DurableLedgerState.SUCCESS,
        durable_success=success,
        remote_success=success,
    )

    decision = decide_publication_recovery(evidence, _request())

    assert decision.action is ReleaseAction.CONTINUE_POST_PUBLICATION
    assert decision.reason is ReleaseDecisionReason.EXACT_PUBLICATION_ALREADY_SUCCEEDED
    assert decision.kaggle_upload_allowed is False


def test_exact_success_rejects_every_new_kaggle_upload_attempt() -> None:
    success = _success()
    decision = decide_publication_recovery(
        _evidence(
            DurableLedgerState.SUCCESS,
            durable_success=success,
            remote_success=success,
        ),
        _request(request_kaggle_upload=True),
    )

    assert decision.action is ReleaseAction.BLOCKED
    assert decision.reason is ReleaseDecisionReason.PUBLICATION_ALREADY_SUCCEEDED


@pytest.mark.parametrize(
    ("durable_success", "remote_success"),
    [
        (None, _success()),
        (_success(), None),
        (_success(source_sha="b" * 40), _success()),
        (_success(), _success(assured_bundle_sha256="7" * 64)),
        (_success(), _success(intent_id="8" * 64)),
        (_success(), _success(resolved_version=43)),
        (_success(), _success(publication_marker_sha256="7" * 64)),
        (_success(), _success(resource_inventory_sha256="7" * 64)),
        (_success(), _success(readback_fingerprint="7" * 64)),
        (_success(), _success(resolution_digest="7" * 64)),
    ],
)
def test_success_requires_exact_matching_durable_and_remote_proofs(
    durable_success: PublicationSuccessProof | None,
    remote_success: PublicationSuccessProof | None,
) -> None:
    decision = decide_publication_recovery(
        _evidence(
            DurableLedgerState.SUCCESS,
            durable_success=durable_success,
            remote_success=remote_success,
        ),
        _request(),
    )

    assert decision.action is ReleaseAction.BLOCKED
    assert decision.reason is ReleaseDecisionReason.SUCCESS_EVIDENCE_INCONSISTENT


def test_nonterminal_ledger_state_rejects_durable_success_receipt() -> None:
    decision = decide_publication_recovery(
        _evidence(DurableLedgerState.PENDING, durable_success=_success()),
        _request(),
    )

    assert decision.action is ReleaseAction.BLOCKED
    assert decision.reason is ReleaseDecisionReason.SUCCESS_EVIDENCE_INCONSISTENT


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("repository", "invalid"),
        ("workflow_path", "../ci.yml"),
        ("run_id", True),
        ("run_id", 0),
        ("run_attempt", 0),
        ("publisher_job_id", 0),
        ("source_sha", "A" * 40),
        ("assured_bundle_sha256", "1" * 63),
        ("intent_id", "z" * 64),
    ],
)
def test_publisher_authority_rejects_malformed_identity(field: str, value: object) -> None:
    values: dict[str, object] = {
        "repository": _REPOSITORY,
        "workflow_path": _PUBLISH_WORKFLOW,
        "run_id": 101,
        "run_attempt": 1,
        "publisher_job_id": 1001,
        "source_sha": _SOURCE_SHA,
        "assured_bundle_sha256": _BUNDLE_SHA256,
        "intent_id": _INTENT_ID,
    }
    values[field] = value

    with pytest.raises(ReleaseControlError):
        PublisherAuthority(**values)  # type: ignore[arg-type]


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("source_sha", "a" * 39),
        ("assured_bundle_sha256", "1" * 63),
        ("intent_id", "2" * 65),
        ("resolved_version", True),
        ("resolved_version", 0),
        ("publication_marker_sha256", "3" * 63),
        ("resource_inventory_sha256", "4" * 63),
        ("readback_fingerprint", "5" * 63),
        ("resolution_digest", "6" * 63),
    ],
)
def test_publication_success_rejects_malformed_receipt(field: str, value: object) -> None:
    values: dict[str, object] = {
        "source_sha": _SOURCE_SHA,
        "assured_bundle_sha256": _BUNDLE_SHA256,
        "intent_id": _INTENT_ID,
        "resolved_version": 42,
        "publication_marker_sha256": "3" * 64,
        "resource_inventory_sha256": "4" * 64,
        "readback_fingerprint": "5" * 64,
        "resolution_digest": "6" * 64,
    }
    values[field] = value

    with pytest.raises(ReleaseControlError):
        PublicationSuccessProof(**values)  # type: ignore[arg-type]


@pytest.mark.parametrize(
    "field",
    [
        "publisher_terminal",
        "writer_inventory_stable",
        "ledger_inventory_stable",
        "competing_writer_detected",
        "zero_active_replay_used",
    ],
)
def test_release_evidence_rejects_non_boolean_flags(field: str) -> None:
    values: dict[str, object] = {
        "authority": _authority(),
        "ledger_state": DurableLedgerState.ABSENT,
        "publisher_terminal": True,
        "writer_inventory_stable": True,
        "ledger_inventory_stable": True,
        "competing_writer_detected": False,
        "zero_active_replay_used": False,
    }
    values[field] = 1

    with pytest.raises(ReleaseControlError):
        ReleaseStateEvidence(**cast("Any", values))


def test_release_evidence_rejects_raw_state_and_ambiguous_writer_inventory() -> None:
    with pytest.raises(ReleaseControlError, match="ledger_state"):
        replace(_evidence(DurableLedgerState.ABSENT), ledger_state="absent")  # type: ignore[arg-type]
    with pytest.raises(ReleaseControlError, match="tuple"):
        replace(_evidence(DurableLedgerState.ABSENT), active_writers=[])  # type: ignore[arg-type]
    with pytest.raises(ReleaseControlError, match="invalid evidence"):
        replace(_evidence(DurableLedgerState.ABSENT), active_writers=(object(),))  # type: ignore[arg-type]
    writer = _authority(run_id=303, publisher_job_id=3003)
    with pytest.raises(ReleaseControlError, match="ambiguous duplicate"):
        replace(
            _evidence(DurableLedgerState.ABSENT),
            active_writers=(writer, writer),
        )


@pytest.mark.parametrize(
    "field", ["receipt_bound", "pending_takeover_durable", "request_kaggle_upload"]
)
def test_recovery_request_rejects_non_boolean_flags(field: str) -> None:
    values: dict[str, object] = {
        "target": _authority(),
        "receipt_bound": True,
        "pending_takeover_durable": False,
        "request_kaggle_upload": False,
    }
    values[field] = 1

    with pytest.raises(ReleaseControlError):
        PublisherRecoveryRequest(**values)  # type: ignore[arg-type]


def test_decider_rejects_untyped_inputs() -> None:
    with pytest.raises(ReleaseControlError, match="evidence"):
        decide_publication_recovery(cast("Any", object()), _request())
    with pytest.raises(ReleaseControlError, match="request"):
        decide_publication_recovery(
            _evidence(DurableLedgerState.ABSENT),
            cast("Any", object()),
        )


def _metadata_head(
    *,
    repository: str = _REPOSITORY,
    source_sha: str = _SOURCE_SHA,
    metadata_head_sha: str = _METADATA_HEAD_SHA,
    parent_shas: tuple[str, ...] = (_SOURCE_SHA,),
    changed_files: tuple[str, ...] = ("dataset-metadata.json",),
    byte_reproducible: bool = True,
) -> MetadataHeadEvidence:
    return MetadataHeadEvidence(
        repository=repository,
        source_sha=source_sha,
        metadata_head_sha=metadata_head_sha,
        parent_shas=parent_shas,
        changed_files=changed_files,
        byte_reproducible=byte_reproducible,
    )


def _dispatch(
    *,
    repository: str = _REPOSITORY,
    workflow_id: int = 77,
    workflow_path: str = CI_WORKFLOW_PATH,
    run_id: int = 707,
    head_sha: str = _METADATA_HEAD_SHA,
    event: str = "workflow_dispatch",
    explicitly_dispatched: bool = True,
) -> CIDispatchReceipt:
    return CIDispatchReceipt(
        repository=repository,
        workflow_id=workflow_id,
        workflow_path=workflow_path,
        run_id=run_id,
        head_sha=head_sha,
        event=event,
        explicitly_dispatched=explicitly_dispatched,
    )


def _jobs(
    *,
    run_id: int = 707,
    run_attempt: int = 1,
    head_sha: str = _METADATA_HEAD_SHA,
) -> tuple[CIJobReceipt, ...]:
    return tuple(
        CIJobReceipt(
            name=name,
            job_id=800 + index,
            run_id=run_id,
            run_attempt=run_attempt,
            head_sha=head_sha,
            status="completed",
            conclusion="success",
        )
        for index, name in enumerate(sorted(REQUIRED_METADATA_CI_JOBS))
    )


def _ci_run(
    *,
    repository: str = _REPOSITORY,
    workflow_id: int = 77,
    workflow_path: str = CI_WORKFLOW_PATH,
    run_id: int = 707,
    run_attempt: int = 1,
    head_sha: str = _METADATA_HEAD_SHA,
    event: str = "workflow_dispatch",
    directly_verified: bool = True,
    jobs: tuple[CIJobReceipt, ...] | None = None,
) -> CIRunReceipt:
    return CIRunReceipt(
        repository=repository,
        workflow_id=workflow_id,
        workflow_path=workflow_path,
        run_id=run_id,
        run_attempt=run_attempt,
        head_sha=head_sha,
        event=event,
        directly_verified=directly_verified,
        jobs=_jobs(run_id=run_id, run_attempt=run_attempt, head_sha=head_sha)
        if jobs is None
        else jobs,
    )


def test_unchanged_metadata_resolves_to_frozen_source_without_ci() -> None:
    head = _metadata_head(
        metadata_head_sha=_SOURCE_SHA,
        parent_shas=(),
        changed_files=(),
    )

    validation = validate_metadata_head(head)

    assert validation.metadata_head_sha == _SOURCE_SHA
    assert validation.metadata_child_created is False
    assert validation.ci_run_id is None


@pytest.mark.parametrize(
    "head",
    [
        _metadata_head(
            metadata_head_sha=_SOURCE_SHA,
            parent_shas=(_SOURCE_SHA,),
            changed_files=(),
        ),
        _metadata_head(
            metadata_head_sha=_SOURCE_SHA,
            parent_shas=(),
            changed_files=("dataset-metadata.json",),
        ),
        _metadata_head(
            metadata_head_sha=_SOURCE_SHA,
            parent_shas=(),
            changed_files=(),
            byte_reproducible=False,
        ),
    ],
)
def test_unchanged_metadata_rejects_inconsistent_commit_evidence(
    head: MetadataHeadEvidence,
) -> None:
    with pytest.raises(ReleaseControlError, match="unchanged"):
        validate_metadata_head(head)


def test_unchanged_metadata_rejects_spurious_ci_claim() -> None:
    head = _metadata_head(
        metadata_head_sha=_SOURCE_SHA,
        parent_shas=(),
        changed_files=(),
    )

    with pytest.raises(ReleaseControlError, match="must not claim"):
        validate_metadata_head(head, dispatch=_dispatch(), ci_run=_ci_run())


def test_direct_metadata_only_child_requires_exact_explicit_ci_success() -> None:
    validation = validate_metadata_head(
        _metadata_head(),
        dispatch=_dispatch(),
        ci_run=_ci_run(),
    )

    assert validation.metadata_head_sha == _METADATA_HEAD_SHA
    assert validation.metadata_child_created is True
    assert validation.ci_run_id == 707


@pytest.mark.parametrize(
    ("head", "message"),
    [
        (_metadata_head(parent_shas=()), "direct non-merge"),
        (_metadata_head(parent_shas=("c" * 40,)), "direct non-merge"),
        (_metadata_head(parent_shas=(_SOURCE_SHA, "c" * 40)), "direct non-merge"),
        (_metadata_head(changed_files=()), "allowlisted"),
        (_metadata_head(changed_files=("README.md",)), "allowlisted"),
        (_metadata_head(byte_reproducible=False), "byte-reproducible"),
    ],
)
def test_metadata_child_rejects_wrong_shape_or_files(
    head: MetadataHeadEvidence,
    message: str,
) -> None:
    with pytest.raises(ReleaseControlError, match=message):
        validate_metadata_head(head, dispatch=_dispatch(), ci_run=_ci_run())


@pytest.mark.parametrize(
    ("dispatch", "ci_run"),
    [
        (None, _ci_run()),
        (_dispatch(), None),
        (None, None),
    ],
)
def test_metadata_child_requires_both_dispatch_and_direct_run_receipts(
    dispatch: CIDispatchReceipt | None,
    ci_run: CIRunReceipt | None,
) -> None:
    with pytest.raises(ReleaseControlError, match="requires explicit"):
        validate_metadata_head(_metadata_head(), dispatch=dispatch, ci_run=ci_run)


@pytest.mark.parametrize(
    "dispatch",
    [
        _dispatch(explicitly_dispatched=False),
        _dispatch(event="push"),
        _dispatch(workflow_path=".github/workflows/daily-update.yml"),
    ],
)
def test_metadata_ci_rejects_implicit_push_or_wrong_workflow_dispatch(
    dispatch: CIDispatchReceipt,
) -> None:
    with pytest.raises(ReleaseControlError, match="explicitly dispatched"):
        validate_metadata_head(_metadata_head(), dispatch=dispatch, ci_run=_ci_run())


@pytest.mark.parametrize(
    "ci_run",
    [
        _ci_run(directly_verified=False),
        _ci_run(event="push"),
        _ci_run(workflow_path=".github/workflows/daily-update.yml"),
    ],
)
def test_metadata_ci_rejects_implicit_or_unverified_direct_run(
    ci_run: CIRunReceipt,
) -> None:
    with pytest.raises(ReleaseControlError, match="directly verified"):
        validate_metadata_head(_metadata_head(), dispatch=_dispatch(), ci_run=ci_run)


@pytest.mark.parametrize(
    "ci_run",
    [
        _ci_run(repository="someone/else"),
        _ci_run(workflow_id=78),
        _ci_run(run_id=708),
        _ci_run(head_sha="c" * 40),
    ],
)
def test_metadata_ci_rejects_dispatch_direct_run_provenance_drift(
    ci_run: CIRunReceipt,
) -> None:
    with pytest.raises(ReleaseControlError, match="provenance differ"):
        validate_metadata_head(_metadata_head(), dispatch=_dispatch(), ci_run=ci_run)


def test_metadata_ci_rejects_a_rerun_attempt_even_when_all_jobs_match() -> None:
    with pytest.raises(ReleaseControlError, match="not directly verified"):
        validate_metadata_head(
            _metadata_head(),
            dispatch=_dispatch(),
            ci_run=_ci_run(run_attempt=2),
        )


@pytest.mark.parametrize(
    "dispatch",
    [
        _dispatch(repository="someone/else"),
        _dispatch(head_sha="c" * 40),
    ],
)
def test_metadata_ci_rejects_cross_repository_or_cross_head_dispatch(
    dispatch: CIDispatchReceipt,
) -> None:
    matching_run = _ci_run(
        repository=dispatch.repository,
        head_sha=dispatch.head_sha,
    )

    with pytest.raises(ReleaseControlError, match="exact metadata head"):
        validate_metadata_head(_metadata_head(), dispatch=dispatch, ci_run=matching_run)


def test_metadata_ci_rejects_missing_or_extra_required_jobs() -> None:
    jobs = _jobs()

    for inventory in (
        jobs[:-1],
        (*jobs, replace(jobs[-1], name="extra", job_id=9999)),
    ):
        with pytest.raises(ReleaseControlError, match="incomplete"):
            validate_metadata_head(
                _metadata_head(),
                dispatch=_dispatch(),
                ci_run=_ci_run(jobs=inventory),
            )


def test_metadata_ci_rejects_duplicate_job_name_or_id() -> None:
    jobs = _jobs()
    duplicate_name = (*jobs[:-1], replace(jobs[-1], name=jobs[0].name))
    duplicate_id = (*jobs[:-1], replace(jobs[-1], job_id=jobs[0].job_id))

    for inventory in (duplicate_name, duplicate_id):
        with pytest.raises(ReleaseControlError, match="ambiguous"):
            validate_metadata_head(
                _metadata_head(),
                dispatch=_dispatch(),
                ci_run=_ci_run(jobs=inventory),
            )


@pytest.mark.parametrize(
    "mutated_job",
    [
        replace(_jobs()[0], run_id=708),
        replace(_jobs()[0], run_attempt=2),
        replace(_jobs()[0], head_sha="c" * 40),
    ],
)
def test_metadata_ci_rejects_cross_provenance_jobs(mutated_job: CIJobReceipt) -> None:
    jobs = _jobs()
    inventory = (mutated_job, *jobs[1:])

    with pytest.raises(ReleaseControlError, match="job provenance"):
        validate_metadata_head(
            _metadata_head(),
            dispatch=_dispatch(),
            ci_run=_ci_run(jobs=inventory),
        )


@pytest.mark.parametrize(
    "mutated_job",
    [
        replace(_jobs()[0], status="in_progress", conclusion="success"),
        replace(_jobs()[0], status="completed", conclusion="failure"),
    ],
)
def test_metadata_ci_requires_every_required_job_to_succeed(
    mutated_job: CIJobReceipt,
) -> None:
    jobs = _jobs()
    inventory = (mutated_job, *jobs[1:])

    with pytest.raises(ReleaseControlError, match="did not succeed"):
        validate_metadata_head(
            _metadata_head(),
            dispatch=_dispatch(),
            ci_run=_ci_run(jobs=inventory),
        )


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("repository", "invalid"),
        ("source_sha", "a" * 39),
        ("metadata_head_sha", "b" * 39),
        ("parent_shas", [_SOURCE_SHA]),
        ("changed_files", ["dataset-metadata.json"]),
        ("byte_reproducible", 1),
    ],
)
def test_metadata_head_rejects_malformed_fields(field: str, value: object) -> None:
    values: dict[str, object] = {
        "repository": _REPOSITORY,
        "source_sha": _SOURCE_SHA,
        "metadata_head_sha": _METADATA_HEAD_SHA,
        "parent_shas": (_SOURCE_SHA,),
        "changed_files": ("dataset-metadata.json",),
        "byte_reproducible": True,
    }
    values[field] = value

    with pytest.raises(ReleaseControlError):
        MetadataHeadEvidence(**values)  # type: ignore[arg-type]


@pytest.mark.parametrize(
    "changed_file",
    ["", "/dataset-metadata.json", "../dataset-metadata.json", "a\\b", "a//b", "a/./b"],
)
def test_metadata_head_rejects_unsafe_changed_file_paths(changed_file: str) -> None:
    with pytest.raises(ReleaseControlError, match="changed file"):
        _metadata_head(changed_files=(changed_file,))


def test_metadata_head_rejects_duplicate_parent_or_file_receipts() -> None:
    with pytest.raises(ReleaseControlError, match="parent_shas contains duplicates"):
        _metadata_head(parent_shas=(_SOURCE_SHA, _SOURCE_SHA))
    with pytest.raises(ReleaseControlError, match="changed_files contains duplicates"):
        _metadata_head(changed_files=("dataset-metadata.json", "dataset-metadata.json"))


@pytest.mark.parametrize(
    ("factory", "updates"),
    [
        (_dispatch, {"workflow_id": True}),
        (_dispatch, {"run_id": 0}),
        (_dispatch, {"head_sha": "b" * 39}),
        (_dispatch, {"explicitly_dispatched": 1}),
        (_ci_run, {"workflow_id": 0}),
        (_ci_run, {"run_attempt": True}),
        (_ci_run, {"head_sha": "b" * 39}),
        (_ci_run, {"directly_verified": 1}),
    ],
)
def test_ci_receipts_reject_malformed_ids_shas_and_booleans(
    factory: Callable[..., object],
    updates: dict[str, object],
) -> None:
    with pytest.raises(ReleaseControlError):
        factory(**updates)


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("name", ""),
        ("job_id", True),
        ("run_id", 0),
        ("run_attempt", 0),
        ("head_sha", "b" * 39),
        ("status", ""),
        ("conclusion", ""),
    ],
)
def test_ci_job_receipt_rejects_malformed_fields(field: str, value: object) -> None:
    values: dict[str, object] = {
        "name": "test",
        "job_id": 801,
        "run_id": 707,
        "run_attempt": 1,
        "head_sha": _METADATA_HEAD_SHA,
        "status": "completed",
        "conclusion": "success",
    }
    values[field] = value

    with pytest.raises(ReleaseControlError):
        CIJobReceipt(**values)  # type: ignore[arg-type]


def test_ci_run_rejects_non_tuple_or_untyped_job_inventory() -> None:
    with pytest.raises(ReleaseControlError, match="tuple"):
        replace(_ci_run(), jobs=list(_jobs()))  # type: ignore[arg-type]
    with pytest.raises(ReleaseControlError, match="invalid evidence"):
        replace(_ci_run(), jobs=(object(),))  # type: ignore[arg-type]
