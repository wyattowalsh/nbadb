"""Exact per-operation commitment over disposition authority and bindings."""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass, field
from typing import ClassVar, Self, cast

from nbadb.contracts.transform_output_disposition_authority import (
    CurrentTransformOutputDispositionV1,
    TransformOutputDispositionAuthorityError,
    VerifiedTransformOutputDispositionAuthorityEnvelopeV1,
)
from nbadb.contracts.transform_output_disposition_evidence import (
    CANONICAL_JSON_MAX_BYTES,
    DispositionEvidenceError,
    canonical_json_bytes_v1,
    decode_canonical_json_bytes_v1,
)
from nbadb.contracts.transform_output_generation_binding import (
    TransformOutputGenerationBindingError,
    TransformOutputGenerationBindingV1,
)
from nbadb.contracts.transform_output_operation_data_authority import (
    OperationDataAuthorityError,
    OperationDataEvidenceV1,
)

__all__ = [
    "TransformOutputCurrentRootV1",
    "TransformOutputOperationCommitmentError",
    "TransformOutputOperationCommitmentV1",
    "compile_transform_output_operation_commitment",
]

_VERSION = 1
_KIND = "nbadb_transform_output_operation_commitment"
_MAX_BYTES = CANONICAL_JSON_MAX_BYTES + 1
_MAX_DEPTH = 48
_MAX_NODES = 200_000
_MAX_STRING_BYTES = 24 * 1024 * 1024
_MAX_NUMBER_CHARS = 128
_SHA_RE = re.compile(r"[0-9a-f]{64}\Z", re.ASCII)
_TOKEN = object()


class TransformOutputOperationCommitmentError(ValueError):
    """An operation commitment is malformed or inconsistent."""


def _canonical(value: object) -> bytes:
    try:
        return canonical_json_bytes_v1(value)
    except (DispositionEvidenceError, MemoryError, RecursionError) as exc:
        raise TransformOutputOperationCommitmentError("commitment is not canonical JSON") from exc


def _digest(value: object) -> str:
    return hashlib.sha256(_canonical(value)).hexdigest()


def _bounded_canonical(value: object) -> bytes:
    encoded = _canonical(value)
    if len(encoded) + 1 > _MAX_BYTES:
        raise TransformOutputOperationCommitmentError("commitment exceeds its canonical byte bound")
    return encoded


def _sha(value: object, name: str) -> str:
    if type(value) is not str or _SHA_RE.fullmatch(value) is None:
        raise TransformOutputOperationCommitmentError(f"{name} must be a lowercase SHA-256")
    return value


def _preflight_json_bytes(raw: bytes) -> None:
    """Reject hostile JSON shape before the shared decoder materializes it."""

    depth = 0
    nodes = 0
    in_string = False
    escaped = False
    current_string_bytes = 0
    total_string_bytes = 0
    index = 0
    while index < len(raw):
        byte = raw[index]
        if in_string:
            if escaped:
                escaped = False
                current_string_bytes += 1
            elif byte == 0x5C:
                escaped = True
                current_string_bytes += 1
            elif byte == 0x22:
                in_string = False
                if current_string_bytes > _MAX_STRING_BYTES:
                    raise TransformOutputOperationCommitmentError(
                        "commitment contains an over-bound string token"
                    )
                total_string_bytes += current_string_bytes
                if total_string_bytes > _MAX_STRING_BYTES:
                    raise TransformOutputOperationCommitmentError(
                        "commitment exceeds its lexical aggregate string bound"
                    )
                current_string_bytes = 0
            else:
                current_string_bytes += 1
            index += 1
            continue
        if byte == 0x22:
            in_string = True
            nodes += 1
        elif byte in (0x7B, 0x5B):
            depth += 1
            nodes += 1
        elif byte in (0x7D, 0x5D):
            depth -= 1
            if depth < 0:
                raise TransformOutputOperationCommitmentError(
                    "commitment JSON is structurally invalid"
                )
        elif byte == 0x2D or 0x30 <= byte <= 0x39:
            nodes += 1
            end = index + 1
            while end < len(raw) and raw[end] not in b" \t\r\n,]}:":
                end += 1
            if end - index > _MAX_NUMBER_CHARS:
                raise TransformOutputOperationCommitmentError(
                    "commitment contains an over-bound number token"
                )
            index = end - 1
        elif byte in (0x74, 0x66, 0x6E):
            nodes += 1
        if depth > _MAX_DEPTH:
            raise TransformOutputOperationCommitmentError(
                "commitment exceeds its lexical depth bound"
            )
        if nodes > _MAX_NODES:
            raise TransformOutputOperationCommitmentError(
                "commitment exceeds its lexical structure bound"
            )
        index += 1
    if in_string or escaped or depth != 0:
        raise TransformOutputOperationCommitmentError("commitment JSON is structurally invalid")


@dataclass(frozen=True, slots=True, order=True)
class TransformOutputCurrentRootV1:
    """Exact table-local roots applicable to the current operation."""

    output_name: str
    entry_sha256: str
    policy_sha256: str
    table_contract_sha256: str
    schema_identity_sha256: str
    transform_identity_sha256: str
    ordered_columns_sha256: str
    dependency_identity_sha256: str
    current_root_sha256: str = field(init=False, compare=True)

    schema_version: ClassVar[int] = _VERSION
    kind: ClassVar[str] = "nbadb_transform_output_current_root"

    def __post_init__(self) -> None:
        if type(self.output_name) is not str or not self.output_name:
            raise TransformOutputOperationCommitmentError("output_name is invalid")
        for name in (
            "entry_sha256",
            "policy_sha256",
            "table_contract_sha256",
            "schema_identity_sha256",
            "transform_identity_sha256",
            "ordered_columns_sha256",
            "dependency_identity_sha256",
        ):
            _sha(getattr(self, name), name)
        object.__setattr__(self, "current_root_sha256", _digest(self._preimage()))

    @classmethod
    def from_entry(cls, entry: CurrentTransformOutputDispositionV1) -> Self:
        if type(entry) is not CurrentTransformOutputDispositionV1:
            raise TransformOutputOperationCommitmentError("entry has a foreign type")
        return cls(
            entry.output_name,
            entry.entry_sha256,
            entry.capability_policy.policy_sha256,
            entry.table_contract_sha256,
            entry.schema_identity_sha256,
            entry.transform_identity_sha256,
            entry.ordered_columns_sha256,
            entry.dependency_identity_sha256,
        )

    def _preimage(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "kind": self.kind,
            "output_name": self.output_name,
            "entry_sha256": self.entry_sha256,
            "policy_sha256": self.policy_sha256,
            "table_contract_sha256": self.table_contract_sha256,
            "schema_identity_sha256": self.schema_identity_sha256,
            "transform_identity_sha256": self.transform_identity_sha256,
            "ordered_columns_sha256": self.ordered_columns_sha256,
            "dependency_identity_sha256": self.dependency_identity_sha256,
        }

    def to_dict(self) -> dict[str, object]:
        return {**self._preimage(), "current_root_sha256": self.current_root_sha256}


@dataclass(frozen=True, slots=True, init=False)
class TransformOutputOperationCommitmentV1:
    """Complete operation authority derived from one envelope and binding set."""

    authority_envelope: VerifiedTransformOutputDispositionAuthorityEnvelopeV1
    bindings: tuple[TransformOutputGenerationBindingV1, ...]
    operation_identity_sha256: str
    transaction_generation_identity_sha256: str
    disposition_generation_identity_sha256: str
    authored_decision_authority_sha256: str
    operation_data_evidence_sha256: str
    binding_count: int
    binding_inventory: tuple[tuple[str, str], ...]
    binding_inventory_sha256: str
    structural_output_names: tuple[str, ...]
    executable_output_names: tuple[str, ...]
    active_output_names: tuple[str, ...]
    non_executable_output_names: tuple[str, ...]
    tombstone_output_names: tuple[str, ...]
    dependency_graph: tuple[tuple[str, tuple[str, ...]], ...]
    topological_order: tuple[str, ...]
    current_roots: tuple[TransformOutputCurrentRootV1, ...]
    current_root_inventory_sha256: str
    commitment_sha256: str

    schema_version: ClassVar[int] = _VERSION
    kind: ClassVar[str] = _KIND

    def __init__(self) -> None:
        raise TypeError("TransformOutputOperationCommitmentV1 requires from_canonical_bytes")

    def _preimage(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "kind": self.kind,
            "authority_envelope": self.authority_envelope.to_dict(),
            "bindings": [item.to_dict() for item in self.bindings],
            "operation_identity_sha256": self.operation_identity_sha256,
            "transaction_generation_identity_sha256": self.transaction_generation_identity_sha256,
            "disposition_generation_identity_sha256": self.disposition_generation_identity_sha256,
            "authored_decision_authority_sha256": self.authored_decision_authority_sha256,
            "operation_data_evidence_sha256": self.operation_data_evidence_sha256,
            "binding_count": self.binding_count,
            "binding_inventory": [
                {"output_name": name, "binding_sha256": root}
                for name, root in self.binding_inventory
            ],
            "binding_inventory_sha256": self.binding_inventory_sha256,
            "structural_output_names": list(self.structural_output_names),
            "executable_output_names": list(self.executable_output_names),
            "active_output_names": list(self.active_output_names),
            "non_executable_output_names": list(self.non_executable_output_names),
            "tombstone_output_names": list(self.tombstone_output_names),
            "dependency_graph": [
                {"output_name": name, "dependencies": list(deps)}
                for name, deps in self.dependency_graph
            ],
            "topological_order": list(self.topological_order),
            "current_roots": [item.to_dict() for item in self.current_roots],
            "current_root_inventory_sha256": self.current_root_inventory_sha256,
        }

    def to_dict(self) -> dict[str, object]:
        return {**self._preimage(), "commitment_sha256": self.commitment_sha256}

    def canonical_bytes(self) -> bytes:
        return _bounded_canonical(self.to_dict()) + b"\n"

    @classmethod
    def from_canonical_bytes(cls, raw: bytes) -> Self:
        if cls is not TransformOutputOperationCommitmentV1:
            raise TransformOutputOperationCommitmentError(
                "commitment replay requires the exact DTO class"
            )
        try:
            return cast("Self", _replay_operation_commitment(raw))
        except TransformOutputOperationCommitmentError:
            raise
        except (
            DispositionEvidenceError,
            TransformOutputDispositionAuthorityError,
            TransformOutputGenerationBindingError,
            OperationDataAuthorityError,
        ) as exc:
            raise TransformOutputOperationCommitmentError(str(exc)) from exc
        except (MemoryError, RecursionError) as exc:
            raise TransformOutputOperationCommitmentError(
                "commitment replay exceeded its resource bounds"
            ) from exc


def _replay_operation_commitment(raw: object) -> TransformOutputOperationCommitmentV1:
    if type(raw) is not bytes or not raw or len(raw) > _MAX_BYTES:
        raise TransformOutputOperationCommitmentError("commitment bytes invalid or oversized")
    if not raw.endswith(b"\n") or raw.endswith(b"\n\n"):
        raise TransformOutputOperationCommitmentError("commitment bytes must end in exactly one LF")
    encoded = raw[:-1]
    if not encoded:
        raise TransformOutputOperationCommitmentError("commitment JSON payload is empty")
    _preflight_json_bytes(encoded)
    payload = decode_canonical_json_bytes_v1(raw, persisted=True)
    if type(payload) is not dict or any(type(key) is not str for key in payload):
        raise TransformOutputOperationCommitmentError("commitment root must be an exact object")
    root = cast("dict[str, object]", payload)
    expected_keys = frozenset(TransformOutputOperationCommitmentV1.__annotations__) | {
        "schema_version",
        "kind",
    }
    if frozenset(root) != expected_keys:
        raise TransformOutputOperationCommitmentError("commitment fields differ")
    if (
        type(root["schema_version"]) is not int
        or root["schema_version"] != TransformOutputOperationCommitmentV1.schema_version
        or type(root["kind"]) is not str
        or root["kind"] != TransformOutputOperationCommitmentV1.kind
    ):
        raise TransformOutputOperationCommitmentError("commitment schema identity is invalid")
    envelope = VerifiedTransformOutputDispositionAuthorityEnvelopeV1.from_canonical_bytes(
        _canonical(root["authority_envelope"]) + b"\n"
    )
    bindings_raw = root["bindings"]
    if type(bindings_raw) is not list:
        raise TransformOutputOperationCommitmentError("bindings must be an array")
    if len(bindings_raw) != len(envelope.executable_output_names):
        raise TransformOutputOperationCommitmentError(
            "persisted binding count differs from the exact executable denominator"
        )
    bindings = tuple(
        TransformOutputGenerationBindingV1.from_canonical_bytes(_canonical(item) + b"\n")
        for item in bindings_raw
    )
    commitment = _construct_operation_commitment(
        token=_TOKEN,
        authority_envelope=envelope,
        bindings=bindings,
        operation_data_evidence_sha256=cast("str", root["operation_data_evidence_sha256"]),
    )
    if commitment.canonical_bytes() != raw:
        raise TransformOutputOperationCommitmentError(
            "commitment differs from its exact canonical reconstruction"
        )
    return commitment


def compile_transform_output_operation_commitment(
    *,
    authority_envelope: VerifiedTransformOutputDispositionAuthorityEnvelopeV1,
    bindings: tuple[TransformOutputGenerationBindingV1, ...],
    operation_data_evidence: OperationDataEvidenceV1,
) -> TransformOutputOperationCommitmentV1:
    """Close one operation from strict-replayed authority and same-snapshot evidence."""

    if type(authority_envelope) is not VerifiedTransformOutputDispositionAuthorityEnvelopeV1:
        raise TransformOutputOperationCommitmentError("authority_envelope has foreign type")
    if type(bindings) is not tuple or any(
        type(item) is not TransformOutputGenerationBindingV1 for item in bindings
    ):
        raise TransformOutputOperationCommitmentError("bindings must be an exact typed tuple")
    if type(operation_data_evidence) is not OperationDataEvidenceV1:
        raise TransformOutputOperationCommitmentError("operation_data_evidence has foreign type")
    try:
        replayed_envelope = (
            VerifiedTransformOutputDispositionAuthorityEnvelopeV1.from_canonical_bytes(
                authority_envelope.canonical_bytes()
            )
        )
    except (ValueError, MemoryError, RecursionError) as exc:
        raise TransformOutputOperationCommitmentError(
            "operation commitment envelope is not strict replayable authority"
        ) from exc
    if replayed_envelope.to_dict() != authority_envelope.to_dict():
        raise TransformOutputOperationCommitmentError(
            "operation commitment envelope differs after strict replay"
        )
    if len(bindings) != len(replayed_envelope.executable_output_names):
        raise TransformOutputOperationCommitmentError(
            "binding count differs from the exact executable denominator"
        )
    try:
        replayed_bindings = tuple(
            TransformOutputGenerationBindingV1.from_canonical_bytes(item.canonical_bytes())
            for item in bindings
        )
    except (ValueError, MemoryError, RecursionError) as exc:
        raise TransformOutputOperationCommitmentError(
            "operation commitment binding is not strict replayable authority"
        ) from exc
    if tuple(item.to_dict() for item in replayed_bindings) != tuple(
        item.to_dict() for item in bindings
    ):
        raise TransformOutputOperationCommitmentError(
            "operation commitment binding differs after strict replay"
        )
    try:
        replayed_evidence = OperationDataEvidenceV1.from_canonical_bytes(
            operation_data_evidence.canonical_bytes()
        )
    except (ValueError, MemoryError, RecursionError) as exc:
        raise TransformOutputOperationCommitmentError(
            "operation data evidence is not strict replayable authority"
        ) from exc
    if replayed_evidence.to_dict() != operation_data_evidence.to_dict():
        raise TransformOutputOperationCommitmentError(
            "operation data evidence differs after strict replay"
        )
    if not replayed_bindings:
        raise TransformOutputOperationCommitmentError(
            "operation commitment requires at least one executable binding"
        )
    operation_context = replayed_evidence.operation_context
    operation_identities = {item.operation_identity_sha256 for item in replayed_bindings}
    transaction_generation_identities = {
        item.transaction_generation_identity_sha256 for item in replayed_bindings
    }
    if operation_identities != {
        operation_context.operation_sha256
    } or transaction_generation_identities != {
        operation_context.transaction_generation_identity_sha256
    }:
        raise TransformOutputOperationCommitmentError(
            "operation data evidence differs from binding operation or generation"
        )
    commitment = _construct_operation_commitment(
        token=_TOKEN,
        authority_envelope=replayed_envelope,
        bindings=replayed_bindings,
        operation_data_evidence_sha256=(replayed_evidence.operation_data_evidence_sha256),
    )
    try:
        replayed_commitment = TransformOutputOperationCommitmentV1.from_canonical_bytes(
            commitment.canonical_bytes()
        )
    except ValueError as exc:
        raise TransformOutputOperationCommitmentError(
            "compiled operation commitment is not strict replayable authority"
        ) from exc
    if replayed_commitment.to_dict() != commitment.to_dict():
        raise TransformOutputOperationCommitmentError(
            "compiled operation commitment differs after strict replay"
        )
    return replayed_commitment


def _construct_operation_commitment(
    *,
    token: object,
    authority_envelope: VerifiedTransformOutputDispositionAuthorityEnvelopeV1,
    bindings: tuple[TransformOutputGenerationBindingV1, ...],
    operation_data_evidence_sha256: str,
) -> TransformOutputOperationCommitmentV1:
    if token is not _TOKEN:
        raise TransformOutputOperationCommitmentError("commitment construction token invalid")
    if type(authority_envelope) is not VerifiedTransformOutputDispositionAuthorityEnvelopeV1:
        raise TransformOutputOperationCommitmentError("authority_envelope has foreign type")
    if type(bindings) is not tuple or any(
        type(item) is not TransformOutputGenerationBindingV1 for item in bindings
    ):
        raise TransformOutputOperationCommitmentError("bindings must be an exact typed tuple")
    _sha(operation_data_evidence_sha256, "operation_data_evidence_sha256")
    names = tuple(item.current_entry.output_name for item in bindings)
    if names != authority_envelope.executable_output_names or names != tuple(sorted(set(names))):
        raise TransformOutputOperationCommitmentError(
            "bindings must exactly cover executable outputs"
        )
    operations = {item.operation_identity_sha256 for item in bindings}
    transactions = {item.transaction_generation_identity_sha256 for item in bindings}
    envelopes = {item.current_envelope_sha256 for item in bindings}
    authored_authorities = {item.authored_decision_authority_sha256 for item in bindings}
    if (
        len(operations) != 1
        or len(transactions) != 1
        or envelopes != {authority_envelope.envelope_sha256}
        or authored_authorities != {authority_envelope.authored_decision_authority_sha256}
    ):
        raise TransformOutputOperationCommitmentError(
            "bindings mix operation, transaction, envelope, or authored-decision authority"
        )
    entry_by_name = {item.output_name: item for item in authority_envelope.entries}
    for binding in bindings:
        if (
            binding.current_entry.to_dict()
            != entry_by_name[binding.current_entry.output_name].to_dict()
        ):
            raise TransformOutputOperationCommitmentError(
                "binding current entry differs from envelope"
            )
    order_index = {name: index for index, name in enumerate(authority_envelope.topological_order)}
    for owner, dependencies in authority_envelope.dependency_graph:
        if any(order_index[dependency] >= order_index[owner] for dependency in dependencies):
            raise TransformOutputOperationCommitmentError(
                "topological order violates dependency graph"
            )
    binding_inventory = tuple(
        (name, item.binding_sha256) for name, item in zip(names, bindings, strict=True)
    )
    current_roots = tuple(
        TransformOutputCurrentRootV1.from_entry(item) for item in authority_envelope.entries
    )
    values: dict[str, object] = {
        "authority_envelope": authority_envelope,
        "bindings": bindings,
        "operation_identity_sha256": next(iter(operations)),
        "transaction_generation_identity_sha256": next(iter(transactions)),
        "disposition_generation_identity_sha256": authority_envelope.generation_identity_sha256,
        "authored_decision_authority_sha256": (
            authority_envelope.authored_decision_authority_sha256
        ),
        "operation_data_evidence_sha256": operation_data_evidence_sha256,
        "binding_count": len(bindings),
        "binding_inventory": binding_inventory,
        "binding_inventory_sha256": _digest(
            {
                "kind": "nbadb_transform_output_binding_inventory",
                "rows": [
                    {"output_name": output_name, "binding_sha256": binding_sha256}
                    for output_name, binding_sha256 in binding_inventory
                ],
            }
        ),
        "structural_output_names": authority_envelope.structural_output_names,
        "executable_output_names": authority_envelope.executable_output_names,
        "active_output_names": authority_envelope.active_output_names,
        "non_executable_output_names": authority_envelope.non_executable_output_names,
        "tombstone_output_names": authority_envelope.tombstone_output_names,
        "dependency_graph": authority_envelope.dependency_graph,
        "topological_order": authority_envelope.topological_order,
        "current_roots": current_roots,
        "current_root_inventory_sha256": _digest(
            {
                "kind": "nbadb_transform_output_current_root_inventory",
                "rows": [item.current_root_sha256 for item in current_roots],
            }
        ),
    }
    instance = object.__new__(TransformOutputOperationCommitmentV1)
    for name, value in values.items():
        object.__setattr__(instance, name, value)
    object.__setattr__(instance, "commitment_sha256", _digest(instance._preimage()))
    instance.canonical_bytes()
    return instance
