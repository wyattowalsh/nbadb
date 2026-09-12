from __future__ import annotations

import hashlib
import json
from enum import StrEnum
from pathlib import Path
from typing import Annotated

import typer

from nbadb.cli.app import app
from nbadb.orchestrate.persistence import atomic_write_path
from nbadb.orchestrate.recurring_evidence import (
    FreshnessDecision,
    RecurringEvidenceError,
    RecurringRunPhase,
    RecurringRunStatusReason,
    RecurringRunStatusV1,
)


class _Outcome(StrEnum):
    SUCCESS = "success"
    FAILURE = "failure"
    CANCELLED = "cancelled"
    SKIPPED = "skipped"
    UNKNOWN = "unknown"


_FRESH_REASONS = {
    RecurringRunStatusReason.UPDATE_PUBLISHED_AND_READ_BACK,
    RecurringRunStatusReason.NO_GAME_CLOSED_AND_VERSIONED,
}

OutputPathOption = Annotated[Path, typer.Option("--output-path")]
SourceShaOption = Annotated[str, typer.Option("--source-sha")]
ActionsRunIdOption = Annotated[int, typer.Option("--actions-run-id", min=1)]
ActionsRunAttemptOption = Annotated[int, typer.Option("--actions-run-attempt", min=1)]
ExpectedPriorDateOption = Annotated[str, typer.Option("--expected-prior-nba-date")]
TimezoneOption = Annotated[str, typer.Option("--timezone")]
ProviderCutoffOption = Annotated[str, typer.Option("--provider-availability-cutoff")]
ScheduledDeadlineOption = Annotated[str, typer.Option("--scheduled-deadline")]
ActualCompletionOption = Annotated[str, typer.Option("--actual-completion")]
DatasetRefOption = Annotated[str, typer.Option("--dataset-ref")]
WorkflowResultOption = Annotated[str, typer.Option("--workflow-result")]
CheckoutOutcomeOption = Annotated[str, typer.Option("--checkout-outcome")]
ParentOutcomeOption = Annotated[str, typer.Option("--parent-outcome")]
CapacityOutcomeOption = Annotated[str, typer.Option("--capacity-outcome")]
ExtractionOutcomeOption = Annotated[str, typer.Option("--extraction-outcome")]
AssuranceOutcomeOption = Annotated[str, typer.Option("--assurance-outcome")]
PublicationOutcomeOption = Annotated[str, typer.Option("--publication-outcome")]
ReadbackOutcomeOption = Annotated[str, typer.Option("--readback-outcome")]
ParentVersionOption = Annotated[int | None, typer.Option("--parent-dataset-version", min=1)]
ParentCutoffOption = Annotated[str | None, typer.Option("--parent-cutoff")]
ParentFingerprintOption = Annotated[str | None, typer.Option("--parent-fingerprint-sha256")]
LatestVersionOption = Annotated[
    int | None,
    typer.Option("--latest-assured-remote-version", min=1),
]
LatestCutoffOption = Annotated[str | None, typer.Option("--latest-assured-remote-cutoff")]
TransactionIdOption = Annotated[str | None, typer.Option("--update-transaction-id")]
CoordinatorIdentityOption = Annotated[
    str | None,
    typer.Option("--coordinator-identity-sha256"),
]
CandidateIdentityOption = Annotated[
    str | None,
    typer.Option("--candidate-identity-sha256"),
]
RequestClosureOption = Annotated[str | None, typer.Option("--request-closure-sha256")]
PublicationReadbackOption = Annotated[
    str | None,
    typer.Option("--publication-readback-sha256"),
]
ProviderMutationCountOption = Annotated[
    int,
    typer.Option("--provider-mutation-count", min=0),
]
KaggleMutationCountOption = Annotated[
    int,
    typer.Option("--kaggle-mutation-count", min=0),
]
NoMutationProofPathOption = Annotated[
    Path | None,
    typer.Option("--pre-extraction-no-mutation-proof-path"),
]
FreshReasonOption = Annotated[str | None, typer.Option("--fresh-reason")]


def _outcome(value: str, *, label: str) -> _Outcome:
    normalized = value.strip().lower() or _Outcome.UNKNOWN.value
    try:
        return _Outcome(normalized)
    except ValueError as exc:
        allowed = ", ".join(item.value for item in _Outcome)
        raise RecurringEvidenceError(f"{label} must be one of: {allowed}") from exc


def _fresh_reason(value: str | None) -> RecurringRunStatusReason | None:
    if value is None or not value.strip():
        return None
    try:
        reason = RecurringRunStatusReason(value.strip())
    except ValueError as exc:
        raise RecurringEvidenceError("fresh_reason is not a recurring status reason") from exc
    if reason not in _FRESH_REASONS:
        raise RecurringEvidenceError("fresh_reason must be a terminal freshness reason")
    return reason


def _pre_extraction_reason(
    *,
    checkout: _Outcome,
    parent: _Outcome,
    capacity: _Outcome,
    parent_dataset_version: int | None,
) -> RecurringRunStatusReason | None:
    if checkout is not _Outcome.SUCCESS:
        return RecurringRunStatusReason.CHECKOUT_FAILED
    if parent is not _Outcome.SUCCESS or parent_dataset_version is None:
        return RecurringRunStatusReason.PARENT_ADMISSION_FAILED
    if capacity in {_Outcome.FAILURE, _Outcome.CANCELLED}:
        return RecurringRunStatusReason.CAPACITY_BLOCKED
    return None


def _cancelled_phase(
    *,
    checkout: _Outcome,
    parent: _Outcome,
    capacity: _Outcome,
    extraction: _Outcome,
    assurance: _Outcome,
    publication: _Outcome,
) -> RecurringRunPhase:
    if checkout is not _Outcome.SUCCESS or parent is not _Outcome.SUCCESS:
        return RecurringRunPhase.PRE_EXTRACTION
    if capacity in {_Outcome.FAILURE, _Outcome.CANCELLED}:
        return RecurringRunPhase.PRE_EXTRACTION
    if extraction is not _Outcome.SUCCESS:
        return RecurringRunPhase.EXTRACTION
    if assurance is not _Outcome.SUCCESS:
        return RecurringRunPhase.ASSURANCE
    if publication is not _Outcome.SUCCESS:
        return RecurringRunPhase.PUBLICATION
    return RecurringRunPhase.COMPLETE


def _pre_extraction_no_mutation_proof(
    *,
    source_sha: str,
    actions_run_id: int,
    actions_run_attempt: int,
    expected_prior_nba_date: str,
    dataset_ref: str,
    parent_dataset_version: int | None,
    reason: RecurringRunStatusReason,
    workflow: _Outcome,
    checkout: _Outcome,
    parent: _Outcome,
    capacity: _Outcome,
    extraction: _Outcome,
    assurance: _Outcome,
    publication: _Outcome,
    readback: _Outcome,
    provider_mutation_count: int,
    kaggle_mutation_count: int,
) -> bytes:
    if workflow not in {_Outcome.FAILURE, _Outcome.CANCELLED}:
        raise RecurringEvidenceError(
            "pre-extraction no-mutation proof requires a failed or cancelled workflow"
        )
    downstream_outcomes = {
        "extraction": extraction,
        "assurance": assurance,
        "publication": publication,
        "readback": readback,
    }
    reached = sorted(
        label
        for label, outcome in downstream_outcomes.items()
        if outcome not in {_Outcome.SKIPPED, _Outcome.UNKNOWN}
    )
    if reached:
        raise RecurringEvidenceError(
            "pre-extraction no-mutation proof conflicts with reached downstream steps: "
            + ", ".join(reached)
        )
    if provider_mutation_count != 0 or kaggle_mutation_count != 0:
        raise RecurringEvidenceError(
            "pre-extraction no-mutation proof requires zero provider and Kaggle mutations"
        )
    payload = {
        "actions_run_attempt": actions_run_attempt,
        "actions_run_id": actions_run_id,
        "dataset_ref": dataset_ref,
        "expected_prior_nba_date": expected_prior_nba_date,
        "kaggle_mutation_count": kaggle_mutation_count,
        "kind": "recurring_pre_extraction_no_mutation_proof",
        "outcomes": {
            "assurance": assurance.value,
            "capacity": capacity.value,
            "checkout": checkout.value,
            "extraction": extraction.value,
            "parent": parent.value,
            "publication": publication.value,
            "readback": readback.value,
            "workflow": workflow.value,
        },
        "parent_dataset_version": parent_dataset_version,
        "proof_basis": "workflow_control_flow_and_exact_step_outcomes",
        "provider_mutation_count": provider_mutation_count,
        "reason": reason.value,
        "schema_version": 1,
        "source_sha": source_sha,
    }
    return (
        json.dumps(
            payload,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=True,
            allow_nan=False,
        ).encode("utf-8")
        + b"\n"
    )


def _build_recurring_run_status(
    *,
    source_sha: str,
    actions_run_id: int,
    actions_run_attempt: int,
    expected_prior_nba_date: str,
    timezone: str,
    provider_availability_cutoff: str,
    scheduled_deadline: str,
    actual_completion: str,
    dataset_ref: str,
    workflow_result: str,
    checkout_outcome: str,
    parent_outcome: str,
    capacity_outcome: str,
    extraction_outcome: str,
    assurance_outcome: str,
    publication_outcome: str,
    readback_outcome: str,
    parent_dataset_version: int | None,
    parent_cutoff: str | None,
    parent_fingerprint_sha256: str | None,
    latest_assured_remote_version: int | None,
    latest_assured_remote_cutoff: str | None,
    update_transaction_id: str | None,
    coordinator_identity_sha256: str | None,
    candidate_identity_sha256: str | None,
    request_closure_sha256: str | None,
    publication_readback_sha256: str | None,
    provider_mutation_count: int,
    kaggle_mutation_count: int,
    pre_extraction_no_mutation_proof_sha256: str | None,
    fresh_reason: str | None,
) -> RecurringRunStatusV1:
    workflow = _outcome(workflow_result, label="workflow_result")
    checkout = _outcome(checkout_outcome, label="checkout_outcome")
    parent = _outcome(parent_outcome, label="parent_outcome")
    capacity = _outcome(capacity_outcome, label="capacity_outcome")
    extraction = _outcome(extraction_outcome, label="extraction_outcome")
    assurance = _outcome(assurance_outcome, label="assurance_outcome")
    publication = _outcome(publication_outcome, label="publication_outcome")
    readback = _outcome(readback_outcome, label="readback_outcome")
    requested_fresh_reason = _fresh_reason(fresh_reason)
    pre_extraction_reason = _pre_extraction_reason(
        checkout=checkout,
        parent=parent,
        capacity=capacity,
        parent_dataset_version=parent_dataset_version,
    )

    phase: RecurringRunPhase
    reason: RecurringRunStatusReason
    freshness = FreshnessDecision.NOT_FRESH

    if pre_extraction_reason is not None:
        phase = RecurringRunPhase.PRE_EXTRACTION
        reason = pre_extraction_reason
    elif workflow is _Outcome.CANCELLED:
        phase = _cancelled_phase(
            checkout=checkout,
            parent=parent,
            capacity=capacity,
            extraction=extraction,
            assurance=assurance,
            publication=publication,
        )
        reason = RecurringRunStatusReason.CANCELLED
    elif extraction is not _Outcome.SUCCESS:
        phase = RecurringRunPhase.EXTRACTION
        reason = RecurringRunStatusReason.EXTRACTION_INCOMPLETE
    elif assurance is not _Outcome.SUCCESS:
        phase = RecurringRunPhase.ASSURANCE
        reason = RecurringRunStatusReason.ASSURANCE_FAILED
    elif publication is not _Outcome.SUCCESS:
        phase = RecurringRunPhase.PUBLICATION
        reason = RecurringRunStatusReason.PUBLICATION_FAILED
    elif readback is not _Outcome.SUCCESS:
        phase = RecurringRunPhase.PUBLICATION
        reason = RecurringRunStatusReason.READBACK_FAILED
    elif workflow is not _Outcome.SUCCESS:
        phase = RecurringRunPhase.COMPLETE
        reason = RecurringRunStatusReason.INTERNAL_ERROR
    else:
        terminal_evidence = (
            parent_cutoff,
            parent_fingerprint_sha256,
            latest_assured_remote_version,
            latest_assured_remote_cutoff,
            update_transaction_id,
            coordinator_identity_sha256,
            candidate_identity_sha256,
            request_closure_sha256,
            publication_readback_sha256,
        )
        if requested_fresh_reason is not None and all(
            value is not None for value in terminal_evidence
        ):
            phase = RecurringRunPhase.COMPLETE
            reason = requested_fresh_reason
            freshness = FreshnessDecision.FRESH
        else:
            # Exact step success is not freshness authority. Without every terminal
            # receipt binding, the always-finalizer closes truthfully as not_fresh.
            phase = RecurringRunPhase.PUBLICATION
            reason = RecurringRunStatusReason.READBACK_FAILED

    is_pre_extraction_reason = reason in {
        RecurringRunStatusReason.CHECKOUT_FAILED,
        RecurringRunStatusReason.PARENT_ADMISSION_FAILED,
        RecurringRunStatusReason.CAPACITY_BLOCKED,
    }
    if is_pre_extraction_reason and pre_extraction_no_mutation_proof_sha256 is None:
        raise RecurringEvidenceError(
            "pre-extraction status requires an exact no-mutation proof digest"
        )

    if reason in {
        RecurringRunStatusReason.CHECKOUT_FAILED,
        RecurringRunStatusReason.PARENT_ADMISSION_FAILED,
    }:
        parent_dataset_version = None
        parent_cutoff = None
        parent_fingerprint_sha256 = None
        latest_assured_remote_version = None
        latest_assured_remote_cutoff = None
        update_transaction_id = None
        coordinator_identity_sha256 = None
        candidate_identity_sha256 = None
        request_closure_sha256 = None
        publication_readback_sha256 = None

    return RecurringRunStatusV1(
        source_sha=source_sha,
        actions_run_id=actions_run_id,
        actions_run_attempt=actions_run_attempt,
        expected_prior_nba_date=expected_prior_nba_date,
        timezone=timezone,
        provider_availability_cutoff=provider_availability_cutoff,
        scheduled_deadline=scheduled_deadline,
        actual_completion=actual_completion,
        phase=phase,
        freshness=freshness,
        reason=reason,
        dataset_ref=dataset_ref,
        parent_dataset_version=parent_dataset_version,
        parent_cutoff=parent_cutoff,
        parent_fingerprint_sha256=parent_fingerprint_sha256,
        latest_assured_remote_version=latest_assured_remote_version,
        latest_assured_remote_cutoff=latest_assured_remote_cutoff,
        update_transaction_id=update_transaction_id,
        coordinator_identity_sha256=coordinator_identity_sha256,
        candidate_identity_sha256=candidate_identity_sha256,
        request_closure_sha256=request_closure_sha256,
        publication_readback_sha256=publication_readback_sha256,
        provider_mutation_count=provider_mutation_count,
        kaggle_mutation_count=kaggle_mutation_count,
        no_mutation_proven=is_pre_extraction_reason,
        no_mutation_proof_sha256=(
            pre_extraction_no_mutation_proof_sha256 if is_pre_extraction_reason else None
        ),
    )


@app.command("recurring-status")
def recurring_status(
    output_path: OutputPathOption,
    source_sha: SourceShaOption,
    actions_run_id: ActionsRunIdOption,
    actions_run_attempt: ActionsRunAttemptOption,
    expected_prior_nba_date: ExpectedPriorDateOption,
    timezone: TimezoneOption,
    provider_availability_cutoff: ProviderCutoffOption,
    scheduled_deadline: ScheduledDeadlineOption,
    actual_completion: ActualCompletionOption,
    dataset_ref: DatasetRefOption,
    workflow_result: WorkflowResultOption,
    checkout_outcome: CheckoutOutcomeOption = "unknown",
    parent_outcome: ParentOutcomeOption = "unknown",
    capacity_outcome: CapacityOutcomeOption = "unknown",
    extraction_outcome: ExtractionOutcomeOption = "unknown",
    assurance_outcome: AssuranceOutcomeOption = "unknown",
    publication_outcome: PublicationOutcomeOption = "unknown",
    readback_outcome: ReadbackOutcomeOption = "unknown",
    parent_dataset_version: ParentVersionOption = None,
    parent_cutoff: ParentCutoffOption = None,
    parent_fingerprint_sha256: ParentFingerprintOption = None,
    latest_assured_remote_version: LatestVersionOption = None,
    latest_assured_remote_cutoff: LatestCutoffOption = None,
    update_transaction_id: TransactionIdOption = None,
    coordinator_identity_sha256: CoordinatorIdentityOption = None,
    candidate_identity_sha256: CandidateIdentityOption = None,
    request_closure_sha256: RequestClosureOption = None,
    publication_readback_sha256: PublicationReadbackOption = None,
    provider_mutation_count: ProviderMutationCountOption = 0,
    kaggle_mutation_count: KaggleMutationCountOption = 0,
    pre_extraction_no_mutation_proof_path: NoMutationProofPathOption = None,
    fresh_reason: FreshReasonOption = None,
) -> None:
    """Emit one canonical always-finalized recurring freshness receipt."""

    try:
        workflow = _outcome(workflow_result, label="workflow_result")
        checkout = _outcome(checkout_outcome, label="checkout_outcome")
        parent = _outcome(parent_outcome, label="parent_outcome")
        capacity = _outcome(capacity_outcome, label="capacity_outcome")
        extraction = _outcome(extraction_outcome, label="extraction_outcome")
        assurance = _outcome(assurance_outcome, label="assurance_outcome")
        publication = _outcome(publication_outcome, label="publication_outcome")
        readback = _outcome(readback_outcome, label="readback_outcome")
        pre_extraction_reason = _pre_extraction_reason(
            checkout=checkout,
            parent=parent,
            capacity=capacity,
            parent_dataset_version=parent_dataset_version,
        )
        proof_bytes: bytes | None = None
        proof_sha256: str | None = None
        if pre_extraction_reason is not None:
            if pre_extraction_no_mutation_proof_path is None:
                raise RecurringEvidenceError(
                    "pre-extraction status requires a no-mutation proof output path"
                )
            if pre_extraction_no_mutation_proof_path.is_symlink():
                raise RecurringEvidenceError(
                    "pre-extraction no-mutation proof path must not be a symlink"
                )
            proof_bytes = _pre_extraction_no_mutation_proof(
                source_sha=source_sha,
                actions_run_id=actions_run_id,
                actions_run_attempt=actions_run_attempt,
                expected_prior_nba_date=expected_prior_nba_date,
                dataset_ref=dataset_ref,
                parent_dataset_version=parent_dataset_version,
                reason=pre_extraction_reason,
                workflow=workflow,
                checkout=checkout,
                parent=parent,
                capacity=capacity,
                extraction=extraction,
                assurance=assurance,
                publication=publication,
                readback=readback,
                provider_mutation_count=provider_mutation_count,
                kaggle_mutation_count=kaggle_mutation_count,
            )
            proof_sha256 = hashlib.sha256(proof_bytes).hexdigest()

        status = _build_recurring_run_status(
            source_sha=source_sha,
            actions_run_id=actions_run_id,
            actions_run_attempt=actions_run_attempt,
            expected_prior_nba_date=expected_prior_nba_date,
            timezone=timezone,
            provider_availability_cutoff=provider_availability_cutoff,
            scheduled_deadline=scheduled_deadline,
            actual_completion=actual_completion,
            dataset_ref=dataset_ref,
            workflow_result=workflow_result,
            checkout_outcome=checkout_outcome,
            parent_outcome=parent_outcome,
            capacity_outcome=capacity_outcome,
            extraction_outcome=extraction_outcome,
            assurance_outcome=assurance_outcome,
            publication_outcome=publication_outcome,
            readback_outcome=readback_outcome,
            parent_dataset_version=parent_dataset_version,
            parent_cutoff=parent_cutoff,
            parent_fingerprint_sha256=parent_fingerprint_sha256,
            latest_assured_remote_version=latest_assured_remote_version,
            latest_assured_remote_cutoff=latest_assured_remote_cutoff,
            update_transaction_id=update_transaction_id,
            coordinator_identity_sha256=coordinator_identity_sha256,
            candidate_identity_sha256=candidate_identity_sha256,
            request_closure_sha256=request_closure_sha256,
            publication_readback_sha256=publication_readback_sha256,
            provider_mutation_count=provider_mutation_count,
            kaggle_mutation_count=kaggle_mutation_count,
            pre_extraction_no_mutation_proof_sha256=proof_sha256,
            fresh_reason=fresh_reason,
        )
        if output_path.is_symlink():
            raise RecurringEvidenceError("output_path must not be a symlink")

        if proof_bytes is not None and pre_extraction_no_mutation_proof_path is not None:

            def _write_proof(temporary: Path) -> None:
                temporary.write_bytes(proof_bytes)

            atomic_write_path(pre_extraction_no_mutation_proof_path, _write_proof)

        def _write_status(temporary: Path) -> None:
            temporary.write_bytes(status.canonical_bytes)

        atomic_write_path(output_path, _write_status)
    except (OSError, RecurringEvidenceError) as exc:
        typer.echo(f"Recurring status failed: {type(exc).__name__}: {exc}", err=True)
        raise typer.Exit(1) from exc

    typer.echo(f"Recurring status: {status.freshness.value}")
    typer.echo(f"Reason: {status.reason.value}")
    if proof_bytes is not None and pre_extraction_no_mutation_proof_path is not None:
        typer.echo(f"No-mutation proof SHA-256: {hashlib.sha256(proof_bytes).hexdigest()}")
        typer.echo(f"No-mutation proof: {pre_extraction_no_mutation_proof_path}")
    typer.echo(f"Receipt SHA-256: {status.content_sha256}")
    typer.echo(f"Receipt: {output_path}")
