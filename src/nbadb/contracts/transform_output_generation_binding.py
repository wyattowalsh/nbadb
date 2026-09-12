"""Sealed per-operation bindings for immutable transform receipts."""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from typing import Any, ClassVar, Literal, Self, cast

from nbadb.contracts.transform_output_disposition_authority import (
    CurrentTransformOutputDispositionV1,
    VerifiedTransformOutputDispositionAuthorityEnvelopeV1,
)
from nbadb.contracts.transform_output_materialization_receipt import (
    TransformOutputMaterializationReceiptV1,
)
from nbadb.orchestrate.successor_transform_authority import TransformOutputAttestation

__all__ = [
    "TransformOutputGenerationBindingError",
    "TransformOutputGenerationBindingV1",
    "compile_transform_output_generation_binding",
]

_SCHEMA_VERSION = 1
_KIND = "nbadb_transform_output_generation_binding"
_SCOPE = "primary_working_duckdb"
_MAX_BYTES = 8 * 1024 * 1024
_MAX_DEPTH = 48
_MAX_NODES = 32_768
_MAX_STRING_BYTES = 2 * 1024 * 1024
_MAX_NUMBER_CHARS = 128
_SHA_RE = re.compile(r"[0-9a-f]{64}\Z", re.ASCII)
_TOKEN = object()


class TransformOutputGenerationBindingError(ValueError):
    """A generation binding is malformed or inconsistent."""


def _canonical(value: object) -> bytes:
    try:
        return json.dumps(
            value,
            allow_nan=False,
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        ).encode()
    except (MemoryError, TypeError, UnicodeEncodeError, ValueError, RecursionError) as exc:
        raise TransformOutputGenerationBindingError("binding is not canonical JSON") from exc


def _digest(value: object) -> str:
    return hashlib.sha256(_canonical(value)).hexdigest()


def _bounded_canonical(value: object) -> bytes:
    _bounded(value)
    encoded = _canonical(value)
    if len(encoded) + 1 > _MAX_BYTES:
        raise TransformOutputGenerationBindingError("binding exceeds its canonical byte bound")
    return encoded


def _sha(value: object, field_name: str) -> str:
    if type(value) is not str or _SHA_RE.fullmatch(value) is None:
        raise TransformOutputGenerationBindingError(f"{field_name} must be a lowercase SHA-256")
    return value


def _object(value: object, keys: frozenset[str], label: str) -> dict[str, object]:
    if (
        type(value) is not dict
        or frozenset(value) != keys
        or any(type(key) is not str for key in value)
    ):
        raise TransformOutputGenerationBindingError(f"{label} fields differ")
    return cast("dict[str, object]", value)


def _schema_identity(
    payload: dict[str, object],
    *,
    schema_version: int,
    kind: str,
    label: str,
) -> None:
    if (
        type(payload["schema_version"]) is not int
        or payload["schema_version"] != schema_version
        or type(payload["kind"]) is not str
        or payload["kind"] != kind
    ):
        raise TransformOutputGenerationBindingError(f"{label} schema identity is invalid")


def _pairs(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise TransformOutputGenerationBindingError("binding contains a duplicate key")
        result[key] = value
    return result


def _preflight_json_bytes(raw: bytes) -> None:
    """Reject hostile JSON shape before the decoder materializes an object graph."""

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
                    raise TransformOutputGenerationBindingError(
                        "binding contains an over-bound string token"
                    )
                total_string_bytes += current_string_bytes
                if total_string_bytes > _MAX_STRING_BYTES:
                    raise TransformOutputGenerationBindingError(
                        "binding exceeds its lexical aggregate string bound"
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
                raise TransformOutputGenerationBindingError("binding JSON is structurally invalid")
        elif byte == 0x2D or 0x30 <= byte <= 0x39:
            nodes += 1
            end = index + 1
            while end < len(raw) and raw[end] not in b" \t\r\n,]}:":
                end += 1
            if end - index > _MAX_NUMBER_CHARS:
                raise TransformOutputGenerationBindingError(
                    "binding contains an over-bound number token"
                )
            index = end - 1
        elif byte in (0x74, 0x66, 0x6E):
            nodes += 1
        if depth > _MAX_DEPTH:
            raise TransformOutputGenerationBindingError("binding exceeds its lexical depth bound")
        if nodes > _MAX_NODES:
            raise TransformOutputGenerationBindingError(
                "binding exceeds its lexical structure bound"
            )
        index += 1
    if in_string or escaped or depth != 0:
        raise TransformOutputGenerationBindingError("binding JSON is structurally invalid")


def _integer(token: str) -> int:
    if len(token) > _MAX_NUMBER_CHARS:
        raise TransformOutputGenerationBindingError("binding integer token exceeds its bound")
    return int(token)


def _floating(token: str) -> float:
    raise TransformOutputGenerationBindingError(
        f"binding floating JSON values are forbidden: {token}"
    )


def _constant(token: str) -> object:
    raise TransformOutputGenerationBindingError(
        f"binding nonfinite JSON values are forbidden: {token}"
    )


def _bounded(value: object, depth: int = 0) -> tuple[int, int]:
    if depth > _MAX_DEPTH:
        raise TransformOutputGenerationBindingError("binding exceeds its depth bound")
    if value is None or type(value) in {bool, int}:
        return 1, 0
    if type(value) is str:
        return 1, len(value.encode())
    if type(value) is list:
        children = [_bounded(item, depth + 1) for item in value]
    elif type(value) is dict:
        children = [
            (nodes + 1, strings + len(cast("str", key).encode()))
            for key, item in value.items()
            for nodes, strings in [_bounded(item, depth + 1)]
        ]
    else:
        raise TransformOutputGenerationBindingError("binding contains a foreign JSON value")
    result = 1 + sum(item[0] for item in children), sum(item[1] for item in children)
    if result[0] > _MAX_NODES or result[1] > _MAX_STRING_BYTES:
        raise TransformOutputGenerationBindingError("binding exceeds its aggregate bound")
    return result


@dataclass(frozen=True, slots=True, init=False)
class TransformOutputGenerationBindingV1:
    """One verifier-derived use of a receipt in an exact current operation."""

    operation_identity_sha256: str
    transaction_generation_identity_sha256: str
    current_envelope_sha256: str
    authored_decision_authority_sha256: str
    current_entry: CurrentTransformOutputDispositionV1
    receipt: TransformOutputMaterializationReceiptV1
    fresh_attestation: TransformOutputAttestation
    canonical_relation_name: str
    canonical_relation_identity_sha256: str
    classification: Literal["reuse", "rebuild"]
    binding_sha256: str

    schema_version: ClassVar[int] = _SCHEMA_VERSION
    kind: ClassVar[str] = _KIND

    def __init__(self) -> None:
        raise TypeError("TransformOutputGenerationBindingV1 requires from_canonical_bytes")

    def _preimage(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "kind": self.kind,
            "operation_identity_sha256": self.operation_identity_sha256,
            "transaction_generation_identity_sha256": self.transaction_generation_identity_sha256,
            "current_envelope_sha256": self.current_envelope_sha256,
            "authored_decision_authority_sha256": self.authored_decision_authority_sha256,
            "current_entry": self.current_entry.to_dict(),
            "receipt": self.receipt.to_dict(),
            "fresh_attestation": self.fresh_attestation.to_dict(),
            "canonical_relation_name": self.canonical_relation_name,
            "canonical_relation_identity_sha256": self.canonical_relation_identity_sha256,
            "classification": self.classification,
        }

    def to_dict(self) -> dict[str, object]:
        return {**self._preimage(), "binding_sha256": self.binding_sha256}

    def canonical_bytes(self) -> bytes:
        return _bounded_canonical(self.to_dict()) + b"\n"

    @classmethod
    def from_canonical_bytes(cls, raw: bytes) -> Self:
        if type(raw) is not bytes or not raw or len(raw) > _MAX_BYTES:
            raise TransformOutputGenerationBindingError("binding bytes are invalid or oversized")
        if not raw.endswith(b"\n") or raw.endswith(b"\n\n"):
            raise TransformOutputGenerationBindingError("binding bytes must end in exactly one LF")
        encoded = raw[:-1]
        if not encoded:
            raise TransformOutputGenerationBindingError("binding JSON payload is empty")
        _preflight_json_bytes(encoded)
        try:
            payload = json.loads(
                encoded,
                object_pairs_hook=_pairs,
                parse_constant=_constant,
                parse_float=_floating,
                parse_int=_integer,
            )
        except TransformOutputGenerationBindingError:
            raise
        except (
            MemoryError,
            UnicodeDecodeError,
            json.JSONDecodeError,
            RecursionError,
            ValueError,
        ) as exc:
            raise TransformOutputGenerationBindingError("binding JSON is invalid") from exc
        _bounded(payload)
        if _canonical(payload) + b"\n" != raw:
            raise TransformOutputGenerationBindingError("binding bytes are not canonical")
        root = _object(
            payload,
            frozenset(
                {
                    "schema_version",
                    "kind",
                    "operation_identity_sha256",
                    "transaction_generation_identity_sha256",
                    "current_envelope_sha256",
                    "authored_decision_authority_sha256",
                    "current_entry",
                    "receipt",
                    "fresh_attestation",
                    "canonical_relation_name",
                    "canonical_relation_identity_sha256",
                    "classification",
                    "binding_sha256",
                }
            ),
            "binding",
        )
        _schema_identity(
            root,
            schema_version=cls.schema_version,
            kind=cls.kind,
            label="binding",
        )
        receipt = TransformOutputMaterializationReceiptV1.from_canonical_bytes(
            _canonical(root["receipt"]) + b"\n"
        )
        if _canonical(root["current_entry"]) != _canonical(receipt.disposition_entry.to_dict()):
            raise TransformOutputGenerationBindingError(
                "current entry differs from immutable receipt local authority"
            )
        attestation_data = _object(
            root["fresh_attestation"],
            frozenset({"table_name", "row_count", "schema_sha256", "content_sha256"}),
            "fresh attestation",
        )
        try:
            fresh = TransformOutputAttestation(
                table_name=cast("Any", attestation_data["table_name"]),
                row_count=cast("Any", attestation_data["row_count"]),
                schema_sha256=cast("Any", attestation_data["schema_sha256"]),
                content_sha256=cast("Any", attestation_data["content_sha256"]),
            )
        except ValueError as exc:
            raise TransformOutputGenerationBindingError("fresh attestation is invalid") from exc
        binding = _construct_binding(
            token=_TOKEN,
            operation_identity_sha256=cast("Any", root["operation_identity_sha256"]),
            transaction_generation_identity_sha256=cast(
                "Any", root["transaction_generation_identity_sha256"]
            ),
            current_envelope_sha256=cast("Any", root["current_envelope_sha256"]),
            authored_decision_authority_sha256=cast(
                "Any", root["authored_decision_authority_sha256"]
            ),
            current_entry=receipt.disposition_entry,
            receipt=receipt,
            fresh_attestation=fresh,
            canonical_relation_name=root["canonical_relation_name"],
            expected_classification=root["classification"],
            expected_relation_identity_sha256=root["canonical_relation_identity_sha256"],
            expected_binding_sha256=root["binding_sha256"],
        )
        if binding.canonical_bytes() != raw:
            raise TransformOutputGenerationBindingError(
                "binding differs from its exact reconstructed form"
            )
        return cast("Self", binding)


def compile_transform_output_generation_binding(
    *,
    operation_identity_sha256: str,
    transaction_generation_identity_sha256: str,
    authority_envelope: VerifiedTransformOutputDispositionAuthorityEnvelopeV1,
    receipt: TransformOutputMaterializationReceiptV1,
    fresh_attestation: TransformOutputAttestation,
) -> TransformOutputGenerationBindingV1:
    """Close one current executable output without caller-supplied authority roots."""

    if type(authority_envelope) is not VerifiedTransformOutputDispositionAuthorityEnvelopeV1:
        raise TransformOutputGenerationBindingError("authority_envelope has a foreign type")
    try:
        replayed_envelope = (
            VerifiedTransformOutputDispositionAuthorityEnvelopeV1.from_canonical_bytes(
                authority_envelope.canonical_bytes()
            )
        )
    except ValueError as exc:
        raise TransformOutputGenerationBindingError(
            "authority_envelope is not strict replayable authority"
        ) from exc
    if replayed_envelope.to_dict() != authority_envelope.to_dict():
        raise TransformOutputGenerationBindingError(
            "authority_envelope differs after strict replay"
        )
    if type(receipt) is not TransformOutputMaterializationReceiptV1:
        raise TransformOutputGenerationBindingError("receipt has a foreign type")
    try:
        replayed_receipt = TransformOutputMaterializationReceiptV1.from_canonical_bytes(
            receipt.canonical_bytes()
        )
    except ValueError as exc:
        raise TransformOutputGenerationBindingError(
            "receipt is not strict replayable authority"
        ) from exc
    if replayed_receipt.to_dict() != receipt.to_dict():
        raise TransformOutputGenerationBindingError("receipt differs after strict replay")
    authority_envelope = replayed_envelope
    receipt = replayed_receipt
    output_name = receipt.disposition_entry.output_name
    current_entries = tuple(
        entry for entry in authority_envelope.entries if entry.output_name == output_name
    )
    if len(current_entries) != 1 or output_name not in authority_envelope.executable_output_names:
        raise TransformOutputGenerationBindingError(
            "receipt output is not one exact executable envelope entry"
        )
    current_entry = current_entries[0]
    binding = _construct_binding(
        token=_TOKEN,
        operation_identity_sha256=operation_identity_sha256,
        transaction_generation_identity_sha256=transaction_generation_identity_sha256,
        current_envelope_sha256=authority_envelope.envelope_sha256,
        authored_decision_authority_sha256=(authority_envelope.authored_decision_authority_sha256),
        current_entry=current_entry,
        receipt=receipt,
        fresh_attestation=fresh_attestation,
        canonical_relation_name=output_name,
    )
    try:
        replayed_binding = TransformOutputGenerationBindingV1.from_canonical_bytes(
            binding.canonical_bytes()
        )
    except ValueError as exc:
        raise TransformOutputGenerationBindingError(
            "compiled binding is not strict replayable authority"
        ) from exc
    if replayed_binding.to_dict() != binding.to_dict():
        raise TransformOutputGenerationBindingError("compiled binding differs after strict replay")
    return replayed_binding


def _construct_binding(
    *,
    token: object,
    operation_identity_sha256: str,
    transaction_generation_identity_sha256: str,
    current_envelope_sha256: str,
    authored_decision_authority_sha256: str,
    current_entry: CurrentTransformOutputDispositionV1,
    receipt: TransformOutputMaterializationReceiptV1,
    fresh_attestation: TransformOutputAttestation,
    canonical_relation_name: object,
    expected_classification: object | None = None,
    expected_relation_identity_sha256: object | None = None,
    expected_binding_sha256: object | None = None,
) -> TransformOutputGenerationBindingV1:
    if token is not _TOKEN:
        raise TransformOutputGenerationBindingError("binding construction token is invalid")
    for value, name in (
        (operation_identity_sha256, "operation_identity_sha256"),
        (transaction_generation_identity_sha256, "transaction_generation_identity_sha256"),
        (current_envelope_sha256, "current_envelope_sha256"),
        (authored_decision_authority_sha256, "authored_decision_authority_sha256"),
    ):
        _sha(value, name)
    if type(current_entry) is not CurrentTransformOutputDispositionV1:
        raise TransformOutputGenerationBindingError("current_entry has a foreign type")
    if type(receipt) is not TransformOutputMaterializationReceiptV1:
        raise TransformOutputGenerationBindingError("receipt has a foreign type")
    try:
        replayed_receipt = TransformOutputMaterializationReceiptV1.from_canonical_bytes(
            receipt.canonical_bytes()
        )
    except ValueError as exc:
        raise TransformOutputGenerationBindingError(
            "receipt is not persistable canonical authority"
        ) from exc
    if replayed_receipt.to_dict() != receipt.to_dict():
        raise TransformOutputGenerationBindingError("receipt canonical replay differs")
    if type(fresh_attestation) is not TransformOutputAttestation:
        raise TransformOutputGenerationBindingError("fresh_attestation has a foreign type")
    if current_entry.to_dict() != receipt.disposition_entry.to_dict():
        raise TransformOutputGenerationBindingError("current local authority differs from receipt")
    if fresh_attestation != receipt.attestation:
        raise TransformOutputGenerationBindingError("fresh attestation differs from receipt")
    if canonical_relation_name != current_entry.output_name:
        raise TransformOutputGenerationBindingError(
            "canonical relation differs from current output"
        )
    relation_identity = _digest(
        {
            "kind": "nbadb_primary_working_duckdb_canonical_relation",
            "scope": _SCOPE,
            "output_name": current_entry.output_name,
        }
    )
    classification: Literal["reuse", "rebuild"] = (
        "rebuild"
        if receipt.transaction_generation_identity_sha256 == transaction_generation_identity_sha256
        else "reuse"
    )
    if expected_classification is not None and expected_classification != classification:
        raise TransformOutputGenerationBindingError("classification is not verifier-derived")
    if (
        expected_relation_identity_sha256 is not None
        and _sha(expected_relation_identity_sha256, "canonical_relation_identity_sha256")
        != relation_identity
    ):
        raise TransformOutputGenerationBindingError("canonical relation identity is not derived")
    instance = object.__new__(TransformOutputGenerationBindingV1)
    for name, value in (
        ("operation_identity_sha256", operation_identity_sha256),
        ("transaction_generation_identity_sha256", transaction_generation_identity_sha256),
        ("current_envelope_sha256", current_envelope_sha256),
        ("authored_decision_authority_sha256", authored_decision_authority_sha256),
        ("current_entry", current_entry),
        ("receipt", receipt),
        ("fresh_attestation", fresh_attestation),
        ("canonical_relation_name", current_entry.output_name),
        ("canonical_relation_identity_sha256", relation_identity),
        ("classification", classification),
    ):
        object.__setattr__(instance, name, value)
    binding_sha256 = _digest(instance._preimage())
    if (
        expected_binding_sha256 is not None
        and _sha(expected_binding_sha256, "binding_sha256") != binding_sha256
    ):
        raise TransformOutputGenerationBindingError("binding_sha256 is not derived")
    object.__setattr__(instance, "binding_sha256", binding_sha256)
    instance.canonical_bytes()
    return instance
