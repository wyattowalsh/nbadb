"""Digest-bound review receipts for authored model contracts.

This module records structural evidence for an authored decision and a distinct
reviewer decision.  It can prove canonical identities, role/task separation,
and required validation receipts; it cannot by itself prove that two declared
identities correspond to genuinely independent humans or processes.
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from typing import TYPE_CHECKING, ClassVar, Literal, Self, cast

if TYPE_CHECKING:
    from collections.abc import Mapping

__all__ = [
    "MODEL_REVIEW_RECEIPT_KIND",
    "MODEL_REVIEW_RECEIPT_SCHEMA_VERSION",
    "FindingSeverity",
    "FindingStatus",
    "IndependenceEvidenceKind",
    "ReviewDisposition",
    "ReviewEvidenceError",
    "ReviewFindingV1",
    "ReviewReceiptV1",
    "ReviewValidationReceiptV1",
    "ValidationClass",
]

MODEL_REVIEW_RECEIPT_SCHEMA_VERSION = 1
MODEL_REVIEW_RECEIPT_KIND = "nbadb_model_review_receipt"

type FindingSeverity = Literal["blocker", "major", "minor", "note"]
type FindingStatus = Literal["open", "resolved"]
type IndependenceEvidenceKind = Literal[
    "independent_agent_review",
    "maintainer_review",
    "protected_environment_approval",
    "qualified_external_review",
]
type ReviewDisposition = Literal["accepted", "changes_required"]
type ValidationClass = Literal["positive", "negative", "mutation"]

_SHA256_RE = re.compile(r"[0-9a-f]{64}\Z", flags=re.ASCII)
_SAFE_ID_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.:@/-]{0,511}\Z", flags=re.ASCII)
_FINDING_SEVERITIES = frozenset({"blocker", "major", "minor", "note"})
_FINDING_STATUSES = frozenset({"open", "resolved"})
_INDEPENDENCE_EVIDENCE_KINDS = frozenset(
    {
        "independent_agent_review",
        "maintainer_review",
        "protected_environment_approval",
        "qualified_external_review",
    }
)
_REVIEW_DISPOSITIONS = frozenset({"accepted", "changes_required"})
_VALIDATION_CLASSES = frozenset({"positive", "negative", "mutation"})


class ReviewEvidenceError(ValueError):
    """An authored-review receipt or one of its evidence rows is invalid."""


def _canonical_bytes(value: object) -> bytes:
    try:
        return json.dumps(
            value,
            allow_nan=False,
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        ).encode("utf-8")
    except (TypeError, ValueError) as exc:
        raise ReviewEvidenceError("review evidence is not canonical JSON") from exc


def _sha256(value: object) -> str:
    return hashlib.sha256(_canonical_bytes(value)).hexdigest()


def _require_sha256(value: object, *, field: str) -> str:
    if not isinstance(value, str) or _SHA256_RE.fullmatch(value) is None:
        raise ReviewEvidenceError(f"{field} must be a lowercase SHA-256")
    return value


def _require_id(value: object, *, field: str) -> str:
    if not isinstance(value, str) or _SAFE_ID_RE.fullmatch(value) is None:
        raise ReviewEvidenceError(f"{field} must be a safe nonempty identifier")
    return value


def _require_exact_keys(
    payload: Mapping[str, object],
    expected: frozenset[str],
    *,
    label: str,
) -> None:
    if any(not isinstance(key, str) for key in payload):
        raise ReviewEvidenceError(f"{label} keys must be strings")
    actual = frozenset(payload)
    if actual == expected:
        return
    missing = ",".join(sorted(expected - actual))
    unexpected = ",".join(sorted(actual - expected))
    raise ReviewEvidenceError(f"{label} fields differ (missing={missing}; unexpected={unexpected})")


def _require_mapping(value: object, *, label: str) -> Mapping[str, object]:
    if type(value) is not dict:
        raise ReviewEvidenceError(f"{label} must be an object")
    return cast("Mapping[str, object]", value)


def _require_sorted_unique_sha256s(value: object) -> tuple[str, ...]:
    if type(value) is not list:
        raise ReviewEvidenceError("accepted_input_sha256s must be an array")
    values = tuple(
        _require_sha256(item, field="accepted_input_sha256s")
        for item in cast("list[object]", value)
    )
    if not values or values != tuple(sorted(set(values))):
        raise ReviewEvidenceError("accepted_input_sha256s must be nonempty, sorted, and unique")
    return values


def _decode_canonical_bytes(raw: bytes) -> Mapping[str, object]:
    if not isinstance(raw, bytes) or not raw:
        raise ReviewEvidenceError("review receipt bytes must be nonempty")

    def _pairs(pairs: list[tuple[str, object]]) -> dict[str, object]:
        result: dict[str, object] = {}
        for key, value in pairs:
            if key in result:
                raise ReviewEvidenceError(f"duplicate JSON key: {key}")
            result[key] = value
        return result

    def _constant(value: str) -> object:
        raise ReviewEvidenceError(f"non-finite JSON constant: {value}")

    try:
        value = json.loads(raw, object_pairs_hook=_pairs, parse_constant=_constant)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ReviewEvidenceError("review receipt bytes are invalid JSON") from exc
    payload = _require_mapping(value, label="review receipt")
    if _canonical_bytes(payload) != raw:
        raise ReviewEvidenceError("review receipt bytes are not canonical")
    return payload


@dataclass(frozen=True, slots=True, order=True)
class ReviewFindingV1:
    """One exact finding and its current authored-review disposition."""

    finding_id: str
    severity: FindingSeverity
    status: FindingStatus
    evidence_sha256: str

    def __post_init__(self) -> None:
        _require_id(self.finding_id, field="finding_id")
        if self.severity not in _FINDING_SEVERITIES:
            raise ReviewEvidenceError("finding severity is invalid")
        if self.status not in _FINDING_STATUSES:
            raise ReviewEvidenceError("finding status is invalid")
        _require_sha256(self.evidence_sha256, field="finding evidence_sha256")

    def to_dict(self) -> dict[str, object]:
        return {
            "finding_id": self.finding_id,
            "severity": self.severity,
            "status": self.status,
            "evidence_sha256": self.evidence_sha256,
        }

    @classmethod
    def from_dict(cls, value: object) -> Self:
        payload = _require_mapping(value, label="review finding")
        _require_exact_keys(
            payload,
            frozenset({"finding_id", "severity", "status", "evidence_sha256"}),
            label="review finding",
        )
        return cls(
            finding_id=cast("str", payload["finding_id"]),
            severity=cast("FindingSeverity", payload["severity"]),
            status=cast("FindingStatus", payload["status"]),
            evidence_sha256=cast("str", payload["evidence_sha256"]),
        )


@dataclass(frozen=True, slots=True, order=True)
class ReviewValidationReceiptV1:
    """One positive, negative, or mutation validation receipt."""

    receipt_id: str
    validation_class: ValidationClass
    command_sha256: str
    evidence_sha256: str
    passed: bool

    def __post_init__(self) -> None:
        _require_id(self.receipt_id, field="validation receipt_id")
        if self.validation_class not in _VALIDATION_CLASSES:
            raise ReviewEvidenceError("validation_class is invalid")
        _require_sha256(self.command_sha256, field="validation command_sha256")
        _require_sha256(self.evidence_sha256, field="validation evidence_sha256")
        if type(self.passed) is not bool:
            raise ReviewEvidenceError("validation passed must be an exact boolean")

    def to_dict(self) -> dict[str, object]:
        return {
            "receipt_id": self.receipt_id,
            "validation_class": self.validation_class,
            "command_sha256": self.command_sha256,
            "evidence_sha256": self.evidence_sha256,
            "passed": self.passed,
        }

    @classmethod
    def from_dict(cls, value: object) -> Self:
        payload = _require_mapping(value, label="review validation receipt")
        _require_exact_keys(
            payload,
            frozenset(
                {
                    "receipt_id",
                    "validation_class",
                    "command_sha256",
                    "evidence_sha256",
                    "passed",
                }
            ),
            label="review validation receipt",
        )
        return cls(
            receipt_id=cast("str", payload["receipt_id"]),
            validation_class=cast("ValidationClass", payload["validation_class"]),
            command_sha256=cast("str", payload["command_sha256"]),
            evidence_sha256=cast("str", payload["evidence_sha256"]),
            passed=cast("bool", payload["passed"]),
        )


@dataclass(frozen=True, slots=True)
class ReviewReceiptV1:
    """Canonical acceptance or changes-required receipt for one semantic subject."""

    subject_kind: str
    subject_semantic_sha256: str
    author_task_id: str
    author_role: str
    reviewer_task_id: str
    reviewer_role: str
    independence_evidence_kind: IndependenceEvidenceKind
    independence_evidence_sha256: str
    accepted_input_sha256s: tuple[str, ...]
    disposition: ReviewDisposition
    findings: tuple[ReviewFindingV1, ...]
    validation_receipts: tuple[ReviewValidationReceiptV1, ...]

    schema_version: ClassVar[int] = MODEL_REVIEW_RECEIPT_SCHEMA_VERSION
    kind: ClassVar[str] = MODEL_REVIEW_RECEIPT_KIND

    def __post_init__(self) -> None:
        _require_id(self.subject_kind, field="subject_kind")
        _require_sha256(self.subject_semantic_sha256, field="subject_semantic_sha256")
        _require_id(self.author_task_id, field="author_task_id")
        _require_id(self.author_role, field="author_role")
        _require_id(self.reviewer_task_id, field="reviewer_task_id")
        _require_id(self.reviewer_role, field="reviewer_role")
        if self.author_task_id == self.reviewer_task_id:
            raise ReviewEvidenceError("author and reviewer task identities must differ")
        if self.author_role == self.reviewer_role:
            raise ReviewEvidenceError("author and reviewer roles must differ")
        if self.independence_evidence_kind not in _INDEPENDENCE_EVIDENCE_KINDS:
            raise ReviewEvidenceError("independence_evidence_kind is invalid")
        _require_sha256(
            self.independence_evidence_sha256,
            field="independence_evidence_sha256",
        )
        if self.disposition not in _REVIEW_DISPOSITIONS:
            raise ReviewEvidenceError("review disposition is invalid")
        if not self.accepted_input_sha256s or self.accepted_input_sha256s != tuple(
            sorted(set(self.accepted_input_sha256s))
        ):
            raise ReviewEvidenceError("accepted_input_sha256s must be nonempty, sorted, and unique")
        for digest in self.accepted_input_sha256s:
            _require_sha256(digest, field="accepted_input_sha256s")
        if self.subject_semantic_sha256 not in self.accepted_input_sha256s:
            raise ReviewEvidenceError(
                "accepted_input_sha256s must include the exact subject semantic digest"
            )
        if type(self.findings) is not tuple or any(
            type(item) is not ReviewFindingV1 for item in self.findings
        ):
            raise ReviewEvidenceError("findings must be an exact typed tuple")
        if self.findings != tuple(sorted(self.findings)) or len(
            {item.finding_id for item in self.findings}
        ) != len(self.findings):
            raise ReviewEvidenceError("findings must be sorted with unique identities")
        if type(self.validation_receipts) is not tuple or any(
            type(item) is not ReviewValidationReceiptV1 for item in self.validation_receipts
        ):
            raise ReviewEvidenceError("validation_receipts must be an exact typed tuple")
        if self.validation_receipts != tuple(sorted(self.validation_receipts)) or len(
            {item.receipt_id for item in self.validation_receipts}
        ) != len(self.validation_receipts):
            raise ReviewEvidenceError("validation_receipts must be sorted with unique identities")
        classes = {item.validation_class for item in self.validation_receipts}
        if classes != _VALIDATION_CLASSES:
            raise ReviewEvidenceError(
                "review evidence requires positive, negative, and mutation receipts"
            )
        has_open_finding = any(item.status == "open" for item in self.findings)
        has_failed_validation = any(not item.passed for item in self.validation_receipts)
        if self.disposition == "accepted" and (has_open_finding or has_failed_validation):
            raise ReviewEvidenceError(
                "an accepted review cannot contain open findings or failed validation"
            )
        if self.disposition == "changes_required" and not (
            has_open_finding or has_failed_validation
        ):
            raise ReviewEvidenceError(
                "changes_required review must retain an open finding or failed validation"
            )

    def _content_dict(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "kind": self.kind,
            "subject_kind": self.subject_kind,
            "subject_semantic_sha256": self.subject_semantic_sha256,
            "author_task_id": self.author_task_id,
            "author_role": self.author_role,
            "reviewer_task_id": self.reviewer_task_id,
            "reviewer_role": self.reviewer_role,
            "independence_evidence_kind": self.independence_evidence_kind,
            "independence_evidence_sha256": self.independence_evidence_sha256,
            "accepted_input_sha256s": list(self.accepted_input_sha256s),
            "disposition": self.disposition,
            "findings": [item.to_dict() for item in self.findings],
            "validation_receipts": [item.to_dict() for item in self.validation_receipts],
        }

    @property
    def receipt_sha256(self) -> str:
        return _sha256(self._content_dict())

    @property
    def canonical_bytes(self) -> bytes:
        return _canonical_bytes(self.to_dict())

    def to_dict(self) -> dict[str, object]:
        return {**self._content_dict(), "receipt_sha256": self.receipt_sha256}

    @classmethod
    def from_dict(cls, value: object) -> Self:
        payload = _require_mapping(value, label="review receipt")
        _require_exact_keys(
            payload,
            frozenset(
                {
                    "schema_version",
                    "kind",
                    "subject_kind",
                    "subject_semantic_sha256",
                    "author_task_id",
                    "author_role",
                    "reviewer_task_id",
                    "reviewer_role",
                    "independence_evidence_kind",
                    "independence_evidence_sha256",
                    "accepted_input_sha256s",
                    "disposition",
                    "findings",
                    "validation_receipts",
                    "receipt_sha256",
                }
            ),
            label="review receipt",
        )
        if payload["schema_version"] != cls.schema_version or payload["kind"] != cls.kind:
            raise ReviewEvidenceError("review receipt schema identity is invalid")
        findings = payload["findings"]
        validations = payload["validation_receipts"]
        if type(findings) is not list or type(validations) is not list:
            raise ReviewEvidenceError("review finding and validation inventories must be arrays")
        receipt = cls(
            subject_kind=cast("str", payload["subject_kind"]),
            subject_semantic_sha256=cast("str", payload["subject_semantic_sha256"]),
            author_task_id=cast("str", payload["author_task_id"]),
            author_role=cast("str", payload["author_role"]),
            reviewer_task_id=cast("str", payload["reviewer_task_id"]),
            reviewer_role=cast("str", payload["reviewer_role"]),
            independence_evidence_kind=cast(
                "IndependenceEvidenceKind",
                payload["independence_evidence_kind"],
            ),
            independence_evidence_sha256=cast(
                "str",
                payload["independence_evidence_sha256"],
            ),
            accepted_input_sha256s=_require_sorted_unique_sha256s(
                payload["accepted_input_sha256s"]
            ),
            disposition=cast("ReviewDisposition", payload["disposition"]),
            findings=tuple(ReviewFindingV1.from_dict(item) for item in findings),
            validation_receipts=tuple(
                ReviewValidationReceiptV1.from_dict(item) for item in validations
            ),
        )
        if payload["receipt_sha256"] != receipt.receipt_sha256:
            raise ReviewEvidenceError("review receipt digest is invalid")
        return receipt

    @classmethod
    def from_canonical_bytes(cls, raw: bytes) -> Self:
        return cls.from_dict(_decode_canonical_bytes(raw))
