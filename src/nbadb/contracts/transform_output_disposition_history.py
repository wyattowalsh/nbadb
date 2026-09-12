"""Flat bounded history for transform-output disposition envelopes.

This module proves only persisted structural chain integrity.  It never reruns
today's registries for historical generations and exposes no admission,
materialization, or publication decision.  Every historical envelope and its
generation-local staging snapshot is embedded exactly once in an oldest-to-
newest flat sequence.
"""

from __future__ import annotations

import base64
import binascii
import hashlib
from dataclasses import dataclass, replace
from typing import Any, ClassVar, Never, Self, cast

from nbadb.contracts import transform_output_disposition_authority as authority_module
from nbadb.contracts.transform_output_disposition_authority import (
    CurrentTransformOutputDispositionV1,
    TransformOutputCapabilityPolicyV1,
    TransformOutputChangeV1,
    TransformOutputDependencyV1,
    TransformOutputDispositionAuditMetadataV1,
    TransformOutputDispositionAuthorityError,
    TransformOutputEvidenceReferenceV1,
    TransformOutputRemovedTombstoneV1,
    TransformOutputSemanticClaimV1,
    VerifiedTransformOutputDispositionAuthorityEnvelopeV1,
)
from nbadb.contracts.transform_output_disposition_evidence import (
    DispositionEvidenceError,
    TransformOutputDispositionProofPackV1,
    TransformOutputDispositionSourceMemberV1,
    canonical_json_bytes_v1,
    decode_canonical_json_bytes_v1,
    persisted_canonical_json_bytes_v1,
)
from nbadb.contracts.transform_output_disposition_structural import (
    TransformOutputDispositionStructuralError,
    TransformOutputStructuralAuthorityV1,
)
from nbadb.contracts.transform_output_staging_input_authority import (
    RegisteredStagingInputContractInventoryV1,
    StagingInputContractAuthorityError,
)

__all__ = [
    "MAX_TRANSFORM_OUTPUT_DISPOSITION_HISTORY_GENERATIONS_V1",
    "TransformOutputDispositionHistoryChainV1",
    "TransformOutputDispositionHistoryError",
    "TransformOutputDispositionHistoryGenerationV1",
    "TransformOutputDispositionHistoryStagingSnapshotV1",
]

MAX_TRANSFORM_OUTPUT_DISPOSITION_HISTORY_GENERATIONS_V1 = 32

_SCHEMA_VERSION = 1
_CHAIN_KIND = "nbadb_transform_output_disposition_history_chain"
_GENERATION_KIND = "nbadb_transform_output_disposition_history_generation"
_STAGING_SNAPSHOT_KIND = "nbadb_transform_output_disposition_history_staging_snapshot"
_ENVELOPE_MEMBER_PATH_PREFIX = "transform-output-disposition/history"
_MAX_EMBEDDED_STAGING_SNAPSHOT_BYTES = 2 * 1024 * 1024

_STAGING_SNAPSHOT_DOMAIN = b"nbadb:transform-output-disposition:history-staging:v1"
_GENERATION_RECORD_DOMAIN = b"nbadb:transform-output-disposition:history-generation:v1"
_GENERATION_INVENTORY_DOMAIN = b"nbadb:transform-output-disposition:history-inventory:v1"
_CHAIN_DOMAIN = b"nbadb:transform-output-disposition:history-chain:v1"

_STAGING_TOKEN = object()
_GENERATION_TOKEN = object()
_CHAIN_TOKEN = object()

_ENVELOPE_KEYS = frozenset(
    {
        "schema_version",
        "kind",
        "structural_authority",
        "proof_pack",
        "audit_metadata",
        "generation_sequence",
        "prior_envelope_sha256",
        "entries",
        "tombstones",
        "changes",
        "dependencies",
        "structural_output_names",
        "entry_inventory",
        "state_inventory",
        "state_counts",
        "capability_inventory",
        "active_output_names",
        "experimental_output_names",
        "non_executable_output_names",
        "executable_output_names",
        "stable_load_output_names",
        "transform_publication_output_names",
        "chat_ceiling_output_names",
        "tombstone_output_names",
        "dependency_graph",
        "topological_order",
        "structural_count",
        "structural_authority_sha256",
        "star_model_contract_sha256",
        "authored_decision_authority_sha256",
        "source_bundle_sha256",
        "proof_pack_sha256",
        "verifier_source_inventory_sha256",
        "audit_metadata_sha256",
        "output_name_inventory_sha256",
        "table_authority_inventory_sha256",
        "entries_sha256",
        "tombstones_sha256",
        "changes_sha256",
        "dependencies_sha256",
        "entry_inventory_sha256",
        "state_inventory_sha256",
        "capability_inventory_sha256",
        "dependency_graph_sha256",
        "topological_order_sha256",
        "proof_result_sha256",
        "generation_identity_sha256",
        "envelope_sha256",
    }
)


class TransformOutputDispositionHistoryError(ValueError):
    """A persisted disposition-history chain is malformed or inconsistent."""


def _fail(message: str) -> Never:
    raise TransformOutputDispositionHistoryError(message)


def _mapping(value: object, *, label: str) -> dict[str, object]:
    if type(value) is not dict or any(type(key) is not str for key in value):
        _fail(f"{label} must be an exact JSON object")
    return cast("dict[str, object]", value)


def _exact_keys(value: dict[str, object], expected: frozenset[str], *, label: str) -> None:
    if frozenset(value) != expected:
        missing = ",".join(sorted(expected - frozenset(value)))
        unexpected = ",".join(sorted(frozenset(value) - expected))
        _fail(f"{label} fields differ (missing={missing}; unexpected={unexpected})")


def _array(
    value: object,
    *,
    label: str,
    maximum: int,
    allow_empty: bool,
) -> list[object]:
    if type(value) is not list:
        _fail(f"{label} must be an exact JSON array")
    rows = cast("list[object]", value)
    if (not allow_empty and not rows) or len(rows) > maximum:
        _fail(f"{label} count is invalid")
    return rows


def _schema_identity(
    payload: dict[str, object],
    *,
    schema_version: int,
    kind: str,
    label: str,
) -> None:
    if (
        type(payload.get("schema_version")) is not int
        or payload["schema_version"] != schema_version
        or type(payload.get("kind")) is not str
        or payload["kind"] != kind
    ):
        _fail(f"{label} schema identity is invalid")


def _positive_integer(value: object, *, label: str) -> int:
    if type(value) is not int or value <= 0:
        _fail(f"{label} must be a positive exact integer")
    return value


def _sha256(value: object, *, label: str) -> str:
    if (
        type(value) is not str
        or len(value) != 64
        or any(character not in "0123456789abcdef" for character in value)
    ):
        _fail(f"{label} must be a lowercase SHA-256")
    return value


def _optional_sha256(value: object, *, label: str) -> str | None:
    if value is None:
        return None
    return _sha256(value, label=label)


def _domain_sha256(domain: bytes, value: object) -> str:
    digest = hashlib.sha256()
    digest.update(domain)
    digest.update(b"\x00")
    digest.update(canonical_json_bytes_v1(value))
    return digest.hexdigest()


def _canonical_base64(raw: bytes) -> str:
    return base64.b64encode(raw).decode("ascii")


def _decode_canonical_base64(value: object, *, label: str) -> bytes:
    if type(value) is not str:
        _fail(f"{label} must be canonical base64 text")
    try:
        encoded = value.encode("ascii", errors="strict")
        decoded = base64.b64decode(encoded, validate=True)
    except (UnicodeEncodeError, binascii.Error, ValueError) as exc:
        raise TransformOutputDispositionHistoryError(
            f"{label} must be canonical base64 text"
        ) from exc
    if _canonical_base64(decoded) != value:
        _fail(f"{label} is not canonical base64")
    return decoded


def _parse_entry(value: object) -> CurrentTransformOutputDispositionV1:
    payload = _mapping(value, label="historical disposition entry")
    _exact_keys(
        payload,
        frozenset(CurrentTransformOutputDispositionV1.digest_field_names) | {"entry_sha256"},
        label="historical disposition entry",
    )
    _schema_identity(
        payload,
        schema_version=CurrentTransformOutputDispositionV1.schema_version,
        kind=CurrentTransformOutputDispositionV1.kind,
        label="historical disposition entry",
    )
    policy_payload = _mapping(payload["capability_policy"], label="historical capability policy")
    _exact_keys(
        policy_payload,
        frozenset(
            {
                "schema_version",
                "kind",
                "execute",
                "primary_materialize",
                "stable_load",
                "transform_publication",
                "chat_ceiling",
                "policy_sha256",
            }
        ),
        label="historical capability policy",
    )
    _schema_identity(
        policy_payload,
        schema_version=TransformOutputCapabilityPolicyV1.schema_version,
        kind=TransformOutputCapabilityPolicyV1.kind,
        label="historical capability policy",
    )
    policy = TransformOutputCapabilityPolicyV1(
        execute=cast("Any", policy_payload["execute"]),
        primary_materialize=cast("Any", policy_payload["primary_materialize"]),
        stable_load=cast("Any", policy_payload["stable_load"]),
        transform_publication=cast("Any", policy_payload["transform_publication"]),
        chat_ceiling=cast("Any", policy_payload["chat_ceiling"]),
    )
    if policy.to_dict() != policy_payload:
        _fail("historical capability policy is not derived")

    claims: list[TransformOutputSemanticClaimV1] = []
    for item in _array(
        payload["semantic_claims"],
        label="historical semantic claims",
        maximum=65_536,
        allow_empty=False,
    ):
        row = _mapping(item, label="historical semantic claim")
        _exact_keys(
            row,
            frozenset(
                {
                    "schema_version",
                    "kind",
                    "claim_id",
                    "claim_kind",
                    "claim_sha256",
                    "evidence_sha256s",
                }
            ),
            label="historical semantic claim",
        )
        _schema_identity(
            row,
            schema_version=TransformOutputSemanticClaimV1.schema_version,
            kind=TransformOutputSemanticClaimV1.kind,
            label="historical semantic claim",
        )
        evidence_sha256s = _array(
            row["evidence_sha256s"],
            label="historical claim evidence",
            maximum=65_536,
            allow_empty=False,
        )
        claims.append(
            TransformOutputSemanticClaimV1(
                claim_id=cast("Any", row["claim_id"]),
                claim_kind=cast("Any", row["claim_kind"]),
                claim_sha256=cast("Any", row["claim_sha256"]),
                evidence_sha256s=tuple(cast("list[str]", evidence_sha256s)),
            )
        )

    evidence: list[TransformOutputEvidenceReferenceV1] = []
    for item in _array(
        payload["evidence_references"],
        label="historical evidence references",
        maximum=65_536,
        allow_empty=False,
    ):
        row = _mapping(item, label="historical evidence reference")
        _exact_keys(
            row,
            frozenset(
                {
                    "schema_version",
                    "kind",
                    "evidence_class",
                    "reference_id",
                    "evidence_sha256",
                }
            ),
            label="historical evidence reference",
        )
        _schema_identity(
            row,
            schema_version=TransformOutputEvidenceReferenceV1.schema_version,
            kind=TransformOutputEvidenceReferenceV1.kind,
            label="historical evidence reference",
        )
        evidence.append(
            TransformOutputEvidenceReferenceV1(
                evidence_class=cast("Any", row["evidence_class"]),
                reference_id=cast("Any", row["reference_id"]),
                evidence_sha256=cast("Any", row["evidence_sha256"]),
            )
        )

    triggers = _array(
        payload["revalidation_triggers"],
        label="historical revalidation triggers",
        maximum=65_536,
        allow_empty=False,
    )
    entry = CurrentTransformOutputDispositionV1(
        output_name=cast("Any", payload["output_name"]),
        family=cast("Any", payload["family"]),
        table_contract_sha256=cast("Any", payload["table_contract_sha256"]),
        schema_identity_sha256=cast("Any", payload["schema_identity_sha256"]),
        transform_identity_sha256=cast("Any", payload["transform_identity_sha256"]),
        ordered_columns_sha256=cast("Any", payload["ordered_columns_sha256"]),
        dependency_identity_sha256=cast("Any", payload["dependency_identity_sha256"]),
        state=cast("Any", payload["state"]),
        capability_policy=policy,
        semantic_claims=tuple(claims),
        reason_code=cast("Any", payload["reason_code"]),
        evidence_references=tuple(evidence),
        revalidation_triggers=tuple(cast("list[str]", triggers)),
    )
    if entry.to_dict() != payload:
        _fail("historical disposition entry is not derived")
    return entry


def _parse_tombstone(value: object) -> TransformOutputRemovedTombstoneV1:
    payload = _mapping(value, label="historical tombstone")
    _exact_keys(
        payload,
        frozenset(
            {
                "schema_version",
                "kind",
                "output_name",
                "family",
                "last_entry_sha256",
                "removal_change_sha256",
                "first_tombstone_generation_sequence",
                "prior_envelope_sha256",
                "removal_reason_code",
                "removal_evidence_sha256s",
                "tombstone_sha256",
            }
        ),
        label="historical tombstone",
    )
    _schema_identity(
        payload,
        schema_version=TransformOutputRemovedTombstoneV1.schema_version,
        kind=TransformOutputRemovedTombstoneV1.kind,
        label="historical tombstone",
    )
    evidence = _array(
        payload["removal_evidence_sha256s"],
        label="historical tombstone evidence",
        maximum=65_536,
        allow_empty=False,
    )
    tombstone = TransformOutputRemovedTombstoneV1(
        output_name=cast("Any", payload["output_name"]),
        family=cast("Any", payload["family"]),
        last_entry_sha256=cast("Any", payload["last_entry_sha256"]),
        removal_change_sha256=cast("Any", payload["removal_change_sha256"]),
        first_tombstone_generation_sequence=cast(
            "Any", payload["first_tombstone_generation_sequence"]
        ),
        prior_envelope_sha256=cast("Any", payload["prior_envelope_sha256"]),
        removal_reason_code=cast("Any", payload["removal_reason_code"]),
        removal_evidence_sha256s=tuple(cast("list[str]", evidence)),
    )
    if tombstone.to_dict() != payload:
        _fail("historical tombstone is not derived")
    return tombstone


def _parse_change(value: object) -> TransformOutputChangeV1:
    payload = _mapping(value, label="historical change")
    _exact_keys(
        payload,
        frozenset(
            {
                "schema_version",
                "kind",
                "change_kind",
                "output_name",
                "prior_entry_sha256",
                "current_entry_sha256",
                "prior_state",
                "current_state",
                "prior_table_contract_sha256",
                "current_table_contract_sha256",
                "evidence_sha256s",
                "change_sha256",
            }
        ),
        label="historical change",
    )
    _schema_identity(
        payload,
        schema_version=TransformOutputChangeV1.schema_version,
        kind=TransformOutputChangeV1.kind,
        label="historical change",
    )
    evidence = _array(
        payload["evidence_sha256s"],
        label="historical change evidence",
        maximum=65_536,
        allow_empty=False,
    )
    change = TransformOutputChangeV1(
        change_kind=cast("Any", payload["change_kind"]),
        output_name=cast("Any", payload["output_name"]),
        prior_entry_sha256=cast("Any", payload["prior_entry_sha256"]),
        current_entry_sha256=cast("Any", payload["current_entry_sha256"]),
        prior_state=cast("Any", payload["prior_state"]),
        current_state=cast("Any", payload["current_state"]),
        prior_table_contract_sha256=cast("Any", payload["prior_table_contract_sha256"]),
        current_table_contract_sha256=cast("Any", payload["current_table_contract_sha256"]),
        evidence_sha256s=tuple(cast("list[str]", evidence)),
    )
    if change.to_dict() != payload:
        _fail("historical change is not derived")
    return change


def _parse_dependency(value: object) -> TransformOutputDependencyV1:
    payload = _mapping(value, label="historical dependency")
    _exact_keys(
        payload,
        frozenset(
            {
                "schema_version",
                "kind",
                "output_name",
                "ordinal",
                "dependency_id",
                "dependency_kind",
                "dependency_contract_sha256",
                "dependency_sha256",
            }
        ),
        label="historical dependency",
    )
    _schema_identity(
        payload,
        schema_version=TransformOutputDependencyV1.schema_version,
        kind=TransformOutputDependencyV1.kind,
        label="historical dependency",
    )
    dependency = TransformOutputDependencyV1(
        output_name=cast("Any", payload["output_name"]),
        ordinal=cast("Any", payload["ordinal"]),
        dependency_id=cast("Any", payload["dependency_id"]),
        dependency_kind=cast("Any", payload["dependency_kind"]),
        dependency_contract_sha256=cast("Any", payload["dependency_contract_sha256"]),
    )
    if dependency.to_dict() != payload:
        _fail("historical dependency is not derived")
    return dependency


def _parse_envelope_rows(
    payload: dict[str, object],
) -> tuple[
    tuple[CurrentTransformOutputDispositionV1, ...],
    tuple[TransformOutputRemovedTombstoneV1, ...],
    tuple[TransformOutputChangeV1, ...],
    tuple[TransformOutputDependencyV1, ...],
]:
    entries = tuple(
        _parse_entry(item)
        for item in _array(
            payload["entries"], label="historical entries", maximum=65_536, allow_empty=False
        )
    )
    tombstones = tuple(
        _parse_tombstone(item)
        for item in _array(
            payload["tombstones"],
            label="historical tombstones",
            maximum=65_536,
            allow_empty=True,
        )
    )
    changes = tuple(
        _parse_change(item)
        for item in _array(
            payload["changes"], label="historical changes", maximum=65_536, allow_empty=True
        )
    )
    dependencies = tuple(
        _parse_dependency(item)
        for item in _array(
            payload["dependencies"],
            label="historical dependencies",
            maximum=65_536,
            allow_empty=True,
        )
    )
    return entries, tombstones, changes, dependencies


def _reconstruct_historical_envelope(
    raw: bytes,
) -> VerifiedTransformOutputDispositionAuthorityEnvelopeV1:
    decoded = decode_canonical_json_bytes_v1(raw, persisted=True)
    payload = _mapping(decoded, label="historical disposition envelope")
    _exact_keys(payload, _ENVELOPE_KEYS, label="historical disposition envelope")
    _schema_identity(
        payload,
        schema_version=VerifiedTransformOutputDispositionAuthorityEnvelopeV1.schema_version,
        kind=VerifiedTransformOutputDispositionAuthorityEnvelopeV1.kind,
        label="historical disposition envelope",
    )
    structural = TransformOutputStructuralAuthorityV1.from_dict(payload["structural_authority"])
    proof_pack = TransformOutputDispositionProofPackV1.from_dict(payload["proof_pack"])
    audit_metadata = TransformOutputDispositionAuditMetadataV1.from_dict(payload["audit_metadata"])
    generation_sequence = _positive_integer(
        payload["generation_sequence"], label="historical generation sequence"
    )
    prior_envelope_sha256 = _optional_sha256(
        payload["prior_envelope_sha256"], label="historical predecessor envelope SHA-256"
    )
    authored_decision_authority_sha256 = _sha256(
        payload["authored_decision_authority_sha256"],
        label="historical authored-decision authority SHA-256",
    )
    entries, tombstones, changes, dependencies = _parse_envelope_rows(payload)
    envelope = authority_module._construct_verified_envelope(
        token=authority_module._VERIFIED_ENVELOPE_CONSTRUCTION_TOKEN,
        structural_authority=structural,
        proof_pack=proof_pack,
        audit_metadata=audit_metadata,
        entries=entries,
        tombstones=tombstones,
        changes=changes,
        dependencies=dependencies,
        authored_decision_authority_sha256=authored_decision_authority_sha256,
        generation_sequence=generation_sequence,
        prior_envelope_sha256=prior_envelope_sha256,
    )
    if envelope.canonical_bytes() != raw:
        _fail("historical envelope differs from its exact sealed reconstruction")
    return envelope


@dataclass(frozen=True, slots=True, init=False)
class TransformOutputDispositionHistoryStagingSnapshotV1:
    """Typed exact bytes for one generation-local registered-staging snapshot."""

    inventory: RegisteredStagingInputContractInventoryV1
    canonical_bytes_base64: str
    byte_length: int
    content_sha256: str
    semantic_schema_version: int
    semantic_kind: str
    semantic_contract_sha256: str
    structural_output_count: int
    structural_output_inventory_sha256: str
    star_model_contract_sha256: str
    entry_count: int
    entry_inventory_sha256: str
    snapshot_identity_sha256: str

    schema_version: ClassVar[int] = _SCHEMA_VERSION
    kind: ClassVar[str] = _STAGING_SNAPSHOT_KIND

    def __init__(self) -> None:
        raise TypeError(
            "TransformOutputDispositionHistoryStagingSnapshotV1 requires canonical replay"
        )

    @property
    def content_bytes(self) -> bytes:
        return _decode_canonical_base64(self.canonical_bytes_base64, label="staging snapshot bytes")

    def _identity_preimage(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "kind": self.kind,
            "byte_length": self.byte_length,
            "content_sha256": self.content_sha256,
            "semantic_schema_version": self.semantic_schema_version,
            "semantic_kind": self.semantic_kind,
            "semantic_contract_sha256": self.semantic_contract_sha256,
            "structural_output_count": self.structural_output_count,
            "structural_output_inventory_sha256": self.structural_output_inventory_sha256,
            "star_model_contract_sha256": self.star_model_contract_sha256,
            "entry_count": self.entry_count,
            "entry_inventory_sha256": self.entry_inventory_sha256,
        }

    def to_dict(self) -> dict[str, object]:
        return {
            **self._identity_preimage(),
            "canonical_bytes_base64": self.canonical_bytes_base64,
            "snapshot_identity_sha256": self.snapshot_identity_sha256,
        }

    @classmethod
    def from_dict(cls, value: object) -> Self:
        payload = _mapping(value, label="history staging snapshot")
        _exact_keys(
            payload,
            frozenset(
                {
                    "schema_version",
                    "kind",
                    "canonical_bytes_base64",
                    "byte_length",
                    "content_sha256",
                    "semantic_schema_version",
                    "semantic_kind",
                    "semantic_contract_sha256",
                    "structural_output_count",
                    "structural_output_inventory_sha256",
                    "star_model_contract_sha256",
                    "entry_count",
                    "entry_inventory_sha256",
                    "snapshot_identity_sha256",
                }
            ),
            label="history staging snapshot",
        )
        _schema_identity(
            payload,
            schema_version=cls.schema_version,
            kind=cls.kind,
            label="history staging snapshot",
        )
        byte_length = _positive_integer(
            payload["byte_length"], label="history staging snapshot byte length"
        )
        if byte_length > _MAX_EMBEDDED_STAGING_SNAPSHOT_BYTES:
            _fail("history staging snapshot byte length exceeds the maximum")
        if (
            type(payload["semantic_schema_version"]) is not int
            or payload["semantic_schema_version"] <= 0
            or type(payload["semantic_kind"]) is not str
            or not payload["semantic_kind"]
            or type(payload["structural_output_count"]) is not int
            or payload["structural_output_count"] <= 0
            or type(payload["entry_count"]) is not int
            or payload["entry_count"] < 0
        ):
            _fail("history staging snapshot semantic counts or identity have foreign types")
        for field_name in (
            "content_sha256",
            "semantic_contract_sha256",
            "structural_output_inventory_sha256",
            "star_model_contract_sha256",
            "entry_inventory_sha256",
            "snapshot_identity_sha256",
        ):
            _sha256(payload[field_name], label=f"history staging snapshot {field_name}")
        encoded = payload["canonical_bytes_base64"]
        if type(encoded) is str and len(encoded) > 4 * (
            (_MAX_EMBEDDED_STAGING_SNAPSHOT_BYTES + 2) // 3
        ):
            _fail("history staging snapshot base64 exceeds the maximum")
        raw = _decode_canonical_base64(encoded, label="staging snapshot bytes")
        try:
            inventory = RegisteredStagingInputContractInventoryV1.from_historical_canonical_bytes(
                raw
            )
        except (StagingInputContractAuthorityError, DispositionEvidenceError) as exc:
            raise TransformOutputDispositionHistoryError(
                "history staging snapshot is not a typed historical staging authority"
            ) from exc
        snapshot = _construct_staging_snapshot(
            token=_STAGING_TOKEN,
            inventory=inventory,
        )
        if snapshot.to_dict() != payload:
            _fail("history staging snapshot differs from exact reconstruction")
        return cast("Self", snapshot)


def _construct_staging_snapshot(
    *,
    token: object,
    inventory: RegisteredStagingInputContractInventoryV1,
) -> TransformOutputDispositionHistoryStagingSnapshotV1:
    if token is not _STAGING_TOKEN:
        _fail("history staging snapshot construction token is invalid")
    if type(inventory) is not RegisteredStagingInputContractInventoryV1:
        _fail("history staging snapshot inventory has a foreign type")
    raw = inventory.canonical_bytes()
    if type(raw) is not bytes or not raw or len(raw) > _MAX_EMBEDDED_STAGING_SNAPSHOT_BYTES:
        _fail("history staging snapshot bytes are empty, foreign, or oversized")
    if raw.endswith(b"\n"):
        _fail("history staging snapshot must use exact non-persisted canonical bytes")
    try:
        reconstructed = RegisteredStagingInputContractInventoryV1.from_historical_canonical_bytes(
            raw
        )
    except (StagingInputContractAuthorityError, DispositionEvidenceError) as exc:
        raise TransformOutputDispositionHistoryError(
            "history staging snapshot is not a typed historical staging authority"
        ) from exc
    if reconstructed != inventory:
        _fail("history staging snapshot inventory differs from typed reconstruction")
    instance = object.__new__(TransformOutputDispositionHistoryStagingSnapshotV1)
    object.__setattr__(instance, "inventory", reconstructed)
    object.__setattr__(instance, "canonical_bytes_base64", _canonical_base64(raw))
    object.__setattr__(instance, "byte_length", len(raw))
    object.__setattr__(instance, "content_sha256", hashlib.sha256(raw).hexdigest())
    object.__setattr__(instance, "semantic_schema_version", reconstructed.schema_version)
    object.__setattr__(instance, "semantic_kind", reconstructed.kind)
    object.__setattr__(instance, "semantic_contract_sha256", reconstructed.contract_sha256)
    object.__setattr__(instance, "structural_output_count", reconstructed.structural_output_count)
    object.__setattr__(
        instance,
        "structural_output_inventory_sha256",
        reconstructed.structural_output_inventory_sha256,
    )
    object.__setattr__(
        instance,
        "star_model_contract_sha256",
        reconstructed.star_model_contract_sha256,
    )
    object.__setattr__(instance, "entry_count", reconstructed.entry_count)
    object.__setattr__(
        instance,
        "entry_inventory_sha256",
        reconstructed.entry_inventory_sha256,
    )
    object.__setattr__(
        instance,
        "snapshot_identity_sha256",
        _domain_sha256(_STAGING_SNAPSHOT_DOMAIN, instance._identity_preimage()),
    )
    canonical_json_bytes_v1(instance.to_dict())
    return instance


@dataclass(frozen=True, slots=True, init=False)
class TransformOutputDispositionHistoryGenerationV1:
    """One flat, exact historical envelope and generation-local evidence identity."""

    generation_sequence: int
    prior_envelope_sha256: str | None
    envelope_member: TransformOutputDispositionSourceMemberV1
    envelope_sha256: str
    generation_identity_sha256: str
    structural_authority_sha256: str
    authored_decision_authority_sha256: str
    source_bundle_root_sha256: str
    proof_pack_root_sha256: str
    source_member_inventory: tuple[tuple[str, str, str], ...]
    source_member_inventory_root_sha256: str
    staging_snapshot: TransformOutputDispositionHistoryStagingSnapshotV1
    generation_record_sha256: str

    schema_version: ClassVar[int] = _SCHEMA_VERSION
    kind: ClassVar[str] = _GENERATION_KIND

    def __init__(self) -> None:
        raise TypeError("TransformOutputDispositionHistoryGenerationV1 requires canonical replay")

    def _record_preimage(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "kind": self.kind,
            "generation_sequence": self.generation_sequence,
            "prior_envelope_sha256": self.prior_envelope_sha256,
            "envelope_member": self.envelope_member.to_dict(),
            "envelope_sha256": self.envelope_sha256,
            "generation_identity_sha256": self.generation_identity_sha256,
            "structural_authority_sha256": self.structural_authority_sha256,
            "authored_decision_authority_sha256": (self.authored_decision_authority_sha256),
            "source_bundle_root_sha256": self.source_bundle_root_sha256,
            "proof_pack_root_sha256": self.proof_pack_root_sha256,
            "source_member_inventory": [
                {
                    "normalized_path": path,
                    "role": role,
                    "member_sha256": member_sha256,
                }
                for path, role, member_sha256 in self.source_member_inventory
            ],
            "source_member_inventory_root_sha256": (self.source_member_inventory_root_sha256),
            "staging_snapshot": self.staging_snapshot.to_dict(),
        }

    def to_dict(self) -> dict[str, object]:
        return {
            **self._record_preimage(),
            "generation_record_sha256": self.generation_record_sha256,
        }

    @classmethod
    def from_dict(cls, value: object) -> Self:
        payload = _mapping(value, label="history generation")
        _exact_keys(
            payload,
            frozenset(
                {
                    "schema_version",
                    "kind",
                    "generation_sequence",
                    "prior_envelope_sha256",
                    "envelope_member",
                    "envelope_sha256",
                    "generation_identity_sha256",
                    "structural_authority_sha256",
                    "authored_decision_authority_sha256",
                    "source_bundle_root_sha256",
                    "proof_pack_root_sha256",
                    "source_member_inventory",
                    "source_member_inventory_root_sha256",
                    "staging_snapshot",
                    "generation_record_sha256",
                }
            ),
            label="history generation",
        )
        _schema_identity(
            payload,
            schema_version=cls.schema_version,
            kind=cls.kind,
            label="history generation",
        )
        generation_sequence = _positive_integer(
            payload["generation_sequence"], label="history generation sequence"
        )
        _sha256(
            payload["authored_decision_authority_sha256"],
            label="history generation authored-decision authority SHA-256",
        )
        envelope_member = TransformOutputDispositionSourceMemberV1.from_dict(
            payload["envelope_member"]
        )
        staging_snapshot = TransformOutputDispositionHistoryStagingSnapshotV1.from_dict(
            payload["staging_snapshot"]
        )
        generation = _construct_generation(
            token=_GENERATION_TOKEN,
            generation_sequence=generation_sequence,
            envelope_member=envelope_member,
            staging_snapshot=staging_snapshot,
        )
        if generation.to_dict() != payload:
            _fail("history generation differs from exact reconstruction")
        return cast("Self", generation)


def _envelope_member_path(generation_sequence: int) -> str:
    return f"{_ENVELOPE_MEMBER_PATH_PREFIX}/generation-{generation_sequence:06d}-envelope.json"


def _construct_generation(
    *,
    token: object,
    generation_sequence: int,
    envelope_member: TransformOutputDispositionSourceMemberV1,
    staging_snapshot: TransformOutputDispositionHistoryStagingSnapshotV1,
) -> TransformOutputDispositionHistoryGenerationV1:
    if token is not _GENERATION_TOKEN:
        _fail("history generation construction token is invalid")
    generation_sequence = _positive_integer(
        generation_sequence, label="history generation sequence"
    )
    if generation_sequence > MAX_TRANSFORM_OUTPUT_DISPOSITION_HISTORY_GENERATIONS_V1:
        _fail("history generation sequence exceeds the chain maximum")
    if type(envelope_member) is not TransformOutputDispositionSourceMemberV1:
        _fail("history envelope member has a foreign type")
    if (
        envelope_member.normalized_path != _envelope_member_path(generation_sequence)
        or envelope_member.role != "prior_or_initial_history"
        or envelope_member.media_type != "application/json"
        or envelope_member.representation != "embedded_bytes"
    ):
        _fail("history envelope member metadata is invalid")
    if type(staging_snapshot) is not TransformOutputDispositionHistoryStagingSnapshotV1:
        _fail("history staging snapshot has a foreign type")

    envelope = _reconstruct_historical_envelope(envelope_member.content_bytes)
    if envelope.generation_sequence != generation_sequence:
        _fail("history generation sequence differs from embedded envelope")
    inventory = staging_snapshot.inventory
    if (
        inventory.structural_output_names != envelope.structural_output_names
        or inventory.structural_output_count != envelope.structural_count
    ):
        _fail("history staging structural output denominator differs from embedded envelope")
    if inventory.star_model_contract_sha256 != envelope.star_model_contract_sha256:
        _fail("history staging star-model contract differs from embedded envelope")
    staging_contracts = {entry.dependency_id: entry.contract_sha256 for entry in inventory.entries}
    observed_staging_ids: set[str] = set()
    for dependency in envelope.dependencies:
        if dependency.dependency_kind != "staging_input":
            continue
        observed_staging_ids.add(dependency.dependency_id)
        if staging_contracts.get(dependency.dependency_id) != dependency.dependency_contract_sha256:
            _fail("history staging dependency differs from its typed historical authority")
    if observed_staging_ids != set(staging_contracts):
        _fail("history staging dependency denominator differs from its typed authority")
    source_bundle = envelope.proof_pack.source_bundle
    source_inventory = tuple(
        (member.normalized_path, member.role, member.member_sha256)
        for member in source_bundle.members
    )

    instance = object.__new__(TransformOutputDispositionHistoryGenerationV1)
    object.__setattr__(instance, "generation_sequence", generation_sequence)
    object.__setattr__(instance, "prior_envelope_sha256", envelope.prior_envelope_sha256)
    object.__setattr__(instance, "envelope_member", envelope_member)
    object.__setattr__(instance, "envelope_sha256", envelope.envelope_sha256)
    object.__setattr__(instance, "generation_identity_sha256", envelope.generation_identity_sha256)
    object.__setattr__(
        instance, "structural_authority_sha256", envelope.structural_authority_sha256
    )
    object.__setattr__(
        instance,
        "authored_decision_authority_sha256",
        envelope.authored_decision_authority_sha256,
    )
    object.__setattr__(
        instance, "source_bundle_root_sha256", source_bundle.source_bundle_root_sha256
    )
    object.__setattr__(
        instance, "proof_pack_root_sha256", envelope.proof_pack.proof_pack_root_sha256
    )
    object.__setattr__(instance, "source_member_inventory", source_inventory)
    object.__setattr__(
        instance,
        "source_member_inventory_root_sha256",
        source_bundle.member_inventory_root_sha256,
    )
    object.__setattr__(instance, "staging_snapshot", staging_snapshot)
    object.__setattr__(
        instance,
        "generation_record_sha256",
        _domain_sha256(_GENERATION_RECORD_DOMAIN, instance._record_preimage()),
    )
    canonical_json_bytes_v1(instance.to_dict())
    return instance


def _entry_evidence_sha256s(
    entry: CurrentTransformOutputDispositionV1,
) -> tuple[str, ...]:
    return tuple(sorted(item.evidence_sha256 for item in entry.evidence_references))


def _validate_adjacent_change(
    *,
    change: TransformOutputChangeV1,
    expected_kind: str,
    prior: CurrentTransformOutputDispositionV1 | None,
    current: CurrentTransformOutputDispositionV1 | None,
) -> None:
    expected = (
        expected_kind,
        None if prior is None else prior.entry_sha256,
        None if current is None else current.entry_sha256,
        None if prior is None else prior.state,
        None if current is None else current.state,
        None if prior is None else prior.table_contract_sha256,
        None if current is None else current.table_contract_sha256,
    )
    observed = (
        change.change_kind,
        change.prior_entry_sha256,
        change.current_entry_sha256,
        change.prior_state,
        change.current_state,
        change.prior_table_contract_sha256,
        change.current_table_contract_sha256,
    )
    if observed != expected:
        _fail(f"historical change misclassifies the exact difference: {change.output_name}")
    if current is not None and change.evidence_sha256s != _entry_evidence_sha256s(current):
        _fail(f"historical change evidence differs from the current entry: {change.output_name}")


def _validate_adjacent_evolution(
    *,
    prior: VerifiedTransformOutputDispositionAuthorityEnvelopeV1,
    current: VerifiedTransformOutputDispositionAuthorityEnvelopeV1,
) -> None:
    """Validate one historical transition without consulting current registries."""
    if (
        current.generation_sequence != prior.generation_sequence + 1
        or current.prior_envelope_sha256 != prior.envelope_sha256
    ):
        _fail("historical evolution does not bind its exact immediate predecessor")

    prior_by_name = {entry.output_name: entry for entry in prior.entries}
    current_by_name = {entry.output_name: entry for entry in current.entries}
    prior_tombstone_by_name = {item.output_name: item for item in prior.tombstones}
    current_tombstone_by_name = {item.output_name: item for item in current.tombstones}
    change_by_name = {item.output_name: item for item in current.changes}

    if len(change_by_name) != len(current.changes):
        _fail("historical evolution contains duplicate changes for one output")
    if set(current_by_name) & set(prior_tombstone_by_name):
        _fail("a permanently tombstoned historical output name reappears")
    for output_name, prior_tombstone in prior_tombstone_by_name.items():
        if current_tombstone_by_name.get(output_name) != prior_tombstone:
            _fail("a historical tombstone was deleted or mutated")

    expected_changed_names: set[str] = set()
    for output_name in sorted(set(prior_by_name) | set(current_by_name)):
        prior_entry = prior_by_name.get(output_name)
        current_entry = current_by_name.get(output_name)
        if prior_entry is None:
            expected_kind = "structural_addition"
        elif current_entry is None:
            expected_kind = "removal"
        elif prior_entry.entry_sha256 == current_entry.entry_sha256:
            continue
        elif (
            prior_entry.state != current_entry.state
            and prior_entry.table_contract_sha256 == current_entry.table_contract_sha256
            and replace(
                prior_entry,
                state=current_entry.state,
                capability_policy=current_entry.capability_policy,
            )
            == current_entry
        ):
            expected_kind = "state_transition"
        elif prior_entry.state == current_entry.state:
            expected_kind = "contract_rebind"
        else:
            _fail(f"historical entry combines incompatible state and contract drift: {output_name}")

        expected_changed_names.add(output_name)
        change = change_by_name.get(output_name)
        if change is None:
            _fail(f"historical evolution is missing one exact change row: {output_name}")
        _validate_adjacent_change(
            change=change,
            expected_kind=expected_kind,
            prior=prior_entry,
            current=current_entry,
        )
        if expected_kind == "removal":
            if prior_entry is None:
                raise AssertionError("historical removal requires a prior entry")
            tombstone = current_tombstone_by_name.get(output_name)
            if tombstone is None:
                _fail(f"historical removal has no immutable tombstone: {output_name}")
            if (
                tombstone.family != prior_entry.family
                or tombstone.last_entry_sha256 != prior_entry.entry_sha256
                or tombstone.removal_change_sha256 != change.change_sha256
                or tombstone.first_tombstone_generation_sequence != current.generation_sequence
                or tombstone.prior_envelope_sha256 != prior.envelope_sha256
                or tombstone.removal_evidence_sha256s != change.evidence_sha256s
            ):
                _fail(f"historical removal tombstone differs from exact evolution: {output_name}")

    if set(change_by_name) != expected_changed_names:
        _fail("historical evolution contains extra or missing change identities")
    new_tombstone_names = set(current_tombstone_by_name) - set(prior_tombstone_by_name)
    removed_names = set(prior_by_name) - set(current_by_name)
    if new_tombstone_names != removed_names:
        _fail("historical tombstone additions differ from exact structural removals")


@dataclass(frozen=True, slots=True, init=False)
class TransformOutputDispositionHistoryChainV1:
    """Complete bounded oldest-to-newest disposition-envelope history."""

    generations: tuple[TransformOutputDispositionHistoryGenerationV1, ...]
    generation_count: int
    initial_generation_sequence: int
    initial_envelope_sha256: str
    terminal_generation_sequence: int
    terminal_envelope_sha256: str
    generation_record_inventory_root_sha256: str
    chain_root_sha256: str

    schema_version: ClassVar[int] = _SCHEMA_VERSION
    kind: ClassVar[str] = _CHAIN_KIND

    def __init__(self) -> None:
        raise TypeError("TransformOutputDispositionHistoryChainV1 requires from_canonical_bytes")

    def _chain_preimage(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "kind": self.kind,
            "generations": [generation.to_dict() for generation in self.generations],
            "generation_count": self.generation_count,
            "initial_generation_sequence": self.initial_generation_sequence,
            "initial_envelope_sha256": self.initial_envelope_sha256,
            "terminal_generation_sequence": self.terminal_generation_sequence,
            "terminal_envelope_sha256": self.terminal_envelope_sha256,
            "generation_record_inventory_root_sha256": (
                self.generation_record_inventory_root_sha256
            ),
        }

    def to_dict(self) -> dict[str, object]:
        return {**self._chain_preimage(), "chain_root_sha256": self.chain_root_sha256}

    def canonical_bytes(self) -> bytes:
        return persisted_canonical_json_bytes_v1(self.to_dict())

    @classmethod
    def from_canonical_bytes(cls, raw: bytes) -> Self:
        if type(raw) is not bytes:
            _fail("history chain input must be exact bytes")
        try:
            decoded = decode_canonical_json_bytes_v1(raw, persisted=True)
            payload = _mapping(decoded, label="history chain")
            _exact_keys(
                payload,
                frozenset(
                    {
                        "schema_version",
                        "kind",
                        "generations",
                        "generation_count",
                        "initial_generation_sequence",
                        "initial_envelope_sha256",
                        "terminal_generation_sequence",
                        "terminal_envelope_sha256",
                        "generation_record_inventory_root_sha256",
                        "chain_root_sha256",
                    }
                ),
                label="history chain",
            )
            _schema_identity(
                payload,
                schema_version=cls.schema_version,
                kind=cls.kind,
                label="history chain",
            )
            rows = _array(
                payload["generations"],
                label="history generations",
                maximum=MAX_TRANSFORM_OUTPUT_DISPOSITION_HISTORY_GENERATIONS_V1,
                allow_empty=False,
            )
            if type(payload["generation_count"]) is not int or payload["generation_count"] != len(
                rows
            ):
                _fail("history generation count is invalid")
            # The exact count gate deliberately precedes any embedded member replay.
            generations = tuple(
                TransformOutputDispositionHistoryGenerationV1.from_dict(row) for row in rows
            )
            chain = _construct_chain(token=_CHAIN_TOKEN, generations=generations)
            if chain.canonical_bytes() != raw:
                _fail("history chain differs from exact canonical reconstruction")
            return cast("Self", chain)
        except TransformOutputDispositionHistoryError:
            raise
        except (
            DispositionEvidenceError,
            StagingInputContractAuthorityError,
            TransformOutputDispositionAuthorityError,
            TransformOutputDispositionStructuralError,
            MemoryError,
            RecursionError,
        ) as exc:
            raise TransformOutputDispositionHistoryError(str(exc)) from exc


def _construct_chain(
    *,
    token: object,
    generations: tuple[TransformOutputDispositionHistoryGenerationV1, ...],
) -> TransformOutputDispositionHistoryChainV1:
    if token is not _CHAIN_TOKEN:
        _fail("history chain construction token is invalid")
    if (
        type(generations) is not tuple
        or not generations
        or len(generations) > MAX_TRANSFORM_OUTPUT_DISPOSITION_HISTORY_GENERATIONS_V1
        or any(
            type(item) is not TransformOutputDispositionHistoryGenerationV1 for item in generations
        )
    ):
        _fail("history generations must be one nonempty bounded typed tuple")

    prior_sha256: str | None = None
    prior_envelope: VerifiedTransformOutputDispositionAuthorityEnvelopeV1 | None = None
    seen_envelopes: set[str] = set()
    seen_records: set[str] = set()
    for expected_sequence, generation in enumerate(generations, start=1):
        if generation.generation_sequence != expected_sequence:
            _fail("history generations are not contiguous oldest-to-newest")
        if generation.prior_envelope_sha256 != prior_sha256:
            _fail("history generation predecessor differs from the immediate envelope")
        if generation.envelope_sha256 in seen_envelopes:
            _fail("history envelope chain contains a duplicate or cycle")
        if generation.generation_record_sha256 in seen_records:
            _fail("history generation record inventory contains a duplicate")
        current_envelope = _reconstruct_historical_envelope(
            generation.envelope_member.content_bytes
        )
        if prior_envelope is not None:
            _validate_adjacent_evolution(prior=prior_envelope, current=current_envelope)
        seen_envelopes.add(generation.envelope_sha256)
        seen_records.add(generation.generation_record_sha256)
        prior_sha256 = generation.envelope_sha256
        prior_envelope = current_envelope

    first = generations[0]
    last = generations[-1]
    inventory_root = _domain_sha256(
        _GENERATION_INVENTORY_DOMAIN,
        [generation.generation_record_sha256 for generation in generations],
    )
    instance = object.__new__(TransformOutputDispositionHistoryChainV1)
    object.__setattr__(instance, "generations", generations)
    object.__setattr__(instance, "generation_count", len(generations))
    object.__setattr__(instance, "initial_generation_sequence", first.generation_sequence)
    object.__setattr__(instance, "initial_envelope_sha256", first.envelope_sha256)
    object.__setattr__(instance, "terminal_generation_sequence", last.generation_sequence)
    object.__setattr__(instance, "terminal_envelope_sha256", last.envelope_sha256)
    object.__setattr__(instance, "generation_record_inventory_root_sha256", inventory_root)
    object.__setattr__(
        instance,
        "chain_root_sha256",
        _domain_sha256(_CHAIN_DOMAIN, instance._chain_preimage()),
    )
    instance.canonical_bytes()
    return instance
