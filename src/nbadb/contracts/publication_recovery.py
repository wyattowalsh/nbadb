"""Strict durable evidence for cross-run publication recovery.

These receipts contain no mutable lookup or status authority.  They bind two
stable observations, the original and recovery executors, an immutable handoff,
and (for a durable takeover status) the exact uploaded receipt member.  Every
self digest is recomputed from canonical bytes excluding that digest field.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, fields
from datetime import datetime
from typing import Any, ClassVar, Final, Self, cast

from nbadb.contracts.actions_artifact import ArtifactMemberIdentityV1
from nbadb.contracts.receipt_digest import (
    CanonicalReceiptError,
    canonical_receipt_digest,
    verify_receipt_digest,
)
from nbadb.kaggle.publication_ledger import ExecutorReceipt

__all__ = [
    "PUBLICATION_RECOVERY_SCHEMA_VERSION",
    "PendingTakeoverReceiptV1",
    "PendingTakeoverStatusReceiptV1",
    "PublicationRecoveryContractError",
    "StablePublicationInventoryReceiptV1",
]

PUBLICATION_RECOVERY_SCHEMA_VERSION: Final = 1
_HEX_32_RE: Final = re.compile(r"[0-9a-f]{32}\Z")
_HEX_40_RE: Final = re.compile(r"[0-9a-f]{40}\Z")
_HEX_64_RE: Final = re.compile(r"[0-9a-f]{64}\Z")
_REPOSITORY_RE: Final = re.compile(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+\Z")
_JOB_RE: Final = re.compile(r"[A-Za-z0-9_.-]+\Z")
_TERMINAL_CONCLUSIONS: Final = frozenset(
    {
        "action_required",
        "cancelled",
        "failure",
        "neutral",
        "skipped",
        "stale",
        "startup_failure",
        "success",
        "timed_out",
    }
)


class PublicationRecoveryContractError(ValueError):
    """A publication-recovery receipt is malformed, ambiguous, or tampered."""


def _require_text(value: object, field: str) -> str:
    if not isinstance(value, str) or not value or value.strip() != value:
        raise PublicationRecoveryContractError(f"{field} must be a nonempty exact string")
    return value


def _require_hex(value: object, field: str, *, length: int = 64) -> str:
    text = _require_text(value, field)
    pattern = {32: _HEX_32_RE, 40: _HEX_40_RE, 64: _HEX_64_RE}[length]
    if pattern.fullmatch(text) is None:
        raise PublicationRecoveryContractError(f"{field} must be {length} lowercase hex characters")
    return text


def _require_positive(value: object, field: str) -> int:
    if type(value) is not int or value < 1:
        raise PublicationRecoveryContractError(f"{field} must be a positive integer")
    return value


def _require_bool(value: object, field: str) -> bool:
    if type(value) is not bool:
        raise PublicationRecoveryContractError(f"{field} must be an exact boolean")
    return value


def _require_timestamp(value: object, field: str) -> str:
    text = _require_text(value, field)
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError as exc:
        raise PublicationRecoveryContractError(f"{field} must be an ISO-8601 timestamp") from exc
    if parsed.tzinfo is None:
        raise PublicationRecoveryContractError(f"{field} must include a timezone")
    return text


def _require_repository(value: object, field: str) -> str:
    text = _require_text(value, field)
    if _REPOSITORY_RE.fullmatch(text) is None:
        raise PublicationRecoveryContractError(f"{field} must be owner/name")
    return text


def _require_executor(value: object, field: str) -> ExecutorReceipt:
    if not isinstance(value, ExecutorReceipt):
        raise PublicationRecoveryContractError(f"{field} must be an ExecutorReceipt")
    _require_repository(value.repository, f"{field}.repository")
    _require_positive(value.run_id, f"{field}.run_id")
    _require_positive(value.run_attempt, f"{field}.run_attempt")
    _require_positive(value.workflow_id, f"{field}.workflow_id")
    _require_positive(value.job_id, f"{field}.job_id")
    _require_hex(value.workflow_sha, f"{field}.workflow_sha", length=40)
    _require_hex(value.workflow_content_sha256, f"{field}.workflow_content_sha256")
    _require_hex(value.admission_digest, f"{field}.admission_digest")
    if _JOB_RE.fullmatch(value.job) is None:
        raise PublicationRecoveryContractError(f"{field}.job is invalid")
    return value


def _executor_payload(value: ExecutorReceipt) -> dict[str, object]:
    return dict(value.to_dict())


def _executor_from_payload(value: object, field: str) -> ExecutorReceipt:
    if not isinstance(value, dict):
        raise PublicationRecoveryContractError(f"{field} must be an object")
    expected = {
        "repository",
        "run_id",
        "run_attempt",
        "workflow_id",
        "workflow",
        "workflow_path",
        "workflow_sha",
        "job",
        "job_id",
        "job_url",
        "actor",
        "log_url",
        "workflow_content_sha256",
        "admission_digest",
    }
    if set(value) != expected:
        raise PublicationRecoveryContractError(f"{field} has an invalid exact-key shape")
    receipt = ExecutorReceipt(
        repository=_require_repository(value.get("repository"), f"{field}.repository"),
        run_id=_require_positive(value.get("run_id"), f"{field}.run_id"),
        run_attempt=_require_positive(value.get("run_attempt"), f"{field}.run_attempt"),
        workflow_id=_require_positive(value.get("workflow_id"), f"{field}.workflow_id"),
        workflow=_require_text(value.get("workflow"), f"{field}.workflow"),
        workflow_path=_require_text(value.get("workflow_path"), f"{field}.workflow_path"),
        workflow_sha=_require_hex(value.get("workflow_sha"), f"{field}.workflow_sha", length=40),
        job=_require_text(value.get("job"), f"{field}.job"),
        job_id=_require_positive(value.get("job_id"), f"{field}.job_id"),
        job_url=_require_text(value.get("job_url"), f"{field}.job_url"),
        actor=_require_text(value.get("actor"), f"{field}.actor"),
        log_url=_require_text(value.get("log_url"), f"{field}.log_url"),
        workflow_content_sha256=_require_hex(
            value.get("workflow_content_sha256"), f"{field}.workflow_content_sha256"
        ),
        admission_digest=_require_hex(value.get("admission_digest"), f"{field}.admission_digest"),
    )
    return _require_executor(receipt, field)


def _exact_keys(payload: object, expected: set[str], label: str) -> dict[str, object]:
    if not isinstance(payload, dict) or set(payload) != expected:
        raise PublicationRecoveryContractError(f"{label} has an invalid exact-key shape")
    return cast("dict[str, object]", payload)


def _build_sealed[ReceiptT](
    cls: type[ReceiptT], digest_field: str, values: dict[str, Any]
) -> ReceiptT:
    expected = {field.name for field in fields(cast("Any", cls))} - {digest_field}
    if set(values) != expected:
        raise PublicationRecoveryContractError(f"{cls.__name__}.build has an invalid field set")
    proto = object.__new__(cls)
    for name in expected:
        object.__setattr__(proto, name, values[name])
    object.__setattr__(proto, digest_field, "0" * 64)
    cast("Any", proto)._validate()
    digest = canonical_receipt_digest(proto, digest_field=digest_field)
    return cls(**{**values, digest_field: digest})


class _Sealed:
    _DIGEST_FIELD: ClassVar[str]

    def __post_init__(self) -> None:
        self._validate()
        try:
            verify_receipt_digest(self, digest_field=self._DIGEST_FIELD)
        except CanonicalReceiptError as exc:
            raise PublicationRecoveryContractError(str(exc)) from exc

    def _validate(self) -> None:
        raise NotImplementedError

    def verify(self) -> None:
        self.__post_init__()


@dataclass(frozen=True, slots=True)
class StablePublicationInventoryReceiptV1(_Sealed):
    """Two independently sampled, byte-stable publication inventories."""

    repository: str
    dataset: str
    first_sampled_at: str
    second_sampled_at: str
    first_writer_inventory_sha256: str
    second_writer_inventory_sha256: str
    first_ledger_inventory_sha256: str
    second_ledger_inventory_sha256: str
    first_remote_inventory_sha256: str
    second_remote_inventory_sha256: str
    first_active_writer_count: int
    second_active_writer_count: int
    first_resolving_marker_present: bool
    second_resolving_marker_present: bool
    first_competing_publisher_present: bool
    second_competing_publisher_present: bool
    inventory_sha256: str

    _DIGEST_FIELD: ClassVar[str] = "inventory_sha256"

    def _validate(self) -> None:
        _require_repository(self.repository, "repository")
        dataset = _require_text(self.dataset, "dataset")
        if dataset.count("/") != 1:
            raise PublicationRecoveryContractError("dataset must be owner/name")
        first = _require_timestamp(self.first_sampled_at, "first_sampled_at")
        second = _require_timestamp(self.second_sampled_at, "second_sampled_at")
        if datetime.fromisoformat(first.replace("Z", "+00:00")) >= datetime.fromisoformat(
            second.replace("Z", "+00:00")
        ):
            raise PublicationRecoveryContractError(
                "inventory samples must be independently ordered"
            )
        for prefix in ("writer", "ledger", "remote"):
            left = _require_hex(
                getattr(self, f"first_{prefix}_inventory_sha256"), f"first_{prefix}"
            )
            right = _require_hex(
                getattr(self, f"second_{prefix}_inventory_sha256"), f"second_{prefix}"
            )
            if left != right:
                raise PublicationRecoveryContractError(f"{prefix} inventory did not stabilize")
        if self.first_active_writer_count != 0 or self.second_active_writer_count != 0:
            raise PublicationRecoveryContractError("stable inventory contains an active writer")
        for field in (
            "first_resolving_marker_present",
            "second_resolving_marker_present",
            "first_competing_publisher_present",
            "second_competing_publisher_present",
        ):
            if _require_bool(getattr(self, field), field):
                raise PublicationRecoveryContractError(
                    "stable inventory contains resolving competition"
                )
        _require_hex(self.inventory_sha256, "inventory_sha256")

    @classmethod
    def build(cls, **values: Any) -> Self:
        return _build_sealed(cls, cls._DIGEST_FIELD, values)

    def to_payload(self) -> dict[str, object]:
        payload = {field.name: getattr(self, field.name) for field in fields(self)}
        payload["schema_version"] = PUBLICATION_RECOVERY_SCHEMA_VERSION
        return payload

    @classmethod
    def from_payload(cls, payload: object) -> Self:
        expected = {field.name for field in fields(cls)} | {"schema_version"}
        value = _exact_keys(payload, expected, cls.__name__)
        if value.get("schema_version") != PUBLICATION_RECOVERY_SCHEMA_VERSION:
            raise PublicationRecoveryContractError("unsupported stable-inventory schema version")
        return cls(
            repository=cast("str", value.get("repository")),
            dataset=cast("str", value.get("dataset")),
            first_sampled_at=cast("str", value.get("first_sampled_at")),
            second_sampled_at=cast("str", value.get("second_sampled_at")),
            first_writer_inventory_sha256=cast("str", value.get("first_writer_inventory_sha256")),
            second_writer_inventory_sha256=cast("str", value.get("second_writer_inventory_sha256")),
            first_ledger_inventory_sha256=cast("str", value.get("first_ledger_inventory_sha256")),
            second_ledger_inventory_sha256=cast("str", value.get("second_ledger_inventory_sha256")),
            first_remote_inventory_sha256=cast("str", value.get("first_remote_inventory_sha256")),
            second_remote_inventory_sha256=cast("str", value.get("second_remote_inventory_sha256")),
            first_active_writer_count=cast("int", value.get("first_active_writer_count")),
            second_active_writer_count=cast("int", value.get("second_active_writer_count")),
            first_resolving_marker_present=cast(
                "bool", value.get("first_resolving_marker_present")
            ),
            second_resolving_marker_present=cast(
                "bool", value.get("second_resolving_marker_present")
            ),
            first_competing_publisher_present=cast(
                "bool", value.get("first_competing_publisher_present")
            ),
            second_competing_publisher_present=cast(
                "bool", value.get("second_competing_publisher_present")
            ),
            inventory_sha256=cast("str", value.get("inventory_sha256")),
        )


@dataclass(frozen=True, slots=True)
class PendingTakeoverReceiptV1(_Sealed):
    """Exact cross-run transfer authority for one still-pending intent."""

    repository: str
    dataset: str
    intent_id: str
    deployment_id: int
    original_executor: ExecutorReceipt
    origin_terminal_conclusion: str
    recovery_executor: ExecutorReceipt
    terminal_handoff_sha256: str
    stable_inventory: StablePublicationInventoryReceiptV1
    nonce: str
    takeover_sha256: str

    _DIGEST_FIELD: ClassVar[str] = "takeover_sha256"

    def _validate(self) -> None:
        repository = _require_repository(self.repository, "repository")
        if _require_text(self.dataset, "dataset").count("/") != 1:
            raise PublicationRecoveryContractError("dataset must be owner/name")
        _require_hex(self.intent_id, "intent_id")
        _require_positive(self.deployment_id, "deployment_id")
        origin = _require_executor(self.original_executor, "original_executor")
        recovery = _require_executor(self.recovery_executor, "recovery_executor")
        conclusion = _require_text(self.origin_terminal_conclusion, "origin_terminal_conclusion")
        if conclusion not in _TERMINAL_CONCLUSIONS:
            raise PublicationRecoveryContractError("origin publisher is not terminal")
        if origin.repository != repository or recovery.repository != repository:
            raise PublicationRecoveryContractError("takeover executor repository differs")
        if (origin.run_id, origin.run_attempt, origin.job_id) == (
            recovery.run_id,
            recovery.run_attempt,
            recovery.job_id,
        ):
            raise PublicationRecoveryContractError("takeover recovery executor must be distinct")
        _require_hex(self.terminal_handoff_sha256, "terminal_handoff_sha256")
        if not isinstance(self.stable_inventory, StablePublicationInventoryReceiptV1):
            raise PublicationRecoveryContractError("stable_inventory is invalid")
        self.stable_inventory.verify()
        if (
            self.stable_inventory.repository != repository
            or self.stable_inventory.dataset != self.dataset
        ):
            raise PublicationRecoveryContractError("takeover stable inventory provenance differs")
        _require_hex(self.nonce, "nonce", length=32)
        _require_hex(self.takeover_sha256, "takeover_sha256")

    @classmethod
    def build(cls, **values: Any) -> Self:
        return _build_sealed(cls, cls._DIGEST_FIELD, values)

    def to_payload(self) -> dict[str, object]:
        payload: dict[str, object] = {
            "repository": self.repository,
            "dataset": self.dataset,
            "intent_id": self.intent_id,
            "deployment_id": self.deployment_id,
            "original_executor": _executor_payload(self.original_executor),
            "origin_terminal_conclusion": self.origin_terminal_conclusion,
            "recovery_executor": _executor_payload(self.recovery_executor),
            "terminal_handoff_sha256": self.terminal_handoff_sha256,
            "stable_inventory": self.stable_inventory.to_payload(),
            "nonce": self.nonce,
            "takeover_sha256": self.takeover_sha256,
            "schema_version": PUBLICATION_RECOVERY_SCHEMA_VERSION,
        }
        return payload

    @classmethod
    def from_payload(cls, payload: object) -> Self:
        expected = {
            "repository",
            "dataset",
            "intent_id",
            "deployment_id",
            "original_executor",
            "origin_terminal_conclusion",
            "recovery_executor",
            "terminal_handoff_sha256",
            "stable_inventory",
            "nonce",
            "takeover_sha256",
            "schema_version",
        }
        value = _exact_keys(payload, expected, cls.__name__)
        if value.get("schema_version") != PUBLICATION_RECOVERY_SCHEMA_VERSION:
            raise PublicationRecoveryContractError("unsupported takeover schema version")
        return cls(
            repository=cast("str", value.get("repository")),
            dataset=cast("str", value.get("dataset")),
            intent_id=cast("str", value.get("intent_id")),
            deployment_id=cast("int", value.get("deployment_id")),
            original_executor=_executor_from_payload(
                value.get("original_executor"), "original_executor"
            ),
            origin_terminal_conclusion=cast("str", value.get("origin_terminal_conclusion")),
            recovery_executor=_executor_from_payload(
                value.get("recovery_executor"), "recovery_executor"
            ),
            terminal_handoff_sha256=cast("str", value.get("terminal_handoff_sha256")),
            stable_inventory=StablePublicationInventoryReceiptV1.from_payload(
                value.get("stable_inventory")
            ),
            nonce=cast("str", value.get("nonce")),
            takeover_sha256=cast("str", value.get("takeover_sha256")),
        )


@dataclass(frozen=True, slots=True)
class PendingTakeoverStatusReceiptV1(_Sealed):
    """Durable pending-status proof binding one takeover artifact member."""

    deployment_id: int
    status_id: int
    state: str
    creator_login: str
    creator_id: int
    description_token: str
    takeover_member: ArtifactMemberIdentityV1
    takeover_sha256: str
    recovery_executor: ExecutorReceipt
    status_sha256: str

    _DIGEST_FIELD: ClassVar[str] = "status_sha256"

    def _validate(self) -> None:
        _require_positive(self.deployment_id, "deployment_id")
        _require_positive(self.status_id, "status_id")
        if self.state != "pending":
            raise PublicationRecoveryContractError("takeover status state must be pending")
        _require_text(self.creator_login, "creator_login")
        _require_positive(self.creator_id, "creator_id")
        _require_text(self.description_token, "description_token")
        if not isinstance(self.takeover_member, ArtifactMemberIdentityV1):
            raise PublicationRecoveryContractError("takeover_member is invalid")
        _require_hex(self.takeover_sha256, "takeover_sha256")
        _require_executor(self.recovery_executor, "recovery_executor")
        if self.takeover_member.member_sha256 != self.takeover_sha256:
            raise PublicationRecoveryContractError("takeover member digest differs")
        _require_hex(self.status_sha256, "status_sha256")

    @classmethod
    def build(cls, **values: Any) -> Self:
        return _build_sealed(cls, cls._DIGEST_FIELD, values)

    def to_payload(self) -> dict[str, object]:
        return {
            "schema_version": PUBLICATION_RECOVERY_SCHEMA_VERSION,
            "deployment_id": self.deployment_id,
            "status_id": self.status_id,
            "state": self.state,
            "creator_login": self.creator_login,
            "creator_id": self.creator_id,
            "description_token": self.description_token,
            "takeover_member": self.takeover_member.to_payload(),
            "takeover_sha256": self.takeover_sha256,
            "recovery_executor": _executor_payload(self.recovery_executor),
            "status_sha256": self.status_sha256,
        }

    @classmethod
    def from_payload(cls, payload: object) -> Self:
        expected = {
            "schema_version",
            "deployment_id",
            "status_id",
            "state",
            "creator_login",
            "creator_id",
            "description_token",
            "takeover_member",
            "takeover_sha256",
            "recovery_executor",
            "status_sha256",
        }
        value = _exact_keys(payload, expected, cls.__name__)
        if value.get("schema_version") != PUBLICATION_RECOVERY_SCHEMA_VERSION:
            raise PublicationRecoveryContractError("unsupported takeover-status schema version")
        return cls(
            deployment_id=cast("int", value.get("deployment_id")),
            status_id=cast("int", value.get("status_id")),
            state=cast("str", value.get("state")),
            creator_login=cast("str", value.get("creator_login")),
            creator_id=cast("int", value.get("creator_id")),
            description_token=cast("str", value.get("description_token")),
            takeover_member=ArtifactMemberIdentityV1.from_payload(value.get("takeover_member")),
            takeover_sha256=cast("str", value.get("takeover_sha256")),
            recovery_executor=_executor_from_payload(
                value.get("recovery_executor"), "recovery_executor"
            ),
            status_sha256=cast("str", value.get("status_sha256")),
        )
