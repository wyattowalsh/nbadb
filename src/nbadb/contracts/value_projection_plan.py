"""Dependency-pure value-free planning authority for body projection.

The module deliberately imports only the Python standard library.  It replays
the public-value and lossless-ownership semantic rows from exact built-in
values, then seals the additional source, occurrence, and source-record joins
needed by a later body projector.  No provider payload value is stored here.
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass, fields
from typing import Any, ClassVar, Final, Literal, Never, Self, cast

__all__ = [
    "VALUE_PROJECTION_PLAN_RECORD_KINDS_V1",
    "VALUE_PROJECTION_PLAN_REPRESENTATION_KINDS_V1",
    "VALUE_PROJECTION_PLAN_SCHEMA_VERSION",
    "VALUE_PROJECTION_PLAN_SOURCE_FAMILIES_V1",
    "VALUE_PROJECTION_PLAN_SOURCE_INPUT_KINDS_V1",
    "VALUE_PROJECTION_PLAN_SOURCE_RELATION_KINDS_V1",
    "VALUE_PROJECTION_PLAN_UNIT_KINDS_V1",
    "ValueProjectionPlanAssignmentV1",
    "ValueProjectionPlanError",
    "ValueProjectionPlanExpectedUnitV1",
    "ValueProjectionPlanObservationSourceV1",
    "ValueProjectionPlanOccurrenceV1",
    "ValueProjectionPlanOwnershipBindingV1",
    "ValueProjectionPlanOwnershipObservationV1",
    "ValueProjectionPlanOwnershipPartitionV1",
    "ValueProjectionPlanSourceRecordV1",
    "ValueProjectionPlanV1",
    "validate_value_projection_plan",
]


VALUE_PROJECTION_PLAN_SCHEMA_VERSION: Final = 1
MAX_VALUE_PROJECTION_PLAN_OBSERVATIONS: Final = 100_000
MAX_VALUE_PROJECTION_PLAN_PARTITIONS: Final = 200_000
MAX_VALUE_PROJECTION_PLAN_SOURCE_RECORDS: Final = 14_000_000
MAX_VALUE_PROJECTION_PLAN_BYTES: Final = 256 * 1024 * 1024

ValueProjectionPlanSourceInputKindV1 = Literal[
    "parser_input_body",
    "declared_bodyless_packet",
]
ValueProjectionPlanRepresentationKindV1 = Literal[
    "rectangular_result_cells_v1",
    "stats_lossless_records_v1",
    "live_lossless_nodes_v1",
    "response_lossless_records_v1",
    "response_fixed_zero_v1",
]
ValueProjectionPlanUnitKindV1 = Literal[
    "result_occurrence",
    "response_residual",
    "response_fixed_zero",
]
ValueProjectionPlanSourceFamilyV1 = Literal["stats", "live", "static"]
ValueProjectionPlanSourceRelationKindV1 = Literal[
    "result_cell_v1",
    "stats_lossless_record_v1",
    "live_lossless_node_v1",
]
ValueProjectionPlanRecordKindV1 = Literal[
    "cell",
    "response",
    "json_node",
    "result_set",
    "missing_expected",
    "raw_headers",
    "raw_rows",
    "header",
    "row",
    "result_declaration",
    "result_occurrence",
    "node",
    "field_cell",
]

VALUE_PROJECTION_PLAN_SOURCE_INPUT_KINDS_V1: Final = (
    "parser_input_body",
    "declared_bodyless_packet",
)
VALUE_PROJECTION_PLAN_REPRESENTATION_KINDS_V1: Final = (
    "rectangular_result_cells_v1",
    "stats_lossless_records_v1",
    "live_lossless_nodes_v1",
    "response_lossless_records_v1",
    "response_fixed_zero_v1",
)
VALUE_PROJECTION_PLAN_UNIT_KINDS_V1: Final = (
    "result_occurrence",
    "response_residual",
    "response_fixed_zero",
)
VALUE_PROJECTION_PLAN_SOURCE_FAMILIES_V1: Final = ("stats", "live", "static")
VALUE_PROJECTION_PLAN_SOURCE_RELATION_KINDS_V1: Final = (
    "result_cell_v1",
    "stats_lossless_record_v1",
    "live_lossless_node_v1",
)
VALUE_PROJECTION_PLAN_RECORD_KINDS_V1: Final = (
    "cell",
    "response",
    "json_node",
    "result_set",
    "missing_expected",
    "raw_headers",
    "raw_rows",
    "header",
    "row",
    "result_declaration",
    "result_occurrence",
    "node",
    "field_cell",
)

_SOURCE_INPUT_KINDS = frozenset(VALUE_PROJECTION_PLAN_SOURCE_INPUT_KINDS_V1)
_REPRESENTATION_KINDS = frozenset(VALUE_PROJECTION_PLAN_REPRESENTATION_KINDS_V1)
_UNIT_KINDS = frozenset(VALUE_PROJECTION_PLAN_UNIT_KINDS_V1)
_SOURCE_FAMILIES = frozenset(VALUE_PROJECTION_PLAN_SOURCE_FAMILIES_V1)
_SOURCE_RELATION_KINDS = frozenset(VALUE_PROJECTION_PLAN_SOURCE_RELATION_KINDS_V1)
_RECORD_KINDS = frozenset(VALUE_PROJECTION_PLAN_RECORD_KINDS_V1)
_RESULT_REPRESENTATIONS = frozenset(
    {
        "rectangular_result_cells_v1",
        "stats_lossless_records_v1",
        "live_lossless_nodes_v1",
    }
)
_RESULT_PRESENCES = frozenset(
    {
        "present",
        "missing",
        "null",
        "mixed_absent",
        "present_empty",
        "empty_object",
        "empty_array",
        "not_observed_parent_empty",
    }
)
_CONTAINER_KINDS = frozenset(
    {
        "nba_api_result_set",
        "nba_api_static_records",
        "nba_api_live_json_array",
        "nba_api_live_json_object",
    }
)
_RECORDS_BY_RELATION_AND_OWNER: Final = {
    ("result_cell_v1", "result_occurrence"): frozenset({"cell"}),
    ("stats_lossless_record_v1", "result_occurrence"): frozenset(
        {"result_set", "missing_expected", "raw_headers", "raw_rows", "header", "row", "cell"}
    ),
    ("stats_lossless_record_v1", "response_residual"): frozenset({"response", "json_node"}),
    ("live_lossless_node_v1", "result_occurrence"): frozenset(
        {"result_declaration", "result_occurrence", "node", "field_cell"}
    ),
    ("live_lossless_node_v1", "response_residual"): frozenset({"node"}),
}
_RELATIONS_BY_REPRESENTATION: Final = {
    "rectangular_result_cells_v1": frozenset({"result_cell_v1"}),
    "stats_lossless_records_v1": frozenset({"stats_lossless_record_v1"}),
    "live_lossless_nodes_v1": frozenset({"live_lossless_node_v1"}),
    "response_lossless_records_v1": frozenset(
        {"stats_lossless_record_v1", "live_lossless_node_v1"}
    ),
    "response_fixed_zero_v1": frozenset(),
}

_MAX_ORDINAL: Final = (1 << 63) - 1
_MAX_HEADER_COUNT: Final = 4_096
_MAX_ORDERED_HEADERS_BYTES: Final = 4 * 1024 * 1024
_MAX_EMBEDDED_JSON_STRING_BYTES: Final = (_MAX_ORDERED_HEADERS_BYTES * 2) + 2
_MAX_ROW_BYTES: Final = 64 * 1024
_MAX_OCCURRENCE_ROW_BYTES: Final = _MAX_EMBEDDED_JSON_STRING_BYTES + _MAX_ROW_BYTES
_MAX_TEXT_BYTES: Final = 4_096
_MAX_JSON_DEPTH: Final = 16
_MAX_JSON_NODES: Final = 2_000_000
_MAX_JSON_STRING_BYTES: Final = _MAX_EMBEDDED_JSON_STRING_BYTES
_MAX_JSON_NUMBER_BYTES: Final = 128
_SHA256_RE: Final = re.compile(r"[0-9a-f]{64}\Z")

_UNIT_KIND: Final = "nbadb_expected_value_unit_v1"
_UNIT_INVENTORY_KIND: Final = "nbadb_expected_value_unit_inventory_v1"
_PUBLIC_UNIT_ROOT_KIND: Final = "nbadb_expected_value_unit_ordered_root_v1"
_ASSIGNMENT_KIND: Final = "nbadb_value_representation_assignment_v1"
_OWNERSHIP_BINDING_KIND: Final = "nbadb_lossless_ownership_binding_v1"
_OWNERSHIP_PARTITION_KIND: Final = "nbadb_lossless_ownership_partition_v1"
_OWNERSHIP_OBSERVATION_KIND: Final = "nbadb_lossless_observation_ownership_v1"
_OWNERSHIP_RECEIPT_KIND: Final = "nbadb_lossless_ownership_receipt_v1"
_PARTITION_BINDING_ROOT_KIND: Final = "nbadb_lossless_partition_bindings_v1"
_PARTITION_RECORD_ROOT_KIND: Final = "nbadb_lossless_partition_source_records_v1"
_OBSERVATION_PARTITION_ROOT_KIND: Final = "nbadb_lossless_observation_partitions_v1"
_OBSERVATION_BINDING_ROOT_KIND: Final = "nbadb_lossless_observation_bindings_v1"
_OBSERVATION_RECORD_ROOT_KIND: Final = "nbadb_lossless_observation_source_records_v1"
_ASSIGNMENT_AUTHORITY_ROOT_KIND: Final = "nbadb_lossless_representation_assignments_v1"
_OBSERVATION_AUTHORITY_ROOT_KIND: Final = "nbadb_lossless_owned_observations_v1"
_PARTITION_AUTHORITY_ROOT_KIND: Final = "nbadb_lossless_ownership_partitions_v1"
_BINDING_AUTHORITY_ROOT_KIND: Final = "nbadb_lossless_ownership_bindings_v1"
_RECORD_AUTHORITY_ROOT_KIND: Final = "nbadb_lossless_owned_source_records_v1"
_FIXED_ZERO_ROOT_KIND: Final = "nbadb_lossless_fixed_zero_landings_v1"

_SOURCE_KIND: Final = "nbadb_value_projection_plan_observation_source_v1"
_OCCURRENCE_PLAN_KIND: Final = "nbadb_value_projection_occurrence_plan_v1"
_SOURCE_RECORD_PLAN_KIND: Final = "nbadb_value_projection_source_record_plan_v1"
_PLAN_KIND: Final = "nbadb_value_projection_plan_v1"
_PLAN_UNIT_ROOT_KIND: Final = "nbadb_value_projection_plan_expected_units_v1"
_PLAN_ASSIGNMENT_ROOT_KIND: Final = "nbadb_value_projection_plan_assignments_v1"
_PLAN_OBSERVATION_ROOT_KIND: Final = "nbadb_value_projection_plan_observations_v1"
_PLAN_SOURCE_ROOT_KIND: Final = "nbadb_value_projection_plan_sources_v1"
_PLAN_PARTITION_ROOT_KIND: Final = "nbadb_value_projection_plan_partitions_v1"
_PLAN_OCCURRENCE_ROOT_KIND: Final = "nbadb_value_projection_plan_occurrences_v1"
_PLAN_BINDING_ROOT_KIND: Final = "nbadb_value_projection_plan_bindings_v1"
_PLAN_SOURCE_RECORD_ROOT_KIND: Final = "nbadb_value_projection_plan_source_records_v1"


class ValueProjectionPlanError(ValueError):
    """The value-free projection plan is unsafe or internally inconsistent."""


def _fail(message: str) -> Never:
    raise ValueProjectionPlanError(message)


def _require_exact_class(cls: type[object], expected: type[object], *, label: str) -> None:
    if cls is not expected:
        _fail(f"{label} has a foreign exact class")


def _exact_sha256(value: object, *, label: str) -> str:
    if type(value) is not str or _SHA256_RE.fullmatch(value) is None:
        _fail(f"{label} must be one exact lowercase SHA-256")
    return value


def _optional_sha256(value: object, *, label: str) -> str | None:
    if value is None:
        return None
    return _exact_sha256(value, label=label)


def _exact_nonnegative(value: object, *, label: str, maximum: int) -> int:
    if type(value) is not int or value < 0 or value > maximum:
        _fail(f"{label} must be one bounded exact nonnegative integer")
    return value


def _optional_nonnegative(value: object, *, label: str, maximum: int) -> int | None:
    if value is None:
        return None
    return _exact_nonnegative(value, label=label, maximum=maximum)


def _exact_text(value: object, *, label: str, allow_empty: bool = False) -> str:
    if type(value) is not str or (not allow_empty and not value):
        _fail(f"{label} must be exact text")
    try:
        encoded = value.encode("utf-8", errors="strict")
    except UnicodeEncodeError:
        _fail(f"{label} contains invalid Unicode")
    if len(encoded) > _MAX_TEXT_BYTES:
        _fail(f"{label} exceeds its UTF-8 byte bound")
    return value


def _optional_text(value: object, *, label: str) -> str | None:
    if value is None:
        return None
    return _exact_text(value, label=label)


def _preflight_builtin_graph(value: object, *, maximum_nodes: int = _MAX_JSON_NODES) -> None:
    stack: list[tuple[object, int]] = [(value, 0)]
    nodes = 0
    byte_count = 0
    while stack:
        item, depth = stack.pop()
        nodes += 1
        if nodes > maximum_nodes or depth > _MAX_JSON_DEPTH:
            _fail("value-projection plan input exceeds its structural bound")
        if item is None or type(item) is bool:
            continue
        if type(item) is int:
            if item < -_MAX_ORDINAL or item > _MAX_ORDINAL:
                _fail("value-projection plan input contains an unbounded integer")
            continue
        if type(item) is str:
            try:
                byte_count += len(item.encode("utf-8", errors="strict"))
            except UnicodeEncodeError:
                _fail("value-projection plan input contains invalid Unicode")
            if byte_count > MAX_VALUE_PROJECTION_PLAN_BYTES:
                _fail("value-projection plan input exceeds its string-byte bound")
            continue
        if type(item) in {tuple, list}:
            sequence = cast("tuple[object, ...] | list[object]", item)
            stack.extend((child, depth + 1) for child in reversed(sequence))
            continue
        if type(item) is dict:
            mapping = cast("dict[object, object]", item)
            for key, child in reversed(tuple(mapping.items())):
                if type(key) is not str:
                    _fail("value-projection plan input contains a non-string key")
                try:
                    byte_count += len(key.encode("utf-8", errors="strict"))
                except UnicodeEncodeError:
                    _fail("value-projection plan input contains invalid Unicode")
                if byte_count > MAX_VALUE_PROJECTION_PLAN_BYTES:
                    _fail("value-projection plan input exceeds its string-byte bound")
                stack.append((child, depth + 1))
            continue
        _fail("value-projection plan input contains a foreign exact type")


def _canonical_json_bytes(value: object, *, maximum_bytes: int) -> bytes:
    _preflight_builtin_graph(value)
    try:
        encoded = json.dumps(
            value,
            allow_nan=False,
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        ).encode("utf-8", errors="strict")
    except ValueProjectionPlanError:
        raise
    except Exception:
        raise ValueProjectionPlanError(
            "value-projection plan value is not canonical JSON"
        ) from None
    if not encoded or len(encoded) > maximum_bytes:
        _fail("value-projection plan canonical JSON exceeds its byte bound")
    return encoded


def _canonical_sha256(value: object, *, maximum_bytes: int = _MAX_ROW_BYTES) -> str:
    return hashlib.sha256(_canonical_json_bytes(value, maximum_bytes=maximum_bytes)).hexdigest()


def _homogeneous_parent_state_sha256(state: str, count: int) -> str:
    """Hash one canonical homogeneous parent-state array with bounded memory."""

    encoded_state = _canonical_json_bytes(state, maximum_bytes=256)
    digest = hashlib.sha256()
    digest.update(b"[")
    if count:
        digest.update(encoded_state)
        separator_and_state = b"," + encoded_state
        remaining = count - 1
        while remaining:
            chunk_size = min(remaining, 4_096)
            digest.update(separator_and_state * chunk_size)
            remaining -= chunk_size
    digest.update(b"]")
    return digest.hexdigest()


def _preflight_json_bytes(value: object, *, maximum_bytes: int) -> bytes:
    if type(value) is not bytes or not value or len(value) > maximum_bytes:
        _fail("value-projection plan canonical bytes exceed their exact bound")
    encoded = cast("bytes", value)
    depth = 0
    nodes = 1
    in_string = False
    escaped = False
    string_bytes = 0
    number_bytes = 0
    for byte in encoded:
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
                    _fail("value-projection plan JSON contains an over-bound string")
                string_bytes = 0
            else:
                string_bytes += 1
            continue
        if byte == 0x22:
            in_string = True
            number_bytes = 0
        elif byte in (0x7B, 0x5B):
            depth += 1
            nodes += 1
            number_bytes = 0
            if depth > _MAX_JSON_DEPTH:
                _fail("value-projection plan JSON exceeds its depth bound")
        elif byte in (0x7D, 0x5D):
            depth -= 1
            number_bytes = 0
            if depth < 0:
                _fail("value-projection plan JSON is structurally invalid")
        elif byte in (0x2C, 0x3A):
            nodes += 1
            number_bytes = 0
        elif byte in b"-+0123456789.eE":
            number_bytes += 1
            if number_bytes > _MAX_JSON_NUMBER_BYTES:
                _fail("value-projection plan JSON contains an over-bound number")
        elif byte not in b" \t\r\n":
            number_bytes = 0
        if nodes > _MAX_JSON_NODES:
            _fail("value-projection plan JSON exceeds its token bound")
    if in_string or escaped or depth != 0:
        _fail("value-projection plan JSON is structurally invalid")
    return encoded


def _decode_canonical_json(value: object, *, maximum_bytes: int) -> object:
    encoded = _preflight_json_bytes(value, maximum_bytes=maximum_bytes)

    def object_pairs(pairs: list[tuple[str, object]]) -> dict[str, object]:
        result: dict[str, object] = {}
        for key, child in pairs:
            if type(key) is not str or key in result:
                _fail("value-projection plan JSON contains a duplicate or foreign key")
            result[key] = child
        return result

    def parse_int(token: str) -> int:
        if len(token) > _MAX_JSON_NUMBER_BYTES:
            _fail("value-projection plan JSON contains an over-bound integer")
        parsed = int(token)
        if parsed < -_MAX_ORDINAL or parsed > _MAX_ORDINAL:
            _fail("value-projection plan JSON contains an unbounded integer")
        return parsed

    def reject_number(_token: str) -> Never:
        _fail("value-projection plan JSON contains a non-integer number")

    try:
        decoded = json.loads(
            encoded,
            object_pairs_hook=object_pairs,
            parse_constant=reject_number,
            parse_float=reject_number,
            parse_int=parse_int,
        )
    except ValueProjectionPlanError:
        raise
    except Exception:
        raise ValueProjectionPlanError("value-projection plan JSON is invalid") from None
    _preflight_builtin_graph(decoded)
    if _canonical_json_bytes(decoded, maximum_bytes=maximum_bytes) != encoded:
        _fail("value-projection plan JSON is noncanonical")
    return decoded


def _ordered_headers_from_json(
    ordered_headers_json: object,
    *,
    ordered_headers_sha256: object,
    header_count: object,
) -> tuple[str, ...]:
    count = _exact_nonnegative(
        header_count,
        label="occurrence plan header count",
        maximum=_MAX_HEADER_COUNT,
    )
    if type(ordered_headers_json) is not str:
        _fail("occurrence plan ordered headers must be exact canonical JSON text")
    try:
        encoded = ordered_headers_json.encode("utf-8", errors="strict")
    except UnicodeEncodeError:
        _fail("occurrence plan ordered headers contain invalid Unicode")
    if not encoded or len(encoded) > _MAX_ORDERED_HEADERS_BYTES:
        _fail("occurrence plan ordered headers exceed their exact byte bound")
    decoded = _decode_canonical_json(
        encoded,
        maximum_bytes=_MAX_ORDERED_HEADERS_BYTES,
    )
    if type(decoded) is not list:
        _fail("occurrence plan ordered headers must be one exact JSON array")
    raw_headers = cast("list[object]", decoded)
    if len(raw_headers) != count:
        _fail("occurrence plan ordered-header count differs from its exact array")
    headers: list[str] = []
    for header in raw_headers:
        headers.append(
            _exact_text(
                header,
                label="occurrence plan ordered header",
                allow_empty=True,
            )
        )
    expected_sha256 = _exact_sha256(
        ordered_headers_sha256,
        label="occurrence plan header inventory",
    )
    if hashlib.sha256(encoded).hexdigest() != expected_sha256:
        _fail("occurrence plan ordered-header digest differs from its exact array")
    if count == 0 and ordered_headers_json != "[]":
        _fail("occurrence plan zero-header authority must be the exact empty array")
    return tuple(headers)


def _strict_row(
    value: object,
    *,
    expected_fields: tuple[str, ...],
    label: str,
) -> dict[str, object]:
    if type(value) is not dict:
        _fail(f"{label} does not have its exact ordered row shape")
    object_row = cast("dict[object, object]", value)
    if any(type(key) is not str for key in object_row) or tuple(object_row) != expected_fields:
        _fail(f"{label} does not have its exact ordered row shape")
    row = cast("dict[str, object]", value)
    if (
        type(row["schema_version"]) is not int
        or row["schema_version"] != VALUE_PROJECTION_PLAN_SCHEMA_VERSION
    ):
        _fail(f"{label} schema version is invalid")
    return row


def _row_fields(cls: type[object]) -> tuple[str, ...]:
    return ("schema_version", *(item.name for item in fields(cls)))


def _to_row(value: object) -> dict[str, object]:
    return {
        "schema_version": VALUE_PROJECTION_PLAN_SCHEMA_VERSION,
        **{item.name: getattr(value, item.name) for item in fields(cast("Any", value))},
    }


def _identity_payload(value: object, *, kind: str, digest_field: str) -> dict[str, object]:
    return {
        "schema_version": VALUE_PROJECTION_PLAN_SCHEMA_VERSION,
        "kind": kind,
        **{
            item.name: getattr(value, item.name)
            for item in fields(cast("Any", value))
            if item.name != digest_field
        },
    }


def _from_row(cls: type[object], value: object, *, label: str) -> object:
    row = _strict_row(value, expected_fields=_row_fields(cls), label=label)
    try:
        return cast("Any", cls)(**{item.name: row[item.name] for item in fields(cls)})
    except ValueProjectionPlanError:
        raise
    except Exception:
        raise ValueProjectionPlanError(f"{label} failed exact semantic replay") from None


def _row_from_canonical_bytes(
    cls: type[object],
    value: object,
    *,
    label: str,
    maximum_bytes: int = _MAX_ROW_BYTES,
) -> dict[str, object]:
    decoded = _decode_canonical_json(value, maximum_bytes=maximum_bytes)
    if type(decoded) is not dict:
        _fail(f"{label} canonical bytes do not contain one exact row")
    mapping = cast("dict[str, object]", decoded)
    expected = _row_fields(cls)
    if tuple(mapping) != tuple(sorted(expected)):
        _fail(f"{label} canonical bytes have foreign fields")
    return {name: mapping[name] for name in expected}


def _legacy_ordered_root(*, kind: str, item_sha256s: tuple[str, ...]) -> str:
    digest = hashlib.sha256()
    digest.update(b'{"count":')
    digest.update(str(len(item_sha256s)).encode("ascii"))
    digest.update(b',"items":[')
    for ordinal, item_sha256 in enumerate(item_sha256s):
        _exact_sha256(item_sha256, label="ordered-root item")
        if ordinal:
            digest.update(b",")
        digest.update(_canonical_json_bytes(item_sha256, maximum_bytes=256))
    digest.update(b'],"kind":')
    digest.update(_canonical_json_bytes(kind, maximum_bytes=256))
    digest.update(b',"schema_version":1}')
    return digest.hexdigest()


def _public_unit_root(*, raw_authority_bundle_sha256: str, unit_sha256s: tuple[str, ...]) -> str:
    digest = hashlib.sha256()
    digest.update(b'{"count":')
    digest.update(str(len(unit_sha256s)).encode("ascii"))
    digest.update(b',"items":[')
    for ordinal, unit_sha256 in enumerate(unit_sha256s):
        _exact_sha256(unit_sha256, label="expected-unit root item")
        if ordinal:
            digest.update(b",")
        digest.update(_canonical_json_bytes(unit_sha256, maximum_bytes=256))
    digest.update(b'],"kind":')
    digest.update(_canonical_json_bytes(_PUBLIC_UNIT_ROOT_KIND, maximum_bytes=256))
    digest.update(b',"raw_authority_bundle_sha256":')
    digest.update(_canonical_json_bytes(raw_authority_bundle_sha256, maximum_bytes=256))
    digest.update(b',"schema_version":1}')
    return digest.hexdigest()


def _length_framed_root(
    *,
    kind: str,
    raw_authority_bundle_sha256: str,
    item_sha256s: tuple[str, ...],
    maximum: int,
) -> str:
    _exact_text(kind, label="plan ordered-root kind")
    _exact_sha256(raw_authority_bundle_sha256, label="plan ordered-root bundle")
    if type(item_sha256s) is not tuple or len(item_sha256s) > maximum:
        _fail("value-projection plan ordered root is foreign or over-bound")
    digest = hashlib.sha256()
    digest.update(b"nbadb-value-projection-plan-length-framed-root-v1\x00")

    def feed(item: bytes) -> None:
        digest.update(len(item).to_bytes(8, byteorder="big", signed=False))
        digest.update(item)

    feed(str(VALUE_PROJECTION_PLAN_SCHEMA_VERSION).encode("ascii"))
    feed(kind.encode("utf-8"))
    feed(raw_authority_bundle_sha256.encode("ascii"))
    feed(str(len(item_sha256s)).encode("ascii"))
    for ordinal, item_sha256 in enumerate(item_sha256s):
        _exact_sha256(item_sha256, label="plan ordered-root item")
        feed(str(ordinal).encode("ascii"))
        feed(item_sha256.encode("ascii"))
    return digest.hexdigest()


class _CanonicalRow:
    kind: ClassVar[str]
    digest_field: ClassVar[str]

    def to_row(self) -> dict[str, object]:
        return _to_row(self)

    def canonical_bytes(self) -> bytes:
        return _canonical_json_bytes(self.to_row(), maximum_bytes=_MAX_ROW_BYTES)


@dataclass(frozen=True, slots=True)
class ValueProjectionPlanExpectedUnitV1(_CanonicalRow):
    unit_sha256: str
    raw_authority_bundle_sha256: str
    unit_ordinal: int
    observation_sha256: str
    observation_ordinal: int
    unit_kind: ValueProjectionPlanUnitKindV1
    occurrence_sha256: str | None
    occurrence_ordinal: int | None

    kind: ClassVar[str] = _UNIT_KIND
    digest_field: ClassVar[str] = "unit_sha256"

    def __post_init__(self) -> None:
        _exact_sha256(self.unit_sha256, label="expected-unit identity")
        _exact_sha256(self.raw_authority_bundle_sha256, label="expected-unit bundle")
        _exact_nonnegative(
            self.unit_ordinal,
            label="expected-unit ordinal",
            maximum=MAX_VALUE_PROJECTION_PLAN_OBSERVATIONS - 1,
        )
        _exact_sha256(self.observation_sha256, label="expected-unit observation")
        _exact_nonnegative(
            self.observation_ordinal,
            label="expected-unit observation ordinal",
            maximum=MAX_VALUE_PROJECTION_PLAN_OBSERVATIONS - 1,
        )
        if type(self.unit_kind) is not str or self.unit_kind not in _UNIT_KINDS:
            _fail("expected-unit kind is outside its closed V1 domain")
        if self.unit_kind == "result_occurrence":
            _exact_sha256(self.occurrence_sha256, label="expected-unit occurrence")
            _exact_nonnegative(
                self.occurrence_ordinal,
                label="expected-unit occurrence ordinal",
                maximum=MAX_VALUE_PROJECTION_PLAN_OBSERVATIONS - 1,
            )
        elif self.occurrence_sha256 is not None or self.occurrence_ordinal is not None:
            _fail("response expected unit fabricates occurrence identity")
        if self.unit_sha256 != _canonical_sha256(
            _identity_payload(self, kind=self.kind, digest_field=self.digest_field)
        ):
            _fail("expected-unit digest differs from its exact semantic identity")

    @classmethod
    def from_row(cls, value: object) -> Self:
        _require_exact_class(cls, ValueProjectionPlanExpectedUnitV1, label="expected-unit plan")
        return cast("Self", _from_row(cls, value, label="expected-unit plan row"))

    @classmethod
    def from_canonical_bytes(cls, value: object) -> Self:
        _require_exact_class(cls, ValueProjectionPlanExpectedUnitV1, label="expected-unit plan")
        return cls.from_row(_row_from_canonical_bytes(cls, value, label="expected-unit plan"))


@dataclass(frozen=True, slots=True)
class ValueProjectionPlanAssignmentV1(_CanonicalRow):
    assignment_sha256: str
    raw_authority_bundle_sha256: str
    unit_sha256: str
    unit_ordinal: int
    source_input_kind: ValueProjectionPlanSourceInputKindV1
    representation_kind: ValueProjectionPlanRepresentationKindV1

    kind: ClassVar[str] = _ASSIGNMENT_KIND
    digest_field: ClassVar[str] = "assignment_sha256"

    def __post_init__(self) -> None:
        for value, label in (
            (self.assignment_sha256, "assignment identity"),
            (self.raw_authority_bundle_sha256, "assignment bundle"),
            (self.unit_sha256, "assignment expected unit"),
        ):
            _exact_sha256(value, label=label)
        _exact_nonnegative(
            self.unit_ordinal,
            label="assignment unit ordinal",
            maximum=MAX_VALUE_PROJECTION_PLAN_OBSERVATIONS - 1,
        )
        if (
            type(self.source_input_kind) is not str
            or self.source_input_kind not in _SOURCE_INPUT_KINDS
        ):
            _fail("assignment source-input kind is outside its closed V1 domain")
        if (
            type(self.representation_kind) is not str
            or self.representation_kind not in _REPRESENTATION_KINDS
        ):
            _fail("assignment representation kind is outside its closed V1 domain")
        if self.assignment_sha256 != _canonical_sha256(
            _identity_payload(self, kind=self.kind, digest_field=self.digest_field)
        ):
            _fail("assignment digest differs from its exact semantic identity")

    @classmethod
    def from_row(cls, value: object) -> Self:
        _require_exact_class(cls, ValueProjectionPlanAssignmentV1, label="assignment plan")
        return cast("Self", _from_row(cls, value, label="assignment plan row"))

    @classmethod
    def from_canonical_bytes(cls, value: object) -> Self:
        _require_exact_class(cls, ValueProjectionPlanAssignmentV1, label="assignment plan")
        return cls.from_row(_row_from_canonical_bytes(cls, value, label="assignment plan"))


@dataclass(frozen=True, slots=True)
class ValueProjectionPlanOwnershipObservationV1(_CanonicalRow):
    observation_ownership_sha256: str
    raw_authority_bundle_sha256: str
    observation_record_sha256: str
    observation_sha256: str
    observation_ordinal: int
    source_input_kind: ValueProjectionPlanSourceInputKindV1
    first_partition_ordinal: int
    partition_count: int
    partition_root_sha256: str
    result_occurrence_partition_count: int
    zero_result_occurrence_partition_count: int
    result_occurrence_record_count: int
    response_partition_kind: ValueProjectionPlanUnitKindV1
    response_record_count: int
    fixed_zero_landing_sha256: str | None
    record_count: int
    record_root_sha256: str
    binding_count: int
    binding_root_sha256: str

    kind: ClassVar[str] = _OWNERSHIP_OBSERVATION_KIND
    digest_field: ClassVar[str] = "observation_ownership_sha256"

    def __post_init__(self) -> None:
        for value, label in (
            (self.observation_ownership_sha256, "ownership observation identity"),
            (self.raw_authority_bundle_sha256, "ownership observation bundle"),
            (self.observation_record_sha256, "ownership observation record"),
            (self.observation_sha256, "ownership observation"),
            (self.partition_root_sha256, "ownership observation partition root"),
            (self.record_root_sha256, "ownership observation record root"),
            (self.binding_root_sha256, "ownership observation binding root"),
        ):
            _exact_sha256(value, label=label)
        for value, label, maximum in (
            (
                self.observation_ordinal,
                "ownership observation ordinal",
                MAX_VALUE_PROJECTION_PLAN_OBSERVATIONS - 1,
            ),
            (
                self.first_partition_ordinal,
                "ownership first partition",
                MAX_VALUE_PROJECTION_PLAN_PARTITIONS - 1,
            ),
            (
                self.partition_count,
                "ownership partition count",
                MAX_VALUE_PROJECTION_PLAN_PARTITIONS,
            ),
            (
                self.result_occurrence_partition_count,
                "ownership occurrence count",
                MAX_VALUE_PROJECTION_PLAN_OBSERVATIONS,
            ),
            (
                self.zero_result_occurrence_partition_count,
                "ownership zero occurrence count",
                MAX_VALUE_PROJECTION_PLAN_OBSERVATIONS,
            ),
            (
                self.result_occurrence_record_count,
                "ownership occurrence record count",
                MAX_VALUE_PROJECTION_PLAN_SOURCE_RECORDS,
            ),
            (
                self.response_record_count,
                "ownership response record count",
                MAX_VALUE_PROJECTION_PLAN_SOURCE_RECORDS,
            ),
            (self.record_count, "ownership record count", MAX_VALUE_PROJECTION_PLAN_SOURCE_RECORDS),
            (
                self.binding_count,
                "ownership binding count",
                MAX_VALUE_PROJECTION_PLAN_SOURCE_RECORDS,
            ),
        ):
            _exact_nonnegative(value, label=label, maximum=maximum)
        if (
            type(self.source_input_kind) is not str
            or self.source_input_kind not in _SOURCE_INPUT_KINDS
        ):
            _fail("ownership observation source input is outside its closed V1 domain")
        if self.response_partition_kind not in {"response_residual", "response_fixed_zero"}:
            _fail("ownership observation response kind is outside its closed V1 domain")
        _optional_sha256(self.fixed_zero_landing_sha256, label="ownership fixed-zero landing")
        if (
            self.partition_count != self.result_occurrence_partition_count + 1
            or self.zero_result_occurrence_partition_count > self.result_occurrence_partition_count
            or self.record_count != self.result_occurrence_record_count + self.response_record_count
            or self.binding_count != self.record_count
            or self.result_occurrence_record_count
            < self.result_occurrence_partition_count - self.zero_result_occurrence_partition_count
        ):
            _fail("ownership observation aggregate algebra is inconsistent")
        if self.response_partition_kind == "response_fixed_zero":
            if (
                self.result_occurrence_partition_count != 0
                or self.zero_result_occurrence_partition_count != 0
                or self.result_occurrence_record_count != 0
                or self.response_record_count != 0
                or self.record_count != 0
                or self.fixed_zero_landing_sha256 is None
            ):
                _fail("fixed-zero ownership observation contradicts its exact empty algebra")
        elif self.fixed_zero_landing_sha256 is not None:
            _fail("response-residual ownership observation fabricates fixed-zero evidence")
        elif self.result_occurrence_partition_count == 0 and self.response_record_count == 0:
            _fail("empty ownership observation requires a fixed-zero response")
        if self.observation_ownership_sha256 != _canonical_sha256(
            _identity_payload(self, kind=self.kind, digest_field=self.digest_field)
        ):
            _fail("ownership observation digest differs from its exact identity")

    @classmethod
    def from_row(cls, value: object) -> Self:
        _require_exact_class(
            cls,
            ValueProjectionPlanOwnershipObservationV1,
            label="ownership observation plan",
        )
        return cast("Self", _from_row(cls, value, label="ownership observation plan row"))

    @classmethod
    def from_canonical_bytes(cls, value: object) -> Self:
        _require_exact_class(
            cls,
            ValueProjectionPlanOwnershipObservationV1,
            label="ownership observation plan",
        )
        return cls.from_row(
            _row_from_canonical_bytes(cls, value, label="ownership observation plan")
        )


@dataclass(frozen=True, slots=True)
class ValueProjectionPlanOwnershipPartitionV1(_CanonicalRow):
    partition_sha256: str
    raw_authority_bundle_sha256: str
    observation_record_sha256: str
    observation_sha256: str
    observation_ordinal: int
    partition_ordinal: int
    observation_partition_ordinal: int
    partition_kind: ValueProjectionPlanUnitKindV1
    occurrence_sha256: str | None
    occurrence_ordinal: int | None
    unit_sha256: str | None
    unit_ordinal: int | None
    assignment_sha256: str | None
    record_count: int
    record_root_sha256: str
    binding_root_sha256: str
    fixed_zero_landing_sha256: str | None

    kind: ClassVar[str] = _OWNERSHIP_PARTITION_KIND
    digest_field: ClassVar[str] = "partition_sha256"

    def __post_init__(self) -> None:
        for value, label in (
            (self.partition_sha256, "ownership partition identity"),
            (self.raw_authority_bundle_sha256, "ownership partition bundle"),
            (self.observation_record_sha256, "ownership partition observation record"),
            (self.observation_sha256, "ownership partition observation"),
            (self.record_root_sha256, "ownership partition record root"),
            (self.binding_root_sha256, "ownership partition binding root"),
        ):
            _exact_sha256(value, label=label)
        for value, label, maximum in (
            (
                self.observation_ordinal,
                "partition observation ordinal",
                MAX_VALUE_PROJECTION_PLAN_OBSERVATIONS - 1,
            ),
            (self.partition_ordinal, "partition ordinal", MAX_VALUE_PROJECTION_PLAN_PARTITIONS - 1),
            (
                self.observation_partition_ordinal,
                "observation partition ordinal",
                MAX_VALUE_PROJECTION_PLAN_PARTITIONS - 1,
            ),
            (self.record_count, "partition record count", MAX_VALUE_PROJECTION_PLAN_SOURCE_RECORDS),
        ):
            _exact_nonnegative(value, label=label, maximum=maximum)
        if type(self.partition_kind) is not str or self.partition_kind not in _UNIT_KINDS:
            _fail("ownership partition kind is outside its closed V1 domain")
        _optional_sha256(self.occurrence_sha256, label="partition occurrence")
        _optional_nonnegative(
            self.occurrence_ordinal,
            label="partition occurrence ordinal",
            maximum=MAX_VALUE_PROJECTION_PLAN_OBSERVATIONS - 1,
        )
        _optional_sha256(self.unit_sha256, label="partition unit")
        _optional_nonnegative(
            self.unit_ordinal,
            label="partition unit ordinal",
            maximum=MAX_VALUE_PROJECTION_PLAN_OBSERVATIONS - 1,
        )
        _optional_sha256(self.assignment_sha256, label="partition assignment")
        _optional_sha256(self.fixed_zero_landing_sha256, label="partition fixed-zero landing")
        unit_present = (
            self.unit_sha256 is not None
            and self.unit_ordinal is not None
            and self.assignment_sha256 is not None
        )
        unit_absent = (
            self.unit_sha256 is None
            and self.unit_ordinal is None
            and self.assignment_sha256 is None
        )
        if not unit_present and not unit_absent:
            _fail("ownership partition has a partial expected-unit binding")
        if self.partition_kind == "result_occurrence":
            if (
                self.occurrence_sha256 is None
                or self.occurrence_ordinal is None
                or not unit_present
                or self.fixed_zero_landing_sha256 is not None
            ):
                _fail("result-occurrence partition has an invalid shape")
        elif self.partition_kind == "response_residual":
            if (
                self.occurrence_sha256 is not None
                or self.occurrence_ordinal is not None
                or self.fixed_zero_landing_sha256 is not None
                or (self.record_count > 0 and not unit_present)
                or (self.record_count == 0 and not unit_absent)
            ):
                _fail("response-residual partition has an invalid shape")
        elif (
            self.occurrence_sha256 is not None
            or self.occurrence_ordinal is not None
            or not unit_present
            or self.record_count != 0
            or self.fixed_zero_landing_sha256 is None
        ):
            _fail("fixed-zero partition has an invalid shape")
        empty_record_root = _legacy_ordered_root(kind=_PARTITION_RECORD_ROOT_KIND, item_sha256s=())
        empty_binding_root = _legacy_ordered_root(
            kind=_PARTITION_BINDING_ROOT_KIND, item_sha256s=()
        )
        if (self.record_count == 0) != (self.record_root_sha256 == empty_record_root) or (
            self.record_count == 0
        ) != (self.binding_root_sha256 == empty_binding_root):
            _fail("ownership partition zero roots are inconsistent")
        if self.partition_sha256 != _canonical_sha256(
            _identity_payload(self, kind=self.kind, digest_field=self.digest_field)
        ):
            _fail("ownership partition digest differs from its exact identity")

    @classmethod
    def from_row(cls, value: object) -> Self:
        _require_exact_class(
            cls,
            ValueProjectionPlanOwnershipPartitionV1,
            label="ownership partition plan",
        )
        return cast("Self", _from_row(cls, value, label="ownership partition plan row"))

    @classmethod
    def from_canonical_bytes(cls, value: object) -> Self:
        _require_exact_class(
            cls,
            ValueProjectionPlanOwnershipPartitionV1,
            label="ownership partition plan",
        )
        return cls.from_row(_row_from_canonical_bytes(cls, value, label="ownership partition plan"))


@dataclass(frozen=True, slots=True)
class ValueProjectionPlanOwnershipBindingV1(_CanonicalRow):
    binding_sha256: str
    raw_authority_bundle_sha256: str
    observation_record_sha256: str
    observation_sha256: str
    observation_ordinal: int
    binding_ordinal: int
    observation_record_ordinal: int
    partition_ordinal: int
    source_record_sha256: str
    unit_sha256: str
    unit_ordinal: int
    assignment_sha256: str
    ownership_kind: Literal["result_occurrence", "response_residual"]
    occurrence_sha256: str | None
    occurrence_ordinal: int | None

    kind: ClassVar[str] = _OWNERSHIP_BINDING_KIND
    digest_field: ClassVar[str] = "binding_sha256"

    def __post_init__(self) -> None:
        for value, label in (
            (self.binding_sha256, "ownership binding identity"),
            (self.raw_authority_bundle_sha256, "ownership binding bundle"),
            (self.observation_record_sha256, "ownership binding observation record"),
            (self.observation_sha256, "ownership binding observation"),
            (self.source_record_sha256, "ownership binding source record"),
            (self.unit_sha256, "ownership binding unit"),
            (self.assignment_sha256, "ownership binding assignment"),
        ):
            _exact_sha256(value, label=label)
        for value, label, maximum in (
            (
                self.observation_ordinal,
                "binding observation ordinal",
                MAX_VALUE_PROJECTION_PLAN_OBSERVATIONS - 1,
            ),
            (self.binding_ordinal, "binding ordinal", MAX_VALUE_PROJECTION_PLAN_SOURCE_RECORDS - 1),
            (
                self.observation_record_ordinal,
                "binding observation record ordinal",
                MAX_VALUE_PROJECTION_PLAN_SOURCE_RECORDS - 1,
            ),
            (
                self.partition_ordinal,
                "binding partition ordinal",
                MAX_VALUE_PROJECTION_PLAN_PARTITIONS - 1,
            ),
            (self.unit_ordinal, "binding unit ordinal", MAX_VALUE_PROJECTION_PLAN_OBSERVATIONS - 1),
        ):
            _exact_nonnegative(value, label=label, maximum=maximum)
        if self.ownership_kind not in {"result_occurrence", "response_residual"}:
            _fail("ownership binding kind is outside its closed V1 domain")
        if self.ownership_kind == "result_occurrence":
            _exact_sha256(self.occurrence_sha256, label="binding occurrence")
            _exact_nonnegative(
                self.occurrence_ordinal,
                label="binding occurrence ordinal",
                maximum=MAX_VALUE_PROJECTION_PLAN_OBSERVATIONS - 1,
            )
        elif self.occurrence_sha256 is not None or self.occurrence_ordinal is not None:
            _fail("response-residual binding fabricates occurrence identity")
        if self.binding_sha256 != _canonical_sha256(
            _identity_payload(self, kind=self.kind, digest_field=self.digest_field)
        ):
            _fail("ownership binding digest differs from its exact identity")

    @classmethod
    def from_row(cls, value: object) -> Self:
        _require_exact_class(
            cls,
            ValueProjectionPlanOwnershipBindingV1,
            label="ownership binding plan",
        )
        return cast("Self", _from_row(cls, value, label="ownership binding plan row"))

    @classmethod
    def from_canonical_bytes(cls, value: object) -> Self:
        _require_exact_class(
            cls,
            ValueProjectionPlanOwnershipBindingV1,
            label="ownership binding plan",
        )
        return cls.from_row(_row_from_canonical_bytes(cls, value, label="ownership binding plan"))


@dataclass(frozen=True, slots=True)
class ValueProjectionPlanObservationSourceV1(_CanonicalRow):
    source_sha256: str
    raw_authority_bundle_sha256: str
    observation_record_sha256: str
    observation_sha256: str
    observation_ordinal: int
    source_input_kind: ValueProjectionPlanSourceInputKindV1
    source_family: ValueProjectionPlanSourceFamilyV1
    body_blob_sha256: str | None
    body_blob_readback_sha256: str | None
    parser_input_object_sha256: str | None
    bodyless_packet_sha256: str | None
    bodyless_readback_sha256: str | None
    payload_sha256: str
    payload_byte_count: int

    kind: ClassVar[str] = _SOURCE_KIND
    digest_field: ClassVar[str] = "source_sha256"

    def __post_init__(self) -> None:
        for value, label in (
            (self.source_sha256, "observation source identity"),
            (self.raw_authority_bundle_sha256, "observation source bundle"),
            (self.observation_record_sha256, "observation source record"),
            (self.observation_sha256, "observation source observation"),
            (self.payload_sha256, "observation source payload"),
        ):
            _exact_sha256(value, label=label)
        _exact_nonnegative(
            self.observation_ordinal,
            label="observation source ordinal",
            maximum=MAX_VALUE_PROJECTION_PLAN_OBSERVATIONS - 1,
        )
        _exact_nonnegative(
            self.payload_byte_count,
            label="observation source payload bytes",
            maximum=_MAX_ORDINAL,
        )
        if self.payload_byte_count == 0:
            _fail("observation source cannot reference an empty payload")
        if (
            type(self.source_input_kind) is not str
            or self.source_input_kind not in _SOURCE_INPUT_KINDS
        ):
            _fail("observation source input kind is outside its closed V1 domain")
        if type(self.source_family) is not str or self.source_family not in _SOURCE_FAMILIES:
            _fail("observation source family is outside its closed V1 domain")
        parser_fields = (
            self.body_blob_sha256,
            self.body_blob_readback_sha256,
            self.parser_input_object_sha256,
        )
        bodyless_fields = (self.bodyless_packet_sha256, self.bodyless_readback_sha256)
        for value, label in (
            (self.body_blob_sha256, "observation body blob"),
            (self.body_blob_readback_sha256, "observation body readback"),
            (self.parser_input_object_sha256, "observation parser-input object"),
            (self.bodyless_packet_sha256, "observation bodyless packet"),
            (self.bodyless_readback_sha256, "observation bodyless readback"),
        ):
            _optional_sha256(value, label=label)
        if self.source_input_kind == "parser_input_body":
            if any(value is None for value in parser_fields) or any(
                value is not None for value in bodyless_fields
            ):
                _fail("parser-input source has an invalid exact authority shape")
            if self.source_family not in {"stats", "live"}:
                _fail("parser-input source has a foreign source family")
        elif any(value is not None for value in parser_fields) or any(
            value is None for value in bodyless_fields
        ):
            _fail("declared-bodyless source has an invalid exact authority shape")
        elif self.source_family != "static":
            _fail("declared-bodyless source must have the static source family")
        if self.source_sha256 != _canonical_sha256(
            _identity_payload(self, kind=self.kind, digest_field=self.digest_field)
        ):
            _fail("observation source digest differs from its exact identity")

    @classmethod
    def build(
        cls,
        *,
        raw_authority_bundle_sha256: str,
        observation_record_sha256: str,
        observation_sha256: str,
        observation_ordinal: int,
        source_input_kind: ValueProjectionPlanSourceInputKindV1,
        source_family: ValueProjectionPlanSourceFamilyV1,
        payload_sha256: str,
        payload_byte_count: int,
        body_blob_sha256: str | None = None,
        body_blob_readback_sha256: str | None = None,
        parser_input_object_sha256: str | None = None,
        bodyless_packet_sha256: str | None = None,
        bodyless_readback_sha256: str | None = None,
    ) -> Self:
        _require_exact_class(
            cls,
            ValueProjectionPlanObservationSourceV1,
            label="observation source",
        )
        values = {
            "raw_authority_bundle_sha256": raw_authority_bundle_sha256,
            "observation_record_sha256": observation_record_sha256,
            "observation_sha256": observation_sha256,
            "observation_ordinal": observation_ordinal,
            "source_input_kind": source_input_kind,
            "source_family": source_family,
            "body_blob_sha256": body_blob_sha256,
            "body_blob_readback_sha256": body_blob_readback_sha256,
            "parser_input_object_sha256": parser_input_object_sha256,
            "bodyless_packet_sha256": bodyless_packet_sha256,
            "bodyless_readback_sha256": bodyless_readback_sha256,
            "payload_sha256": payload_sha256,
            "payload_byte_count": payload_byte_count,
        }
        payload = {
            "schema_version": VALUE_PROJECTION_PLAN_SCHEMA_VERSION,
            "kind": cls.kind,
            **values,
        }
        return cls(source_sha256=_canonical_sha256(payload), **cast("Any", values))

    @classmethod
    def from_row(cls, value: object) -> Self:
        _require_exact_class(
            cls,
            ValueProjectionPlanObservationSourceV1,
            label="observation source",
        )
        return cast("Self", _from_row(cls, value, label="observation source plan row"))

    @classmethod
    def from_canonical_bytes(cls, value: object) -> Self:
        _require_exact_class(
            cls,
            ValueProjectionPlanObservationSourceV1,
            label="observation source",
        )
        return cls.from_row(_row_from_canonical_bytes(cls, value, label="observation source plan"))


@dataclass(frozen=True, slots=True)
class ValueProjectionPlanOccurrenceV1(_CanonicalRow):
    occurrence_plan_sha256: str
    raw_authority_bundle_sha256: str
    occurrence_plan_ordinal: int
    observation_record_sha256: str
    observation_sha256: str
    observation_ordinal: int
    partition_sha256: str
    partition_ordinal: int
    occurrence_sha256: str
    occurrence_ordinal: int
    unit_sha256: str
    unit_ordinal: int
    assignment_sha256: str
    source_input_kind: ValueProjectionPlanSourceInputKindV1
    representation_kind: ValueProjectionPlanRepresentationKindV1
    result_name: str
    result_duplicate_ordinal: int
    provider_result_ordinal: int | None
    expected_result_ordinal: int | None
    canonical_result_ordinal: int | None
    result_path: str | None
    container_kind: str
    result_presence: str
    ordered_headers_json: str
    ordered_headers_sha256: str
    header_count: int
    row_count: int
    cell_count: int
    node_count: int
    container_count: int
    missing_count: int
    null_count: int
    parent_state_sha256: str | None
    representation_output_sha256: str

    kind: ClassVar[str] = _OCCURRENCE_PLAN_KIND
    digest_field: ClassVar[str] = "occurrence_plan_sha256"

    def __post_init__(self) -> None:
        for value, label in (
            (self.occurrence_plan_sha256, "occurrence plan identity"),
            (self.raw_authority_bundle_sha256, "occurrence plan bundle"),
            (self.observation_record_sha256, "occurrence plan observation record"),
            (self.observation_sha256, "occurrence plan observation"),
            (self.partition_sha256, "occurrence plan partition"),
            (self.occurrence_sha256, "occurrence plan occurrence"),
            (self.unit_sha256, "occurrence plan unit"),
            (self.assignment_sha256, "occurrence plan assignment"),
            (self.ordered_headers_sha256, "occurrence plan header inventory"),
            (self.representation_output_sha256, "occurrence plan output"),
        ):
            _exact_sha256(value, label=label)
        for value, label, maximum in (
            (
                self.occurrence_plan_ordinal,
                "occurrence plan ordinal",
                MAX_VALUE_PROJECTION_PLAN_OBSERVATIONS - 1,
            ),
            (
                self.observation_ordinal,
                "occurrence plan observation ordinal",
                MAX_VALUE_PROJECTION_PLAN_OBSERVATIONS - 1,
            ),
            (
                self.partition_ordinal,
                "occurrence plan partition ordinal",
                MAX_VALUE_PROJECTION_PLAN_PARTITIONS - 1,
            ),
            (
                self.occurrence_ordinal,
                "occurrence plan occurrence ordinal",
                MAX_VALUE_PROJECTION_PLAN_OBSERVATIONS - 1,
            ),
            (
                self.unit_ordinal,
                "occurrence plan unit ordinal",
                MAX_VALUE_PROJECTION_PLAN_OBSERVATIONS - 1,
            ),
            (
                self.result_duplicate_ordinal,
                "occurrence plan duplicate ordinal",
                MAX_VALUE_PROJECTION_PLAN_OBSERVATIONS - 1,
            ),
            (
                self.header_count,
                "occurrence plan header count",
                _MAX_HEADER_COUNT,
            ),
            (self.row_count, "occurrence plan row count", MAX_VALUE_PROJECTION_PLAN_SOURCE_RECORDS),
            (
                self.cell_count,
                "occurrence plan cell count",
                MAX_VALUE_PROJECTION_PLAN_SOURCE_RECORDS,
            ),
            (
                self.node_count,
                "occurrence plan node count",
                MAX_VALUE_PROJECTION_PLAN_SOURCE_RECORDS,
            ),
            (
                self.container_count,
                "occurrence plan container count",
                MAX_VALUE_PROJECTION_PLAN_SOURCE_RECORDS,
            ),
            (
                self.missing_count,
                "occurrence plan missing count",
                MAX_VALUE_PROJECTION_PLAN_SOURCE_RECORDS,
            ),
            (
                self.null_count,
                "occurrence plan null count",
                MAX_VALUE_PROJECTION_PLAN_SOURCE_RECORDS,
            ),
        ):
            _exact_nonnegative(value, label=label, maximum=maximum)
        _exact_sha256(self.parent_state_sha256, label="occurrence plan parent-state inventory")
        for value, label in (
            (self.provider_result_ordinal, "occurrence provider result ordinal"),
            (self.expected_result_ordinal, "occurrence expected result ordinal"),
            (self.canonical_result_ordinal, "occurrence canonical result ordinal"),
        ):
            _optional_nonnegative(
                value,
                label=label,
                maximum=MAX_VALUE_PROJECTION_PLAN_OBSERVATIONS - 1,
            )
        if (
            type(self.source_input_kind) is not str
            or self.source_input_kind not in _SOURCE_INPUT_KINDS
        ):
            _fail("occurrence plan source input is outside its closed V1 domain")
        if (
            type(self.representation_kind) is not str
            or self.representation_kind not in _RESULT_REPRESENTATIONS
        ):
            _fail("occurrence plan representation is not one result representation")
        _exact_text(self.result_name, label="occurrence plan result name", allow_empty=True)
        result_path = _optional_text(self.result_path, label="occurrence plan result path")
        if result_path is not None and (
            not result_path.startswith("$")
            or ".." in result_path
            or "/" in result_path
            or "\\" in result_path
            or "@" in result_path
        ):
            _fail("occurrence plan result path is unsafe or noncanonical")
        if type(self.container_kind) is not str or self.container_kind not in _CONTAINER_KINDS:
            _fail("occurrence plan container kind is outside its closed V1 domain")
        if type(self.result_presence) is not str or self.result_presence not in _RESULT_PRESENCES:
            _fail("occurrence plan presence is outside its closed V1 domain")
        _ordered_headers_from_json(
            self.ordered_headers_json,
            ordered_headers_sha256=self.ordered_headers_sha256,
            header_count=self.header_count,
        )
        if self.representation_kind == "rectangular_result_cells_v1" and (
            self.cell_count != self.header_count * self.row_count
        ):
            _fail("rectangular occurrence count algebra is inconsistent")
        if self.representation_kind == "live_lossless_nodes_v1" and (
            self.cell_count != self.header_count * self.row_count
        ):
            _fail("live occurrence cell denominator is inconsistent")
        if self.representation_kind == "stats_lossless_records_v1" and (
            self.container_kind != "nba_api_result_set" or result_path is not None
        ):
            _fail("stats-lossless occurrence has a foreign container or path")
        if self.representation_kind == "live_lossless_nodes_v1" and (
            self.container_kind not in {"nba_api_live_json_array", "nba_api_live_json_object"}
            or result_path is None
            or not result_path.startswith("$.")
        ):
            _fail("live-lossless occurrence has a foreign container or path")
        self._validate_raw_occurrence_algebra()
        if self.occurrence_plan_sha256 != _canonical_sha256(
            _identity_payload(self, kind=self.kind, digest_field=self.digest_field),
            maximum_bytes=_MAX_OCCURRENCE_ROW_BYTES,
        ):
            _fail("occurrence plan digest differs from its exact identity")

    def _validate_raw_occurrence_algebra(self) -> None:
        presence = self.result_presence
        container = self.container_kind
        present_parent_count = self.container_count - self.null_count
        if present_parent_count < 0:
            _fail("occurrence parent-state counts cannot be reconstructed")
        parent_state_counts = (
            ("present", present_parent_count),
            ("missing", self.missing_count),
            ("null", self.null_count),
        )
        populated_parent_states = tuple(
            (state, count) for state, count in parent_state_counts if count
        )
        if not populated_parent_states:
            expected_parent_state = _homogeneous_parent_state_sha256("present", 0)
        elif len(populated_parent_states) == 1:
            state, count = populated_parent_states[0]
            expected_parent_state = _homogeneous_parent_state_sha256(state, count)
        else:
            expected_parent_state = None
        if expected_parent_state is not None and self.parent_state_sha256 != expected_parent_state:
            _fail("occurrence parent-state commitment is inconsistent")
        if container == "nba_api_result_set":
            if self.result_path is not None or presence not in {
                "present",
                "present_empty",
                "missing",
            }:
                _fail("stats occurrence container, path, or presence is inconsistent")
            if self.node_count != 0:
                _fail("stats occurrence fabricates JSON nodes")
            stats_parent_state = _canonical_sha256(
                ["missing"] if presence == "missing" else ["present"]
            )
            if self.parent_state_sha256 != stats_parent_state:
                _fail("stats occurrence parent-state commitment is inconsistent")
        elif container == "nba_api_static_records":
            if (
                self.result_path != "$"
                or presence not in {"present", "empty_array"}
                or self.parent_state_sha256 != _canonical_sha256(["present"])
            ):
                _fail(
                    "static occurrence container, path, presence, or parent state is inconsistent"
                )
        elif (
            self.result_path is None
            or not self.result_path.startswith("$.")
            or presence
            not in {
                "present",
                "empty_array",
                "missing",
                "null",
                "mixed_absent",
                "empty_object",
                "not_observed_parent_empty",
            }
        ):
            _fail("live occurrence container, path, or presence is inconsistent")

        if presence == "not_observed_parent_empty":
            if (
                container not in {"nba_api_live_json_array", "nba_api_live_json_object"}
                or self.parent_state_sha256 != _canonical_sha256([])
                or any(
                    value != 0
                    for value in (
                        self.header_count,
                        self.row_count,
                        self.cell_count,
                        self.node_count,
                        self.container_count,
                        self.missing_count,
                        self.null_count,
                    )
                )
            ):
                _fail("parent-empty occurrence count algebra is inconsistent")
        elif presence == "missing":
            if (
                self.container_count != 0
                or self.missing_count < 1
                or any(
                    value != 0
                    for value in (
                        self.header_count,
                        self.row_count,
                        self.cell_count,
                        self.node_count,
                        self.null_count,
                    )
                )
            ):
                _fail("missing occurrence count algebra is inconsistent")
        elif presence == "null":
            if (
                self.container_count != self.null_count
                or self.null_count < 1
                or self.node_count != self.null_count
                or any(
                    value != 0
                    for value in (
                        self.header_count,
                        self.row_count,
                        self.cell_count,
                        self.missing_count,
                    )
                )
            ):
                _fail("null occurrence count algebra is inconsistent")
        elif presence == "mixed_absent":
            if (
                container not in {"nba_api_live_json_array", "nba_api_live_json_object"}
                or self.container_count != self.null_count
                or self.missing_count < 1
                or self.null_count < 1
                or self.node_count != self.null_count
                or any(value != 0 for value in (self.header_count, self.row_count, self.cell_count))
            ):
                _fail("mixed-absent occurrence count algebra is inconsistent")
        elif presence == "present_empty":
            if (
                container != "nba_api_result_set"
                or self.container_count != 1
                or any(
                    value != 0
                    for value in (
                        self.row_count,
                        self.cell_count,
                        self.node_count,
                        self.missing_count,
                        self.null_count,
                    )
                )
            ):
                _fail("present-empty occurrence count algebra is inconsistent")
        elif presence == "empty_object":
            if (
                container != "nba_api_live_json_object"
                or self.container_count != 1
                or self.node_count != 1
                or any(
                    value != 0
                    for value in (
                        self.header_count,
                        self.row_count,
                        self.cell_count,
                        self.missing_count,
                        self.null_count,
                    )
                )
            ):
                _fail("empty-object occurrence count algebra is inconsistent")
        elif presence == "empty_array":
            if (
                container not in {"nba_api_static_records", "nba_api_live_json_array"}
                or self.container_count != 1
                or self.node_count != 1
                or any(
                    value != 0
                    for value in (
                        self.header_count,
                        self.row_count,
                        self.cell_count,
                        self.missing_count,
                        self.null_count,
                    )
                )
            ):
                _fail("empty-array occurrence count algebra is inconsistent")
        elif presence == "present":
            present_containers = self.container_count - self.null_count
            if (
                present_containers < 1
                or (
                    container == "nba_api_result_set"
                    and (
                        self.container_count != 1
                        or self.missing_count != 0
                        or self.null_count != 0
                        or self.row_count == 0
                        or self.node_count != 0
                    )
                )
                or (
                    container == "nba_api_static_records"
                    and (
                        self.container_count != 1
                        or self.missing_count != 0
                        or self.null_count != 0
                        or self.row_count == 0
                        or self.node_count != self.row_count
                    )
                )
                or (
                    container in {"nba_api_live_json_array", "nba_api_live_json_object"}
                    and self.node_count
                    != (self.row_count if self.row_count else present_containers)
                )
            ):
                _fail("present occurrence count algebra is inconsistent")
        else:
            _fail("occurrence presence has no exact Raw V2 algebra")

    def ordered_headers(self) -> tuple[str, ...]:
        """Return a fresh exact header tuple, including valid zero-row headers."""

        return _ordered_headers_from_json(
            self.ordered_headers_json,
            ordered_headers_sha256=self.ordered_headers_sha256,
            header_count=self.header_count,
        )

    def canonical_bytes(self) -> bytes:
        return _canonical_json_bytes(
            self.to_row(),
            maximum_bytes=_MAX_OCCURRENCE_ROW_BYTES,
        )

    @classmethod
    def build(cls, **values: Any) -> Self:
        _require_exact_class(cls, ValueProjectionPlanOccurrenceV1, label="occurrence plan")
        payload = {
            "schema_version": VALUE_PROJECTION_PLAN_SCHEMA_VERSION,
            "kind": cls.kind,
            **values,
        }
        return cls(
            occurrence_plan_sha256=_canonical_sha256(
                payload,
                maximum_bytes=_MAX_OCCURRENCE_ROW_BYTES,
            ),
            **values,
        )

    @classmethod
    def from_row(cls, value: object) -> Self:
        _require_exact_class(cls, ValueProjectionPlanOccurrenceV1, label="occurrence plan")
        return cast("Self", _from_row(cls, value, label="occurrence plan row"))

    @classmethod
    def from_canonical_bytes(cls, value: object) -> Self:
        _require_exact_class(cls, ValueProjectionPlanOccurrenceV1, label="occurrence plan")
        return cls.from_row(
            _row_from_canonical_bytes(
                cls,
                value,
                label="occurrence plan",
                maximum_bytes=_MAX_OCCURRENCE_ROW_BYTES,
            )
        )


@dataclass(frozen=True, slots=True)
class ValueProjectionPlanSourceRecordV1(_CanonicalRow):
    source_record_plan_sha256: str
    raw_authority_bundle_sha256: str
    source_record_plan_ordinal: int
    observation_record_sha256: str
    observation_sha256: str
    observation_ordinal: int
    partition_sha256: str
    partition_ordinal: int
    binding_sha256: str
    binding_ordinal: int
    observation_record_ordinal: int
    source_record_sha256: str
    unit_sha256: str
    unit_ordinal: int
    assignment_sha256: str
    unit_kind: Literal["result_occurrence", "response_residual"]
    occurrence_sha256: str | None
    occurrence_ordinal: int | None
    source_input_kind: ValueProjectionPlanSourceInputKindV1
    representation_kind: ValueProjectionPlanRepresentationKindV1
    source_relation_kind: ValueProjectionPlanSourceRelationKindV1
    projection_record_kind: ValueProjectionPlanRecordKindV1

    kind: ClassVar[str] = _SOURCE_RECORD_PLAN_KIND
    digest_field: ClassVar[str] = "source_record_plan_sha256"

    def __post_init__(self) -> None:
        for value, label in (
            (self.source_record_plan_sha256, "source-record plan identity"),
            (self.raw_authority_bundle_sha256, "source-record plan bundle"),
            (self.observation_record_sha256, "source-record plan observation record"),
            (self.observation_sha256, "source-record plan observation"),
            (self.partition_sha256, "source-record plan partition"),
            (self.binding_sha256, "source-record plan binding"),
            (self.source_record_sha256, "source-record plan source record"),
            (self.unit_sha256, "source-record plan unit"),
            (self.assignment_sha256, "source-record plan assignment"),
        ):
            _exact_sha256(value, label=label)
        for value, label, maximum in (
            (
                self.source_record_plan_ordinal,
                "source-record plan ordinal",
                MAX_VALUE_PROJECTION_PLAN_SOURCE_RECORDS - 1,
            ),
            (
                self.observation_ordinal,
                "source-record observation ordinal",
                MAX_VALUE_PROJECTION_PLAN_OBSERVATIONS - 1,
            ),
            (
                self.partition_ordinal,
                "source-record partition ordinal",
                MAX_VALUE_PROJECTION_PLAN_PARTITIONS - 1,
            ),
            (
                self.binding_ordinal,
                "source-record binding ordinal",
                MAX_VALUE_PROJECTION_PLAN_SOURCE_RECORDS - 1,
            ),
            (
                self.observation_record_ordinal,
                "source-record observation ordinal",
                MAX_VALUE_PROJECTION_PLAN_SOURCE_RECORDS - 1,
            ),
            (
                self.unit_ordinal,
                "source-record unit ordinal",
                MAX_VALUE_PROJECTION_PLAN_OBSERVATIONS - 1,
            ),
        ):
            _exact_nonnegative(value, label=label, maximum=maximum)
        if self.unit_kind not in {"result_occurrence", "response_residual"}:
            _fail("source-record plan unit kind cannot own a source record")
        if self.unit_kind == "result_occurrence":
            _exact_sha256(self.occurrence_sha256, label="source-record occurrence")
            _exact_nonnegative(
                self.occurrence_ordinal,
                label="source-record occurrence ordinal",
                maximum=MAX_VALUE_PROJECTION_PLAN_OBSERVATIONS - 1,
            )
        elif self.occurrence_sha256 is not None or self.occurrence_ordinal is not None:
            _fail("response source-record plan fabricates occurrence identity")
        if (
            type(self.source_input_kind) is not str
            or self.source_input_kind not in _SOURCE_INPUT_KINDS
        ):
            _fail("source-record plan input kind is outside its closed V1 domain")
        if (
            type(self.representation_kind) is not str
            or self.representation_kind not in _REPRESENTATION_KINDS
        ):
            _fail("source-record plan representation is outside its closed V1 domain")
        if (
            type(self.source_relation_kind) is not str
            or self.source_relation_kind not in _SOURCE_RELATION_KINDS
        ):
            _fail("source-record plan relation is outside its closed V1 domain")
        if (
            type(self.projection_record_kind) is not str
            or self.projection_record_kind not in _RECORD_KINDS
        ):
            _fail("source-record projection kind is outside its closed V1 domain")
        if self.source_relation_kind not in _RELATIONS_BY_REPRESENTATION[
            self.representation_kind
        ] or self.projection_record_kind not in _RECORDS_BY_RELATION_AND_OWNER.get(
            (self.source_relation_kind, self.unit_kind), frozenset()
        ):
            _fail("source-record relation, owner, or record kind contradicts its representation")
        if self.source_record_plan_sha256 != _canonical_sha256(
            _identity_payload(self, kind=self.kind, digest_field=self.digest_field)
        ):
            _fail("source-record plan digest differs from its exact identity")

    @classmethod
    def build(cls, **values: Any) -> Self:
        _require_exact_class(cls, ValueProjectionPlanSourceRecordV1, label="source-record plan")
        payload = {
            "schema_version": VALUE_PROJECTION_PLAN_SCHEMA_VERSION,
            "kind": cls.kind,
            **values,
        }
        return cls(source_record_plan_sha256=_canonical_sha256(payload), **values)

    @classmethod
    def from_row(cls, value: object) -> Self:
        _require_exact_class(cls, ValueProjectionPlanSourceRecordV1, label="source-record plan")
        return cast("Self", _from_row(cls, value, label="source-record plan row"))

    @classmethod
    def from_canonical_bytes(cls, value: object) -> Self:
        _require_exact_class(cls, ValueProjectionPlanSourceRecordV1, label="source-record plan")
        return cls.from_row(_row_from_canonical_bytes(cls, value, label="source-record plan"))


_PLAN_VECTOR_FIELDS: Final = (
    "expected_units",
    "assignments",
    "ownership_observations",
    "ownership_partitions",
    "ownership_bindings",
    "observation_sources",
    "occurrence_plans",
    "source_record_plans",
)


@dataclass(frozen=True, slots=True)
class ValueProjectionPlanV1:
    plan_sha256: str
    raw_authority_bundle_sha256: str
    ownership_receipt_sha256: str
    expected_unit_inventory_sha256: str
    expected_unit_count: int
    expected_unit_authority_root_sha256: str
    expected_unit_root_sha256: str
    assignment_count: int
    ownership_assignment_root_sha256: str
    assignment_root_sha256: str
    observation_count: int
    ownership_observation_root_sha256: str
    observation_root_sha256: str
    observation_source_count: int
    observation_source_root_sha256: str
    partition_count: int
    ownership_partition_root_sha256: str
    partition_root_sha256: str
    occurrence_count: int
    occurrence_root_sha256: str
    binding_count: int
    ownership_binding_root_sha256: str
    binding_root_sha256: str
    source_record_count: int
    ownership_source_record_root_sha256: str
    source_record_root_sha256: str
    expected_units: tuple[ValueProjectionPlanExpectedUnitV1, ...]
    assignments: tuple[ValueProjectionPlanAssignmentV1, ...]
    ownership_observations: tuple[ValueProjectionPlanOwnershipObservationV1, ...]
    ownership_partitions: tuple[ValueProjectionPlanOwnershipPartitionV1, ...]
    ownership_bindings: tuple[ValueProjectionPlanOwnershipBindingV1, ...]
    observation_sources: tuple[ValueProjectionPlanObservationSourceV1, ...]
    occurrence_plans: tuple[ValueProjectionPlanOccurrenceV1, ...]
    source_record_plans: tuple[ValueProjectionPlanSourceRecordV1, ...]

    schema_version: ClassVar[int] = VALUE_PROJECTION_PLAN_SCHEMA_VERSION
    kind: ClassVar[str] = _PLAN_KIND

    def __post_init__(self) -> None:
        _exact_sha256(self.plan_sha256, label="value-projection plan identity")
        derived = _derive_plan(
            raw_authority_bundle_sha256=self.raw_authority_bundle_sha256,
            ownership_receipt_sha256=self.ownership_receipt_sha256,
            expected_unit_inventory_sha256=self.expected_unit_inventory_sha256,
            expected_units=self.expected_units,
            assignments=self.assignments,
            ownership_observations=self.ownership_observations,
            ownership_partitions=self.ownership_partitions,
            ownership_bindings=self.ownership_bindings,
            observation_sources=self.observation_sources,
            occurrence_plans=self.occurrence_plans,
            source_record_plans=self.source_record_plans,
        )
        for field_name, expected in derived.items():
            if getattr(self, field_name) != expected:
                _fail(f"value-projection plan {field_name} differs from exact replay")
        if self.plan_sha256 != _canonical_sha256(
            self.identity_payload(), maximum_bytes=_MAX_ROW_BYTES
        ):
            _fail("value-projection plan digest differs from its exact identity")

    @classmethod
    def build(
        cls,
        *,
        raw_authority_bundle_sha256: str,
        ownership_receipt_sha256: str,
        expected_unit_inventory_sha256: str,
        expected_units: tuple[ValueProjectionPlanExpectedUnitV1, ...],
        assignments: tuple[ValueProjectionPlanAssignmentV1, ...],
        ownership_observations: tuple[ValueProjectionPlanOwnershipObservationV1, ...],
        ownership_partitions: tuple[ValueProjectionPlanOwnershipPartitionV1, ...],
        ownership_bindings: tuple[ValueProjectionPlanOwnershipBindingV1, ...],
        observation_sources: tuple[ValueProjectionPlanObservationSourceV1, ...],
        occurrence_plans: tuple[ValueProjectionPlanOccurrenceV1, ...],
        source_record_plans: tuple[ValueProjectionPlanSourceRecordV1, ...],
    ) -> Self:
        _require_exact_class(cls, ValueProjectionPlanV1, label="value-projection plan")
        derived = _derive_plan(
            raw_authority_bundle_sha256=raw_authority_bundle_sha256,
            ownership_receipt_sha256=ownership_receipt_sha256,
            expected_unit_inventory_sha256=expected_unit_inventory_sha256,
            expected_units=expected_units,
            assignments=assignments,
            ownership_observations=ownership_observations,
            ownership_partitions=ownership_partitions,
            ownership_bindings=ownership_bindings,
            observation_sources=observation_sources,
            occurrence_plans=occurrence_plans,
            source_record_plans=source_record_plans,
        )
        values = {
            "raw_authority_bundle_sha256": raw_authority_bundle_sha256,
            "ownership_receipt_sha256": ownership_receipt_sha256,
            "expected_unit_inventory_sha256": expected_unit_inventory_sha256,
            **derived,
            "expected_units": expected_units,
            "assignments": assignments,
            "ownership_observations": ownership_observations,
            "ownership_partitions": ownership_partitions,
            "ownership_bindings": ownership_bindings,
            "observation_sources": observation_sources,
            "occurrence_plans": occurrence_plans,
            "source_record_plans": source_record_plans,
        }
        identity = {
            "schema_version": cls.schema_version,
            "kind": cls.kind,
            **{name: value for name, value in values.items() if name not in _PLAN_VECTOR_FIELDS},
        }
        return cls(plan_sha256=_canonical_sha256(identity), **cast("Any", values))

    def identity_payload(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "kind": self.kind,
            **{
                item.name: getattr(self, item.name)
                for item in fields(self)
                if item.name != "plan_sha256" and item.name not in _PLAN_VECTOR_FIELDS
            },
        }

    def to_row(self) -> dict[str, object]:
        row: dict[str, object] = {
            "schema_version": self.schema_version,
            **{
                item.name: getattr(self, item.name)
                for item in fields(self)
                if item.name not in _PLAN_VECTOR_FIELDS
            },
        }
        row.update(
            {
                "expected_units": [item.to_row() for item in self.expected_units],
                "assignments": [item.to_row() for item in self.assignments],
                "ownership_observations": [item.to_row() for item in self.ownership_observations],
                "ownership_partitions": [item.to_row() for item in self.ownership_partitions],
                "ownership_bindings": [item.to_row() for item in self.ownership_bindings],
                "observation_sources": [item.to_row() for item in self.observation_sources],
                "occurrence_plans": [item.to_row() for item in self.occurrence_plans],
                "source_record_plans": [item.to_row() for item in self.source_record_plans],
            }
        )
        return row

    def canonical_bytes(self) -> bytes:
        return _canonical_json_bytes(self.to_row(), maximum_bytes=MAX_VALUE_PROJECTION_PLAN_BYTES)

    @classmethod
    def from_row(
        cls,
        value: object,
        *,
        expected_plan_sha256: str,
        expected_raw_authority_bundle_sha256: str,
        expected_ownership_receipt_sha256: str,
    ) -> Self:
        _require_exact_class(cls, ValueProjectionPlanV1, label="value-projection plan")
        expected_plan = _exact_sha256(expected_plan_sha256, label="expected plan identity")
        expected_bundle = _exact_sha256(
            expected_raw_authority_bundle_sha256,
            label="expected plan raw bundle",
        )
        expected_receipt = _exact_sha256(
            expected_ownership_receipt_sha256,
            label="expected ownership receipt",
        )
        row = _strict_row(
            value, expected_fields=_row_fields(cls), label="value-projection plan row"
        )
        for name, expected in (
            ("plan_sha256", expected_plan),
            ("raw_authority_bundle_sha256", expected_bundle),
            ("ownership_receipt_sha256", expected_receipt),
        ):
            if _exact_sha256(row[name], label=f"candidate {name}") != expected:
                _fail("value-projection plan differs from its external authority pins")
        vector_specs: tuple[tuple[str, type[object], int], ...] = (
            (
                "expected_units",
                ValueProjectionPlanExpectedUnitV1,
                MAX_VALUE_PROJECTION_PLAN_OBSERVATIONS,
            ),
            (
                "assignments",
                ValueProjectionPlanAssignmentV1,
                MAX_VALUE_PROJECTION_PLAN_OBSERVATIONS,
            ),
            (
                "ownership_observations",
                ValueProjectionPlanOwnershipObservationV1,
                MAX_VALUE_PROJECTION_PLAN_OBSERVATIONS,
            ),
            (
                "ownership_partitions",
                ValueProjectionPlanOwnershipPartitionV1,
                MAX_VALUE_PROJECTION_PLAN_PARTITIONS,
            ),
            (
                "ownership_bindings",
                ValueProjectionPlanOwnershipBindingV1,
                MAX_VALUE_PROJECTION_PLAN_SOURCE_RECORDS,
            ),
            (
                "observation_sources",
                ValueProjectionPlanObservationSourceV1,
                MAX_VALUE_PROJECTION_PLAN_OBSERVATIONS,
            ),
            (
                "occurrence_plans",
                ValueProjectionPlanOccurrenceV1,
                MAX_VALUE_PROJECTION_PLAN_OBSERVATIONS,
            ),
            (
                "source_record_plans",
                ValueProjectionPlanSourceRecordV1,
                MAX_VALUE_PROJECTION_PLAN_SOURCE_RECORDS,
            ),
        )
        decoded: dict[str, tuple[object, ...]] = {}
        for name, dto_type, maximum in vector_specs:
            raw = row[name]
            if type(raw) not in {tuple, list}:
                _fail(f"value-projection plan {name} inventory is foreign or over-bound")
            raw_items = cast("list[object] | tuple[object, ...]", raw)
            if len(raw_items) > maximum:
                _fail(f"value-projection plan {name} inventory is foreign or over-bound")
            try:
                decoded[name] = tuple(cast("Any", dto_type).from_row(item) for item in raw_items)
            except ValueProjectionPlanError:
                raise
            except Exception:
                raise ValueProjectionPlanError(
                    f"value-projection plan {name} inventory failed exact replay"
                ) from None
        kwargs = {
            item.name: decoded[item.name] if item.name in decoded else row[item.name]
            for item in fields(cls)
        }
        try:
            return cls(**cast("Any", kwargs))
        except ValueProjectionPlanError:
            raise
        except Exception:
            raise ValueProjectionPlanError(
                "value-projection plan row failed exact semantic replay"
            ) from None

    @classmethod
    def from_canonical_bytes(
        cls,
        value: object,
        *,
        expected_plan_sha256: str,
        expected_raw_authority_bundle_sha256: str,
        expected_ownership_receipt_sha256: str,
    ) -> Self:
        _require_exact_class(cls, ValueProjectionPlanV1, label="value-projection plan")
        _exact_sha256(expected_plan_sha256, label="expected plan identity")
        _exact_sha256(expected_raw_authority_bundle_sha256, label="expected plan raw bundle")
        _exact_sha256(expected_ownership_receipt_sha256, label="expected ownership receipt")
        decoded = _decode_canonical_json(value, maximum_bytes=MAX_VALUE_PROJECTION_PLAN_BYTES)
        if type(decoded) is not dict:
            _fail("value-projection plan canonical bytes do not contain one exact row")
        mapping = cast("dict[str, object]", decoded)
        expected_fields = _row_fields(cls)
        if tuple(mapping) != tuple(sorted(expected_fields)):
            _fail("value-projection plan canonical bytes have foreign fields")
        ordered = {name: mapping[name] for name in expected_fields}
        vector_types: dict[str, type[object]] = {
            "expected_units": ValueProjectionPlanExpectedUnitV1,
            "assignments": ValueProjectionPlanAssignmentV1,
            "ownership_observations": ValueProjectionPlanOwnershipObservationV1,
            "ownership_partitions": ValueProjectionPlanOwnershipPartitionV1,
            "ownership_bindings": ValueProjectionPlanOwnershipBindingV1,
            "observation_sources": ValueProjectionPlanObservationSourceV1,
            "occurrence_plans": ValueProjectionPlanOccurrenceV1,
            "source_record_plans": ValueProjectionPlanSourceRecordV1,
        }
        for name, dto_type in vector_types.items():
            raw_items = ordered[name]
            if type(raw_items) is not list:
                _fail(f"value-projection plan {name} canonical inventory is foreign")
            child_fields = _row_fields(dto_type)
            normalized: list[dict[str, object]] = []
            for raw_item in cast("list[object]", raw_items):
                if type(raw_item) is not dict:
                    _fail(f"value-projection plan {name} canonical row is foreign")
                child = cast("dict[str, object]", raw_item)
                if tuple(child) != tuple(sorted(child_fields)):
                    _fail(f"value-projection plan {name} canonical row has foreign fields")
                normalized.append({field_name: child[field_name] for field_name in child_fields})
            ordered[name] = normalized
        candidate = cls.from_row(
            ordered,
            expected_plan_sha256=expected_plan_sha256,
            expected_raw_authority_bundle_sha256=expected_raw_authority_bundle_sha256,
            expected_ownership_receipt_sha256=expected_ownership_receipt_sha256,
        )
        if cast("bytes", value) != candidate.canonical_bytes():
            _fail("value-projection plan canonical bytes are noncanonical")
        return candidate


def _replay_tuple(
    value: object,
    *,
    cls: type[object],
    maximum: int,
    label: str,
) -> tuple[Any, ...]:
    if type(value) is not tuple or len(value) > maximum:
        _fail(f"{label} is foreign or over-bound")
    exact = value
    if any(type(item) is not cls for item in exact):
        _fail(f"{label} contains a foreign DTO type")
    replayed: list[object] = []
    for item in exact:
        try:
            replayed.append(cast("Any", cls).from_row(cast("Any", item).to_row()))
        except ValueProjectionPlanError:
            raise
        except Exception:
            raise ValueProjectionPlanError(f"{label} failed exact row replay") from None
    return tuple(replayed)


def _derive_plan(
    *,
    raw_authority_bundle_sha256: str,
    ownership_receipt_sha256: str,
    expected_unit_inventory_sha256: str,
    expected_units: object,
    assignments: object,
    ownership_observations: object,
    ownership_partitions: object,
    ownership_bindings: object,
    observation_sources: object,
    occurrence_plans: object,
    source_record_plans: object,
) -> dict[str, object]:
    bundle = _exact_sha256(raw_authority_bundle_sha256, label="plan raw-authority bundle")
    receipt_pin = _exact_sha256(ownership_receipt_sha256, label="plan ownership receipt")
    inventory_pin = _exact_sha256(
        expected_unit_inventory_sha256,
        label="plan expected-unit inventory",
    )
    units = cast(
        "tuple[ValueProjectionPlanExpectedUnitV1, ...]",
        _replay_tuple(
            expected_units,
            cls=ValueProjectionPlanExpectedUnitV1,
            maximum=MAX_VALUE_PROJECTION_PLAN_OBSERVATIONS,
            label="plan expected-unit inventory",
        ),
    )
    exact_assignments = cast(
        "tuple[ValueProjectionPlanAssignmentV1, ...]",
        _replay_tuple(
            assignments,
            cls=ValueProjectionPlanAssignmentV1,
            maximum=MAX_VALUE_PROJECTION_PLAN_OBSERVATIONS,
            label="plan assignment inventory",
        ),
    )
    observations = cast(
        "tuple[ValueProjectionPlanOwnershipObservationV1, ...]",
        _replay_tuple(
            ownership_observations,
            cls=ValueProjectionPlanOwnershipObservationV1,
            maximum=MAX_VALUE_PROJECTION_PLAN_OBSERVATIONS,
            label="plan ownership-observation inventory",
        ),
    )
    partitions = cast(
        "tuple[ValueProjectionPlanOwnershipPartitionV1, ...]",
        _replay_tuple(
            ownership_partitions,
            cls=ValueProjectionPlanOwnershipPartitionV1,
            maximum=MAX_VALUE_PROJECTION_PLAN_PARTITIONS,
            label="plan ownership-partition inventory",
        ),
    )
    bindings = cast(
        "tuple[ValueProjectionPlanOwnershipBindingV1, ...]",
        _replay_tuple(
            ownership_bindings,
            cls=ValueProjectionPlanOwnershipBindingV1,
            maximum=MAX_VALUE_PROJECTION_PLAN_SOURCE_RECORDS,
            label="plan ownership-binding inventory",
        ),
    )
    sources = cast(
        "tuple[ValueProjectionPlanObservationSourceV1, ...]",
        _replay_tuple(
            observation_sources,
            cls=ValueProjectionPlanObservationSourceV1,
            maximum=MAX_VALUE_PROJECTION_PLAN_OBSERVATIONS,
            label="plan observation-source inventory",
        ),
    )
    occurrences = cast(
        "tuple[ValueProjectionPlanOccurrenceV1, ...]",
        _replay_tuple(
            occurrence_plans,
            cls=ValueProjectionPlanOccurrenceV1,
            maximum=MAX_VALUE_PROJECTION_PLAN_OBSERVATIONS,
            label="plan occurrence inventory",
        ),
    )
    records = cast(
        "tuple[ValueProjectionPlanSourceRecordV1, ...]",
        _replay_tuple(
            source_record_plans,
            cls=ValueProjectionPlanSourceRecordV1,
            maximum=MAX_VALUE_PROJECTION_PLAN_SOURCE_RECORDS,
            label="plan source-record inventory",
        ),
    )
    if len(exact_assignments) != len(units):
        _fail("plan expected-unit and assignment denominators differ")
    if len(sources) != len(observations):
        _fail("plan observation and exact source denominators differ")
    if len(records) != len(bindings):
        _fail("plan binding and source-record denominators differ")

    seen_units: set[str] = set()
    seen_occurrences: set[tuple[str, str]] = set()
    completed_unit_observations: set[str] = set()
    active_observation: str | None = None
    active_observation_ordinal = -1
    expected_occurrence_ordinal = 0
    response_seen = False
    for ordinal, (unit, assignment) in enumerate(zip(units, exact_assignments, strict=True)):
        if (
            unit.raw_authority_bundle_sha256 != bundle
            or unit.unit_ordinal != ordinal
            or assignment.raw_authority_bundle_sha256 != bundle
            or assignment.unit_ordinal != ordinal
            or assignment.unit_sha256 != unit.unit_sha256
            or unit.unit_sha256 in seen_units
        ):
            _fail("plan unit or assignment inventory is foreign, duplicate, or reordered")
        seen_units.add(unit.unit_sha256)
        if unit.observation_sha256 != active_observation:
            if active_observation is not None:
                completed_unit_observations.add(active_observation)
            if unit.observation_sha256 in completed_unit_observations:
                _fail("plan expected-unit inventory reopens a completed observation")
            active_observation_ordinal += 1
            active_observation = unit.observation_sha256
            expected_occurrence_ordinal = 0
            response_seen = False
        if unit.observation_ordinal != active_observation_ordinal:
            _fail("plan expected-unit observation order is not contiguous")
        if unit.unit_kind == "result_occurrence":
            if response_seen or unit.occurrence_ordinal != expected_occurrence_ordinal:
                _fail("plan expected-unit occurrence order is not contiguous")
            occurrence_identity = (unit.observation_sha256, cast("str", unit.occurrence_sha256))
            if occurrence_identity in seen_occurrences:
                _fail("plan expected-unit inventory repeats one occurrence")
            seen_occurrences.add(occurrence_identity)
            expected_occurrence_ordinal += 1
            if assignment.representation_kind not in _RESULT_REPRESENTATIONS:
                _fail("result expected unit has a non-result representation")
        elif unit.unit_kind == "response_residual":
            if response_seen or assignment.representation_kind != "response_lossless_records_v1":
                _fail("response-residual expected unit has an invalid assignment")
            response_seen = True
        else:
            if (
                response_seen
                or expected_occurrence_ordinal != 0
                or assignment.representation_kind != "response_fixed_zero_v1"
            ):
                _fail("fixed-zero expected unit has an invalid assignment")
            response_seen = True

    if any(
        observation.raw_authority_bundle_sha256 != bundle
        or observation.observation_ordinal != ordinal
        or source.raw_authority_bundle_sha256 != bundle
        or source.observation_ordinal != ordinal
        or source.observation_record_sha256 != observation.observation_record_sha256
        or source.observation_sha256 != observation.observation_sha256
        or source.source_input_kind != observation.source_input_kind
        for ordinal, (observation, source) in enumerate(zip(observations, sources, strict=True))
    ):
        _fail("plan observation or source inventory is foreign or reordered")
    if len({item.observation_sha256 for item in observations}) != len(observations) or len(
        {item.observation_record_sha256 for item in observations}
    ) != len(observations):
        _fail("plan observation inventory contains a duplicate identity")
    if len({item.source_sha256 for item in sources}) != len(sources):
        _fail("plan observation-source inventory contains a duplicate identity")

    partitions_by_observation: list[list[ValueProjectionPlanOwnershipPartitionV1]] = [
        [] for _ in observations
    ]
    binding_ids_by_partition: list[list[str]] = [[] for _ in partitions]
    record_ids_by_partition: list[list[str]] = [[] for _ in partitions]
    record_kinds_by_partition: list[list[str]] = [[] for _ in partitions]
    record_kind_counts_by_partition: list[dict[str, int]] = [{} for _ in partitions]
    binding_ids_by_observation: list[list[str]] = [[] for _ in observations]
    record_ids_by_observation: list[list[str]] = [[] for _ in observations]
    used_unit_ordinals: set[int] = set()
    result_partitions: list[ValueProjectionPlanOwnershipPartitionV1] = []
    last_observation_ordinal = -1
    next_observation_partition = [0 for _ in observations]
    response_partition_seen = [False for _ in observations]
    for ordinal, partition in enumerate(partitions):
        if partition.observation_ordinal >= len(observations):
            _fail("plan ownership partition references a foreign observation")
        observation = observations[partition.observation_ordinal]
        if (
            partition.raw_authority_bundle_sha256 != bundle
            or partition.partition_ordinal != ordinal
            or partition.observation_record_sha256 != observation.observation_record_sha256
            or partition.observation_sha256 != observation.observation_sha256
            or partition.observation_ordinal < last_observation_ordinal
            or partition.observation_partition_ordinal
            != next_observation_partition[partition.observation_ordinal]
        ):
            _fail("plan ownership partition is foreign or reordered")
        last_observation_ordinal = partition.observation_ordinal
        next_observation_partition[partition.observation_ordinal] += 1
        partitions_by_observation[partition.observation_ordinal].append(partition)
        if partition.partition_kind == "result_occurrence":
            if response_partition_seen[partition.observation_ordinal]:
                _fail("plan occurrence partition follows its response partition")
            result_partitions.append(partition)
        else:
            if response_partition_seen[partition.observation_ordinal]:
                _fail("plan observation contains several response partitions")
            response_partition_seen[partition.observation_ordinal] = True
        if partition.unit_ordinal is None:
            if partition.partition_kind != "response_residual" or partition.record_count != 0:
                _fail("plan ownership partition omits a required expected unit")
            continue
        if partition.unit_ordinal >= len(units) or partition.unit_ordinal in used_unit_ordinals:
            _fail("plan ownership partition duplicates or references a foreign expected unit")
        unit = units[partition.unit_ordinal]
        assignment = exact_assignments[partition.unit_ordinal]
        if (
            partition.unit_sha256 != unit.unit_sha256
            or partition.assignment_sha256 != assignment.assignment_sha256
            or partition.partition_kind != unit.unit_kind
            or partition.observation_sha256 != unit.observation_sha256
            or partition.observation_ordinal != unit.observation_ordinal
            or partition.occurrence_sha256 != unit.occurrence_sha256
            or partition.occurrence_ordinal != unit.occurrence_ordinal
            or assignment.source_input_kind != observation.source_input_kind
        ):
            _fail("plan ownership partition disagrees with its unit or observation")
        used_unit_ordinals.add(partition.unit_ordinal)
    if used_unit_ordinals != set(range(len(units))):
        _fail("plan ownership partitions leave an expected unit orphaned")
    if any(not seen for seen in response_partition_seen):
        _fail("plan observation lacks its mandatory response partition")

    next_record_ordinal = [0 for _ in observations]
    seen_binding_ids: set[str] = set()
    seen_record_ids: set[str] = set()
    last_binding_observation = -1
    for ordinal, (binding, record) in enumerate(zip(bindings, records, strict=True)):
        if binding.observation_ordinal >= len(observations) or binding.partition_ordinal >= len(
            partitions
        ):
            _fail("plan ownership binding references a foreign owner")
        observation = observations[binding.observation_ordinal]
        source = sources[binding.observation_ordinal]
        partition = partitions[binding.partition_ordinal]
        if binding.unit_ordinal >= len(units):
            _fail("plan ownership binding references a foreign expected unit")
        unit = units[binding.unit_ordinal]
        assignment = exact_assignments[binding.unit_ordinal]
        if (
            binding.raw_authority_bundle_sha256 != bundle
            or binding.binding_ordinal != ordinal
            or binding.observation_record_sha256 != observation.observation_record_sha256
            or binding.observation_sha256 != observation.observation_sha256
            or binding.observation_ordinal < last_binding_observation
            or binding.observation_record_ordinal
            != next_record_ordinal[binding.observation_ordinal]
            or partition.observation_ordinal != binding.observation_ordinal
            or binding.unit_sha256 != unit.unit_sha256
            or binding.assignment_sha256 != assignment.assignment_sha256
            or binding.ownership_kind != unit.unit_kind
            or binding.occurrence_sha256 != unit.occurrence_sha256
            or binding.occurrence_ordinal != unit.occurrence_ordinal
            or binding.unit_sha256 != partition.unit_sha256
            or binding.assignment_sha256 != partition.assignment_sha256
            or binding.ownership_kind != partition.partition_kind
        ):
            _fail("plan ownership binding is orphaned, foreign, or reordered")
        if (
            binding.binding_sha256 in seen_binding_ids
            or binding.source_record_sha256 in seen_record_ids
        ):
            _fail("plan ownership binding dual-assigns a source record")
        seen_binding_ids.add(binding.binding_sha256)
        seen_record_ids.add(binding.source_record_sha256)
        last_binding_observation = binding.observation_ordinal
        next_record_ordinal[binding.observation_ordinal] += 1
        binding_ids_by_partition[binding.partition_ordinal].append(binding.binding_sha256)
        record_ids_by_partition[binding.partition_ordinal].append(binding.source_record_sha256)
        binding_ids_by_observation[binding.observation_ordinal].append(binding.binding_sha256)
        record_ids_by_observation[binding.observation_ordinal].append(binding.source_record_sha256)
        if (
            record.raw_authority_bundle_sha256 != bundle
            or record.source_record_plan_ordinal != ordinal
            or record.observation_record_sha256 != binding.observation_record_sha256
            or record.observation_sha256 != binding.observation_sha256
            or record.observation_ordinal != binding.observation_ordinal
            or record.partition_sha256 != partition.partition_sha256
            or record.partition_ordinal != binding.partition_ordinal
            or record.binding_sha256 != binding.binding_sha256
            or record.binding_ordinal != binding.binding_ordinal
            or record.observation_record_ordinal != binding.observation_record_ordinal
            or record.source_record_sha256 != binding.source_record_sha256
            or record.unit_sha256 != binding.unit_sha256
            or record.unit_ordinal != binding.unit_ordinal
            or record.assignment_sha256 != binding.assignment_sha256
            or record.unit_kind != binding.ownership_kind
            or record.occurrence_sha256 != binding.occurrence_sha256
            or record.occurrence_ordinal != binding.occurrence_ordinal
            or record.source_input_kind != observation.source_input_kind
            or record.representation_kind != assignment.representation_kind
        ):
            _fail("plan source-record row disagrees with its exact ownership binding")
        expected_relation = (
            "result_cell_v1"
            if assignment.representation_kind == "rectangular_result_cells_v1"
            else {
                "stats": "stats_lossless_record_v1",
                "live": "live_lossless_node_v1",
            }.get(source.source_family)
        )
        if record.source_relation_kind != expected_relation:
            _fail("plan source-record relation disagrees with its observation source family")
        record_kinds_by_partition[binding.partition_ordinal].append(record.projection_record_kind)
        partition_kind_counts = record_kind_counts_by_partition[binding.partition_ordinal]
        partition_kind_counts[record.projection_record_kind] = (
            partition_kind_counts.get(record.projection_record_kind, 0) + 1
        )

    for partition in partitions:
        binding_ids = tuple(binding_ids_by_partition[partition.partition_ordinal])
        record_ids = tuple(record_ids_by_partition[partition.partition_ordinal])
        if (
            partition.record_count != len(binding_ids)
            or partition.binding_root_sha256
            != _legacy_ordered_root(kind=_PARTITION_BINDING_ROOT_KIND, item_sha256s=binding_ids)
            or partition.record_root_sha256
            != _legacy_ordered_root(kind=_PARTITION_RECORD_ROOT_KIND, item_sha256s=record_ids)
        ):
            _fail("plan ownership partition roots differ from its exact bindings")
        if partition.partition_kind == "response_residual" and partition.record_count:
            record_kinds = record_kinds_by_partition[partition.partition_ordinal]
            source_family = sources[partition.observation_ordinal].source_family
            if source_family == "stats":
                if record_kinds[0] != "response" or any(
                    kind != "json_node" for kind in record_kinds[1:]
                ):
                    _fail("stats response-residual record order or kinds are inconsistent")
            elif source_family == "live":
                if any(kind != "node" for kind in record_kinds):
                    _fail("live response-residual record kinds are inconsistent")
            else:
                _fail("static observation fabricates a response-residual record partition")

    for observation in observations:
        owned_partitions = partitions_by_observation[observation.observation_ordinal]
        partition_ids = tuple(item.partition_sha256 for item in owned_partitions)
        binding_ids = tuple(binding_ids_by_observation[observation.observation_ordinal])
        record_ids = tuple(record_ids_by_observation[observation.observation_ordinal])
        occurrence_partitions = [
            item for item in owned_partitions if item.partition_kind == "result_occurrence"
        ]
        response = owned_partitions[-1]
        if (
            not owned_partitions
            or observation.first_partition_ordinal != owned_partitions[0].partition_ordinal
            or observation.partition_count != len(owned_partitions)
            or observation.partition_root_sha256
            != _legacy_ordered_root(
                kind=_OBSERVATION_PARTITION_ROOT_KIND, item_sha256s=partition_ids
            )
            or observation.result_occurrence_partition_count != len(occurrence_partitions)
            or observation.zero_result_occurrence_partition_count
            != sum(item.record_count == 0 for item in occurrence_partitions)
            or observation.result_occurrence_record_count
            != sum(item.record_count for item in occurrence_partitions)
            or observation.response_partition_kind != response.partition_kind
            or observation.response_record_count != response.record_count
            or observation.fixed_zero_landing_sha256 != response.fixed_zero_landing_sha256
            or observation.record_count != len(binding_ids)
            or observation.binding_count != len(binding_ids)
            or observation.record_root_sha256
            != _legacy_ordered_root(kind=_OBSERVATION_RECORD_ROOT_KIND, item_sha256s=record_ids)
            or observation.binding_root_sha256
            != _legacy_ordered_root(kind=_OBSERVATION_BINDING_ROOT_KIND, item_sha256s=binding_ids)
        ):
            _fail("plan ownership observation differs from its exact child rows")

    if len(occurrences) != len(result_partitions):
        _fail("plan occurrence denominator differs from result partitions")
    duplicate_counts: dict[tuple[int, str], int] = {}
    for ordinal, (occurrence, partition) in enumerate(
        zip(occurrences, result_partitions, strict=True)
    ):
        unit = units[cast("int", partition.unit_ordinal)]
        assignment = exact_assignments[unit.unit_ordinal]
        observation = observations[partition.observation_ordinal]
        source = sources[partition.observation_ordinal]
        duplicate_key = (partition.observation_ordinal, occurrence.result_name)
        expected_duplicate = duplicate_counts.get(duplicate_key, 0)
        duplicate_counts[duplicate_key] = expected_duplicate + 1
        if (
            occurrence.raw_authority_bundle_sha256 != bundle
            or occurrence.occurrence_plan_ordinal != ordinal
            or occurrence.observation_record_sha256 != partition.observation_record_sha256
            or occurrence.observation_sha256 != partition.observation_sha256
            or occurrence.observation_ordinal != partition.observation_ordinal
            or occurrence.partition_sha256 != partition.partition_sha256
            or occurrence.partition_ordinal != partition.partition_ordinal
            or occurrence.occurrence_sha256 != partition.occurrence_sha256
            or occurrence.occurrence_ordinal != partition.occurrence_ordinal
            or occurrence.unit_sha256 != unit.unit_sha256
            or occurrence.unit_ordinal != unit.unit_ordinal
            or occurrence.assignment_sha256 != assignment.assignment_sha256
            or occurrence.source_input_kind != observation.source_input_kind
            or occurrence.representation_kind != assignment.representation_kind
            or occurrence.result_duplicate_ordinal != expected_duplicate
        ):
            _fail("plan occurrence row is foreign, reordered, or semantically inconsistent")
        if (
            (
                assignment.representation_kind == "stats_lossless_records_v1"
                and source.source_family != "stats"
            )
            or (
                assignment.representation_kind == "live_lossless_nodes_v1"
                and source.source_family != "live"
            )
            or (
                assignment.representation_kind == "rectangular_result_cells_v1"
                and source.source_family not in {"stats", "static"}
            )
            or (
                source.source_family == "stats"
                and occurrence.container_kind != "nba_api_result_set"
            )
            or (
                source.source_family == "static"
                and occurrence.container_kind != "nba_api_static_records"
            )
            or (
                source.source_family == "live"
                and occurrence.container_kind
                not in {"nba_api_live_json_array", "nba_api_live_json_object"}
            )
        ):
            _fail("plan occurrence representation or container contradicts its exact source")
        kind_counts = record_kind_counts_by_partition[partition.partition_ordinal]
        if assignment.representation_kind == "rectangular_result_cells_v1":
            if partition.record_count != occurrence.cell_count or kind_counts != (
                {"cell": occurrence.cell_count} if occurrence.cell_count else {}
            ):
                _fail("rectangular occurrence differs from its exact cell partition")
        elif assignment.representation_kind == "stats_lossless_records_v1":
            declaration_kind = (
                "missing_expected" if occurrence.result_presence == "missing" else "result_set"
            )
            expected_counts = {
                declaration_kind: 1,
                "raw_headers": 1,
                "raw_rows": 1,
            }
            for record_kind, count in (
                ("header", occurrence.header_count),
                ("row", occurrence.row_count),
                ("cell", occurrence.cell_count),
            ):
                if count:
                    expected_counts[record_kind] = count
            expected_record_count = (
                3 + occurrence.header_count + occurrence.row_count + occurrence.cell_count
            )
            if (
                occurrence.node_count != 0
                or partition.record_count != expected_record_count
                or kind_counts != expected_counts
            ):
                _fail("stats-lossless occurrence differs from its exact record partition")
        else:
            result_occurrence_record_count = occurrence.container_count + occurrence.missing_count
            node_record_count = kind_counts.get("node", 0)
            if node_record_count < max(
                result_occurrence_record_count,
                occurrence.node_count,
            ):
                _fail("live-lossless occurrence omits its exact root-node denominator")
            expected_counts = {"result_declaration": 1}
            for record_kind, count in (
                ("result_occurrence", result_occurrence_record_count),
                ("node", node_record_count),
                ("field_cell", occurrence.cell_count),
            ):
                if count:
                    expected_counts[record_kind] = count
            expected_record_count = (
                1 + result_occurrence_record_count + node_record_count + occurrence.cell_count
            )
            if partition.record_count != expected_record_count or kind_counts != expected_counts:
                _fail("live-lossless occurrence differs from its exact record partition")

    unit_ids = tuple(item.unit_sha256 for item in units)
    assignment_ids = tuple(item.assignment_sha256 for item in exact_assignments)
    observation_ids = tuple(item.observation_ownership_sha256 for item in observations)
    source_ids = tuple(item.source_sha256 for item in sources)
    partition_ids = tuple(item.partition_sha256 for item in partitions)
    occurrence_ids = tuple(item.occurrence_plan_sha256 for item in occurrences)
    binding_ids = tuple(item.binding_sha256 for item in bindings)
    record_plan_ids = tuple(item.source_record_plan_sha256 for item in records)
    source_record_ids = tuple(item.source_record_sha256 for item in bindings)
    unit_authority_root = _public_unit_root(
        raw_authority_bundle_sha256=bundle,
        unit_sha256s=unit_ids,
    )
    inventory_sha256 = _canonical_sha256(
        {
            "kind": _UNIT_INVENTORY_KIND,
            "schema_version": VALUE_PROJECTION_PLAN_SCHEMA_VERSION,
            "raw_authority_bundle_sha256": bundle,
            "unit_count": len(units),
            "unit_root_sha256": unit_authority_root,
            "units": [item.to_row() for item in units],
        },
        maximum_bytes=MAX_VALUE_PROJECTION_PLAN_BYTES,
    )
    if inventory_sha256 != inventory_pin:
        _fail("plan expected-unit inventory differs from its external identity")
    assignment_authority_root = _legacy_ordered_root(
        kind=_ASSIGNMENT_AUTHORITY_ROOT_KIND,
        item_sha256s=assignment_ids,
    )
    observation_authority_root = _legacy_ordered_root(
        kind=_OBSERVATION_AUTHORITY_ROOT_KIND,
        item_sha256s=observation_ids,
    )
    partition_authority_root = _legacy_ordered_root(
        kind=_PARTITION_AUTHORITY_ROOT_KIND,
        item_sha256s=partition_ids,
    )
    binding_authority_root = _legacy_ordered_root(
        kind=_BINDING_AUTHORITY_ROOT_KIND,
        item_sha256s=binding_ids,
    )
    source_record_authority_root = _legacy_ordered_root(
        kind=_RECORD_AUTHORITY_ROOT_KIND,
        item_sha256s=source_record_ids,
    )
    residual_partitions = [
        item for item in partitions if item.partition_kind == "response_residual"
    ]
    fixed_partitions = [item for item in partitions if item.partition_kind == "response_fixed_zero"]
    ownership_values: dict[str, object] = {
        "raw_authority_bundle_sha256": bundle,
        "expected_unit_count": len(units),
        "expected_unit_inventory_sha256": inventory_sha256,
        "expected_unit_root_sha256": unit_authority_root,
        "representation_assignment_count": len(exact_assignments),
        "representation_assignment_root_sha256": assignment_authority_root,
        "observation_count": len(observations),
        "observation_root_sha256": observation_authority_root,
        "partition_count": len(partitions),
        "partition_root_sha256": partition_authority_root,
        "result_occurrence_partition_count": len(result_partitions),
        "zero_result_occurrence_partition_count": sum(
            item.record_count == 0 for item in result_partitions
        ),
        "result_occurrence_record_count": sum(item.record_count for item in result_partitions),
        "response_residual_partition_count": len(residual_partitions),
        "positive_response_residual_partition_count": sum(
            item.record_count > 0 for item in residual_partitions
        ),
        "zero_response_residual_partition_count": sum(
            item.record_count == 0 for item in residual_partitions
        ),
        "response_residual_record_count": sum(item.record_count for item in residual_partitions),
        "response_fixed_zero_partition_count": len(fixed_partitions),
        "fixed_zero_landing_root_sha256": _legacy_ordered_root(
            kind=_FIXED_ZERO_ROOT_KIND,
            item_sha256s=tuple(
                cast("str", item.fixed_zero_landing_sha256) for item in fixed_partitions
            ),
        ),
        "binding_count": len(bindings),
        "binding_root_sha256": binding_authority_root,
        "source_record_count": len(bindings),
        "source_record_root_sha256": source_record_authority_root,
    }
    receipt_sha256 = _canonical_sha256(
        {
            "schema_version": VALUE_PROJECTION_PLAN_SCHEMA_VERSION,
            "kind": _OWNERSHIP_RECEIPT_KIND,
            **ownership_values,
        }
    )
    if receipt_sha256 != receipt_pin:
        _fail("plan ownership receipt differs from exact independent replay")
    return {
        "expected_unit_count": len(units),
        "expected_unit_authority_root_sha256": unit_authority_root,
        "expected_unit_root_sha256": _length_framed_root(
            kind=_PLAN_UNIT_ROOT_KIND,
            raw_authority_bundle_sha256=bundle,
            item_sha256s=unit_ids,
            maximum=MAX_VALUE_PROJECTION_PLAN_OBSERVATIONS,
        ),
        "assignment_count": len(exact_assignments),
        "ownership_assignment_root_sha256": assignment_authority_root,
        "assignment_root_sha256": _length_framed_root(
            kind=_PLAN_ASSIGNMENT_ROOT_KIND,
            raw_authority_bundle_sha256=bundle,
            item_sha256s=assignment_ids,
            maximum=MAX_VALUE_PROJECTION_PLAN_OBSERVATIONS,
        ),
        "observation_count": len(observations),
        "ownership_observation_root_sha256": observation_authority_root,
        "observation_root_sha256": _length_framed_root(
            kind=_PLAN_OBSERVATION_ROOT_KIND,
            raw_authority_bundle_sha256=bundle,
            item_sha256s=observation_ids,
            maximum=MAX_VALUE_PROJECTION_PLAN_OBSERVATIONS,
        ),
        "observation_source_count": len(sources),
        "observation_source_root_sha256": _length_framed_root(
            kind=_PLAN_SOURCE_ROOT_KIND,
            raw_authority_bundle_sha256=bundle,
            item_sha256s=source_ids,
            maximum=MAX_VALUE_PROJECTION_PLAN_OBSERVATIONS,
        ),
        "partition_count": len(partitions),
        "ownership_partition_root_sha256": partition_authority_root,
        "partition_root_sha256": _length_framed_root(
            kind=_PLAN_PARTITION_ROOT_KIND,
            raw_authority_bundle_sha256=bundle,
            item_sha256s=partition_ids,
            maximum=MAX_VALUE_PROJECTION_PLAN_PARTITIONS,
        ),
        "occurrence_count": len(occurrences),
        "occurrence_root_sha256": _length_framed_root(
            kind=_PLAN_OCCURRENCE_ROOT_KIND,
            raw_authority_bundle_sha256=bundle,
            item_sha256s=occurrence_ids,
            maximum=MAX_VALUE_PROJECTION_PLAN_OBSERVATIONS,
        ),
        "binding_count": len(bindings),
        "ownership_binding_root_sha256": binding_authority_root,
        "binding_root_sha256": _length_framed_root(
            kind=_PLAN_BINDING_ROOT_KIND,
            raw_authority_bundle_sha256=bundle,
            item_sha256s=binding_ids,
            maximum=MAX_VALUE_PROJECTION_PLAN_SOURCE_RECORDS,
        ),
        "source_record_count": len(records),
        "ownership_source_record_root_sha256": source_record_authority_root,
        "source_record_root_sha256": _length_framed_root(
            kind=_PLAN_SOURCE_RECORD_ROOT_KIND,
            raw_authority_bundle_sha256=bundle,
            item_sha256s=record_plan_ids,
            maximum=MAX_VALUE_PROJECTION_PLAN_SOURCE_RECORDS,
        ),
    }


def validate_value_projection_plan(
    value: object,
    *,
    expected_plan_sha256: str,
    expected_raw_authority_bundle_sha256: str,
    expected_ownership_receipt_sha256: str,
) -> ValueProjectionPlanV1:
    """Replay one exact plan after checking all external pins before traversal."""

    expected_plan = _exact_sha256(expected_plan_sha256, label="expected plan identity")
    expected_bundle = _exact_sha256(
        expected_raw_authority_bundle_sha256,
        label="expected plan raw bundle",
    )
    expected_receipt = _exact_sha256(
        expected_ownership_receipt_sha256,
        label="expected ownership receipt",
    )
    if type(value) is not ValueProjectionPlanV1:
        _fail("value-projection plan has a foreign exact type")
    try:
        candidate_plan = value.plan_sha256
        candidate_bundle = value.raw_authority_bundle_sha256
        candidate_receipt = value.ownership_receipt_sha256
    except Exception:
        raise ValueProjectionPlanError("value-projection plan fields are invalid") from None
    if (
        _exact_sha256(candidate_plan, label="candidate plan identity") != expected_plan
        or _exact_sha256(candidate_bundle, label="candidate plan bundle") != expected_bundle
        or _exact_sha256(candidate_receipt, label="candidate ownership receipt") != expected_receipt
    ):
        _fail("value-projection plan differs from its external authority pins")
    try:
        row = value.to_row()
    except Exception:
        raise ValueProjectionPlanError("value-projection plan fields are invalid") from None
    return ValueProjectionPlanV1.from_row(
        row,
        expected_plan_sha256=expected_plan,
        expected_raw_authority_bundle_sha256=expected_bundle,
        expected_ownership_receipt_sha256=expected_receipt,
    )
