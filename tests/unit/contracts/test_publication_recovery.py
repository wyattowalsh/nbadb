from __future__ import annotations

from dataclasses import replace

import pytest

from nbadb.contracts.actions_artifact import (
    ActionsArtifactIdentityV1,
    ArtifactMemberIdentityV1,
)
from nbadb.contracts.publication_recovery import (
    PendingTakeoverReceiptV1,
    PendingTakeoverStatusReceiptV1,
    PublicationRecoveryContractError,
    StablePublicationInventoryReceiptV1,
)
from nbadb.kaggle.publication_ledger import ExecutorReceipt

_REPOSITORY = "wyattowalsh/nbadb"
_DATASET = "wyattowalsh/basketball"
_SHA = "a" * 64


def _executor(*, run_id: int, run_attempt: int = 1, job_id: int | None = None) -> ExecutorReceipt:
    resolved_job_id = job_id or run_id * 10
    return ExecutorReceipt(
        repository=_REPOSITORY,
        run_id=run_id,
        run_attempt=run_attempt,
        workflow_id=77,
        workflow="Publication",
        workflow_path=".github/workflows/publication.yml",
        workflow_sha="b" * 40,
        job="publish",
        job_id=resolved_job_id,
        job_url=f"https://api.github.test/jobs/{resolved_job_id}",
        actor="wyattowalsh",
        log_url=f"https://github.test/runs/{run_id}/attempts/{run_attempt}",
        workflow_content_sha256="c" * 64,
        admission_digest="d" * 64,
    )


def _stable(**updates: object) -> StablePublicationInventoryReceiptV1:
    values: dict[str, object] = {
        "repository": _REPOSITORY,
        "dataset": _DATASET,
        "first_sampled_at": "2026-09-11T00:00:00Z",
        "second_sampled_at": "2026-09-11T00:00:01Z",
        "first_writer_inventory_sha256": "1" * 64,
        "second_writer_inventory_sha256": "1" * 64,
        "first_ledger_inventory_sha256": "2" * 64,
        "second_ledger_inventory_sha256": "2" * 64,
        "first_remote_inventory_sha256": "3" * 64,
        "second_remote_inventory_sha256": "3" * 64,
        "first_active_writer_count": 0,
        "second_active_writer_count": 0,
        "first_resolving_marker_present": False,
        "second_resolving_marker_present": False,
        "first_competing_publisher_present": False,
        "second_competing_publisher_present": False,
    }
    values.update(updates)
    return StablePublicationInventoryReceiptV1.build(**values)


def _takeover(**updates: object) -> PendingTakeoverReceiptV1:
    values: dict[str, object] = {
        "repository": _REPOSITORY,
        "dataset": _DATASET,
        "intent_id": "4" * 64,
        "deployment_id": 42,
        "original_executor": _executor(run_id=100),
        "origin_terminal_conclusion": "failure",
        "recovery_executor": _executor(run_id=200),
        "terminal_handoff_sha256": "5" * 64,
        "stable_inventory": _stable(),
        "nonce": "6" * 32,
    }
    values.update(updates)
    return PendingTakeoverReceiptV1.build(**values)


def _member(takeover_sha256: str) -> ArtifactMemberIdentityV1:
    artifact = ActionsArtifactIdentityV1(
        repository=_REPOSITORY,
        run_id=200,
        run_attempt=1,
        artifact_id=91,
        artifact_name="publication-takeover-42-200-1",
        artifact_digest=f"sha256:{'7' * 64}",
        artifact_size_bytes=1024,
    )
    return ArtifactMemberIdentityV1(
        artifact=artifact,
        member_path="recovery/pending-takeover.json",
        member_sha256=takeover_sha256,
        member_size_bytes=512,
    )


def _status(takeover: PendingTakeoverReceiptV1) -> PendingTakeoverStatusReceiptV1:
    return PendingTakeoverStatusReceiptV1.build(
        deployment_id=takeover.deployment_id,
        status_id=99,
        state="pending",
        creator_login="github-actions[bot]",
        creator_id=41898282,
        description_token="takeover-token",
        takeover_member=_member(takeover.takeover_sha256),
        takeover_sha256=takeover.takeover_sha256,
        recovery_executor=takeover.recovery_executor,
    )


def test_stable_inventory_round_trip_and_determinism() -> None:
    first = _stable()
    second = _stable()
    assert first.inventory_sha256 == second.inventory_sha256
    assert StablePublicationInventoryReceiptV1.from_payload(first.to_payload()) == first
    first.verify()


@pytest.mark.parametrize(
    "updates",
    [
        {"second_writer_inventory_sha256": "9" * 64},
        {"second_ledger_inventory_sha256": "9" * 64},
        {"second_remote_inventory_sha256": "9" * 64},
        {"first_active_writer_count": 1},
        {"second_resolving_marker_present": True},
        {"first_competing_publisher_present": True},
        {"second_sampled_at": "2026-09-11T00:00:00Z"},
    ],
)
def test_stable_inventory_rejects_drift_activity_or_nonindependent_samples(
    updates: dict[str, object],
) -> None:
    with pytest.raises(PublicationRecoveryContractError):
        _stable(**updates)


def test_stable_inventory_rejects_extra_key_and_digest_tamper() -> None:
    payload = _stable().to_payload()
    payload["extra"] = True
    with pytest.raises(PublicationRecoveryContractError, match="exact-key"):
        StablePublicationInventoryReceiptV1.from_payload(payload)
    payload = _stable().to_payload()
    payload["inventory_sha256"] = "9" * 64
    with pytest.raises(PublicationRecoveryContractError, match="digest mismatch"):
        StablePublicationInventoryReceiptV1.from_payload(payload)


def test_takeover_round_trip_binds_distinct_executors_and_stable_inventory() -> None:
    receipt = _takeover()
    assert receipt.original_executor.run_id == 100
    assert receipt.recovery_executor.run_id == 200
    assert PendingTakeoverReceiptV1.from_payload(receipt.to_payload()) == receipt
    receipt.verify()


def test_takeover_rejects_nonterminal_or_same_executor() -> None:
    origin = _executor(run_id=100)
    with pytest.raises(PublicationRecoveryContractError, match="not terminal"):
        _takeover(origin_terminal_conclusion="in_progress")
    with pytest.raises(PublicationRecoveryContractError, match="distinct"):
        _takeover(recovery_executor=origin)


def test_takeover_rejects_inventory_provenance_and_digest_tamper() -> None:
    with pytest.raises(PublicationRecoveryContractError, match="provenance"):
        _takeover(stable_inventory=_stable(dataset="other/dataset"))
    payload = _takeover().to_payload()
    payload["terminal_handoff_sha256"] = "9" * 64
    with pytest.raises(PublicationRecoveryContractError, match="digest mismatch"):
        PendingTakeoverReceiptV1.from_payload(payload)


def test_takeover_status_round_trip_binds_exact_member_and_executor() -> None:
    takeover = _takeover()
    receipt = _status(takeover)
    assert receipt.takeover_member.member_sha256 == takeover.takeover_sha256
    assert PendingTakeoverStatusReceiptV1.from_payload(receipt.to_payload()) == receipt
    receipt.verify()


def test_takeover_status_rejects_member_or_status_tamper() -> None:
    takeover = _takeover()
    with pytest.raises(PublicationRecoveryContractError, match="member digest"):
        PendingTakeoverStatusReceiptV1.build(
            deployment_id=42,
            status_id=99,
            state="pending",
            creator_login="github-actions[bot]",
            creator_id=41898282,
            description_token="takeover-token",
            takeover_member=_member("9" * 64),
            takeover_sha256=takeover.takeover_sha256,
            recovery_executor=takeover.recovery_executor,
        )
    payload = _status(takeover).to_payload()
    payload["status_sha256"] = "9" * 64
    with pytest.raises(PublicationRecoveryContractError, match="digest mismatch"):
        PendingTakeoverStatusReceiptV1.from_payload(payload)


def test_takeover_status_requires_pending_state() -> None:
    takeover = _takeover()
    with pytest.raises(PublicationRecoveryContractError, match="must be pending"):
        replace(_status(takeover), state="in_progress")
