"""Immutable admission receipts for observed contract-assurance artifacts.

The receipt pair in this module is intentionally small.  It records only the
content identities needed to admit one observed assurance generation and the
immutable artifact identity that carried it.  Paths, diagnostic text, and
other machine-local context are not part of either schema.
"""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, ClassVar, Literal, Self, cast

__all__ = [
    "ASSURANCE_ADMISSION_KIND",
    "ASSURANCE_ADMISSION_SCHEMA_VERSION",
    "ASSURANCE_ARTIFACT_RECEIPT_KIND",
    "AssuranceAdmission",
    "AssuranceAdmissionError",
    "AssuranceArtifactReceipt",
    "AuthorityUpdateMode",
    "ModelStatus",
    "require_production_admissible",
]

ASSURANCE_ADMISSION_SCHEMA_VERSION = 2
ASSURANCE_ADMISSION_KIND = "nbadb_assurance_admission"
ASSURANCE_ARTIFACT_RECEIPT_KIND = "nbadb_assurance_artifact_receipt"

ModelStatus = Literal["GREEN", "RED"]
AuthorityUpdateMode = Literal[
    "full",
    "since_last_observed",
    "recent_window",
    "targeted_backfill",
]

_LOWER_SHA256 = re.compile(r"[0-9a-f]{64}\Z")
_LOWER_GIT_SHA = re.compile(r"[0-9a-f]{40}\Z")
_SAFE_ARTIFACT_NAME = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,254}\Z")


class AssuranceAdmissionError(ValueError):
    """An assurance admission or its immutable artifact receipt is invalid."""


def _require_exact_keys(
    payload: Mapping[str, object],
    *,
    expected: frozenset[str],
    label: str,
) -> None:
    if any(not isinstance(key, str) for key in payload):
        raise AssuranceAdmissionError(f"{label} fields must be strings")
    actual = frozenset(payload)
    if actual == expected:
        return
    missing = sorted(expected - actual)
    unexpected = sorted(actual - expected)
    details: list[str] = []
    if missing:
        details.append("missing=" + ",".join(missing))
    if unexpected:
        details.append("unexpected=" + ",".join(unexpected))
    raise AssuranceAdmissionError(f"{label} fields are invalid: {'; '.join(details)}")


def _require_mapping(value: object, *, field_name: str) -> Mapping[str, object]:
    if not isinstance(value, Mapping):
        raise AssuranceAdmissionError(f"{field_name} must be an object")
    if any(not isinstance(key, str) for key in value):
        raise AssuranceAdmissionError(f"{field_name} fields must be strings")
    return cast("Mapping[str, object]", value)


def _require_schema_header(
    payload: Mapping[str, object],
    *,
    expected_kind: str,
    label: str,
) -> None:
    if (
        type(payload["schema_version"]) is not int
        or payload["schema_version"] != ASSURANCE_ADMISSION_SCHEMA_VERSION
    ):
        raise AssuranceAdmissionError(f"{label} has an unsupported schema version")
    if payload["kind"] != expected_kind:
        raise AssuranceAdmissionError(f"{label} has an unsupported kind")


def _require_sha256(value: object, *, field_name: str, prefixed: bool = False) -> str:
    if not isinstance(value, str):
        raise AssuranceAdmissionError(f"{field_name} must be a lowercase SHA-256")
    candidate = value
    if prefixed:
        if not candidate.startswith("sha256:"):
            raise AssuranceAdmissionError(
                f"{field_name} must use the lowercase sha256: digest form"
            )
        candidate = candidate.removeprefix("sha256:")
    if _LOWER_SHA256.fullmatch(candidate) is None:
        raise AssuranceAdmissionError(f"{field_name} must be a lowercase SHA-256")
    return value


def _require_git_sha(value: object, *, field_name: str) -> str:
    if not isinstance(value, str) or _LOWER_GIT_SHA.fullmatch(value) is None:
        raise AssuranceAdmissionError(f"{field_name} must be a 40-character lowercase commit SHA")
    return value


def _require_positive_int(value: object, *, field_name: str) -> int:
    if type(value) is not int or value < 1:
        raise AssuranceAdmissionError(f"{field_name} must be a positive integer")
    return value


def _require_artifact_name(value: object) -> str:
    if not isinstance(value, str) or _SAFE_ARTIFACT_NAME.fullmatch(value) is None:
        raise AssuranceAdmissionError(
            "artifact_name must be a portable single-segment artifact name"
        )
    return value


def _canonical_json(payload: object) -> str:
    try:
        return json.dumps(
            payload,
            allow_nan=False,
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        )
    except (TypeError, ValueError) as exc:
        raise AssuranceAdmissionError(
            f"assurance receipt is not canonical JSON: {type(exc).__name__}"
        ) from exc


@dataclass(frozen=True, slots=True)
class AssuranceAdmission:
    """Observed identities required to admit one assurance generation."""

    source_sha: str
    assurance_manifest_sha256: str
    generation_semantic_sha256: str
    provider_evidence_sha256: str
    provider_authority_sha256: str
    authority_semantic_diff_sha256: str
    authority_update_mode: AuthorityUpdateMode
    first_extraction: bool
    model_status: ModelStatus

    schema_version: ClassVar[int] = ASSURANCE_ADMISSION_SCHEMA_VERSION
    kind: ClassVar[str] = ASSURANCE_ADMISSION_KIND

    def __post_init__(self) -> None:
        _require_git_sha(self.source_sha, field_name="source_sha")
        _require_sha256(
            self.assurance_manifest_sha256,
            field_name="assurance_manifest_sha256",
        )
        _require_sha256(
            self.generation_semantic_sha256,
            field_name="generation_semantic_sha256",
        )
        _require_sha256(
            self.provider_evidence_sha256,
            field_name="provider_evidence_sha256",
        )
        _require_sha256(
            self.provider_authority_sha256,
            field_name="provider_authority_sha256",
        )
        _require_sha256(
            self.authority_semantic_diff_sha256,
            field_name="authority_semantic_diff_sha256",
        )
        if self.authority_update_mode not in {
            "full",
            "since_last_observed",
            "recent_window",
            "targeted_backfill",
        }:
            raise AssuranceAdmissionError("authority_update_mode is invalid")
        if type(self.first_extraction) is not bool:
            raise AssuranceAdmissionError("first_extraction must be an exact boolean")
        if self.first_extraction and self.authority_update_mode != "full":
            raise AssuranceAdmissionError("a first extraction requires authority_update_mode full")
        if self.model_status not in {"GREEN", "RED"}:
            raise AssuranceAdmissionError("model_status must be GREEN or RED")

    @property
    def canonical_json(self) -> str:
        """Return the exact canonical JSON used for the receipt digest."""

        return _canonical_json(self.to_dict())

    @property
    def sha256(self) -> str:
        """Return the unprefixed digest of the canonical receipt."""

        return hashlib.sha256(self.canonical_json.encode("utf-8")).hexdigest()

    @property
    def digest(self) -> str:
        """Alias for the canonical unprefixed receipt digest."""

        return self.sha256

    @property
    def is_production_admissible(self) -> bool:
        """Whether the observed generation is eligible for production use.

        Identities are already validated in ``__post_init__``.  ``model_status``
        stays advisory metadata: pragmatic DATA-GREEN assurance owns the
        production gate, so a ``RED`` model ledger does not block admission.
        """

        return True

    def require_production_admissible(self) -> Self:
        """Return this admission; identity validation already fail-closed."""

        return self

    def to_dict(self) -> dict[str, str | int]:
        return {
            "schema_version": self.schema_version,
            "kind": self.kind,
            "source_sha": self.source_sha,
            "assurance_manifest_sha256": self.assurance_manifest_sha256,
            "generation_semantic_sha256": self.generation_semantic_sha256,
            "provider_evidence_sha256": self.provider_evidence_sha256,
            "provider_authority_sha256": self.provider_authority_sha256,
            "authority_semantic_diff_sha256": self.authority_semantic_diff_sha256,
            "authority_update_mode": self.authority_update_mode,
            "first_extraction": self.first_extraction,
            "model_status": self.model_status,
        }

    @classmethod
    def from_dict(cls, payload: Mapping[str, object]) -> Self:
        expected = frozenset(
            {
                "schema_version",
                "kind",
                "source_sha",
                "assurance_manifest_sha256",
                "generation_semantic_sha256",
                "provider_evidence_sha256",
                "provider_authority_sha256",
                "authority_semantic_diff_sha256",
                "authority_update_mode",
                "first_extraction",
                "model_status",
            }
        )
        _require_exact_keys(payload, expected=expected, label="assurance admission")
        _require_schema_header(
            payload,
            expected_kind=cls.kind,
            label="assurance admission",
        )
        model_status = payload["model_status"]
        if model_status not in {"GREEN", "RED"}:
            raise AssuranceAdmissionError("model_status must be GREEN or RED")
        authority_update_mode = payload["authority_update_mode"]
        if authority_update_mode not in {
            "full",
            "since_last_observed",
            "recent_window",
            "targeted_backfill",
        }:
            raise AssuranceAdmissionError("authority_update_mode is invalid")
        first_extraction = payload["first_extraction"]
        if type(first_extraction) is not bool:
            raise AssuranceAdmissionError("first_extraction must be an exact boolean")
        return cls(
            source_sha=_require_git_sha(payload["source_sha"], field_name="source_sha"),
            assurance_manifest_sha256=_require_sha256(
                payload["assurance_manifest_sha256"],
                field_name="assurance_manifest_sha256",
            ),
            generation_semantic_sha256=_require_sha256(
                payload["generation_semantic_sha256"],
                field_name="generation_semantic_sha256",
            ),
            provider_evidence_sha256=_require_sha256(
                payload["provider_evidence_sha256"],
                field_name="provider_evidence_sha256",
            ),
            provider_authority_sha256=_require_sha256(
                payload["provider_authority_sha256"],
                field_name="provider_authority_sha256",
            ),
            authority_semantic_diff_sha256=_require_sha256(
                payload["authority_semantic_diff_sha256"],
                field_name="authority_semantic_diff_sha256",
            ),
            authority_update_mode=cast("AuthorityUpdateMode", authority_update_mode),
            first_extraction=first_extraction,
            model_status=cast("ModelStatus", model_status),
        )


@dataclass(frozen=True, slots=True)
class AssuranceArtifactReceipt:
    """Immutable GitHub artifact identity bound to one assurance admission."""

    artifact_id: int
    artifact_name: str
    artifact_digest: str
    artifact_size_bytes: int
    artifact_run_id: int
    artifact_run_attempt: int
    owner_head_sha: str
    assurance_admission: AssuranceAdmission
    assurance_admission_sha256: str

    schema_version: ClassVar[int] = ASSURANCE_ADMISSION_SCHEMA_VERSION
    kind: ClassVar[str] = ASSURANCE_ARTIFACT_RECEIPT_KIND

    def __post_init__(self) -> None:
        _require_positive_int(self.artifact_id, field_name="artifact_id")
        _require_artifact_name(self.artifact_name)
        _require_sha256(
            self.artifact_digest,
            field_name="artifact_digest",
            prefixed=True,
        )
        _require_positive_int(self.artifact_size_bytes, field_name="artifact_size_bytes")
        _require_positive_int(self.artifact_run_id, field_name="artifact_run_id")
        _require_positive_int(
            self.artifact_run_attempt,
            field_name="artifact_run_attempt",
        )
        _require_git_sha(self.owner_head_sha, field_name="owner_head_sha")
        if not isinstance(self.assurance_admission, AssuranceAdmission):
            raise AssuranceAdmissionError("assurance_admission must be an AssuranceAdmission")
        _require_sha256(
            self.assurance_admission_sha256,
            field_name="assurance_admission_sha256",
        )
        if self.assurance_admission_sha256 != self.assurance_admission.sha256:
            raise AssuranceAdmissionError(
                "assurance admission digest does not match the embedded admission"
            )
        if self.owner_head_sha != self.assurance_admission.source_sha:
            raise AssuranceAdmissionError(
                "artifact owner head does not match assurance admission source"
            )

    @classmethod
    def bind(
        cls,
        *,
        artifact_id: int,
        artifact_name: str,
        artifact_digest: str,
        artifact_size_bytes: int,
        artifact_run_id: int,
        artifact_run_attempt: int,
        owner_head_sha: str,
        assurance_admission: AssuranceAdmission,
    ) -> Self:
        """Build a receipt with the canonical inner digest filled in exactly."""

        return cls(
            artifact_id=artifact_id,
            artifact_name=artifact_name,
            artifact_digest=artifact_digest,
            artifact_size_bytes=artifact_size_bytes,
            artifact_run_id=artifact_run_id,
            artifact_run_attempt=artifact_run_attempt,
            owner_head_sha=owner_head_sha,
            assurance_admission=assurance_admission,
            assurance_admission_sha256=assurance_admission.sha256,
        )

    @property
    def canonical_json(self) -> str:
        """Return the exact canonical JSON used for the receipt digest."""

        return _canonical_json(self.to_dict())

    @property
    def sha256(self) -> str:
        """Return the unprefixed digest of the canonical artifact receipt."""

        return hashlib.sha256(self.canonical_json.encode("utf-8")).hexdigest()

    @property
    def digest(self) -> str:
        """Alias for the canonical unprefixed receipt digest."""

        return self.sha256

    @property
    def is_production_admissible(self) -> bool:
        return self.assurance_admission.is_production_admissible

    def require_production_admissible(self) -> Self:
        """Return this receipt; the bound inner admission validates on load."""

        self.assurance_admission.require_production_admissible()
        return self

    def validate_binding(self, admission: AssuranceAdmission) -> None:
        """Prove this receipt is bound to the supplied admission exactly."""

        if not isinstance(admission, AssuranceAdmission):
            raise AssuranceAdmissionError("binding target must be an AssuranceAdmission")
        if admission != self.assurance_admission or admission.sha256 != (
            self.assurance_admission_sha256
        ):
            raise AssuranceAdmissionError(
                "artifact receipt does not match the supplied assurance admission"
            )

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "kind": self.kind,
            "artifact_id": self.artifact_id,
            "artifact_name": self.artifact_name,
            "artifact_digest": self.artifact_digest,
            "artifact_size_bytes": self.artifact_size_bytes,
            "artifact_run_id": self.artifact_run_id,
            "artifact_run_attempt": self.artifact_run_attempt,
            "owner_head_sha": self.owner_head_sha,
            "assurance_admission": self.assurance_admission.to_dict(),
            "assurance_admission_sha256": self.assurance_admission_sha256,
        }

    @classmethod
    def from_dict(cls, payload: Mapping[str, object]) -> Self:
        expected = frozenset(
            {
                "schema_version",
                "kind",
                "artifact_id",
                "artifact_name",
                "artifact_digest",
                "artifact_size_bytes",
                "artifact_run_id",
                "artifact_run_attempt",
                "owner_head_sha",
                "assurance_admission",
                "assurance_admission_sha256",
            }
        )
        _require_exact_keys(
            payload,
            expected=expected,
            label="assurance artifact receipt",
        )
        _require_schema_header(
            payload,
            expected_kind=cls.kind,
            label="assurance artifact receipt",
        )
        admission = AssuranceAdmission.from_dict(
            _require_mapping(
                payload["assurance_admission"],
                field_name="assurance_admission",
            )
        )
        return cls(
            artifact_id=_require_positive_int(
                payload["artifact_id"],
                field_name="artifact_id",
            ),
            artifact_name=_require_artifact_name(payload["artifact_name"]),
            artifact_digest=_require_sha256(
                payload["artifact_digest"],
                field_name="artifact_digest",
                prefixed=True,
            ),
            artifact_size_bytes=_require_positive_int(
                payload["artifact_size_bytes"],
                field_name="artifact_size_bytes",
            ),
            artifact_run_id=_require_positive_int(
                payload["artifact_run_id"],
                field_name="artifact_run_id",
            ),
            artifact_run_attempt=_require_positive_int(
                payload["artifact_run_attempt"],
                field_name="artifact_run_attempt",
            ),
            owner_head_sha=_require_git_sha(
                payload["owner_head_sha"],
                field_name="owner_head_sha",
            ),
            assurance_admission=admission,
            assurance_admission_sha256=_require_sha256(
                payload["assurance_admission_sha256"],
                field_name="assurance_admission_sha256",
            ),
        )


def require_production_admissible[
    T: (AssuranceAdmission, AssuranceArtifactReceipt),
](receipt: T) -> T:
    """Require a production-admissible inner or outer assurance receipt."""

    if not isinstance(receipt, (AssuranceAdmission, AssuranceArtifactReceipt)):
        raise AssuranceAdmissionError("production assurance receipt has an unsupported type")
    return receipt.require_production_admissible()
