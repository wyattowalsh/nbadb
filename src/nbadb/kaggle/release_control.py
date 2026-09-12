"""Pure fail-closed decisions for publication recovery and metadata closeout.

This module deliberately performs no I/O. Callers must first collect and validate
GitHub ledger, Actions, and remote Kaggle receipts, then translate those receipts
into the value objects below. The controller only determines which recovery lane
is safe; it never dispatches a workflow or calls Kaggle.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from enum import StrEnum

_HEX_40_RE = re.compile(r"[0-9a-f]{40}")
_HEX_64_RE = re.compile(r"[0-9a-f]{64}")
_REPOSITORY_RE = re.compile(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+")
_WORKFLOW_PATH_RE = re.compile(r"\.github/workflows/[A-Za-z0-9_.-]+\.ya?ml")

CI_WORKFLOW_PATH = ".github/workflows/ci.yml"
METADATA_ONLY_ALLOWED_FILES = frozenset({"dataset-metadata.json"})
REQUIRED_METADATA_CI_JOBS = frozenset(
    {"workflow-lint", "lint", "metadata", "typecheck", "docs", "test"}
)


class ReleaseControlError(ValueError):
    """Release-control evidence is malformed or internally ambiguous."""


class DurableLedgerState(StrEnum):
    """Validated durable-ledger state relevant to publication recovery."""

    ABSENT = "absent"
    PENDING = "pending"
    IN_PROGRESS = "in_progress"
    SUCCESS = "success"


class ReleaseAction(StrEnum):
    """The complete set of release-control outcomes."""

    NEW_ZERO_ACTIVE_REPLAY = "new_zero_active_replay"
    CLAIM_PENDING_TAKEOVER = "claim_pending_takeover"
    RECONCILE_WITHOUT_UPLOAD = "reconcile_without_upload"
    CONTINUE_POST_PUBLICATION = "continue_post_publication"
    BLOCKED = "blocked"


class ReleaseDecisionReason(StrEnum):
    """Stable, non-sensitive explanations for release decisions."""

    PRE_INTENT_REPLAY_ALLOWED = "pre_intent_replay_allowed"
    PENDING_TAKEOVER_REQUIRED = "pending_takeover_required"
    PENDING_TAKEOVER_DURABLY_CLAIMABLE = "pending_takeover_durably_claimable"
    RECONCILIATION_WITHOUT_UPLOAD_REQUIRED = "reconciliation_without_upload_required"
    EXACT_PUBLICATION_ALREADY_SUCCEEDED = "exact_publication_already_succeeded"
    INVENTORY_NOT_STABLE = "inventory_not_stable"
    PUBLISHER_NOT_TERMINAL = "publisher_not_terminal"
    ACTIVE_WRITER_EXISTS = "active_writer_exists"
    COMPETING_WRITER_EXISTS = "competing_writer_exists"
    RECOVERY_RECEIPT_NOT_BOUND = "recovery_receipt_not_bound"
    RECOVERY_PROVENANCE_MISMATCH = "recovery_provenance_mismatch"
    ZERO_ACTIVE_REPLAY_ALREADY_USED = "zero_active_replay_already_used"
    RECOVERY_IS_NOT_A_NEW_RUN = "recovery_is_not_a_new_run"
    SUCCESS_EVIDENCE_INCONSISTENT = "success_evidence_inconsistent"
    DURABLE_INTENT_REQUIRED = "durable_intent_required"
    RECONCILIATION_ONLY = "reconciliation_only"
    PUBLICATION_ALREADY_SUCCEEDED = "publication_already_succeeded"


def _require_bool(value: object, *, field: str) -> None:
    if type(value) is not bool:
        raise ReleaseControlError(f"{field} must be boolean")


def _require_positive_int(value: object, *, field: str) -> None:
    if type(value) is not int or value <= 0:
        raise ReleaseControlError(f"{field} must be a positive integer")


def _require_hex(value: object, *, field: str, length: int) -> None:
    pattern = _HEX_40_RE if length == 40 else _HEX_64_RE
    if not isinstance(value, str) or pattern.fullmatch(value) is None:
        raise ReleaseControlError(f"{field} must be {length} lowercase hex characters")


def _require_repository(value: object, *, field: str) -> None:
    if not isinstance(value, str) or _REPOSITORY_RE.fullmatch(value) is None:
        raise ReleaseControlError(f"{field} is invalid")


def _require_workflow_path(value: object, *, field: str) -> None:
    if not isinstance(value, str) or _WORKFLOW_PATH_RE.fullmatch(value) is None:
        raise ReleaseControlError(f"{field} is invalid")


def _require_tuple(value: object, *, field: str) -> None:
    if type(value) is not tuple:
        raise ReleaseControlError(f"{field} must be a tuple")


@dataclass(frozen=True, slots=True)
class PublisherAuthority:
    """Receipt-bound publisher execution and assured-bundle authority."""

    repository: str
    workflow_path: str
    run_id: int
    run_attempt: int
    publisher_job_id: int
    source_sha: str
    assured_bundle_sha256: str
    intent_id: str

    def __post_init__(self) -> None:
        _require_repository(self.repository, field="publisher repository")
        _require_workflow_path(self.workflow_path, field="publisher workflow_path")
        _require_positive_int(self.run_id, field="publisher run_id")
        _require_positive_int(self.run_attempt, field="publisher run_attempt")
        _require_positive_int(self.publisher_job_id, field="publisher_job_id")
        _require_hex(self.source_sha, field="publisher source_sha", length=40)
        _require_hex(
            self.assured_bundle_sha256,
            field="publisher assured_bundle_sha256",
            length=64,
        )
        _require_hex(self.intent_id, field="publisher intent_id", length=64)

    @property
    def semantic_identity(self) -> tuple[str, str, str, str, str]:
        """Identity that must survive a pre-intent replacement run."""

        return (
            self.repository,
            self.workflow_path,
            self.source_sha,
            self.assured_bundle_sha256,
            self.intent_id,
        )

    @property
    def execution_identity(self) -> tuple[str, int, int, int]:
        """Exact workflow-run, attempt, and publisher-job authority."""

        return (self.repository, self.run_id, self.run_attempt, self.publisher_job_id)


@dataclass(frozen=True, slots=True)
class PublicationSuccessProof:
    """Comparable durable or remote proof of one exact publication result."""

    source_sha: str
    assured_bundle_sha256: str
    intent_id: str
    resolved_version: int
    publication_marker_sha256: str
    resource_inventory_sha256: str
    readback_fingerprint: str
    resolution_digest: str

    def __post_init__(self) -> None:
        _require_hex(self.source_sha, field="publication success source_sha", length=40)
        for field in (
            "assured_bundle_sha256",
            "intent_id",
            "publication_marker_sha256",
            "resource_inventory_sha256",
            "readback_fingerprint",
            "resolution_digest",
        ):
            _require_hex(
                getattr(self, field),
                field=f"publication success {field}",
                length=64,
            )
        _require_positive_int(self.resolved_version, field="publication success resolved_version")

    def matches(self, authority: PublisherAuthority) -> bool:
        """Return whether this result is bound to the authority's frozen bundle."""

        return (
            self.source_sha == authority.source_sha
            and self.assured_bundle_sha256 == authority.assured_bundle_sha256
            and self.intent_id == authority.intent_id
        )


@dataclass(frozen=True, slots=True)
class ReleaseStateEvidence:
    """Stable read-only evidence used to decide the next publication action."""

    authority: PublisherAuthority
    ledger_state: DurableLedgerState
    publisher_terminal: bool
    writer_inventory_stable: bool
    ledger_inventory_stable: bool
    active_writers: tuple[PublisherAuthority, ...] = ()
    competing_writer_detected: bool = False
    zero_active_replay_used: bool = False
    durable_success: PublicationSuccessProof | None = None
    remote_success: PublicationSuccessProof | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.authority, PublisherAuthority):
            raise ReleaseControlError("release authority is invalid")
        if not isinstance(self.ledger_state, DurableLedgerState):
            raise ReleaseControlError("ledger_state is invalid")
        for field in (
            "publisher_terminal",
            "writer_inventory_stable",
            "ledger_inventory_stable",
            "competing_writer_detected",
            "zero_active_replay_used",
        ):
            _require_bool(getattr(self, field), field=field)
        _require_tuple(self.active_writers, field="active_writers")
        if not all(isinstance(writer, PublisherAuthority) for writer in self.active_writers):
            raise ReleaseControlError("active_writers contains invalid evidence")
        writer_identities = [writer.execution_identity for writer in self.active_writers]
        if len(writer_identities) != len(set(writer_identities)):
            raise ReleaseControlError("active_writers contains ambiguous duplicate executions")
        for field in ("durable_success", "remote_success"):
            value = getattr(self, field)
            if value is not None and not isinstance(value, PublicationSuccessProof):
                raise ReleaseControlError(f"{field} is invalid")


@dataclass(frozen=True, slots=True)
class PublisherRecoveryRequest:
    """Exact recovery target requested by an already authenticated controller."""

    target: PublisherAuthority
    receipt_bound: bool
    pending_takeover_durable: bool = False
    request_kaggle_upload: bool = False

    def __post_init__(self) -> None:
        if not isinstance(self.target, PublisherAuthority):
            raise ReleaseControlError("recovery target is invalid")
        _require_bool(self.receipt_bound, field="receipt_bound")
        _require_bool(self.pending_takeover_durable, field="pending_takeover_durable")
        _require_bool(self.request_kaggle_upload, field="request_kaggle_upload")


@dataclass(frozen=True, slots=True)
class ReleaseDecision:
    """One fail-closed publication recovery decision."""

    action: ReleaseAction
    reason: ReleaseDecisionReason
    kaggle_upload_allowed: bool

    def __post_init__(self) -> None:
        if not isinstance(self.action, ReleaseAction):
            raise ReleaseControlError("release action is invalid")
        if not isinstance(self.reason, ReleaseDecisionReason):
            raise ReleaseControlError("release decision reason is invalid")
        _require_bool(self.kaggle_upload_allowed, field="kaggle_upload_allowed")
        if self.action is ReleaseAction.BLOCKED and self.kaggle_upload_allowed:
            raise ReleaseControlError("a blocked release decision cannot allow Kaggle upload")


def _blocked(reason: ReleaseDecisionReason) -> ReleaseDecision:
    return ReleaseDecision(
        action=ReleaseAction.BLOCKED,
        reason=reason,
        kaggle_upload_allowed=False,
    )


def _success_proof_is_valid(
    proof: PublicationSuccessProof | None,
    *,
    authority: PublisherAuthority,
) -> bool:
    return proof is not None and proof.matches(authority)


def decide_publication_recovery(
    evidence: ReleaseStateEvidence,
    request: PublisherRecoveryRequest,
) -> ReleaseDecision:
    """Choose the sole safe recovery lane from stable, receipt-bound evidence.

    ``ABSENT`` authorizes dispatch of one new run but never authorizes a direct
    Kaggle call. ``PENDING`` may admit the exact publisher job to claim and upload.
    ``IN_PROGRESS`` is reconciliation-only because the prior upload outcome may be
    ambiguous. Exact durable and remote success can continue only with
    post-publication work.
    """

    if not isinstance(evidence, ReleaseStateEvidence):
        raise ReleaseControlError("release evidence is invalid")
    if not isinstance(request, PublisherRecoveryRequest):
        raise ReleaseControlError("recovery request is invalid")
    if not evidence.writer_inventory_stable or not evidence.ledger_inventory_stable:
        return _blocked(ReleaseDecisionReason.INVENTORY_NOT_STABLE)
    if not evidence.publisher_terminal:
        return _blocked(ReleaseDecisionReason.PUBLISHER_NOT_TERMINAL)
    if evidence.active_writers:
        return _blocked(ReleaseDecisionReason.ACTIVE_WRITER_EXISTS)
    if evidence.competing_writer_detected:
        return _blocked(ReleaseDecisionReason.COMPETING_WRITER_EXISTS)
    if not request.receipt_bound:
        return _blocked(ReleaseDecisionReason.RECOVERY_RECEIPT_NOT_BOUND)
    if request.target.semantic_identity != evidence.authority.semantic_identity:
        return _blocked(ReleaseDecisionReason.RECOVERY_PROVENANCE_MISMATCH)

    state = evidence.ledger_state
    if state is DurableLedgerState.ABSENT:
        if evidence.durable_success is not None or evidence.remote_success is not None:
            return _blocked(ReleaseDecisionReason.SUCCESS_EVIDENCE_INCONSISTENT)
        if evidence.zero_active_replay_used:
            return _blocked(ReleaseDecisionReason.ZERO_ACTIVE_REPLAY_ALREADY_USED)
        if (
            request.target.run_id == evidence.authority.run_id
            or request.target.publisher_job_id == evidence.authority.publisher_job_id
        ):
            return _blocked(ReleaseDecisionReason.RECOVERY_IS_NOT_A_NEW_RUN)
        if request.request_kaggle_upload:
            return _blocked(ReleaseDecisionReason.DURABLE_INTENT_REQUIRED)
        return ReleaseDecision(
            action=ReleaseAction.NEW_ZERO_ACTIVE_REPLAY,
            reason=ReleaseDecisionReason.PRE_INTENT_REPLAY_ALLOWED,
            kaggle_upload_allowed=False,
        )

    if evidence.durable_success is not None and state is not DurableLedgerState.SUCCESS:
        return _blocked(ReleaseDecisionReason.SUCCESS_EVIDENCE_INCONSISTENT)
    if evidence.remote_success is not None and not _success_proof_is_valid(
        evidence.remote_success,
        authority=evidence.authority,
    ):
        return _blocked(ReleaseDecisionReason.SUCCESS_EVIDENCE_INCONSISTENT)

    if state is DurableLedgerState.PENDING:
        if evidence.remote_success is not None:
            if request.request_kaggle_upload:
                return _blocked(ReleaseDecisionReason.PUBLICATION_ALREADY_SUCCEEDED)
            return ReleaseDecision(
                action=ReleaseAction.RECONCILE_WITHOUT_UPLOAD,
                reason=ReleaseDecisionReason.RECONCILIATION_WITHOUT_UPLOAD_REQUIRED,
                kaggle_upload_allowed=False,
            )
        if request.target.execution_identity == evidence.authority.execution_identity:
            return _blocked(ReleaseDecisionReason.RECOVERY_IS_NOT_A_NEW_RUN)
        if not request.pending_takeover_durable:
            return _blocked(ReleaseDecisionReason.PENDING_TAKEOVER_REQUIRED)
        if not request.request_kaggle_upload:
            return _blocked(ReleaseDecisionReason.PENDING_TAKEOVER_REQUIRED)
        return ReleaseDecision(
            action=ReleaseAction.CLAIM_PENDING_TAKEOVER,
            reason=ReleaseDecisionReason.PENDING_TAKEOVER_DURABLY_CLAIMABLE,
            kaggle_upload_allowed=True,
        )

    if state is DurableLedgerState.IN_PROGRESS:
        if request.request_kaggle_upload:
            return _blocked(ReleaseDecisionReason.RECONCILIATION_ONLY)
        return ReleaseDecision(
            action=ReleaseAction.RECONCILE_WITHOUT_UPLOAD,
            reason=ReleaseDecisionReason.RECONCILIATION_WITHOUT_UPLOAD_REQUIRED,
            kaggle_upload_allowed=False,
        )

    if not _success_proof_is_valid(
        evidence.durable_success,
        authority=evidence.authority,
    ) or not _success_proof_is_valid(
        evidence.remote_success,
        authority=evidence.authority,
    ):
        return _blocked(ReleaseDecisionReason.SUCCESS_EVIDENCE_INCONSISTENT)
    if evidence.durable_success != evidence.remote_success:
        return _blocked(ReleaseDecisionReason.SUCCESS_EVIDENCE_INCONSISTENT)
    if request.request_kaggle_upload:
        return _blocked(ReleaseDecisionReason.PUBLICATION_ALREADY_SUCCEEDED)
    return ReleaseDecision(
        action=ReleaseAction.CONTINUE_POST_PUBLICATION,
        reason=ReleaseDecisionReason.EXACT_PUBLICATION_ALREADY_SUCCEEDED,
        kaggle_upload_allowed=False,
    )


def _require_relative_file(value: object, *, field: str) -> None:
    if (
        not isinstance(value, str)
        or not value
        or value.startswith("/")
        or "\\" in value
        or "//" in value
        or any(part in {"", ".", ".."} for part in value.split("/"))
    ):
        raise ReleaseControlError(f"{field} is invalid")


@dataclass(frozen=True, slots=True)
class MetadataHeadEvidence:
    """Git commit evidence for the frozen source or one metadata-only child."""

    repository: str
    source_sha: str
    metadata_head_sha: str
    parent_shas: tuple[str, ...]
    changed_files: tuple[str, ...]
    byte_reproducible: bool

    def __post_init__(self) -> None:
        _require_repository(self.repository, field="metadata repository")
        _require_hex(self.source_sha, field="metadata source_sha", length=40)
        _require_hex(self.metadata_head_sha, field="metadata_head_sha", length=40)
        _require_tuple(self.parent_shas, field="metadata parent_shas")
        _require_tuple(self.changed_files, field="metadata changed_files")
        _require_bool(self.byte_reproducible, field="metadata byte_reproducible")
        for parent_sha in self.parent_shas:
            _require_hex(parent_sha, field="metadata parent_sha", length=40)
        for changed_file in self.changed_files:
            _require_relative_file(changed_file, field="metadata changed file")
        if len(self.parent_shas) != len(set(self.parent_shas)):
            raise ReleaseControlError("metadata parent_shas contains duplicates")
        if len(self.changed_files) != len(set(self.changed_files)):
            raise ReleaseControlError("metadata changed_files contains duplicates")


@dataclass(frozen=True, slots=True)
class CIDispatchReceipt:
    """Exact receipt returned by an explicit CI workflow dispatch."""

    repository: str
    workflow_id: int
    workflow_path: str
    run_id: int
    head_sha: str
    event: str
    explicitly_dispatched: bool

    def __post_init__(self) -> None:
        _require_repository(self.repository, field="CI dispatch repository")
        _require_positive_int(self.workflow_id, field="CI dispatch workflow_id")
        _require_workflow_path(self.workflow_path, field="CI dispatch workflow_path")
        _require_positive_int(self.run_id, field="CI dispatch run_id")
        _require_hex(self.head_sha, field="CI dispatch head_sha", length=40)
        if not isinstance(self.event, str) or not self.event:
            raise ReleaseControlError("CI dispatch event is invalid")
        _require_bool(self.explicitly_dispatched, field="CI explicitly_dispatched")


@dataclass(frozen=True, slots=True)
class CIJobReceipt:
    """Direct receipt for one job in the explicitly dispatched CI run."""

    name: str
    job_id: int
    run_id: int
    run_attempt: int
    head_sha: str
    status: str
    conclusion: str

    def __post_init__(self) -> None:
        if not isinstance(self.name, str) or not self.name:
            raise ReleaseControlError("CI job name is invalid")
        _require_positive_int(self.job_id, field="CI job_id")
        _require_positive_int(self.run_id, field="CI job run_id")
        _require_positive_int(self.run_attempt, field="CI job run_attempt")
        _require_hex(self.head_sha, field="CI job head_sha", length=40)
        if not isinstance(self.status, str) or not self.status:
            raise ReleaseControlError("CI job status is invalid")
        if not isinstance(self.conclusion, str) or not self.conclusion:
            raise ReleaseControlError("CI job conclusion is invalid")


@dataclass(frozen=True, slots=True)
class CIRunReceipt:
    """Directly re-read identity and complete job inventory for exact-head CI."""

    repository: str
    workflow_id: int
    workflow_path: str
    run_id: int
    run_attempt: int
    head_sha: str
    event: str
    directly_verified: bool
    jobs: tuple[CIJobReceipt, ...]

    def __post_init__(self) -> None:
        _require_repository(self.repository, field="CI run repository")
        _require_positive_int(self.workflow_id, field="CI run workflow_id")
        _require_workflow_path(self.workflow_path, field="CI run workflow_path")
        _require_positive_int(self.run_id, field="CI run_id")
        _require_positive_int(self.run_attempt, field="CI run_attempt")
        _require_hex(self.head_sha, field="CI run head_sha", length=40)
        if not isinstance(self.event, str) or not self.event:
            raise ReleaseControlError("CI run event is invalid")
        _require_bool(self.directly_verified, field="CI directly_verified")
        _require_tuple(self.jobs, field="CI jobs")
        if not all(isinstance(job, CIJobReceipt) for job in self.jobs):
            raise ReleaseControlError("CI jobs contains invalid evidence")


@dataclass(frozen=True, slots=True)
class MetadataHeadValidation:
    """Validated metadata head and its exact CI closeout, when required."""

    metadata_head_sha: str
    metadata_child_created: bool
    ci_run_id: int | None

    def __post_init__(self) -> None:
        _require_hex(self.metadata_head_sha, field="validated metadata_head_sha", length=40)
        _require_bool(self.metadata_child_created, field="metadata_child_created")
        if self.ci_run_id is not None:
            _require_positive_int(self.ci_run_id, field="validated CI run_id")
        if self.metadata_child_created != (self.ci_run_id is not None):
            raise ReleaseControlError("metadata child and CI identity are inconsistent")


def validate_metadata_head(
    head: MetadataHeadEvidence,
    *,
    dispatch: CIDispatchReceipt | None = None,
    ci_run: CIRunReceipt | None = None,
) -> MetadataHeadValidation:
    """Validate metadata head ``M`` and exact explicitly dispatched CI evidence."""

    if not isinstance(head, MetadataHeadEvidence):
        raise ReleaseControlError("metadata head evidence is invalid")
    if head.metadata_head_sha == head.source_sha:
        if head.parent_shas or head.changed_files or not head.byte_reproducible:
            raise ReleaseControlError("unchanged metadata head evidence is inconsistent")
        if dispatch is not None or ci_run is not None:
            raise ReleaseControlError("unchanged metadata head must not claim child CI")
        return MetadataHeadValidation(
            metadata_head_sha=head.metadata_head_sha,
            metadata_child_created=False,
            ci_run_id=None,
        )

    if head.parent_shas != (head.source_sha,):
        raise ReleaseControlError("metadata child is not one direct non-merge child")
    if not head.changed_files or not set(head.changed_files).issubset(METADATA_ONLY_ALLOWED_FILES):
        raise ReleaseControlError("metadata child changed files are not allowlisted")
    if not head.byte_reproducible:
        raise ReleaseControlError("metadata child is not byte-reproducible")
    if not isinstance(dispatch, CIDispatchReceipt) or not isinstance(ci_run, CIRunReceipt):
        raise ReleaseControlError("metadata child requires explicit direct CI evidence")
    if (
        not dispatch.explicitly_dispatched
        or dispatch.event != "workflow_dispatch"
        or dispatch.workflow_path != CI_WORKFLOW_PATH
    ):
        raise ReleaseControlError("metadata child CI was not explicitly dispatched")
    if (
        not ci_run.directly_verified
        or ci_run.event != "workflow_dispatch"
        or ci_run.workflow_path != CI_WORKFLOW_PATH
        or ci_run.run_attempt != 1
    ):
        raise ReleaseControlError("metadata child CI run was not directly verified")
    dispatch_identity = (
        dispatch.repository,
        dispatch.workflow_id,
        dispatch.workflow_path,
        dispatch.run_id,
        dispatch.head_sha,
        dispatch.event,
    )
    direct_identity = (
        ci_run.repository,
        ci_run.workflow_id,
        ci_run.workflow_path,
        ci_run.run_id,
        ci_run.head_sha,
        ci_run.event,
    )
    if dispatch_identity != direct_identity:
        raise ReleaseControlError("metadata child CI dispatch and direct run provenance differ")
    if dispatch.repository != head.repository or dispatch.head_sha != head.metadata_head_sha:
        raise ReleaseControlError("metadata child CI does not bind exact metadata head")

    job_names = [job.name for job in ci_run.jobs]
    job_ids = [job.job_id for job in ci_run.jobs]
    if len(job_names) != len(set(job_names)) or len(job_ids) != len(set(job_ids)):
        raise ReleaseControlError("metadata child CI job inventory is ambiguous")
    if frozenset(job_names) != REQUIRED_METADATA_CI_JOBS:
        raise ReleaseControlError("metadata child CI job inventory is incomplete")
    for job in ci_run.jobs:
        if (
            job.run_id != ci_run.run_id
            or job.run_attempt != ci_run.run_attempt
            or job.head_sha != ci_run.head_sha
        ):
            raise ReleaseControlError("metadata child CI job provenance differs")
        if job.status != "completed" or job.conclusion != "success":
            raise ReleaseControlError("metadata child CI job did not succeed")

    return MetadataHeadValidation(
        metadata_head_sha=head.metadata_head_sha,
        metadata_child_created=True,
        ci_run_id=ci_run.run_id,
    )
