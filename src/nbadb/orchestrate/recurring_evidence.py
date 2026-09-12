"""Canonical evidence contracts for recurring publication closeout.

The value objects in this module are deliberately side-effect free.  They validate
already-produced evidence; they do not download data, inspect files, authenticate a
human, publish to Kaggle, or manufacture a DATA-GREEN decision.
"""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import date, datetime
from enum import StrEnum
from pathlib import PurePosixPath
from typing import Any, ClassVar, Self, cast
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

__all__ = [
    "REQUIRED_DOCS_PARITY_SURFACES",
    "REQUIRED_HUMAN_COVERAGE_CATEGORIES",
    "REQUIRED_MANUAL_FORMATS",
    "DataGreenReceiptV1",
    "DocsMetadataParityV1",
    "ExactParentSuccessorV1",
    "FreshnessDecision",
    "FullBaselineProvenanceV1",
    "HumanFormatObservationV1",
    "HumanQueryObservationV1",
    "HumanVerificationReceiptV1",
    "ImmutableVersionReadbackV1",
    "ReadbackResourceV1",
    "RecurringEvidenceError",
    "RecurringRunPhase",
    "RecurringRunStatusReason",
    "RecurringRunStatusV1",
]

_MAX_CANONICAL_BYTES = 64 * 1024 * 1024
_MAX_INVENTORY_ITEMS = 100_000
_MAX_SAMPLES = 10_000
_MAX_SIGNED_63 = (1 << 63) - 1
_SHA256_RE = re.compile(r"[0-9a-f]{64}")
_SOURCE_SHA_RE = re.compile(r"[0-9a-f]{40}")
_DATASET_REF_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,63}/[A-Za-z0-9][A-Za-z0-9_.-]{0,127}")
_SAFE_TOKEN_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.:@+-]{0,255}")
_SAFE_PATH_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9._/-]{0,1023}")
_NON_HUMAN_SUBJECT_PARTS = (
    "agent",
    "automation",
    "bot",
    "codex",
    "default",
    "gpt",
    "headless",
    "workflow",
)

REQUIRED_MANUAL_FORMATS = ("duckdb", "sqlite", "parquet", "csv")
REQUIRED_HUMAN_COVERAGE_CATEGORIES = tuple(
    sorted(
        {
            "aggregates",
            "analytics",
            "box_scores",
            "draft",
            "earliest_era",
            "field_gap_boundaries",
            "field_introduction_boundaries",
            "games",
            "live_snapshots",
            "parquet_csv_decoding",
            "play_by_play",
            "players",
            "raw_lossless",
            "recent_era",
            "rosters",
            "shots",
            "standings",
            "teams",
            "unavailable_edges",
            "updated_window",
            "zero_row_edges",
        }
    )
)
REQUIRED_DOCS_PARITY_SURFACES = tuple(
    sorted(
        {
            "authored_cadence",
            "authored_limitations",
            "authored_model_scope",
            "authored_provenance",
            "authored_temporal_scope",
            "experimental_labels",
            "generated_catalog",
            "generated_lineage",
            "generated_schema",
            "kaggle_metadata",
            "remote_inventory",
        }
    )
)


class RecurringEvidenceError(ValueError):
    """Raised when recurring closeout evidence is incomplete or inconsistent."""


class FreshnessDecision(StrEnum):
    FRESH = "fresh"
    NOT_FRESH = "not_fresh"


class RecurringRunPhase(StrEnum):
    PRE_EXTRACTION = "pre_extraction"
    EXTRACTION = "extraction"
    ASSURANCE = "assurance"
    PUBLICATION = "publication"
    COMPLETE = "complete"


class RecurringRunStatusReason(StrEnum):
    UPDATE_PUBLISHED_AND_READ_BACK = "update_published_and_read_back"
    NO_GAME_CLOSED_AND_VERSIONED = "no_game_closed_and_versioned"
    PARENT_ADMISSION_FAILED = "parent_admission_failed"
    CAPACITY_BLOCKED = "capacity_blocked"
    CHECKOUT_FAILED = "checkout_failed"
    EXTRACTION_INCOMPLETE = "extraction_incomplete"
    ASSURANCE_FAILED = "assurance_failed"
    PUBLICATION_FAILED = "publication_failed"
    READBACK_FAILED = "readback_failed"
    CANCELLED = "cancelled"
    INTERNAL_ERROR = "internal_error"


def _canonical_json_bytes(payload: object) -> bytes:
    try:
        encoded = json.dumps(
            payload,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=True,
            allow_nan=False,
        ).encode("utf-8")
    except (TypeError, ValueError) as exc:
        raise RecurringEvidenceError("receipt contains a noncanonical JSON value") from exc
    if len(encoded) > _MAX_CANONICAL_BYTES:
        raise RecurringEvidenceError("canonical receipt exceeds the byte limit")
    return encoded


def _canonical_sha256(payload: object) -> str:
    return hashlib.sha256(_canonical_json_bytes(payload)).hexdigest()


def _strict_json_object(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise RecurringEvidenceError(f"canonical receipt contains duplicate key {key!r}")
        result[key] = value
    return result


def _reject_json_constant(value: str) -> None:
    raise RecurringEvidenceError(f"canonical receipt contains invalid JSON constant {value}")


def _decode_canonical_receipt(encoded: object) -> Mapping[str, object]:
    if type(encoded) is not bytes:
        raise RecurringEvidenceError("canonical receipt must be bytes")
    raw = encoded
    if not raw or len(raw) > _MAX_CANONICAL_BYTES:
        raise RecurringEvidenceError("canonical receipt byte length is invalid")
    try:
        decoded = json.loads(
            raw,
            object_pairs_hook=_strict_json_object,
            parse_constant=_reject_json_constant,
        )
    except RecurringEvidenceError:
        raise
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise RecurringEvidenceError("canonical receipt is not valid UTF-8 JSON") from exc
    if not isinstance(decoded, dict) or not all(isinstance(key, str) for key in decoded):
        raise RecurringEvidenceError("canonical receipt root must be an object")
    if _canonical_json_bytes(decoded) + b"\n" != raw:
        raise RecurringEvidenceError("receipt bytes are not the canonical JSON encoding")
    return cast("Mapping[str, object]", decoded)


class _CanonicalReceipt:
    def to_dict(self) -> dict[str, Any]:
        raise NotImplementedError

    @classmethod
    def from_dict(cls, payload: Mapping[str, object]) -> Self:
        raise NotImplementedError

    @property
    def canonical_bytes(self) -> bytes:
        return _canonical_json_bytes(self.to_dict()) + b"\n"

    @property
    def content_sha256(self) -> str:
        return hashlib.sha256(self.canonical_bytes).hexdigest()

    @classmethod
    def from_bytes(cls, encoded: object) -> Self:
        payload = _decode_canonical_receipt(encoded)
        result = cls.from_dict(payload)
        if result.canonical_bytes != encoded:
            raise RecurringEvidenceError("receipt does not reproduce its canonical bytes")
        return result


def _require_exact_keys(
    payload: Mapping[str, object],
    expected: set[str] | frozenset[str],
    *,
    label: str,
) -> None:
    actual = set(payload)
    if actual == set(expected):
        return
    missing = sorted(set(expected) - actual)
    unexpected = sorted(actual - set(expected))
    raise RecurringEvidenceError(
        f"{label} fields are invalid: missing={missing}; unexpected={unexpected}"
    )


def _mapping(value: object, *, label: str) -> Mapping[str, object]:
    if not isinstance(value, Mapping) or not all(isinstance(key, str) for key in value):
        raise RecurringEvidenceError(f"{label} must be an object with string keys")
    return cast("Mapping[str, object]", value)


def _list(value: object, *, label: str) -> Sequence[object]:
    if not isinstance(value, list):
        raise RecurringEvidenceError(f"{label} must be a list")
    return value


def _string(value: object, *, label: str) -> str:
    if not isinstance(value, str) or not value:
        raise RecurringEvidenceError(f"{label} must be a nonempty string")
    try:
        encoded = value.encode("utf-8")
    except UnicodeEncodeError as exc:
        raise RecurringEvidenceError(f"{label} is not valid Unicode text") from exc
    if len(encoded) > 4_096:
        raise RecurringEvidenceError(f"{label} exceeds the byte limit")
    if any(ord(character) < 32 or ord(character) == 127 for character in value):
        raise RecurringEvidenceError(f"{label} contains control characters")
    return value


def _safe_token(value: object, *, label: str) -> str:
    result = _string(value, label=label)
    if _SAFE_TOKEN_RE.fullmatch(result) is None:
        raise RecurringEvidenceError(f"{label} must be an exact safe token")
    return result


def _sha256(value: object, *, label: str) -> str:
    if not isinstance(value, str) or _SHA256_RE.fullmatch(value) is None:
        raise RecurringEvidenceError(f"{label} must be a lowercase SHA-256")
    return value


def _source_sha(value: object, *, label: str = "source_sha") -> str:
    if not isinstance(value, str) or _SOURCE_SHA_RE.fullmatch(value) is None:
        raise RecurringEvidenceError(f"{label} must be a lowercase 40-character commit SHA")
    return value


def _dataset_ref(value: object, *, label: str = "dataset_ref") -> str:
    if not isinstance(value, str) or _DATASET_REF_RE.fullmatch(value) is None:
        raise RecurringEvidenceError(f"{label} must be an exact owner/dataset reference")
    return value


def _positive_int(value: object, *, label: str) -> int:
    if type(value) is not int or value < 1 or value > _MAX_SIGNED_63:
        raise RecurringEvidenceError(
            f"{label} must be a positive integer within signed-63-bit range"
        )
    return value


def _nonnegative_int(value: object, *, label: str) -> int:
    if type(value) is not int or value < 0 or value > _MAX_SIGNED_63:
        raise RecurringEvidenceError(
            f"{label} must be a nonnegative integer within signed-63-bit range"
        )
    return value


def _bool(value: object, *, label: str) -> bool:
    if type(value) is not bool:
        raise RecurringEvidenceError(f"{label} must be a boolean")
    return value


def _utc_instant(value: object, *, label: str) -> str:
    result = _string(value, label=label)
    try:
        parsed = datetime.strptime(result, "%Y-%m-%dT%H:%M:%SZ")
    except ValueError as exc:
        raise RecurringEvidenceError(
            f"{label} must use canonical UTC form YYYY-MM-DDTHH:MM:SSZ"
        ) from exc
    if parsed.strftime("%Y-%m-%dT%H:%M:%SZ") != result:
        raise RecurringEvidenceError(f"{label} must use canonical UTC form YYYY-MM-DDTHH:MM:SSZ")
    return result


def _calendar_date(value: object, *, label: str) -> str:
    result = _string(value, label=label)
    try:
        parsed = date.fromisoformat(result)
    except ValueError as exc:
        raise RecurringEvidenceError(f"{label} must use canonical YYYY-MM-DD form") from exc
    if parsed.isoformat() != result:
        raise RecurringEvidenceError(f"{label} must use canonical YYYY-MM-DD form")
    return result


def _timezone(value: object, *, label: str) -> str:
    result = _string(value, label=label)
    if result.startswith(("/", ".")) or ".." in result or "\\" in result:
        raise RecurringEvidenceError(f"{label} is not a canonical IANA timezone")
    try:
        zone = ZoneInfo(result)
    except ZoneInfoNotFoundError as exc:
        raise RecurringEvidenceError(f"{label} is not a known IANA timezone") from exc
    if zone.key != result:
        raise RecurringEvidenceError(f"{label} is not a canonical IANA timezone")
    return result


def _optional_sha256(value: object, *, label: str) -> str | None:
    return None if value is None else _sha256(value, label=label)


def _optional_positive_int(value: object, *, label: str) -> int | None:
    return None if value is None else _positive_int(value, label=label)


def _optional_utc(value: object, *, label: str) -> str | None:
    return None if value is None else _utc_instant(value, label=label)


def _safe_relative_path(value: object, *, label: str) -> str:
    result = _string(value, label=label)
    if _SAFE_PATH_RE.fullmatch(result) is None or "\\" in result or result.startswith("/"):
        raise RecurringEvidenceError(f"{label} must be a canonical relative POSIX path")
    path = PurePosixPath(result)
    if (
        path.is_absolute()
        or path.as_posix() != result
        or any(part in {"", ".", ".."} for part in path.parts)
        or any(part.endswith(":") for part in path.parts)
    ):
        raise RecurringEvidenceError(f"{label} must be a canonical relative POSIX path")
    return result


def _sorted_unique_strings(
    values: object,
    *,
    label: str,
    expected: tuple[str, ...] | None = None,
) -> tuple[str, ...]:
    sequence = tuple(_list(values, label=label)) if isinstance(values, list) else values
    if type(sequence) is not tuple:
        raise RecurringEvidenceError(f"{label} must be an immutable tuple")
    result = tuple(_safe_token(value, label=label) for value in sequence)
    if not result:
        raise RecurringEvidenceError(f"{label} must be nonempty")
    if len(result) != len(set(result)) or result != tuple(sorted(result)):
        raise RecurringEvidenceError(f"{label} must be sorted and duplicate-free")
    if expected is not None and result != expected:
        raise RecurringEvidenceError(f"{label} does not cover the required inventory")
    return result


@dataclass(frozen=True, slots=True)
class RecurringRunStatusV1(_CanonicalReceipt):
    """Always-finalizable freshness state for one recurring execution."""

    source_sha: str
    actions_run_id: int
    actions_run_attempt: int
    expected_prior_nba_date: str
    timezone: str
    provider_availability_cutoff: str
    scheduled_deadline: str
    actual_completion: str
    phase: RecurringRunPhase
    freshness: FreshnessDecision
    reason: RecurringRunStatusReason
    dataset_ref: str
    parent_dataset_version: int | None
    parent_cutoff: str | None
    parent_fingerprint_sha256: str | None
    latest_assured_remote_version: int | None
    latest_assured_remote_cutoff: str | None
    update_transaction_id: str | None
    coordinator_identity_sha256: str | None
    candidate_identity_sha256: str | None
    request_closure_sha256: str | None
    publication_readback_sha256: str | None
    provider_mutation_count: int
    kaggle_mutation_count: int
    no_mutation_proven: bool
    no_mutation_proof_sha256: str | None
    finalizer_always_ran: bool = True
    schema_version: ClassVar[int] = 1
    kind: ClassVar[str] = "recurring_run_status"

    def __post_init__(self) -> None:
        _source_sha(self.source_sha)
        _positive_int(self.actions_run_id, label="actions_run_id")
        _positive_int(self.actions_run_attempt, label="actions_run_attempt")
        expected_date = _calendar_date(
            self.expected_prior_nba_date,
            label="expected_prior_nba_date",
        )
        _timezone(self.timezone, label="timezone")
        _utc_instant(self.provider_availability_cutoff, label="provider_availability_cutoff")
        _utc_instant(self.scheduled_deadline, label="scheduled_deadline")
        _utc_instant(self.actual_completion, label="actual_completion")
        if not isinstance(self.phase, RecurringRunPhase):
            raise RecurringEvidenceError("phase must be a RecurringRunPhase")
        if not isinstance(self.freshness, FreshnessDecision):
            raise RecurringEvidenceError("freshness must be a FreshnessDecision")
        if not isinstance(self.reason, RecurringRunStatusReason):
            raise RecurringEvidenceError("reason must be a RecurringRunStatusReason")
        _dataset_ref(self.dataset_ref)
        _optional_positive_int(self.parent_dataset_version, label="parent_dataset_version")
        _optional_utc(self.parent_cutoff, label="parent_cutoff")
        _optional_sha256(self.parent_fingerprint_sha256, label="parent_fingerprint_sha256")
        _optional_positive_int(
            self.latest_assured_remote_version,
            label="latest_assured_remote_version",
        )
        latest_cutoff = _optional_utc(
            self.latest_assured_remote_cutoff,
            label="latest_assured_remote_cutoff",
        )
        _optional_sha256(self.update_transaction_id, label="update_transaction_id")
        _optional_sha256(
            self.coordinator_identity_sha256,
            label="coordinator_identity_sha256",
        )
        _optional_sha256(self.candidate_identity_sha256, label="candidate_identity_sha256")
        _optional_sha256(self.request_closure_sha256, label="request_closure_sha256")
        _optional_sha256(
            self.publication_readback_sha256,
            label="publication_readback_sha256",
        )
        provider_mutations = _nonnegative_int(
            self.provider_mutation_count,
            label="provider_mutation_count",
        )
        kaggle_mutations = _nonnegative_int(
            self.kaggle_mutation_count,
            label="kaggle_mutation_count",
        )
        _bool(self.no_mutation_proven, label="no_mutation_proven")
        _optional_sha256(self.no_mutation_proof_sha256, label="no_mutation_proof_sha256")
        if self.finalizer_always_ran is not True:
            raise RecurringEvidenceError("RecurringRunStatusV1 must come from the always finalizer")

        if self.no_mutation_proven:
            if provider_mutations != 0 or kaggle_mutations != 0:
                raise RecurringEvidenceError("no-mutation proof conflicts with mutation counts")
            if self.no_mutation_proof_sha256 is None:
                raise RecurringEvidenceError("no-mutation proof digest is required")
        elif self.no_mutation_proof_sha256 is not None:
            raise RecurringEvidenceError("no-mutation digest requires no_mutation_proven")

        pre_extraction_reasons = {
            RecurringRunStatusReason.PARENT_ADMISSION_FAILED,
            RecurringRunStatusReason.CAPACITY_BLOCKED,
            RecurringRunStatusReason.CHECKOUT_FAILED,
        }
        if self.reason in pre_extraction_reasons:
            if self.phase is not RecurringRunPhase.PRE_EXTRACTION:
                raise RecurringEvidenceError("pre-extraction reason requires pre_extraction phase")
            if not self.no_mutation_proven:
                raise RecurringEvidenceError("pre-extraction failure requires no-mutation proof")
            if self.candidate_identity_sha256 is not None:
                raise RecurringEvidenceError("pre-extraction failure cannot bind a candidate")

        fresh_reasons = {
            RecurringRunStatusReason.UPDATE_PUBLISHED_AND_READ_BACK,
            RecurringRunStatusReason.NO_GAME_CLOSED_AND_VERSIONED,
        }
        if self.freshness is FreshnessDecision.FRESH:
            required = (
                self.parent_dataset_version,
                self.parent_cutoff,
                self.parent_fingerprint_sha256,
                self.latest_assured_remote_version,
                latest_cutoff,
                self.update_transaction_id,
                self.coordinator_identity_sha256,
                self.candidate_identity_sha256,
                self.request_closure_sha256,
                self.publication_readback_sha256,
            )
            if self.phase is not RecurringRunPhase.COMPLETE or self.reason not in fresh_reasons:
                raise RecurringEvidenceError("fresh status requires a terminal closed reason")
            if any(value is None for value in required):
                raise RecurringEvidenceError("fresh status is missing terminal evidence")
            if cast("int", self.latest_assured_remote_version) <= cast(
                "int", self.parent_dataset_version
            ):
                raise RecurringEvidenceError("fresh status must bind a newer remote version")
            if kaggle_mutations != 1:
                raise RecurringEvidenceError("fresh status requires exactly one Kaggle mutation")
            if latest_cutoff is not None and latest_cutoff[:10] < expected_date:
                raise RecurringEvidenceError("fresh remote cutoff does not close the expected day")
            if self.no_mutation_proven:
                raise RecurringEvidenceError("fresh versioned status cannot assert no mutation")
        elif self.reason in fresh_reasons:
            raise RecurringEvidenceError("closed freshness reason conflicts with not_fresh")

        if self.reason is RecurringRunStatusReason.PARENT_ADMISSION_FAILED and any(
            value is not None
            for value in (
                self.parent_dataset_version,
                self.parent_cutoff,
                self.parent_fingerprint_sha256,
                self.update_transaction_id,
                self.candidate_identity_sha256,
                self.publication_readback_sha256,
            )
        ):
            raise RecurringEvidenceError("failed parent admission cannot invent parent state")

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "kind": self.kind,
            "source_sha": self.source_sha,
            "actions_run_id": self.actions_run_id,
            "actions_run_attempt": self.actions_run_attempt,
            "expected_prior_nba_date": self.expected_prior_nba_date,
            "timezone": self.timezone,
            "provider_availability_cutoff": self.provider_availability_cutoff,
            "scheduled_deadline": self.scheduled_deadline,
            "actual_completion": self.actual_completion,
            "phase": self.phase.value,
            "freshness": self.freshness.value,
            "reason": self.reason.value,
            "dataset_ref": self.dataset_ref,
            "parent_dataset_version": self.parent_dataset_version,
            "parent_cutoff": self.parent_cutoff,
            "parent_fingerprint_sha256": self.parent_fingerprint_sha256,
            "latest_assured_remote_version": self.latest_assured_remote_version,
            "latest_assured_remote_cutoff": self.latest_assured_remote_cutoff,
            "update_transaction_id": self.update_transaction_id,
            "coordinator_identity_sha256": self.coordinator_identity_sha256,
            "candidate_identity_sha256": self.candidate_identity_sha256,
            "request_closure_sha256": self.request_closure_sha256,
            "publication_readback_sha256": self.publication_readback_sha256,
            "provider_mutation_count": self.provider_mutation_count,
            "kaggle_mutation_count": self.kaggle_mutation_count,
            "no_mutation_proven": self.no_mutation_proven,
            "no_mutation_proof_sha256": self.no_mutation_proof_sha256,
            "finalizer_always_ran": self.finalizer_always_ran,
        }

    @classmethod
    def from_dict(cls, payload: Mapping[str, object]) -> Self:
        expected = set(cls.__dataclass_fields__) - {"schema_version", "kind"}
        expected.update({"schema_version", "kind"})
        _require_exact_keys(payload, expected, label=cls.kind)
        if (
            type(payload["schema_version"]) is not int
            or payload["schema_version"] != cls.schema_version
            or payload["kind"] != cls.kind
        ):
            raise RecurringEvidenceError("recurring run status schema identity is invalid")
        try:
            phase = RecurringRunPhase(payload["phase"])
            freshness = FreshnessDecision(payload["freshness"])
            reason = RecurringRunStatusReason(payload["reason"])
        except (TypeError, ValueError) as exc:
            raise RecurringEvidenceError("recurring run status enum value is invalid") from exc
        return cls(
            source_sha=_source_sha(payload["source_sha"]),
            actions_run_id=_positive_int(payload["actions_run_id"], label="actions_run_id"),
            actions_run_attempt=_positive_int(
                payload["actions_run_attempt"],
                label="actions_run_attempt",
            ),
            expected_prior_nba_date=_calendar_date(
                payload["expected_prior_nba_date"],
                label="expected_prior_nba_date",
            ),
            timezone=_timezone(payload["timezone"], label="timezone"),
            provider_availability_cutoff=_utc_instant(
                payload["provider_availability_cutoff"],
                label="provider_availability_cutoff",
            ),
            scheduled_deadline=_utc_instant(
                payload["scheduled_deadline"],
                label="scheduled_deadline",
            ),
            actual_completion=_utc_instant(
                payload["actual_completion"],
                label="actual_completion",
            ),
            phase=phase,
            freshness=freshness,
            reason=reason,
            dataset_ref=_dataset_ref(payload["dataset_ref"]),
            parent_dataset_version=_optional_positive_int(
                payload["parent_dataset_version"],
                label="parent_dataset_version",
            ),
            parent_cutoff=_optional_utc(payload["parent_cutoff"], label="parent_cutoff"),
            parent_fingerprint_sha256=_optional_sha256(
                payload["parent_fingerprint_sha256"],
                label="parent_fingerprint_sha256",
            ),
            latest_assured_remote_version=_optional_positive_int(
                payload["latest_assured_remote_version"],
                label="latest_assured_remote_version",
            ),
            latest_assured_remote_cutoff=_optional_utc(
                payload["latest_assured_remote_cutoff"],
                label="latest_assured_remote_cutoff",
            ),
            update_transaction_id=_optional_sha256(
                payload["update_transaction_id"],
                label="update_transaction_id",
            ),
            coordinator_identity_sha256=_optional_sha256(
                payload["coordinator_identity_sha256"],
                label="coordinator_identity_sha256",
            ),
            candidate_identity_sha256=_optional_sha256(
                payload["candidate_identity_sha256"],
                label="candidate_identity_sha256",
            ),
            request_closure_sha256=_optional_sha256(
                payload["request_closure_sha256"],
                label="request_closure_sha256",
            ),
            publication_readback_sha256=_optional_sha256(
                payload["publication_readback_sha256"],
                label="publication_readback_sha256",
            ),
            provider_mutation_count=_nonnegative_int(
                payload["provider_mutation_count"],
                label="provider_mutation_count",
            ),
            kaggle_mutation_count=_nonnegative_int(
                payload["kaggle_mutation_count"],
                label="kaggle_mutation_count",
            ),
            no_mutation_proven=_bool(
                payload["no_mutation_proven"],
                label="no_mutation_proven",
            ),
            no_mutation_proof_sha256=_optional_sha256(
                payload["no_mutation_proof_sha256"],
                label="no_mutation_proof_sha256",
            ),
            finalizer_always_ran=_bool(
                payload["finalizer_always_ran"],
                label="finalizer_always_ran",
            ),
        )


@dataclass(frozen=True, slots=True)
class ReadbackResourceV1:
    """One regular remote resource streamed through complete SHA-256 readback."""

    path: str
    size_bytes: int
    declared_sha256: str
    streamed_sha256: str
    file_type: str = "regular"

    def __post_init__(self) -> None:
        _safe_relative_path(self.path, label="resource path")
        _nonnegative_int(self.size_bytes, label="resource size_bytes")
        declared = _sha256(self.declared_sha256, label="resource declared_sha256")
        streamed = _sha256(self.streamed_sha256, label="resource streamed_sha256")
        if declared != streamed:
            raise RecurringEvidenceError("resource streamed digest differs from declaration")
        if self.file_type != "regular":
            raise RecurringEvidenceError("readback resources must be regular files, never symlinks")

    def to_dict(self) -> dict[str, Any]:
        return {
            "path": self.path,
            "size_bytes": self.size_bytes,
            "declared_sha256": self.declared_sha256,
            "streamed_sha256": self.streamed_sha256,
            "file_type": self.file_type,
        }

    @classmethod
    def from_dict(cls, payload: Mapping[str, object]) -> Self:
        _require_exact_keys(
            payload,
            {"path", "size_bytes", "declared_sha256", "streamed_sha256", "file_type"},
            label="readback resource",
        )
        return cls(
            path=_safe_relative_path(payload["path"], label="resource path"),
            size_bytes=_nonnegative_int(payload["size_bytes"], label="resource size_bytes"),
            declared_sha256=_sha256(
                payload["declared_sha256"],
                label="resource declared_sha256",
            ),
            streamed_sha256=_sha256(
                payload["streamed_sha256"],
                label="resource streamed_sha256",
            ),
            file_type=_string(payload["file_type"], label="resource file_type"),
        )


@dataclass(frozen=True, slots=True)
class ImmutableVersionReadbackV1(_CanonicalReceipt):
    """Complete immutable redownload of one exact successor version."""

    dataset_ref: str
    parent_dataset_version: int
    dataset_version: int
    version_endpoint: str
    source_sha: str
    update_transaction_id: str
    parent_fingerprint_sha256: str
    assured_candidate_sha256: str
    publication_receipt_sha256: str
    remote_publication_readback_sha256: str
    resources: tuple[ReadbackResourceV1, ...]
    resource_inventory_sha256: str
    dataset_root_id: str
    evidence_root_id: str
    immutable_tree_sha256_before: str
    immutable_tree_sha256_after: str
    destination_was_empty: bool = True
    owner_only: bool = True
    exact_version_endpoint_used: bool = True
    inventory_complete: bool = True
    streamed_one_file_at_a_time: bool = True
    dataset_tree_non_writable: bool = True
    sidecars_absent: bool = True
    schema_version: ClassVar[int] = 1
    kind: ClassVar[str] = "immutable_version_readback"

    def __post_init__(self) -> None:
        dataset_ref = _dataset_ref(self.dataset_ref)
        parent_version = _positive_int(
            self.parent_dataset_version,
            label="parent_dataset_version",
        )
        dataset_version = _positive_int(self.dataset_version, label="dataset_version")
        if dataset_version != parent_version + 1:
            raise RecurringEvidenceError(
                "immutable readback is not the exact next parent successor"
            )
        expected_endpoint = f"/{dataset_ref}/versions/{dataset_version}"
        if self.version_endpoint != expected_endpoint:
            raise RecurringEvidenceError(
                "immutable readback must use the exact /versions/N endpoint"
            )
        _source_sha(self.source_sha)
        _sha256(self.update_transaction_id, label="update_transaction_id")
        _sha256(self.parent_fingerprint_sha256, label="parent_fingerprint_sha256")
        _sha256(self.assured_candidate_sha256, label="assured_candidate_sha256")
        _sha256(self.publication_receipt_sha256, label="publication_receipt_sha256")
        _sha256(
            self.remote_publication_readback_sha256,
            label="remote_publication_readback_sha256",
        )
        resources = tuple(self.resources)
        if not resources or len(resources) > _MAX_INVENTORY_ITEMS:
            raise RecurringEvidenceError("readback resource inventory size is invalid")
        if any(not isinstance(item, ReadbackResourceV1) for item in resources):
            raise RecurringEvidenceError("readback resource inventory member is invalid")
        paths = tuple(item.path for item in resources)
        if paths != tuple(sorted(paths)) or len(paths) != len(set(paths)):
            raise RecurringEvidenceError("readback resources must be sorted and path-unique")
        expected_inventory = _canonical_sha256([item.to_dict() for item in resources])
        if (
            _sha256(
                self.resource_inventory_sha256,
                label="resource_inventory_sha256",
            )
            != expected_inventory
        ):
            raise RecurringEvidenceError("readback inventory digest drifted from its resources")
        dataset_root = _safe_token(self.dataset_root_id, label="dataset_root_id")
        evidence_root = _safe_token(self.evidence_root_id, label="evidence_root_id")
        if dataset_root == evidence_root:
            raise RecurringEvidenceError("dataset and evidence roots must be separate")
        before = _sha256(
            self.immutable_tree_sha256_before,
            label="immutable_tree_sha256_before",
        )
        after = _sha256(
            self.immutable_tree_sha256_after,
            label="immutable_tree_sha256_after",
        )
        if before != after:
            raise RecurringEvidenceError("immutable dataset tree changed during verification")
        required_truths = {
            "destination_was_empty": self.destination_was_empty,
            "owner_only": self.owner_only,
            "exact_version_endpoint_used": self.exact_version_endpoint_used,
            "inventory_complete": self.inventory_complete,
            "streamed_one_file_at_a_time": self.streamed_one_file_at_a_time,
            "dataset_tree_non_writable": self.dataset_tree_non_writable,
            "sidecars_absent": self.sidecars_absent,
        }
        for label, value in required_truths.items():
            if value is not True:
                raise RecurringEvidenceError(f"immutable readback requires {label}=true")
        object.__setattr__(self, "resources", resources)

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "kind": self.kind,
            "dataset_ref": self.dataset_ref,
            "parent_dataset_version": self.parent_dataset_version,
            "dataset_version": self.dataset_version,
            "version_endpoint": self.version_endpoint,
            "source_sha": self.source_sha,
            "update_transaction_id": self.update_transaction_id,
            "parent_fingerprint_sha256": self.parent_fingerprint_sha256,
            "assured_candidate_sha256": self.assured_candidate_sha256,
            "publication_receipt_sha256": self.publication_receipt_sha256,
            "remote_publication_readback_sha256": self.remote_publication_readback_sha256,
            "resource_count": len(self.resources),
            "resources": [item.to_dict() for item in self.resources],
            "resource_inventory_sha256": self.resource_inventory_sha256,
            "dataset_root_id": self.dataset_root_id,
            "evidence_root_id": self.evidence_root_id,
            "immutable_tree_sha256_before": self.immutable_tree_sha256_before,
            "immutable_tree_sha256_after": self.immutable_tree_sha256_after,
            "destination_was_empty": self.destination_was_empty,
            "owner_only": self.owner_only,
            "exact_version_endpoint_used": self.exact_version_endpoint_used,
            "inventory_complete": self.inventory_complete,
            "streamed_one_file_at_a_time": self.streamed_one_file_at_a_time,
            "dataset_tree_non_writable": self.dataset_tree_non_writable,
            "sidecars_absent": self.sidecars_absent,
        }

    @classmethod
    def from_dict(cls, payload: Mapping[str, object]) -> Self:
        expected = {
            "schema_version",
            "kind",
            "dataset_ref",
            "parent_dataset_version",
            "dataset_version",
            "version_endpoint",
            "source_sha",
            "update_transaction_id",
            "parent_fingerprint_sha256",
            "assured_candidate_sha256",
            "publication_receipt_sha256",
            "remote_publication_readback_sha256",
            "resource_count",
            "resources",
            "resource_inventory_sha256",
            "dataset_root_id",
            "evidence_root_id",
            "immutable_tree_sha256_before",
            "immutable_tree_sha256_after",
            "destination_was_empty",
            "owner_only",
            "exact_version_endpoint_used",
            "inventory_complete",
            "streamed_one_file_at_a_time",
            "dataset_tree_non_writable",
            "sidecars_absent",
        }
        _require_exact_keys(payload, expected, label=cls.kind)
        if (
            type(payload["schema_version"]) is not int
            or payload["schema_version"] != cls.schema_version
            or payload["kind"] != cls.kind
        ):
            raise RecurringEvidenceError("immutable readback schema identity is invalid")
        resources = tuple(
            ReadbackResourceV1.from_dict(_mapping(item, label="readback resource"))
            for item in _list(payload["resources"], label="resources")
        )
        if _nonnegative_int(payload["resource_count"], label="resource_count") != len(resources):
            raise RecurringEvidenceError("readback resource_count does not match inventory")
        return cls(
            dataset_ref=_dataset_ref(payload["dataset_ref"]),
            parent_dataset_version=_positive_int(
                payload["parent_dataset_version"],
                label="parent_dataset_version",
            ),
            dataset_version=_positive_int(payload["dataset_version"], label="dataset_version"),
            version_endpoint=_string(payload["version_endpoint"], label="version_endpoint"),
            source_sha=_source_sha(payload["source_sha"]),
            update_transaction_id=_sha256(
                payload["update_transaction_id"],
                label="update_transaction_id",
            ),
            parent_fingerprint_sha256=_sha256(
                payload["parent_fingerprint_sha256"],
                label="parent_fingerprint_sha256",
            ),
            assured_candidate_sha256=_sha256(
                payload["assured_candidate_sha256"],
                label="assured_candidate_sha256",
            ),
            publication_receipt_sha256=_sha256(
                payload["publication_receipt_sha256"],
                label="publication_receipt_sha256",
            ),
            remote_publication_readback_sha256=_sha256(
                payload["remote_publication_readback_sha256"],
                label="remote_publication_readback_sha256",
            ),
            resources=resources,
            resource_inventory_sha256=_sha256(
                payload["resource_inventory_sha256"],
                label="resource_inventory_sha256",
            ),
            dataset_root_id=_safe_token(payload["dataset_root_id"], label="dataset_root_id"),
            evidence_root_id=_safe_token(
                payload["evidence_root_id"],
                label="evidence_root_id",
            ),
            immutable_tree_sha256_before=_sha256(
                payload["immutable_tree_sha256_before"],
                label="immutable_tree_sha256_before",
            ),
            immutable_tree_sha256_after=_sha256(
                payload["immutable_tree_sha256_after"],
                label="immutable_tree_sha256_after",
            ),
            destination_was_empty=_bool(
                payload["destination_was_empty"],
                label="destination_was_empty",
            ),
            owner_only=_bool(payload["owner_only"], label="owner_only"),
            exact_version_endpoint_used=_bool(
                payload["exact_version_endpoint_used"],
                label="exact_version_endpoint_used",
            ),
            inventory_complete=_bool(
                payload["inventory_complete"],
                label="inventory_complete",
            ),
            streamed_one_file_at_a_time=_bool(
                payload["streamed_one_file_at_a_time"],
                label="streamed_one_file_at_a_time",
            ),
            dataset_tree_non_writable=_bool(
                payload["dataset_tree_non_writable"],
                label="dataset_tree_non_writable",
            ),
            sidecars_absent=_bool(payload["sidecars_absent"], label="sidecars_absent"),
        )


def _sha256_tuple(values: object, *, label: str, nonempty: bool = True) -> tuple[str, ...]:
    sequence = tuple(_list(values, label=label)) if isinstance(values, list) else values
    if type(sequence) is not tuple:
        raise RecurringEvidenceError(f"{label} must be an immutable tuple")
    result = tuple(_sha256(value, label=label) for value in sequence)
    if nonempty and not result:
        raise RecurringEvidenceError(f"{label} must be nonempty")
    if len(result) != len(set(result)) or result != tuple(sorted(result)):
        raise RecurringEvidenceError(f"{label} must be sorted and duplicate-free")
    return result


def _path_tuple(values: object, *, label: str) -> tuple[str, ...]:
    sequence = tuple(_list(values, label=label)) if isinstance(values, list) else values
    if type(sequence) is not tuple:
        raise RecurringEvidenceError(f"{label} must be an immutable tuple")
    result = tuple(_safe_relative_path(value, label=label) for value in sequence)
    if not result or len(result) > _MAX_SAMPLES:
        raise RecurringEvidenceError(f"{label} size is invalid")
    if len(result) != len(set(result)) or result != tuple(sorted(result)):
        raise RecurringEvidenceError(f"{label} must be sorted and duplicate-free")
    return result


@dataclass(frozen=True, slots=True)
class HumanQueryObservationV1:
    """One human-selected query and its independently recorded value evidence."""

    query_id: str
    query_sha256: str
    result_sha256: str
    row_count: int
    sampled_value_sha256s: tuple[str, ...]

    def __post_init__(self) -> None:
        _safe_token(self.query_id, label="query_id")
        _sha256(self.query_sha256, label="query_sha256")
        _sha256(self.result_sha256, label="result_sha256")
        _nonnegative_int(self.row_count, label="row_count")
        values = _sha256_tuple(self.sampled_value_sha256s, label="sampled_value_sha256s")
        object.__setattr__(self, "sampled_value_sha256s", values)

    def to_dict(self) -> dict[str, Any]:
        return {
            "query_id": self.query_id,
            "query_sha256": self.query_sha256,
            "result_sha256": self.result_sha256,
            "row_count": self.row_count,
            "sampled_value_sha256s": list(self.sampled_value_sha256s),
        }

    @classmethod
    def from_dict(cls, payload: Mapping[str, object]) -> Self:
        _require_exact_keys(
            payload,
            {
                "query_id",
                "query_sha256",
                "result_sha256",
                "row_count",
                "sampled_value_sha256s",
            },
            label="human query observation",
        )
        return cls(
            query_id=_safe_token(payload["query_id"], label="query_id"),
            query_sha256=_sha256(payload["query_sha256"], label="query_sha256"),
            result_sha256=_sha256(payload["result_sha256"], label="result_sha256"),
            row_count=_nonnegative_int(payload["row_count"], label="row_count"),
            sampled_value_sha256s=_sha256_tuple(
                payload["sampled_value_sha256s"],
                label="sampled_value_sha256s",
            ),
        )


@dataclass(frozen=True, slots=True)
class HumanFormatObservationV1:
    """Human-authored read-only observations for one public storage format."""

    format_name: str
    access_mode: str
    decoder_identity_sha256: str
    sampled_resource_paths: tuple[str, ...]
    query_observations: tuple[HumanQueryObservationV1, ...]

    def __post_init__(self) -> None:
        if self.format_name not in REQUIRED_MANUAL_FORMATS:
            raise RecurringEvidenceError("manual format is not one of the required four")
        expected_modes = {
            "duckdb": "read_only_external_access_disabled",
            "sqlite": "mode_ro_immutable_1",
            "parquet": "independent_decoder_read_only",
            "csv": "independent_decoder_read_only",
        }
        if self.access_mode != expected_modes[self.format_name]:
            raise RecurringEvidenceError("manual format access mode is not fail-closed")
        _sha256(self.decoder_identity_sha256, label="decoder_identity_sha256")
        paths = _path_tuple(self.sampled_resource_paths, label="sampled_resource_paths")
        suffixes = {
            "duckdb": (".duckdb",),
            "sqlite": (".sqlite",),
            "parquet": (".parquet",),
            "csv": (".csv",),
        }
        if any(not path.endswith(suffixes[self.format_name]) for path in paths):
            raise RecurringEvidenceError("sampled resource does not match its storage format")
        observations = tuple(self.query_observations)
        if not observations or len(observations) > _MAX_SAMPLES:
            raise RecurringEvidenceError("manual query observation inventory size is invalid")
        if any(not isinstance(item, HumanQueryObservationV1) for item in observations):
            raise RecurringEvidenceError("manual query observation is invalid")
        query_ids = tuple(item.query_id for item in observations)
        if query_ids != tuple(sorted(query_ids)) or len(query_ids) != len(set(query_ids)):
            raise RecurringEvidenceError("manual queries must be sorted and identity-unique")
        object.__setattr__(self, "sampled_resource_paths", paths)
        object.__setattr__(self, "query_observations", observations)

    def to_dict(self) -> dict[str, Any]:
        return {
            "format_name": self.format_name,
            "access_mode": self.access_mode,
            "decoder_identity_sha256": self.decoder_identity_sha256,
            "sampled_resource_paths": list(self.sampled_resource_paths),
            "query_observations": [item.to_dict() for item in self.query_observations],
        }

    @classmethod
    def from_dict(cls, payload: Mapping[str, object]) -> Self:
        _require_exact_keys(
            payload,
            {
                "format_name",
                "access_mode",
                "decoder_identity_sha256",
                "sampled_resource_paths",
                "query_observations",
            },
            label="human format observation",
        )
        return cls(
            format_name=_string(payload["format_name"], label="format_name"),
            access_mode=_string(payload["access_mode"], label="access_mode"),
            decoder_identity_sha256=_sha256(
                payload["decoder_identity_sha256"],
                label="decoder_identity_sha256",
            ),
            sampled_resource_paths=_path_tuple(
                payload["sampled_resource_paths"],
                label="sampled_resource_paths",
            ),
            query_observations=tuple(
                HumanQueryObservationV1.from_dict(_mapping(item, label="human query observation"))
                for item in _list(payload["query_observations"], label="query_observations")
            ),
        )


@dataclass(frozen=True, slots=True)
class HumanVerificationReceiptV1(_CanonicalReceipt):
    """Authenticated human-authored inspection of the immutable successor tree."""

    dataset_ref: str
    parent_dataset_version: int
    successor_dataset_version: int
    source_sha: str
    update_transaction_id: str
    parent_fingerprint_sha256: str
    assured_candidate_sha256: str
    immutable_readback_sha256: str
    resource_inventory_sha256: str
    immutable_tree_sha256_before: str
    immutable_tree_sha256_after: str
    challenge_sha256: str
    challenge_nonce: str
    coverage_categories: tuple[str, ...]
    verifier_subject: str
    verifier_identity_sha256: str
    authentication_method: str
    authentication_evidence_sha256: str
    trusted_handoff_receipt_sha256: str
    audit_time: str
    format_observations: tuple[HumanFormatObservationV1, ...]
    version_page_inventory_sha256: str
    acknowledgement: str
    authenticated: bool = True
    human_authored: bool = True
    workflow_authored: bool = False
    headless: bool = False
    kaggle_version_page_checked: bool = True
    schema_version: ClassVar[int] = 1
    kind: ClassVar[str] = "human_verification_receipt"

    _ACKNOWLEDGEMENT: ClassVar[str] = (
        "I manually verified the exact immutable nbadb version in all four formats."
    )
    _AUTH_METHODS: ClassVar[frozenset[str]] = frozenset(
        {"github_trusted_handoff", "signed_identity", "webauthn"}
    )

    def __post_init__(self) -> None:
        _dataset_ref(self.dataset_ref)
        parent = _positive_int(self.parent_dataset_version, label="parent_dataset_version")
        successor = _positive_int(
            self.successor_dataset_version,
            label="successor_dataset_version",
        )
        if successor != parent + 1:
            raise RecurringEvidenceError("human receipt does not bind the exact parent successor")
        _source_sha(self.source_sha)
        _sha256(self.update_transaction_id, label="update_transaction_id")
        _sha256(self.parent_fingerprint_sha256, label="parent_fingerprint_sha256")
        _sha256(self.assured_candidate_sha256, label="assured_candidate_sha256")
        _sha256(self.immutable_readback_sha256, label="immutable_readback_sha256")
        inventory = _sha256(
            self.resource_inventory_sha256,
            label="resource_inventory_sha256",
        )
        before = _sha256(
            self.immutable_tree_sha256_before,
            label="immutable_tree_sha256_before",
        )
        after = _sha256(
            self.immutable_tree_sha256_after,
            label="immutable_tree_sha256_after",
        )
        if before != after:
            raise RecurringEvidenceError("human inspection changed the immutable dataset tree")
        _sha256(self.challenge_sha256, label="challenge_sha256")
        nonce = _safe_token(self.challenge_nonce, label="challenge_nonce")
        if len(nonce) < 32:
            raise RecurringEvidenceError("challenge_nonce must contain at least 32 characters")
        categories = _sorted_unique_strings(
            self.coverage_categories,
            label="coverage_categories",
            expected=REQUIRED_HUMAN_COVERAGE_CATEGORIES,
        )
        subject = _safe_token(self.verifier_subject, label="verifier_subject")
        lowered_subject = subject.casefold()
        if any(part in lowered_subject for part in _NON_HUMAN_SUBJECT_PARTS):
            raise RecurringEvidenceError("verifier_subject is not an admissible human identity")
        _sha256(self.verifier_identity_sha256, label="verifier_identity_sha256")
        if self.authentication_method not in self._AUTH_METHODS:
            raise RecurringEvidenceError("authentication_method is not a trusted human method")
        _sha256(
            self.authentication_evidence_sha256,
            label="authentication_evidence_sha256",
        )
        _sha256(
            self.trusted_handoff_receipt_sha256,
            label="trusted_handoff_receipt_sha256",
        )
        _utc_instant(self.audit_time, label="audit_time")
        observations = tuple(self.format_observations)
        if any(not isinstance(item, HumanFormatObservationV1) for item in observations):
            raise RecurringEvidenceError("format observation member is invalid")
        if tuple(item.format_name for item in observations) != REQUIRED_MANUAL_FORMATS:
            raise RecurringEvidenceError("human receipt must contain all four formats exactly once")
        version_inventory = _sha256(
            self.version_page_inventory_sha256,
            label="version_page_inventory_sha256",
        )
        if version_inventory != inventory:
            raise RecurringEvidenceError("version-page inventory differs from immutable readback")
        if self.acknowledgement != self._ACKNOWLEDGEMENT:
            raise RecurringEvidenceError("human acknowledgement is not exact")
        truth_fields = {
            "authenticated": self.authenticated,
            "human_authored": self.human_authored,
            "kaggle_version_page_checked": self.kaggle_version_page_checked,
        }
        for label, value in truth_fields.items():
            if value is not True:
                raise RecurringEvidenceError(f"human receipt requires {label}=true")
        if self.workflow_authored is not False or self.headless is not False:
            raise RecurringEvidenceError("automation cannot author human verification")
        object.__setattr__(self, "coverage_categories", categories)
        object.__setattr__(self, "format_observations", observations)

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "kind": self.kind,
            "dataset_ref": self.dataset_ref,
            "parent_dataset_version": self.parent_dataset_version,
            "successor_dataset_version": self.successor_dataset_version,
            "source_sha": self.source_sha,
            "update_transaction_id": self.update_transaction_id,
            "parent_fingerprint_sha256": self.parent_fingerprint_sha256,
            "assured_candidate_sha256": self.assured_candidate_sha256,
            "immutable_readback_sha256": self.immutable_readback_sha256,
            "resource_inventory_sha256": self.resource_inventory_sha256,
            "immutable_tree_sha256_before": self.immutable_tree_sha256_before,
            "immutable_tree_sha256_after": self.immutable_tree_sha256_after,
            "challenge_sha256": self.challenge_sha256,
            "challenge_nonce": self.challenge_nonce,
            "coverage_categories": list(self.coverage_categories),
            "verifier_subject": self.verifier_subject,
            "verifier_identity_sha256": self.verifier_identity_sha256,
            "authentication_method": self.authentication_method,
            "authentication_evidence_sha256": self.authentication_evidence_sha256,
            "trusted_handoff_receipt_sha256": self.trusted_handoff_receipt_sha256,
            "audit_time": self.audit_time,
            "format_observation_count": len(self.format_observations),
            "query_observation_count": sum(
                len(item.query_observations) for item in self.format_observations
            ),
            "format_observations": [item.to_dict() for item in self.format_observations],
            "version_page_inventory_sha256": self.version_page_inventory_sha256,
            "acknowledgement": self.acknowledgement,
            "authenticated": self.authenticated,
            "human_authored": self.human_authored,
            "workflow_authored": self.workflow_authored,
            "headless": self.headless,
            "kaggle_version_page_checked": self.kaggle_version_page_checked,
        }

    @classmethod
    def from_dict(cls, payload: Mapping[str, object]) -> Self:
        expected = {
            "schema_version",
            "kind",
            "dataset_ref",
            "parent_dataset_version",
            "successor_dataset_version",
            "source_sha",
            "update_transaction_id",
            "parent_fingerprint_sha256",
            "assured_candidate_sha256",
            "immutable_readback_sha256",
            "resource_inventory_sha256",
            "immutable_tree_sha256_before",
            "immutable_tree_sha256_after",
            "challenge_sha256",
            "challenge_nonce",
            "coverage_categories",
            "verifier_subject",
            "verifier_identity_sha256",
            "authentication_method",
            "authentication_evidence_sha256",
            "trusted_handoff_receipt_sha256",
            "audit_time",
            "format_observation_count",
            "query_observation_count",
            "format_observations",
            "version_page_inventory_sha256",
            "acknowledgement",
            "authenticated",
            "human_authored",
            "workflow_authored",
            "headless",
            "kaggle_version_page_checked",
        }
        _require_exact_keys(payload, expected, label=cls.kind)
        if (
            type(payload["schema_version"]) is not int
            or payload["schema_version"] != cls.schema_version
            or payload["kind"] != cls.kind
        ):
            raise RecurringEvidenceError("human receipt schema identity is invalid")
        formats = tuple(
            HumanFormatObservationV1.from_dict(_mapping(item, label="human format observation"))
            for item in _list(payload["format_observations"], label="format_observations")
        )
        if _nonnegative_int(
            payload["format_observation_count"],
            label="format_observation_count",
        ) != len(formats):
            raise RecurringEvidenceError("format_observation_count does not match inventory")
        query_count = sum(len(item.query_observations) for item in formats)
        if (
            _nonnegative_int(
                payload["query_observation_count"],
                label="query_observation_count",
            )
            != query_count
        ):
            raise RecurringEvidenceError("query_observation_count does not match observations")
        return cls(
            dataset_ref=_dataset_ref(payload["dataset_ref"]),
            parent_dataset_version=_positive_int(
                payload["parent_dataset_version"],
                label="parent_dataset_version",
            ),
            successor_dataset_version=_positive_int(
                payload["successor_dataset_version"],
                label="successor_dataset_version",
            ),
            source_sha=_source_sha(payload["source_sha"]),
            update_transaction_id=_sha256(
                payload["update_transaction_id"],
                label="update_transaction_id",
            ),
            parent_fingerprint_sha256=_sha256(
                payload["parent_fingerprint_sha256"],
                label="parent_fingerprint_sha256",
            ),
            assured_candidate_sha256=_sha256(
                payload["assured_candidate_sha256"],
                label="assured_candidate_sha256",
            ),
            immutable_readback_sha256=_sha256(
                payload["immutable_readback_sha256"],
                label="immutable_readback_sha256",
            ),
            resource_inventory_sha256=_sha256(
                payload["resource_inventory_sha256"],
                label="resource_inventory_sha256",
            ),
            immutable_tree_sha256_before=_sha256(
                payload["immutable_tree_sha256_before"],
                label="immutable_tree_sha256_before",
            ),
            immutable_tree_sha256_after=_sha256(
                payload["immutable_tree_sha256_after"],
                label="immutable_tree_sha256_after",
            ),
            challenge_sha256=_sha256(payload["challenge_sha256"], label="challenge_sha256"),
            challenge_nonce=_safe_token(payload["challenge_nonce"], label="challenge_nonce"),
            coverage_categories=_sorted_unique_strings(
                payload["coverage_categories"],
                label="coverage_categories",
                expected=REQUIRED_HUMAN_COVERAGE_CATEGORIES,
            ),
            verifier_subject=_safe_token(
                payload["verifier_subject"],
                label="verifier_subject",
            ),
            verifier_identity_sha256=_sha256(
                payload["verifier_identity_sha256"],
                label="verifier_identity_sha256",
            ),
            authentication_method=_string(
                payload["authentication_method"],
                label="authentication_method",
            ),
            authentication_evidence_sha256=_sha256(
                payload["authentication_evidence_sha256"],
                label="authentication_evidence_sha256",
            ),
            trusted_handoff_receipt_sha256=_sha256(
                payload["trusted_handoff_receipt_sha256"],
                label="trusted_handoff_receipt_sha256",
            ),
            audit_time=_utc_instant(payload["audit_time"], label="audit_time"),
            format_observations=formats,
            version_page_inventory_sha256=_sha256(
                payload["version_page_inventory_sha256"],
                label="version_page_inventory_sha256",
            ),
            acknowledgement=_string(payload["acknowledgement"], label="acknowledgement"),
            authenticated=_bool(payload["authenticated"], label="authenticated"),
            human_authored=_bool(payload["human_authored"], label="human_authored"),
            workflow_authored=_bool(payload["workflow_authored"], label="workflow_authored"),
            headless=_bool(payload["headless"], label="headless"),
            kaggle_version_page_checked=_bool(
                payload["kaggle_version_page_checked"],
                label="kaggle_version_page_checked",
            ),
        )


@dataclass(frozen=True, slots=True)
class DocsMetadataParityV1(_CanonicalReceipt):
    """Exact docs, generated metadata, and remote-version parity evidence."""

    dataset_ref: str
    parent_dataset_version: int
    successor_dataset_version: int
    source_sha: str
    model_authority_sha256: str
    update_transaction_id: str
    assured_candidate_sha256: str
    immutable_readback_sha256: str
    human_verification_receipt_sha256: str
    remote_resource_inventory_sha256: str
    stable_registry_sha256: str
    authored_docs_sha256: str
    generated_schema_sha256: str
    generated_lineage_sha256: str
    generated_catalog_sha256: str
    kaggle_metadata_sha256: str
    cadence_contract_sha256: str
    temporal_contract_sha256: str
    provenance_contract_sha256: str
    limitations_sha256: str
    experimental_labels_sha256: str
    parity_evidence_sha256: str
    checked_surfaces: tuple[str, ...]
    mismatch_codes: tuple[str, ...] = ()
    parity_complete: bool = True
    schema_version: ClassVar[int] = 1
    kind: ClassVar[str] = "docs_metadata_parity"

    def __post_init__(self) -> None:
        _dataset_ref(self.dataset_ref)
        parent = _positive_int(self.parent_dataset_version, label="parent_dataset_version")
        successor = _positive_int(
            self.successor_dataset_version,
            label="successor_dataset_version",
        )
        if successor != parent + 1:
            raise RecurringEvidenceError("docs parity does not bind the exact parent successor")
        _source_sha(self.source_sha)
        for label, value in (
            ("model_authority_sha256", self.model_authority_sha256),
            ("update_transaction_id", self.update_transaction_id),
            ("assured_candidate_sha256", self.assured_candidate_sha256),
            ("immutable_readback_sha256", self.immutable_readback_sha256),
            ("human_verification_receipt_sha256", self.human_verification_receipt_sha256),
            ("remote_resource_inventory_sha256", self.remote_resource_inventory_sha256),
            ("stable_registry_sha256", self.stable_registry_sha256),
            ("authored_docs_sha256", self.authored_docs_sha256),
            ("generated_schema_sha256", self.generated_schema_sha256),
            ("generated_lineage_sha256", self.generated_lineage_sha256),
            ("generated_catalog_sha256", self.generated_catalog_sha256),
            ("kaggle_metadata_sha256", self.kaggle_metadata_sha256),
            ("cadence_contract_sha256", self.cadence_contract_sha256),
            ("temporal_contract_sha256", self.temporal_contract_sha256),
            ("provenance_contract_sha256", self.provenance_contract_sha256),
            ("limitations_sha256", self.limitations_sha256),
            ("experimental_labels_sha256", self.experimental_labels_sha256),
            ("parity_evidence_sha256", self.parity_evidence_sha256),
        ):
            _sha256(value, label=label)
        surfaces = _sorted_unique_strings(
            self.checked_surfaces,
            label="checked_surfaces",
            expected=REQUIRED_DOCS_PARITY_SURFACES,
        )
        mismatches = tuple(self.mismatch_codes)
        if mismatches:
            raise RecurringEvidenceError("docs parity cannot contain unresolved mismatches")
        if self.parity_complete is not True:
            raise RecurringEvidenceError("docs parity must be complete")
        object.__setattr__(self, "checked_surfaces", surfaces)
        object.__setattr__(self, "mismatch_codes", mismatches)

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "kind": self.kind,
            "dataset_ref": self.dataset_ref,
            "parent_dataset_version": self.parent_dataset_version,
            "successor_dataset_version": self.successor_dataset_version,
            "source_sha": self.source_sha,
            "model_authority_sha256": self.model_authority_sha256,
            "update_transaction_id": self.update_transaction_id,
            "assured_candidate_sha256": self.assured_candidate_sha256,
            "immutable_readback_sha256": self.immutable_readback_sha256,
            "human_verification_receipt_sha256": self.human_verification_receipt_sha256,
            "remote_resource_inventory_sha256": self.remote_resource_inventory_sha256,
            "stable_registry_sha256": self.stable_registry_sha256,
            "authored_docs_sha256": self.authored_docs_sha256,
            "generated_schema_sha256": self.generated_schema_sha256,
            "generated_lineage_sha256": self.generated_lineage_sha256,
            "generated_catalog_sha256": self.generated_catalog_sha256,
            "kaggle_metadata_sha256": self.kaggle_metadata_sha256,
            "cadence_contract_sha256": self.cadence_contract_sha256,
            "temporal_contract_sha256": self.temporal_contract_sha256,
            "provenance_contract_sha256": self.provenance_contract_sha256,
            "limitations_sha256": self.limitations_sha256,
            "experimental_labels_sha256": self.experimental_labels_sha256,
            "parity_evidence_sha256": self.parity_evidence_sha256,
            "checked_surfaces": list(self.checked_surfaces),
            "mismatch_codes": list(self.mismatch_codes),
            "parity_complete": self.parity_complete,
        }

    @classmethod
    def from_dict(cls, payload: Mapping[str, object]) -> Self:
        expected = {
            "schema_version",
            "kind",
            "dataset_ref",
            "parent_dataset_version",
            "successor_dataset_version",
            "source_sha",
            "model_authority_sha256",
            "update_transaction_id",
            "assured_candidate_sha256",
            "immutable_readback_sha256",
            "human_verification_receipt_sha256",
            "remote_resource_inventory_sha256",
            "stable_registry_sha256",
            "authored_docs_sha256",
            "generated_schema_sha256",
            "generated_lineage_sha256",
            "generated_catalog_sha256",
            "kaggle_metadata_sha256",
            "cadence_contract_sha256",
            "temporal_contract_sha256",
            "provenance_contract_sha256",
            "limitations_sha256",
            "experimental_labels_sha256",
            "parity_evidence_sha256",
            "checked_surfaces",
            "mismatch_codes",
            "parity_complete",
        }
        _require_exact_keys(payload, expected, label=cls.kind)
        if (
            type(payload["schema_version"]) is not int
            or payload["schema_version"] != cls.schema_version
            or payload["kind"] != cls.kind
        ):
            raise RecurringEvidenceError("docs parity schema identity is invalid")
        mismatch_values = _list(payload["mismatch_codes"], label="mismatch_codes")
        if mismatch_values:
            raise RecurringEvidenceError("docs parity mismatch inventory must be empty")
        return cls(
            dataset_ref=_dataset_ref(payload["dataset_ref"]),
            parent_dataset_version=_positive_int(
                payload["parent_dataset_version"],
                label="parent_dataset_version",
            ),
            successor_dataset_version=_positive_int(
                payload["successor_dataset_version"],
                label="successor_dataset_version",
            ),
            source_sha=_source_sha(payload["source_sha"]),
            model_authority_sha256=_sha256(
                payload["model_authority_sha256"],
                label="model_authority_sha256",
            ),
            update_transaction_id=_sha256(
                payload["update_transaction_id"],
                label="update_transaction_id",
            ),
            assured_candidate_sha256=_sha256(
                payload["assured_candidate_sha256"],
                label="assured_candidate_sha256",
            ),
            immutable_readback_sha256=_sha256(
                payload["immutable_readback_sha256"],
                label="immutable_readback_sha256",
            ),
            human_verification_receipt_sha256=_sha256(
                payload["human_verification_receipt_sha256"],
                label="human_verification_receipt_sha256",
            ),
            remote_resource_inventory_sha256=_sha256(
                payload["remote_resource_inventory_sha256"],
                label="remote_resource_inventory_sha256",
            ),
            stable_registry_sha256=_sha256(
                payload["stable_registry_sha256"],
                label="stable_registry_sha256",
            ),
            authored_docs_sha256=_sha256(
                payload["authored_docs_sha256"],
                label="authored_docs_sha256",
            ),
            generated_schema_sha256=_sha256(
                payload["generated_schema_sha256"],
                label="generated_schema_sha256",
            ),
            generated_lineage_sha256=_sha256(
                payload["generated_lineage_sha256"],
                label="generated_lineage_sha256",
            ),
            generated_catalog_sha256=_sha256(
                payload["generated_catalog_sha256"],
                label="generated_catalog_sha256",
            ),
            kaggle_metadata_sha256=_sha256(
                payload["kaggle_metadata_sha256"],
                label="kaggle_metadata_sha256",
            ),
            cadence_contract_sha256=_sha256(
                payload["cadence_contract_sha256"],
                label="cadence_contract_sha256",
            ),
            temporal_contract_sha256=_sha256(
                payload["temporal_contract_sha256"],
                label="temporal_contract_sha256",
            ),
            provenance_contract_sha256=_sha256(
                payload["provenance_contract_sha256"],
                label="provenance_contract_sha256",
            ),
            limitations_sha256=_sha256(
                payload["limitations_sha256"],
                label="limitations_sha256",
            ),
            experimental_labels_sha256=_sha256(
                payload["experimental_labels_sha256"],
                label="experimental_labels_sha256",
            ),
            parity_evidence_sha256=_sha256(
                payload["parity_evidence_sha256"],
                label="parity_evidence_sha256",
            ),
            checked_surfaces=_sorted_unique_strings(
                payload["checked_surfaces"],
                label="checked_surfaces",
                expected=REQUIRED_DOCS_PARITY_SURFACES,
            ),
            mismatch_codes=(),
            parity_complete=_bool(payload["parity_complete"], label="parity_complete"),
        )


@dataclass(frozen=True, slots=True)
class FullBaselineProvenanceV1(_CanonicalReceipt):
    """Fresh attempt-one full-model initial publication provenance."""

    dataset_ref: str
    dataset_version: int
    source_sha: str
    upstream_authority_sha256: str
    model_authority_sha256: str
    model_green_receipt_sha256: str
    actions_run_id: int
    actions_run_attempt: int
    extraction_chain_id: str
    free_execution_admission_sha256: str
    source_ci_receipt_sha256: str
    full_extraction_receipt_sha256: str
    committed_checkpoint_sha256: str
    terminal_catchup_sha256: str
    terminal_scan_sha256: str
    four_format_parity_sha256: str
    dynamic_resource_inventory_sha256: str
    initial_remote_resource_inventory_sha256: str
    initial_assurance_sha256: str
    publication_ledger_receipt_sha256: str
    initial_remote_readback_sha256: str
    public_version_fingerprint_sha256: str
    attempt_one: bool = True
    full_model_authority: bool = True
    populated_row_assurance: bool = True
    exact_positive_version_read_back: bool = True
    schema_version: ClassVar[int] = 1
    kind: ClassVar[str] = "full_baseline_provenance"

    def __post_init__(self) -> None:
        _dataset_ref(self.dataset_ref)
        _positive_int(self.dataset_version, label="dataset_version")
        _source_sha(self.source_sha)
        for label, value in (
            ("upstream_authority_sha256", self.upstream_authority_sha256),
            ("model_authority_sha256", self.model_authority_sha256),
            ("model_green_receipt_sha256", self.model_green_receipt_sha256),
            ("free_execution_admission_sha256", self.free_execution_admission_sha256),
            ("source_ci_receipt_sha256", self.source_ci_receipt_sha256),
            ("full_extraction_receipt_sha256", self.full_extraction_receipt_sha256),
            ("committed_checkpoint_sha256", self.committed_checkpoint_sha256),
            ("terminal_catchup_sha256", self.terminal_catchup_sha256),
            ("terminal_scan_sha256", self.terminal_scan_sha256),
            ("four_format_parity_sha256", self.four_format_parity_sha256),
            ("dynamic_resource_inventory_sha256", self.dynamic_resource_inventory_sha256),
            (
                "initial_remote_resource_inventory_sha256",
                self.initial_remote_resource_inventory_sha256,
            ),
            ("initial_assurance_sha256", self.initial_assurance_sha256),
            ("publication_ledger_receipt_sha256", self.publication_ledger_receipt_sha256),
            ("initial_remote_readback_sha256", self.initial_remote_readback_sha256),
            ("public_version_fingerprint_sha256", self.public_version_fingerprint_sha256),
        ):
            _sha256(value, label=label)
        if self.dynamic_resource_inventory_sha256 != self.initial_remote_resource_inventory_sha256:
            raise RecurringEvidenceError(
                "initial remote inventory differs from the frozen baseline inventory"
            )
        _positive_int(self.actions_run_id, label="actions_run_id")
        if _positive_int(self.actions_run_attempt, label="actions_run_attempt") != 1:
            raise RecurringEvidenceError("full baseline must come from run attempt one")
        _safe_token(self.extraction_chain_id, label="extraction_chain_id")
        for label, value in (
            ("attempt_one", self.attempt_one),
            ("full_model_authority", self.full_model_authority),
            ("populated_row_assurance", self.populated_row_assurance),
            ("exact_positive_version_read_back", self.exact_positive_version_read_back),
        ):
            if value is not True:
                raise RecurringEvidenceError(f"full baseline requires {label}=true")

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "kind": self.kind,
            **{
                name: getattr(self, name)
                for name in self.__dataclass_fields__
                if name not in {"schema_version", "kind"}
            },
        }

    @classmethod
    def from_dict(cls, payload: Mapping[str, object]) -> Self:
        expected = set(cls.__dataclass_fields__) - {"schema_version", "kind"}
        expected.update({"schema_version", "kind"})
        _require_exact_keys(payload, expected, label=cls.kind)
        if (
            type(payload["schema_version"]) is not int
            or payload["schema_version"] != cls.schema_version
            or payload["kind"] != cls.kind
        ):
            raise RecurringEvidenceError("full baseline schema identity is invalid")
        return cls(
            dataset_ref=_dataset_ref(payload["dataset_ref"]),
            dataset_version=_positive_int(payload["dataset_version"], label="dataset_version"),
            source_sha=_source_sha(payload["source_sha"]),
            upstream_authority_sha256=_sha256(
                payload["upstream_authority_sha256"], label="upstream_authority_sha256"
            ),
            model_authority_sha256=_sha256(
                payload["model_authority_sha256"], label="model_authority_sha256"
            ),
            model_green_receipt_sha256=_sha256(
                payload["model_green_receipt_sha256"], label="model_green_receipt_sha256"
            ),
            actions_run_id=_positive_int(payload["actions_run_id"], label="actions_run_id"),
            actions_run_attempt=_positive_int(
                payload["actions_run_attempt"], label="actions_run_attempt"
            ),
            extraction_chain_id=_safe_token(
                payload["extraction_chain_id"], label="extraction_chain_id"
            ),
            free_execution_admission_sha256=_sha256(
                payload["free_execution_admission_sha256"],
                label="free_execution_admission_sha256",
            ),
            source_ci_receipt_sha256=_sha256(
                payload["source_ci_receipt_sha256"], label="source_ci_receipt_sha256"
            ),
            full_extraction_receipt_sha256=_sha256(
                payload["full_extraction_receipt_sha256"],
                label="full_extraction_receipt_sha256",
            ),
            committed_checkpoint_sha256=_sha256(
                payload["committed_checkpoint_sha256"], label="committed_checkpoint_sha256"
            ),
            terminal_catchup_sha256=_sha256(
                payload["terminal_catchup_sha256"], label="terminal_catchup_sha256"
            ),
            terminal_scan_sha256=_sha256(
                payload["terminal_scan_sha256"], label="terminal_scan_sha256"
            ),
            four_format_parity_sha256=_sha256(
                payload["four_format_parity_sha256"], label="four_format_parity_sha256"
            ),
            dynamic_resource_inventory_sha256=_sha256(
                payload["dynamic_resource_inventory_sha256"],
                label="dynamic_resource_inventory_sha256",
            ),
            initial_remote_resource_inventory_sha256=_sha256(
                payload["initial_remote_resource_inventory_sha256"],
                label="initial_remote_resource_inventory_sha256",
            ),
            initial_assurance_sha256=_sha256(
                payload["initial_assurance_sha256"], label="initial_assurance_sha256"
            ),
            publication_ledger_receipt_sha256=_sha256(
                payload["publication_ledger_receipt_sha256"],
                label="publication_ledger_receipt_sha256",
            ),
            initial_remote_readback_sha256=_sha256(
                payload["initial_remote_readback_sha256"],
                label="initial_remote_readback_sha256",
            ),
            public_version_fingerprint_sha256=_sha256(
                payload["public_version_fingerprint_sha256"],
                label="public_version_fingerprint_sha256",
            ),
            attempt_one=_bool(payload["attempt_one"], label="attempt_one"),
            full_model_authority=_bool(
                payload["full_model_authority"], label="full_model_authority"
            ),
            populated_row_assurance=_bool(
                payload["populated_row_assurance"], label="populated_row_assurance"
            ),
            exact_positive_version_read_back=_bool(
                payload["exact_positive_version_read_back"],
                label="exact_positive_version_read_back",
            ),
        )


@dataclass(frozen=True, slots=True)
class ExactParentSuccessorV1(_CanonicalReceipt):
    """Accepted daily successor and its exact-parent publication lineage."""

    dataset_ref: str
    parent_dataset_version: int
    successor_dataset_version: int
    source_sha: str
    upstream_authority_sha256: str
    model_authority_sha256: str
    source_ci_receipt_sha256: str
    update_transaction_id: str
    parent_fingerprint_sha256: str
    assured_candidate_sha256: str
    update_assurance_sha256: str
    recurring_run_status: RecurringRunStatusV1
    recurring_run_status_sha256: str
    coordinator_identity_sha256: str
    request_universe_sha256: str
    monthly_acceptance_sha256: str
    opportunistic_acceptance_sha256: str
    four_format_parity_sha256: str
    dynamic_resource_inventory_sha256: str
    free_execution_admission_sha256: str
    publication_intent_sha256: str
    transaction_generation_resource_sha256: str
    publication_ledger_receipt_sha256: str
    publication_receipt_sha256: str
    remote_publication_readback_sha256: str
    remote_resource_inventory_sha256: str
    exact_parent_proven: bool = True
    distinct_transaction_versioned: bool = True
    schema_version: ClassVar[int] = 1
    kind: ClassVar[str] = "exact_parent_successor"

    def __post_init__(self) -> None:
        dataset_ref = _dataset_ref(self.dataset_ref)
        parent = _positive_int(self.parent_dataset_version, label="parent_dataset_version")
        successor = _positive_int(
            self.successor_dataset_version,
            label="successor_dataset_version",
        )
        if successor != parent + 1:
            raise RecurringEvidenceError("accepted successor must be the exact next version")
        source_sha = _source_sha(self.source_sha)
        for label, value in (
            ("upstream_authority_sha256", self.upstream_authority_sha256),
            ("model_authority_sha256", self.model_authority_sha256),
            ("source_ci_receipt_sha256", self.source_ci_receipt_sha256),
            ("update_transaction_id", self.update_transaction_id),
            ("parent_fingerprint_sha256", self.parent_fingerprint_sha256),
            ("assured_candidate_sha256", self.assured_candidate_sha256),
            ("update_assurance_sha256", self.update_assurance_sha256),
            ("recurring_run_status_sha256", self.recurring_run_status_sha256),
            ("coordinator_identity_sha256", self.coordinator_identity_sha256),
            ("request_universe_sha256", self.request_universe_sha256),
            ("monthly_acceptance_sha256", self.monthly_acceptance_sha256),
            ("opportunistic_acceptance_sha256", self.opportunistic_acceptance_sha256),
            ("four_format_parity_sha256", self.four_format_parity_sha256),
            ("dynamic_resource_inventory_sha256", self.dynamic_resource_inventory_sha256),
            ("free_execution_admission_sha256", self.free_execution_admission_sha256),
            ("publication_intent_sha256", self.publication_intent_sha256),
            (
                "transaction_generation_resource_sha256",
                self.transaction_generation_resource_sha256,
            ),
            ("publication_ledger_receipt_sha256", self.publication_ledger_receipt_sha256),
            ("publication_receipt_sha256", self.publication_receipt_sha256),
            ("remote_publication_readback_sha256", self.remote_publication_readback_sha256),
            ("remote_resource_inventory_sha256", self.remote_resource_inventory_sha256),
        ):
            _sha256(value, label=label)
        status = self.recurring_run_status
        if not isinstance(status, RecurringRunStatusV1):
            raise RecurringEvidenceError("recurring_run_status must be fully validated")
        if status.content_sha256 != self.recurring_run_status_sha256:
            raise RecurringEvidenceError("recurring status digest drifted")
        if (
            status.source_sha != source_sha
            or status.dataset_ref != dataset_ref
            or status.parent_dataset_version != parent
            or status.latest_assured_remote_version != successor
            or status.parent_fingerprint_sha256 != self.parent_fingerprint_sha256
            or status.update_transaction_id != self.update_transaction_id
            or status.coordinator_identity_sha256 != self.coordinator_identity_sha256
            or status.candidate_identity_sha256 != self.assured_candidate_sha256
            or status.request_closure_sha256 != self.request_universe_sha256
            or status.publication_readback_sha256 != self.remote_publication_readback_sha256
            or status.freshness is not FreshnessDecision.FRESH
        ):
            raise RecurringEvidenceError("recurring status does not close the exact successor")
        if self.exact_parent_proven is not True:
            raise RecurringEvidenceError("exact parent proof is required")
        if self.distinct_transaction_versioned is not True:
            raise RecurringEvidenceError("distinct update transaction must own a version")
        if self.dynamic_resource_inventory_sha256 != self.remote_resource_inventory_sha256:
            raise RecurringEvidenceError(
                "successor remote inventory differs from the frozen candidate inventory"
            )

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "kind": self.kind,
            "dataset_ref": self.dataset_ref,
            "parent_dataset_version": self.parent_dataset_version,
            "successor_dataset_version": self.successor_dataset_version,
            "source_sha": self.source_sha,
            "upstream_authority_sha256": self.upstream_authority_sha256,
            "model_authority_sha256": self.model_authority_sha256,
            "source_ci_receipt_sha256": self.source_ci_receipt_sha256,
            "update_transaction_id": self.update_transaction_id,
            "parent_fingerprint_sha256": self.parent_fingerprint_sha256,
            "assured_candidate_sha256": self.assured_candidate_sha256,
            "update_assurance_sha256": self.update_assurance_sha256,
            "recurring_run_status": self.recurring_run_status.to_dict(),
            "recurring_run_status_sha256": self.recurring_run_status_sha256,
            "coordinator_identity_sha256": self.coordinator_identity_sha256,
            "request_universe_sha256": self.request_universe_sha256,
            "monthly_acceptance_sha256": self.monthly_acceptance_sha256,
            "opportunistic_acceptance_sha256": self.opportunistic_acceptance_sha256,
            "four_format_parity_sha256": self.four_format_parity_sha256,
            "dynamic_resource_inventory_sha256": self.dynamic_resource_inventory_sha256,
            "free_execution_admission_sha256": self.free_execution_admission_sha256,
            "publication_intent_sha256": self.publication_intent_sha256,
            "transaction_generation_resource_sha256": (self.transaction_generation_resource_sha256),
            "publication_ledger_receipt_sha256": self.publication_ledger_receipt_sha256,
            "publication_receipt_sha256": self.publication_receipt_sha256,
            "remote_publication_readback_sha256": self.remote_publication_readback_sha256,
            "remote_resource_inventory_sha256": self.remote_resource_inventory_sha256,
            "exact_parent_proven": self.exact_parent_proven,
            "distinct_transaction_versioned": self.distinct_transaction_versioned,
        }

    @classmethod
    def from_dict(cls, payload: Mapping[str, object]) -> Self:
        expected = {
            "schema_version",
            "kind",
            "dataset_ref",
            "parent_dataset_version",
            "successor_dataset_version",
            "source_sha",
            "upstream_authority_sha256",
            "model_authority_sha256",
            "source_ci_receipt_sha256",
            "update_transaction_id",
            "parent_fingerprint_sha256",
            "assured_candidate_sha256",
            "update_assurance_sha256",
            "recurring_run_status",
            "recurring_run_status_sha256",
            "coordinator_identity_sha256",
            "request_universe_sha256",
            "monthly_acceptance_sha256",
            "opportunistic_acceptance_sha256",
            "four_format_parity_sha256",
            "dynamic_resource_inventory_sha256",
            "free_execution_admission_sha256",
            "publication_intent_sha256",
            "transaction_generation_resource_sha256",
            "publication_ledger_receipt_sha256",
            "publication_receipt_sha256",
            "remote_publication_readback_sha256",
            "remote_resource_inventory_sha256",
            "exact_parent_proven",
            "distinct_transaction_versioned",
        }
        _require_exact_keys(payload, expected, label=cls.kind)
        if (
            type(payload["schema_version"]) is not int
            or payload["schema_version"] != cls.schema_version
            or payload["kind"] != cls.kind
        ):
            raise RecurringEvidenceError("exact successor schema identity is invalid")
        return cls(
            dataset_ref=_dataset_ref(payload["dataset_ref"]),
            parent_dataset_version=_positive_int(
                payload["parent_dataset_version"], label="parent_dataset_version"
            ),
            successor_dataset_version=_positive_int(
                payload["successor_dataset_version"], label="successor_dataset_version"
            ),
            source_sha=_source_sha(payload["source_sha"]),
            upstream_authority_sha256=_sha256(
                payload["upstream_authority_sha256"], label="upstream_authority_sha256"
            ),
            model_authority_sha256=_sha256(
                payload["model_authority_sha256"], label="model_authority_sha256"
            ),
            source_ci_receipt_sha256=_sha256(
                payload["source_ci_receipt_sha256"], label="source_ci_receipt_sha256"
            ),
            update_transaction_id=_sha256(
                payload["update_transaction_id"], label="update_transaction_id"
            ),
            parent_fingerprint_sha256=_sha256(
                payload["parent_fingerprint_sha256"], label="parent_fingerprint_sha256"
            ),
            assured_candidate_sha256=_sha256(
                payload["assured_candidate_sha256"], label="assured_candidate_sha256"
            ),
            update_assurance_sha256=_sha256(
                payload["update_assurance_sha256"], label="update_assurance_sha256"
            ),
            recurring_run_status=RecurringRunStatusV1.from_dict(
                _mapping(payload["recurring_run_status"], label="recurring_run_status")
            ),
            recurring_run_status_sha256=_sha256(
                payload["recurring_run_status_sha256"], label="recurring_run_status_sha256"
            ),
            coordinator_identity_sha256=_sha256(
                payload["coordinator_identity_sha256"], label="coordinator_identity_sha256"
            ),
            request_universe_sha256=_sha256(
                payload["request_universe_sha256"], label="request_universe_sha256"
            ),
            monthly_acceptance_sha256=_sha256(
                payload["monthly_acceptance_sha256"], label="monthly_acceptance_sha256"
            ),
            opportunistic_acceptance_sha256=_sha256(
                payload["opportunistic_acceptance_sha256"],
                label="opportunistic_acceptance_sha256",
            ),
            four_format_parity_sha256=_sha256(
                payload["four_format_parity_sha256"], label="four_format_parity_sha256"
            ),
            dynamic_resource_inventory_sha256=_sha256(
                payload["dynamic_resource_inventory_sha256"],
                label="dynamic_resource_inventory_sha256",
            ),
            free_execution_admission_sha256=_sha256(
                payload["free_execution_admission_sha256"],
                label="free_execution_admission_sha256",
            ),
            publication_intent_sha256=_sha256(
                payload["publication_intent_sha256"], label="publication_intent_sha256"
            ),
            transaction_generation_resource_sha256=_sha256(
                payload["transaction_generation_resource_sha256"],
                label="transaction_generation_resource_sha256",
            ),
            publication_ledger_receipt_sha256=_sha256(
                payload["publication_ledger_receipt_sha256"],
                label="publication_ledger_receipt_sha256",
            ),
            publication_receipt_sha256=_sha256(
                payload["publication_receipt_sha256"], label="publication_receipt_sha256"
            ),
            remote_publication_readback_sha256=_sha256(
                payload["remote_publication_readback_sha256"],
                label="remote_publication_readback_sha256",
            ),
            remote_resource_inventory_sha256=_sha256(
                payload["remote_resource_inventory_sha256"],
                label="remote_resource_inventory_sha256",
            ),
            exact_parent_proven=_bool(payload["exact_parent_proven"], label="exact_parent_proven"),
            distinct_transaction_versioned=_bool(
                payload["distinct_transaction_versioned"],
                label="distinct_transaction_versioned",
            ),
        )


@dataclass(frozen=True, slots=True)
class DataGreenReceiptV1(_CanonicalReceipt):
    """The sole final DATA-GREEN authority after every immutable proof joins."""

    source_sha: str
    upstream_authority_sha256: str
    model_authority_sha256: str
    dataset_ref: str
    initial_dataset_version: int
    successor_dataset_version: int
    update_transaction_id: str
    baseline: FullBaselineProvenanceV1
    baseline_provenance_sha256: str
    successor: ExactParentSuccessorV1
    exact_parent_successor_sha256: str
    immutable_readback: ImmutableVersionReadbackV1
    immutable_readback_sha256: str
    human_verification: HumanVerificationReceiptV1
    human_verification_sha256: str
    docs_metadata_parity: DocsMetadataParityV1
    docs_metadata_parity_sha256: str
    initial_publication_readback_sha256: str
    successor_publication_readback_sha256: str
    external_rights_receipt_sha256: str
    actions_closeout_run_id: int
    actions_closeout_run_attempt: int
    closeout_job_receipt_sha256: str
    closeout_source_ci_receipt_sha256: str
    actions_only: bool = True
    non_kaggle_writing_closeout: bool = True
    all_proofs_complete: bool = True
    data_green: bool = True
    schema_version: ClassVar[int] = 1
    kind: ClassVar[str] = "data_green_receipt"

    def __post_init__(self) -> None:
        source_sha = _source_sha(self.source_sha)
        upstream = _sha256(
            self.upstream_authority_sha256,
            label="upstream_authority_sha256",
        )
        model = _sha256(self.model_authority_sha256, label="model_authority_sha256")
        dataset_ref = _dataset_ref(self.dataset_ref)
        initial_version = _positive_int(
            self.initial_dataset_version,
            label="initial_dataset_version",
        )
        successor_version = _positive_int(
            self.successor_dataset_version,
            label="successor_dataset_version",
        )
        if successor_version != initial_version + 1:
            raise RecurringEvidenceError("DATA-GREEN versions are not an exact parent successor")
        transaction_id = _sha256(self.update_transaction_id, label="update_transaction_id")
        if not isinstance(self.baseline, FullBaselineProvenanceV1):
            raise RecurringEvidenceError("baseline provenance is not validated")
        if not isinstance(self.successor, ExactParentSuccessorV1):
            raise RecurringEvidenceError("exact-parent successor is not validated")
        if not isinstance(self.immutable_readback, ImmutableVersionReadbackV1):
            raise RecurringEvidenceError("immutable readback is not validated")
        if not isinstance(self.human_verification, HumanVerificationReceiptV1):
            raise RecurringEvidenceError("human verification is not validated")
        if not isinstance(self.docs_metadata_parity, DocsMetadataParityV1):
            raise RecurringEvidenceError("docs metadata parity is not validated")
        members = (
            ("baseline_provenance_sha256", self.baseline_provenance_sha256, self.baseline),
            (
                "exact_parent_successor_sha256",
                self.exact_parent_successor_sha256,
                self.successor,
            ),
            ("immutable_readback_sha256", self.immutable_readback_sha256, self.immutable_readback),
            (
                "human_verification_sha256",
                self.human_verification_sha256,
                self.human_verification,
            ),
            (
                "docs_metadata_parity_sha256",
                self.docs_metadata_parity_sha256,
                self.docs_metadata_parity,
            ),
        )
        for label, declared, receipt in members:
            if _sha256(declared, label=label) != receipt.content_sha256:
                raise RecurringEvidenceError(f"{label} drifted from its constituent receipt")

        baseline = self.baseline
        successor = self.successor
        readback = self.immutable_readback
        human = self.human_verification
        docs = self.docs_metadata_parity
        if (
            baseline.source_sha != source_sha
            or successor.source_sha != source_sha
            or readback.source_sha != source_sha
            or human.source_sha != source_sha
            or docs.source_sha != source_sha
            or baseline.upstream_authority_sha256 != upstream
            or successor.upstream_authority_sha256 != upstream
            or baseline.model_authority_sha256 != model
            or successor.model_authority_sha256 != model
            or docs.model_authority_sha256 != model
        ):
            raise RecurringEvidenceError("DATA-GREEN source or authority lineage differs")
        if (
            baseline.dataset_ref != dataset_ref
            or successor.dataset_ref != dataset_ref
            or readback.dataset_ref != dataset_ref
            or human.dataset_ref != dataset_ref
            or docs.dataset_ref != dataset_ref
            or baseline.dataset_version != initial_version
            or successor.parent_dataset_version != initial_version
            or successor.successor_dataset_version != successor_version
            or readback.parent_dataset_version != initial_version
            or readback.dataset_version != successor_version
            or human.parent_dataset_version != initial_version
            or human.successor_dataset_version != successor_version
            or docs.parent_dataset_version != initial_version
            or docs.successor_dataset_version != successor_version
        ):
            raise RecurringEvidenceError("DATA-GREEN dataset lineage mixes versions or parents")
        if (
            successor.update_transaction_id != transaction_id
            or readback.update_transaction_id != transaction_id
            or human.update_transaction_id != transaction_id
            or docs.update_transaction_id != transaction_id
        ):
            raise RecurringEvidenceError("DATA-GREEN update_transaction_id differs")
        if (
            successor.parent_fingerprint_sha256 != baseline.public_version_fingerprint_sha256
            or readback.parent_fingerprint_sha256 != baseline.public_version_fingerprint_sha256
            or human.parent_fingerprint_sha256 != baseline.public_version_fingerprint_sha256
        ):
            raise RecurringEvidenceError("DATA-GREEN parent fingerprint differs")
        if (
            readback.assured_candidate_sha256 != successor.assured_candidate_sha256
            or human.assured_candidate_sha256 != successor.assured_candidate_sha256
            or docs.assured_candidate_sha256 != successor.assured_candidate_sha256
        ):
            raise RecurringEvidenceError("DATA-GREEN candidate identity differs")
        if (
            readback.publication_receipt_sha256 != successor.publication_receipt_sha256
            or readback.remote_publication_readback_sha256
            != successor.remote_publication_readback_sha256
            or readback.resource_inventory_sha256 != successor.remote_resource_inventory_sha256
            or human.resource_inventory_sha256 != readback.resource_inventory_sha256
            or docs.remote_resource_inventory_sha256 != readback.resource_inventory_sha256
        ):
            raise RecurringEvidenceError("DATA-GREEN remote inventory or publication differs")
        if (
            human.immutable_readback_sha256 != readback.content_sha256
            or human.immutable_tree_sha256_before != readback.immutable_tree_sha256_before
            or human.immutable_tree_sha256_after != readback.immutable_tree_sha256_after
            or docs.immutable_readback_sha256 != readback.content_sha256
            or docs.human_verification_receipt_sha256 != human.content_sha256
        ):
            raise RecurringEvidenceError("DATA-GREEN immutable, human, or docs binding differs")
        readback_paths = {item.path for item in readback.resources}
        sampled_paths = {
            path
            for observation in human.format_observations
            for path in observation.sampled_resource_paths
        }
        if not sampled_paths.issubset(readback_paths):
            raise RecurringEvidenceError(
                "human verification sampled a resource outside the immutable readback"
            )
        initial_readback = _sha256(
            self.initial_publication_readback_sha256,
            label="initial_publication_readback_sha256",
        )
        successor_readback = _sha256(
            self.successor_publication_readback_sha256,
            label="successor_publication_readback_sha256",
        )
        if initial_readback != baseline.initial_remote_readback_sha256:
            raise RecurringEvidenceError("initial publication readback differs from baseline")
        if successor_readback != successor.remote_publication_readback_sha256:
            raise RecurringEvidenceError("successor publication readback differs")
        if initial_readback == successor_readback:
            raise RecurringEvidenceError("initial and successor readbacks must be distinct")
        _sha256(self.external_rights_receipt_sha256, label="external_rights_receipt_sha256")
        _positive_int(self.actions_closeout_run_id, label="actions_closeout_run_id")
        _positive_int(self.actions_closeout_run_attempt, label="actions_closeout_run_attempt")
        _sha256(self.closeout_job_receipt_sha256, label="closeout_job_receipt_sha256")
        closeout_ci = _sha256(
            self.closeout_source_ci_receipt_sha256,
            label="closeout_source_ci_receipt_sha256",
        )
        if (
            closeout_ci != baseline.source_ci_receipt_sha256
            or closeout_ci != successor.source_ci_receipt_sha256
        ):
            raise RecurringEvidenceError("closeout CI does not bind the shared reviewed source")
        for label, value in (
            ("actions_only", self.actions_only),
            ("non_kaggle_writing_closeout", self.non_kaggle_writing_closeout),
            ("all_proofs_complete", self.all_proofs_complete),
            ("data_green", self.data_green),
        ):
            if value is not True:
                raise RecurringEvidenceError(f"DataGreenReceiptV1 requires {label}=true")

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "kind": self.kind,
            "source_sha": self.source_sha,
            "upstream_authority_sha256": self.upstream_authority_sha256,
            "model_authority_sha256": self.model_authority_sha256,
            "dataset_ref": self.dataset_ref,
            "initial_dataset_version": self.initial_dataset_version,
            "successor_dataset_version": self.successor_dataset_version,
            "update_transaction_id": self.update_transaction_id,
            "baseline": self.baseline.to_dict(),
            "baseline_provenance_sha256": self.baseline_provenance_sha256,
            "successor": self.successor.to_dict(),
            "exact_parent_successor_sha256": self.exact_parent_successor_sha256,
            "immutable_readback": self.immutable_readback.to_dict(),
            "immutable_readback_sha256": self.immutable_readback_sha256,
            "human_verification": self.human_verification.to_dict(),
            "human_verification_sha256": self.human_verification_sha256,
            "docs_metadata_parity": self.docs_metadata_parity.to_dict(),
            "docs_metadata_parity_sha256": self.docs_metadata_parity_sha256,
            "initial_publication_readback_sha256": self.initial_publication_readback_sha256,
            "successor_publication_readback_sha256": (self.successor_publication_readback_sha256),
            "external_rights_receipt_sha256": self.external_rights_receipt_sha256,
            "actions_closeout_run_id": self.actions_closeout_run_id,
            "actions_closeout_run_attempt": self.actions_closeout_run_attempt,
            "closeout_job_receipt_sha256": self.closeout_job_receipt_sha256,
            "closeout_source_ci_receipt_sha256": self.closeout_source_ci_receipt_sha256,
            "actions_only": self.actions_only,
            "non_kaggle_writing_closeout": self.non_kaggle_writing_closeout,
            "all_proofs_complete": self.all_proofs_complete,
            "data_green": self.data_green,
        }

    @classmethod
    def from_dict(cls, payload: Mapping[str, object]) -> Self:
        expected = {
            "schema_version",
            "kind",
            "source_sha",
            "upstream_authority_sha256",
            "model_authority_sha256",
            "dataset_ref",
            "initial_dataset_version",
            "successor_dataset_version",
            "update_transaction_id",
            "baseline",
            "baseline_provenance_sha256",
            "successor",
            "exact_parent_successor_sha256",
            "immutable_readback",
            "immutable_readback_sha256",
            "human_verification",
            "human_verification_sha256",
            "docs_metadata_parity",
            "docs_metadata_parity_sha256",
            "initial_publication_readback_sha256",
            "successor_publication_readback_sha256",
            "external_rights_receipt_sha256",
            "actions_closeout_run_id",
            "actions_closeout_run_attempt",
            "closeout_job_receipt_sha256",
            "closeout_source_ci_receipt_sha256",
            "actions_only",
            "non_kaggle_writing_closeout",
            "all_proofs_complete",
            "data_green",
        }
        _require_exact_keys(payload, expected, label=cls.kind)
        if (
            type(payload["schema_version"]) is not int
            or payload["schema_version"] != cls.schema_version
            or payload["kind"] != cls.kind
        ):
            raise RecurringEvidenceError("DATA-GREEN schema identity is invalid")
        return cls(
            source_sha=_source_sha(payload["source_sha"]),
            upstream_authority_sha256=_sha256(
                payload["upstream_authority_sha256"], label="upstream_authority_sha256"
            ),
            model_authority_sha256=_sha256(
                payload["model_authority_sha256"], label="model_authority_sha256"
            ),
            dataset_ref=_dataset_ref(payload["dataset_ref"]),
            initial_dataset_version=_positive_int(
                payload["initial_dataset_version"], label="initial_dataset_version"
            ),
            successor_dataset_version=_positive_int(
                payload["successor_dataset_version"], label="successor_dataset_version"
            ),
            update_transaction_id=_sha256(
                payload["update_transaction_id"], label="update_transaction_id"
            ),
            baseline=FullBaselineProvenanceV1.from_dict(
                _mapping(payload["baseline"], label="baseline")
            ),
            baseline_provenance_sha256=_sha256(
                payload["baseline_provenance_sha256"], label="baseline_provenance_sha256"
            ),
            successor=ExactParentSuccessorV1.from_dict(
                _mapping(payload["successor"], label="successor")
            ),
            exact_parent_successor_sha256=_sha256(
                payload["exact_parent_successor_sha256"],
                label="exact_parent_successor_sha256",
            ),
            immutable_readback=ImmutableVersionReadbackV1.from_dict(
                _mapping(payload["immutable_readback"], label="immutable_readback")
            ),
            immutable_readback_sha256=_sha256(
                payload["immutable_readback_sha256"], label="immutable_readback_sha256"
            ),
            human_verification=HumanVerificationReceiptV1.from_dict(
                _mapping(payload["human_verification"], label="human_verification")
            ),
            human_verification_sha256=_sha256(
                payload["human_verification_sha256"], label="human_verification_sha256"
            ),
            docs_metadata_parity=DocsMetadataParityV1.from_dict(
                _mapping(payload["docs_metadata_parity"], label="docs_metadata_parity")
            ),
            docs_metadata_parity_sha256=_sha256(
                payload["docs_metadata_parity_sha256"], label="docs_metadata_parity_sha256"
            ),
            initial_publication_readback_sha256=_sha256(
                payload["initial_publication_readback_sha256"],
                label="initial_publication_readback_sha256",
            ),
            successor_publication_readback_sha256=_sha256(
                payload["successor_publication_readback_sha256"],
                label="successor_publication_readback_sha256",
            ),
            external_rights_receipt_sha256=_sha256(
                payload["external_rights_receipt_sha256"],
                label="external_rights_receipt_sha256",
            ),
            actions_closeout_run_id=_positive_int(
                payload["actions_closeout_run_id"], label="actions_closeout_run_id"
            ),
            actions_closeout_run_attempt=_positive_int(
                payload["actions_closeout_run_attempt"], label="actions_closeout_run_attempt"
            ),
            closeout_job_receipt_sha256=_sha256(
                payload["closeout_job_receipt_sha256"], label="closeout_job_receipt_sha256"
            ),
            closeout_source_ci_receipt_sha256=_sha256(
                payload["closeout_source_ci_receipt_sha256"],
                label="closeout_source_ci_receipt_sha256",
            ),
            actions_only=_bool(payload["actions_only"], label="actions_only"),
            non_kaggle_writing_closeout=_bool(
                payload["non_kaggle_writing_closeout"],
                label="non_kaggle_writing_closeout",
            ),
            all_proofs_complete=_bool(payload["all_proofs_complete"], label="all_proofs_complete"),
            data_green=_bool(payload["data_green"], label="data_green"),
        )
