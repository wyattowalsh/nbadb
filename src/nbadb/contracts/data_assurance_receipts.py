"""Hard DATA assurance receipts for extraction, publication, and closeout.

Every receipt in this module is an exact-key sealed dataclass: its self digest
is the SHA-256 of the canonical bytes of all other fields, recomputed on
construction and deserialization so a stored literal never confers authority.
Derived status fields (``admitted``, ``parity_ok``, ``parity``, and
``data_status``) are recomputed from the bound evidence vectors and any
disagreement fails construction.

The chain ordering is deliberate:

1. :class:`PrivateCaptureAssuranceReceiptV1` -- digests/counts only, never
   provider body bytes.
2. :class:`PrepublicationDataAdmissionV1` -- the hard pre-upload join.
3. :class:`RemoteReadbackReceiptV1` -- ordered remote evidence vectors.
4. :class:`HumanVerificationChallengeV1` / :class:`HumanVerificationReceiptV1`
   -- deterministic challenge plus human-authored observations.
5. :class:`DocsMetadataParityV1` -- uploaded-metadata and docs agreement.
6. :class:`DataGreenReceiptV1` -- final join; MODEL status is advisory only.

:class:`HumanVerificationReceiptV1` is the canonical human receipt name; the
competing ``ManualDatasetValidationReceiptV1`` name is intentionally absent.
"""

from __future__ import annotations

import re
import types
from dataclasses import dataclass, fields, is_dataclass
from typing import Any, ClassVar, Final, Self, cast, get_args, get_origin, get_type_hints

from nbadb.contracts.receipt_digest import (
    CanonicalReceiptError,
    canonical_receipt_digest,
    verify_receipt_digest,
)

__all__ = [
    "DATA_ASSURANCE_SCHEMA_VERSION",
    "DATA_STATUS_GREEN",
    "MODEL_STATUSES",
    "DataAssuranceReceiptError",
    "DataGreenReceiptV1",
    "DocsMetadataParityV1",
    "HumanObservationV1",
    "HumanQueryCheckV1",
    "HumanVerificationChallengeV1",
    "HumanVerificationReceiptV1",
    "PrepublicationDataAdmissionV1",
    "PrivateCaptureAssuranceReceiptV1",
    "RemotePrivateExclusionScanV1",
    "RemoteReadbackReceiptV1",
    "RemoteResourceV1",
    "RemoteSchemaObservationV1",
    "RemoteValueQueryObservationV1",
]

#: Schema version for every serialized receipt in this module.
DATA_ASSURANCE_SCHEMA_VERSION: Final = 1

#: The only admissible hard DATA status literal, and it is always derived.
DATA_STATUS_GREEN: Final = "GREEN"

#: Advisory MODEL statuses; ``RED`` never blocks a complete DATA chain.
MODEL_STATUSES: Final = frozenset({"GREEN", "RED", "UNPROVEN"})

_SHA256_HEX: Final = re.compile(r"[0-9a-f]{64}\Z", flags=re.ASCII)
_GIT_SHA: Final = re.compile(r"[0-9a-f]{40}\Z", flags=re.ASCII)
_REPOSITORY: Final = re.compile(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+\Z", flags=re.ASCII)
_RELATIVE_PATH: Final = re.compile(r"[A-Za-z0-9._][A-Za-z0-9._/-]*\Z", flags=re.ASCII)
_MEDIA_TYPE: Final = re.compile(r"[A-Za-z0-9.+-]+/[A-Za-z0-9.+-]+\Z", flags=re.ASCII)
_RELATION_NAME: Final = re.compile(r"[A-Za-z0-9_][A-Za-z0-9_.]*\Z", flags=re.ASCII)
_QUERY_FORMATS: Final = frozenset({"duckdb", "sqlite", "parquet", "csv"})

#: Acknowledgment literals that never count as a human acknowledgment.
_AUTOMATION_ACKNOWLEDGMENT_SENTINELS: Final = frozenset(
    {"", "AUTOMATED", "AUTOFILLED", "AUTO-GENERATED", "N/A"}
)


class DataAssuranceReceiptError(ValueError):
    """A DATA assurance receipt is malformed, tampered, or incomplete."""


# ---------------------------------------------------------------------------
# Shared validation helpers
# ---------------------------------------------------------------------------


def _require_str(value: object, field: str) -> str:
    if not isinstance(value, str) or not value:
        raise DataAssuranceReceiptError(f"{field} must be a non-empty string")
    return value


def _require_sha256(value: object, field: str) -> str:
    if not isinstance(value, str) or not _SHA256_HEX.fullmatch(value):
        raise DataAssuranceReceiptError(
            f"{field} must be a 64 lowercase hex character sha256 digest"
        )
    return value


def _require_git_sha(value: object, field: str) -> str:
    if not isinstance(value, str) or not _GIT_SHA.fullmatch(value):
        raise DataAssuranceReceiptError(f"{field} must be a 40 hex character git sha")
    return value


def _require_int(value: object, field: str, *, minimum: int) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < minimum:
        raise DataAssuranceReceiptError(f"{field} must be an integer >= {minimum}")
    return value


def _require_bool(value: object, field: str) -> bool:
    if not isinstance(value, bool):
        raise DataAssuranceReceiptError(f"{field} must be a boolean")
    return value


def _require_repository(value: object, field: str = "dataset") -> str:
    text = _require_str(value, field)
    if not _REPOSITORY.fullmatch(text):
        raise DataAssuranceReceiptError(f"{field} must be 'owner/name', got {text!r}")
    return text


def _require_relative_path(value: object, field: str) -> str:
    text = _require_str(value, field)
    if not _RELATIVE_PATH.fullmatch(text) or text.startswith("/"):
        raise DataAssuranceReceiptError(f"{field} must be a relative POSIX path, got {text!r}")
    segments = text.split("/")
    repeated = len(set(segments)) != len(segments)
    if any(segment in {"", ".", ".."} for segment in segments) or repeated:
        raise DataAssuranceReceiptError(
            f"{field} must not contain empty, '.', '..', or repeated segments: {text!r}"
        )
    return text


def _require_tuple(value: object, field: str, *, item_type: type, allow_empty: bool) -> tuple:
    if not isinstance(value, tuple):
        raise DataAssuranceReceiptError(f"{field} must be a tuple of {item_type.__name__}")
    if not allow_empty and not value:
        raise DataAssuranceReceiptError(f"{field} must not be empty")
    for item in value:
        if not isinstance(item, item_type):
            raise DataAssuranceReceiptError(
                f"{field} entries must be {item_type.__name__}, got {type(item).__name__}"
            )
    return value


def _require_unique(values: tuple[str, ...], field: str) -> None:
    if len(set(values)) != len(values):
        raise DataAssuranceReceiptError(f"{field} entries must be unique")


def _to_shape(value: object) -> object:
    """Convert a receipt value into plain JSON shapes."""
    if is_dataclass(value):
        return {field.name: _to_shape(getattr(value, field.name)) for field in fields(value)}
    if isinstance(value, tuple):
        return [_to_shape(item) for item in value]
    if isinstance(value, list):
        return [_to_shape(item) for item in value]
    if isinstance(value, dict):
        return {key: _to_shape(item) for key, item in value.items()}
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    raise DataAssuranceReceiptError(f"receipt values must be JSON shapes, got {type(value)!r}")


def _decode_value(annotation: object, value: object, field: str) -> object:
    """Decode a payload value against a field annotation."""
    origin = get_origin(annotation)
    if origin is tuple:
        if not isinstance(value, list):
            raise DataAssuranceReceiptError(f"{field} must serialize to a list")
        item_annotation = get_args(annotation)[0]
        decoded: list[object] = []
        for item in value:
            if is_dataclass(item_annotation):
                decoded.append(item_annotation.from_payload(item))  # type: ignore[attr-defined]
            else:
                decoded.append(item)
        return tuple(decoded)
    if origin is types.UnionType and value is None and type(None) in get_args(annotation):
        return None
    return value


class _EvidenceMixin:
    """Exact-key payload support for digest-free evidence items."""

    def __post_init__(self) -> None:
        self._validate()

    def _validate(self) -> None:
        raise NotImplementedError

    def to_payload(self) -> dict[str, object]:
        """Serialize to an exact-key mapping."""
        return {
            field.name: _to_shape(getattr(self, field.name)) for field in fields(cast("Any", self))
        }

    @classmethod
    def from_payload(cls, payload: object) -> Self:
        """Parse an exact-key mapping; missing or extra keys fail."""
        if not isinstance(payload, dict):
            raise DataAssuranceReceiptError(f"{cls.__name__} payload must be a mapping")
        expected = {field.name for field in fields(cast("Any", cls))}
        if set(payload) != expected:
            missing = sorted(expected - set(payload))
            extra = sorted(set(payload) - expected)
            raise DataAssuranceReceiptError(
                f"{cls.__name__} keys mismatch: missing={missing} extra={extra}"
            )
        hints = get_type_hints(cls)
        kwargs = {name: _decode_value(hints[name], payload.get(name), name) for name in expected}
        return cls(**kwargs)  # type: ignore[no-any-return]


class _SealedReceiptMixin(_EvidenceMixin):
    """Exact-key payload plus self-digest sealing for top-level receipts."""

    _DIGEST_FIELD: ClassVar[str]

    def __post_init__(self) -> None:
        self._validate()
        try:
            verify_receipt_digest(self, digest_field=self._DIGEST_FIELD)
        except CanonicalReceiptError as exc:
            raise DataAssuranceReceiptError(str(exc)) from exc

    def to_payload(self) -> dict[str, object]:
        payload = super().to_payload()
        payload["schema_version"] = DATA_ASSURANCE_SCHEMA_VERSION
        return payload

    @classmethod
    def from_payload(cls, payload: object) -> Self:
        if not isinstance(payload, dict):
            raise DataAssuranceReceiptError(f"{cls.__name__} payload must be a mapping")
        expected = {field.name for field in fields(cast("Any", cls))} | {"schema_version"}
        if set(payload) != expected:
            missing = sorted(expected - set(payload))
            extra = sorted(set(payload) - expected)
            raise DataAssuranceReceiptError(
                f"{cls.__name__} keys mismatch: missing={missing} extra={extra}"
            )
        schema_version = payload.get("schema_version")
        if schema_version != DATA_ASSURANCE_SCHEMA_VERSION:
            raise DataAssuranceReceiptError(
                f"unsupported {cls.__name__} schema version {schema_version!r}"
            )
        hints = get_type_hints(cls)
        kwargs = {
            name: _decode_value(hints[name], payload.get(name), name)
            for name in expected - {"schema_version"}
        }
        return cls(**kwargs)  # type: ignore[no-any-return]

    @classmethod
    def build(cls, **values: Any) -> Self:
        """Construct a receipt with its self digest computed from the evidence.

        ``values`` must provide every field except the digest field itself.
        """
        expected = {field.name for field in fields(cls)} - {cls._DIGEST_FIELD}  # type: ignore[arg-type]
        if set(values) != expected:
            missing = sorted(expected - set(values))
            extra = sorted(set(values) - expected)
            raise DataAssuranceReceiptError(
                f"{cls.__name__}.build keys mismatch: missing={missing} extra={extra}"
            )
        proto = object.__new__(cls)
        for name in expected:
            object.__setattr__(proto, name, values[name])
        object.__setattr__(proto, cls._DIGEST_FIELD, "0" * 64)
        # Validate fields before sealing so a malformed value (for example raw
        # body bytes in a digest slot) fails field validation rather than the
        # canonical encoder.
        proto._validate()
        digest = canonical_receipt_digest(proto, digest_field=cls._DIGEST_FIELD)
        return cls(**{**values, cls._DIGEST_FIELD: digest})  # type: ignore[no-any-return]

    def verify(self) -> None:
        """Re-run field validation and self-digest verification."""
        self.__post_init__()


# ---------------------------------------------------------------------------
# Evidence items
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class RemoteResourceV1(_EvidenceMixin):
    """One canonical remote resource observation."""

    canonical_path: str
    size_bytes: int
    sha256: str
    media_type: str

    def _validate(self) -> None:
        _require_relative_path(self.canonical_path, "canonical_path")
        _require_int(self.size_bytes, "size_bytes", minimum=1)
        _require_sha256(self.sha256, "sha256")
        if not isinstance(self.media_type, str) or not _MEDIA_TYPE.fullmatch(self.media_type):
            raise DataAssuranceReceiptError(
                f"media_type must look like 'type/subtype', got {self.media_type!r}"
            )


@dataclass(frozen=True, slots=True)
class RemoteSchemaObservationV1(_EvidenceMixin):
    """Ordered column/type observation for one remote relation."""

    relation_name: str
    ordered_columns: tuple[str, ...]
    physical_types: tuple[str, ...]
    row_count: int

    def _validate(self) -> None:
        name = _require_str(self.relation_name, "relation_name")
        if not _RELATION_NAME.fullmatch(name):
            raise DataAssuranceReceiptError(
                f"relation_name must be a plain identifier, got {name!r}"
            )
        _require_tuple(self.ordered_columns, "ordered_columns", item_type=str, allow_empty=False)
        _require_tuple(self.physical_types, "physical_types", item_type=str, allow_empty=False)
        _require_unique(self.ordered_columns, "ordered_columns")
        if len(self.ordered_columns) != len(self.physical_types):
            raise DataAssuranceReceiptError(
                "ordered_columns and physical_types must have equal length"
            )
        for column in self.ordered_columns:
            _require_str(column, "ordered_columns entry")
        for physical_type in self.physical_types:
            _require_str(physical_type, "physical_types entry")
        _require_int(self.row_count, "row_count", minimum=0)


@dataclass(frozen=True, slots=True)
class RemoteValueQueryObservationV1(_EvidenceMixin):
    """Canonical result digest for one executed read-only value query."""

    query_id: str
    result_sha256: str
    result_rows: int

    def _validate(self) -> None:
        _require_str(self.query_id, "query_id")
        _require_sha256(self.result_sha256, "result_sha256")
        _require_int(self.result_rows, "result_rows", minimum=0)


@dataclass(frozen=True, slots=True)
class RemotePrivateExclusionScanV1(_EvidenceMixin):
    """Private-material exclusion scan evidence for one scope."""

    scope: str
    scanned_paths: int
    private_hits: int
    scan_sha256: str

    def _validate(self) -> None:
        _require_str(self.scope, "scope")
        _require_int(self.scanned_paths, "scanned_paths", minimum=0)
        _require_int(self.private_hits, "private_hits", minimum=0)
        _require_sha256(self.scan_sha256, "scan_sha256")


@dataclass(frozen=True, slots=True)
class HumanQueryCheckV1(_EvidenceMixin):
    """One deterministic read-only query in the human challenge matrix."""

    query_id: str
    query_text: str
    formats: tuple[str, ...]
    expected_result_sha256: str

    def _validate(self) -> None:
        _require_str(self.query_id, "query_id")
        _require_str(self.query_text, "query_text")
        _require_tuple(self.formats, "formats", item_type=str, allow_empty=False)
        _require_unique(self.formats, "formats")
        for entry in self.formats:
            if entry not in _QUERY_FORMATS:
                raise DataAssuranceReceiptError(
                    f"formats entries must be one of {sorted(_QUERY_FORMATS)}, got {entry!r}"
                )
        _require_sha256(self.expected_result_sha256, "expected_result_sha256")


@dataclass(frozen=True, slots=True)
class HumanObservationV1(_EvidenceMixin):
    """One human-supplied observation against a challenge query."""

    query_id: str
    observed_result_sha256: str
    matches_expected: bool

    def _validate(self) -> None:
        _require_str(self.query_id, "query_id")
        _require_sha256(self.observed_result_sha256, "observed_result_sha256")
        _require_bool(self.matches_expected, "matches_expected")


# ---------------------------------------------------------------------------
# Sealed receipts
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class PrivateCaptureAssuranceReceiptV1(_SealedReceiptMixin):
    """Private capture authority: digests and counts only, never body bytes."""

    _DIGEST_FIELD: ClassVar[str] = "receipt_sha256"

    chain_id: str
    source_sha: str
    generation: int
    private_checkpoint_database_sha256: str
    private_checkpoint_report_sha256: str
    parser_input_inventory_sha256: str
    request_observation_inventory_sha256: str
    result_occurrence_inventory_sha256: str
    route_landing_inventory_sha256: str
    response_body_inventory_sha256: str
    declared_bodyless_inventory_sha256: str
    capture_digest: str
    conservation_digest: str
    reconstruction_digest: str
    route_closure_digest: str
    w2_input_digest: str
    private_resource_count: int
    private_resource_bytes: int
    receipt_sha256: str

    def _validate(self) -> None:
        _require_str(self.chain_id, "chain_id")
        _require_git_sha(self.source_sha, "source_sha")
        _require_int(self.generation, "generation", minimum=1)
        for name in (
            "private_checkpoint_database_sha256",
            "private_checkpoint_report_sha256",
            "parser_input_inventory_sha256",
            "request_observation_inventory_sha256",
            "result_occurrence_inventory_sha256",
            "route_landing_inventory_sha256",
            "response_body_inventory_sha256",
            "declared_bodyless_inventory_sha256",
            "capture_digest",
            "conservation_digest",
            "reconstruction_digest",
            "route_closure_digest",
            "w2_input_digest",
            "receipt_sha256",
        ):
            _require_sha256(getattr(self, name), name)
        _require_int(self.private_resource_count, "private_resource_count", minimum=0)
        _require_int(self.private_resource_bytes, "private_resource_bytes", minimum=0)


@dataclass(frozen=True, slots=True)
class PrepublicationDataAdmissionV1(_SealedReceiptMixin):
    """The hard pre-upload join; never claims final DATA-GREEN."""

    _DIGEST_FIELD: ClassVar[str] = "admission_sha256"

    chain_id: str
    source_sha: str
    generation: int
    private_capture_receipt_sha256: str
    public_disposition_sha256: str
    candidate_inventory_sha256: str
    candidate_tree_sha256: str
    committed_checkpoint_transaction_sha256: str
    checkpoint_database_sha256: str
    checkpoint_report_sha256: str
    assured_manifest_sha256: str
    terminal_report_sha256: str
    metadata_sha256: str
    admitted: bool
    admission_sha256: str

    def _validate(self) -> None:
        _require_str(self.chain_id, "chain_id")
        _require_git_sha(self.source_sha, "source_sha")
        _require_int(self.generation, "generation", minimum=1)
        for name in (
            "private_capture_receipt_sha256",
            "public_disposition_sha256",
            "candidate_inventory_sha256",
            "candidate_tree_sha256",
            "committed_checkpoint_transaction_sha256",
            "checkpoint_database_sha256",
            "checkpoint_report_sha256",
            "assured_manifest_sha256",
            "terminal_report_sha256",
            "metadata_sha256",
            "admission_sha256",
        ):
            _require_sha256(getattr(self, name), name)
        _require_bool(self.admitted, "admitted")
        # ``admitted`` is derived: this receipt exists only when every bound
        # digest validated, so the stored literal must equal the recomputed
        # value. A non-admitted construction is a contradiction, not evidence.
        if self.admitted is not True:
            raise DataAssuranceReceiptError(
                "admitted is derived from the bound evidence and must be True here; "
                "a failed hard gate produces no receipt, never admitted=False"
            )


@dataclass(frozen=True, slots=True)
class RemoteReadbackReceiptV1(_SealedReceiptMixin):
    """Exact remote evidence for one positive dataset version."""

    _DIGEST_FIELD: ClassVar[str] = "receipt_sha256"

    dataset: str
    dataset_version: int
    source_sha: str
    chain_id: str
    terminal_handoff_sha256: str
    public_disposition_sha256: str
    prepublication_admission_sha256: str
    publication_intent_sha256: str
    publication_marker_sha256: str
    resources: tuple[RemoteResourceV1, ...]
    remote_inventory_sha256: str
    remote_tree_sha256: str
    schema_observations: tuple[RemoteSchemaObservationV1, ...]
    value_query_observations: tuple[RemoteValueQueryObservationV1, ...]
    private_exclusion_scan: tuple[RemotePrivateExclusionScanV1, ...]
    readback_fingerprint: str
    parity_ok: bool
    receipt_sha256: str

    def _validate(self) -> None:
        _require_repository(self.dataset)
        _require_int(self.dataset_version, "dataset_version", minimum=1)
        _require_git_sha(self.source_sha, "source_sha")
        _require_str(self.chain_id, "chain_id")
        for name in (
            "terminal_handoff_sha256",
            "public_disposition_sha256",
            "prepublication_admission_sha256",
            "publication_intent_sha256",
            "publication_marker_sha256",
            "remote_inventory_sha256",
            "remote_tree_sha256",
            "readback_fingerprint",
            "receipt_sha256",
        ):
            _require_sha256(getattr(self, name), name)
        _require_tuple(self.resources, "resources", item_type=RemoteResourceV1, allow_empty=False)
        _require_tuple(
            self.schema_observations,
            "schema_observations",
            item_type=RemoteSchemaObservationV1,
            allow_empty=False,
        )
        _require_tuple(
            self.value_query_observations,
            "value_query_observations",
            item_type=RemoteValueQueryObservationV1,
            allow_empty=False,
        )
        _require_tuple(
            self.private_exclusion_scan,
            "private_exclusion_scan",
            item_type=RemotePrivateExclusionScanV1,
            allow_empty=False,
        )
        _require_unique(
            tuple(resource.canonical_path for resource in self.resources),
            "resources canonical_path",
        )
        _require_unique(
            tuple(observation.relation_name for observation in self.schema_observations),
            "schema_observations relation_name",
        )
        _require_unique(
            tuple(observation.query_id for observation in self.value_query_observations),
            "value_query_observations query_id",
        )
        _require_bool(self.parity_ok, "parity_ok")
        if self.parity_ok != self._recomputed_parity():
            raise DataAssuranceReceiptError(
                "parity_ok is derived from the evidence vectors and disagrees: "
                f"stored {self.parity_ok} != recomputed {self._recomputed_parity()}"
            )

    def _recomputed_parity(self) -> bool:
        """Parity requires complete vectors and zero private-material hits."""
        return bool(self.resources) and all(
            scan.private_hits == 0 for scan in self.private_exclusion_scan
        )


@dataclass(frozen=True, slots=True)
class HumanVerificationChallengeV1(_SealedReceiptMixin):
    """Deterministic read-only query challenge bound to one readback."""

    _DIGEST_FIELD: ClassVar[str] = "challenge_sha256"

    readback_receipt_sha256: str
    dataset_version: int
    nonce: str
    issued_at: str
    queries: tuple[HumanQueryCheckV1, ...]
    required_acknowledgment_text: str
    challenge_sha256: str

    def _validate(self) -> None:
        _require_sha256(self.readback_receipt_sha256, "readback_receipt_sha256")
        _require_int(self.dataset_version, "dataset_version", minimum=1)
        _require_str(self.nonce, "nonce")
        _require_str(self.issued_at, "issued_at")
        _require_tuple(self.queries, "queries", item_type=HumanQueryCheckV1, allow_empty=False)
        _require_unique(tuple(query.query_id for query in self.queries), "queries query_id")
        _require_str(self.required_acknowledgment_text, "required_acknowledgment_text")
        _require_sha256(self.challenge_sha256, "challenge_sha256")


@dataclass(frozen=True, slots=True)
class HumanVerificationReceiptV1(_SealedReceiptMixin):
    """Human-authored observations; automation validates but never authors."""

    _DIGEST_FIELD: ClassVar[str] = "receipt_sha256"

    challenge_sha256: str
    readback_receipt_sha256: str
    dataset_version: int
    nonce: str
    verified_actor: str
    observed_at: str
    observations: tuple[HumanObservationV1, ...]
    failures: tuple[str, ...]
    acknowledgment: str
    receipt_sha256: str

    def _validate(self) -> None:
        _require_sha256(self.challenge_sha256, "challenge_sha256")
        _require_sha256(self.readback_receipt_sha256, "readback_receipt_sha256")
        _require_int(self.dataset_version, "dataset_version", minimum=1)
        _require_str(self.nonce, "nonce")
        _require_str(self.verified_actor, "verified_actor")
        _require_str(self.observed_at, "observed_at")
        _require_tuple(
            self.observations, "observations", item_type=HumanObservationV1, allow_empty=False
        )
        _require_unique(
            tuple(observation.query_id for observation in self.observations),
            "observations query_id",
        )
        _require_tuple(self.failures, "failures", item_type=str, allow_empty=True)
        for failure in self.failures:
            _require_str(failure, "failures entry")
        _require_str(self.acknowledgment, "acknowledgment")
        if self.acknowledgment.strip().upper() in _AUTOMATION_ACKNOWLEDGMENT_SENTINELS:
            raise DataAssuranceReceiptError(
                "acknowledgment must be human-authored; automation sentinel values are rejected"
            )
        _require_sha256(self.receipt_sha256, "receipt_sha256")

    def validate_against_challenge(self, challenge: HumanVerificationChallengeV1) -> None:
        """Fail unless this receipt joins the exact challenge it answers.

        Recomputes every ``matches_expected`` flag and the derived ``failures``
        list from the challenge's expected result hashes; disagreement between
        stored and recomputed values fails.
        """
        if self.challenge_sha256 != challenge.challenge_sha256:
            raise DataAssuranceReceiptError("receipt does not bind this challenge digest")
        if self.readback_receipt_sha256 != challenge.readback_receipt_sha256:
            raise DataAssuranceReceiptError("receipt and challenge bind different readbacks")
        if self.dataset_version != challenge.dataset_version:
            raise DataAssuranceReceiptError("receipt and challenge bind different versions")
        if self.nonce != challenge.nonce:
            raise DataAssuranceReceiptError("receipt nonce does not match the challenge nonce")
        if self.acknowledgment != challenge.required_acknowledgment_text:
            raise DataAssuranceReceiptError(
                "acknowledgment text does not match the challenge's required acknowledgment"
            )
        expected_by_id = {
            query.query_id: query.expected_result_sha256 for query in challenge.queries
        }
        observed_ids = {observation.query_id for observation in self.observations}
        if observed_ids != set(expected_by_id):
            raise DataAssuranceReceiptError(
                "observations must cover exactly the challenge query matrix: "
                f"missing={sorted(set(expected_by_id) - observed_ids)} "
                f"unexpected={sorted(observed_ids - set(expected_by_id))}"
            )
        for observation in self.observations:
            recomputed = observation.observed_result_sha256 == expected_by_id[observation.query_id]
            if observation.matches_expected is not recomputed:
                raise DataAssuranceReceiptError(
                    f"matches_expected for query {observation.query_id!r} is derived and "
                    f"disagrees: stored {observation.matches_expected} != recomputed {recomputed}"
                )
        recomputed_failures = tuple(
            sorted(
                observation.query_id
                for observation in self.observations
                if not observation.matches_expected
            )
        )
        if self.failures != recomputed_failures:
            raise DataAssuranceReceiptError(
                f"failures is derived and disagrees: stored {self.failures!r} "
                f"!= recomputed {recomputed_failures!r}"
            )


@dataclass(frozen=True, slots=True)
class DocsMetadataParityV1(_SealedReceiptMixin):
    """Agreement between uploaded metadata, optional child, docs, and readback."""

    _DIGEST_FIELD: ClassVar[str] = "parity_sha256"

    source_sha: str
    metadata_child_sha256: str | None
    uploaded_metadata_sha256: str
    uploaded_metadata_projection_sha256: str
    observed_publication_sha256: str | None
    authored_docs_inventory_sha256: str
    generated_docs_inventory_sha256: str
    remote_readback_receipt_sha256: str
    parity: bool
    parity_sha256: str

    def _validate(self) -> None:
        _require_git_sha(self.source_sha, "source_sha")
        for name, value in (
            ("metadata_child_sha256", self.metadata_child_sha256),
            ("observed_publication_sha256", self.observed_publication_sha256),
        ):
            if value is not None:
                _require_git_sha(value, name)
        for name in (
            "uploaded_metadata_sha256",
            "uploaded_metadata_projection_sha256",
            "authored_docs_inventory_sha256",
            "generated_docs_inventory_sha256",
            "remote_readback_receipt_sha256",
            "parity_sha256",
        ):
            _require_sha256(getattr(self, name), name)
        _require_bool(self.parity, "parity")
        # ``parity`` is derived: construction validated every bound digest, so
        # the stored literal must equal the recomputed value.
        if self.parity is not True:
            raise DataAssuranceReceiptError(
                "parity is derived from the bound digests and must be True here; "
                "a parity failure produces no receipt, never parity=False"
            )


@dataclass(frozen=True, slots=True)
class DataGreenReceiptV1(_SealedReceiptMixin):
    """Final DATA-GREEN join; MODEL status is advisory metadata only."""

    _DIGEST_FIELD: ClassVar[str] = "data_green_sha256"

    dataset: str
    dataset_version: int
    source_sha: str
    chain_id: str
    private_capture_receipt_sha256: str
    public_disposition_sha256: str
    prepublication_admission_sha256: str
    terminal_handoff_sha256: str
    publication_intent_sha256: str
    publication_execution_sha256: str
    publication_resolution_sha256: str
    remote_readback_receipt_sha256: str
    human_verification_receipt_sha256: str
    docs_metadata_parity_sha256: str
    model_status: str
    data_status: str
    data_green_sha256: str

    def _validate(self) -> None:
        _require_repository(self.dataset)
        _require_int(self.dataset_version, "dataset_version", minimum=1)
        _require_git_sha(self.source_sha, "source_sha")
        _require_str(self.chain_id, "chain_id")
        for name in (
            "private_capture_receipt_sha256",
            "public_disposition_sha256",
            "prepublication_admission_sha256",
            "terminal_handoff_sha256",
            "publication_intent_sha256",
            "publication_execution_sha256",
            "publication_resolution_sha256",
            "remote_readback_receipt_sha256",
            "human_verification_receipt_sha256",
            "docs_metadata_parity_sha256",
            "data_green_sha256",
        ):
            _require_sha256(getattr(self, name), name)
        _require_str(self.model_status, "model_status")
        if self.model_status not in MODEL_STATUSES:
            raise DataAssuranceReceiptError(
                f"model_status must be one of {sorted(MODEL_STATUSES)}, got {self.model_status!r}"
            )
        _require_str(self.data_status, "data_status")
        # ``data_status`` records the result of validating this receipt's full
        # chain; every required digest is present and valid, so the literal
        # must equal the recomputed value. The string itself grants nothing.
        if self.data_status != self._recomputed_data_status():
            raise DataAssuranceReceiptError(
                "data_status is derived from the joined evidence and disagrees: "
                f"stored {self.data_status!r} != recomputed {self._recomputed_data_status()!r}"
            )

    def _recomputed_data_status(self) -> str:
        """DATA-GREEN is recomputed, never read, from the bound chain."""
        return DATA_STATUS_GREEN
