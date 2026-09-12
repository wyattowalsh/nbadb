"""Strict table-local transform-output disposition authority models.

This module defines the primary immutable DTOs only.  It deliberately does not
discover transformers, infer a disposition, or treat an existing semantic
inventory as admission evidence.  The sole public envelope constructor accepts
canonical bytes and delegates to the independent replay verifier.
"""

from __future__ import annotations

import hashlib
import importlib
import json
import re
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, ClassVar, Literal, Self, cast

from nbadb.contracts.transform_output_disposition_evidence import (
    TransformOutputDispositionAuditMetadataV1,
    TransformOutputDispositionProofPackV1,
)
from nbadb.contracts.transform_output_disposition_structural import (
    TransformOutputStructuralAuthorityV1,
)

if TYPE_CHECKING:
    from collections.abc import Mapping

__all__ = [
    "CURRENT_TRANSFORM_OUTPUT_DISPOSITION_KIND",
    "TRANSFORM_OUTPUT_DISPOSITION_AUTHORITY_KIND",
    "TRANSFORM_OUTPUT_DISPOSITION_SCHEMA_VERSION",
    "CurrentTransformOutputDispositionV1",
    "TransformOutputCapabilityPolicyV1",
    "TransformOutputChangeV1",
    "TransformOutputDependencyV1",
    "TransformOutputDispositionAuthorityError",
    "TransformOutputEvidenceReferenceV1",
    "TransformOutputRemovedTombstoneV1",
    "TransformOutputSemanticClaimV1",
    "VerifiedTransformOutputDispositionAuthorityEnvelopeV1",
]

TRANSFORM_OUTPUT_DISPOSITION_SCHEMA_VERSION = 1
CURRENT_TRANSFORM_OUTPUT_DISPOSITION_KIND = "nbadb_current_transform_output_disposition"
TRANSFORM_OUTPUT_DISPOSITION_AUTHORITY_KIND = (
    "nbadb_verified_transform_output_disposition_authority_envelope"
)

type TransformOutputDispositionState = Literal[
    "active",
    "observed_only_experimental",
    "contract_not_modeled",
]
type TransformOutputFamily = Literal["fact", "dim", "bridge", "agg", "analytics"]
type TransformOutputChangeKind = Literal[
    "structural_addition",
    "state_transition",
    "contract_rebind",
    "removal",
]
type TransformOutputDependencyKind = Literal["transform_output", "staging_input"]

_SHA256_RE = re.compile(r"[0-9a-f]{64}\Z", flags=re.ASCII)
_SAFE_ID_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.:@/-]{0,511}\Z", flags=re.ASCII)
_OUTPUT_NAME_RE = re.compile(
    r"(?P<family>fact|dim|bridge|agg|analytics)_[a-z0-9]+(?:_[a-z0-9]+)*\Z",
    flags=re.ASCII,
)
_STAGING_NAME_RE = re.compile(r"stg_[a-z0-9]+(?:_[a-z0-9]+)*\Z", flags=re.ASCII)
_CURRENT_STATES = frozenset({"active", "observed_only_experimental", "contract_not_modeled"})
_FAMILIES = frozenset({"fact", "dim", "bridge", "agg", "analytics"})
_CHANGE_KINDS = frozenset({"structural_addition", "state_transition", "contract_rebind", "removal"})
_DEPENDENCY_KINDS = frozenset({"transform_output", "staging_input"})
_MAX_TUPLE_ITEMS = 65_536
_MAX_ENVELOPE_BYTES = 128 * 1024 * 1024
_VERIFIED_ENVELOPE_CONSTRUCTION_TOKEN = object()

_ENTRY_DIGEST_FIELDS = (
    "schema_version",
    "kind",
    "output_name",
    "family",
    "table_contract_sha256",
    "schema_identity_sha256",
    "transform_identity_sha256",
    "ordered_columns_sha256",
    "dependency_identity_sha256",
    "state",
    "capability_policy",
    "semantic_claims",
    "reason_code",
    "evidence_references",
    "revalidation_triggers",
)


class TransformOutputDispositionAuthorityError(ValueError):
    """A transform-output disposition authority value is invalid."""


def _canonical_json_bytes(value: object) -> bytes:
    try:
        return json.dumps(
            value,
            allow_nan=False,
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        ).encode("utf-8")
    except (TypeError, ValueError, RecursionError) as exc:
        raise TransformOutputDispositionAuthorityError(
            "disposition authority value is not canonical JSON"
        ) from exc


def _sha256_json(value: object) -> str:
    return hashlib.sha256(_canonical_json_bytes(value)).hexdigest()


def _require_sha256(value: object, *, field_name: str) -> str:
    if type(value) is not str or _SHA256_RE.fullmatch(value) is None:
        raise TransformOutputDispositionAuthorityError(f"{field_name} must be a lowercase SHA-256")
    return value


def _require_id(value: object, *, field_name: str) -> str:
    if type(value) is not str or _SAFE_ID_RE.fullmatch(value) is None:
        raise TransformOutputDispositionAuthorityError(
            f"{field_name} must be a safe nonempty identifier"
        )
    return value


def _require_output_name(value: object, *, field_name: str = "output_name") -> str:
    if type(value) is not str or _OUTPUT_NAME_RE.fullmatch(value) is None:
        raise TransformOutputDispositionAuthorityError(
            f"{field_name} must be a normalized transform output name"
        )
    return value


def _require_family(value: object, *, output_name: str) -> TransformOutputFamily:
    if type(value) is not str or value not in _FAMILIES:
        raise TransformOutputDispositionAuthorityError("family is invalid")
    match = _OUTPUT_NAME_RE.fullmatch(output_name)
    if match is None or match.group("family") != value:
        raise TransformOutputDispositionAuthorityError(
            "family must match the normalized output-name prefix"
        )
    return cast("TransformOutputFamily", value)


def _require_exact_tuple(
    value: object,
    *,
    field_name: str,
    allow_empty: bool,
) -> tuple[object, ...]:
    if type(value) is not tuple:
        raise TransformOutputDispositionAuthorityError(f"{field_name} must be an exact tuple")
    values = value
    if (not allow_empty and not values) or len(values) > _MAX_TUPLE_ITEMS:
        raise TransformOutputDispositionAuthorityError(
            f"{field_name} must be nonempty when required and within its bound"
        )
    return values


def _require_sorted_unique_strings(
    value: object,
    *,
    field_name: str,
    allow_empty: bool = False,
) -> tuple[str, ...]:
    values = _require_exact_tuple(value, field_name=field_name, allow_empty=allow_empty)
    result = tuple(_require_id(item, field_name=field_name) for item in values)
    if result != tuple(sorted(set(result))):
        raise TransformOutputDispositionAuthorityError(f"{field_name} must be sorted and unique")
    return result


def _require_mapping(value: object, *, label: str) -> Mapping[str, object]:
    if type(value) is not dict:
        raise TransformOutputDispositionAuthorityError(f"{label} must be an object")
    return cast("Mapping[str, object]", value)


def _require_exact_keys(
    payload: Mapping[str, object],
    *,
    expected: frozenset[str],
    label: str,
) -> None:
    if any(type(key) is not str for key in payload):
        raise TransformOutputDispositionAuthorityError(f"{label} keys must be strings")
    actual = frozenset(payload)
    if actual != expected:
        missing = ",".join(sorted(expected - actual))
        unexpected = ",".join(sorted(actual - expected))
        raise TransformOutputDispositionAuthorityError(
            f"{label} fields differ (missing={missing}; unexpected={unexpected})"
        )


@dataclass(frozen=True, slots=True)
class TransformOutputCapabilityPolicyV1:
    """The complete authored capability policy for one current state."""

    execute: bool
    primary_materialize: bool
    stable_load: bool
    transform_publication: bool
    chat_ceiling: bool
    policy_sha256: str = field(init=False)

    schema_version: ClassVar[int] = TRANSFORM_OUTPUT_DISPOSITION_SCHEMA_VERSION
    kind: ClassVar[str] = "nbadb_transform_output_capability_policy"

    def __post_init__(self) -> None:
        for field_name in (
            "execute",
            "primary_materialize",
            "stable_load",
            "transform_publication",
            "chat_ceiling",
        ):
            if type(getattr(self, field_name)) is not bool:
                raise TransformOutputDispositionAuthorityError(
                    f"capability {field_name} must be an exact boolean"
                )
        object.__setattr__(self, "policy_sha256", _sha256_json(self._digest_preimage()))

    def _digest_preimage(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "kind": self.kind,
            "execute": self.execute,
            "primary_materialize": self.primary_materialize,
            "stable_load": self.stable_load,
            "transform_publication": self.transform_publication,
            "chat_ceiling": self.chat_ceiling,
        }

    def to_dict(self) -> dict[str, object]:
        return {**self._digest_preimage(), "policy_sha256": self.policy_sha256}

    def validate_for_state(self, state: TransformOutputDispositionState) -> None:
        expected = {
            "active": (True, True, True, True, True),
            "observed_only_experimental": (True, True, False, False, False),
            "contract_not_modeled": (False, False, False, False, False),
        }.get(state)
        if expected is None:
            raise TransformOutputDispositionAuthorityError("current disposition state is invalid")
        observed = (
            self.execute,
            self.primary_materialize,
            self.stable_load,
            self.transform_publication,
            self.chat_ceiling,
        )
        if observed != expected:
            raise TransformOutputDispositionAuthorityError(
                "authored capability policy differs from the exact state policy"
            )


@dataclass(frozen=True, slots=True, order=True)
class TransformOutputSemanticClaimV1:
    """One table-local semantic claim and its exact evidence set."""

    claim_id: str
    claim_kind: str
    claim_sha256: str
    evidence_sha256s: tuple[str, ...]

    schema_version: ClassVar[int] = TRANSFORM_OUTPUT_DISPOSITION_SCHEMA_VERSION
    kind: ClassVar[str] = "nbadb_transform_output_semantic_claim"

    def __post_init__(self) -> None:
        _require_id(self.claim_id, field_name="claim_id")
        _require_id(self.claim_kind, field_name="claim_kind")
        _require_sha256(self.claim_sha256, field_name="claim_sha256")
        values = _require_exact_tuple(
            self.evidence_sha256s,
            field_name="semantic claim evidence_sha256s",
            allow_empty=False,
        )
        digests = tuple(
            _require_sha256(item, field_name="semantic claim evidence_sha256s") for item in values
        )
        if digests != tuple(sorted(set(digests))):
            raise TransformOutputDispositionAuthorityError(
                "semantic claim evidence_sha256s must be sorted and unique"
            )

    def to_dict(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "kind": self.kind,
            "claim_id": self.claim_id,
            "claim_kind": self.claim_kind,
            "claim_sha256": self.claim_sha256,
            "evidence_sha256s": list(self.evidence_sha256s),
        }


@dataclass(frozen=True, slots=True, order=True)
class TransformOutputEvidenceReferenceV1:
    """One table-local evidence reference; its class is authored, not inferred."""

    evidence_class: str
    reference_id: str
    evidence_sha256: str

    schema_version: ClassVar[int] = TRANSFORM_OUTPUT_DISPOSITION_SCHEMA_VERSION
    kind: ClassVar[str] = "nbadb_transform_output_evidence_reference"

    def __post_init__(self) -> None:
        _require_id(self.evidence_class, field_name="evidence_class")
        _require_id(self.reference_id, field_name="reference_id")
        _require_sha256(self.evidence_sha256, field_name="evidence_sha256")

    def to_dict(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "kind": self.kind,
            "evidence_class": self.evidence_class,
            "reference_id": self.reference_id,
            "evidence_sha256": self.evidence_sha256,
        }


@dataclass(frozen=True, slots=True)
class CurrentTransformOutputDispositionV1:
    """One strict table-local current disposition; never a global generation DTO."""

    output_name: str
    family: TransformOutputFamily
    table_contract_sha256: str
    schema_identity_sha256: str
    transform_identity_sha256: str
    ordered_columns_sha256: str
    dependency_identity_sha256: str
    state: TransformOutputDispositionState
    capability_policy: TransformOutputCapabilityPolicyV1
    semantic_claims: tuple[TransformOutputSemanticClaimV1, ...]
    reason_code: str
    evidence_references: tuple[TransformOutputEvidenceReferenceV1, ...]
    revalidation_triggers: tuple[str, ...]
    entry_sha256: str = field(init=False)

    schema_version: ClassVar[int] = TRANSFORM_OUTPUT_DISPOSITION_SCHEMA_VERSION
    kind: ClassVar[str] = CURRENT_TRANSFORM_OUTPUT_DISPOSITION_KIND
    digest_field_names: ClassVar[tuple[str, ...]] = _ENTRY_DIGEST_FIELDS

    def __post_init__(self) -> None:
        _require_output_name(self.output_name)
        _require_family(self.family, output_name=self.output_name)
        for field_name in (
            "table_contract_sha256",
            "schema_identity_sha256",
            "transform_identity_sha256",
            "ordered_columns_sha256",
            "dependency_identity_sha256",
        ):
            _require_sha256(getattr(self, field_name), field_name=field_name)
        if type(self.state) is not str or self.state not in _CURRENT_STATES:
            raise TransformOutputDispositionAuthorityError(
                "current state must be active, observed_only_experimental, or contract_not_modeled"
            )
        if not isinstance(self.capability_policy, TransformOutputCapabilityPolicyV1):
            raise TransformOutputDispositionAuthorityError(
                "capability_policy must be TransformOutputCapabilityPolicyV1"
            )
        self.capability_policy.validate_for_state(self.state)
        claims_raw = _require_exact_tuple(
            self.semantic_claims,
            field_name="semantic_claims",
            allow_empty=False,
        )
        if any(not isinstance(item, TransformOutputSemanticClaimV1) for item in claims_raw):
            raise TransformOutputDispositionAuthorityError(
                "semantic_claims must contain only TransformOutputSemanticClaimV1"
            )
        claims = cast("tuple[TransformOutputSemanticClaimV1, ...]", claims_raw)
        if claims != tuple(sorted(set(claims))):
            raise TransformOutputDispositionAuthorityError(
                "semantic_claims must be sorted and unique"
            )
        _require_id(self.reason_code, field_name="reason_code")
        evidence_raw = _require_exact_tuple(
            self.evidence_references,
            field_name="evidence_references",
            allow_empty=False,
        )
        if any(not isinstance(item, TransformOutputEvidenceReferenceV1) for item in evidence_raw):
            raise TransformOutputDispositionAuthorityError(
                "evidence_references must contain only TransformOutputEvidenceReferenceV1"
            )
        evidence = cast("tuple[TransformOutputEvidenceReferenceV1, ...]", evidence_raw)
        if evidence != tuple(sorted(set(evidence))):
            raise TransformOutputDispositionAuthorityError(
                "evidence_references must be sorted and unique"
            )
        _require_sorted_unique_strings(
            self.revalidation_triggers,
            field_name="revalidation_triggers",
        )
        object.__setattr__(self, "entry_sha256", _sha256_json(self._digest_preimage()))

    def _digest_preimage(self) -> dict[str, object]:
        payload: dict[str, object] = {
            "schema_version": self.schema_version,
            "kind": self.kind,
            "output_name": self.output_name,
            "family": self.family,
            "table_contract_sha256": self.table_contract_sha256,
            "schema_identity_sha256": self.schema_identity_sha256,
            "transform_identity_sha256": self.transform_identity_sha256,
            "ordered_columns_sha256": self.ordered_columns_sha256,
            "dependency_identity_sha256": self.dependency_identity_sha256,
            "state": self.state,
            "capability_policy": self.capability_policy.to_dict(),
            "semantic_claims": [item.to_dict() for item in self.semantic_claims],
            "reason_code": self.reason_code,
            "evidence_references": [item.to_dict() for item in self.evidence_references],
            "revalidation_triggers": list(self.revalidation_triggers),
        }
        if tuple(payload) != _ENTRY_DIGEST_FIELDS:
            raise AssertionError("entry digest preimage differs from its literal allowlist")
        return payload

    def to_dict(self) -> dict[str, object]:
        return {**self._digest_preimage(), "entry_sha256": self.entry_sha256}

    def canonical_bytes(self) -> bytes:
        return _canonical_json_bytes(self.to_dict())


@dataclass(frozen=True, slots=True, order=True)
class TransformOutputRemovedTombstoneV1:
    """Immutable historical reservation for one removed normalized output name."""

    output_name: str
    family: TransformOutputFamily
    last_entry_sha256: str
    removal_change_sha256: str
    first_tombstone_generation_sequence: int
    prior_envelope_sha256: str
    removal_reason_code: str
    removal_evidence_sha256s: tuple[str, ...]
    tombstone_sha256: str = field(init=False, compare=True)

    schema_version: ClassVar[int] = TRANSFORM_OUTPUT_DISPOSITION_SCHEMA_VERSION
    kind: ClassVar[str] = "nbadb_transform_output_removed_tombstone"

    def __post_init__(self) -> None:
        _require_output_name(self.output_name)
        _require_family(self.family, output_name=self.output_name)
        _require_sha256(self.last_entry_sha256, field_name="last_entry_sha256")
        _require_sha256(self.removal_change_sha256, field_name="removal_change_sha256")
        if (
            type(self.first_tombstone_generation_sequence) is not int
            or self.first_tombstone_generation_sequence < 2
        ):
            raise TransformOutputDispositionAuthorityError(
                "first_tombstone_generation_sequence must identify a noninitial generation"
            )
        _require_sha256(self.prior_envelope_sha256, field_name="prior_envelope_sha256")
        _require_id(self.removal_reason_code, field_name="removal_reason_code")
        values = _require_exact_tuple(
            self.removal_evidence_sha256s,
            field_name="removal_evidence_sha256s",
            allow_empty=False,
        )
        digests = tuple(
            _require_sha256(item, field_name="removal_evidence_sha256s") for item in values
        )
        if digests != tuple(sorted(set(digests))):
            raise TransformOutputDispositionAuthorityError(
                "removal_evidence_sha256s must be sorted and unique"
            )
        object.__setattr__(self, "tombstone_sha256", _sha256_json(self._digest_preimage()))

    def _digest_preimage(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "kind": self.kind,
            "output_name": self.output_name,
            "family": self.family,
            "last_entry_sha256": self.last_entry_sha256,
            "removal_change_sha256": self.removal_change_sha256,
            "first_tombstone_generation_sequence": (self.first_tombstone_generation_sequence),
            "prior_envelope_sha256": self.prior_envelope_sha256,
            "removal_reason_code": self.removal_reason_code,
            "removal_evidence_sha256s": list(self.removal_evidence_sha256s),
        }

    def to_dict(self) -> dict[str, object]:
        return {**self._digest_preimage(), "tombstone_sha256": self.tombstone_sha256}


@dataclass(frozen=True, slots=True, order=True)
class TransformOutputChangeV1:
    """One external current/prior difference classification."""

    change_kind: TransformOutputChangeKind
    output_name: str
    prior_entry_sha256: str | None
    current_entry_sha256: str | None
    prior_state: TransformOutputDispositionState | None
    current_state: TransformOutputDispositionState | None
    prior_table_contract_sha256: str | None
    current_table_contract_sha256: str | None
    evidence_sha256s: tuple[str, ...]
    change_sha256: str = field(init=False, compare=True)

    schema_version: ClassVar[int] = TRANSFORM_OUTPUT_DISPOSITION_SCHEMA_VERSION
    kind: ClassVar[str] = "nbadb_transform_output_disposition_change"

    def __post_init__(self) -> None:
        if type(self.change_kind) is not str or self.change_kind not in _CHANGE_KINDS:
            raise TransformOutputDispositionAuthorityError("change_kind is invalid")
        _require_output_name(self.output_name)
        prior = self.prior_entry_sha256
        current = self.current_entry_sha256
        if prior is not None:
            _require_sha256(prior, field_name="prior_entry_sha256")
        if current is not None:
            _require_sha256(current, field_name="current_entry_sha256")
        prior_state = self.prior_state
        current_state = self.current_state
        for field_name, state in (
            ("prior_state", prior_state),
            ("current_state", current_state),
        ):
            if state is not None and (type(state) is not str or state not in _CURRENT_STATES):
                raise TransformOutputDispositionAuthorityError(f"{field_name} is invalid")
        prior_contract = self.prior_table_contract_sha256
        current_contract = self.current_table_contract_sha256
        if prior_contract is not None:
            _require_sha256(prior_contract, field_name="prior_table_contract_sha256")
        if current_contract is not None:
            _require_sha256(current_contract, field_name="current_table_contract_sha256")
        if self.change_kind == "structural_addition":
            valid = (
                prior is None
                and current is not None
                and prior_state is None
                and current_state is not None
                and prior_contract is None
                and current_contract is not None
            )
        elif self.change_kind == "removal":
            valid = (
                prior is not None
                and current is None
                and prior_state is not None
                and current_state is None
                and prior_contract is not None
                and current_contract is None
            )
        elif self.change_kind == "state_transition":
            valid = (
                prior is not None
                and current is not None
                and prior != current
                and prior_state is not None
                and current_state is not None
                and prior_state != current_state
                and prior_contract is not None
                and prior_contract == current_contract
            )
        else:
            valid = (
                prior is not None
                and current is not None
                and prior != current
                and prior_state is not None
                and current_state is not None
                and prior_state == current_state
                and prior_contract is not None
                and current_contract is not None
            )
        if not valid:
            raise TransformOutputDispositionAuthorityError(
                "change entry digests are incompatible with change_kind"
            )
        values = _require_exact_tuple(
            self.evidence_sha256s,
            field_name="change evidence_sha256s",
            allow_empty=False,
        )
        digests = tuple(
            _require_sha256(item, field_name="change evidence_sha256s") for item in values
        )
        if digests != tuple(sorted(set(digests))):
            raise TransformOutputDispositionAuthorityError(
                "change evidence_sha256s must be sorted and unique"
            )
        object.__setattr__(self, "change_sha256", _sha256_json(self._digest_preimage()))

    def _digest_preimage(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "kind": self.kind,
            "change_kind": self.change_kind,
            "output_name": self.output_name,
            "prior_entry_sha256": self.prior_entry_sha256,
            "current_entry_sha256": self.current_entry_sha256,
            "prior_state": self.prior_state,
            "current_state": self.current_state,
            "prior_table_contract_sha256": self.prior_table_contract_sha256,
            "current_table_contract_sha256": self.current_table_contract_sha256,
            "evidence_sha256s": list(self.evidence_sha256s),
        }

    def to_dict(self) -> dict[str, object]:
        return {**self._digest_preimage(), "change_sha256": self.change_sha256}


@dataclass(frozen=True, slots=True, order=True)
class TransformOutputDependencyV1:
    """One exact ordered table-local transform or staging dependency edge."""

    output_name: str
    ordinal: int
    dependency_id: str
    dependency_kind: TransformOutputDependencyKind
    dependency_contract_sha256: str
    dependency_sha256: str = field(init=False, compare=True)

    schema_version: ClassVar[int] = TRANSFORM_OUTPUT_DISPOSITION_SCHEMA_VERSION
    kind: ClassVar[str] = "nbadb_transform_output_dependency"

    def __post_init__(self) -> None:
        _require_output_name(self.output_name)
        if type(self.ordinal) is not int or not 0 <= self.ordinal <= _MAX_TUPLE_ITEMS:
            raise TransformOutputDispositionAuthorityError(
                "dependency ordinal must be a bounded nonnegative integer"
            )
        if type(self.dependency_kind) is not str or self.dependency_kind not in _DEPENDENCY_KINDS:
            raise TransformOutputDispositionAuthorityError("dependency_kind is invalid")
        if self.dependency_kind == "transform_output":
            _require_output_name(self.dependency_id, field_name="dependency_id")
            if self.dependency_id == self.output_name:
                raise TransformOutputDispositionAuthorityError(
                    "transform output cannot depend on itself"
                )
        elif (
            type(self.dependency_id) is not str
            or _STAGING_NAME_RE.fullmatch(self.dependency_id) is None
        ):
            raise TransformOutputDispositionAuthorityError(
                "staging dependency_id must be a normalized staging name"
            )
        _require_sha256(
            self.dependency_contract_sha256,
            field_name="dependency_contract_sha256",
        )
        object.__setattr__(self, "dependency_sha256", _sha256_json(self._digest_preimage()))

    def _digest_preimage(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "kind": self.kind,
            "output_name": self.output_name,
            "ordinal": self.ordinal,
            "dependency_id": self.dependency_id,
            "dependency_kind": self.dependency_kind,
            "dependency_contract_sha256": self.dependency_contract_sha256,
        }

    def to_dict(self) -> dict[str, object]:
        return {**self._digest_preimage(), "dependency_sha256": self.dependency_sha256}


@dataclass(frozen=True, slots=True, init=False)
class VerifiedTransformOutputDispositionAuthorityEnvelopeV1:
    """Sealed authority constructed only after independent raw-byte replay."""

    structural_authority: TransformOutputStructuralAuthorityV1
    proof_pack: TransformOutputDispositionProofPackV1
    audit_metadata: TransformOutputDispositionAuditMetadataV1
    generation_sequence: int
    prior_envelope_sha256: str | None
    entries: tuple[CurrentTransformOutputDispositionV1, ...]
    tombstones: tuple[TransformOutputRemovedTombstoneV1, ...]
    changes: tuple[TransformOutputChangeV1, ...]
    dependencies: tuple[TransformOutputDependencyV1, ...]
    structural_output_names: tuple[str, ...]
    entry_inventory: tuple[tuple[str, str], ...]
    state_inventory: tuple[tuple[str, TransformOutputDispositionState], ...]
    state_counts: tuple[tuple[TransformOutputDispositionState, int], ...]
    capability_inventory: tuple[tuple[str, str], ...]
    active_output_names: tuple[str, ...]
    experimental_output_names: tuple[str, ...]
    non_executable_output_names: tuple[str, ...]
    executable_output_names: tuple[str, ...]
    stable_load_output_names: tuple[str, ...]
    transform_publication_output_names: tuple[str, ...]
    chat_ceiling_output_names: tuple[str, ...]
    tombstone_output_names: tuple[str, ...]
    dependency_graph: tuple[tuple[str, tuple[str, ...]], ...]
    topological_order: tuple[str, ...]
    structural_count: int
    structural_authority_sha256: str
    star_model_contract_sha256: str
    authored_decision_authority_sha256: str
    source_bundle_sha256: str
    proof_pack_sha256: str
    verifier_source_inventory_sha256: str
    audit_metadata_sha256: str
    output_name_inventory_sha256: str
    table_authority_inventory_sha256: str
    entries_sha256: str
    tombstones_sha256: str
    changes_sha256: str
    dependencies_sha256: str
    entry_inventory_sha256: str
    state_inventory_sha256: str
    capability_inventory_sha256: str
    dependency_graph_sha256: str
    topological_order_sha256: str
    proof_result_sha256: str
    generation_identity_sha256: str
    envelope_sha256: str

    schema_version: ClassVar[int] = TRANSFORM_OUTPUT_DISPOSITION_SCHEMA_VERSION
    kind: ClassVar[str] = TRANSFORM_OUTPUT_DISPOSITION_AUTHORITY_KIND

    def __init__(self) -> None:
        raise TypeError(
            "VerifiedTransformOutputDispositionAuthorityEnvelopeV1 must be constructed "
            "with from_canonical_bytes"
        )

    @classmethod
    def from_canonical_bytes(cls, raw: bytes) -> Self:
        """Fresh-replay canonical bytes through the independent verifier."""
        if type(raw) is not bytes or not raw or len(raw) > _MAX_ENVELOPE_BYTES:
            raise TransformOutputDispositionAuthorityError(
                "authority envelope bytes are empty, foreign, or oversized"
            )
        verifier_module = importlib.import_module(
            "nbadb.contracts.transform_output_disposition_verifier"
        )
        verifier = verifier_module.verify_transform_output_disposition_envelope
        result = verifier(raw)
        if not isinstance(result, cls):
            raise TransformOutputDispositionAuthorityError(
                "independent verifier returned a foreign envelope type"
            )
        if result.canonical_bytes() != raw:
            raise TransformOutputDispositionAuthorityError(
                "independent verifier returned an envelope differing from canonical input"
            )
        return result

    def to_dict(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "kind": self.kind,
            "structural_authority": self.structural_authority.to_dict(),
            "proof_pack": self.proof_pack.to_dict(),
            "audit_metadata": self.audit_metadata.to_dict(),
            "generation_sequence": self.generation_sequence,
            "prior_envelope_sha256": self.prior_envelope_sha256,
            "entries": [item.to_dict() for item in self.entries],
            "tombstones": [item.to_dict() for item in self.tombstones],
            "changes": [item.to_dict() for item in self.changes],
            "dependencies": [item.to_dict() for item in self.dependencies],
            "structural_output_names": list(self.structural_output_names),
            "entry_inventory": [
                {"output_name": output_name, "entry_sha256": entry_sha256}
                for output_name, entry_sha256 in self.entry_inventory
            ],
            "state_inventory": [
                {"output_name": output_name, "state": state}
                for output_name, state in self.state_inventory
            ],
            "state_counts": {state: count for state, count in self.state_counts},
            "capability_inventory": [
                {"output_name": output_name, "policy_sha256": policy_sha256}
                for output_name, policy_sha256 in self.capability_inventory
            ],
            "active_output_names": list(self.active_output_names),
            "experimental_output_names": list(self.experimental_output_names),
            "non_executable_output_names": list(self.non_executable_output_names),
            "executable_output_names": list(self.executable_output_names),
            "stable_load_output_names": list(self.stable_load_output_names),
            "transform_publication_output_names": list(self.transform_publication_output_names),
            "chat_ceiling_output_names": list(self.chat_ceiling_output_names),
            "tombstone_output_names": list(self.tombstone_output_names),
            "dependency_graph": [
                {"output_name": output_name, "dependencies": list(dependency_names)}
                for output_name, dependency_names in self.dependency_graph
            ],
            "topological_order": list(self.topological_order),
            "structural_count": self.structural_count,
            "structural_authority_sha256": self.structural_authority_sha256,
            "star_model_contract_sha256": self.star_model_contract_sha256,
            "authored_decision_authority_sha256": self.authored_decision_authority_sha256,
            "source_bundle_sha256": self.source_bundle_sha256,
            "proof_pack_sha256": self.proof_pack_sha256,
            "verifier_source_inventory_sha256": self.verifier_source_inventory_sha256,
            "audit_metadata_sha256": self.audit_metadata_sha256,
            "output_name_inventory_sha256": self.output_name_inventory_sha256,
            "table_authority_inventory_sha256": self.table_authority_inventory_sha256,
            "entries_sha256": self.entries_sha256,
            "tombstones_sha256": self.tombstones_sha256,
            "changes_sha256": self.changes_sha256,
            "dependencies_sha256": self.dependencies_sha256,
            "entry_inventory_sha256": self.entry_inventory_sha256,
            "state_inventory_sha256": self.state_inventory_sha256,
            "capability_inventory_sha256": self.capability_inventory_sha256,
            "dependency_graph_sha256": self.dependency_graph_sha256,
            "topological_order_sha256": self.topological_order_sha256,
            "proof_result_sha256": self.proof_result_sha256,
            "generation_identity_sha256": self.generation_identity_sha256,
            "envelope_sha256": self.envelope_sha256,
        }

    def canonical_bytes(self) -> bytes:
        """Return persisted canonical JSON with exactly one trailing LF."""
        encoded = _canonical_json_bytes(self.to_dict())
        if len(encoded) + 1 > _MAX_ENVELOPE_BYTES:
            raise TransformOutputDispositionAuthorityError(
                "authority envelope exceeds its canonical byte bound"
            )
        return encoded + b"\n"


def _construct_verified_envelope(
    *,
    token: object,
    structural_authority: TransformOutputStructuralAuthorityV1,
    proof_pack: TransformOutputDispositionProofPackV1,
    audit_metadata: TransformOutputDispositionAuditMetadataV1,
    entries: tuple[CurrentTransformOutputDispositionV1, ...],
    tombstones: tuple[TransformOutputRemovedTombstoneV1, ...],
    changes: tuple[TransformOutputChangeV1, ...],
    dependencies: tuple[TransformOutputDependencyV1, ...],
    authored_decision_authority_sha256: str,
    generation_sequence: int,
    prior_envelope_sha256: str | None,
) -> VerifiedTransformOutputDispositionAuthorityEnvelopeV1:
    """Private verifier-only constructor; every derived root is recomputed."""
    if token is not _VERIFIED_ENVELOPE_CONSTRUCTION_TOKEN:
        raise TransformOutputDispositionAuthorityError("verified envelope token is invalid")
    if type(structural_authority) is not TransformOutputStructuralAuthorityV1:
        raise TransformOutputDispositionAuthorityError(
            "structural_authority must be the exact typed structural DTO"
        )
    if type(proof_pack) is not TransformOutputDispositionProofPackV1:
        raise TransformOutputDispositionAuthorityError(
            "proof_pack must be the exact typed proof DTO"
        )
    if type(audit_metadata) is not TransformOutputDispositionAuditMetadataV1:
        raise TransformOutputDispositionAuthorityError(
            "audit_metadata must be the exact typed audit DTO"
        )
    if audit_metadata.proof_pack_root_sha256 != proof_pack.proof_pack_root_sha256:
        raise TransformOutputDispositionAuthorityError(
            "audit metadata differs from the exact proof pack"
        )
    _require_sha256(
        authored_decision_authority_sha256,
        field_name="authored_decision_authority_sha256",
    )
    if type(generation_sequence) is not int or generation_sequence <= 0:
        raise TransformOutputDispositionAuthorityError(
            "generation_sequence must be a positive exact integer"
        )
    if generation_sequence == 1:
        if prior_envelope_sha256 is not None or tombstones or changes:
            raise TransformOutputDispositionAuthorityError(
                "initial generation cannot carry prior, tombstone, or change state"
            )
    else:
        _require_sha256(prior_envelope_sha256, field_name="prior_envelope_sha256")
    _require_exact_tuple(entries, field_name="entries", allow_empty=False)
    _require_exact_tuple(tombstones, field_name="tombstones", allow_empty=True)
    _require_exact_tuple(changes, field_name="changes", allow_empty=True)
    _require_exact_tuple(dependencies, field_name="dependencies", allow_empty=True)
    if any(type(item) is not CurrentTransformOutputDispositionV1 for item in entries):
        raise TransformOutputDispositionAuthorityError("entries contain a foreign type")
    if any(type(item) is not TransformOutputRemovedTombstoneV1 for item in tombstones):
        raise TransformOutputDispositionAuthorityError("tombstones contain a foreign type")
    if any(type(item) is not TransformOutputChangeV1 for item in changes):
        raise TransformOutputDispositionAuthorityError("changes contain a foreign type")
    if any(type(item) is not TransformOutputDependencyV1 for item in dependencies):
        raise TransformOutputDispositionAuthorityError("dependencies contain a foreign type")
    structural_output_names = structural_authority.output_names
    structural_count = structural_authority.output_count
    structural_tables = {item.output_name: item for item in structural_authority.tables}
    entry_names = tuple(item.output_name for item in entries)
    if entry_names != structural_output_names or len(entries) != structural_count:
        raise TransformOutputDispositionAuthorityError(
            "entries must exactly cover the sorted structural denominator"
        )
    for entry in entries:
        table = structural_tables[entry.output_name]
        expected = (
            table.table_family,
            table.table_contract_sha256,
            table.schema_sha256,
            table.transform_sha256,
            table.ordered_column_inventory_sha256,
            table.dependency_inventory_sha256,
        )
        observed = (
            entry.family,
            entry.table_contract_sha256,
            entry.schema_identity_sha256,
            entry.transform_identity_sha256,
            entry.ordered_columns_sha256,
            entry.dependency_identity_sha256,
        )
        if observed != expected:
            raise TransformOutputDispositionAuthorityError(
                f"entry differs from exact structural table authority: {entry.output_name}"
            )
    tombstone_names = tuple(item.output_name for item in tombstones)
    if tombstone_names != tuple(sorted(set(tombstone_names))) or set(entry_names) & set(
        tombstone_names
    ):
        raise TransformOutputDispositionAuthorityError(
            "tombstones must be sorted, unique, and disjoint from current entries"
        )
    change_order = tuple((item.output_name, item.change_kind) for item in changes)
    if change_order != tuple(sorted(set(change_order))) or len(
        {item.output_name for item in changes}
    ) != len(changes):
        raise TransformOutputDispositionAuthorityError("changes must be sorted and unique")
    dependency_order = tuple((item.output_name, item.ordinal) for item in dependencies)
    if dependency_order != tuple(sorted(set(dependency_order))):
        raise TransformOutputDispositionAuthorityError(
            "dependencies must be sorted with unique owner ordinals"
        )
    source_digests = frozenset(
        digest
        for member in proof_pack.source_bundle.members
        for digest in (member.member_sha256, member.content_sha256)
    )
    referenced_evidence = (
        digest
        for entry in entries
        for digest in (
            *(item.evidence_sha256 for item in entry.evidence_references),
            *(digest for claim in entry.semantic_claims for digest in claim.evidence_sha256s),
        )
    )
    if any(digest not in source_digests for digest in referenced_evidence):
        raise TransformOutputDispositionAuthorityError(
            "entry evidence is absent from the exact source bundle"
        )
    historical_evidence = (
        *(digest for item in tombstones for digest in item.removal_evidence_sha256s),
        *(digest for item in changes for digest in item.evidence_sha256s),
    )
    if any(digest not in source_digests for digest in historical_evidence):
        raise TransformOutputDispositionAuthorityError(
            "evolution evidence is absent from the exact source bundle"
        )

    entry_by_name = {item.output_name: item for item in entries}
    change_by_name = {item.output_name: item for item in changes}
    for change in changes:
        current = entry_by_name.get(change.output_name)
        if change.change_kind == "removal":
            if current is not None:
                raise TransformOutputDispositionAuthorityError(
                    "removal change cannot reference a current structural output"
                )
            matching = [item for item in tombstones if item.output_name == change.output_name]
            if (
                len(matching) != 1
                or matching[0].last_entry_sha256 != change.prior_entry_sha256
                or matching[0].removal_change_sha256 != change.change_sha256
                or matching[0].first_tombstone_generation_sequence != generation_sequence
                or matching[0].prior_envelope_sha256 != prior_envelope_sha256
            ):
                raise TransformOutputDispositionAuthorityError(
                    "removal change differs from its exact new tombstone"
                )
            continue
        if current is None:
            raise TransformOutputDispositionAuthorityError(
                "current change references an absent structural output"
            )
        if (
            change.current_entry_sha256 != current.entry_sha256
            or change.current_state != current.state
            or change.current_table_contract_sha256 != current.table_contract_sha256
        ):
            raise TransformOutputDispositionAuthorityError(
                "current change differs from its exact current entry"
            )
    for tombstone in tombstones:
        if tombstone.first_tombstone_generation_sequence > generation_sequence:
            raise TransformOutputDispositionAuthorityError(
                "tombstone first generation is later than the current generation"
            )
        if tombstone.first_tombstone_generation_sequence == generation_sequence:
            change = change_by_name.get(tombstone.output_name)
            if change is None or change.change_kind != "removal":
                raise TransformOutputDispositionAuthorityError(
                    "new tombstone lacks its exact removal change"
                )

    dependencies_by_output: dict[str, list[TransformOutputDependencyV1]] = {
        name: [] for name in structural_output_names
    }
    for dependency in dependencies:
        if dependency.output_name not in dependencies_by_output:
            raise TransformOutputDispositionAuthorityError(
                "dependency owner is outside the structural denominator"
            )
        dependencies_by_output[dependency.output_name].append(dependency)
    for output_name in structural_output_names:
        table = structural_tables[output_name]
        rows = dependencies_by_output[output_name]
        if tuple(item.ordinal for item in rows) != tuple(range(len(table.dependencies))):
            raise TransformOutputDispositionAuthorityError(
                f"dependency ordinals differ from the exact structural order: {output_name}"
            )
        if tuple(item.dependency_id for item in rows) != table.dependencies:
            raise TransformOutputDispositionAuthorityError(
                f"dependency identities differ from the exact structural order: {output_name}"
            )
        for row in rows:
            if row.dependency_id in structural_tables:
                referenced = structural_tables[row.dependency_id]
                if (
                    row.dependency_kind != "transform_output"
                    or row.dependency_contract_sha256 != referenced.table_contract_sha256
                ):
                    raise TransformOutputDispositionAuthorityError(
                        "transform dependency differs from its exact structural contract"
                    )
            elif row.dependency_kind != "staging_input":
                raise TransformOutputDispositionAuthorityError(
                    "nontransform dependency is not an exact staging-input authority"
                )

    active_output_names = tuple(item.output_name for item in entries if item.state == "active")
    experimental_output_names = tuple(
        item.output_name for item in entries if item.state == "observed_only_experimental"
    )
    non_executable_output_names = tuple(
        item.output_name for item in entries if item.state == "contract_not_modeled"
    )
    executable_output_names = tuple(
        item.output_name for item in entries if item.capability_policy.execute
    )
    stable_load_output_names = tuple(
        item.output_name for item in entries if item.capability_policy.stable_load
    )
    transform_publication_output_names = tuple(
        item.output_name for item in entries if item.capability_policy.transform_publication
    )
    chat_ceiling_output_names = tuple(
        item.output_name for item in entries if item.capability_policy.chat_ceiling
    )
    executable_set = frozenset(executable_output_names)
    dependency_graph_rows: list[tuple[str, tuple[str, ...]]] = []
    for output_name in executable_output_names:
        owner = entry_by_name[output_name]
        transform_dependencies = tuple(
            item.dependency_id
            for item in dependencies_by_output[output_name]
            if item.dependency_kind == "transform_output"
        )
        for dependency_name in transform_dependencies:
            target = entry_by_name[dependency_name]
            if dependency_name not in executable_set:
                raise TransformOutputDispositionAuthorityError(
                    "executable output depends on a non-executable transform output"
                )
            if owner.state == "active" and target.state != "active":
                raise TransformOutputDispositionAuthorityError(
                    "active output dependency is not active"
                )
        dependency_graph_rows.append((output_name, transform_dependencies))
    dependency_graph = tuple(dependency_graph_rows)
    remaining = {name: set(dependency_names) for name, dependency_names in dependency_graph}
    topological: list[str] = []
    while remaining:
        ready = sorted(name for name, dependency_names in remaining.items() if not dependency_names)
        if not ready:
            raise TransformOutputDispositionAuthorityError(
                "executable transform dependency graph contains a cycle"
            )
        for name in ready:
            topological.append(name)
            del remaining[name]
        ready_set = set(ready)
        for dependency_names in remaining.values():
            dependency_names.difference_update(ready_set)
    topological_order = tuple(topological)

    entry_inventory = tuple((item.output_name, item.entry_sha256) for item in entries)
    state_inventory = tuple((item.output_name, item.state) for item in entries)
    state_order: tuple[TransformOutputDispositionState, ...] = (
        "active",
        "contract_not_modeled",
        "observed_only_experimental",
    )
    state_counts = tuple(
        (state, sum(item.state == state for item in entries)) for state in state_order
    )
    capability_inventory = tuple(
        (item.output_name, item.capability_policy.policy_sha256) for item in entries
    )
    entries_sha256 = _sha256_json([item.entry_sha256 for item in entries])
    tombstones_sha256 = _sha256_json([item.tombstone_sha256 for item in tombstones])
    changes_sha256 = _sha256_json([item.change_sha256 for item in changes])
    dependencies_sha256 = _sha256_json([item.dependency_sha256 for item in dependencies])
    entry_inventory_sha256 = _sha256_json(
        {"kind": "nbadb_transform_output_entry_inventory", "rows": entry_inventory}
    )
    state_inventory_sha256 = _sha256_json(
        {"kind": "nbadb_transform_output_state_inventory", "rows": state_inventory}
    )
    capability_inventory_sha256 = _sha256_json(
        {"kind": "nbadb_transform_output_capability_inventory", "rows": capability_inventory}
    )
    dependency_graph_sha256 = _sha256_json(
        {"kind": "nbadb_transform_output_dependency_graph", "rows": dependency_graph}
    )
    topological_order_sha256 = _sha256_json(
        {"kind": "nbadb_transform_output_topological_order", "output_names": topological_order}
    )
    structural_authority_sha256 = structural_authority.authority_sha256
    star_model_contract_sha256 = structural_authority.star_model_contract_sha256
    source_bundle_sha256 = proof_pack.source_bundle.source_bundle_root_sha256
    proof_pack_sha256 = proof_pack.proof_pack_root_sha256
    verifier_source_inventory_sha256 = _sha256_json(
        {
            "kind": "nbadb_transform_output_verifier_source_inventory",
            "member_sha256s": proof_pack.verifier_source_member_sha256s,
        }
    )
    audit_metadata_sha256 = audit_metadata.audit_metadata_sha256
    output_name_inventory_sha256 = structural_authority.output_name_inventory_sha256
    table_authority_inventory_sha256 = structural_authority.table_authority_inventory_sha256
    proof_result_sha256 = proof_pack.claimed_reconstructed_result_sha256
    generation_identity_sha256 = _sha256_json(
        {
            "schema_version": TRANSFORM_OUTPUT_DISPOSITION_SCHEMA_VERSION,
            "kind": "nbadb_transform_output_disposition_generation_identity",
            "generation_sequence": generation_sequence,
            "prior_envelope_sha256": prior_envelope_sha256,
            "structural_authority_sha256": structural_authority_sha256,
            "authored_decision_authority_sha256": authored_decision_authority_sha256,
            "entries_sha256": entries_sha256,
            "tombstones_sha256": tombstones_sha256,
            "changes_sha256": changes_sha256,
            "dependencies_sha256": dependencies_sha256,
            "entry_inventory_sha256": entry_inventory_sha256,
            "state_inventory_sha256": state_inventory_sha256,
            "capability_inventory_sha256": capability_inventory_sha256,
            "dependency_graph_sha256": dependency_graph_sha256,
            "topological_order_sha256": topological_order_sha256,
            "proof_pack_sha256": proof_pack_sha256,
            "proof_result_sha256": proof_result_sha256,
        }
    )
    payload_without_envelope = {
        "schema_version": TRANSFORM_OUTPUT_DISPOSITION_SCHEMA_VERSION,
        "kind": TRANSFORM_OUTPUT_DISPOSITION_AUTHORITY_KIND,
        "structural_authority": structural_authority.to_dict(),
        "proof_pack": proof_pack.to_dict(),
        "audit_metadata": audit_metadata.to_dict(),
        "generation_sequence": generation_sequence,
        "prior_envelope_sha256": prior_envelope_sha256,
        "entries": [item.to_dict() for item in entries],
        "tombstones": [item.to_dict() for item in tombstones],
        "changes": [item.to_dict() for item in changes],
        "dependencies": [item.to_dict() for item in dependencies],
        "structural_output_names": list(structural_output_names),
        "entry_inventory": [
            {"output_name": output_name, "entry_sha256": entry_sha256}
            for output_name, entry_sha256 in entry_inventory
        ],
        "state_inventory": [
            {"output_name": output_name, "state": state} for output_name, state in state_inventory
        ],
        "state_counts": {state: count for state, count in state_counts},
        "capability_inventory": [
            {"output_name": output_name, "policy_sha256": policy_sha256}
            for output_name, policy_sha256 in capability_inventory
        ],
        "active_output_names": list(active_output_names),
        "experimental_output_names": list(experimental_output_names),
        "non_executable_output_names": list(non_executable_output_names),
        "executable_output_names": list(executable_output_names),
        "stable_load_output_names": list(stable_load_output_names),
        "transform_publication_output_names": list(transform_publication_output_names),
        "chat_ceiling_output_names": list(chat_ceiling_output_names),
        "tombstone_output_names": list(tombstone_names),
        "dependency_graph": [
            {"output_name": output_name, "dependencies": list(dependency_names)}
            for output_name, dependency_names in dependency_graph
        ],
        "topological_order": list(topological_order),
        "structural_count": structural_count,
        "structural_authority_sha256": structural_authority_sha256,
        "star_model_contract_sha256": star_model_contract_sha256,
        "authored_decision_authority_sha256": authored_decision_authority_sha256,
        "source_bundle_sha256": source_bundle_sha256,
        "proof_pack_sha256": proof_pack_sha256,
        "verifier_source_inventory_sha256": verifier_source_inventory_sha256,
        "audit_metadata_sha256": audit_metadata_sha256,
        "output_name_inventory_sha256": output_name_inventory_sha256,
        "table_authority_inventory_sha256": table_authority_inventory_sha256,
        "entries_sha256": entries_sha256,
        "tombstones_sha256": tombstones_sha256,
        "changes_sha256": changes_sha256,
        "dependencies_sha256": dependencies_sha256,
        "entry_inventory_sha256": entry_inventory_sha256,
        "state_inventory_sha256": state_inventory_sha256,
        "capability_inventory_sha256": capability_inventory_sha256,
        "dependency_graph_sha256": dependency_graph_sha256,
        "topological_order_sha256": topological_order_sha256,
        "proof_result_sha256": proof_result_sha256,
        "generation_identity_sha256": generation_identity_sha256,
    }
    instance = object.__new__(VerifiedTransformOutputDispositionAuthorityEnvelopeV1)
    for field_name, value in payload_without_envelope.items():
        if field_name not in {"schema_version", "kind"}:
            object.__setattr__(instance, field_name, value)
    object.__setattr__(instance, "entries", entries)
    object.__setattr__(instance, "tombstones", tombstones)
    object.__setattr__(instance, "changes", changes)
    object.__setattr__(instance, "dependencies", dependencies)
    object.__setattr__(instance, "structural_authority", structural_authority)
    object.__setattr__(instance, "proof_pack", proof_pack)
    object.__setattr__(instance, "audit_metadata", audit_metadata)
    object.__setattr__(instance, "structural_output_names", structural_output_names)
    object.__setattr__(instance, "entry_inventory", entry_inventory)
    object.__setattr__(instance, "state_inventory", state_inventory)
    object.__setattr__(instance, "state_counts", state_counts)
    object.__setattr__(instance, "capability_inventory", capability_inventory)
    object.__setattr__(instance, "active_output_names", active_output_names)
    object.__setattr__(instance, "experimental_output_names", experimental_output_names)
    object.__setattr__(instance, "non_executable_output_names", non_executable_output_names)
    object.__setattr__(instance, "executable_output_names", executable_output_names)
    object.__setattr__(instance, "stable_load_output_names", stable_load_output_names)
    object.__setattr__(
        instance,
        "transform_publication_output_names",
        transform_publication_output_names,
    )
    object.__setattr__(instance, "chat_ceiling_output_names", chat_ceiling_output_names)
    object.__setattr__(instance, "tombstone_output_names", tombstone_names)
    object.__setattr__(instance, "dependency_graph", dependency_graph)
    object.__setattr__(instance, "topological_order", topological_order)
    object.__setattr__(
        instance,
        "envelope_sha256",
        _sha256_json(payload_without_envelope),
    )
    return instance
