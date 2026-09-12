"""Scalar W2 operation and persistence receipts.

This leaf seals the content-independent request-attempt key, the scalar roots
needed to promote one completed W2 public candidate, and the exact keyed
post-commit readback of the resulting operation row.  It deliberately does
not import body, projection, ownership, schema, staging, or store DTOs.
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass, fields
from typing import Any, ClassVar, Final, Never, Self, cast

from nbadb.contracts.raw_request_authority import MAX_AUTHORITY_ROWS, RequestObservationV2
from nbadb.contracts.raw_request_observation_order import (
    canonical_raw_request_observations,
)

__all__ = [
    "W2_OPERATION_SCHEMA_VERSION",
    "W2OperationError",
    "W2OperationKeyV1",
    "W2OperationPersistenceReceiptV1",
    "W2OperationReceiptV1",
    "w2_committed_staging_readback_root",
]


W2_OPERATION_SCHEMA_VERSION: Final = 1

_MAX_ORDINAL: Final = (1 << 63) - 1
_MAX_OPERATION_ROWS: Final = 14_000_000
_MAX_CANONICAL_BYTES: Final = 256 * 1024
_MAX_JSON_DEPTH: Final = 32
_MAX_JSON_NODES: Final = 4_096
_MAX_JSON_STRING_BYTES: Final = 64 * 1024
_MAX_JSON_NUMBER_BYTES: Final = 20
_SHA256_RE: Final = re.compile(r"[0-9a-f]{64}\Z")

_KEY_KIND: Final = "nbadb_w2_operation_key_v1"
_RECEIPT_KIND: Final = "nbadb_w2_operation_receipt_v1"
_PERSISTENCE_KIND: Final = "nbadb_w2_operation_persistence_receipt_v1"
_ATTEMPT_ROOT_KIND: Final = "nbadb_w2_operation_attempts_v1"
_COMMITTED_READBACK_ROOT_KIND: Final = "nbadb_w2_committed_staging_readbacks_v1"
_PERSISTENCE_READBACK_ROOT_KIND: Final = "nbadb_w2_operation_post_commit_readback_v1"

_BODY_EMPTY_ROOT_KINDS: Final = {
    "body_blob_root_sha256": "nbadb_body_value_projection_body_blobs_v1",
    "body_blob_readback_root_sha256": "nbadb_body_value_projection_body_readbacks_v1",
    "parser_input_object_root_sha256": "nbadb_body_value_projection_parser_inputs_v1",
    "bodyless_packet_root_sha256": "nbadb_body_value_projection_bodyless_packets_v1",
    "bodyless_readback_root_sha256": "nbadb_body_value_projection_bodyless_readbacks_v1",
    "observation_source_root_sha256": "nbadb_body_value_projection_sources_v1",
}
_OWNERSHIP_EMPTY_ROOT_KINDS: Final = {
    "ownership_observation_root_sha256": "nbadb_lossless_owned_observations_v1",
    "ownership_partition_root_sha256": "nbadb_lossless_ownership_partitions_v1",
    "ownership_binding_root_sha256": "nbadb_lossless_ownership_bindings_v1",
    "ownership_source_record_root_sha256": "nbadb_lossless_owned_source_records_v1",
    "representation_assignment_root_sha256": "nbadb_lossless_representation_assignments_v1",
}
_PROJECTION_EMPTY_ROOT_KINDS: Final = {
    "projection_partition_root_sha256": "nbadb_value_projection_partitions_v1",
    "projection_item_root_sha256": "nbadb_value_projection_items_v1",
    "partition_equality_root_sha256": "nbadb_value_projection_partition_equalities_v1",
    "item_equality_root_sha256": "nbadb_value_projection_item_equalities_v1",
}
_PUBLIC_RELATION_EMPTY_ROOT_KINDS: Final = {
    "result_cell_row_root_sha256": "nbadb_public_projection_result_cell_rows_v1",
    "stats_lossless_row_root_sha256": "nbadb_public_projection_stats_lossless_rows_v1",
    "live_lossless_row_root_sha256": "nbadb_public_projection_live_lossless_rows_v1",
    "value_representation_row_root_sha256": (
        "nbadb_public_projection_value_representation_rows_v1"
    ),
    "route_field_landing_row_root_sha256": ("nbadb_public_projection_route_field_landing_rows_v1"),
}
_COUNT_ROOT_FIELDS: Final = (
    ("committed_staging_readback_count", "committed_staging_readback_root_sha256"),
    ("body_blob_count", "body_blob_root_sha256"),
    ("body_blob_readback_count", "body_blob_readback_root_sha256"),
    ("parser_input_object_count", "parser_input_object_root_sha256"),
    ("bodyless_packet_count", "bodyless_packet_root_sha256"),
    ("bodyless_readback_count", "bodyless_readback_root_sha256"),
    ("observation_source_count", "observation_source_root_sha256"),
    ("ownership_observation_count", "ownership_observation_root_sha256"),
    ("ownership_partition_count", "ownership_partition_root_sha256"),
    ("ownership_binding_count", "ownership_binding_root_sha256"),
    ("ownership_source_record_count", "ownership_source_record_root_sha256"),
    ("expected_unit_count", "expected_unit_root_sha256"),
    ("representation_assignment_count", "representation_assignment_root_sha256"),
    ("route_field_landing_count", "route_field_landing_root_sha256"),
    ("projection_partition_count", "projection_partition_root_sha256"),
    ("projection_item_count", "projection_item_root_sha256"),
    ("partition_equality_count", "partition_equality_root_sha256"),
    ("item_equality_count", "item_equality_root_sha256"),
    ("result_cell_row_count", "result_cell_row_root_sha256"),
    ("stats_lossless_row_count", "stats_lossless_row_root_sha256"),
    ("live_lossless_row_count", "live_lossless_row_root_sha256"),
    ("value_representation_row_count", "value_representation_row_root_sha256"),
    ("route_field_landing_row_count", "route_field_landing_row_root_sha256"),
)


class W2OperationError(ValueError):
    """A W2 operation key, receipt, or persistence proof is invalid."""


def _fail(message: str) -> Never:
    raise W2OperationError(message) from None


def _require_exact_class(cls: type[object], expected: type[object], *, label: str) -> None:
    if cls is not expected:
        _fail(f"{label} has a foreign exact class")


def _exact_sha256(value: object, *, label: str) -> str:
    if type(value) is not str or _SHA256_RE.fullmatch(value) is None:
        _fail(f"{label} must be one exact lowercase SHA-256")
    return value


def _exact_nonnegative(value: object, *, label: str, maximum: int) -> int:
    if type(value) is not int or value < 0 or value > maximum:
        _fail(f"{label} must be one bounded exact nonnegative integer")
    return value


def _preflight_builtin_graph(value: object) -> None:
    stack: list[tuple[object, int]] = [(value, 0)]
    nodes = 0
    string_bytes = 0
    while stack:
        item, depth = stack.pop()
        nodes += 1
        if nodes > _MAX_JSON_NODES or depth > _MAX_JSON_DEPTH:
            _fail("W2 operation canonical input exceeds its structural bound")
        if item is None or type(item) is bool:
            continue
        if type(item) is int:
            if item < -_MAX_ORDINAL or item > _MAX_ORDINAL:
                _fail("W2 operation canonical input contains an unbounded integer")
            continue
        if type(item) is str:
            try:
                encoded = item.encode("utf-8", errors="strict")
            except UnicodeEncodeError:
                _fail("W2 operation canonical input contains invalid Unicode")
            string_bytes += len(encoded)
            if string_bytes > _MAX_JSON_STRING_BYTES:
                _fail("W2 operation canonical input exceeds its string-byte bound")
            continue
        if type(item) in {tuple, list}:
            sequence = cast("tuple[object, ...] | list[object]", item)
            stack.extend((child, depth + 1) for child in reversed(sequence))
            continue
        if type(item) is dict:
            mapping = cast("dict[object, object]", item)
            for key, child in reversed(tuple(mapping.items())):
                if type(key) is not str:
                    _fail("W2 operation canonical input contains a foreign mapping key")
                try:
                    key_bytes = key.encode("utf-8", errors="strict")
                except UnicodeEncodeError:
                    _fail("W2 operation canonical input contains invalid Unicode")
                string_bytes += len(key_bytes)
                if string_bytes > _MAX_JSON_STRING_BYTES:
                    _fail("W2 operation canonical input exceeds its string-byte bound")
                stack.append((child, depth + 1))
            continue
        _fail("W2 operation canonical input contains a foreign exact type")


def _canonical_json_bytes(value: object, *, maximum_bytes: int = _MAX_CANONICAL_BYTES) -> bytes:
    _preflight_builtin_graph(value)
    failed = False
    try:
        encoded = json.dumps(
            value,
            allow_nan=False,
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        ).encode("utf-8", errors="strict")
    except (RecursionError, TypeError, UnicodeEncodeError, ValueError):
        failed = True
        encoded = b""
    if failed:
        _fail("W2 operation identity is not exact canonical JSON")
    if not encoded or len(encoded) > maximum_bytes:
        _fail("W2 operation canonical JSON exceeds its byte bound")
    return encoded


def _canonical_sha256(value: object) -> str:
    return hashlib.sha256(_canonical_json_bytes(value)).hexdigest()


def _preflight_json_bytes(value: object, *, maximum_bytes: int) -> bytes:
    if type(value) is not bytes or not value or len(value) > maximum_bytes:
        _fail("W2 operation canonical bytes are empty, foreign, or over-bound")
    raw = cast("bytes", value)
    depth = 0
    nodes = 1
    in_string = False
    escaped = False
    string_bytes = 0
    index = 0
    while index < len(raw):
        byte = raw[index]
        if in_string:
            if escaped:
                escaped = False
                string_bytes += 1
            elif byte == 0x5C:
                escaped = True
                string_bytes += 1
            elif byte == 0x22:
                in_string = False
                if string_bytes > _MAX_JSON_STRING_BYTES:
                    _fail("W2 operation JSON contains an over-bound string")
                string_bytes = 0
            else:
                string_bytes += 1
            index += 1
            continue
        if byte == 0x22:
            in_string = True
        elif byte in (0x7B, 0x5B):
            depth += 1
            nodes += 1
        elif byte in (0x7D, 0x5D):
            depth -= 1
            if depth < 0:
                _fail("W2 operation JSON is structurally invalid")
        elif byte in (0x2C, 0x3A):
            nodes += 1
        elif byte == 0x2D or 0x30 <= byte <= 0x39:
            end = index + 1
            while end < len(raw) and raw[end] not in b" \t\r\n,]}":
                end += 1
            if end - index > _MAX_JSON_NUMBER_BYTES:
                _fail("W2 operation JSON contains an over-bound number token")
            index = end - 1
        if depth > _MAX_JSON_DEPTH or nodes > _MAX_JSON_NODES:
            _fail("W2 operation JSON exceeds its lexical structure bound")
        index += 1
    if in_string or escaped or depth != 0:
        _fail("W2 operation JSON is structurally invalid")
    return raw


def _reject_duplicate_keys(pairs: list[tuple[str, object]]) -> dict[str, object]:
    decoded: dict[str, object] = {}
    for key, value in pairs:
        if key in decoded:
            _fail("W2 operation JSON contains a duplicate object key")
        decoded[key] = value
    return decoded


def _bounded_json_integer(token: str) -> int:
    if len(token) > _MAX_JSON_NUMBER_BYTES:
        _fail("W2 operation JSON contains an over-bound integer token")
    value = int(token)
    if value < -_MAX_ORDINAL or value > _MAX_ORDINAL:
        _fail("W2 operation JSON contains an unbounded integer")
    return value


def _reject_json_number(_token: str) -> Never:
    _fail("W2 operation JSON contains a non-integer number")


def _decode_canonical_json(value: object, *, maximum_bytes: int) -> object:
    raw = _preflight_json_bytes(value, maximum_bytes=maximum_bytes)
    failed = False
    decoded: object = None
    try:
        decoded = json.loads(
            raw,
            object_pairs_hook=_reject_duplicate_keys,
            parse_int=_bounded_json_integer,
            parse_float=_reject_json_number,
            parse_constant=_reject_json_number,
        )
    except W2OperationError:
        raise
    except (json.JSONDecodeError, RecursionError, TypeError, UnicodeDecodeError, ValueError):
        failed = True
    if failed:
        _fail("W2 operation canonical JSON is invalid")
    if _canonical_json_bytes(decoded, maximum_bytes=maximum_bytes) != raw:
        _fail("W2 operation JSON is not in canonical byte form")
    return decoded


def _row_fields(cls: type[object]) -> tuple[str, ...]:
    return ("schema_version", *(item.name for item in fields(cls)))


def _strict_row(value: object, *, cls: type[object], label: str) -> dict[str, object]:
    if type(value) is not dict:
        _fail(f"{label} must be one exact built-in mapping")
    row = cast("dict[object, object]", value)
    expected = _row_fields(cls)
    if any(type(key) is not str for key in row) or tuple(row) != expected:
        _fail(f"{label} has a foreign ordered field shape")
    if type(row["schema_version"]) is not int or row["schema_version"] != 1:
        _fail(f"{label} schema version is invalid")
    return cast("dict[str, object]", value)


def _length_framed_root(
    *,
    prefix: bytes,
    kind: str,
    scopes: tuple[str, ...],
    item_sha256s: tuple[str, ...],
    maximum: int,
    include_schema_version: bool,
) -> str:
    if type(kind) is not str or not kind or type(scopes) is not tuple:
        _fail("W2 operation ordered-root domain is foreign")
    if type(item_sha256s) is not tuple or len(item_sha256s) > maximum:
        _fail("W2 operation ordered-root inventory is foreign or over-bound")
    digest = hashlib.sha256()
    digest.update(prefix)

    def feed(raw: bytes) -> None:
        digest.update(len(raw).to_bytes(8, byteorder="big", signed=False))
        digest.update(raw)

    if include_schema_version:
        feed(b"1")
    feed(kind.encode("utf-8"))
    for scope in scopes:
        feed(_exact_sha256(scope, label="ordered-root scope").encode("ascii"))
    feed(str(len(item_sha256s)).encode("ascii"))
    for ordinal, item_sha256 in enumerate(item_sha256s):
        feed(str(ordinal).encode("ascii"))
        feed(_exact_sha256(item_sha256, label="ordered-root item").encode("ascii"))
    return digest.hexdigest()


def _legacy_root(*, kind: str, item_sha256s: tuple[str, ...]) -> str:
    if type(item_sha256s) is not tuple:
        _fail("W2 operation legacy root inventory is foreign")
    for item in item_sha256s:
        _exact_sha256(item, label="legacy ordered-root item")
    return _canonical_sha256(
        {
            "count": len(item_sha256s),
            "items": list(item_sha256s),
            "kind": kind,
            "schema_version": 1,
        }
    )


def _public_expected_unit_root(
    *, raw_authority_bundle_sha256: str, item_sha256s: tuple[str, ...]
) -> str:
    bundle = _exact_sha256(raw_authority_bundle_sha256, label="expected-unit root bundle")
    if type(item_sha256s) is not tuple:
        _fail("expected-unit root inventory is foreign")
    digest = hashlib.sha256()
    digest.update(b'{"count":')
    digest.update(str(len(item_sha256s)).encode("ascii"))
    digest.update(b',"items":[')
    for ordinal, item in enumerate(item_sha256s):
        _exact_sha256(item, label="expected-unit root item")
        if ordinal:
            digest.update(b",")
        digest.update(_canonical_json_bytes(item, maximum_bytes=256))
    digest.update(b'],"kind":"nbadb_expected_value_unit_ordered_root_v1"')
    digest.update(b',"raw_authority_bundle_sha256":')
    digest.update(_canonical_json_bytes(bundle, maximum_bytes=256))
    digest.update(b',"schema_version":1}')
    return digest.hexdigest()


def _route_landing_root(*, raw_authority_bundle_sha256: str, item_sha256s: tuple[str, ...]) -> str:
    bundle = _exact_sha256(raw_authority_bundle_sha256, label="route-field root bundle")
    if type(item_sha256s) is not tuple:
        _fail("route-field root inventory is foreign")
    for item in item_sha256s:
        _exact_sha256(item, label="route-field root item")
    return _canonical_sha256(
        {
            "count": len(item_sha256s),
            "items": list(item_sha256s),
            "kind": "raw_nba_api_route_field_rows_v1",
            "raw_authority_bundle_sha256": bundle,
        }
    )


def _public_relation_root(
    *, kind: str, raw_authority_bundle_sha256: str, item_sha256s: tuple[str, ...]
) -> str:
    return _length_framed_root(
        prefix=b"nbadb-public-table-value-projection-root-v1\x00",
        kind=kind,
        scopes=(raw_authority_bundle_sha256,),
        item_sha256s=item_sha256s,
        maximum=_MAX_OPERATION_ROWS,
        include_schema_version=False,
    )


def _value_projection_root(
    *, kind: str, raw_authority_bundle_sha256: str, item_sha256s: tuple[str, ...]
) -> str:
    return _length_framed_root(
        prefix=b"nbadb-value-projection-length-framed-root-v1\x00",
        kind=kind,
        scopes=(raw_authority_bundle_sha256,),
        item_sha256s=item_sha256s,
        maximum=_MAX_OPERATION_ROWS,
        include_schema_version=True,
    )


def _body_projection_root(
    *, kind: str, raw_authority_bundle_sha256: str, item_sha256s: tuple[str, ...]
) -> str:
    return _value_projection_root(
        kind=kind,
        raw_authority_bundle_sha256=raw_authority_bundle_sha256,
        item_sha256s=item_sha256s,
    )


def _attempt_root(item_sha256s: tuple[str, ...]) -> str:
    return _length_framed_root(
        prefix=b"nbadb-w2-operation-attempt-root-v1\x00",
        kind=_ATTEMPT_ROOT_KIND,
        scopes=(),
        item_sha256s=item_sha256s,
        maximum=MAX_AUTHORITY_ROWS,
        include_schema_version=True,
    )


def w2_committed_staging_readback_root(
    *,
    raw_authority_bundle_sha256: str,
    readback_receipt_sha256s: tuple[str, ...],
) -> str:
    """Seal canonical committed staging readback receipts for one Raw bundle."""

    return _length_framed_root(
        prefix=b"nbadb-w2-operation-root-v1\x00",
        kind=_COMMITTED_READBACK_ROOT_KIND,
        scopes=(raw_authority_bundle_sha256,),
        item_sha256s=readback_receipt_sha256s,
        maximum=_MAX_OPERATION_ROWS,
        include_schema_version=True,
    )


def _post_commit_readback_root(
    *,
    operation_key_sha256: str,
    w2_operation_schema_sha256: str,
    row_sha256s: tuple[str, ...],
) -> str:
    return _length_framed_root(
        prefix=b"nbadb-w2-operation-persistence-root-v1\x00",
        kind=_PERSISTENCE_READBACK_ROOT_KIND,
        scopes=(operation_key_sha256, w2_operation_schema_sha256),
        item_sha256s=row_sha256s,
        maximum=1,
        include_schema_version=True,
    )


@dataclass(frozen=True, slots=True)
class W2OperationKeyV1:
    """Content-independent operation key over exact request attempts."""

    operation_key_sha256: str
    operation_attempt_count: int
    operation_attempt_root_sha256: str

    schema_version: ClassVar[int] = W2_OPERATION_SCHEMA_VERSION
    kind: ClassVar[str] = _KEY_KIND

    def __post_init__(self) -> None:
        _exact_sha256(self.operation_key_sha256, label="W2 operation key")
        count = _exact_nonnegative(
            self.operation_attempt_count,
            label="W2 operation attempt count",
            maximum=MAX_AUTHORITY_ROWS,
        )
        if count == 0:
            _fail("W2 operation key requires at least one request attempt")
        _exact_sha256(self.operation_attempt_root_sha256, label="W2 operation attempt root")
        if self.operation_key_sha256 != _canonical_sha256(self.identity_payload()):
            _fail("W2 operation key digest differs from its exact attempt authority")

    @classmethod
    def build(cls, observations: tuple[RequestObservationV2, ...]) -> Self:
        _require_exact_class(cls, W2OperationKeyV1, label="W2 operation key")
        if type(observations) is not tuple or not observations:
            _fail("W2 operation key requires one exact nonempty observation tuple")
        failed = False
        try:
            ordered = canonical_raw_request_observations(observations, selection=None)
        except Exception:
            failed = True
            ordered = ()
        if failed:
            _fail("W2 operation observations fail exact canonical authority")
        attempt_digests: list[str] = []
        for observation in ordered:
            failed = False
            try:
                attempt_bytes = observation.attempt.to_canonical_bytes()
            except Exception:
                failed = True
                attempt_bytes = b""
            if failed or type(attempt_bytes) is not bytes:
                _fail("W2 operation attempt cannot be canonically replayed")
            attempt_digests.append(hashlib.sha256(attempt_bytes).hexdigest())
        values = {
            "operation_attempt_count": len(attempt_digests),
            "operation_attempt_root_sha256": _attempt_root(tuple(attempt_digests)),
        }
        identity = {"schema_version": cls.schema_version, "kind": cls.kind, **values}
        return cls(operation_key_sha256=_canonical_sha256(identity), **values)

    def identity_payload(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "kind": self.kind,
            "operation_attempt_count": self.operation_attempt_count,
            "operation_attempt_root_sha256": self.operation_attempt_root_sha256,
        }

    def to_row(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            **{item.name: getattr(self, item.name) for item in fields(self)},
        }

    def canonical_bytes(self) -> bytes:
        return _canonical_json_bytes(self.to_row())

    @classmethod
    def from_row(cls, value: object, *, expected_operation_key_sha256: str) -> Self:
        _require_exact_class(cls, W2OperationKeyV1, label="W2 operation key")
        expected = _exact_sha256(expected_operation_key_sha256, label="expected W2 operation key")
        row = _strict_row(value, cls=cls, label="W2 operation key row")
        if (
            _exact_sha256(row["operation_key_sha256"], label="candidate W2 operation key")
            != expected
        ):
            _fail("W2 operation key row differs from its external authority pin")
        try:
            return cls(**cast("Any", {item.name: row[item.name] for item in fields(cls)}))
        except W2OperationError:
            raise
        except Exception:
            pass
        _fail("W2 operation key row failed exact semantic replay")

    @classmethod
    def from_canonical_bytes(cls, value: object, *, expected_operation_key_sha256: str) -> Self:
        _require_exact_class(cls, W2OperationKeyV1, label="W2 operation key")
        _exact_sha256(expected_operation_key_sha256, label="expected W2 operation key")
        decoded = _decode_canonical_json(value, maximum_bytes=_MAX_CANONICAL_BYTES)
        if type(decoded) is not dict:
            _fail("W2 operation key bytes do not contain one exact row")
        mapping = cast("dict[str, object]", decoded)
        expected_fields = _row_fields(cls)
        if tuple(mapping) != tuple(sorted(expected_fields)):
            _fail("W2 operation key bytes have foreign fields")
        candidate = cls.from_row(
            {name: mapping[name] for name in expected_fields},
            expected_operation_key_sha256=expected_operation_key_sha256,
        )
        if value != candidate.canonical_bytes():
            _fail("W2 operation key bytes are not exact canonical replay")
        return candidate


@dataclass(frozen=True, slots=True)
class W2OperationReceiptV1:
    """One scalar seal over an exact committed W2 public candidate."""

    operation_receipt_sha256: str
    operation_key_sha256: str
    operation_attempt_count: int
    operation_attempt_root_sha256: str
    raw_authority_bundle_sha256: str
    committed_staging_readback_count: int
    committed_staging_readback_root_sha256: str
    body_value_projection_receipt_sha256: str
    body_projection_policy_sha256: str
    body_blob_inventory_sha256: str
    body_blob_count: int
    body_blob_root_sha256: str
    body_blob_readback_count: int
    body_blob_readback_root_sha256: str
    body_blob_byte_count: int
    parser_input_object_count: int
    parser_input_object_root_sha256: str
    declared_bodyless_authority_sha256: str
    bodyless_packet_count: int
    bodyless_packet_root_sha256: str
    bodyless_readback_count: int
    bodyless_readback_root_sha256: str
    bodyless_packet_byte_count: int
    observation_source_count: int
    observation_source_root_sha256: str
    lossless_ownership_receipt_sha256: str
    ownership_observation_count: int
    ownership_observation_root_sha256: str
    ownership_partition_count: int
    ownership_partition_root_sha256: str
    ownership_fixed_zero_landing_root_sha256: str
    ownership_binding_count: int
    ownership_binding_root_sha256: str
    ownership_source_record_count: int
    ownership_source_record_root_sha256: str
    expected_unit_inventory_sha256: str
    expected_unit_count: int
    expected_unit_root_sha256: str
    representation_assignment_count: int
    representation_assignment_root_sha256: str
    route_field_landing_receipt_sha256: str
    route_field_landing_count: int
    route_field_landing_root_sha256: str
    value_projection_plan_sha256: str
    public_table_value_projection_receipt_sha256: str
    value_projection_equality_receipt_sha256: str
    projection_sha256: str
    projection_partition_count: int
    projection_partition_root_sha256: str
    projection_item_count: int
    projection_item_root_sha256: str
    partition_equality_count: int
    partition_equality_root_sha256: str
    item_equality_count: int
    item_equality_root_sha256: str
    equality_root_sha256: str
    result_cell_schema_sha256: str
    result_cell_row_count: int
    result_cell_row_root_sha256: str
    stats_lossless_schema_sha256: str
    stats_lossless_row_count: int
    stats_lossless_row_root_sha256: str
    live_lossless_schema_sha256: str
    live_lossless_row_count: int
    live_lossless_row_root_sha256: str
    value_representation_schema_sha256: str
    value_representation_row_count: int
    value_representation_row_root_sha256: str
    route_field_landing_schema_sha256: str
    route_field_landing_row_count: int
    route_field_landing_row_root_sha256: str
    w2_operation_schema_sha256: str

    schema_version: ClassVar[int] = W2_OPERATION_SCHEMA_VERSION
    kind: ClassVar[str] = _RECEIPT_KIND

    def __post_init__(self) -> None:
        for item in fields(self):
            value = getattr(self, item.name)
            if item.name.endswith("_sha256"):
                _exact_sha256(value, label=item.name)
            elif item.name.endswith("_count"):
                maximum = (
                    _MAX_ORDINAL
                    if item.name in {"body_blob_byte_count", "bodyless_packet_byte_count"}
                    else _MAX_OPERATION_ROWS
                )
                _exact_nonnegative(value, label=item.name, maximum=maximum)
        key = W2OperationKeyV1(
            operation_key_sha256=self.operation_key_sha256,
            operation_attempt_count=self.operation_attempt_count,
            operation_attempt_root_sha256=self.operation_attempt_root_sha256,
        )
        if key.operation_attempt_count > MAX_AUTHORITY_ROWS:
            _fail("W2 operation receipt attempt count exceeds Raw authority")
        self._validate_aggregate_algebra()
        self._validate_empty_roots()
        if self.operation_receipt_sha256 != _canonical_sha256(self.identity_payload()):
            _fail("W2 operation receipt digest differs from its exact scalar identity")

    def _validate_aggregate_algebra(self) -> None:
        if (
            self.body_blob_count != self.body_blob_readback_count
            or self.body_blob_count != self.parser_input_object_count
            or self.bodyless_packet_count != self.bodyless_readback_count
            or self.observation_source_count != self.body_blob_count + self.bodyless_packet_count
        ):
            _fail("W2 operation body/bodyless source denominators are inconsistent")
        if (self.body_blob_count == 0) != (self.body_blob_byte_count == 0):
            _fail("W2 operation body-byte zero algebra is inconsistent")
        if (self.bodyless_packet_count == 0) != (self.bodyless_packet_byte_count == 0):
            _fail("W2 operation bodyless-byte zero algebra is inconsistent")
        if self.ownership_observation_count != self.observation_source_count:
            _fail("W2 operation ownership/source observation denominators differ")
        if self.operation_attempt_count < self.ownership_observation_count:
            _fail("W2 operation attempt count cannot be below owned observations")
        if self.committed_staging_readback_count < self.ownership_observation_count:
            _fail("W2 operation staging readbacks cannot be below owned observations")
        if self.ownership_partition_count < self.ownership_observation_count:
            _fail("W2 operation ownership partitions cannot be below owned observations")
        if self.ownership_partition_count < self.expected_unit_count:
            _fail("W2 operation ownership partitions cannot be below expected units")
        if self.route_field_landing_count < self.expected_unit_count:
            _fail("W2 operation route-field rows cannot be below expected units")
        if self.ownership_partition_count != self.projection_partition_count:
            _fail("W2 operation ownership/projection partition denominators differ")
        if (
            self.expected_unit_count != self.representation_assignment_count
            or self.value_representation_row_count != self.representation_assignment_count
        ):
            _fail("W2 operation expected-unit assignment denominators are inconsistent")
        if (
            self.ownership_binding_count != self.ownership_source_record_count
            or self.ownership_binding_count != self.projection_item_count
        ):
            _fail(
                "W2 operation ownership binding/source-record/projection-item denominators differ"
            )
        if (
            self.result_cell_row_count
            + self.stats_lossless_row_count
            + self.live_lossless_row_count
            != self.ownership_source_record_count
        ):
            _fail("W2 operation public data-row/source-record denominators differ")
        if self.route_field_landing_count != self.route_field_landing_row_count:
            _fail("W2 operation route-field authority/public denominators differ")
        if (
            self.projection_partition_count != self.partition_equality_count
            or self.projection_item_count != self.item_equality_count
        ):
            _fail("W2 operation projection/equality denominators are inconsistent")

    def _empty_root(self, root_field: str) -> str:
        bundle = self.raw_authority_bundle_sha256
        if root_field == "committed_staging_readback_root_sha256":
            return w2_committed_staging_readback_root(
                raw_authority_bundle_sha256=bundle,
                readback_receipt_sha256s=(),
            )
        if root_field in _BODY_EMPTY_ROOT_KINDS:
            return _body_projection_root(
                kind=_BODY_EMPTY_ROOT_KINDS[root_field],
                raw_authority_bundle_sha256=bundle,
                item_sha256s=(),
            )
        if root_field in _OWNERSHIP_EMPTY_ROOT_KINDS:
            return _legacy_root(
                kind=_OWNERSHIP_EMPTY_ROOT_KINDS[root_field],
                item_sha256s=(),
            )
        if root_field == "expected_unit_root_sha256":
            return _public_expected_unit_root(
                raw_authority_bundle_sha256=bundle,
                item_sha256s=(),
            )
        if root_field == "route_field_landing_root_sha256":
            return _route_landing_root(
                raw_authority_bundle_sha256=bundle,
                item_sha256s=(),
            )
        if root_field in _PROJECTION_EMPTY_ROOT_KINDS:
            return _value_projection_root(
                kind=_PROJECTION_EMPTY_ROOT_KINDS[root_field],
                raw_authority_bundle_sha256=bundle,
                item_sha256s=(),
            )
        if root_field in _PUBLIC_RELATION_EMPTY_ROOT_KINDS:
            return _public_relation_root(
                kind=_PUBLIC_RELATION_EMPTY_ROOT_KINDS[root_field],
                raw_authority_bundle_sha256=bundle,
                item_sha256s=(),
            )
        _fail("W2 operation has no exact empty-root domain")

    def _validate_empty_roots(self) -> None:
        for count_field, root_field in _COUNT_ROOT_FIELDS:
            count = cast("int", getattr(self, count_field))
            root = cast("str", getattr(self, root_field))
            empty = self._empty_root(root_field)
            if (count == 0) != (root == empty):
                _fail(f"W2 operation {root_field} has inconsistent zero-root algebra")

    @classmethod
    def build(cls, *, operation_key: W2OperationKeyV1, **values: object) -> Self:
        _require_exact_class(cls, W2OperationReceiptV1, label="W2 operation receipt")
        if type(operation_key) is not W2OperationKeyV1:
            _fail("W2 operation receipt requires one exact operation-key DTO")
        key = W2OperationKeyV1.from_row(
            operation_key.to_row(),
            expected_operation_key_sha256=operation_key.operation_key_sha256,
        )
        excluded = {
            "operation_receipt_sha256",
            "operation_key_sha256",
            "operation_attempt_count",
            "operation_attempt_root_sha256",
        }
        required = {item.name for item in fields(cls) if item.name not in excluded}
        if any(type(name) is not str for name in values) or set(values) != required:
            _fail("W2 operation receipt builder fields are missing or foreign")
        ordered: dict[str, object] = {}
        for item in fields(cls):
            if item.name == "operation_receipt_sha256":
                continue
            if item.name == "operation_key_sha256":
                ordered[item.name] = key.operation_key_sha256
            elif item.name == "operation_attempt_count":
                ordered[item.name] = key.operation_attempt_count
            elif item.name == "operation_attempt_root_sha256":
                ordered[item.name] = key.operation_attempt_root_sha256
            else:
                ordered[item.name] = values[item.name]
        identity = {"schema_version": cls.schema_version, "kind": cls.kind, **ordered}
        return cls(
            operation_receipt_sha256=_canonical_sha256(identity),
            **cast("Any", ordered),
        )

    def identity_payload(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "kind": self.kind,
            **{
                item.name: getattr(self, item.name)
                for item in fields(self)
                if item.name != "operation_receipt_sha256"
            },
        }

    def to_row(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            **{item.name: getattr(self, item.name) for item in fields(self)},
        }

    def canonical_bytes(self) -> bytes:
        return _canonical_json_bytes(self.to_row())

    @classmethod
    def from_row(
        cls,
        value: object,
        *,
        expected_operation_receipt_sha256: str,
        expected_operation_key_sha256: str,
        expected_raw_authority_bundle_sha256: str,
        expected_w2_operation_schema_sha256: str,
    ) -> Self:
        _require_exact_class(cls, W2OperationReceiptV1, label="W2 operation receipt")
        pins = {
            "operation_receipt_sha256": _exact_sha256(
                expected_operation_receipt_sha256,
                label="expected W2 operation receipt",
            ),
            "operation_key_sha256": _exact_sha256(
                expected_operation_key_sha256,
                label="expected W2 operation key",
            ),
            "raw_authority_bundle_sha256": _exact_sha256(
                expected_raw_authority_bundle_sha256,
                label="expected W2 Raw bundle",
            ),
            "w2_operation_schema_sha256": _exact_sha256(
                expected_w2_operation_schema_sha256,
                label="expected W2 operation schema",
            ),
        }
        row = _strict_row(value, cls=cls, label="W2 operation receipt row")
        for name, expected in pins.items():
            if _exact_sha256(row[name], label=f"candidate {name}") != expected:
                _fail("W2 operation receipt differs from its external authority pins")
        try:
            return cls(**cast("Any", {item.name: row[item.name] for item in fields(cls)}))
        except W2OperationError:
            raise
        except Exception:
            pass
        _fail("W2 operation receipt row failed exact semantic replay")

    @classmethod
    def from_canonical_bytes(
        cls,
        value: object,
        *,
        expected_operation_receipt_sha256: str,
        expected_operation_key_sha256: str,
        expected_raw_authority_bundle_sha256: str,
        expected_w2_operation_schema_sha256: str,
    ) -> Self:
        _require_exact_class(cls, W2OperationReceiptV1, label="W2 operation receipt")
        for label, expected in (
            ("expected W2 operation receipt", expected_operation_receipt_sha256),
            ("expected W2 operation key", expected_operation_key_sha256),
            ("expected W2 Raw bundle", expected_raw_authority_bundle_sha256),
            ("expected W2 operation schema", expected_w2_operation_schema_sha256),
        ):
            _exact_sha256(expected, label=label)
        decoded = _decode_canonical_json(value, maximum_bytes=_MAX_CANONICAL_BYTES)
        if type(decoded) is not dict:
            _fail("W2 operation receipt bytes do not contain one exact row")
        mapping = cast("dict[str, object]", decoded)
        expected_fields = _row_fields(cls)
        if tuple(mapping) != tuple(sorted(expected_fields)):
            _fail("W2 operation receipt bytes have foreign fields")
        candidate = cls.from_row(
            {name: mapping[name] for name in expected_fields},
            expected_operation_receipt_sha256=expected_operation_receipt_sha256,
            expected_operation_key_sha256=expected_operation_key_sha256,
            expected_raw_authority_bundle_sha256=expected_raw_authority_bundle_sha256,
            expected_w2_operation_schema_sha256=expected_w2_operation_schema_sha256,
        )
        if value != candidate.canonical_bytes():
            _fail("W2 operation receipt bytes are not exact canonical replay")
        return candidate


@dataclass(frozen=True, slots=True)
class W2OperationPersistenceReceiptV1:
    """Read-after-commit proof for one exact W2 operation row."""

    persistence_receipt_sha256: str
    operation_key_sha256: str
    operation_receipt_sha256: str
    w2_operation_schema_sha256: str
    operation_row_sha256: str
    post_commit_readback_row_count: int
    post_commit_readback_row_sha256: str
    post_commit_readback_root_sha256: str
    replayed: bool

    schema_version: ClassVar[int] = W2_OPERATION_SCHEMA_VERSION
    kind: ClassVar[str] = _PERSISTENCE_KIND

    def __post_init__(self) -> None:
        for item in fields(self):
            value = getattr(self, item.name)
            if item.name.endswith("_sha256"):
                _exact_sha256(value, label=item.name)
        if type(self.replayed) is not bool:
            _fail("W2 operation persistence replay flag must be one exact boolean")
        if (
            type(self.post_commit_readback_row_count) is not int
            or self.post_commit_readback_row_count != 1
        ):
            _fail("W2 operation persistence requires exactly one keyed readback row")
        if self.operation_row_sha256 != self.post_commit_readback_row_sha256:
            _fail("W2 operation inserted and post-commit row hashes differ")
        expected_root = _post_commit_readback_root(
            operation_key_sha256=self.operation_key_sha256,
            w2_operation_schema_sha256=self.w2_operation_schema_sha256,
            row_sha256s=(self.post_commit_readback_row_sha256,),
        )
        if self.post_commit_readback_root_sha256 != expected_root:
            _fail("W2 operation post-commit readback root is invalid")
        if self.persistence_receipt_sha256 != _canonical_sha256(self.identity_payload()):
            _fail("W2 operation persistence digest differs from its exact semantic identity")

    @classmethod
    def build(
        cls,
        *,
        operation: W2OperationReceiptV1,
        post_commit_readback_row: object,
        replayed: bool,
    ) -> Self:
        _require_exact_class(
            cls,
            W2OperationPersistenceReceiptV1,
            label="W2 operation persistence receipt",
        )
        if type(operation) is not W2OperationReceiptV1:
            _fail("W2 operation persistence requires one exact operation receipt")
        if type(replayed) is not bool:
            _fail("W2 operation persistence replay flag must be one exact boolean")
        exact_operation = W2OperationReceiptV1.from_row(
            operation.to_row(),
            expected_operation_receipt_sha256=operation.operation_receipt_sha256,
            expected_operation_key_sha256=operation.operation_key_sha256,
            expected_raw_authority_bundle_sha256=operation.raw_authority_bundle_sha256,
            expected_w2_operation_schema_sha256=operation.w2_operation_schema_sha256,
        )
        readback = W2OperationReceiptV1.from_row(
            post_commit_readback_row,
            expected_operation_receipt_sha256=operation.operation_receipt_sha256,
            expected_operation_key_sha256=operation.operation_key_sha256,
            expected_raw_authority_bundle_sha256=operation.raw_authority_bundle_sha256,
            expected_w2_operation_schema_sha256=operation.w2_operation_schema_sha256,
        )
        if readback != exact_operation:
            _fail("W2 operation post-commit readback differs from the inserted row")
        operation_row_sha256 = hashlib.sha256(exact_operation.canonical_bytes()).hexdigest()
        readback_row_sha256 = hashlib.sha256(readback.canonical_bytes()).hexdigest()
        values: dict[str, object] = {
            "operation_key_sha256": exact_operation.operation_key_sha256,
            "operation_receipt_sha256": exact_operation.operation_receipt_sha256,
            "w2_operation_schema_sha256": exact_operation.w2_operation_schema_sha256,
            "operation_row_sha256": operation_row_sha256,
            "post_commit_readback_row_count": 1,
            "post_commit_readback_row_sha256": readback_row_sha256,
            "post_commit_readback_root_sha256": _post_commit_readback_root(
                operation_key_sha256=exact_operation.operation_key_sha256,
                w2_operation_schema_sha256=exact_operation.w2_operation_schema_sha256,
                row_sha256s=(readback_row_sha256,),
            ),
            "replayed": replayed,
        }
        identity = {
            "schema_version": cls.schema_version,
            "kind": cls.kind,
            **{name: value for name, value in values.items() if name != "replayed"},
        }
        return cls(
            persistence_receipt_sha256=_canonical_sha256(identity),
            **cast("Any", values),
        )

    def identity_payload(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "kind": self.kind,
            **{
                item.name: getattr(self, item.name)
                for item in fields(self)
                if item.name not in {"persistence_receipt_sha256", "replayed"}
            },
        }

    def to_row(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            **{item.name: getattr(self, item.name) for item in fields(self)},
        }

    def canonical_bytes(self) -> bytes:
        return _canonical_json_bytes(self.to_row())

    @classmethod
    def from_row(
        cls,
        value: object,
        *,
        expected_persistence_receipt_sha256: str,
        expected_operation_key_sha256: str,
        expected_operation_receipt_sha256: str,
        expected_w2_operation_schema_sha256: str,
        expected_operation_row_sha256: str,
    ) -> Self:
        _require_exact_class(
            cls,
            W2OperationPersistenceReceiptV1,
            label="W2 operation persistence receipt",
        )
        pins = {
            "persistence_receipt_sha256": _exact_sha256(
                expected_persistence_receipt_sha256,
                label="expected W2 persistence receipt",
            ),
            "operation_key_sha256": _exact_sha256(
                expected_operation_key_sha256,
                label="expected W2 operation key",
            ),
            "operation_receipt_sha256": _exact_sha256(
                expected_operation_receipt_sha256,
                label="expected W2 operation receipt",
            ),
            "w2_operation_schema_sha256": _exact_sha256(
                expected_w2_operation_schema_sha256,
                label="expected W2 operation schema",
            ),
            "operation_row_sha256": _exact_sha256(
                expected_operation_row_sha256,
                label="expected W2 operation row",
            ),
        }
        row = _strict_row(value, cls=cls, label="W2 operation persistence row")
        for name, expected in pins.items():
            if _exact_sha256(row[name], label=f"candidate {name}") != expected:
                _fail("W2 operation persistence differs from its external authority pins")
        try:
            return cls(**cast("Any", {item.name: row[item.name] for item in fields(cls)}))
        except W2OperationError:
            raise
        except Exception:
            pass
        _fail("W2 operation persistence row failed exact semantic replay")

    @classmethod
    def from_canonical_bytes(
        cls,
        value: object,
        *,
        expected_persistence_receipt_sha256: str,
        expected_operation_key_sha256: str,
        expected_operation_receipt_sha256: str,
        expected_w2_operation_schema_sha256: str,
        expected_operation_row_sha256: str,
    ) -> Self:
        _require_exact_class(
            cls,
            W2OperationPersistenceReceiptV1,
            label="W2 operation persistence receipt",
        )
        for label, expected in (
            ("expected W2 persistence receipt", expected_persistence_receipt_sha256),
            ("expected W2 operation key", expected_operation_key_sha256),
            ("expected W2 operation receipt", expected_operation_receipt_sha256),
            ("expected W2 operation schema", expected_w2_operation_schema_sha256),
            ("expected W2 operation row", expected_operation_row_sha256),
        ):
            _exact_sha256(expected, label=label)
        decoded = _decode_canonical_json(value, maximum_bytes=_MAX_CANONICAL_BYTES)
        if type(decoded) is not dict:
            _fail("W2 operation persistence bytes do not contain one exact row")
        mapping = cast("dict[str, object]", decoded)
        expected_fields = _row_fields(cls)
        if tuple(mapping) != tuple(sorted(expected_fields)):
            _fail("W2 operation persistence bytes have foreign fields")
        candidate = cls.from_row(
            {name: mapping[name] for name in expected_fields},
            expected_persistence_receipt_sha256=expected_persistence_receipt_sha256,
            expected_operation_key_sha256=expected_operation_key_sha256,
            expected_operation_receipt_sha256=expected_operation_receipt_sha256,
            expected_w2_operation_schema_sha256=expected_w2_operation_schema_sha256,
            expected_operation_row_sha256=expected_operation_row_sha256,
        )
        if value != candidate.canonical_bytes():
            _fail("W2 operation persistence bytes are not exact canonical replay")
        return candidate
