"""Immutable table-local transform materialization receipts."""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from typing import Any, ClassVar, Literal, Self, cast

from nbadb.contracts.transform_output_disposition_authority import (
    CurrentTransformOutputDispositionV1,
    TransformOutputCapabilityPolicyV1,
    TransformOutputEvidenceReferenceV1,
    TransformOutputSemanticClaimV1,
)
from nbadb.orchestrate.successor_transform_authority import TransformOutputAttestation

__all__ = [
    "TransformOutputMaterializationReceiptError",
    "TransformOutputMaterializationReceiptV1",
    "compile_transform_output_materialization_receipt",
]

_KIND = "nbadb_transform_output_materialization_receipt"
_SCHEMA_VERSION = 1
_SCOPE = "primary_working_duckdb"
_MAX_CANONICAL_BYTES = 4 * 1024 * 1024
_MAX_NODES = 16_384
_MAX_DEPTH = 32
_MAX_STRING_BYTES = 1 * 1024 * 1024
_MAX_NUMBER_CHARS = 128
_SHA256_RE = re.compile(r"[0-9a-f]{64}\Z", re.ASCII)
_ID_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.:@/-]{0,511}\Z", re.ASCII)
_CONSTRUCTION_TOKEN = object()


class TransformOutputMaterializationReceiptError(ValueError):
    """A materialization receipt is malformed or noncanonical."""


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
        raise TransformOutputMaterializationReceiptError("receipt is not canonical JSON") from exc


def _digest(value: object) -> str:
    return hashlib.sha256(_canonical(value)).hexdigest()


def _bounded_canonical(value: object) -> bytes:
    _bounded(value)
    encoded = _canonical(value)
    if len(encoded) + 1 > _MAX_CANONICAL_BYTES:
        raise TransformOutputMaterializationReceiptError("receipt exceeds its canonical byte bound")
    return encoded


def _sha(value: object, name: str) -> str:
    if type(value) is not str or _SHA256_RE.fullmatch(value) is None:
        raise TransformOutputMaterializationReceiptError(f"{name} must be a lowercase SHA-256")
    return value


def _identifier(value: object, name: str) -> str:
    if type(value) is not str or _ID_RE.fullmatch(value) is None:
        raise TransformOutputMaterializationReceiptError(f"{name} must be a safe identifier")
    return value


def _object(value: object, keys: frozenset[str], label: str) -> dict[str, object]:
    if (
        type(value) is not dict
        or frozenset(value) != keys
        or any(type(key) is not str for key in value)
    ):
        raise TransformOutputMaterializationReceiptError(f"{label} fields differ")
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
        raise TransformOutputMaterializationReceiptError(f"{label} schema identity is invalid")


def _bounded(value: object, *, depth: int = 0) -> tuple[int, int]:
    if depth > _MAX_DEPTH:
        raise TransformOutputMaterializationReceiptError("receipt exceeds its depth bound")
    if value is None or type(value) in {bool, int}:
        return 1, 0
    if type(value) is str:
        return 1, len(value.encode())
    if type(value) is list:
        totals = [_bounded(item, depth=depth + 1) for item in value]
    elif type(value) is dict:
        totals = [
            (1 + child_nodes, len(cast("str", key).encode()) + child_strings)
            for key, item in value.items()
            for child_nodes, child_strings in [_bounded(item, depth=depth + 1)]
        ]
    else:
        raise TransformOutputMaterializationReceiptError("receipt contains a foreign JSON value")
    nodes = 1 + sum(item[0] for item in totals)
    strings = sum(item[1] for item in totals)
    if nodes > _MAX_NODES or strings > _MAX_STRING_BYTES:
        raise TransformOutputMaterializationReceiptError("receipt exceeds its aggregate bound")
    return nodes, strings


def _pairs(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise TransformOutputMaterializationReceiptError("receipt contains a duplicate key")
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
                    raise TransformOutputMaterializationReceiptError(
                        "receipt contains an over-bound string token"
                    )
                total_string_bytes += current_string_bytes
                if total_string_bytes > _MAX_STRING_BYTES:
                    raise TransformOutputMaterializationReceiptError(
                        "receipt exceeds its lexical aggregate string bound"
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
                raise TransformOutputMaterializationReceiptError(
                    "receipt JSON is structurally invalid"
                )
        elif byte == 0x2D or 0x30 <= byte <= 0x39:
            nodes += 1
            end = index + 1
            while end < len(raw) and raw[end] not in b" \t\r\n,]}:":
                end += 1
            if end - index > _MAX_NUMBER_CHARS:
                raise TransformOutputMaterializationReceiptError(
                    "receipt contains an over-bound number token"
                )
            index = end - 1
        elif byte in (0x74, 0x66, 0x6E):
            nodes += 1
        if depth > _MAX_DEPTH:
            raise TransformOutputMaterializationReceiptError(
                "receipt exceeds its lexical depth bound"
            )
        if nodes > _MAX_NODES:
            raise TransformOutputMaterializationReceiptError(
                "receipt exceeds its lexical structure bound"
            )
        index += 1
    if in_string or escaped or depth != 0:
        raise TransformOutputMaterializationReceiptError("receipt JSON is structurally invalid")


def _integer(token: str) -> int:
    if len(token) > _MAX_NUMBER_CHARS:
        raise TransformOutputMaterializationReceiptError("receipt integer token exceeds its bound")
    return int(token)


def _floating(token: str) -> float:
    raise TransformOutputMaterializationReceiptError(
        f"receipt floating JSON values are forbidden: {token}"
    )


def _constant(token: str) -> object:
    raise TransformOutputMaterializationReceiptError(
        f"receipt nonfinite JSON values are forbidden: {token}"
    )


def _parse_entry(value: object) -> CurrentTransformOutputDispositionV1:
    payload = _object(
        value,
        frozenset(CurrentTransformOutputDispositionV1.digest_field_names) | {"entry_sha256"},
        "disposition entry",
    )
    _schema_identity(
        payload,
        schema_version=CurrentTransformOutputDispositionV1.schema_version,
        kind=CurrentTransformOutputDispositionV1.kind,
        label="disposition entry",
    )
    policy_data = _object(
        payload["capability_policy"],
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
        "capability policy",
    )
    _schema_identity(
        policy_data,
        schema_version=TransformOutputCapabilityPolicyV1.schema_version,
        kind=TransformOutputCapabilityPolicyV1.kind,
        label="capability policy",
    )
    policy = TransformOutputCapabilityPolicyV1(
        execute=cast("Any", policy_data["execute"]),
        primary_materialize=cast("Any", policy_data["primary_materialize"]),
        stable_load=cast("Any", policy_data["stable_load"]),
        transform_publication=cast("Any", policy_data["transform_publication"]),
        chat_ceiling=cast("Any", policy_data["chat_ceiling"]),
    )
    if policy.to_dict() != policy_data:
        raise TransformOutputMaterializationReceiptError("capability policy is not derived")
    claims_raw = payload["semantic_claims"]
    evidence_raw = payload["evidence_references"]
    triggers_raw = payload["revalidation_triggers"]
    if (
        type(claims_raw) is not list
        or type(evidence_raw) is not list
        or type(triggers_raw) is not list
    ):
        raise TransformOutputMaterializationReceiptError("entry collections must be arrays")
    claims_list: list[TransformOutputSemanticClaimV1] = []
    for item in claims_raw:
        row = _object(
            item,
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
            "semantic claim",
        )
        _schema_identity(
            row,
            schema_version=TransformOutputSemanticClaimV1.schema_version,
            kind=TransformOutputSemanticClaimV1.kind,
            label="semantic claim",
        )
        claims_list.append(
            TransformOutputSemanticClaimV1(
                claim_id=cast("Any", row["claim_id"]),
                claim_kind=cast("Any", row["claim_kind"]),
                claim_sha256=cast("Any", row["claim_sha256"]),
                evidence_sha256s=tuple(cast("Any", row["evidence_sha256s"])),
            )
        )
    claims = tuple(claims_list)
    evidence_list: list[TransformOutputEvidenceReferenceV1] = []
    for item in evidence_raw:
        row = _object(
            item,
            frozenset(
                {"schema_version", "kind", "evidence_class", "reference_id", "evidence_sha256"}
            ),
            "evidence reference",
        )
        _schema_identity(
            row,
            schema_version=TransformOutputEvidenceReferenceV1.schema_version,
            kind=TransformOutputEvidenceReferenceV1.kind,
            label="evidence reference",
        )
        evidence_list.append(
            TransformOutputEvidenceReferenceV1(
                evidence_class=cast("Any", row["evidence_class"]),
                reference_id=cast("Any", row["reference_id"]),
                evidence_sha256=cast("Any", row["evidence_sha256"]),
            )
        )
    evidence = tuple(evidence_list)
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
        semantic_claims=claims,
        reason_code=cast("Any", payload["reason_code"]),
        evidence_references=evidence,
        revalidation_triggers=cast("Any", tuple(triggers_raw)),
    )
    if entry.to_dict() != payload:
        raise TransformOutputMaterializationReceiptError("disposition entry is not derived")
    return entry


@dataclass(frozen=True, slots=True, init=False)
class TransformOutputMaterializationReceiptV1:
    """Original immutable evidence for one table-local materialization."""

    original_materialization_id: str
    transaction_generation_identity_sha256: str
    disposition_entry: CurrentTransformOutputDispositionV1
    materialization_scope: Literal["primary_working_duckdb"]
    attestation: TransformOutputAttestation
    receipt_sha256: str

    schema_version: ClassVar[int] = _SCHEMA_VERSION
    kind: ClassVar[str] = _KIND

    def __init__(self) -> None:
        raise TypeError("TransformOutputMaterializationReceiptV1 requires from_canonical_bytes")

    def _preimage(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "kind": self.kind,
            "original_materialization_id": self.original_materialization_id,
            "transaction_generation_identity_sha256": self.transaction_generation_identity_sha256,
            "disposition_entry": self.disposition_entry.to_dict(),
            "materialization_scope": self.materialization_scope,
            "attestation": self.attestation.to_dict(),
        }

    def to_dict(self) -> dict[str, object]:
        return {**self._preimage(), "receipt_sha256": self.receipt_sha256}

    def canonical_bytes(self) -> bytes:
        return _bounded_canonical(self.to_dict()) + b"\n"

    @classmethod
    def from_canonical_bytes(cls, raw: bytes) -> Self:
        if type(raw) is not bytes or not raw or len(raw) > _MAX_CANONICAL_BYTES:
            raise TransformOutputMaterializationReceiptError(
                "receipt bytes are invalid or oversized"
            )
        if not raw.endswith(b"\n") or raw.endswith(b"\n\n"):
            raise TransformOutputMaterializationReceiptError(
                "receipt bytes must end in exactly one LF"
            )
        encoded = raw[:-1]
        if not encoded:
            raise TransformOutputMaterializationReceiptError("receipt JSON payload is empty")
        _preflight_json_bytes(encoded)
        try:
            payload = json.loads(
                encoded,
                object_pairs_hook=_pairs,
                parse_constant=_constant,
                parse_float=_floating,
                parse_int=_integer,
            )
        except TransformOutputMaterializationReceiptError:
            raise
        except (
            MemoryError,
            UnicodeDecodeError,
            json.JSONDecodeError,
            RecursionError,
            ValueError,
        ) as exc:
            raise TransformOutputMaterializationReceiptError("receipt JSON is invalid") from exc
        _bounded(payload)
        if _canonical(payload) + b"\n" != raw:
            raise TransformOutputMaterializationReceiptError(
                "receipt bytes are not strict canonical JSON"
            )
        root = _object(
            payload,
            frozenset(
                {
                    "schema_version",
                    "kind",
                    "original_materialization_id",
                    "transaction_generation_identity_sha256",
                    "disposition_entry",
                    "materialization_scope",
                    "attestation",
                    "receipt_sha256",
                }
            ),
            "receipt",
        )
        _schema_identity(
            root,
            schema_version=cls.schema_version,
            kind=cls.kind,
            label="receipt",
        )
        entry = _parse_entry(root["disposition_entry"])
        attestation_data = _object(
            root["attestation"],
            frozenset({"table_name", "row_count", "schema_sha256", "content_sha256"}),
            "attestation",
        )
        try:
            attestation = TransformOutputAttestation(
                table_name=cast("Any", attestation_data["table_name"]),
                row_count=cast("Any", attestation_data["row_count"]),
                schema_sha256=cast("Any", attestation_data["schema_sha256"]),
                content_sha256=cast("Any", attestation_data["content_sha256"]),
            )
        except ValueError as exc:
            raise TransformOutputMaterializationReceiptError("attestation is invalid") from exc
        receipt = _construct_receipt(
            token=_CONSTRUCTION_TOKEN,
            original_materialization_id=cast("Any", root["original_materialization_id"]),
            transaction_generation_identity_sha256=cast(
                "Any", root["transaction_generation_identity_sha256"]
            ),
            disposition_entry=entry,
            materialization_scope=root["materialization_scope"],
            attestation=attestation,
            expected_receipt_sha256=root["receipt_sha256"],
        )
        if receipt.canonical_bytes() != raw:
            raise TransformOutputMaterializationReceiptError(
                "receipt differs from its exact canonical reconstruction"
            )
        return cast("Self", receipt)


def compile_transform_output_materialization_receipt(
    *,
    original_materialization_id: str,
    transaction_generation_identity_sha256: str,
    disposition_entry: CurrentTransformOutputDispositionV1,
    attestation: TransformOutputAttestation,
) -> TransformOutputMaterializationReceiptV1:
    """Compile one verifier-supplied materialization into immutable local authority."""

    receipt = _construct_receipt(
        token=_CONSTRUCTION_TOKEN,
        original_materialization_id=original_materialization_id,
        transaction_generation_identity_sha256=transaction_generation_identity_sha256,
        disposition_entry=disposition_entry,
        materialization_scope=_SCOPE,
        attestation=attestation,
    )
    try:
        replayed = TransformOutputMaterializationReceiptV1.from_canonical_bytes(
            receipt.canonical_bytes()
        )
    except ValueError as exc:
        raise TransformOutputMaterializationReceiptError(
            "compiled receipt is not strict replayable authority"
        ) from exc
    if replayed.to_dict() != receipt.to_dict():
        raise TransformOutputMaterializationReceiptError(
            "compiled receipt differs after strict replay"
        )
    return replayed


def _construct_receipt(
    *,
    token: object,
    original_materialization_id: str,
    transaction_generation_identity_sha256: str,
    disposition_entry: CurrentTransformOutputDispositionV1,
    materialization_scope: object,
    attestation: TransformOutputAttestation,
    expected_receipt_sha256: object | None = None,
) -> TransformOutputMaterializationReceiptV1:
    if token is not _CONSTRUCTION_TOKEN:
        raise TransformOutputMaterializationReceiptError("receipt construction token is invalid")
    _identifier(original_materialization_id, "original_materialization_id")
    _sha(transaction_generation_identity_sha256, "transaction_generation_identity_sha256")
    if type(disposition_entry) is not CurrentTransformOutputDispositionV1:
        raise TransformOutputMaterializationReceiptError("disposition_entry has a foreign type")
    if materialization_scope != _SCOPE:
        raise TransformOutputMaterializationReceiptError(
            "materialization_scope must be primary_working_duckdb"
        )
    if (
        type(attestation) is not TransformOutputAttestation
        or attestation.table_name != disposition_entry.output_name
    ):
        raise TransformOutputMaterializationReceiptError(
            "attestation differs from disposition output"
        )
    instance = object.__new__(TransformOutputMaterializationReceiptV1)
    object.__setattr__(instance, "original_materialization_id", original_materialization_id)
    object.__setattr__(
        instance, "transaction_generation_identity_sha256", transaction_generation_identity_sha256
    )
    object.__setattr__(instance, "disposition_entry", disposition_entry)
    object.__setattr__(instance, "materialization_scope", _SCOPE)
    object.__setattr__(instance, "attestation", attestation)
    receipt_sha256 = _digest(instance._preimage())
    if (
        expected_receipt_sha256 is not None
        and _sha(expected_receipt_sha256, "receipt_sha256") != receipt_sha256
    ):
        raise TransformOutputMaterializationReceiptError("receipt_sha256 is not derived")
    object.__setattr__(instance, "receipt_sha256", receipt_sha256)
    instance.canonical_bytes()
    return instance
