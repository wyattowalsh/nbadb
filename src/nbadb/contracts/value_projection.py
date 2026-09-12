"""Dependency-pure canonical value projection receipts for W2.

The DTOs in this module form the common, value-bearing leaf below the public
value assignment and lossless ownership authorities.  They intentionally
consume only exact built-in values and already-normalized scalar identities.
No parser, extractor, schema, frame library, or side verifier is imported.

Every source record projects to exactly one :class:`ValueProjectionItemV1`.
Explicit partitions retain zero-result, zero-residual, and fixed-zero proofs;
the aggregate receipt binds their canonical order to the Raw Authority bundle.
"""

from __future__ import annotations

import hashlib
import json
import math
import re
from dataclasses import dataclass, fields
from typing import Any, ClassVar, Final, Literal, Never, Self, cast

__all__ = [
    "BODY_VALUE_PROJECTION_SCHEMA_VERSION",
    "MAX_VALUE_PROJECTION_ITEMS",
    "MAX_VALUE_PROJECTION_OBSERVATIONS",
    "MAX_VALUE_PROJECTION_PARTITIONS",
    "VALUE_PROJECTION_COORDINATE_FIELDS_V1",
    "VALUE_PROJECTION_HEADER_REFERENCE_KINDS_V1",
    "VALUE_PROJECTION_PRESENCE_KINDS_V1",
    "VALUE_PROJECTION_RECORD_KINDS_V1",
    "VALUE_PROJECTION_REPRESENTATION_KINDS_V1",
    "VALUE_PROJECTION_SOURCE_INPUT_KINDS_V1",
    "VALUE_PROJECTION_UNIT_KINDS_V1",
    "VALUE_PROJECTION_VALUE_KINDS_V1",
    "VALUE_PROJECTION_VALUE_STATES_V1",
    "BodyValueProjectionReceiptV1",
    "ValueProjectionError",
    "ValueProjectionItemV1",
    "ValueProjectionPartitionV1",
    "ValueProjectionReceiptV1",
]


BODY_VALUE_PROJECTION_SCHEMA_VERSION: Final = 1
MAX_VALUE_PROJECTION_OBSERVATIONS: Final = 100_000
MAX_VALUE_PROJECTION_PARTITIONS: Final = 200_000
MAX_VALUE_PROJECTION_ITEMS: Final = 14_000_000
MAX_VALUE_PROJECTION_CANONICAL_VALUE_BYTES: Final = 64 * 1024 * 1024
MAX_VALUE_PROJECTION_TOTAL_CANONICAL_BYTES: Final = 256 * 1024 * 1024
MAX_VALUE_PROJECTION_JSON_DEPTH: Final = 64
MAX_VALUE_PROJECTION_JSON_NODES: Final = 2_000_000
MAX_VALUE_PROJECTION_PATH_BYTES: Final = 4_096

ValueProjectionSourceInputKindV1 = Literal[
    "parser_input_body",
    "declared_bodyless_packet",
]
ValueProjectionRepresentationKindV1 = Literal[
    "rectangular_result_cells_v1",
    "stats_lossless_records_v1",
    "live_lossless_nodes_v1",
    "response_lossless_records_v1",
    "response_fixed_zero_v1",
]
ValueProjectionUnitKindV1 = Literal[
    "result_occurrence",
    "response_residual",
    "response_fixed_zero",
]
ValueProjectionRecordKindV1 = Literal[
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
ValueProjectionValueStateV1 = Literal[
    "canonical",
    "structural_container",
    "missing",
    "absent",
]
ValueProjectionHeaderReferenceKindV1 = Literal[
    "named",
    "non_string",
    "out_of_range",
]
ValueProjectionPresenceKindV1 = Literal[
    "present",
    "null",
    "empty_object",
    "empty_array",
    "missing",
    "mixed_absent",
    "not_observed_parent_empty",
]
ValueProjectionValueKindV1 = Literal[
    "null",
    "boolean",
    "integer",
    "number",
    "string",
    "array",
    "object",
    "missing",
]

VALUE_PROJECTION_SOURCE_INPUT_KINDS_V1: Final = (
    "parser_input_body",
    "declared_bodyless_packet",
)
VALUE_PROJECTION_REPRESENTATION_KINDS_V1: Final = (
    "rectangular_result_cells_v1",
    "stats_lossless_records_v1",
    "live_lossless_nodes_v1",
    "response_lossless_records_v1",
    "response_fixed_zero_v1",
)
VALUE_PROJECTION_UNIT_KINDS_V1: Final = (
    "result_occurrence",
    "response_residual",
    "response_fixed_zero",
)
VALUE_PROJECTION_RECORD_KINDS_V1: Final = (
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
VALUE_PROJECTION_VALUE_STATES_V1: Final = (
    "canonical",
    "structural_container",
    "missing",
    "absent",
)
VALUE_PROJECTION_HEADER_REFERENCE_KINDS_V1: Final = (
    "named",
    "non_string",
    "out_of_range",
)
VALUE_PROJECTION_PRESENCE_KINDS_V1: Final = (
    "present",
    "null",
    "empty_object",
    "empty_array",
    "missing",
    "mixed_absent",
    "not_observed_parent_empty",
)
VALUE_PROJECTION_VALUE_KINDS_V1: Final = (
    "null",
    "boolean",
    "integer",
    "number",
    "string",
    "array",
    "object",
    "missing",
)

# The coordinate object always carries every key.  A representation uses only
# the applicable coordinates and writes JSON null for the remainder.  This
# prevents open-ended metadata from becoming part of the public value plane.
VALUE_PROJECTION_COORDINATE_FIELDS_V1: Final = (
    "result_name",
    "result_duplicate_ordinal",
    "provider_result_ordinal",
    "expected_result_ordinal",
    "canonical_result_ordinal",
    "result_path",
    "container_kind",
    "result_presence",
    "header_reference_kind",
    "header_name",
    "header_ordinal",
    "header_value_sha256",
    "header_duplicate_ordinal",
    "field_name",
    "field_ordinal",
    "row_ordinal",
    "row_duplicate_ordinal",
    "row_value_sha256",
    "cell_ordinal",
    "value_duplicate_ordinal",
    "node_ordinal",
    "parent_node_ordinal",
    "json_path",
    "parent_json_path",
    "depth",
    "object_key",
    "object_key_ordinal",
    "array_ordinal",
    "key_presence",
    "owner_result_name",
    "owner_result_ordinal",
    "owner_result_occurrence",
    "context_result_name",
    "context_result_ordinal",
    "context_result_occurrence",
    "declaration_parent_result_name",
    "declaration_parent_field_name",
    "result_occurrence_global_ordinal",
    "result_occurrence_ordinal",
    "result_occurrence_parent_result_name",
    "result_occurrence_parent_result_ordinal",
    "result_occurrence_presence_kind",
    "result_occurrence_row_count",
    "decoder_value_sha256",
    "matches_result_occurrence",
    "known_contract_field",
)

_MAX_ORDINAL: Final = (1 << 63) - 1
_MAX_ROW_BYTES: Final = MAX_VALUE_PROJECTION_CANONICAL_VALUE_BYTES + (256 * 1024)
_MAX_RECEIPT_BYTES: Final = 256 * 1024
_MAX_METADATA_TEXT_BYTES: Final = 4_096
_MAX_HEADER_COUNT: Final = 4_096
_MAX_JSON_NUMBER_TOKEN_BYTES: Final = 128
_SHA256_RE: Final = re.compile(r"[0-9a-f]{64}\Z")

_SOURCE_INPUT_KINDS = frozenset(VALUE_PROJECTION_SOURCE_INPUT_KINDS_V1)
_REPRESENTATION_KINDS = frozenset(VALUE_PROJECTION_REPRESENTATION_KINDS_V1)
_UNIT_KINDS = frozenset(VALUE_PROJECTION_UNIT_KINDS_V1)
_RECORD_KINDS = frozenset(VALUE_PROJECTION_RECORD_KINDS_V1)
_VALUE_STATES = frozenset(VALUE_PROJECTION_VALUE_STATES_V1)
_HEADER_REFERENCE_KINDS = frozenset(VALUE_PROJECTION_HEADER_REFERENCE_KINDS_V1)
_PRESENCE_KINDS = frozenset(VALUE_PROJECTION_PRESENCE_KINDS_V1)
_VALUE_KINDS = frozenset(VALUE_PROJECTION_VALUE_KINDS_V1)
_RESULT_REPRESENTATIONS = frozenset(
    {
        "rectangular_result_cells_v1",
        "stats_lossless_records_v1",
        "live_lossless_nodes_v1",
    }
)
_RESULT_CONTAINERS_BY_REPRESENTATION: Final = {
    "rectangular_result_cells_v1": frozenset({"nba_api_result_set", "nba_api_static_records"}),
    "stats_lossless_records_v1": frozenset({"nba_api_result_set"}),
    "live_lossless_nodes_v1": frozenset({"nba_api_live_json_array", "nba_api_live_json_object"}),
}
_MISSING_PRESENCES = frozenset({"missing", "mixed_absent", "not_observed_parent_empty"})
_LIVE_OCCURRENCE_PRESENCES = frozenset(
    {"present", "null", "empty_object", "empty_array", "missing"}
)
_RESULT_PRESENCES = frozenset(
    {
        "present",
        "present_empty",
        "missing",
        "empty_array",
        "null",
        "mixed_absent",
        "not_observed_parent_empty",
    }
)
_KEY_PRESENCES = frozenset({"required", "optional", "optional_or_undocumented"})

_RECORDS_BY_REPRESENTATION: Final = {
    "rectangular_result_cells_v1": frozenset({"cell"}),
    "stats_lossless_records_v1": frozenset(
        {
            "result_set",
            "missing_expected",
            "raw_headers",
            "raw_rows",
            "header",
            "row",
            "cell",
        }
    ),
    "live_lossless_nodes_v1": frozenset(
        {"result_declaration", "result_occurrence", "node", "field_cell"}
    ),
    "response_lossless_records_v1": frozenset({"response", "json_node", "node"}),
}

_ITEM_KIND: Final = "nbadb_value_projection_item_v1"
_PARTITION_KIND: Final = "nbadb_value_projection_partition_v1"
_RECEIPT_KIND: Final = "nbadb_value_projection_receipt_v1"
_BODY_RECEIPT_KIND: Final = "nbadb_body_value_projection_receipt_v1"
_PARTITION_ITEM_ROOT_KIND: Final = "nbadb_value_projection_partition_items_v1"
_PARTITION_RECORD_ROOT_KIND: Final = "nbadb_value_projection_partition_records_v1"
_PARTITION_BINDING_ROOT_KIND: Final = "nbadb_value_projection_partition_bindings_v1"
_OBSERVATION_ROOT_KIND: Final = "nbadb_value_projection_observations_v1"
_PARTITION_ROOT_KIND: Final = "nbadb_value_projection_partitions_v1"
_ITEM_ROOT_KIND: Final = "nbadb_value_projection_items_v1"
_SOURCE_RECORD_ROOT_KIND: Final = "nbadb_value_projection_source_records_v1"
_BINDING_ROOT_KIND: Final = "nbadb_value_projection_bindings_v1"
_UNIT_ROOT_KIND: Final = "nbadb_value_projection_units_v1"
_ASSIGNMENT_ROOT_KIND: Final = "nbadb_value_projection_assignments_v1"
_FIXED_ZERO_ROOT_KIND: Final = "nbadb_value_projection_fixed_zero_landings_v1"
_BODY_BLOB_ROOT_KIND: Final = "nbadb_body_value_projection_body_blobs_v1"
_BODY_READBACK_ROOT_KIND: Final = "nbadb_body_value_projection_body_readbacks_v1"
_PARSER_INPUT_ROOT_KIND: Final = "nbadb_body_value_projection_parser_inputs_v1"
_BODYLESS_PACKET_ROOT_KIND: Final = "nbadb_body_value_projection_bodyless_packets_v1"
_BODYLESS_READBACK_ROOT_KIND: Final = "nbadb_body_value_projection_bodyless_readbacks_v1"
_OBSERVATION_SOURCE_ROOT_KIND: Final = "nbadb_body_value_projection_sources_v1"
_PUBLIC_UNIT_ROOT_KIND: Final = "nbadb_expected_value_unit_ordered_root_v1"
_OWNERSHIP_ASSIGNMENT_ROOT_KIND: Final = "nbadb_lossless_representation_assignments_v1"

_PUBLIC_UNIT_KIND: Final = "nbadb_expected_value_unit_v1"
_PUBLIC_UNIT_INVENTORY_KIND: Final = "nbadb_expected_value_unit_inventory_v1"
_PUBLIC_ASSIGNMENT_KIND: Final = "nbadb_value_representation_assignment_v1"
_OWNERSHIP_BINDING_KIND: Final = "nbadb_lossless_ownership_binding_v1"
_OWNERSHIP_PARTITION_KIND: Final = "nbadb_lossless_ownership_partition_v1"
_OWNERSHIP_OBSERVATION_KIND: Final = "nbadb_lossless_observation_ownership_v1"
_OWNERSHIP_RECEIPT_KIND: Final = "nbadb_lossless_ownership_receipt_v1"
_OWNERSHIP_PARTITION_BINDING_ROOT_KIND: Final = "nbadb_lossless_partition_bindings_v1"
_OWNERSHIP_PARTITION_RECORD_ROOT_KIND: Final = "nbadb_lossless_partition_source_records_v1"
_OWNERSHIP_OBSERVATION_PARTITION_ROOT_KIND: Final = "nbadb_lossless_observation_partitions_v1"
_OWNERSHIP_OBSERVATION_BINDING_ROOT_KIND: Final = "nbadb_lossless_observation_bindings_v1"
_OWNERSHIP_OBSERVATION_RECORD_ROOT_KIND: Final = "nbadb_lossless_observation_source_records_v1"
_OWNERSHIP_OBSERVATION_ROOT_KIND: Final = "nbadb_lossless_owned_observations_v1"
_OWNERSHIP_PARTITION_ROOT_KIND: Final = "nbadb_lossless_ownership_partitions_v1"
_OWNERSHIP_BINDING_ROOT_KIND: Final = "nbadb_lossless_ownership_bindings_v1"
_OWNERSHIP_RECORD_ROOT_KIND: Final = "nbadb_lossless_owned_source_records_v1"
_OWNERSHIP_FIXED_ZERO_ROOT_KIND: Final = "nbadb_lossless_fixed_zero_landings_v1"
_MAX_SEMANTIC_INVENTORY_BYTES: Final = 64 * 1024 * 1024

_PUBLIC_UNIT_ROW_FIELDS: Final = (
    "schema_version",
    "unit_sha256",
    "raw_authority_bundle_sha256",
    "unit_ordinal",
    "observation_sha256",
    "observation_ordinal",
    "unit_kind",
    "occurrence_sha256",
    "occurrence_ordinal",
)
_PUBLIC_ASSIGNMENT_ROW_FIELDS: Final = (
    "schema_version",
    "assignment_sha256",
    "raw_authority_bundle_sha256",
    "unit_sha256",
    "unit_ordinal",
    "source_input_kind",
    "representation_kind",
)
_OWNERSHIP_BINDING_ROW_FIELDS: Final = (
    "schema_version",
    "binding_sha256",
    "raw_authority_bundle_sha256",
    "observation_record_sha256",
    "observation_sha256",
    "observation_ordinal",
    "binding_ordinal",
    "observation_record_ordinal",
    "partition_ordinal",
    "source_record_sha256",
    "unit_sha256",
    "unit_ordinal",
    "assignment_sha256",
    "ownership_kind",
    "occurrence_sha256",
    "occurrence_ordinal",
)
_OWNERSHIP_PARTITION_ROW_FIELDS: Final = (
    "schema_version",
    "partition_sha256",
    "raw_authority_bundle_sha256",
    "observation_record_sha256",
    "observation_sha256",
    "observation_ordinal",
    "partition_ordinal",
    "observation_partition_ordinal",
    "partition_kind",
    "occurrence_sha256",
    "occurrence_ordinal",
    "unit_sha256",
    "unit_ordinal",
    "assignment_sha256",
    "record_count",
    "record_root_sha256",
    "binding_root_sha256",
    "fixed_zero_landing_sha256",
)
_OWNERSHIP_OBSERVATION_ROW_FIELDS: Final = (
    "schema_version",
    "observation_ownership_sha256",
    "raw_authority_bundle_sha256",
    "observation_record_sha256",
    "observation_sha256",
    "observation_ordinal",
    "source_input_kind",
    "first_partition_ordinal",
    "partition_count",
    "partition_root_sha256",
    "result_occurrence_partition_count",
    "zero_result_occurrence_partition_count",
    "result_occurrence_record_count",
    "response_partition_kind",
    "response_record_count",
    "fixed_zero_landing_sha256",
    "record_count",
    "record_root_sha256",
    "binding_count",
    "binding_root_sha256",
)
_OWNERSHIP_RECEIPT_ROW_FIELDS: Final = (
    "schema_version",
    "receipt_sha256",
    "raw_authority_bundle_sha256",
    "expected_unit_count",
    "expected_unit_inventory_sha256",
    "expected_unit_root_sha256",
    "representation_assignment_count",
    "representation_assignment_root_sha256",
    "observation_count",
    "observation_root_sha256",
    "partition_count",
    "partition_root_sha256",
    "result_occurrence_partition_count",
    "zero_result_occurrence_partition_count",
    "result_occurrence_record_count",
    "response_residual_partition_count",
    "positive_response_residual_partition_count",
    "zero_response_residual_partition_count",
    "response_residual_record_count",
    "response_fixed_zero_partition_count",
    "fixed_zero_landing_root_sha256",
    "binding_count",
    "binding_root_sha256",
    "source_record_count",
    "source_record_root_sha256",
)

_COORDINATE_ORDINAL_FIELDS: Final = frozenset(
    {
        "result_duplicate_ordinal",
        "provider_result_ordinal",
        "expected_result_ordinal",
        "canonical_result_ordinal",
        "header_ordinal",
        "header_duplicate_ordinal",
        "field_ordinal",
        "row_ordinal",
        "row_duplicate_ordinal",
        "cell_ordinal",
        "value_duplicate_ordinal",
        "node_ordinal",
        "parent_node_ordinal",
        "depth",
        "object_key_ordinal",
        "array_ordinal",
        "owner_result_ordinal",
        "owner_result_occurrence",
        "context_result_ordinal",
        "context_result_occurrence",
        "result_occurrence_global_ordinal",
        "result_occurrence_ordinal",
        "result_occurrence_parent_result_ordinal",
        "result_occurrence_row_count",
    }
)
_COORDINATE_TEXT_FIELDS: Final = frozenset(
    {
        "result_name",
        "result_path",
        "container_kind",
        "result_presence",
        "header_reference_kind",
        "header_name",
        "field_name",
        "json_path",
        "parent_json_path",
        "object_key",
        "key_presence",
        "owner_result_name",
        "context_result_name",
        "declaration_parent_result_name",
        "declaration_parent_field_name",
        "result_occurrence_parent_result_name",
        "result_occurrence_presence_kind",
    }
)
_COORDINATE_PATH_FIELDS: Final = frozenset({"result_path", "json_path", "parent_json_path"})

_RESULT_COORDINATE_FIELDS: Final = frozenset(
    {
        "result_name",
        "result_duplicate_ordinal",
        "provider_result_ordinal",
        "expected_result_ordinal",
        "canonical_result_ordinal",
        "result_path",
        "container_kind",
        "result_presence",
    }
)
_BASIC_HEADER_COORDINATE_FIELDS: Final = frozenset(
    {"header_name", "header_ordinal", "header_duplicate_ordinal"}
)
_STATS_HEADER_COORDINATE_FIELDS: Final = frozenset(
    {
        "header_reference_kind",
        "header_name",
        "header_ordinal",
        "header_value_sha256",
        "header_duplicate_ordinal",
    }
)
_HEADER_SLOT_FIELDS: Final = frozenset(
    {"header_reference_kind", "header_name", "header_value_sha256"}
)
_FIELD_COORDINATE_FIELDS: Final = frozenset({"field_name", "field_ordinal"})
_ROW_COORDINATE_FIELDS: Final = frozenset(
    {"row_ordinal", "row_duplicate_ordinal", "row_value_sha256"}
)
_CELL_COORDINATE_FIELDS: Final = frozenset({"cell_ordinal", "value_duplicate_ordinal"})
_NODE_COORDINATE_FIELDS: Final = frozenset(
    {
        "node_ordinal",
        "parent_node_ordinal",
        "json_path",
        "parent_json_path",
        "depth",
        "object_key",
        "object_key_ordinal",
        "array_ordinal",
    }
)
_LIVE_CONTEXT_COORDINATE_FIELDS: Final = frozenset(
    {
        "key_presence",
        "owner_result_name",
        "owner_result_ordinal",
        "owner_result_occurrence",
        "context_result_name",
        "context_result_ordinal",
        "context_result_occurrence",
        "known_contract_field",
    }
)
_LIVE_NODE_CONTEXT_COORDINATE_FIELDS: Final = frozenset(
    {
        "context_result_name",
        "context_result_ordinal",
        "context_result_occurrence",
        "known_contract_field",
    }
)
_LIVE_FIELD_REQUIRED_COORDINATE_FIELDS: Final = frozenset(
    {
        "key_presence",
        "owner_result_name",
        "owner_result_ordinal",
        "owner_result_occurrence",
        "context_result_name",
        "context_result_ordinal",
        "context_result_occurrence",
        "known_contract_field",
    }
)

_LIVE_DECLARATION_COORDINATE_FIELDS: Final = frozenset(
    {
        "declaration_parent_result_name",
        "declaration_parent_field_name",
    }
)
_LIVE_OCCURRENCE_COORDINATE_FIELDS: Final = frozenset(
    {
        "node_ordinal",
        "json_path",
        "result_occurrence_global_ordinal",
        "result_occurrence_ordinal",
        "result_occurrence_parent_result_name",
        "result_occurrence_parent_result_ordinal",
        "result_occurrence_presence_kind",
        "result_occurrence_row_count",
        "decoder_value_sha256",
    }
)


class ValueProjectionError(ValueError):
    """A value projection identity or aggregate proof is invalid."""


def _fail(message: str) -> Never:
    raise ValueProjectionError(message)


def _exact_sha256(value: object, *, field_name: str) -> str:
    if type(value) is not str or _SHA256_RE.fullmatch(value) is None:
        _fail(f"{field_name} must be one lowercase full SHA-256")
    return value


def _optional_sha256(value: object, *, field_name: str) -> str | None:
    if value is None:
        return None
    return _exact_sha256(value, field_name=field_name)


def _exact_nonnegative(value: object, *, field_name: str, maximum: int) -> int:
    if type(value) is not int or value < 0 or value > maximum:
        _fail(f"{field_name} must be one bounded nonnegative exact integer")
    return value


def _optional_nonnegative(
    value: object,
    *,
    field_name: str,
    maximum: int,
) -> int | None:
    if value is None:
        return None
    return _exact_nonnegative(value, field_name=field_name, maximum=maximum)


def _exact_text(
    value: object,
    *,
    field_name: str,
    maximum_bytes: int,
    allow_empty: bool = False,
) -> str:
    if type(value) is not str or (not allow_empty and not value):
        _fail(f"{field_name} must be exact bounded text")
    try:
        encoded = value.encode("utf-8", errors="strict")
    except UnicodeEncodeError:
        _fail(f"{field_name} contains invalid Unicode")
    if len(encoded) > maximum_bytes:
        _fail(f"{field_name} exceeds its UTF-8 byte bound")
    return value


def _optional_text(
    value: object,
    *,
    field_name: str,
    maximum_bytes: int,
    allow_empty: bool = False,
) -> str | None:
    if value is None:
        return None
    return _exact_text(
        value,
        field_name=field_name,
        maximum_bytes=maximum_bytes,
        allow_empty=allow_empty,
    )


def _preflight_builtin_graph(value: object, *, maximum_bytes: int) -> None:
    stack: list[tuple[object, int]] = [(value, 0)]
    node_count = 0
    string_bytes = 0
    while stack:
        item, depth = stack.pop()
        node_count += 1
        if node_count > MAX_VALUE_PROJECTION_JSON_NODES:
            _fail("value-projection canonical graph exceeds its node bound")
        if depth > MAX_VALUE_PROJECTION_JSON_DEPTH:
            _fail("value-projection canonical graph exceeds its depth bound")
        if item is None or type(item) is bool:
            continue
        if type(item) is int:
            if item < -_MAX_ORDINAL or item > _MAX_ORDINAL:
                _fail("value-projection canonical graph contains an unbounded integer")
            continue
        if type(item) is float:
            if not math.isfinite(item):
                _fail("value-projection canonical graph contains a nonfinite number")
            continue
        if type(item) is str:
            try:
                string_bytes += len(item.encode("utf-8", errors="strict"))
            except UnicodeEncodeError:
                _fail("value-projection canonical graph contains invalid Unicode")
            if string_bytes > maximum_bytes:
                _fail("value-projection canonical graph exceeds its string-byte bound")
            continue
        if type(item) is list:
            stack.extend((child, depth + 1) for child in reversed(cast("list[object]", item)))
            continue
        if type(item) is dict:
            mapping = cast("dict[object, object]", item)
            for key, child in reversed(tuple(mapping.items())):
                if type(key) is not str:
                    _fail("value-projection canonical graph contains a non-string key")
                try:
                    string_bytes += len(key.encode("utf-8", errors="strict"))
                except UnicodeEncodeError:
                    _fail("value-projection canonical graph contains invalid Unicode")
                if string_bytes > maximum_bytes:
                    _fail("value-projection canonical graph exceeds its string-byte bound")
                stack.append((child, depth + 1))
            continue
        _fail("value-projection canonical graph contains a foreign exact type")


def _canonical_json_bytes(value: object, *, maximum_bytes: int) -> bytes:
    _preflight_builtin_graph(value, maximum_bytes=maximum_bytes)
    try:
        encoded = json.dumps(
            value,
            allow_nan=False,
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        ).encode("utf-8", errors="strict")
    except (RecursionError, TypeError, UnicodeEncodeError, ValueError):
        _fail("value-projection value is not canonical JSON")
    if not encoded or len(encoded) > maximum_bytes:
        _fail("value-projection canonical JSON exceeds its byte bound")
    return encoded


def _sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _canonical_sha256(value: object, *, maximum_bytes: int = _MAX_RECEIPT_BYTES) -> str:
    return _sha256_bytes(_canonical_json_bytes(value, maximum_bytes=maximum_bytes))


def _preflight_json_bytes(value: bytes, *, maximum_bytes: int) -> None:
    if type(value) is not bytes or not value or len(value) > maximum_bytes:
        _fail("value-projection JSON bytes are empty, foreign, or over-bound")
    depth = 0
    nodes = 1
    in_string = False
    escaped = False
    string_bytes = 0
    for byte in value:
        if in_string:
            if escaped:
                escaped = False
                string_bytes += 1
            elif byte == 0x5C:
                escaped = True
                string_bytes += 1
            elif byte == 0x22:
                in_string = False
                if string_bytes > MAX_VALUE_PROJECTION_CANONICAL_VALUE_BYTES:
                    _fail("value-projection JSON contains an over-bound string")
                string_bytes = 0
            else:
                string_bytes += 1
            continue
        if byte == 0x22:
            in_string = True
        elif byte in (0x7B, 0x5B):
            depth += 1
            nodes += 1
        elif byte in (0x7D, 0x5D):
            depth -= 1
            if depth < 0:
                _fail("value-projection JSON has invalid structure")
        elif byte in (0x2C, 0x3A):
            nodes += 1
        if depth > MAX_VALUE_PROJECTION_JSON_DEPTH or nodes > MAX_VALUE_PROJECTION_JSON_NODES:
            _fail("value-projection JSON exceeds its structural bound")
    if in_string or escaped or depth != 0:
        _fail("value-projection JSON has invalid structure")


def _reject_duplicate_keys(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            _fail("value-projection JSON contains duplicate object keys")
        result[key] = value
    return result


def _bounded_json_integer(token: str) -> int:
    if len(token) > 20:
        _fail("value-projection JSON contains an over-bound integer token")
    value = int(token)
    if value < -_MAX_ORDINAL or value > _MAX_ORDINAL:
        _fail("value-projection JSON contains an over-bound integer")
    return value


def _bounded_json_number(token: str) -> float:
    if len(token.encode("ascii")) > _MAX_JSON_NUMBER_TOKEN_BYTES:
        _fail("value-projection JSON contains an over-bound number token")
    value = float(token)
    if not math.isfinite(value):
        _fail("value-projection JSON contains a nonfinite number")
    return value


def _reject_json_constant(_token: str) -> Never:
    _fail("value-projection JSON contains a nonfinite number")


def _decode_canonical_json(value: object, *, maximum_bytes: int) -> tuple[str, object]:
    if type(value) is not str:
        _fail("value-projection canonical JSON must be exact text")
    try:
        encoded = value.encode("utf-8", errors="strict")
    except UnicodeEncodeError:
        _fail("value-projection canonical JSON contains invalid Unicode")
    _preflight_json_bytes(encoded, maximum_bytes=maximum_bytes)
    try:
        decoded = json.loads(
            encoded,
            object_pairs_hook=_reject_duplicate_keys,
            parse_int=_bounded_json_integer,
            parse_float=_bounded_json_number,
            parse_constant=_reject_json_constant,
        )
    except ValueProjectionError:
        raise
    except (json.JSONDecodeError, RecursionError, TypeError, UnicodeDecodeError, ValueError):
        _fail("value-projection canonical JSON is invalid")
    if _canonical_json_bytes(decoded, maximum_bytes=maximum_bytes) != encoded:
        _fail("value-projection JSON is not in canonical byte form")
    return value, decoded


def _json_path_for_tokens(tokens: tuple[str | int, ...]) -> str:
    path = "$"
    for token in tokens:
        if type(token) is int:
            _exact_nonnegative(token, field_name="JSON-path array ordinal", maximum=_MAX_ORDINAL)
            path += f"[{token}]"
        elif type(token) is str:
            encoded = _canonical_json_bytes(
                token,
                maximum_bytes=MAX_VALUE_PROJECTION_PATH_BYTES,
            ).decode("utf-8")
            path += f"[{encoded}]"
        else:
            _fail("value-projection JSON path contains a foreign token")
        if len(path.encode("utf-8")) > MAX_VALUE_PROJECTION_PATH_BYTES:
            _fail("value-projection JSON path exceeds its UTF-8 byte bound")
    return path


def _canonical_json_path_tokens(value: object) -> tuple[str | int, ...]:
    path = _exact_text(
        value,
        field_name="value-projection JSON path",
        maximum_bytes=MAX_VALUE_PROJECTION_PATH_BYTES,
    )
    if not path.startswith("$"):
        _fail("value-projection JSON path lacks its exact root")
    tokens: list[str | int] = []
    cursor = 1
    decoder = json.JSONDecoder()
    while cursor < len(path):
        if path[cursor] != "[":
            _fail("value-projection JSON path has a noncanonical component")
        component_start = cursor + 1
        if component_start >= len(path):
            _fail("value-projection JSON path has an incomplete component")
        if path[component_start] == '"':
            try:
                token, component_end = decoder.raw_decode(path, component_start)
            except (json.JSONDecodeError, RecursionError, TypeError, ValueError):
                _fail("value-projection JSON path has an invalid object-key component")
            if type(token) is not str:
                _fail("value-projection JSON path object-key component is foreign")
            if component_end >= len(path) or path[component_end] != "]":
                _fail("value-projection JSON path has an unterminated object-key component")
            tokens.append(token)
            cursor = component_end + 1
            continue
        component_end = path.find("]", component_start)
        if component_end == -1:
            _fail("value-projection JSON path has an unterminated array component")
        raw_ordinal = path[component_start:component_end]
        if not raw_ordinal.isascii() or not raw_ordinal.isdigit():
            _fail("value-projection JSON path array component is invalid")
        if len(raw_ordinal) > 1 and raw_ordinal.startswith("0"):
            _fail("value-projection JSON path array component is noncanonical")
        ordinal = _exact_nonnegative(
            int(raw_ordinal),
            field_name="JSON-path array ordinal",
            maximum=_MAX_ORDINAL,
        )
        tokens.append(ordinal)
        cursor = component_end + 1
    exact_tokens = tuple(tokens)
    if _json_path_for_tokens(exact_tokens) != path:
        _fail("value-projection JSON path is not in canonical V1 form")
    return exact_tokens


def _json_path_child(
    parent_path: object,
    *,
    object_key: object = None,
    array_ordinal: object = None,
) -> str:
    parent_tokens = _canonical_json_path_tokens(parent_path)
    object_edge = object_key is not None
    array_edge = array_ordinal is not None
    if object_edge == array_edge:
        _fail("value-projection JSON child path has no exclusive edge")
    if object_edge:
        key = _exact_text(
            object_key,
            field_name="value-projection JSON object key",
            maximum_bytes=_MAX_METADATA_TEXT_BYTES,
            allow_empty=True,
        )
        return _json_path_for_tokens((*parent_tokens, key))
    ordinal = _exact_nonnegative(
        array_ordinal,
        field_name="value-projection JSON array ordinal",
        maximum=_MAX_ORDINAL,
    )
    return _json_path_for_tokens((*parent_tokens, ordinal))


def _value_kind(value: object) -> ValueProjectionValueKindV1:
    if value is None:
        return "null"
    if type(value) is bool:
        return "boolean"
    if type(value) is int:
        return "integer"
    if type(value) is float:
        return "number"
    if type(value) is str:
        return "string"
    if type(value) is list:
        return "array"
    if type(value) is dict:
        return "object"
    _fail("value-projection runtime value has a foreign exact type")


def _presence_kind(value: object) -> ValueProjectionPresenceKindV1:
    if value is None:
        return "null"
    if type(value) is dict and not value:
        return "empty_object"
    if type(value) is list and not value:
        return "empty_array"
    return "present"


def _length_framed_root(
    *,
    kind: str,
    raw_authority_bundle_sha256: str,
    item_sha256s: tuple[str, ...],
    maximum: int,
) -> str:
    _exact_text(kind, field_name="ordered-root kind", maximum_bytes=256)
    _exact_sha256(raw_authority_bundle_sha256, field_name="ordered-root raw bundle")
    if type(item_sha256s) is not tuple or len(item_sha256s) > maximum:
        _fail("value-projection ordered root has a foreign or over-bound inventory")
    digest = hashlib.sha256()
    digest.update(b"nbadb-value-projection-length-framed-root-v1\x00")

    def feed(value: bytes) -> None:
        digest.update(len(value).to_bytes(8, byteorder="big", signed=False))
        digest.update(value)

    feed(str(BODY_VALUE_PROJECTION_SCHEMA_VERSION).encode("ascii"))
    feed(kind.encode("utf-8"))
    feed(raw_authority_bundle_sha256.encode("ascii"))
    feed(str(len(item_sha256s)).encode("ascii"))
    for ordinal, item_sha256 in enumerate(item_sha256s):
        _exact_sha256(item_sha256, field_name="ordered-root item")
        feed(str(ordinal).encode("ascii"))
        feed(item_sha256.encode("ascii"))
    return digest.hexdigest()


def _public_expected_unit_root(
    *,
    raw_authority_bundle_sha256: str,
    unit_sha256s: tuple[str, ...],
) -> str:
    """Reproduce the public-value kernel root without importing that kernel."""

    digest = hashlib.sha256()
    digest.update(b'{"count":')
    digest.update(str(len(unit_sha256s)).encode("ascii"))
    digest.update(b',"items":[')
    for ordinal, unit_sha256 in enumerate(unit_sha256s):
        _exact_sha256(unit_sha256, field_name="expected-unit identity")
        if ordinal:
            digest.update(b",")
        digest.update(_canonical_json_bytes(unit_sha256, maximum_bytes=256))
    digest.update(b'],"kind":')
    digest.update(_canonical_json_bytes(_PUBLIC_UNIT_ROOT_KIND, maximum_bytes=256))
    digest.update(b',"raw_authority_bundle_sha256":')
    digest.update(_canonical_json_bytes(raw_authority_bundle_sha256, maximum_bytes=256))
    digest.update(b',"schema_version":1}')
    return digest.hexdigest()


def _ownership_assignment_root(assignment_sha256s: tuple[str, ...]) -> str:
    """Reproduce the ownership receipt assignment root without importing it."""

    if (
        type(assignment_sha256s) is not tuple
        or len(assignment_sha256s) > MAX_VALUE_PROJECTION_OBSERVATIONS
    ):
        _fail("representation-assignment inventory is foreign or over-bound")
    return _legacy_ordered_root(
        kind=_OWNERSHIP_ASSIGNMENT_ROOT_KIND,
        item_sha256s=assignment_sha256s,
    )


def _legacy_ordered_root(*, kind: str, item_sha256s: tuple[str, ...]) -> str:
    digest = hashlib.sha256()
    digest.update(b'{"count":')
    digest.update(str(len(item_sha256s)).encode("ascii"))
    digest.update(b',"items":[')
    for ordinal, item_sha256 in enumerate(item_sha256s):
        _exact_sha256(item_sha256, field_name="legacy ordered-root item")
        if ordinal:
            digest.update(b",")
        digest.update(_canonical_json_bytes(item_sha256, maximum_bytes=256))
    digest.update(b'],"kind":')
    digest.update(_canonical_json_bytes(kind, maximum_bytes=256))
    digest.update(b',"schema_version":1}')
    return digest.hexdigest()


@dataclass(frozen=True, slots=True)
class _SemanticAuthorityV1:
    ownership_receipt: dict[str, object]
    expected_units: tuple[dict[str, object], ...]
    assignments: tuple[dict[str, object], ...]
    observations: tuple[dict[str, object], ...]
    partitions: tuple[dict[str, object], ...]
    bindings: tuple[dict[str, object], ...]


def _strict_semantic_row(
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
        or row["schema_version"] != BODY_VALUE_PROJECTION_SCHEMA_VERSION
    ):
        _fail(f"{label} schema version is invalid")
    return {field_name: row[field_name] for field_name in expected_fields}


def _semantic_identity_sha256(
    row: dict[str, object],
    *,
    kind: str,
    digest_field: str,
) -> str:
    return _canonical_sha256(
        {
            "schema_version": BODY_VALUE_PROJECTION_SCHEMA_VERSION,
            "kind": kind,
            **{
                field_name: value
                for field_name, value in row.items()
                if field_name not in {"schema_version", digest_field}
            },
        },
        maximum_bytes=64 * 1024,
    )


def _exact_semantic_inventory(
    value: object,
    *,
    maximum: int,
    label: str,
) -> tuple[object, ...]:
    if type(value) is not tuple or len(value) > maximum:
        _fail(f"{label} is foreign or over-bound")
    return value


def _decode_expected_units(
    *,
    raw_authority_bundle_sha256: str,
    rows: object,
) -> tuple[tuple[dict[str, object], ...], str, str]:
    values = _exact_semantic_inventory(
        rows,
        maximum=MAX_VALUE_PROJECTION_OBSERVATIONS,
        label="value-projection expected-unit semantic inventory",
    )
    decoded: list[dict[str, object]] = []
    seen_unit_sha256s: set[str] = set()
    seen_observation_sha256s: set[str] = set()
    seen_occurrence_sha256s: set[tuple[str, str]] = set()
    active_observation_sha256: str | None = None
    active_observation_ordinal = -1
    expected_occurrence_ordinal = 0
    response_seen = False
    for unit_ordinal, value in enumerate(values):
        row = _strict_semantic_row(
            value,
            expected_fields=_PUBLIC_UNIT_ROW_FIELDS,
            label="value-projection expected-unit semantic row",
        )
        unit_sha256 = _exact_sha256(row["unit_sha256"], field_name="expected-unit identity")
        bundle_sha256 = _exact_sha256(
            row["raw_authority_bundle_sha256"],
            field_name="expected-unit raw bundle",
        )
        declared_unit_ordinal = _exact_nonnegative(
            row["unit_ordinal"],
            field_name="expected-unit ordinal",
            maximum=MAX_VALUE_PROJECTION_OBSERVATIONS - 1,
        )
        observation_sha256 = _exact_sha256(
            row["observation_sha256"],
            field_name="expected-unit observation",
        )
        observation_ordinal = _exact_nonnegative(
            row["observation_ordinal"],
            field_name="expected-unit observation ordinal",
            maximum=MAX_VALUE_PROJECTION_OBSERVATIONS - 1,
        )
        unit_kind = row["unit_kind"]
        if type(unit_kind) is not str or unit_kind not in _UNIT_KINDS:
            _fail("expected-unit semantic kind is outside its closed V1 domain")
        occurrence_sha256 = _optional_sha256(
            row["occurrence_sha256"],
            field_name="expected-unit occurrence",
        )
        occurrence_ordinal = _optional_nonnegative(
            row["occurrence_ordinal"],
            field_name="expected-unit occurrence ordinal",
            maximum=MAX_VALUE_PROJECTION_OBSERVATIONS - 1,
        )
        if (
            bundle_sha256 != raw_authority_bundle_sha256
            or declared_unit_ordinal != unit_ordinal
            or unit_sha256 in seen_unit_sha256s
        ):
            _fail("expected-unit semantic inventory is foreign, duplicate, or reordered")
        if unit_sha256 != _semantic_identity_sha256(
            row,
            kind=_PUBLIC_UNIT_KIND,
            digest_field="unit_sha256",
        ):
            _fail("expected-unit semantic digest differs from its exact identity")
        seen_unit_sha256s.add(unit_sha256)
        if observation_sha256 != active_observation_sha256:
            if observation_sha256 in seen_observation_sha256s:
                _fail("expected-unit semantic inventory reopens a completed observation")
            seen_observation_sha256s.add(observation_sha256)
            active_observation_sha256 = observation_sha256
            active_observation_ordinal += 1
            expected_occurrence_ordinal = 0
            response_seen = False
        if observation_ordinal != active_observation_ordinal:
            _fail("expected-unit semantic observation order is not contiguous")
        if unit_kind == "result_occurrence":
            if (
                response_seen
                or occurrence_sha256 is None
                or occurrence_ordinal != expected_occurrence_ordinal
            ):
                _fail("expected-unit semantic occurrence order or shape is invalid")
            occurrence_identity = (observation_sha256, occurrence_sha256)
            if occurrence_identity in seen_occurrence_sha256s:
                _fail("expected-unit semantic inventory repeats one occurrence")
            seen_occurrence_sha256s.add(occurrence_identity)
            expected_occurrence_ordinal += 1
        else:
            if occurrence_sha256 is not None or occurrence_ordinal is not None or response_seen:
                _fail("expected-unit semantic response shape is invalid")
            if unit_kind == "response_fixed_zero" and expected_occurrence_ordinal != 0:
                _fail("fixed-zero semantic unit cannot follow a result occurrence")
            response_seen = True
        decoded.append(row)
    exact = tuple(decoded)
    unit_root_sha256 = _public_expected_unit_root(
        raw_authority_bundle_sha256=raw_authority_bundle_sha256,
        unit_sha256s=tuple(cast("str", row["unit_sha256"]) for row in exact),
    )
    inventory_sha256 = _canonical_sha256(
        {
            "kind": _PUBLIC_UNIT_INVENTORY_KIND,
            "schema_version": BODY_VALUE_PROJECTION_SCHEMA_VERSION,
            "raw_authority_bundle_sha256": raw_authority_bundle_sha256,
            "unit_count": len(exact),
            "unit_root_sha256": unit_root_sha256,
            "units": [dict(row) for row in exact],
        },
        maximum_bytes=_MAX_SEMANTIC_INVENTORY_BYTES,
    )
    return exact, inventory_sha256, unit_root_sha256


def _decode_assignments(
    *,
    raw_authority_bundle_sha256: str,
    rows: object,
    expected_units: tuple[dict[str, object], ...],
) -> tuple[tuple[dict[str, object], ...], str]:
    values = _exact_semantic_inventory(
        rows,
        maximum=MAX_VALUE_PROJECTION_OBSERVATIONS,
        label="value-projection assignment semantic inventory",
    )
    if len(values) != len(expected_units):
        _fail("value-projection semantic unit and assignment denominators differ")
    decoded: list[dict[str, object]] = []
    seen_assignment_sha256s: set[str] = set()
    for unit_ordinal, (value, unit) in enumerate(zip(values, expected_units, strict=True)):
        row = _strict_semantic_row(
            value,
            expected_fields=_PUBLIC_ASSIGNMENT_ROW_FIELDS,
            label="value-projection assignment semantic row",
        )
        assignment_sha256 = _exact_sha256(
            row["assignment_sha256"],
            field_name="representation assignment identity",
        )
        bundle_sha256 = _exact_sha256(
            row["raw_authority_bundle_sha256"],
            field_name="representation assignment raw bundle",
        )
        unit_sha256 = _exact_sha256(
            row["unit_sha256"],
            field_name="representation assignment unit",
        )
        declared_unit_ordinal = _exact_nonnegative(
            row["unit_ordinal"],
            field_name="representation assignment unit ordinal",
            maximum=MAX_VALUE_PROJECTION_OBSERVATIONS - 1,
        )
        source_input_kind = row["source_input_kind"]
        representation_kind = row["representation_kind"]
        if type(source_input_kind) is not str or source_input_kind not in _SOURCE_INPUT_KINDS:
            _fail("representation assignment source input is outside its closed V1 domain")
        if type(representation_kind) is not str or representation_kind not in _REPRESENTATION_KINDS:
            _fail("representation assignment kind is outside its closed V1 domain")
        unit_kind = unit["unit_kind"]
        if unit_kind == "result_occurrence":
            compatible = representation_kind in _RESULT_REPRESENTATIONS
        elif unit_kind == "response_residual":
            compatible = representation_kind == "response_lossless_records_v1"
        else:
            compatible = representation_kind == "response_fixed_zero_v1"
        if (
            bundle_sha256 != raw_authority_bundle_sha256
            or declared_unit_ordinal != unit_ordinal
            or unit_sha256 != unit["unit_sha256"]
            or assignment_sha256 in seen_assignment_sha256s
            or not compatible
        ):
            _fail("representation assignment is duplicate or foreign to its exact unit")
        if assignment_sha256 != _semantic_identity_sha256(
            row,
            kind=_PUBLIC_ASSIGNMENT_KIND,
            digest_field="assignment_sha256",
        ):
            _fail("representation assignment digest differs from its exact identity")
        seen_assignment_sha256s.add(assignment_sha256)
        decoded.append(row)
    exact = tuple(decoded)
    return exact, _legacy_ordered_root(
        kind=_OWNERSHIP_ASSIGNMENT_ROOT_KIND,
        item_sha256s=tuple(cast("str", row["assignment_sha256"]) for row in exact),
    )


def _decode_ownership_observations(
    *,
    raw_authority_bundle_sha256: str,
    rows: object,
) -> tuple[dict[str, object], ...]:
    values = _exact_semantic_inventory(
        rows,
        maximum=MAX_VALUE_PROJECTION_OBSERVATIONS,
        label="value-projection ownership observation semantic inventory",
    )
    decoded: list[dict[str, object]] = []
    seen_observation_sha256s: set[str] = set()
    seen_observation_record_sha256s: set[str] = set()
    for observation_ordinal, value in enumerate(values):
        row = _strict_semantic_row(
            value,
            expected_fields=_OWNERSHIP_OBSERVATION_ROW_FIELDS,
            label="value-projection ownership observation semantic row",
        )
        for field_name in (
            "observation_ownership_sha256",
            "raw_authority_bundle_sha256",
            "observation_record_sha256",
            "observation_sha256",
            "partition_root_sha256",
            "record_root_sha256",
            "binding_root_sha256",
        ):
            _exact_sha256(row[field_name], field_name=field_name)
        declared_ordinal = _exact_nonnegative(
            row["observation_ordinal"],
            field_name="ownership observation ordinal",
            maximum=MAX_VALUE_PROJECTION_OBSERVATIONS - 1,
        )
        for field_name, maximum in (
            ("first_partition_ordinal", MAX_VALUE_PROJECTION_PARTITIONS - 1),
            ("partition_count", MAX_VALUE_PROJECTION_PARTITIONS),
            ("result_occurrence_partition_count", MAX_VALUE_PROJECTION_OBSERVATIONS),
            ("zero_result_occurrence_partition_count", MAX_VALUE_PROJECTION_OBSERVATIONS),
            ("result_occurrence_record_count", MAX_VALUE_PROJECTION_ITEMS),
            ("response_record_count", MAX_VALUE_PROJECTION_ITEMS),
            ("record_count", MAX_VALUE_PROJECTION_ITEMS),
            ("binding_count", MAX_VALUE_PROJECTION_ITEMS),
        ):
            _exact_nonnegative(row[field_name], field_name=field_name, maximum=maximum)
        source_input_kind = row["source_input_kind"]
        response_partition_kind = row["response_partition_kind"]
        if type(source_input_kind) is not str or source_input_kind not in _SOURCE_INPUT_KINDS:
            _fail("ownership observation source input is outside its closed V1 domain")
        if type(response_partition_kind) is not str or response_partition_kind not in {
            "response_residual",
            "response_fixed_zero",
        }:
            _fail("ownership observation response kind is outside its closed V1 domain")
        fixed_zero_landing_sha256 = _optional_sha256(
            row["fixed_zero_landing_sha256"],
            field_name="ownership observation fixed-zero landing",
        )
        occurrence_count = cast("int", row["result_occurrence_partition_count"])
        zero_occurrence_count = cast("int", row["zero_result_occurrence_partition_count"])
        occurrence_record_count = cast("int", row["result_occurrence_record_count"])
        response_record_count = cast("int", row["response_record_count"])
        record_count = cast("int", row["record_count"])
        if (
            row["raw_authority_bundle_sha256"] != raw_authority_bundle_sha256
            or declared_ordinal != observation_ordinal
            or row["partition_count"] != occurrence_count + 1
            or zero_occurrence_count > occurrence_count
            or record_count != occurrence_record_count + response_record_count
            or row["binding_count"] != record_count
            or occurrence_record_count < occurrence_count - zero_occurrence_count
        ):
            _fail("ownership observation aggregate shape is inconsistent")
        observation_sha256 = cast("str", row["observation_sha256"])
        observation_record_sha256 = cast("str", row["observation_record_sha256"])
        if (
            observation_sha256 in seen_observation_sha256s
            or observation_record_sha256 in seen_observation_record_sha256s
        ):
            _fail("ownership observation semantic inventory contains a duplicate identity")
        seen_observation_sha256s.add(observation_sha256)
        seen_observation_record_sha256s.add(observation_record_sha256)
        if response_partition_kind == "response_fixed_zero":
            if (
                occurrence_count != 0
                or zero_occurrence_count != 0
                or occurrence_record_count != 0
                or response_record_count != 0
                or record_count != 0
                or fixed_zero_landing_sha256 is None
            ):
                _fail("fixed-zero ownership observation contradicts its empty algebra")
        elif fixed_zero_landing_sha256 is not None:
            _fail("response-residual ownership observation fabricates a fixed-zero landing")
        elif occurrence_count == 0 and response_record_count == 0:
            _fail("empty ownership observation lacks its mandatory fixed-zero partition")
        if row["observation_ownership_sha256"] != _semantic_identity_sha256(
            row,
            kind=_OWNERSHIP_OBSERVATION_KIND,
            digest_field="observation_ownership_sha256",
        ):
            _fail("ownership observation digest differs from its exact identity")
        decoded.append(row)
    return tuple(decoded)


def _decode_ownership_partitions(
    *,
    raw_authority_bundle_sha256: str,
    rows: object,
    expected_units: tuple[dict[str, object], ...],
    assignments: tuple[dict[str, object], ...],
    observations: tuple[dict[str, object], ...],
) -> tuple[dict[str, object], ...]:
    values = _exact_semantic_inventory(
        rows,
        maximum=MAX_VALUE_PROJECTION_PARTITIONS,
        label="value-projection ownership partition semantic inventory",
    )
    decoded: list[dict[str, object]] = []
    used_unit_ordinals: set[int] = set()
    next_observation_partition_ordinal: dict[int, int] = {}
    for partition_ordinal, value in enumerate(values):
        row = _strict_semantic_row(
            value,
            expected_fields=_OWNERSHIP_PARTITION_ROW_FIELDS,
            label="value-projection ownership partition semantic row",
        )
        for field_name in (
            "partition_sha256",
            "raw_authority_bundle_sha256",
            "observation_record_sha256",
            "observation_sha256",
            "record_root_sha256",
            "binding_root_sha256",
        ):
            _exact_sha256(row[field_name], field_name=field_name)
        observation_ordinal = _exact_nonnegative(
            row["observation_ordinal"],
            field_name="ownership partition observation ordinal",
            maximum=MAX_VALUE_PROJECTION_OBSERVATIONS - 1,
        )
        declared_partition_ordinal = _exact_nonnegative(
            row["partition_ordinal"],
            field_name="ownership partition ordinal",
            maximum=MAX_VALUE_PROJECTION_PARTITIONS - 1,
        )
        observation_partition_ordinal = _exact_nonnegative(
            row["observation_partition_ordinal"],
            field_name="ownership observation partition ordinal",
            maximum=MAX_VALUE_PROJECTION_PARTITIONS - 1,
        )
        record_count = _exact_nonnegative(
            row["record_count"],
            field_name="ownership partition record count",
            maximum=MAX_VALUE_PROJECTION_ITEMS,
        )
        partition_kind = row["partition_kind"]
        if type(partition_kind) is not str or partition_kind not in _UNIT_KINDS:
            _fail("ownership partition kind is outside its closed V1 domain")
        occurrence_sha256 = _optional_sha256(
            row["occurrence_sha256"],
            field_name="ownership partition occurrence",
        )
        occurrence_ordinal = _optional_nonnegative(
            row["occurrence_ordinal"],
            field_name="ownership partition occurrence ordinal",
            maximum=MAX_VALUE_PROJECTION_OBSERVATIONS - 1,
        )
        unit_sha256 = _optional_sha256(
            row["unit_sha256"],
            field_name="ownership partition unit",
        )
        unit_ordinal = _optional_nonnegative(
            row["unit_ordinal"],
            field_name="ownership partition unit ordinal",
            maximum=MAX_VALUE_PROJECTION_OBSERVATIONS - 1,
        )
        assignment_sha256 = _optional_sha256(
            row["assignment_sha256"],
            field_name="ownership partition assignment",
        )
        fixed_zero_landing_sha256 = _optional_sha256(
            row["fixed_zero_landing_sha256"],
            field_name="ownership partition fixed-zero landing",
        )
        if (
            row["raw_authority_bundle_sha256"] != raw_authority_bundle_sha256
            or declared_partition_ordinal != partition_ordinal
            or observation_ordinal >= len(observations)
        ):
            _fail("ownership partition is foreign or reordered")
        observation = observations[observation_ordinal]
        if (
            row["observation_record_sha256"] != observation["observation_record_sha256"]
            or row["observation_sha256"] != observation["observation_sha256"]
            or observation_partition_ordinal
            != next_observation_partition_ordinal.get(observation_ordinal, 0)
        ):
            _fail("ownership partition references a foreign observation or order")
        next_observation_partition_ordinal[observation_ordinal] = observation_partition_ordinal + 1
        unit_present = (
            unit_sha256 is not None and unit_ordinal is not None and assignment_sha256 is not None
        )
        unit_absent = unit_sha256 is None and unit_ordinal is None and assignment_sha256 is None
        if not unit_present and not unit_absent:
            _fail("ownership partition has a partial semantic unit binding")
        if partition_kind == "result_occurrence":
            valid_shape = (
                occurrence_sha256 is not None
                and occurrence_ordinal is not None
                and unit_present
                and fixed_zero_landing_sha256 is None
            )
        elif partition_kind == "response_residual":
            valid_shape = (
                occurrence_sha256 is None
                and occurrence_ordinal is None
                and fixed_zero_landing_sha256 is None
                and ((record_count > 0 and unit_present) or (record_count == 0 and unit_absent))
            )
        else:
            valid_shape = (
                occurrence_sha256 is None
                and occurrence_ordinal is None
                and unit_present
                and record_count == 0
                and fixed_zero_landing_sha256 is not None
            )
        if not valid_shape:
            _fail("ownership partition semantic zero/unit shape is invalid")
        if unit_ordinal is not None:
            if unit_ordinal >= len(expected_units) or unit_ordinal in used_unit_ordinals:
                _fail("ownership partition repeats or references a foreign unit")
            unit = expected_units[unit_ordinal]
            assignment = assignments[unit_ordinal]
            if (
                unit_sha256 != unit["unit_sha256"]
                or assignment_sha256 != assignment["assignment_sha256"]
                or partition_kind != unit["unit_kind"]
                or observation_ordinal != unit["observation_ordinal"]
                or row["observation_sha256"] != unit["observation_sha256"]
                or occurrence_sha256 != unit["occurrence_sha256"]
                or occurrence_ordinal != unit["occurrence_ordinal"]
                or assignment["source_input_kind"] != observation["source_input_kind"]
            ):
                _fail("ownership partition semantic unit join is inconsistent")
            used_unit_ordinals.add(unit_ordinal)
        empty_record_root = _legacy_ordered_root(
            kind=_OWNERSHIP_PARTITION_RECORD_ROOT_KIND,
            item_sha256s=(),
        )
        empty_binding_root = _legacy_ordered_root(
            kind=_OWNERSHIP_PARTITION_BINDING_ROOT_KIND,
            item_sha256s=(),
        )
        if (record_count == 0) != (row["record_root_sha256"] == empty_record_root) or (
            record_count == 0
        ) != (row["binding_root_sha256"] == empty_binding_root):
            _fail("ownership partition semantic zero roots are inconsistent")
        if row["partition_sha256"] != _semantic_identity_sha256(
            row,
            kind=_OWNERSHIP_PARTITION_KIND,
            digest_field="partition_sha256",
        ):
            _fail("ownership partition semantic digest differs from its exact identity")
        decoded.append(row)
    if used_unit_ordinals != set(range(len(expected_units))):
        _fail("ownership partition semantic inventory leaves an expected unit orphaned")
    return tuple(decoded)


def _decode_ownership_bindings(
    *,
    raw_authority_bundle_sha256: str,
    rows: object,
    expected_units: tuple[dict[str, object], ...],
    assignments: tuple[dict[str, object], ...],
    observations: tuple[dict[str, object], ...],
    partitions: tuple[dict[str, object], ...],
) -> tuple[dict[str, object], ...]:
    values = _exact_semantic_inventory(
        rows,
        maximum=MAX_VALUE_PROJECTION_ITEMS,
        label="value-projection ownership binding semantic inventory",
    )
    decoded: list[dict[str, object]] = []
    seen_binding_sha256s: set[str] = set()
    seen_source_record_sha256s: set[str] = set()
    next_observation_record_ordinal: dict[int, int] = {}
    last_observation_ordinal = -1
    for binding_ordinal, value in enumerate(values):
        row = _strict_semantic_row(
            value,
            expected_fields=_OWNERSHIP_BINDING_ROW_FIELDS,
            label="value-projection ownership binding semantic row",
        )
        for field_name in (
            "binding_sha256",
            "raw_authority_bundle_sha256",
            "observation_record_sha256",
            "observation_sha256",
            "source_record_sha256",
            "unit_sha256",
            "assignment_sha256",
        ):
            _exact_sha256(row[field_name], field_name=field_name)
        observation_ordinal = _exact_nonnegative(
            row["observation_ordinal"],
            field_name="ownership binding observation ordinal",
            maximum=MAX_VALUE_PROJECTION_OBSERVATIONS - 1,
        )
        declared_binding_ordinal = _exact_nonnegative(
            row["binding_ordinal"],
            field_name="ownership binding ordinal",
            maximum=MAX_VALUE_PROJECTION_ITEMS - 1,
        )
        observation_record_ordinal = _exact_nonnegative(
            row["observation_record_ordinal"],
            field_name="ownership binding observation record ordinal",
            maximum=MAX_VALUE_PROJECTION_ITEMS - 1,
        )
        partition_ordinal = _exact_nonnegative(
            row["partition_ordinal"],
            field_name="ownership binding partition ordinal",
            maximum=MAX_VALUE_PROJECTION_PARTITIONS - 1,
        )
        unit_ordinal = _exact_nonnegative(
            row["unit_ordinal"],
            field_name="ownership binding unit ordinal",
            maximum=MAX_VALUE_PROJECTION_OBSERVATIONS - 1,
        )
        ownership_kind = row["ownership_kind"]
        if type(ownership_kind) is not str or ownership_kind not in {
            "result_occurrence",
            "response_residual",
        }:
            _fail("ownership binding kind is outside its closed V1 domain")
        occurrence_sha256 = _optional_sha256(
            row["occurrence_sha256"],
            field_name="ownership binding occurrence",
        )
        occurrence_ordinal = _optional_nonnegative(
            row["occurrence_ordinal"],
            field_name="ownership binding occurrence ordinal",
            maximum=MAX_VALUE_PROJECTION_OBSERVATIONS - 1,
        )
        if ownership_kind == "result_occurrence":
            if occurrence_sha256 is None or occurrence_ordinal is None:
                _fail("result ownership binding omits occurrence identity")
        elif occurrence_sha256 is not None or occurrence_ordinal is not None:
            _fail("response ownership binding fabricates occurrence identity")
        if (
            row["raw_authority_bundle_sha256"] != raw_authority_bundle_sha256
            or declared_binding_ordinal != binding_ordinal
            or observation_ordinal >= len(observations)
            or partition_ordinal >= len(partitions)
            or unit_ordinal >= len(expected_units)
            or observation_ordinal < last_observation_ordinal
        ):
            _fail("ownership binding semantic inventory is foreign or reordered")
        last_observation_ordinal = observation_ordinal
        observation = observations[observation_ordinal]
        partition = partitions[partition_ordinal]
        unit = expected_units[unit_ordinal]
        assignment = assignments[unit_ordinal]
        expected_observation_record_ordinal = next_observation_record_ordinal.get(
            observation_ordinal,
            0,
        )
        if observation_record_ordinal != expected_observation_record_ordinal:
            _fail("ownership binding observation record order is not contiguous")
        next_observation_record_ordinal[observation_ordinal] = observation_record_ordinal + 1
        binding_sha256 = cast("str", row["binding_sha256"])
        source_record_sha256 = cast("str", row["source_record_sha256"])
        if (
            binding_sha256 in seen_binding_sha256s
            or source_record_sha256 in seen_source_record_sha256s
        ):
            _fail("ownership binding semantic inventory dual-assigns a source record")
        seen_binding_sha256s.add(binding_sha256)
        seen_source_record_sha256s.add(source_record_sha256)
        if (
            row["observation_record_sha256"] != observation["observation_record_sha256"]
            or row["observation_sha256"] != observation["observation_sha256"]
            or partition["observation_ordinal"] != observation_ordinal
            or row["unit_sha256"] != unit["unit_sha256"]
            or row["assignment_sha256"] != assignment["assignment_sha256"]
            or ownership_kind != unit["unit_kind"]
            or occurrence_sha256 != unit["occurrence_sha256"]
            or occurrence_ordinal != unit["occurrence_ordinal"]
            or row["unit_sha256"] != partition["unit_sha256"]
            or unit_ordinal != partition["unit_ordinal"]
            or row["assignment_sha256"] != partition["assignment_sha256"]
            or ownership_kind != partition["partition_kind"]
            or occurrence_sha256 != partition["occurrence_sha256"]
            or occurrence_ordinal != partition["occurrence_ordinal"]
        ):
            _fail("ownership binding semantic join is inconsistent")
        if binding_sha256 != _semantic_identity_sha256(
            row,
            kind=_OWNERSHIP_BINDING_KIND,
            digest_field="binding_sha256",
        ):
            _fail("ownership binding semantic digest differs from its exact identity")
        decoded.append(row)
    return tuple(decoded)


def _validate_ownership_children(
    *,
    observations: tuple[dict[str, object], ...],
    partitions: tuple[dict[str, object], ...],
    bindings: tuple[dict[str, object], ...],
) -> None:
    partition_groups: list[list[dict[str, object]]] = [[] for _ in observations]
    binding_observation_groups: list[list[dict[str, object]]] = [[] for _ in observations]
    binding_partition_groups: list[list[dict[str, object]]] = [[] for _ in partitions]
    for partition in partitions:
        partition_groups[cast("int", partition["observation_ordinal"])].append(partition)
    for binding in bindings:
        observation_ordinal = cast("int", binding["observation_ordinal"])
        partition_ordinal = cast("int", binding["partition_ordinal"])
        binding_observation_groups[observation_ordinal].append(binding)
        binding_partition_groups[partition_ordinal].append(binding)
    for partition_ordinal, partition in enumerate(partitions):
        owned = binding_partition_groups[partition_ordinal]
        expected_record_root = _legacy_ordered_root(
            kind=_OWNERSHIP_PARTITION_RECORD_ROOT_KIND,
            item_sha256s=tuple(cast("str", row["source_record_sha256"]) for row in owned),
        )
        expected_binding_root = _legacy_ordered_root(
            kind=_OWNERSHIP_PARTITION_BINDING_ROOT_KIND,
            item_sha256s=tuple(cast("str", row["binding_sha256"]) for row in owned),
        )
        if (
            partition["record_count"] != len(owned)
            or partition["record_root_sha256"] != expected_record_root
            or partition["binding_root_sha256"] != expected_binding_root
        ):
            _fail("ownership partition semantic roots differ from its exact bindings")
    for observation_ordinal, observation in enumerate(observations):
        owned_partitions = partition_groups[observation_ordinal]
        owned_bindings = binding_observation_groups[observation_ordinal]
        if not owned_partitions:
            _fail("ownership observation semantic row has no partition")
        first_partition_ordinal = cast("int", owned_partitions[0]["partition_ordinal"])
        if any(
            partition["partition_ordinal"] != first_partition_ordinal + local_ordinal
            or partition["observation_partition_ordinal"] != local_ordinal
            for local_ordinal, partition in enumerate(owned_partitions)
        ):
            _fail("ownership observation semantic partition order is not contiguous")
        occurrence_partitions = owned_partitions[:-1]
        response_partition = owned_partitions[-1]
        if any(
            partition["partition_kind"] != "result_occurrence"
            or partition["occurrence_ordinal"] != occurrence_ordinal
            for occurrence_ordinal, partition in enumerate(occurrence_partitions)
        ) or response_partition["partition_kind"] not in {
            "response_residual",
            "response_fixed_zero",
        }:
            _fail("ownership observation semantic partition kinds are reordered")
        result_record_count = sum(
            cast("int", partition["record_count"]) for partition in occurrence_partitions
        )
        response_record_count = cast("int", response_partition["record_count"])
        expected = {
            "first_partition_ordinal": first_partition_ordinal,
            "partition_count": len(owned_partitions),
            "partition_root_sha256": _legacy_ordered_root(
                kind=_OWNERSHIP_OBSERVATION_PARTITION_ROOT_KIND,
                item_sha256s=tuple(
                    cast("str", partition["partition_sha256"]) for partition in owned_partitions
                ),
            ),
            "result_occurrence_partition_count": len(occurrence_partitions),
            "zero_result_occurrence_partition_count": sum(
                partition["record_count"] == 0 for partition in occurrence_partitions
            ),
            "result_occurrence_record_count": result_record_count,
            "response_partition_kind": response_partition["partition_kind"],
            "response_record_count": response_record_count,
            "fixed_zero_landing_sha256": response_partition["fixed_zero_landing_sha256"],
            "record_count": len(owned_bindings),
            "record_root_sha256": _legacy_ordered_root(
                kind=_OWNERSHIP_OBSERVATION_RECORD_ROOT_KIND,
                item_sha256s=tuple(
                    cast("str", binding["source_record_sha256"]) for binding in owned_bindings
                ),
            ),
            "binding_count": len(owned_bindings),
            "binding_root_sha256": _legacy_ordered_root(
                kind=_OWNERSHIP_OBSERVATION_BINDING_ROOT_KIND,
                item_sha256s=tuple(
                    cast("str", binding["binding_sha256"]) for binding in owned_bindings
                ),
            ),
        }
        if any(observation[field_name] != value for field_name, value in expected.items()):
            _fail("ownership observation semantic row differs from its exact children")


def _decode_ownership_receipt(
    *,
    raw_authority_bundle_sha256: str,
    value: object,
    expected_unit_inventory_sha256: str,
    expected_unit_root_sha256: str,
    representation_assignment_root_sha256: str,
    expected_units: tuple[dict[str, object], ...],
    assignments: tuple[dict[str, object], ...],
    observations: tuple[dict[str, object], ...],
    partitions: tuple[dict[str, object], ...],
    bindings: tuple[dict[str, object], ...],
) -> dict[str, object]:
    row = _strict_semantic_row(
        value,
        expected_fields=_OWNERSHIP_RECEIPT_ROW_FIELDS,
        label="value-projection ownership receipt semantic row",
    )
    for field_name in (
        "receipt_sha256",
        "raw_authority_bundle_sha256",
        "expected_unit_inventory_sha256",
        "expected_unit_root_sha256",
        "representation_assignment_root_sha256",
        "observation_root_sha256",
        "partition_root_sha256",
        "fixed_zero_landing_root_sha256",
        "binding_root_sha256",
        "source_record_root_sha256",
    ):
        _exact_sha256(row[field_name], field_name=field_name)
    for field_name, maximum in (
        ("expected_unit_count", MAX_VALUE_PROJECTION_OBSERVATIONS),
        ("representation_assignment_count", MAX_VALUE_PROJECTION_OBSERVATIONS),
        ("observation_count", MAX_VALUE_PROJECTION_OBSERVATIONS),
        ("partition_count", MAX_VALUE_PROJECTION_PARTITIONS),
        ("result_occurrence_partition_count", MAX_VALUE_PROJECTION_OBSERVATIONS),
        ("zero_result_occurrence_partition_count", MAX_VALUE_PROJECTION_OBSERVATIONS),
        ("result_occurrence_record_count", MAX_VALUE_PROJECTION_ITEMS),
        ("response_residual_partition_count", MAX_VALUE_PROJECTION_OBSERVATIONS),
        ("positive_response_residual_partition_count", MAX_VALUE_PROJECTION_OBSERVATIONS),
        ("zero_response_residual_partition_count", MAX_VALUE_PROJECTION_OBSERVATIONS),
        ("response_residual_record_count", MAX_VALUE_PROJECTION_ITEMS),
        ("response_fixed_zero_partition_count", MAX_VALUE_PROJECTION_OBSERVATIONS),
        ("binding_count", MAX_VALUE_PROJECTION_ITEMS),
        ("source_record_count", MAX_VALUE_PROJECTION_ITEMS),
    ):
        _exact_nonnegative(row[field_name], field_name=field_name, maximum=maximum)
    occurrence_partitions = tuple(
        partition for partition in partitions if partition["partition_kind"] == "result_occurrence"
    )
    residual_partitions = tuple(
        partition for partition in partitions if partition["partition_kind"] == "response_residual"
    )
    fixed_zero_partitions = tuple(
        partition
        for partition in partitions
        if partition["partition_kind"] == "response_fixed_zero"
    )
    expected = {
        "raw_authority_bundle_sha256": raw_authority_bundle_sha256,
        "expected_unit_count": len(expected_units),
        "expected_unit_inventory_sha256": expected_unit_inventory_sha256,
        "expected_unit_root_sha256": expected_unit_root_sha256,
        "representation_assignment_count": len(assignments),
        "representation_assignment_root_sha256": representation_assignment_root_sha256,
        "observation_count": len(observations),
        "observation_root_sha256": _legacy_ordered_root(
            kind=_OWNERSHIP_OBSERVATION_ROOT_KIND,
            item_sha256s=tuple(
                cast("str", observation["observation_ownership_sha256"])
                for observation in observations
            ),
        ),
        "partition_count": len(partitions),
        "partition_root_sha256": _legacy_ordered_root(
            kind=_OWNERSHIP_PARTITION_ROOT_KIND,
            item_sha256s=tuple(
                cast("str", partition["partition_sha256"]) for partition in partitions
            ),
        ),
        "result_occurrence_partition_count": len(occurrence_partitions),
        "zero_result_occurrence_partition_count": sum(
            partition["record_count"] == 0 for partition in occurrence_partitions
        ),
        "result_occurrence_record_count": sum(
            cast("int", partition["record_count"]) for partition in occurrence_partitions
        ),
        "response_residual_partition_count": len(residual_partitions),
        "positive_response_residual_partition_count": sum(
            cast("int", partition["record_count"]) > 0 for partition in residual_partitions
        ),
        "zero_response_residual_partition_count": sum(
            partition["record_count"] == 0 for partition in residual_partitions
        ),
        "response_residual_record_count": sum(
            cast("int", partition["record_count"]) for partition in residual_partitions
        ),
        "response_fixed_zero_partition_count": len(fixed_zero_partitions),
        "fixed_zero_landing_root_sha256": _legacy_ordered_root(
            kind=_OWNERSHIP_FIXED_ZERO_ROOT_KIND,
            item_sha256s=tuple(
                cast("str", partition["fixed_zero_landing_sha256"])
                for partition in fixed_zero_partitions
            ),
        ),
        "binding_count": len(bindings),
        "binding_root_sha256": _legacy_ordered_root(
            kind=_OWNERSHIP_BINDING_ROOT_KIND,
            item_sha256s=tuple(cast("str", binding["binding_sha256"]) for binding in bindings),
        ),
        "source_record_count": len(bindings),
        "source_record_root_sha256": _legacy_ordered_root(
            kind=_OWNERSHIP_RECORD_ROOT_KIND,
            item_sha256s=tuple(
                cast("str", binding["source_record_sha256"]) for binding in bindings
            ),
        ),
    }
    if any(row[field_name] != expected_value for field_name, expected_value in expected.items()):
        _fail("ownership receipt semantic row differs from its exact authority closure")
    if row["receipt_sha256"] != _semantic_identity_sha256(
        row,
        kind=_OWNERSHIP_RECEIPT_KIND,
        digest_field="receipt_sha256",
    ):
        _fail("ownership receipt semantic digest differs from its exact identity")
    return row


def _decode_semantic_authority(
    *,
    raw_authority_bundle_sha256: str,
    ownership_receipt_row: object,
    expected_unit_rows: object,
    representation_assignment_rows: object,
    ownership_observation_rows: object,
    ownership_partition_rows: object,
    ownership_binding_rows: object,
) -> _SemanticAuthorityV1:
    expected_units, inventory_sha256, unit_root_sha256 = _decode_expected_units(
        raw_authority_bundle_sha256=raw_authority_bundle_sha256,
        rows=expected_unit_rows,
    )
    assignments, assignment_root_sha256 = _decode_assignments(
        raw_authority_bundle_sha256=raw_authority_bundle_sha256,
        rows=representation_assignment_rows,
        expected_units=expected_units,
    )
    observations = _decode_ownership_observations(
        raw_authority_bundle_sha256=raw_authority_bundle_sha256,
        rows=ownership_observation_rows,
    )
    partitions = _decode_ownership_partitions(
        raw_authority_bundle_sha256=raw_authority_bundle_sha256,
        rows=ownership_partition_rows,
        expected_units=expected_units,
        assignments=assignments,
        observations=observations,
    )
    bindings = _decode_ownership_bindings(
        raw_authority_bundle_sha256=raw_authority_bundle_sha256,
        rows=ownership_binding_rows,
        expected_units=expected_units,
        assignments=assignments,
        observations=observations,
        partitions=partitions,
    )
    _validate_ownership_children(
        observations=observations,
        partitions=partitions,
        bindings=bindings,
    )
    receipt = _decode_ownership_receipt(
        raw_authority_bundle_sha256=raw_authority_bundle_sha256,
        value=ownership_receipt_row,
        expected_unit_inventory_sha256=inventory_sha256,
        expected_unit_root_sha256=unit_root_sha256,
        representation_assignment_root_sha256=assignment_root_sha256,
        expected_units=expected_units,
        assignments=assignments,
        observations=observations,
        partitions=partitions,
        bindings=bindings,
    )
    return _SemanticAuthorityV1(
        ownership_receipt=receipt,
        expected_units=expected_units,
        assignments=assignments,
        observations=observations,
        partitions=partitions,
        bindings=bindings,
    )


def _strict_dataclass_row(
    value: object,
    *,
    cls: type[object],
    label: str,
) -> dict[str, object]:
    expected_fields = ("schema_version", *(item.name for item in fields(cls)))
    if type(value) is not dict:
        _fail(f"{label} does not have its exact ordered row shape")
    object_row = cast("dict[object, object]", value)
    if any(type(key) is not str for key in object_row) or tuple(object_row) != expected_fields:
        _fail(f"{label} does not have its exact ordered row shape")
    row = cast("dict[str, object]", value)
    if (
        type(row["schema_version"]) is not int
        or row["schema_version"] != BODY_VALUE_PROJECTION_SCHEMA_VERSION
    ):
        _fail(f"{label} schema version is invalid")
    return row


def _to_row(value: object) -> dict[str, object]:
    dataclass_value = cast("Any", value)
    return {
        "schema_version": BODY_VALUE_PROJECTION_SCHEMA_VERSION,
        **{item.name: getattr(dataclass_value, item.name) for item in fields(dataclass_value)},
    }


def _identity_payload(value: object, *, kind: str, digest_field: str) -> dict[str, object]:
    dataclass_value = cast("Any", value)
    return {
        "schema_version": BODY_VALUE_PROJECTION_SCHEMA_VERSION,
        "kind": kind,
        **{
            item.name: getattr(dataclass_value, item.name)
            for item in fields(dataclass_value)
            if item.name != digest_field
        },
    }


def _canonical_row_bytes(value: object, *, maximum_bytes: int) -> bytes:
    return _canonical_json_bytes(_to_row(value), maximum_bytes=maximum_bytes)


def _row_from_canonical_bytes(
    value: object,
    *,
    cls: type[object],
    label: str,
    maximum_bytes: int,
) -> dict[str, object]:
    if type(value) is not bytes:
        _fail(f"{label} canonical bytes must be one exact bytes object")
    _preflight_json_bytes(value, maximum_bytes=maximum_bytes)
    try:
        text = value.decode("utf-8", errors="strict")
    except UnicodeDecodeError:
        _fail(f"{label} canonical bytes are not strict UTF-8")
    _canonical, decoded = _decode_canonical_json(text, maximum_bytes=maximum_bytes)
    if type(decoded) is not dict:
        _fail(f"{label} canonical bytes do not contain one row object")
    object_row = cast("dict[object, object]", decoded)
    expected = ("schema_version", *(item.name for item in fields(cls)))
    if any(type(key) is not str for key in object_row) or set(object_row) != set(expected):
        _fail(f"{label} canonical bytes do not contain the exact row keys")
    return {field_name: object_row[field_name] for field_name in expected}


def _validate_coordinate(value: object) -> tuple[str, str, dict[str, object]]:
    if type(value) is not dict:
        _fail("value-projection coordinate must be one exact object")
    object_value = cast("dict[object, object]", value)
    if any(type(key) is not str for key in object_value) or set(object_value) != set(
        VALUE_PROJECTION_COORDINATE_FIELDS_V1
    ):
        _fail("value-projection coordinate differs from its fixed V1 key schema")
    coordinate = cast("dict[str, object]", value)
    for field_name in VALUE_PROJECTION_COORDINATE_FIELDS_V1:
        item = coordinate[field_name]
        if field_name in _COORDINATE_ORDINAL_FIELDS:
            _optional_nonnegative(item, field_name=field_name, maximum=_MAX_ORDINAL)
        elif field_name in {
            "header_value_sha256",
            "row_value_sha256",
            "decoder_value_sha256",
        }:
            _optional_sha256(item, field_name=field_name)
        elif field_name in {"known_contract_field", "matches_result_occurrence"}:
            if item is not None and type(item) is not bool:
                _fail(f"{field_name} must be an exact boolean or null")
        elif field_name in _COORDINATE_TEXT_FIELDS:
            maximum = (
                MAX_VALUE_PROJECTION_PATH_BYTES
                if field_name in _COORDINATE_PATH_FIELDS
                else _MAX_METADATA_TEXT_BYTES
            )
            _optional_text(
                item,
                field_name=field_name,
                maximum_bytes=maximum,
                allow_empty=field_name
                in {
                    "header_name",
                    "result_path",
                    "json_path",
                    "parent_json_path",
                    "object_key",
                },
            )
        else:
            _fail("value-projection coordinate validator has an unknown field")
    result_presence = coordinate["result_presence"]
    if result_presence is not None and result_presence not in _RESULT_PRESENCES:
        _fail("value-projection result presence is outside its closed V1 domain")
    key_presence = coordinate["key_presence"]
    if key_presence is not None and key_presence not in _KEY_PRESENCES:
        _fail("value-projection key presence is outside its closed V1 domain")
    header_reference_kind = coordinate["header_reference_kind"]
    if header_reference_kind is not None and header_reference_kind not in _HEADER_REFERENCE_KINDS:
        _fail("value-projection header reference kind is outside its closed V1 domain")
    occurrence_presence = coordinate["result_occurrence_presence_kind"]
    if occurrence_presence is not None and occurrence_presence not in _LIVE_OCCURRENCE_PRESENCES:
        _fail("live result occurrence presence is outside its closed V1 domain")
    canonical = _canonical_json_bytes(
        coordinate,
        maximum_bytes=MAX_VALUE_PROJECTION_PATH_BYTES * 8,
    ).decode("utf-8")
    return canonical, _sha256_bytes(canonical.encode("utf-8")), coordinate


def _decode_coordinate(value: object, *, expected_sha256: object) -> dict[str, object]:
    canonical, decoded = _decode_canonical_json(
        value,
        maximum_bytes=MAX_VALUE_PROJECTION_PATH_BYTES * 8,
    )
    coordinate_canonical, coordinate_sha256, coordinate = _validate_coordinate(decoded)
    if canonical != coordinate_canonical or expected_sha256 != coordinate_sha256:
        _fail("value-projection coordinate JSON or digest is inconsistent")
    return coordinate


def _empty_coordinate() -> dict[str, object]:
    return {field_name: None for field_name in VALUE_PROJECTION_COORDINATE_FIELDS_V1}


def _validate_header_slots(
    value: object,
    *,
    header_record_count: object,
    header_slot_count: object,
) -> tuple[dict[str, object], ...]:
    record_count = _exact_nonnegative(
        header_record_count,
        field_name="projection header-record count",
        maximum=_MAX_HEADER_COUNT,
    )
    slot_count = _exact_nonnegative(
        header_slot_count,
        field_name="projection header-slot count",
        maximum=_MAX_HEADER_COUNT,
    )
    if record_count > slot_count:
        _fail("projection header-record count exceeds its slot inventory")
    if type(value) is not tuple or len(value) != slot_count:
        _fail("projection ordered header-slot inventory is foreign or incomplete")
    slots: list[dict[str, object]] = []
    for ordinal, item in enumerate(value):
        if (
            type(item) is not dict
            or set(item) != _HEADER_SLOT_FIELDS
            or any(type(key) is not str for key in item)
        ):
            _fail("projection ordered header slot differs from its fixed V1 schema")
        slot = cast("dict[str, object]", item)
        reference_kind = slot["header_reference_kind"]
        if type(reference_kind) is not str or reference_kind not in _HEADER_REFERENCE_KINDS:
            _fail("projection ordered header slot has a foreign reference kind")
        header_name = slot["header_name"]
        header_value_sha256 = slot["header_value_sha256"]
        if ordinal < record_count:
            _exact_sha256(header_value_sha256, field_name="ordered header value")
            if reference_kind == "named":
                _exact_text(
                    header_name,
                    field_name="ordered named header",
                    maximum_bytes=_MAX_METADATA_TEXT_BYTES,
                    allow_empty=True,
                )
                if header_value_sha256 != _sha256_bytes(
                    _canonical_json_bytes(
                        header_name,
                        maximum_bytes=MAX_VALUE_PROJECTION_CANONICAL_VALUE_BYTES,
                    )
                ):
                    _fail("projection named header digest differs from its exact text")
            elif reference_kind != "non_string" or header_name is not None:
                _fail("projection materialized header slot has an invalid exact shape")
        elif (
            reference_kind != "out_of_range"
            or header_name is not None
            or header_value_sha256 is not None
        ):
            _fail("projection out-of-range header slot fabricates header material")
        slots.append(dict(slot))
    return tuple(slots)


_NO_VALUE: Final = object()


@dataclass(frozen=True, slots=True)
class ValueProjectionItemV1:
    """One exact source-record-to-public-value projection."""

    item_sha256: str
    raw_authority_bundle_sha256: str
    ownership_binding_sha256: str
    ownership_binding_ordinal: int
    source_record_sha256: str
    observation_record_sha256: str
    observation_sha256: str
    observation_ordinal: int
    ownership_partition_sha256: str
    partition_ordinal: int
    unit_sha256: str
    unit_ordinal: int
    assignment_sha256: str
    source_input_kind: ValueProjectionSourceInputKindV1
    representation_kind: ValueProjectionRepresentationKindV1
    unit_kind: ValueProjectionUnitKindV1
    occurrence_sha256: str | None
    occurrence_ordinal: int | None
    global_item_ordinal: int
    partition_item_ordinal: int
    record_kind: ValueProjectionRecordKindV1
    coordinate_json: str
    coordinate_sha256: str
    value_state: ValueProjectionValueStateV1
    presence_kind: ValueProjectionPresenceKindV1 | None
    value_kind: ValueProjectionValueKindV1 | None
    canonical_json: str | None
    canonical_json_sha256: str | None

    schema_version: ClassVar[int] = BODY_VALUE_PROJECTION_SCHEMA_VERSION
    kind: ClassVar[str] = _ITEM_KIND

    def __post_init__(self) -> None:
        for field_name in (
            "item_sha256",
            "raw_authority_bundle_sha256",
            "ownership_binding_sha256",
            "source_record_sha256",
            "observation_record_sha256",
            "observation_sha256",
            "ownership_partition_sha256",
            "unit_sha256",
            "assignment_sha256",
            "coordinate_sha256",
        ):
            _exact_sha256(getattr(self, field_name), field_name=field_name)
        for field_name, maximum in (
            ("ownership_binding_ordinal", MAX_VALUE_PROJECTION_ITEMS - 1),
            ("observation_ordinal", MAX_VALUE_PROJECTION_OBSERVATIONS - 1),
            ("partition_ordinal", MAX_VALUE_PROJECTION_PARTITIONS - 1),
            ("unit_ordinal", MAX_VALUE_PROJECTION_OBSERVATIONS - 1),
            ("global_item_ordinal", MAX_VALUE_PROJECTION_ITEMS - 1),
            ("partition_item_ordinal", MAX_VALUE_PROJECTION_ITEMS - 1),
        ):
            _exact_nonnegative(getattr(self, field_name), field_name=field_name, maximum=maximum)
        if self.ownership_binding_ordinal != self.global_item_ordinal:
            _fail("value-projection item order differs from ownership binding order")
        if (
            type(self.source_input_kind) is not str
            or self.source_input_kind not in _SOURCE_INPUT_KINDS
        ):
            _fail("value-projection source-input kind is outside its closed V1 domain")
        if (
            type(self.representation_kind) is not str
            or self.representation_kind not in _REPRESENTATION_KINDS
        ):
            _fail("value-projection representation kind is outside its closed V1 domain")
        if type(self.unit_kind) is not str or self.unit_kind not in _UNIT_KINDS:
            _fail("value-projection unit kind is outside its closed V1 domain")
        if self.unit_kind == "result_occurrence":
            _exact_sha256(self.occurrence_sha256, field_name="item occurrence")
            _exact_nonnegative(
                self.occurrence_ordinal,
                field_name="item occurrence ordinal",
                maximum=MAX_VALUE_PROJECTION_OBSERVATIONS - 1,
            )
            if self.representation_kind not in _RESULT_REPRESENTATIONS:
                _fail("result-occurrence item uses a response representation")
        elif (
            self.unit_kind != "response_residual"
            or self.occurrence_sha256 is not None
            or self.occurrence_ordinal is not None
            or self.representation_kind != "response_lossless_records_v1"
        ):
            _fail("response item has an invalid unit or occurrence shape")
        if self.representation_kind == "response_fixed_zero_v1":
            _fail("fixed-zero representation cannot contain projection items")
        if type(self.record_kind) is not str or self.record_kind not in _RECORD_KINDS:
            _fail("value-projection record kind is outside its closed V1 domain")
        if self.record_kind not in _RECORDS_BY_REPRESENTATION[self.representation_kind]:
            _fail("value-projection record kind is incompatible with its representation")
        _decode_coordinate(self.coordinate_json, expected_sha256=self.coordinate_sha256)
        self._validate_value()
        if self.item_sha256 != _canonical_sha256(
            self.identity_payload(),
            maximum_bytes=_MAX_ROW_BYTES,
        ):
            _fail("value-projection item digest differs from its exact identity")

    def _validate_value(self) -> None:
        if type(self.value_state) is not str or self.value_state not in _VALUE_STATES:
            _fail("value-projection value state is outside its closed V1 domain")
        if self.value_state == "absent":
            if any(
                value is not None
                for value in (
                    self.presence_kind,
                    self.value_kind,
                    self.canonical_json,
                    self.canonical_json_sha256,
                )
            ):
                _fail("absent projection value carries value material")
            return
        if type(self.presence_kind) is not str or self.presence_kind not in _PRESENCE_KINDS:
            _fail("value-projection presence kind is outside its closed V1 domain")
        if type(self.value_kind) is not str or self.value_kind not in _VALUE_KINDS:
            _fail("value-projection value kind is outside its closed V1 domain")
        if self.value_state == "missing":
            if (
                self.presence_kind not in _MISSING_PRESENCES
                or self.value_kind != "missing"
                or self.canonical_json is not None
                or self.canonical_json_sha256 is not None
            ):
                _fail("missing projection value has an invalid absence proof")
            return
        if self.value_state == "structural_container":
            if (
                self.record_kind not in {"node", "json_node", "field_cell"}
                or self.presence_kind != "present"
                or self.value_kind not in {"array", "object"}
                or self.canonical_json is not None
                or self.canonical_json_sha256 is not None
            ):
                _fail("structural projection container has an invalid exact shape")
            return
        if self.presence_kind in _MISSING_PRESENCES or self.value_kind == "missing":
            _fail("canonical projection value uses a missing kind")
        canonical_json, value = _decode_canonical_json(
            self.canonical_json,
            maximum_bytes=MAX_VALUE_PROJECTION_CANONICAL_VALUE_BYTES,
        )
        if (
            self.canonical_json_sha256 != _sha256_bytes(canonical_json.encode("utf-8"))
            or self.value_kind != _value_kind(value)
            or self.presence_kind != _presence_kind(value)
        ):
            _fail("projection canonical value digest, type, or presence is inconsistent")

    @classmethod
    def build(
        cls,
        *,
        raw_authority_bundle_sha256: str,
        ownership_binding_sha256: str,
        ownership_binding_ordinal: int,
        source_record_sha256: str,
        observation_record_sha256: str,
        observation_sha256: str,
        observation_ordinal: int,
        ownership_partition_sha256: str,
        partition_ordinal: int,
        unit_sha256: str,
        unit_ordinal: int,
        assignment_sha256: str,
        source_input_kind: ValueProjectionSourceInputKindV1,
        representation_kind: ValueProjectionRepresentationKindV1,
        unit_kind: ValueProjectionUnitKindV1,
        occurrence_sha256: str | None,
        occurrence_ordinal: int | None,
        global_item_ordinal: int,
        partition_item_ordinal: int,
        record_kind: ValueProjectionRecordKindV1,
        coordinate: dict[str, object],
        value_state: ValueProjectionValueStateV1 = "canonical",
        value: object = _NO_VALUE,
        missing_presence_kind: ValueProjectionPresenceKindV1 | None = None,
        structural_value_kind: ValueProjectionValueKindV1 | None = None,
    ) -> Self:
        # External identities and shapes are validated before either coordinate
        # or value traversal, preserving the pin-first boundary.
        for field_name, identity in (
            ("raw_authority_bundle_sha256", raw_authority_bundle_sha256),
            ("ownership_binding_sha256", ownership_binding_sha256),
            ("source_record_sha256", source_record_sha256),
            ("observation_record_sha256", observation_record_sha256),
            ("observation_sha256", observation_sha256),
            ("ownership_partition_sha256", ownership_partition_sha256),
            ("unit_sha256", unit_sha256),
            ("assignment_sha256", assignment_sha256),
        ):
            _exact_sha256(identity, field_name=field_name)
        for field_name, ordinal, maximum in (
            (
                "ownership_binding_ordinal",
                ownership_binding_ordinal,
                MAX_VALUE_PROJECTION_ITEMS - 1,
            ),
            ("observation_ordinal", observation_ordinal, MAX_VALUE_PROJECTION_OBSERVATIONS - 1),
            ("partition_ordinal", partition_ordinal, MAX_VALUE_PROJECTION_PARTITIONS - 1),
            ("unit_ordinal", unit_ordinal, MAX_VALUE_PROJECTION_OBSERVATIONS - 1),
            ("global_item_ordinal", global_item_ordinal, MAX_VALUE_PROJECTION_ITEMS - 1),
            ("partition_item_ordinal", partition_item_ordinal, MAX_VALUE_PROJECTION_ITEMS - 1),
        ):
            _exact_nonnegative(ordinal, field_name=field_name, maximum=maximum)
        canonical_coordinate, coordinate_sha256, _coordinate = _validate_coordinate(coordinate)
        presence_kind: ValueProjectionPresenceKindV1 | None
        value_kind: ValueProjectionValueKindV1 | None
        canonical_json: str | None
        canonical_json_sha256: str | None
        if value_state == "canonical":
            if (
                value is _NO_VALUE
                or missing_presence_kind is not None
                or structural_value_kind is not None
            ):
                _fail("canonical projection builder requires exactly one runtime value")
            canonical_bytes = _canonical_json_bytes(
                value,
                maximum_bytes=MAX_VALUE_PROJECTION_CANONICAL_VALUE_BYTES,
            )
            canonical_json = canonical_bytes.decode("utf-8")
            _canonical, exact_value = _decode_canonical_json(
                canonical_json,
                maximum_bytes=MAX_VALUE_PROJECTION_CANONICAL_VALUE_BYTES,
            )
            presence_kind = _presence_kind(exact_value)
            value_kind = _value_kind(exact_value)
            canonical_json_sha256 = _sha256_bytes(canonical_bytes)
        elif value_state == "structural_container":
            if (
                value is not _NO_VALUE
                or missing_presence_kind is not None
                or structural_value_kind not in {"array", "object"}
                or record_kind not in {"node", "json_node", "field_cell"}
            ):
                _fail("structural projection builder requires one exact container kind")
            presence_kind = "present"
            value_kind = structural_value_kind
            canonical_json = None
            canonical_json_sha256 = None
        elif value_state == "missing":
            if (
                value is not _NO_VALUE
                or missing_presence_kind not in _MISSING_PRESENCES
                or structural_value_kind is not None
            ):
                _fail("missing projection builder requires one closed missing presence")
            presence_kind = missing_presence_kind
            value_kind = "missing"
            canonical_json = None
            canonical_json_sha256 = None
        elif value_state == "absent":
            if (
                value is not _NO_VALUE
                or missing_presence_kind is not None
                or structural_value_kind is not None
            ):
                _fail("absent projection builder cannot carry value material")
            presence_kind = None
            value_kind = None
            canonical_json = None
            canonical_json_sha256 = None
        else:
            _fail("projection builder value state is outside its closed V1 domain")
        values: dict[str, object] = {
            "raw_authority_bundle_sha256": raw_authority_bundle_sha256,
            "ownership_binding_sha256": ownership_binding_sha256,
            "ownership_binding_ordinal": ownership_binding_ordinal,
            "source_record_sha256": source_record_sha256,
            "observation_record_sha256": observation_record_sha256,
            "observation_sha256": observation_sha256,
            "observation_ordinal": observation_ordinal,
            "ownership_partition_sha256": ownership_partition_sha256,
            "partition_ordinal": partition_ordinal,
            "unit_sha256": unit_sha256,
            "unit_ordinal": unit_ordinal,
            "assignment_sha256": assignment_sha256,
            "source_input_kind": source_input_kind,
            "representation_kind": representation_kind,
            "unit_kind": unit_kind,
            "occurrence_sha256": occurrence_sha256,
            "occurrence_ordinal": occurrence_ordinal,
            "global_item_ordinal": global_item_ordinal,
            "partition_item_ordinal": partition_item_ordinal,
            "record_kind": record_kind,
            "coordinate_json": canonical_coordinate,
            "coordinate_sha256": coordinate_sha256,
            "value_state": value_state,
            "presence_kind": presence_kind,
            "value_kind": value_kind,
            "canonical_json": canonical_json,
            "canonical_json_sha256": canonical_json_sha256,
        }
        payload = {"schema_version": cls.schema_version, "kind": cls.kind, **values}
        return cls(
            item_sha256=_canonical_sha256(payload, maximum_bytes=_MAX_ROW_BYTES),
            **cast("Any", values),
        )

    def identity_payload(self) -> dict[str, object]:
        return _identity_payload(self, kind=self.kind, digest_field="item_sha256")

    def coordinate(self) -> dict[str, object]:
        """Return a fresh exact coordinate object."""

        return dict(
            _decode_coordinate(
                self.coordinate_json,
                expected_sha256=self.coordinate_sha256,
            )
        )

    def value(self) -> object:
        """Return a fresh exact JSON graph; missing/absent records are invalid."""

        if self.value_state != "canonical":
            _fail("noncanonical projection item has no runtime value")
        _canonical, value = _decode_canonical_json(
            self.canonical_json,
            maximum_bytes=MAX_VALUE_PROJECTION_CANONICAL_VALUE_BYTES,
        )
        return value

    def to_row(self) -> dict[str, object]:
        return _to_row(self)

    @classmethod
    def from_row(cls, value: object) -> Self:
        row = _strict_dataclass_row(value, cls=cls, label="value-projection item row")
        try:
            return cls(**cast("Any", {item.name: row[item.name] for item in fields(cls)}))
        except ValueProjectionError:
            raise
        except (TypeError, ValueError, RecursionError):
            _fail("value-projection item row failed semantic reconstruction")

    def canonical_bytes(self) -> bytes:
        return _canonical_row_bytes(self, maximum_bytes=_MAX_ROW_BYTES)

    @classmethod
    def from_canonical_bytes(cls, value: object) -> Self:
        return cls.from_row(
            _row_from_canonical_bytes(
                value,
                cls=cls,
                label="value-projection item",
                maximum_bytes=_MAX_ROW_BYTES,
            )
        )


@dataclass(frozen=True, slots=True)
class ValueProjectionPartitionV1:
    """One explicit result, residual, or fixed-zero value partition."""

    partition_sha256: str
    raw_authority_bundle_sha256: str
    ownership_partition_sha256: str
    observation_record_sha256: str
    observation_sha256: str
    observation_ordinal: int
    partition_ordinal: int
    observation_partition_ordinal: int
    partition_kind: ValueProjectionUnitKindV1
    occurrence_sha256: str | None
    occurrence_ordinal: int | None
    unit_sha256: str | None
    unit_ordinal: int | None
    assignment_sha256: str | None
    source_input_kind: ValueProjectionSourceInputKindV1
    representation_kind: ValueProjectionRepresentationKindV1 | None
    source_record_count: int
    source_record_root_sha256: str
    binding_count: int
    binding_root_sha256: str
    first_global_item_ordinal: int | None
    item_count: int
    item_root_sha256: str
    result_name: str | None
    result_duplicate_ordinal: int | None
    provider_result_ordinal: int | None
    expected_result_ordinal: int | None
    canonical_result_ordinal: int | None
    result_path: str | None
    container_kind: str | None
    result_presence: str | None
    ordered_headers_json: str | None
    ordered_headers_sha256: str | None
    header_count: int
    ordered_header_slots_json: str | None
    ordered_header_slots_sha256: str | None
    header_record_count: int
    header_slot_count: int
    field_count: int
    row_count: int
    cell_count: int
    node_count: int
    record_count: int
    present_count: int
    null_count: int
    empty_object_count: int
    empty_array_count: int
    missing_count: int
    mixed_absent_count: int
    not_observed_parent_empty_count: int
    absent_count: int
    structural_value_count: int
    canonical_value_byte_count: int
    representation_output_sha256: str | None
    fixed_zero_landing_sha256: str | None

    schema_version: ClassVar[int] = BODY_VALUE_PROJECTION_SCHEMA_VERSION
    kind: ClassVar[str] = _PARTITION_KIND

    def __post_init__(self) -> None:
        for field_name in (
            "partition_sha256",
            "raw_authority_bundle_sha256",
            "ownership_partition_sha256",
            "observation_record_sha256",
            "observation_sha256",
            "source_record_root_sha256",
            "binding_root_sha256",
            "item_root_sha256",
        ):
            _exact_sha256(getattr(self, field_name), field_name=field_name)
        for field_name, maximum in (
            ("observation_ordinal", MAX_VALUE_PROJECTION_OBSERVATIONS - 1),
            ("partition_ordinal", MAX_VALUE_PROJECTION_PARTITIONS - 1),
            ("observation_partition_ordinal", MAX_VALUE_PROJECTION_PARTITIONS - 1),
            ("source_record_count", MAX_VALUE_PROJECTION_ITEMS),
            ("binding_count", MAX_VALUE_PROJECTION_ITEMS),
            ("item_count", MAX_VALUE_PROJECTION_ITEMS),
            ("header_count", _MAX_HEADER_COUNT),
            ("header_record_count", _MAX_HEADER_COUNT),
            ("header_slot_count", _MAX_HEADER_COUNT),
            ("field_count", _MAX_HEADER_COUNT),
            ("row_count", MAX_VALUE_PROJECTION_JSON_NODES),
            ("cell_count", MAX_VALUE_PROJECTION_ITEMS),
            ("node_count", MAX_VALUE_PROJECTION_JSON_NODES),
            ("record_count", MAX_VALUE_PROJECTION_ITEMS),
            ("present_count", MAX_VALUE_PROJECTION_ITEMS),
            ("null_count", MAX_VALUE_PROJECTION_ITEMS),
            ("empty_object_count", MAX_VALUE_PROJECTION_ITEMS),
            ("empty_array_count", MAX_VALUE_PROJECTION_ITEMS),
            ("missing_count", MAX_VALUE_PROJECTION_ITEMS),
            ("mixed_absent_count", MAX_VALUE_PROJECTION_ITEMS),
            ("not_observed_parent_empty_count", MAX_VALUE_PROJECTION_ITEMS),
            ("absent_count", MAX_VALUE_PROJECTION_ITEMS),
            ("structural_value_count", MAX_VALUE_PROJECTION_ITEMS),
            ("canonical_value_byte_count", MAX_VALUE_PROJECTION_TOTAL_CANONICAL_BYTES),
        ):
            _exact_nonnegative(getattr(self, field_name), field_name=field_name, maximum=maximum)
        _optional_nonnegative(
            self.first_global_item_ordinal,
            field_name="first global item ordinal",
            maximum=MAX_VALUE_PROJECTION_ITEMS - 1,
        )
        for field_name in (
            "occurrence_sha256",
            "unit_sha256",
            "assignment_sha256",
            "ordered_headers_sha256",
            "ordered_header_slots_sha256",
            "representation_output_sha256",
            "fixed_zero_landing_sha256",
        ):
            _optional_sha256(getattr(self, field_name), field_name=field_name)
        for field_name, maximum in (
            ("occurrence_ordinal", MAX_VALUE_PROJECTION_OBSERVATIONS - 1),
            ("unit_ordinal", MAX_VALUE_PROJECTION_OBSERVATIONS - 1),
            ("result_duplicate_ordinal", MAX_VALUE_PROJECTION_OBSERVATIONS - 1),
            ("provider_result_ordinal", MAX_VALUE_PROJECTION_OBSERVATIONS - 1),
            ("expected_result_ordinal", MAX_VALUE_PROJECTION_OBSERVATIONS - 1),
            ("canonical_result_ordinal", MAX_VALUE_PROJECTION_OBSERVATIONS - 1),
        ):
            _optional_nonnegative(getattr(self, field_name), field_name=field_name, maximum=maximum)
        for field_name in ("result_name", "container_kind"):
            _optional_text(
                getattr(self, field_name),
                field_name=field_name,
                maximum_bytes=_MAX_METADATA_TEXT_BYTES,
            )
        _optional_text(
            self.result_path,
            field_name="result_path",
            maximum_bytes=MAX_VALUE_PROJECTION_PATH_BYTES,
            allow_empty=True,
        )
        if self.result_presence is not None and (
            type(self.result_presence) is not str or self.result_presence not in _RESULT_PRESENCES
        ):
            _fail("projection partition result presence is outside its closed V1 domain")
        if type(self.partition_kind) is not str or self.partition_kind not in _UNIT_KINDS:
            _fail("projection partition kind is outside its closed V1 domain")
        if (
            type(self.source_input_kind) is not str
            or self.source_input_kind not in _SOURCE_INPUT_KINDS
        ):
            _fail("projection partition source input is outside its closed V1 domain")
        if self.representation_kind is not None and (
            type(self.representation_kind) is not str
            or self.representation_kind not in _REPRESENTATION_KINDS
        ):
            _fail("projection partition representation is outside its closed V1 domain")
        if not (
            self.source_record_count == self.binding_count == self.item_count == self.record_count
        ):
            _fail("projection partition source, binding, item, and record counts differ")
        if (self.item_count == 0) != (self.first_global_item_ordinal is None):
            _fail("projection partition first item ordinal disagrees with its count")
        if self.item_count != sum(
            (
                self.present_count,
                self.null_count,
                self.empty_object_count,
                self.empty_array_count,
                self.missing_count,
                self.mixed_absent_count,
                self.not_observed_parent_empty_count,
                self.absent_count,
            )
        ):
            _fail("projection partition presence counters do not partition its items")
        if self.structural_value_count > self.present_count:
            _fail("projection partition structural count exceeds present values")
        self._validate_partition_shape()
        self._validate_zero_roots()
        if self.partition_sha256 != _canonical_sha256(self.identity_payload()):
            _fail("projection partition digest differs from its exact identity")

    def _validate_partition_shape(self) -> None:
        unit_present = (
            self.unit_sha256 is not None
            and self.unit_ordinal is not None
            and self.assignment_sha256 is not None
            and self.representation_kind is not None
        )
        unit_absent = (
            self.unit_sha256 is None
            and self.unit_ordinal is None
            and self.assignment_sha256 is None
            and self.representation_kind is None
        )
        if not unit_present and not unit_absent:
            _fail("projection partition has a partial unit/assignment binding")
        structure = (
            self.result_name,
            self.result_duplicate_ordinal,
            self.provider_result_ordinal,
            self.expected_result_ordinal,
            self.canonical_result_ordinal,
            self.result_path,
            self.container_kind,
            self.result_presence,
            self.ordered_headers_json,
            self.ordered_headers_sha256,
            self.ordered_header_slots_json,
            self.ordered_header_slots_sha256,
        )
        if self.partition_kind == "result_occurrence":
            if (
                not unit_present
                or self.occurrence_sha256 is None
                or self.occurrence_ordinal is None
                or self.representation_kind not in _RESULT_REPRESENTATIONS
                or self.result_name is None
                or self.result_duplicate_ordinal is None
                or self.result_path is None
                or self.container_kind is None
                or self.result_presence is None
                or self.representation_output_sha256 is None
                or self.fixed_zero_landing_sha256 is not None
            ):
                _fail("result projection partition has an invalid identity or structure")
            if self.representation_kind == "stats_lossless_records_v1":
                if (
                    self.ordered_headers_json is not None
                    or self.ordered_headers_sha256 is not None
                    or self.header_count != 0
                    or self.ordered_header_slots_json is None
                    or self.ordered_header_slots_sha256 is None
                    or self.field_count != 0
                ):
                    _fail("stats projection partition has a foreign header vocabulary")
                canonical_slots, slots = _decode_canonical_json(
                    self.ordered_header_slots_json,
                    maximum_bytes=MAX_VALUE_PROJECTION_PATH_BYTES * _MAX_HEADER_COUNT,
                )
                if type(slots) is not list:
                    _fail("stats projection header slots are not one exact array")
                exact_slots = _validate_header_slots(
                    tuple(cast("list[object]", slots)),
                    header_record_count=self.header_record_count,
                    header_slot_count=self.header_slot_count,
                )
                if len(
                    exact_slots
                ) != self.header_slot_count or self.ordered_header_slots_sha256 != _sha256_bytes(
                    canonical_slots.encode("utf-8")
                ):
                    _fail("stats projection ordered header-slot digest is inconsistent")
            else:
                if (
                    self.ordered_headers_json is None
                    or self.ordered_headers_sha256 is None
                    or self.ordered_header_slots_json is not None
                    or self.ordered_header_slots_sha256 is not None
                    or self.header_record_count != 0
                    or self.header_slot_count != 0
                ):
                    _fail("non-stats projection partition has a foreign header vocabulary")
                canonical_headers, headers = _decode_canonical_json(
                    self.ordered_headers_json,
                    maximum_bytes=MAX_VALUE_PROJECTION_PATH_BYTES * _MAX_HEADER_COUNT,
                )
                if type(headers) is not list or any(type(item) is not str for item in headers):
                    _fail("result projection headers must be one exact string array")
                header_values = cast("list[str]", headers)
                if len(header_values) != self.header_count:
                    _fail("result projection header count differs from its ordered headers")
                for header in header_values:
                    _exact_text(
                        header,
                        field_name="ordered result header",
                        maximum_bytes=4_096,
                        allow_empty=True,
                    )
                if self.ordered_headers_sha256 != _sha256_bytes(canonical_headers.encode("utf-8")):
                    _fail("result projection ordered-header digest is inconsistent")
            if (
                self.container_kind
                not in _RESULT_CONTAINERS_BY_REPRESENTATION[cast("str", self.representation_kind)]
            ):
                _fail("result projection container contradicts its representation")
            if self.representation_kind == "rectangular_result_cells_v1" and (
                self.record_count != self.cell_count
                or self.node_count != 0
                or self.field_count != 0
                or self.row_count * self.header_count != self.cell_count
            ):
                _fail("rectangular projection partition is not an exact cell rectangle")
        elif self.partition_kind == "response_residual":
            if (
                self.occurrence_sha256 is not None
                or self.occurrence_ordinal is not None
                or any(value is not None for value in structure)
                or self.header_count != 0
                or self.header_record_count != 0
                or self.header_slot_count != 0
                or self.field_count != 0
                or self.row_count != 0
                or self.cell_count != 0
                or self.fixed_zero_landing_sha256 is not None
            ):
                _fail("response-residual projection partition carries result structure")
            if self.item_count == 0:
                if not unit_absent or self.representation_output_sha256 is not None:
                    _fail("zero response residual must be explicitly unassigned and empty")
            elif (
                not unit_present
                or self.representation_kind != "response_lossless_records_v1"
                or self.representation_output_sha256 is None
            ):
                _fail("positive response residual lacks its sole assignment/output")
        elif (
            not unit_present
            or self.representation_kind != "response_fixed_zero_v1"
            or self.occurrence_sha256 is not None
            or self.occurrence_ordinal is not None
            or self.item_count != 0
            or any(value is not None for value in structure)
            or any(
                value != 0
                for value in (
                    self.header_count,
                    self.header_record_count,
                    self.header_slot_count,
                    self.field_count,
                    self.row_count,
                    self.cell_count,
                    self.node_count,
                )
            )
            or self.representation_output_sha256 is not None
            or self.fixed_zero_landing_sha256 is None
        ):
            _fail("fixed-zero projection partition has an invalid zero proof")

    def _validate_zero_roots(self) -> None:
        roots = (
            (
                self.source_record_root_sha256,
                _length_framed_root(
                    kind=_PARTITION_RECORD_ROOT_KIND,
                    raw_authority_bundle_sha256=self.raw_authority_bundle_sha256,
                    item_sha256s=(),
                    maximum=MAX_VALUE_PROJECTION_ITEMS,
                ),
            ),
            (
                self.binding_root_sha256,
                _length_framed_root(
                    kind=_PARTITION_BINDING_ROOT_KIND,
                    raw_authority_bundle_sha256=self.raw_authority_bundle_sha256,
                    item_sha256s=(),
                    maximum=MAX_VALUE_PROJECTION_ITEMS,
                ),
            ),
            (
                self.item_root_sha256,
                _length_framed_root(
                    kind=_PARTITION_ITEM_ROOT_KIND,
                    raw_authority_bundle_sha256=self.raw_authority_bundle_sha256,
                    item_sha256s=(),
                    maximum=MAX_VALUE_PROJECTION_ITEMS,
                ),
            ),
        )
        for actual, empty in roots:
            if (self.item_count == 0) != (actual == empty):
                _fail("projection partition zero root is inconsistent")
        if (self.canonical_value_byte_count == 0) != (
            self.present_count
            + self.null_count
            + self.empty_object_count
            + self.empty_array_count
            - self.structural_value_count
            == 0
        ):
            _fail("projection partition canonical-byte zero proof is inconsistent")

    @classmethod
    def build(
        cls,
        *,
        raw_authority_bundle_sha256: str,
        ownership_partition_sha256: str,
        observation_record_sha256: str,
        observation_sha256: str,
        observation_ordinal: int,
        partition_ordinal: int,
        observation_partition_ordinal: int,
        partition_kind: ValueProjectionUnitKindV1,
        source_input_kind: ValueProjectionSourceInputKindV1,
        items: tuple[ValueProjectionItemV1, ...],
        occurrence_sha256: str | None = None,
        occurrence_ordinal: int | None = None,
        unit_sha256: str | None = None,
        unit_ordinal: int | None = None,
        assignment_sha256: str | None = None,
        representation_kind: ValueProjectionRepresentationKindV1 | None = None,
        result_name: str | None = None,
        result_duplicate_ordinal: int | None = None,
        provider_result_ordinal: int | None = None,
        expected_result_ordinal: int | None = None,
        canonical_result_ordinal: int | None = None,
        result_path: str | None = None,
        container_kind: str | None = None,
        result_presence: str | None = None,
        ordered_headers: tuple[str, ...] | None = None,
        header_count: int = 0,
        ordered_header_slots: tuple[dict[str, object], ...] | None = None,
        header_record_count: int = 0,
        header_slot_count: int = 0,
        field_count: int = 0,
        row_count: int = 0,
        cell_count: int = 0,
        node_count: int = 0,
        representation_output_sha256: str | None = None,
        fixed_zero_landing_sha256: str | None = None,
    ) -> Self:
        # Pins and tuple shape are checked before member replay/allocation.
        for field_name, identity in (
            ("raw_authority_bundle_sha256", raw_authority_bundle_sha256),
            ("ownership_partition_sha256", ownership_partition_sha256),
            ("observation_record_sha256", observation_record_sha256),
            ("observation_sha256", observation_sha256),
        ):
            _exact_sha256(identity, field_name=field_name)
        if type(items) is not tuple or len(items) > MAX_VALUE_PROJECTION_ITEMS:
            _fail("projection partition item inventory is foreign or over-bound")
        if any(type(item) is not ValueProjectionItemV1 for item in items):
            _fail("projection partition contains a foreign item DTO")
        exact_items = tuple(ValueProjectionItemV1.from_row(item.to_row()) for item in items)
        last_global = -1
        for local_ordinal, item in enumerate(exact_items):
            if (
                item.raw_authority_bundle_sha256 != raw_authority_bundle_sha256
                or item.ownership_partition_sha256 != ownership_partition_sha256
                or item.observation_record_sha256 != observation_record_sha256
                or item.observation_sha256 != observation_sha256
                or item.observation_ordinal != observation_ordinal
                or item.partition_ordinal != partition_ordinal
                or item.partition_item_ordinal != local_ordinal
                or item.source_input_kind != source_input_kind
                or item.unit_kind != partition_kind
                or item.occurrence_sha256 != occurrence_sha256
                or item.occurrence_ordinal != occurrence_ordinal
                or item.unit_sha256 != unit_sha256
                or item.unit_ordinal != unit_ordinal
                or item.assignment_sha256 != assignment_sha256
                or item.representation_kind != representation_kind
            ):
                _fail("projection partition contains a foreign or reordered item")
            if item.global_item_ordinal <= last_global:
                _fail("projection partition item order is not globally monotonic")
            last_global = item.global_item_ordinal
        if len({item.item_sha256 for item in exact_items}) != len(exact_items):
            _fail("projection partition contains a duplicate item identity")
        if len({item.source_record_sha256 for item in exact_items}) != len(exact_items):
            _fail("projection partition dual-projects one source record")
        if len({item.ownership_binding_sha256 for item in exact_items}) != len(exact_items):
            _fail("projection partition reuses one ownership binding")
        ordered_headers_json: str | None
        ordered_headers_sha256: str | None
        if ordered_headers is None:
            ordered_headers_json = None
            ordered_headers_sha256 = None
        else:
            if type(ordered_headers) is not tuple or len(ordered_headers) > _MAX_HEADER_COUNT:
                _fail("projection partition headers are foreign or over-bound")
            if any(type(header) is not str for header in ordered_headers):
                _fail("projection partition headers contain a foreign exact type")
            if header_count != len(ordered_headers):
                _fail("projection partition header count differs from its exact tuple")
            encoded_headers = _canonical_json_bytes(
                list(ordered_headers),
                maximum_bytes=MAX_VALUE_PROJECTION_PATH_BYTES * _MAX_HEADER_COUNT,
            )
            ordered_headers_json = encoded_headers.decode("utf-8")
            ordered_headers_sha256 = _sha256_bytes(encoded_headers)
        ordered_header_slots_json: str | None
        ordered_header_slots_sha256: str | None
        exact_header_slots: tuple[dict[str, object], ...] | None
        if ordered_header_slots is None:
            ordered_header_slots_json = None
            ordered_header_slots_sha256 = None
            exact_header_slots = None
        else:
            exact_header_slots = _validate_header_slots(
                ordered_header_slots,
                header_record_count=header_record_count,
                header_slot_count=header_slot_count,
            )
            encoded_slots = _canonical_json_bytes(
                list(exact_header_slots),
                maximum_bytes=MAX_VALUE_PROJECTION_PATH_BYTES * _MAX_HEADER_COUNT,
            )
            ordered_header_slots_json = encoded_slots.decode("utf-8")
            ordered_header_slots_sha256 = _sha256_bytes(encoded_slots)
        _validate_partition_item_structure(
            items=exact_items,
            partition_kind=partition_kind,
            representation_kind=representation_kind,
            result_name=result_name,
            result_duplicate_ordinal=result_duplicate_ordinal,
            provider_result_ordinal=provider_result_ordinal,
            expected_result_ordinal=expected_result_ordinal,
            canonical_result_ordinal=canonical_result_ordinal,
            result_path=result_path,
            container_kind=container_kind,
            result_presence=result_presence,
            ordered_headers=ordered_headers,
            header_count=header_count,
            ordered_header_slots=exact_header_slots,
            header_record_count=header_record_count,
            header_slot_count=header_slot_count,
            field_count=field_count,
            row_count=row_count,
            cell_count=cell_count,
            node_count=node_count,
        )
        counts = _item_presence_counts(exact_items)
        values: dict[str, object] = {
            "raw_authority_bundle_sha256": raw_authority_bundle_sha256,
            "ownership_partition_sha256": ownership_partition_sha256,
            "observation_record_sha256": observation_record_sha256,
            "observation_sha256": observation_sha256,
            "observation_ordinal": observation_ordinal,
            "partition_ordinal": partition_ordinal,
            "observation_partition_ordinal": observation_partition_ordinal,
            "partition_kind": partition_kind,
            "occurrence_sha256": occurrence_sha256,
            "occurrence_ordinal": occurrence_ordinal,
            "unit_sha256": unit_sha256,
            "unit_ordinal": unit_ordinal,
            "assignment_sha256": assignment_sha256,
            "source_input_kind": source_input_kind,
            "representation_kind": representation_kind,
            "source_record_count": len(exact_items),
            "source_record_root_sha256": _length_framed_root(
                kind=_PARTITION_RECORD_ROOT_KIND,
                raw_authority_bundle_sha256=raw_authority_bundle_sha256,
                item_sha256s=tuple(item.source_record_sha256 for item in exact_items),
                maximum=MAX_VALUE_PROJECTION_ITEMS,
            ),
            "binding_count": len(exact_items),
            "binding_root_sha256": _length_framed_root(
                kind=_PARTITION_BINDING_ROOT_KIND,
                raw_authority_bundle_sha256=raw_authority_bundle_sha256,
                item_sha256s=tuple(item.ownership_binding_sha256 for item in exact_items),
                maximum=MAX_VALUE_PROJECTION_ITEMS,
            ),
            "first_global_item_ordinal": (
                None if not exact_items else exact_items[0].global_item_ordinal
            ),
            "item_count": len(exact_items),
            "item_root_sha256": _length_framed_root(
                kind=_PARTITION_ITEM_ROOT_KIND,
                raw_authority_bundle_sha256=raw_authority_bundle_sha256,
                item_sha256s=tuple(item.item_sha256 for item in exact_items),
                maximum=MAX_VALUE_PROJECTION_ITEMS,
            ),
            "result_name": result_name,
            "result_duplicate_ordinal": result_duplicate_ordinal,
            "provider_result_ordinal": provider_result_ordinal,
            "expected_result_ordinal": expected_result_ordinal,
            "canonical_result_ordinal": canonical_result_ordinal,
            "result_path": result_path,
            "container_kind": container_kind,
            "result_presence": result_presence,
            "ordered_headers_json": ordered_headers_json,
            "ordered_headers_sha256": ordered_headers_sha256,
            "header_count": header_count,
            "ordered_header_slots_json": ordered_header_slots_json,
            "ordered_header_slots_sha256": ordered_header_slots_sha256,
            "header_record_count": header_record_count,
            "header_slot_count": header_slot_count,
            "field_count": field_count,
            "row_count": row_count,
            "cell_count": cell_count,
            "node_count": node_count,
            "record_count": len(exact_items),
            **counts,
            "structural_value_count": sum(
                item.value_state == "structural_container" for item in exact_items
            ),
            "canonical_value_byte_count": sum(
                len(cast("str", item.canonical_json).encode("utf-8"))
                for item in exact_items
                if item.value_state == "canonical"
            ),
            "representation_output_sha256": representation_output_sha256,
            "fixed_zero_landing_sha256": fixed_zero_landing_sha256,
        }
        payload = {"schema_version": cls.schema_version, "kind": cls.kind, **values}
        return cls(partition_sha256=_canonical_sha256(payload), **cast("Any", values))

    def identity_payload(self) -> dict[str, object]:
        return _identity_payload(self, kind=self.kind, digest_field="partition_sha256")

    def to_row(self) -> dict[str, object]:
        return _to_row(self)

    @classmethod
    def from_row(cls, value: object) -> Self:
        row = _strict_dataclass_row(value, cls=cls, label="value-projection partition row")
        try:
            return cls(**cast("Any", {item.name: row[item.name] for item in fields(cls)}))
        except ValueProjectionError:
            raise
        except (TypeError, ValueError, RecursionError):
            _fail("value-projection partition row failed semantic reconstruction")

    def canonical_bytes(self) -> bytes:
        return _canonical_row_bytes(self, maximum_bytes=_MAX_RECEIPT_BYTES)

    @classmethod
    def from_canonical_bytes(cls, value: object) -> Self:
        return cls.from_row(
            _row_from_canonical_bytes(
                value,
                cls=cls,
                label="value-projection partition",
                maximum_bytes=_MAX_RECEIPT_BYTES,
            )
        )


def _item_presence_counts(items: tuple[ValueProjectionItemV1, ...]) -> dict[str, int]:
    mapping = {
        "present": "present_count",
        "null": "null_count",
        "empty_object": "empty_object_count",
        "empty_array": "empty_array_count",
        "missing": "missing_count",
        "mixed_absent": "mixed_absent_count",
        "not_observed_parent_empty": "not_observed_parent_empty_count",
    }
    counts = {field_name: 0 for field_name in mapping.values()}
    counts["absent_count"] = 0
    for item in items:
        if item.value_state == "absent":
            counts["absent_count"] += 1
        else:
            counts[mapping[cast("str", item.presence_kind)]] += 1
    return counts


def _validate_partition_item_structure(
    *,
    items: tuple[ValueProjectionItemV1, ...],
    partition_kind: ValueProjectionUnitKindV1,
    representation_kind: ValueProjectionRepresentationKindV1 | None,
    result_name: str | None,
    result_duplicate_ordinal: int | None,
    provider_result_ordinal: int | None,
    expected_result_ordinal: int | None,
    canonical_result_ordinal: int | None,
    result_path: str | None,
    container_kind: str | None,
    result_presence: str | None,
    ordered_headers: tuple[str, ...] | None,
    header_count: int,
    ordered_header_slots: tuple[dict[str, object], ...] | None,
    header_record_count: int,
    header_slot_count: int,
    field_count: int,
    row_count: int,
    cell_count: int,
    node_count: int,
) -> None:
    live_node_fragment = representation_kind == "live_lossless_nodes_v1" or (
        representation_kind == "response_lossless_records_v1"
        and any(item.record_kind == "node" for item in items)
    )
    if partition_kind != "result_occurrence" and (
        ordered_headers is not None or ordered_header_slots is not None
    ):
        _fail("response projection partition carries a header inventory")
    exact_headers = () if ordered_headers is None else ordered_headers
    exact_header_slots = () if ordered_header_slots is None else ordered_header_slots
    header_duplicate_ordinals: list[int] = []
    header_name_counts: dict[str, int] = {}
    for header in exact_headers:
        duplicate_ordinal = header_name_counts.get(header, 0)
        header_duplicate_ordinals.append(duplicate_ordinal)
        header_name_counts[header] = duplicate_ordinal + 1
    stats_header_duplicate_ordinals: list[int | None] = []
    header_digest_counts: dict[str, int] = {}
    for ordinal, slot in enumerate(exact_header_slots):
        if ordinal >= header_record_count:
            stats_header_duplicate_ordinals.append(None)
            continue
        header_value_sha256 = cast("str", slot["header_value_sha256"])
        duplicate_ordinal = header_digest_counts.get(header_value_sha256, 0)
        stats_header_duplicate_ordinals.append(duplicate_ordinal)
        header_digest_counts[header_value_sha256] = duplicate_ordinal + 1
    header_ordinals: set[int] = set()
    header_record_ordinals: set[int] = set()
    field_ordinals: set[int] = set()
    row_ordinals: set[int] = set()
    cell_ordinals: list[int] = []
    prior_cell_order_key: tuple[int, int, str, int, str] | None = None
    node_ordinals: list[int] = []
    field_names: dict[int, str] = {}
    row_identities: dict[int, tuple[str | None, int | None]] = {}
    node_coordinates: dict[int, dict[str, object]] = {}
    node_items: dict[int, ValueProjectionItemV1] = {}
    node_paths: set[str] = set()
    cell_coordinates: set[tuple[object, ...]] = set()
    live_row_keys: set[tuple[int, int]] = set()
    value_seen: dict[tuple[str, int, str], int] = {}
    result_expected = {
        "result_name": result_name,
        "result_duplicate_ordinal": result_duplicate_ordinal,
        "provider_result_ordinal": provider_result_ordinal,
        "expected_result_ordinal": expected_result_ordinal,
        "canonical_result_ordinal": canonical_result_ordinal,
        "result_path": result_path,
        "container_kind": container_kind,
        "result_presence": result_presence,
    }
    for item in items:
        coordinate = item.coordinate()
        if partition_kind == "result_occurrence":
            if any(coordinate[name] != expected for name, expected in result_expected.items()):
                _fail("projection item result coordinate disagrees with its partition")
        elif any(coordinate[name] is not None for name in _RESULT_COORDINATE_FIELDS):
            _fail("response projection item carries result-level structure")
        allowed = set(_RESULT_COORDINATE_FIELDS) if partition_kind == "result_occurrence" else set()
        required = (
            {name for name, expected in result_expected.items() if expected is not None}
            if partition_kind == "result_occurrence"
            else set()
        )
        if representation_kind == "rectangular_result_cells_v1" and item.record_kind == "cell":
            rectangular_fields = (
                _BASIC_HEADER_COORDINATE_FIELDS | _ROW_COORDINATE_FIELDS | _CELL_COORDINATE_FIELDS
            )
            allowed.update(rectangular_fields)
            required.update(rectangular_fields)
            if item.value_state != "canonical":
                _fail("rectangular projection cell does not carry one canonical value")
        elif representation_kind == "stats_lossless_records_v1":
            allowed_shape = {
                "result_set": set(),
                "missing_expected": set(),
                "raw_headers": set(),
                "raw_rows": set(),
                "header": set(_STATS_HEADER_COORDINATE_FIELDS),
                "row": set(_ROW_COORDINATE_FIELDS),
                "cell": set(
                    _STATS_HEADER_COORDINATE_FIELDS
                    | _ROW_COORDINATE_FIELDS
                    | _CELL_COORDINATE_FIELDS
                ),
            }[item.record_kind]
            required_shape = {
                "result_set": set(),
                "missing_expected": set(),
                "raw_headers": set(),
                "raw_rows": set(),
                "header": {"header_reference_kind", "header_ordinal"},
                "row": set(_ROW_COORDINATE_FIELDS),
                "cell": {
                    "header_reference_kind",
                    "header_ordinal",
                    *_ROW_COORDINATE_FIELDS,
                    *_CELL_COORDINATE_FIELDS,
                },
            }[item.record_kind]
            allowed.update(allowed_shape)
            required.update(required_shape)
        elif representation_kind == "live_lossless_nodes_v1":
            if item.record_kind == "result_declaration":
                allowed.update(_LIVE_DECLARATION_COORDINATE_FIELDS)
                if item.value_state != "absent":
                    _fail("live result declaration carries value material")
            elif item.record_kind == "result_occurrence":
                allowed.update(_LIVE_OCCURRENCE_COORDINATE_FIELDS)
                required.update(
                    _LIVE_OCCURRENCE_COORDINATE_FIELDS
                    - {
                        "result_occurrence_parent_result_name",
                        "result_occurrence_parent_result_ordinal",
                    }
                )
                if item.value_state != "absent":
                    _fail("live result occurrence carries duplicate value material")
            elif item.record_kind == "node":
                allowed.update(
                    _NODE_COORDINATE_FIELDS
                    | _LIVE_NODE_CONTEXT_COORDINATE_FIELDS
                    | {
                        "row_ordinal",
                        "decoder_value_sha256",
                        "matches_result_occurrence",
                    }
                )
                required.update(
                    {
                        "node_ordinal",
                        "json_path",
                        "depth",
                        "context_result_name",
                        "context_result_ordinal",
                        "context_result_occurrence",
                        "decoder_value_sha256",
                        "matches_result_occurrence",
                    }
                )
                if item.value_state not in {"canonical", "structural_container", "missing"}:
                    _fail("live node projection has an invalid exact value state")
            else:
                allowed.update(
                    _FIELD_COORDINATE_FIELDS
                    | _CELL_COORDINATE_FIELDS
                    | _LIVE_CONTEXT_COORDINATE_FIELDS
                    | {"node_ordinal", "row_ordinal", "json_path", "decoder_value_sha256"}
                )
                required.update(
                    {
                        "field_name",
                        "field_ordinal",
                        "cell_ordinal",
                        "value_duplicate_ordinal",
                        "node_ordinal",
                        "row_ordinal",
                        "json_path",
                        "decoder_value_sha256",
                        *_LIVE_FIELD_REQUIRED_COORDINATE_FIELDS,
                    }
                )
                if item.value_state not in {"canonical", "structural_container", "missing"}:
                    _fail("live field projection has an invalid value state")
        elif representation_kind == "response_lossless_records_v1":
            if item.record_kind == "response":
                if item.value_state != "absent":
                    _fail("response marker projection carries value material")
            else:
                allowed.update(_NODE_COORDINATE_FIELDS | _LIVE_CONTEXT_COORDINATE_FIELDS)
                required.update({"node_ordinal", "json_path", "depth"})
                if item.value_state not in {"canonical", "structural_container"}:
                    _fail("response node projection does not carry one canonical value")
        else:
            _fail("projection item has no compatible structural representation")
        nonnull = {name for name, value in coordinate.items() if value is not None}
        if not required <= nonnull or not nonnull <= allowed:
            _fail("projection item coordinate shape is incomplete or additive")
        if coordinate["json_path"] is not None:
            _canonical_json_path_tokens(coordinate["json_path"])
        if coordinate["parent_json_path"] is not None:
            _canonical_json_path_tokens(coordinate["parent_json_path"])

        header_ordinal = cast("int | None", coordinate["header_ordinal"])
        if header_ordinal is not None:
            if representation_kind == "stats_lossless_records_v1":
                if header_ordinal >= header_slot_count:
                    _fail("stats projection header coordinate is outside its slot inventory")
                slot = exact_header_slots[header_ordinal]
                if (
                    coordinate["header_reference_kind"] != slot["header_reference_kind"]
                    or coordinate["header_name"] != slot["header_name"]
                    or coordinate["header_value_sha256"] != slot["header_value_sha256"]
                    or coordinate["header_duplicate_ordinal"]
                    != stats_header_duplicate_ordinals[header_ordinal]
                ):
                    _fail("stats projection header coordinate differs from its exact slot")
                if item.record_kind == "header":
                    if header_ordinal >= header_record_count:
                        _fail("stats projection fabricates an out-of-range header record")
                    if (
                        item.value_state != "canonical"
                        or item.canonical_json_sha256 != slot["header_value_sha256"]
                        or (
                            slot["header_reference_kind"] == "named" and item.value_kind != "string"
                        )
                        or (
                            slot["header_reference_kind"] == "non_string"
                            and item.value_kind == "string"
                        )
                    ):
                        _fail("stats projection header record differs from its exact value")
                    header_record_ordinals.add(header_ordinal)
            else:
                if header_ordinal >= header_count:
                    _fail("projection header coordinate is outside its declared inventory")
                if (
                    coordinate["header_name"] != exact_headers[header_ordinal]
                    or coordinate["header_duplicate_ordinal"]
                    != header_duplicate_ordinals[header_ordinal]
                ):
                    _fail("projection header coordinate differs from its ordered headers")
            header_ordinals.add(header_ordinal)

        field_ordinal = cast("int | None", coordinate["field_ordinal"])
        if field_ordinal is not None:
            field_name = cast("str", coordinate["field_name"])
            if field_ordinal >= field_count:
                _fail("projection field coordinate is outside its declared inventory")
            if representation_kind == "live_lossless_nodes_v1":
                if field_ordinal >= header_count or exact_headers[field_ordinal] != field_name:
                    _fail("live projection field differs from its ordered headers")
                header_ordinals.add(field_ordinal)
            prior_field_name = field_names.setdefault(field_ordinal, field_name)
            if prior_field_name != field_name:
                _fail("projection field ordinal changes its declared name")
            field_ordinals.add(field_ordinal)

        row_ordinal = cast("int | None", coordinate["row_ordinal"])
        if row_ordinal is not None:
            if row_ordinal >= row_count:
                _fail("projection row coordinate is outside its declared inventory")
            row_sha256 = cast("str | None", coordinate["row_value_sha256"])
            row_duplicate = cast("int | None", coordinate["row_duplicate_ordinal"])
            if representation_kind in {
                "rectangular_result_cells_v1",
                "stats_lossless_records_v1",
            } and (row_sha256 is None or row_duplicate is None):
                _fail("projection row coordinate lacks its exact duplicate identity")
            if representation_kind == "live_lossless_nodes_v1" and (
                row_sha256 is not None or row_duplicate is not None
            ):
                _fail("live projection row coordinate fabricates a row digest")
            if representation_kind == "live_lossless_nodes_v1":
                context_occurrence = (
                    coordinate["owner_result_occurrence"]
                    if item.record_kind == "field_cell"
                    else coordinate["context_result_occurrence"]
                )
                if type(context_occurrence) is not int:
                    _fail("live projection row lacks one exact result occurrence")
                live_row_keys.add((context_occurrence, row_ordinal))
            else:
                prior_row = row_identities.setdefault(row_ordinal, (row_sha256, row_duplicate))
                if prior_row != (row_sha256, row_duplicate):
                    _fail("projection row ordinal changes its exact row identity")
                row_ordinals.add(row_ordinal)

        cell_ordinal = cast("int | None", coordinate["cell_ordinal"])
        if cell_ordinal is not None:
            if cell_ordinal >= cell_count:
                _fail("projection cell coordinate is outside its declared inventory")
            selector_kind = "header" if header_ordinal is not None else "field"
            selector_ordinal = header_ordinal if header_ordinal is not None else field_ordinal
            if selector_ordinal is None:
                _fail("projection cell coordinate lacks a header or field owner")
            identity = (
                coordinate["owner_result_occurrence"],
                row_ordinal,
                selector_kind,
                selector_ordinal,
                coordinate["json_path"],
            )
            if identity in cell_coordinates:
                _fail("projection cell coordinate inventory contains a duplicate")
            cell_coordinates.add(identity)
            cell_ordinals.append(cell_ordinal)
            cell_order_key = (
                -1
                if coordinate["owner_result_occurrence"] is None
                else cast("int", coordinate["owner_result_occurrence"]),
                -1 if row_ordinal is None else row_ordinal,
                selector_kind,
                selector_ordinal,
                "" if coordinate["json_path"] is None else cast("str", coordinate["json_path"]),
            )
            if prior_cell_order_key is not None and cell_order_key < prior_cell_order_key:
                _fail("projection cell coordinates are not in canonical structural order")
            prior_cell_order_key = cell_order_key
            if representation_kind == "rectangular_result_cells_v1" and cell_ordinal != (
                cast("int", row_ordinal) * header_count + cast("int", header_ordinal)
            ):
                _fail("rectangular projection cell order is not canonical row-major order")
            value_identity = (
                item.canonical_json_sha256
                if item.value_state == "canonical"
                else f"{item.value_state}:{item.presence_kind}"
            )
            duplicate_key = (selector_kind, selector_ordinal, cast("str", value_identity))
            expected_value_duplicate = value_seen.get(duplicate_key, 0)
            if coordinate["value_duplicate_ordinal"] != expected_value_duplicate:
                _fail("projection value duplicate ordinal is not canonical")
            value_seen[duplicate_key] = expected_value_duplicate + 1

        if item.record_kind in {"node", "json_node"}:
            node_ordinal = cast("int", coordinate["node_ordinal"])
            json_path = cast("str", coordinate["json_path"])
            if node_ordinal in node_coordinates or json_path in node_paths:
                _fail("projection node ordinal or path inventory contains a duplicate")
            node_coordinates[node_ordinal] = coordinate
            node_items[node_ordinal] = item
            node_paths.add(json_path)
            node_ordinals.append(node_ordinal)
        elif (
            coordinate["node_ordinal"] is not None
            and not live_node_fragment
            and cast("int", coordinate["node_ordinal"]) >= node_count
        ):
            _fail("projection node reference is outside its declared inventory")
    expected_cells = sum(item.record_kind in {"cell", "field_cell"} for item in items)
    expected_nodes = sum(item.record_kind in {"node", "json_node"} for item in items)
    if cell_count != expected_cells or node_count != expected_nodes:
        _fail("projection structural cell/node counts differ from exact record kinds")
    if representation_kind == "stats_lossless_records_v1":
        if header_ordinals != set(range(header_slot_count)):
            _fail("stats projection header-slot coordinate inventory is incomplete or gapped")
        if header_record_ordinals != set(range(header_record_count)):
            _fail("stats projection header-record inventory is incomplete or gapped")
    elif header_ordinals != set(range(header_count)) and not (
        representation_kind == "rectangular_result_cells_v1" and row_count == 0 and not items
    ):
        _fail("projection header coordinate inventory is incomplete or gapped")
    for inventory, count, label in ((field_ordinals, field_count, "field"),):
        if inventory != set(range(count)):
            _fail(f"projection {label} coordinate inventory is incomplete or gapped")
    if representation_kind == "live_lossless_nodes_v1":
        if len(live_row_keys) != row_count:
            _fail("live projection row occurrence inventory differs from its denominator")
        rows_by_occurrence: dict[int, set[int]] = {}
        for context_occurrence, row_ordinal in live_row_keys:
            rows_by_occurrence.setdefault(context_occurrence, set()).add(row_ordinal)
        if any(rows != set(range(len(rows))) for rows in rows_by_occurrence.values()):
            _fail("live projection row ordinals are not locally contiguous")
    elif row_ordinals != set(range(row_count)):
        _fail("projection row coordinate inventory is incomplete or gapped")
    if cell_ordinals != list(range(cell_count)):
        _fail("projection cell coordinate order is not canonical and contiguous")
    if not live_node_fragment and node_ordinals != list(range(node_count)):
        _fail("projection node coordinate order is not canonical and contiguous")
    if live_node_fragment:
        return
    seen_row_sha256s: dict[str, int] = {}
    for row_ordinal in range(row_count):
        row_sha256, row_duplicate = row_identities[row_ordinal]
        if row_sha256 is None:
            continue
        expected_duplicate = seen_row_sha256s.get(row_sha256, 0)
        if row_duplicate != expected_duplicate:
            _fail("projection row duplicate ordinal is not canonical")
        seen_row_sha256s[row_sha256] = expected_duplicate + 1
    root_node_count = 0
    child_edge_kinds: dict[int, str] = {}
    child_edge_ordinals: dict[tuple[int, str], int] = {}
    child_object_keys: dict[int, set[str]] = {}
    missing_sidecar_started: set[int] = set()
    node_children: dict[int, list[tuple[ValueProjectionItemV1, dict[str, object]]]] = {}
    for node_ordinal in range(node_count):
        coordinate = node_coordinates[node_ordinal]
        node_item = node_items[node_ordinal]
        parent_ordinal = cast("int | None", coordinate["parent_node_ordinal"])
        depth = cast("int", coordinate["depth"])
        if parent_ordinal is None:
            root_node_count += 1
            if (
                depth != 0
                or coordinate["json_path"] != "$"
                or coordinate["parent_json_path"] is not None
                or coordinate["object_key"] is not None
                or coordinate["object_key_ordinal"] is not None
                or coordinate["array_ordinal"] is not None
            ):
                _fail("projection root node coordinate is inconsistent")
            if representation_kind == "live_lossless_nodes_v1" and (
                coordinate["context_result_name"],
                coordinate["context_result_ordinal"],
                coordinate["context_result_occurrence"],
            ) != (result_name, canonical_result_ordinal, node_item.occurrence_ordinal):
                _fail("live projection root node differs from its exact result context")
            continue
        if parent_ordinal >= node_ordinal or parent_ordinal not in node_coordinates:
            _fail("projection node parent ordinal is foreign or reordered")
        parent = node_coordinates[parent_ordinal]
        if (
            coordinate["parent_json_path"] != parent["json_path"]
            or depth != cast("int", parent["depth"]) + 1
        ):
            _fail("projection node path/depth differs from its parent")
        live_missing_sidecar = (
            representation_kind == "live_lossless_nodes_v1" and node_item.value_state == "missing"
        )
        object_edge = coordinate["object_key"] is not None
        if live_missing_sidecar:
            if (
                not object_edge
                or coordinate["object_key_ordinal"] is not None
                or coordinate["array_ordinal"] is not None
            ):
                _fail("live missing node sidecar has an invalid exact object edge")
        elif object_edge != (coordinate["object_key_ordinal"] is not None) or object_edge == (
            coordinate["array_ordinal"] is not None
        ):
            _fail("projection node object/array edge identity is invalid")
        edge_kind = "object" if object_edge else "array"
        parent_item = node_items[parent_ordinal]
        if live_missing_sidecar:
            if parent_item.value_kind != "object" or parent_item.value_state not in {
                "canonical",
                "structural_container",
            }:
                _fail("live missing node sidecar contradicts its exact object parent")
            missing_sidecar_started.add(parent_ordinal)
        elif (
            parent_item.value_state != "structural_container"
            or parent_item.presence_kind != "present"
            or parent_item.value_kind != edge_kind
        ):
            _fail("projection node edge contradicts its exact parent container")
        elif parent_ordinal in missing_sidecar_started:
            _fail("materialized live node follows a missing field sidecar")
        if child_edge_kinds.setdefault(parent_ordinal, edge_kind) != edge_kind:
            _fail("projection node parent mixes object and array child edges")
        if object_edge:
            object_key = cast("str", coordinate["object_key"])
            if object_key in child_object_keys.setdefault(parent_ordinal, set()):
                _fail("projection node parent repeats one object child key")
            child_object_keys[parent_ordinal].add(object_key)
        if not live_missing_sidecar:
            edge_ordinal = cast(
                "int",
                coordinate["object_key_ordinal"] if object_edge else coordinate["array_ordinal"],
            )
            edge_key = (parent_ordinal, edge_kind)
            if edge_ordinal != child_edge_ordinals.get(edge_key, 0):
                _fail("projection node sibling order is not canonical and contiguous")
            child_edge_ordinals[edge_key] = edge_ordinal + 1
        json_path = cast("str", coordinate["json_path"])
        parent_path = cast("str", coordinate["parent_json_path"])
        expected_path = _json_path_child(
            parent_path,
            object_key=coordinate["object_key"],
            array_ordinal=coordinate["array_ordinal"],
        )
        if json_path != expected_path:
            _fail("projection node path differs from its exact parent edge")
        if not live_missing_sidecar:
            node_children.setdefault(parent_ordinal, []).append((node_item, coordinate))
    if node_count and root_node_count != 1:
        _fail("projection node inventory does not contain exactly one root")
    live_field_nodes: set[int] = set()
    for item in items:
        if item.record_kind != "field_cell":
            continue
        coordinate = item.coordinate()
        node_ordinal = cast("int", coordinate["node_ordinal"])
        if node_ordinal in live_field_nodes:
            _fail("live projection field inventory reuses one exact value node")
        live_field_nodes.add(node_ordinal)
        node = node_coordinates[node_ordinal]
        node_item = node_items[node_ordinal]
        parent_ordinal = cast("int | None", node["parent_node_ordinal"])
        if parent_ordinal is None:
            _fail("live projection field value node has no exact owner parent")
        parent = node_coordinates[parent_ordinal]
        parent_item = node_items[parent_ordinal]
        json_path = cast("str", coordinate["json_path"])
        field_context = (
            coordinate["context_result_name"],
            coordinate["context_result_ordinal"],
            coordinate["context_result_occurrence"],
        )
        node_context = (
            node["context_result_name"],
            node["context_result_ordinal"],
            node["context_result_occurrence"],
        )
        owner_context = (
            coordinate["owner_result_name"],
            coordinate["owner_result_ordinal"],
            coordinate["owner_result_occurrence"],
        )
        parent_context = (
            parent["context_result_name"],
            parent["context_result_ordinal"],
            parent["context_result_occurrence"],
        )
        expected_owner_row = (
            parent["row_ordinal"] if parent["row_ordinal"] is not None else node["row_ordinal"]
        )
        if (
            json_path != node["json_path"]
            or field_context != node_context
            or owner_context != parent_context
            or owner_context != (result_name, canonical_result_ordinal, item.occurrence_ordinal)
            or coordinate["row_ordinal"] != expected_owner_row
            or item.value_state != node_item.value_state
            or item.presence_kind != node_item.presence_kind
            or item.value_kind != node_item.value_kind
            or item.canonical_json != node_item.canonical_json
            or item.canonical_json_sha256 != node_item.canonical_json_sha256
            or coordinate["decoder_value_sha256"] != node["decoder_value_sha256"]
        ):
            _fail("live projection field differs from its exact value node or owner context")
        if coordinate["known_contract_field"] is not True:
            _fail("live projection field is not one exact declared contract field")
        object_field = node["object_key"] is not None
        scalar_field = node["array_ordinal"] is not None
        if object_field:
            if (
                node["object_key"] != coordinate["field_name"]
                or node["known_contract_field"] is not True
                or parent_item.value_kind != "object"
            ):
                _fail("live projection object field differs from its exact node edge")
        elif scalar_field:
            if (
                coordinate["field_name"] != "value"
                or coordinate["field_ordinal"] != 0
                or node["known_contract_field"] is not None
                or parent_item.value_kind != "array"
                or parent_item.value_state != "structural_container"
            ):
                _fail("live scalar projection field differs from its exact array edge")
        else:
            _fail("live projection field value node has no object or scalar array edge")

    reconstructed: list[object] = [None] * node_count
    for node_ordinal in range(node_count - 1, -1, -1):
        node_item = node_items[node_ordinal]
        children = node_children.get(node_ordinal, [])
        has_children = bool(children)
        structural = node_item.value_state == "structural_container"
        if structural != has_children:
            _fail("projection structural-container state differs from its exact children")
        if not structural:
            if node_item.value_state == "missing":
                reconstructed[node_ordinal] = None
                continue
            if (
                node_item.value_state == "canonical"
                and node_item.presence_kind == "present"
                and node_item.value_kind in {"array", "object"}
            ):
                _fail("nonempty projection node is not structurally materialized")
            reconstructed[node_ordinal] = node_item.value()
            continue
        if node_item.value_kind == "array":
            reconstructed[node_ordinal] = [
                reconstructed[cast("int", child_coordinate["node_ordinal"])]
                for _child, child_coordinate in children
            ]
            continue
        object_value: dict[str, object] = {}
        for _child, child_coordinate in children:
            key = cast("str", child_coordinate["object_key"])
            if key in object_value:
                _fail("projection structural object repeats one child key")
            object_value[key] = reconstructed[cast("int", child_coordinate["node_ordinal"])]
        reconstructed[node_ordinal] = object_value
    if reconstructed:
        _canonical_json_bytes(
            reconstructed[0],
            maximum_bytes=MAX_VALUE_PROJECTION_TOTAL_CANONICAL_BYTES,
        )


def _live_node_source_item_sha256(
    *,
    item: ValueProjectionItemV1,
    coordinate: dict[str, object],
    partition: ValueProjectionPartitionV1,
    contract_field_ordinal: int | None,
) -> str:
    """Rebuild the exact independent-decoder node identity owned by Raw-v2."""

    return _canonical_sha256(
        {
            "array_ordinal": coordinate["array_ordinal"],
            "canonical_json": item.canonical_json,
            "container_kind": (
                partition.container_kind
                if coordinate["matches_result_occurrence"] is True
                else None
            ),
            "contract_field_ordinal": contract_field_ordinal,
            "contract_json_path": partition.result_path,
            "depth": coordinate["depth"],
            "json_path": coordinate["json_path"],
            "known_contract_field": coordinate["known_contract_field"],
            "node_ordinal": coordinate["node_ordinal"],
            "object_key": coordinate["object_key"],
            "object_key_ordinal": coordinate["object_key_ordinal"],
            "parent_json_path": coordinate["parent_json_path"],
            "parent_node_ordinal": coordinate["parent_node_ordinal"],
            "presence_kind": item.presence_kind,
            "result_set_name": coordinate["context_result_name"],
            "result_set_occurrence": coordinate["context_result_occurrence"],
            "result_set_ordinal": coordinate["context_result_ordinal"],
            "result_set_row_ordinal": coordinate["row_ordinal"],
            "value_kind": item.value_kind,
            "value_sha256": coordinate["decoder_value_sha256"],
        },
        maximum_bytes=_MAX_ROW_BYTES,
    )


def _validate_live_observation_structure(
    *,
    items: tuple[ValueProjectionItemV1, ...],
    partitions: tuple[ValueProjectionPartitionV1, ...],
) -> None:
    live_partitions = {
        partition.partition_ordinal: partition
        for partition in partitions
        if partition.representation_kind == "live_lossless_nodes_v1"
    }
    if not live_partitions:
        return
    partition_by_ordinal = {partition.partition_ordinal: partition for partition in partitions}
    node_coordinates: dict[int, dict[str, object]] = {}
    node_items: dict[int, ValueProjectionItemV1] = {}
    node_paths: set[str] = set()
    node_ordinals: list[int] = []
    declaration_coordinates: dict[int, dict[str, object]] = {}
    occurrence_coordinates: list[tuple[ValueProjectionItemV1, dict[str, object]]] = []
    occurrence_global_ordinals: set[int] = set()
    occurrence_nodes: set[int] = set()
    occurrence_root_nodes: dict[tuple[int, int], int] = {}
    field_items: list[ValueProjectionItemV1] = []
    for item in items:
        if item.record_kind == "result_declaration":
            if item.partition_ordinal not in live_partitions:
                _fail("live result declaration belongs to a foreign representation partition")
            if item.partition_ordinal in declaration_coordinates:
                _fail("live result partition repeats its exact declaration")
            declaration_coordinates[item.partition_ordinal] = item.coordinate()
            continue
        if item.record_kind == "result_occurrence":
            if item.partition_ordinal not in live_partitions:
                _fail("live result occurrence belongs to a foreign representation partition")
            coordinate = item.coordinate()
            global_ordinal = cast("int", coordinate["result_occurrence_global_ordinal"])
            node_ordinal = cast("int", coordinate["node_ordinal"])
            if global_ordinal in occurrence_global_ordinals or node_ordinal in occurrence_nodes:
                _fail("live result occurrence repeats one global ordinal or node owner")
            occurrence_global_ordinals.add(global_ordinal)
            occurrence_nodes.add(node_ordinal)
            occurrence_coordinates.append((item, coordinate))
            continue
        if item.record_kind == "field_cell":
            field_items.append(item)
            continue
        if item.record_kind != "node":
            continue
        coordinate = item.coordinate()
        node_ordinal = cast("int", coordinate["node_ordinal"])
        json_path = cast("str", coordinate["json_path"])
        if node_ordinal in node_coordinates or json_path in node_paths:
            _fail("live observation repeats one exact node ordinal or path")
        node_coordinates[node_ordinal] = coordinate
        node_items[node_ordinal] = item
        node_paths.add(json_path)
        node_ordinals.append(node_ordinal)
        context = (
            coordinate["context_result_name"],
            coordinate["context_result_ordinal"],
            coordinate["context_result_occurrence"],
        )
        if any(value is None for value in context) != all(value is None for value in context):
            _fail("live observation node result context is partial")
        partition = partition_by_ordinal[item.partition_ordinal]
        if item.representation_kind == "live_lossless_nodes_v1":
            expected_context = (partition.result_name, partition.canonical_result_ordinal)
            if context[:2] != expected_context or type(context[2]) is not int:
                _fail("live observation node differs from its exact ownership result")
            occurrence_root_nodes.setdefault(
                (item.partition_ordinal, context[2]),
                node_ordinal,
            )
        elif item.representation_kind == "response_lossless_records_v1":
            if (
                any(value is not None for value in context)
                or any(
                    coordinate[field_name] is not None
                    for field_name in _LIVE_NODE_CONTEXT_COORDINATE_FIELDS
                )
                or coordinate["row_ordinal"] is not None
            ):
                _fail("live response-residual node fabricates one result context")
        else:
            _fail("live observation node uses a foreign representation")
    if node_ordinals != list(range(len(node_ordinals))):
        _fail("live observation node order is not globally canonical and contiguous")
    if set(declaration_coordinates) != set(live_partitions):
        _fail("live result partitions differ from their exact declaration inventory")
    if occurrence_global_ordinals != set(range(len(occurrence_coordinates))):
        _fail("live result global occurrence inventory is incomplete or gapped")

    declarations_by_name: dict[str, tuple[ValueProjectionPartitionV1, dict[str, object]]] = {}
    declarations_by_ordinal: set[int] = set()
    for partition_ordinal, coordinate in declaration_coordinates.items():
        partition = live_partitions[partition_ordinal]
        name = cast("str", partition.result_name)
        ordinal = cast("int", partition.canonical_result_ordinal)
        if name in declarations_by_name or ordinal in declarations_by_ordinal:
            _fail("live result declaration name or ordinal is duplicated")
        parent_name = coordinate["declaration_parent_result_name"]
        parent_field = coordinate["declaration_parent_field_name"]
        if (parent_name is None) != (parent_field is None):
            _fail("live result declaration parent identity is partial")
        declarations_by_name[name] = (partition, coordinate)
        declarations_by_ordinal.add(ordinal)
    for _partition, coordinate in declarations_by_name.values():
        parent_name = cast("str | None", coordinate["declaration_parent_result_name"])
        if parent_name is None:
            continue
        parent = declarations_by_name.get(parent_name)
        if parent is None:
            _fail("live result declaration names a foreign parent result")
        parent_partition = parent[0]
        _canonical_headers, decoded_headers = _decode_canonical_json(
            cast("str", parent_partition.ordered_headers_json),
            maximum_bytes=MAX_VALUE_PROJECTION_PATH_BYTES * _MAX_HEADER_COUNT,
        )
        if coordinate["declaration_parent_field_name"] not in cast("list[str]", decoded_headers):
            _fail("live result declaration parent field is not declared by its parent")
    if not node_items:
        if field_items or occurrence_coordinates:
            _fail("live observation values have no exact node inventory")
        return

    contract_field_ordinal_by_node: dict[int, int] = {}
    for field_item in field_items:
        field_coordinate = field_item.coordinate()
        field_node_ordinal = cast("int", field_coordinate["node_ordinal"])
        field_ordinal = cast("int", field_coordinate["field_ordinal"])
        if field_node_ordinal in contract_field_ordinal_by_node:
            _fail("live projection field inventory reuses one exact value node")
        contract_field_ordinal_by_node[field_node_ordinal] = field_ordinal

    root_node_count = 0
    child_edge_kinds: dict[int, str] = {}
    child_edge_ordinals: dict[tuple[int, str], int] = {}
    child_object_keys: dict[int, set[str]] = {}
    missing_sidecar_started: set[int] = set()
    node_children: dict[int, list[tuple[ValueProjectionItemV1, dict[str, object]]]] = {}
    for node_ordinal in range(len(node_items)):
        coordinate = node_coordinates[node_ordinal]
        node_item = node_items[node_ordinal]
        parent_ordinal = cast("int | None", coordinate["parent_node_ordinal"])
        depth = cast("int", coordinate["depth"])
        if parent_ordinal is None:
            root_node_count += 1
            if (
                depth != 0
                or coordinate["json_path"] != "$"
                or coordinate["parent_json_path"] is not None
                or coordinate["object_key"] is not None
                or coordinate["object_key_ordinal"] is not None
                or coordinate["array_ordinal"] is not None
            ):
                _fail("live observation root node coordinate is inconsistent")
            if (
                node_item.representation_kind == "live_lossless_nodes_v1"
                and node_ordinal not in occurrence_nodes
            ):
                _fail("live non-occurrence-root node has no exact parent")
            continue
        if parent_ordinal >= node_ordinal or parent_ordinal not in node_coordinates:
            _fail("live observation node parent is foreign or reordered")
        parent = node_coordinates[parent_ordinal]
        parent_item = node_items[parent_ordinal]
        if (
            coordinate["parent_json_path"] != parent["json_path"]
            or depth != cast("int", parent["depth"]) + 1
        ):
            _fail("live observation node path or depth differs from its parent")
        if node_item.representation_kind == "live_lossless_nodes_v1" and (
            node_ordinal not in occurrence_nodes
            and (
                parent_item.representation_kind != "live_lossless_nodes_v1"
                or parent_item.partition_ordinal != node_item.partition_ordinal
                or parent_item.occurrence_sha256 != node_item.occurrence_sha256
                or parent_item.occurrence_ordinal != node_item.occurrence_ordinal
                or any(
                    parent[field_name] != coordinate[field_name]
                    for field_name in (
                        "result_name",
                        "provider_result_ordinal",
                        "expected_result_ordinal",
                        "canonical_result_ordinal",
                        "context_result_name",
                        "context_result_ordinal",
                        "context_result_occurrence",
                    )
                )
            )
        ):
            _fail("live non-occurrence-root node does not inherit its exact parent context")
        missing_sidecar = node_item.value_state == "missing"
        object_edge = coordinate["object_key"] is not None
        if missing_sidecar:
            if (
                not object_edge
                or coordinate["object_key_ordinal"] is not None
                or coordinate["array_ordinal"] is not None
            ):
                _fail("live missing node sidecar has an invalid exact object edge")
        elif object_edge != (coordinate["object_key_ordinal"] is not None) or object_edge == (
            coordinate["array_ordinal"] is not None
        ):
            _fail("live observation node object or array edge identity is invalid")
        edge_kind = "object" if object_edge else "array"
        if missing_sidecar:
            if parent_item.value_kind != "object" or parent_item.value_state not in {
                "canonical",
                "structural_container",
            }:
                _fail("live missing node sidecar contradicts its exact object parent")
            missing_sidecar_started.add(parent_ordinal)
        elif (
            parent_item.value_state != "structural_container"
            or parent_item.presence_kind != "present"
            or parent_item.value_kind != edge_kind
        ):
            _fail("live observation node edge contradicts its exact parent container")
        elif parent_ordinal in missing_sidecar_started:
            _fail("materialized live node follows a missing field sidecar")
        if child_edge_kinds.setdefault(parent_ordinal, edge_kind) != edge_kind:
            _fail("live observation node parent mixes object and array edges")
        if object_edge:
            object_key = cast("str", coordinate["object_key"])
            if object_key in child_object_keys.setdefault(parent_ordinal, set()):
                _fail("live observation node parent repeats one object key")
            child_object_keys[parent_ordinal].add(object_key)
        if not missing_sidecar:
            edge_ordinal = cast(
                "int",
                coordinate["object_key_ordinal"] if object_edge else coordinate["array_ordinal"],
            )
            edge_key = (parent_ordinal, edge_kind)
            if edge_ordinal != child_edge_ordinals.get(edge_key, 0):
                _fail("live observation node sibling order is not contiguous")
            child_edge_ordinals[edge_key] = edge_ordinal + 1
        expected_path = _json_path_child(
            cast("str", coordinate["parent_json_path"]),
            object_key=coordinate["object_key"],
            array_ordinal=coordinate["array_ordinal"],
        )
        if coordinate["json_path"] != expected_path:
            _fail("live observation node path differs from its exact parent edge")
        if not missing_sidecar:
            node_children.setdefault(parent_ordinal, []).append((node_item, coordinate))
    if root_node_count != 1:
        _fail("live observation does not contain exactly one response root node")

    if declarations_by_ordinal != set(range(len(live_partitions))):
        _fail("live result declaration ordinals are incomplete or gapped")
    occurrences_by_partition: dict[int, dict[int, dict[str, object]]] = {
        partition_ordinal: {} for partition_ordinal in live_partitions
    }
    occurrence_coordinate_by_node: dict[int, dict[str, object]] = {}
    for item, coordinate in occurrence_coordinates:
        partition = live_partitions[item.partition_ordinal]
        occurrence_ordinal = cast("int", coordinate["result_occurrence_ordinal"])
        partition_occurrences = occurrences_by_partition[item.partition_ordinal]
        if occurrence_ordinal in partition_occurrences:
            _fail("live result repeats one concrete occurrence ordinal")
        partition_occurrences[occurrence_ordinal] = coordinate
        parent_name = coordinate["result_occurrence_parent_result_name"]
        parent_ordinal = coordinate["result_occurrence_parent_result_ordinal"]
        if (parent_name is None) != (parent_ordinal is None):
            _fail("live result occurrence parent identity is partial")
        declaration = declaration_coordinates[item.partition_ordinal]
        expected_parent_name = declaration["declaration_parent_result_name"]
        expected_parent_ordinal = (
            None
            if expected_parent_name is None
            else declarations_by_name[cast("str", expected_parent_name)][0].canonical_result_ordinal
        )
        if (parent_name, parent_ordinal) != (expected_parent_name, expected_parent_ordinal):
            _fail("live result occurrence differs from its exact declaration parent")
        node_ordinal = cast("int", coordinate["node_ordinal"])
        node = node_coordinates.get(node_ordinal)
        node_item = node_items.get(node_ordinal)
        if (
            node is None
            or node_item is None
            or node_item.partition_ordinal != item.partition_ordinal
        ):
            _fail("live result occurrence references a foreign or cross-partition node")
        if occurrence_root_nodes.get((item.partition_ordinal, occurrence_ordinal)) != node_ordinal:
            _fail("live result occurrence does not select its exact context root node")
        parent_node_ordinal = cast("int | None", node["parent_node_ordinal"])
        actual_parent_name: str | None = None
        actual_parent_ordinal: int | None = None
        actual_parent_field: str | None = None
        if parent_node_ordinal is not None:
            parent_node = node_coordinates[parent_node_ordinal]
            parent_context_name = cast("str | None", parent_node["context_result_name"])
            if parent_context_name is not None and parent_context_name != partition.result_name:
                actual_parent_name = parent_context_name
                actual_parent_ordinal = cast("int", parent_node["context_result_ordinal"])
                actual_parent_field = cast("str | None", node["object_key"])
        if (
            actual_parent_name,
            actual_parent_ordinal,
            actual_parent_field,
        ) != (
            expected_parent_name,
            expected_parent_ordinal,
            declaration["declaration_parent_field_name"],
        ):
            _fail("live result occurrence differs from its exact declaration parent edge")
        expected_context = (
            partition.result_name,
            partition.canonical_result_ordinal,
            occurrence_ordinal,
        )
        node_context = (
            node["context_result_name"],
            node["context_result_ordinal"],
            node["context_result_occurrence"],
        )
        if (
            coordinate["json_path"] != node["json_path"]
            or node_context != expected_context
            or coordinate["result_occurrence_presence_kind"] != node_item.presence_kind
            or coordinate["decoder_value_sha256"] != node["decoder_value_sha256"]
            or node["matches_result_occurrence"] is not True
        ):
            _fail("live result occurrence differs from its exact value node")
        occurrence_presence = cast("str", coordinate["result_occurrence_presence_kind"])
        occurrence_row_count = cast("int", coordinate["result_occurrence_row_count"])
        expected_value_kind = (
            occurrence_presence
            if occurrence_presence in {"missing", "null"}
            else "array"
            if partition.container_kind == "nba_api_live_json_array"
            else "object"
        )
        if node_item.value_kind != expected_value_kind:
            _fail("live result occurrence container differs from its exact value node")
        if (
            (occurrence_presence in {"missing", "null"} and occurrence_row_count != 0)
            or (
                occurrence_presence == "empty_array"
                and (
                    partition.container_kind != "nba_api_live_json_array"
                    or occurrence_row_count != 0
                )
            )
            or (
                occurrence_presence == "empty_object"
                and (
                    partition.container_kind != "nba_api_live_json_object"
                    or occurrence_row_count != 1
                )
            )
            or (
                occurrence_presence == "present"
                and (
                    (
                        partition.container_kind == "nba_api_live_json_array"
                        and occurrence_row_count == 0
                    )
                    or (
                        partition.container_kind == "nba_api_live_json_object"
                        and occurrence_row_count != 1
                    )
                )
            )
        ):
            _fail("live result occurrence presence/container/row algebra is inconsistent")
        occurrence_coordinate_by_node[node_ordinal] = coordinate

    rows_by_occurrence: dict[tuple[int, int], set[int]] = {}
    matched_node_ordinals: set[int] = set()
    expected_global_occurrence_ordinal = 0
    for node_ordinal in range(len(node_items)):
        node_item = node_items[node_ordinal]
        if node_item.representation_kind != "live_lossless_nodes_v1":
            continue
        coordinate = node_coordinates[node_ordinal]
        partition_ordinal = node_item.partition_ordinal
        context_occurrence = cast("int", coordinate["context_result_occurrence"])
        if context_occurrence not in occurrences_by_partition[partition_ordinal]:
            _fail("live node context has no exact result occurrence")
        row_ordinal = cast("int | None", coordinate["row_ordinal"])
        if row_ordinal is not None:
            rows_by_occurrence.setdefault((partition_ordinal, context_occurrence), set()).add(
                row_ordinal
            )
        if coordinate["matches_result_occurrence"] is True:
            matched_node_ordinals.add(node_ordinal)
            occurrence = occurrence_coordinate_by_node.get(node_ordinal)
            if occurrence is None or occurrence["result_occurrence_global_ordinal"] != (
                expected_global_occurrence_ordinal
            ):
                _fail("live matched-node occurrence order is not globally canonical")
            expected_global_occurrence_ordinal += 1
    if matched_node_ordinals != occurrence_nodes:
        _fail("live matched nodes differ from their exact result occurrences")

    for partition_ordinal, partition_occurrences in occurrences_by_partition.items():
        if set(partition_occurrences) != set(range(len(partition_occurrences))):
            _fail("live result concrete occurrence inventory is incomplete or gapped")
        partition = live_partitions[partition_ordinal]
        total_rows = 0
        presence_counts = {presence: 0 for presence in _PRESENCE_KINDS}
        for occurrence_ordinal, coordinate in partition_occurrences.items():
            row_count = cast("int", coordinate["result_occurrence_row_count"])
            total_rows += row_count
            presence_counts[cast("str", coordinate["result_occurrence_presence_kind"])] += 1
            if rows_by_occurrence.get((partition_ordinal, occurrence_ordinal), set()) != set(
                range(row_count)
            ):
                _fail("live result occurrence rows differ from their exact node contexts")
        if total_rows != partition.row_count:
            _fail("live result occurrence row counts differ from their partition denominator")
        container_count = len(partition_occurrences) - (
            presence_counts["missing"] + presence_counts["null"]
        )
        if not partition_occurrences:
            expected_presence = "not_observed_parent_empty"
        elif container_count == 0:
            expected_presence = (
                "mixed_absent"
                if presence_counts["missing"] and presence_counts["null"]
                else "missing"
                if presence_counts["missing"]
                else "null"
            )
        elif (
            partition.container_kind == "nba_api_live_json_array"
            and len(partition_occurrences) == 1
            and presence_counts["empty_array"] == 1
            and total_rows == 0
        ):
            expected_presence = "empty_array"
        else:
            expected_presence = "present"
        if partition.result_presence != expected_presence:
            _fail("live result declaration presence differs from its exact occurrences")

    referenced_field_nodes: set[int] = set()
    for item in field_items:
        coordinate = item.coordinate()
        node_ordinal = cast("int", coordinate["node_ordinal"])
        if node_ordinal not in node_coordinates or node_ordinal in referenced_field_nodes:
            _fail("live projection field references a foreign or reused value node")
        referenced_field_nodes.add(node_ordinal)
        node = node_coordinates[node_ordinal]
        node_item = node_items[node_ordinal]
        parent_ordinal = cast("int | None", node["parent_node_ordinal"])
        if parent_ordinal is None:
            _fail("live projection field value node has no exact owner parent")
        parent = node_coordinates[parent_ordinal]
        parent_item = node_items[parent_ordinal]
        partition = live_partitions.get(item.partition_ordinal)
        if partition is None:
            _fail("live projection field belongs to a foreign representation partition")
        field_context = (
            coordinate["context_result_name"],
            coordinate["context_result_ordinal"],
            coordinate["context_result_occurrence"],
        )
        node_context = (
            node["context_result_name"],
            node["context_result_ordinal"],
            node["context_result_occurrence"],
        )
        owner_context = (
            coordinate["owner_result_name"],
            coordinate["owner_result_ordinal"],
            coordinate["owner_result_occurrence"],
        )
        parent_context = (
            parent["context_result_name"],
            parent["context_result_ordinal"],
            parent["context_result_occurrence"],
        )
        expected_owner_row = (
            parent["row_ordinal"] if parent["row_ordinal"] is not None else node["row_ordinal"]
        )
        if (
            coordinate["json_path"] != node["json_path"]
            or field_context != node_context
            or owner_context != parent_context
            or owner_context[:2] != (partition.result_name, partition.canonical_result_ordinal)
            or coordinate["row_ordinal"] != expected_owner_row
            or item.value_state != node_item.value_state
            or item.presence_kind != node_item.presence_kind
            or item.value_kind != node_item.value_kind
            or item.canonical_json != node_item.canonical_json
            or item.canonical_json_sha256 != node_item.canonical_json_sha256
            or coordinate["decoder_value_sha256"] != node["decoder_value_sha256"]
        ):
            _fail("live projection field differs from its exact value node or owner context")
        if coordinate["known_contract_field"] is not True:
            _fail("live projection field is not one exact declared contract field")
        object_field = node["object_key"] is not None
        scalar_field = node["array_ordinal"] is not None
        if object_field:
            if (
                node["object_key"] != coordinate["field_name"]
                or node["known_contract_field"] is not True
                or parent_item.value_kind != "object"
            ):
                _fail("live projection object field differs from its exact node edge")
        elif scalar_field:
            if (
                coordinate["field_name"] != "value"
                or coordinate["field_ordinal"] != 0
                or node["known_contract_field"] is not None
                or parent_item.value_kind != "array"
                or parent_item.value_state != "structural_container"
            ):
                _fail("live scalar projection field differs from its exact array edge")
        else:
            _fail("live projection field value node has no object or scalar array edge")

    reconstructed: list[object] = [None] * len(node_items)
    for node_ordinal in range(len(node_items) - 1, -1, -1):
        node_item = node_items[node_ordinal]
        children = node_children.get(node_ordinal, [])
        structural = node_item.value_state == "structural_container"
        if structural != bool(children):
            _fail("live structural-container state differs from materialized node children")
        if not structural:
            if node_item.value_state == "missing":
                reconstructed[node_ordinal] = None
                continue
            if (
                node_item.value_state == "canonical"
                and node_item.presence_kind == "present"
                and node_item.value_kind in {"array", "object"}
            ):
                _fail("nonempty live node is not structurally materialized")
            reconstructed[node_ordinal] = node_item.value()
        elif node_item.value_kind == "array":
            reconstructed[node_ordinal] = [
                reconstructed[cast("int", child_coordinate["node_ordinal"])]
                for _child, child_coordinate in children
            ]
        else:
            object_value: dict[str, object] = {}
            for _child, child_coordinate in children:
                key = cast("str", child_coordinate["object_key"])
                if key in object_value:
                    _fail("live structural object repeats one materialized child key")
                object_value[key] = reconstructed[cast("int", child_coordinate["node_ordinal"])]
            reconstructed[node_ordinal] = object_value
    for node_ordinal, node_item in node_items.items():
        if node_item.representation_kind != "live_lossless_nodes_v1":
            continue
        coordinate = node_coordinates[node_ordinal]
        partition = live_partitions[node_item.partition_ordinal]
        contract_field_ordinal = (
            contract_field_ordinal_by_node.get(node_ordinal)
            if coordinate["object_key"] is not None
            else None
        )
        expected_source_record_sha256 = _live_node_source_item_sha256(
            item=node_item,
            coordinate=coordinate,
            partition=partition,
            contract_field_ordinal=contract_field_ordinal,
        )
        if node_item.source_record_sha256 != expected_source_record_sha256:
            _fail("live node decoder value differs from its source-public commitment")
    _canonical_json_bytes(
        reconstructed[0],
        maximum_bytes=MAX_VALUE_PROJECTION_TOTAL_CANONICAL_BYTES,
    )


@dataclass(frozen=True, slots=True)
class ValueProjectionReceiptV1:
    """Bundle-scoped aggregate over all value projection partitions and items."""

    projection_sha256: str
    raw_authority_bundle_sha256: str
    ownership_receipt_sha256: str
    expected_unit_inventory_sha256: str
    expected_unit_count: int
    expected_unit_root_sha256: str
    representation_assignment_count: int
    representation_assignment_root_sha256: str
    projection_unit_root_sha256: str
    projection_assignment_root_sha256: str
    observation_count: int
    observation_root_sha256: str
    parser_input_observation_count: int
    bodyless_observation_count: int
    partition_count: int
    partition_root_sha256: str
    item_count: int
    item_root_sha256: str
    source_record_count: int
    source_record_root_sha256: str
    binding_count: int
    binding_root_sha256: str
    rectangular_result_unit_count: int
    stats_lossless_unit_count: int
    live_lossless_unit_count: int
    response_lossless_unit_count: int
    response_fixed_zero_unit_count: int
    rectangular_result_item_count: int
    stats_lossless_item_count: int
    live_lossless_item_count: int
    response_lossless_item_count: int
    response_fixed_zero_item_count: int
    zero_result_partition_count: int
    zero_response_residual_partition_count: int
    positive_response_residual_partition_count: int
    fixed_zero_partition_count: int
    fixed_zero_landing_root_sha256: str
    present_count: int
    null_count: int
    empty_object_count: int
    empty_array_count: int
    missing_count: int
    mixed_absent_count: int
    not_observed_parent_empty_count: int
    absent_count: int
    null_value_count: int
    boolean_value_count: int
    integer_value_count: int
    number_value_count: int
    string_value_count: int
    array_value_count: int
    object_value_count: int
    missing_value_count: int
    absent_value_count: int
    structural_value_count: int
    canonical_value_byte_count: int

    schema_version: ClassVar[int] = BODY_VALUE_PROJECTION_SCHEMA_VERSION
    kind: ClassVar[str] = _RECEIPT_KIND

    def __post_init__(self) -> None:
        for field_name in (
            "projection_sha256",
            "raw_authority_bundle_sha256",
            "ownership_receipt_sha256",
            "expected_unit_inventory_sha256",
            "expected_unit_root_sha256",
            "representation_assignment_root_sha256",
            "projection_unit_root_sha256",
            "projection_assignment_root_sha256",
            "observation_root_sha256",
            "partition_root_sha256",
            "item_root_sha256",
            "source_record_root_sha256",
            "binding_root_sha256",
            "fixed_zero_landing_root_sha256",
        ):
            _exact_sha256(getattr(self, field_name), field_name=field_name)
        count_maxima = {
            "expected_unit_count": MAX_VALUE_PROJECTION_OBSERVATIONS,
            "representation_assignment_count": MAX_VALUE_PROJECTION_OBSERVATIONS,
            "observation_count": MAX_VALUE_PROJECTION_OBSERVATIONS,
            "parser_input_observation_count": MAX_VALUE_PROJECTION_OBSERVATIONS,
            "bodyless_observation_count": MAX_VALUE_PROJECTION_OBSERVATIONS,
            "partition_count": MAX_VALUE_PROJECTION_PARTITIONS,
            "item_count": MAX_VALUE_PROJECTION_ITEMS,
            "source_record_count": MAX_VALUE_PROJECTION_ITEMS,
            "binding_count": MAX_VALUE_PROJECTION_ITEMS,
            "canonical_value_byte_count": MAX_VALUE_PROJECTION_TOTAL_CANONICAL_BYTES,
        }
        for field in fields(self):
            if field.name.endswith("_count"):
                _exact_nonnegative(
                    getattr(self, field.name),
                    field_name=field.name,
                    maximum=count_maxima.get(field.name, MAX_VALUE_PROJECTION_ITEMS),
                )
        if (
            self.expected_unit_count != self.representation_assignment_count
            or self.item_count != self.source_record_count
            or self.item_count != self.binding_count
            or self.observation_count
            != self.parser_input_observation_count + self.bodyless_observation_count
            or self.expected_unit_count
            != sum(
                (
                    self.rectangular_result_unit_count,
                    self.stats_lossless_unit_count,
                    self.live_lossless_unit_count,
                    self.response_lossless_unit_count,
                    self.response_fixed_zero_unit_count,
                )
            )
            or self.item_count
            != sum(
                (
                    self.rectangular_result_item_count,
                    self.stats_lossless_item_count,
                    self.live_lossless_item_count,
                    self.response_lossless_item_count,
                    self.response_fixed_zero_item_count,
                )
            )
            or self.response_fixed_zero_item_count != 0
            or self.item_count
            != sum(
                (
                    self.present_count,
                    self.null_count,
                    self.empty_object_count,
                    self.empty_array_count,
                    self.missing_count,
                    self.mixed_absent_count,
                    self.not_observed_parent_empty_count,
                    self.absent_count,
                )
            )
            or self.item_count
            != sum(
                (
                    self.null_value_count,
                    self.boolean_value_count,
                    self.integer_value_count,
                    self.number_value_count,
                    self.string_value_count,
                    self.array_value_count,
                    self.object_value_count,
                    self.missing_value_count,
                    self.absent_value_count,
                )
            )
            or self.fixed_zero_partition_count != self.response_fixed_zero_unit_count
            or self.response_lossless_unit_count != self.positive_response_residual_partition_count
            or self.observation_count
            != self.zero_response_residual_partition_count
            + self.positive_response_residual_partition_count
            + self.fixed_zero_partition_count
            or self.partition_count
            != self.rectangular_result_unit_count
            + self.stats_lossless_unit_count
            + self.live_lossless_unit_count
            + self.zero_response_residual_partition_count
            + self.positive_response_residual_partition_count
            + self.fixed_zero_partition_count
            or self.zero_result_partition_count
            > self.rectangular_result_unit_count
            + self.stats_lossless_unit_count
            + self.live_lossless_unit_count
            or self.response_lossless_item_count < self.positive_response_residual_partition_count
            or self.structural_value_count > self.array_value_count + self.object_value_count
        ):
            _fail("value-projection receipt aggregate denominators are inconsistent")
        self._validate_zero_roots()
        if self.expected_unit_count == 0 and self.expected_unit_root_sha256 != (
            _public_expected_unit_root(
                raw_authority_bundle_sha256=self.raw_authority_bundle_sha256,
                unit_sha256s=(),
            )
        ):
            _fail("empty value-projection receipt has a foreign public unit root")
        if (
            self.representation_assignment_count == 0
            and self.representation_assignment_root_sha256 != _ownership_assignment_root(())
        ):
            _fail("empty value-projection receipt has a foreign assignment root")
        if self.projection_sha256 != _canonical_sha256(self.identity_payload()):
            _fail("value-projection receipt digest differs from its exact identity")

    def _validate_zero_roots(self) -> None:
        pairs = (
            (
                self.observation_count,
                self.observation_root_sha256,
                _OBSERVATION_ROOT_KIND,
                MAX_VALUE_PROJECTION_OBSERVATIONS,
            ),
            (
                self.partition_count,
                self.partition_root_sha256,
                _PARTITION_ROOT_KIND,
                MAX_VALUE_PROJECTION_PARTITIONS,
            ),
            (self.item_count, self.item_root_sha256, _ITEM_ROOT_KIND, MAX_VALUE_PROJECTION_ITEMS),
            (
                self.source_record_count,
                self.source_record_root_sha256,
                _SOURCE_RECORD_ROOT_KIND,
                MAX_VALUE_PROJECTION_ITEMS,
            ),
            (
                self.binding_count,
                self.binding_root_sha256,
                _BINDING_ROOT_KIND,
                MAX_VALUE_PROJECTION_ITEMS,
            ),
            (
                self.expected_unit_count,
                self.projection_unit_root_sha256,
                _UNIT_ROOT_KIND,
                MAX_VALUE_PROJECTION_OBSERVATIONS,
            ),
            (
                self.representation_assignment_count,
                self.projection_assignment_root_sha256,
                _ASSIGNMENT_ROOT_KIND,
                MAX_VALUE_PROJECTION_OBSERVATIONS,
            ),
            (
                self.fixed_zero_partition_count,
                self.fixed_zero_landing_root_sha256,
                _FIXED_ZERO_ROOT_KIND,
                MAX_VALUE_PROJECTION_OBSERVATIONS,
            ),
        )
        for count, actual, kind, maximum in pairs:
            empty = _length_framed_root(
                kind=kind,
                raw_authority_bundle_sha256=self.raw_authority_bundle_sha256,
                item_sha256s=(),
                maximum=maximum,
            )
            if (count == 0) != (actual == empty):
                _fail("value-projection receipt zero root is inconsistent")
        if (self.canonical_value_byte_count == 0) != (
            self.null_value_count
            + self.boolean_value_count
            + self.integer_value_count
            + self.number_value_count
            + self.string_value_count
            + self.array_value_count
            + self.object_value_count
            - self.structural_value_count
            == 0
        ):
            _fail("value-projection receipt canonical-byte zero proof is inconsistent")

    @classmethod
    def build(
        cls,
        *,
        raw_authority_bundle_sha256: str,
        ownership_receipt_row: dict[str, object],
        expected_unit_rows: tuple[dict[str, object], ...],
        representation_assignment_rows: tuple[dict[str, object], ...],
        ownership_observation_rows: tuple[dict[str, object], ...],
        ownership_partition_rows: tuple[dict[str, object], ...],
        ownership_binding_rows: tuple[dict[str, object], ...],
        partitions: tuple[ValueProjectionPartitionV1, ...],
        items: tuple[ValueProjectionItemV1, ...],
    ) -> Self:
        # The raw pin and complete value-free semantic closure are validated
        # before any projection DTO callback or value traversal.
        _exact_sha256(raw_authority_bundle_sha256, field_name="raw_authority_bundle_sha256")
        authority = _decode_semantic_authority(
            raw_authority_bundle_sha256=raw_authority_bundle_sha256,
            ownership_receipt_row=ownership_receipt_row,
            expected_unit_rows=expected_unit_rows,
            representation_assignment_rows=representation_assignment_rows,
            ownership_observation_rows=ownership_observation_rows,
            ownership_partition_rows=ownership_partition_rows,
            ownership_binding_rows=ownership_binding_rows,
        )
        for label, inventory, maximum in (
            ("partition inventory", partitions, MAX_VALUE_PROJECTION_PARTITIONS),
            ("item inventory", items, MAX_VALUE_PROJECTION_ITEMS),
        ):
            if type(inventory) is not tuple or len(inventory) > maximum:
                _fail(f"value-projection {label} is foreign or over-bound")
        if any(type(partition) is not ValueProjectionPartitionV1 for partition in partitions):
            _fail("value-projection aggregate contains a foreign partition DTO")
        if any(type(item) is not ValueProjectionItemV1 for item in items):
            _fail("value-projection aggregate contains a foreign item DTO")
        exact_partitions = tuple(
            ValueProjectionPartitionV1.from_row(partition.to_row()) for partition in partitions
        )
        exact_items = tuple(ValueProjectionItemV1.from_row(item.to_row()) for item in items)
        _validate_aggregate_order(
            raw_authority_bundle_sha256=raw_authority_bundle_sha256,
            authority=authority,
            partitions=exact_partitions,
            items=exact_items,
        )
        unit_sha256s = tuple(cast("str", row["unit_sha256"]) for row in authority.expected_units)
        assignment_sha256s = tuple(
            cast("str", row["assignment_sha256"]) for row in authority.assignments
        )
        ownership_receipt_sha256 = cast("str", authority.ownership_receipt["receipt_sha256"])
        expected_unit_inventory_sha256 = cast(
            "str", authority.ownership_receipt["expected_unit_inventory_sha256"]
        )
        expected_unit_root_sha256 = cast(
            "str", authority.ownership_receipt["expected_unit_root_sha256"]
        )
        representation_assignment_root_sha256 = cast(
            "str", authority.ownership_receipt["representation_assignment_root_sha256"]
        )
        observations: list[tuple[int, str, str, str]] = []
        for partition in exact_partitions:
            key = (
                partition.observation_ordinal,
                partition.observation_record_sha256,
                partition.observation_sha256,
                partition.source_input_kind,
            )
            if not observations or observations[-1] != key:
                observations.append(key)
        representation_unit_counts = {
            representation: sum(
                partition.representation_kind == representation for partition in exact_partitions
            )
            for representation in VALUE_PROJECTION_REPRESENTATION_KINDS_V1
        }
        representation_item_counts = {
            representation: sum(item.representation_kind == representation for item in exact_items)
            for representation in VALUE_PROJECTION_REPRESENTATION_KINDS_V1
        }
        presence_counts = _item_presence_counts(exact_items)
        value_counts = {
            value_kind: sum(item.value_kind == value_kind for item in exact_items)
            for value_kind in VALUE_PROJECTION_VALUE_KINDS_V1
        }
        values: dict[str, object] = {
            "raw_authority_bundle_sha256": raw_authority_bundle_sha256,
            "ownership_receipt_sha256": ownership_receipt_sha256,
            "expected_unit_inventory_sha256": expected_unit_inventory_sha256,
            "expected_unit_count": len(unit_sha256s),
            "expected_unit_root_sha256": expected_unit_root_sha256,
            "representation_assignment_count": len(assignment_sha256s),
            "representation_assignment_root_sha256": representation_assignment_root_sha256,
            "projection_unit_root_sha256": _length_framed_root(
                kind=_UNIT_ROOT_KIND,
                raw_authority_bundle_sha256=raw_authority_bundle_sha256,
                item_sha256s=unit_sha256s,
                maximum=MAX_VALUE_PROJECTION_OBSERVATIONS,
            ),
            "projection_assignment_root_sha256": _length_framed_root(
                kind=_ASSIGNMENT_ROOT_KIND,
                raw_authority_bundle_sha256=raw_authority_bundle_sha256,
                item_sha256s=assignment_sha256s,
                maximum=MAX_VALUE_PROJECTION_OBSERVATIONS,
            ),
            "observation_count": len(observations),
            "observation_root_sha256": _length_framed_root(
                kind=_OBSERVATION_ROOT_KIND,
                raw_authority_bundle_sha256=raw_authority_bundle_sha256,
                item_sha256s=tuple(value[1] for value in observations),
                maximum=MAX_VALUE_PROJECTION_OBSERVATIONS,
            ),
            "parser_input_observation_count": sum(
                value[3] == "parser_input_body" for value in observations
            ),
            "bodyless_observation_count": sum(
                value[3] == "declared_bodyless_packet" for value in observations
            ),
            "partition_count": len(exact_partitions),
            "partition_root_sha256": _length_framed_root(
                kind=_PARTITION_ROOT_KIND,
                raw_authority_bundle_sha256=raw_authority_bundle_sha256,
                item_sha256s=tuple(partition.partition_sha256 for partition in exact_partitions),
                maximum=MAX_VALUE_PROJECTION_PARTITIONS,
            ),
            "item_count": len(exact_items),
            "item_root_sha256": _length_framed_root(
                kind=_ITEM_ROOT_KIND,
                raw_authority_bundle_sha256=raw_authority_bundle_sha256,
                item_sha256s=tuple(item.item_sha256 for item in exact_items),
                maximum=MAX_VALUE_PROJECTION_ITEMS,
            ),
            "source_record_count": len(exact_items),
            "source_record_root_sha256": _length_framed_root(
                kind=_SOURCE_RECORD_ROOT_KIND,
                raw_authority_bundle_sha256=raw_authority_bundle_sha256,
                item_sha256s=tuple(item.source_record_sha256 for item in exact_items),
                maximum=MAX_VALUE_PROJECTION_ITEMS,
            ),
            "binding_count": len(exact_items),
            "binding_root_sha256": _length_framed_root(
                kind=_BINDING_ROOT_KIND,
                raw_authority_bundle_sha256=raw_authority_bundle_sha256,
                item_sha256s=tuple(item.ownership_binding_sha256 for item in exact_items),
                maximum=MAX_VALUE_PROJECTION_ITEMS,
            ),
            "rectangular_result_unit_count": representation_unit_counts[
                "rectangular_result_cells_v1"
            ],
            "stats_lossless_unit_count": representation_unit_counts["stats_lossless_records_v1"],
            "live_lossless_unit_count": representation_unit_counts["live_lossless_nodes_v1"],
            "response_lossless_unit_count": representation_unit_counts[
                "response_lossless_records_v1"
            ],
            "response_fixed_zero_unit_count": representation_unit_counts["response_fixed_zero_v1"],
            "rectangular_result_item_count": representation_item_counts[
                "rectangular_result_cells_v1"
            ],
            "stats_lossless_item_count": representation_item_counts["stats_lossless_records_v1"],
            "live_lossless_item_count": representation_item_counts["live_lossless_nodes_v1"],
            "response_lossless_item_count": representation_item_counts[
                "response_lossless_records_v1"
            ],
            "response_fixed_zero_item_count": representation_item_counts["response_fixed_zero_v1"],
            "zero_result_partition_count": sum(
                partition.partition_kind == "result_occurrence" and partition.item_count == 0
                for partition in exact_partitions
            ),
            "zero_response_residual_partition_count": sum(
                partition.partition_kind == "response_residual" and partition.item_count == 0
                for partition in exact_partitions
            ),
            "positive_response_residual_partition_count": sum(
                partition.partition_kind == "response_residual" and partition.item_count > 0
                for partition in exact_partitions
            ),
            "fixed_zero_partition_count": sum(
                partition.partition_kind == "response_fixed_zero" for partition in exact_partitions
            ),
            "fixed_zero_landing_root_sha256": _length_framed_root(
                kind=_FIXED_ZERO_ROOT_KIND,
                raw_authority_bundle_sha256=raw_authority_bundle_sha256,
                item_sha256s=tuple(
                    cast("str", partition.fixed_zero_landing_sha256)
                    for partition in exact_partitions
                    if partition.partition_kind == "response_fixed_zero"
                ),
                maximum=MAX_VALUE_PROJECTION_OBSERVATIONS,
            ),
            **presence_counts,
            "null_value_count": value_counts["null"],
            "boolean_value_count": value_counts["boolean"],
            "integer_value_count": value_counts["integer"],
            "number_value_count": value_counts["number"],
            "string_value_count": value_counts["string"],
            "array_value_count": value_counts["array"],
            "object_value_count": value_counts["object"],
            "missing_value_count": value_counts["missing"],
            "absent_value_count": sum(item.value_state == "absent" for item in exact_items),
            "structural_value_count": sum(
                item.value_state == "structural_container" for item in exact_items
            ),
            "canonical_value_byte_count": sum(
                len(cast("str", item.canonical_json).encode("utf-8"))
                for item in exact_items
                if item.value_state == "canonical"
            ),
        }
        payload = {"schema_version": cls.schema_version, "kind": cls.kind, **values}
        return cls(projection_sha256=_canonical_sha256(payload), **cast("Any", values))

    def identity_payload(self) -> dict[str, object]:
        return _identity_payload(self, kind=self.kind, digest_field="projection_sha256")

    def to_row(self) -> dict[str, object]:
        return _to_row(self)

    @classmethod
    def from_row(cls, value: object) -> Self:
        row = _strict_dataclass_row(value, cls=cls, label="value-projection receipt row")
        try:
            return cls(**cast("Any", {item.name: row[item.name] for item in fields(cls)}))
        except ValueProjectionError:
            raise
        except (TypeError, ValueError, RecursionError):
            _fail("value-projection receipt row failed semantic reconstruction")

    def canonical_bytes(self) -> bytes:
        return _canonical_row_bytes(self, maximum_bytes=_MAX_RECEIPT_BYTES)

    @classmethod
    def from_canonical_bytes(cls, value: object) -> Self:
        return cls.from_row(
            _row_from_canonical_bytes(
                value,
                cls=cls,
                label="value-projection receipt",
                maximum_bytes=_MAX_RECEIPT_BYTES,
            )
        )


def _validate_aggregate_order(
    *,
    raw_authority_bundle_sha256: str,
    authority: _SemanticAuthorityV1,
    partitions: tuple[ValueProjectionPartitionV1, ...],
    items: tuple[ValueProjectionItemV1, ...],
) -> None:
    if len(partitions) != len(authority.partitions) or len(items) != len(authority.bindings):
        _fail("value-projection aggregate differs from its ownership denominators")
    if len({partition.partition_sha256 for partition in partitions}) != len(partitions):
        _fail("value-projection aggregate contains a duplicate partition identity")
    if len({item.item_sha256 for item in items}) != len(items):
        _fail("value-projection aggregate contains a duplicate item identity")
    if len({item.source_record_sha256 for item in items}) != len(items):
        _fail("value-projection aggregate dual-projects one source record")
    if len({item.ownership_binding_sha256 for item in items}) != len(items):
        _fail("value-projection aggregate reuses one ownership binding")
    partition_item_groups: list[list[ValueProjectionItemV1]] = [[] for _ in partitions]
    observation_item_groups: list[list[ValueProjectionItemV1]] = [
        [] for _ in authority.observations
    ]
    observation_partition_groups: list[list[ValueProjectionPartitionV1]] = [
        [] for _ in authority.observations
    ]
    for ordinal, item in enumerate(items):
        binding = authority.bindings[ordinal]
        binding_partition_ordinal = cast("int", binding["partition_ordinal"])
        if binding_partition_ordinal >= len(partitions):
            _fail("value-projection ownership binding references a foreign partition")
        ownership_partition = authority.partitions[binding_partition_ordinal]
        observation = authority.observations[cast("int", binding["observation_ordinal"])]
        assignment = authority.assignments[cast("int", binding["unit_ordinal"])]
        if (
            item.raw_authority_bundle_sha256 != raw_authority_bundle_sha256
            or item.global_item_ordinal != ordinal
            or item.ownership_binding_ordinal != ordinal
            or item.ownership_binding_sha256 != binding["binding_sha256"]
            or item.source_record_sha256 != binding["source_record_sha256"]
            or item.observation_record_sha256 != binding["observation_record_sha256"]
            or item.observation_sha256 != binding["observation_sha256"]
            or item.observation_ordinal != binding["observation_ordinal"]
            or item.ownership_partition_sha256 != ownership_partition["partition_sha256"]
            or item.partition_ordinal != binding_partition_ordinal
            or item.unit_sha256 != binding["unit_sha256"]
            or item.unit_ordinal != binding["unit_ordinal"]
            or item.assignment_sha256 != binding["assignment_sha256"]
            or item.unit_kind != binding["ownership_kind"]
            or item.occurrence_sha256 != binding["occurrence_sha256"]
            or item.occurrence_ordinal != binding["occurrence_ordinal"]
            or item.source_input_kind != observation["source_input_kind"]
            or item.representation_kind != assignment["representation_kind"]
        ):
            _fail("value-projection item differs from its exact ownership binding")
        partition_item_groups[binding_partition_ordinal].append(item)
        observation_item_groups[item.observation_ordinal].append(item)
    active_observation: tuple[int, str, str, str] | None = None
    seen_observation_sha256s: set[str] = set()
    seen_observation_record_sha256s: set[str] = set()
    expected_observation_ordinal = 0
    expected_observation_partition_ordinal = 0
    expected_occurrence_ordinal = 0
    result_name_counts: dict[str, int] = {}
    occurrence_sha256s: set[str] = set()
    response_seen = False
    for ordinal, partition in enumerate(partitions):
        ownership_partition = authority.partitions[ordinal]
        observation = authority.observations[
            cast("int", ownership_partition["observation_ordinal"])
        ]
        unit_ordinal = cast("int | None", ownership_partition["unit_ordinal"])
        assignment = None if unit_ordinal is None else authority.assignments[unit_ordinal]
        expected_representation = None if assignment is None else assignment["representation_kind"]
        if (
            partition.raw_authority_bundle_sha256 != raw_authority_bundle_sha256
            or partition.partition_ordinal != ordinal
            or partition.ownership_partition_sha256 != ownership_partition["partition_sha256"]
            or partition.observation_record_sha256
            != ownership_partition["observation_record_sha256"]
            or partition.observation_sha256 != ownership_partition["observation_sha256"]
            or partition.observation_ordinal != ownership_partition["observation_ordinal"]
            or partition.observation_partition_ordinal
            != ownership_partition["observation_partition_ordinal"]
            or partition.partition_kind != ownership_partition["partition_kind"]
            or partition.occurrence_sha256 != ownership_partition["occurrence_sha256"]
            or partition.occurrence_ordinal != ownership_partition["occurrence_ordinal"]
            or partition.unit_sha256 != ownership_partition["unit_sha256"]
            or partition.unit_ordinal != unit_ordinal
            or partition.assignment_sha256 != ownership_partition["assignment_sha256"]
            or partition.source_input_kind != observation["source_input_kind"]
            or partition.representation_kind != expected_representation
            or partition.source_record_count != ownership_partition["record_count"]
            or partition.binding_count != ownership_partition["record_count"]
            or partition.item_count != ownership_partition["record_count"]
            or partition.fixed_zero_landing_sha256
            != ownership_partition["fixed_zero_landing_sha256"]
        ):
            _fail("value-projection partition differs from its exact ownership partition")
        observation_identity = (
            partition.observation_ordinal,
            partition.observation_record_sha256,
            partition.observation_sha256,
            partition.source_input_kind,
        )
        if observation_identity != active_observation:
            if active_observation is not None and not response_seen:
                _fail("value-projection observation lacks a response partition")
            if partition.observation_ordinal != expected_observation_ordinal:
                _fail("value-projection observation order is not contiguous")
            if (
                partition.observation_sha256 in seen_observation_sha256s
                or partition.observation_record_sha256 in seen_observation_record_sha256s
            ):
                _fail("value-projection partitions reopen a completed observation")
            seen_observation_sha256s.add(partition.observation_sha256)
            seen_observation_record_sha256s.add(partition.observation_record_sha256)
            expected_observation_ordinal += 1
            active_observation = observation_identity
            expected_observation_partition_ordinal = 0
            expected_occurrence_ordinal = 0
            result_name_counts = {}
            occurrence_sha256s = set()
            response_seen = False
        if partition.observation_partition_ordinal != expected_observation_partition_ordinal:
            _fail("value-projection observation partition order is not contiguous")
        expected_observation_partition_ordinal += 1
        if partition.partition_kind == "result_occurrence":
            if response_seen or partition.occurrence_ordinal != expected_occurrence_ordinal:
                _fail("value-projection occurrence partitions are reordered")
            occurrence_sha256 = cast("str", partition.occurrence_sha256)
            if occurrence_sha256 in occurrence_sha256s:
                _fail("value-projection observation repeats one occurrence identity")
            occurrence_sha256s.add(occurrence_sha256)
            result_name = cast("str", partition.result_name)
            expected_duplicate_ordinal = result_name_counts.get(result_name, 0)
            if partition.result_duplicate_ordinal != expected_duplicate_ordinal:
                _fail("value-projection duplicate result ordinal is not canonical")
            result_name_counts[result_name] = expected_duplicate_ordinal + 1
            expected_occurrence_ordinal += 1
        else:
            if response_seen:
                _fail("value-projection observation contains several response partitions")
            response_seen = True
            if partition.partition_kind == "response_fixed_zero" and expected_occurrence_ordinal:
                _fail("fixed-zero projection cannot follow a result occurrence")
            if (
                partition.partition_kind == "response_residual"
                and partition.item_count == 0
                and expected_occurrence_ordinal == 0
            ):
                _fail("empty projection observation requires its fixed-zero response partition")
        partition_items = tuple(partition_item_groups[ordinal])
        rebuilt = ValueProjectionPartitionV1.build(
            raw_authority_bundle_sha256=partition.raw_authority_bundle_sha256,
            ownership_partition_sha256=partition.ownership_partition_sha256,
            observation_record_sha256=partition.observation_record_sha256,
            observation_sha256=partition.observation_sha256,
            observation_ordinal=partition.observation_ordinal,
            partition_ordinal=partition.partition_ordinal,
            observation_partition_ordinal=partition.observation_partition_ordinal,
            partition_kind=partition.partition_kind,
            source_input_kind=partition.source_input_kind,
            items=partition_items,
            occurrence_sha256=partition.occurrence_sha256,
            occurrence_ordinal=partition.occurrence_ordinal,
            unit_sha256=partition.unit_sha256,
            unit_ordinal=partition.unit_ordinal,
            assignment_sha256=partition.assignment_sha256,
            representation_kind=partition.representation_kind,
            result_name=partition.result_name,
            result_duplicate_ordinal=partition.result_duplicate_ordinal,
            provider_result_ordinal=partition.provider_result_ordinal,
            expected_result_ordinal=partition.expected_result_ordinal,
            canonical_result_ordinal=partition.canonical_result_ordinal,
            result_path=partition.result_path,
            container_kind=partition.container_kind,
            result_presence=partition.result_presence,
            ordered_headers=None
            if partition.ordered_headers_json is None
            else tuple(
                cast(
                    "list[str]",
                    _decode_canonical_json(
                        partition.ordered_headers_json,
                        maximum_bytes=MAX_VALUE_PROJECTION_PATH_BYTES * _MAX_HEADER_COUNT,
                    )[1],
                )
            ),
            header_count=partition.header_count,
            ordered_header_slots=None
            if partition.ordered_header_slots_json is None
            else tuple(
                cast(
                    "list[dict[str, object]]",
                    _decode_canonical_json(
                        partition.ordered_header_slots_json,
                        maximum_bytes=MAX_VALUE_PROJECTION_PATH_BYTES * _MAX_HEADER_COUNT,
                    )[1],
                )
            ),
            header_record_count=partition.header_record_count,
            header_slot_count=partition.header_slot_count,
            field_count=partition.field_count,
            row_count=partition.row_count,
            cell_count=partition.cell_count,
            node_count=partition.node_count,
            representation_output_sha256=partition.representation_output_sha256,
            fixed_zero_landing_sha256=partition.fixed_zero_landing_sha256,
        )
        if rebuilt != partition:
            _fail("value-projection partition differs from its exact item reconstruction")
        observation_partition_groups[partition.observation_ordinal].append(partition)
    if partitions and not response_seen:
        _fail("final value-projection observation lacks a response partition")
    for observation_ordinal in range(len(authority.observations)):
        _validate_live_observation_structure(
            items=tuple(observation_item_groups[observation_ordinal]),
            partitions=tuple(observation_partition_groups[observation_ordinal]),
        )


@dataclass(frozen=True, slots=True)
class BodyValueProjectionReceiptV1:
    """Side receipt binding exact body/bodyless sources to a shared projection."""

    receipt_sha256: str
    raw_authority_bundle_sha256: str
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
    projection_sha256: str
    projection_partition_count: int
    projection_partition_root_sha256: str
    projection_item_count: int
    projection_item_root_sha256: str

    schema_version: ClassVar[int] = BODY_VALUE_PROJECTION_SCHEMA_VERSION
    kind: ClassVar[str] = _BODY_RECEIPT_KIND

    def __post_init__(self) -> None:
        for field_name in (
            "receipt_sha256",
            "raw_authority_bundle_sha256",
            "body_projection_policy_sha256",
            "body_blob_inventory_sha256",
            "body_blob_root_sha256",
            "body_blob_readback_root_sha256",
            "parser_input_object_root_sha256",
            "declared_bodyless_authority_sha256",
            "bodyless_packet_root_sha256",
            "bodyless_readback_root_sha256",
            "observation_source_root_sha256",
            "projection_sha256",
            "projection_partition_root_sha256",
            "projection_item_root_sha256",
        ):
            _exact_sha256(getattr(self, field_name), field_name=field_name)
        for field_name, maximum in (
            ("body_blob_count", MAX_VALUE_PROJECTION_OBSERVATIONS),
            ("body_blob_readback_count", MAX_VALUE_PROJECTION_OBSERVATIONS),
            ("body_blob_byte_count", _MAX_ORDINAL),
            ("parser_input_object_count", MAX_VALUE_PROJECTION_OBSERVATIONS),
            ("bodyless_packet_count", MAX_VALUE_PROJECTION_OBSERVATIONS),
            ("bodyless_readback_count", MAX_VALUE_PROJECTION_OBSERVATIONS),
            ("bodyless_packet_byte_count", _MAX_ORDINAL),
            ("observation_source_count", MAX_VALUE_PROJECTION_OBSERVATIONS),
            ("projection_partition_count", MAX_VALUE_PROJECTION_PARTITIONS),
            ("projection_item_count", MAX_VALUE_PROJECTION_ITEMS),
        ):
            _exact_nonnegative(getattr(self, field_name), field_name=field_name, maximum=maximum)
        if (
            self.body_blob_count != self.body_blob_readback_count
            or self.body_blob_count != self.parser_input_object_count
            or self.bodyless_packet_count != self.bodyless_readback_count
            or self.observation_source_count != self.body_blob_count + self.bodyless_packet_count
        ):
            _fail("body projection source/readback denominators are inconsistent")
        self._validate_zero_roots()
        if self.receipt_sha256 != _canonical_sha256(self.identity_payload()):
            _fail("body value-projection receipt digest differs from its exact identity")

    def _validate_zero_roots(self) -> None:
        pairs = (
            (self.body_blob_count, self.body_blob_root_sha256, _BODY_BLOB_ROOT_KIND),
            (
                self.body_blob_readback_count,
                self.body_blob_readback_root_sha256,
                _BODY_READBACK_ROOT_KIND,
            ),
            (
                self.parser_input_object_count,
                self.parser_input_object_root_sha256,
                _PARSER_INPUT_ROOT_KIND,
            ),
            (
                self.bodyless_packet_count,
                self.bodyless_packet_root_sha256,
                _BODYLESS_PACKET_ROOT_KIND,
            ),
            (
                self.bodyless_readback_count,
                self.bodyless_readback_root_sha256,
                _BODYLESS_READBACK_ROOT_KIND,
            ),
            (
                self.observation_source_count,
                self.observation_source_root_sha256,
                _OBSERVATION_SOURCE_ROOT_KIND,
            ),
        )
        for count, actual, kind in pairs:
            empty = _length_framed_root(
                kind=kind,
                raw_authority_bundle_sha256=self.raw_authority_bundle_sha256,
                item_sha256s=(),
                maximum=MAX_VALUE_PROJECTION_OBSERVATIONS,
            )
            if (count == 0) != (actual == empty):
                _fail("body value-projection zero root is inconsistent")
        if (self.body_blob_count == 0) != (self.body_blob_byte_count == 0):
            _fail("body value-projection body-byte zero proof is inconsistent")
        if (self.bodyless_packet_count == 0) != (self.bodyless_packet_byte_count == 0):
            _fail("body value-projection packet-byte zero proof is inconsistent")

    @classmethod
    def build(
        cls,
        *,
        raw_authority_bundle_sha256: str,
        body_projection_policy_sha256: str,
        body_blob_inventory_sha256: str,
        declared_bodyless_authority_sha256: str,
        expected_projection_sha256: str,
        projection: ValueProjectionReceiptV1,
        body_blob_sha256s: tuple[str, ...],
        body_blob_readback_sha256s: tuple[str, ...],
        parser_input_object_sha256s: tuple[str, ...],
        body_blob_byte_count: int,
        bodyless_packet_sha256s: tuple[str, ...],
        bodyless_readback_sha256s: tuple[str, ...],
        bodyless_packet_byte_count: int,
        observation_source_sha256s: tuple[str, ...],
    ) -> Self:
        # External authority pins are rejected before projection or tuple replay.
        for field_name, identity in (
            ("raw_authority_bundle_sha256", raw_authority_bundle_sha256),
            ("body_projection_policy_sha256", body_projection_policy_sha256),
            ("body_blob_inventory_sha256", body_blob_inventory_sha256),
            ("declared_bodyless_authority_sha256", declared_bodyless_authority_sha256),
            ("expected_projection_sha256", expected_projection_sha256),
        ):
            _exact_sha256(identity, field_name=field_name)
        inventories = (
            ("body blob", body_blob_sha256s),
            ("body blob readback", body_blob_readback_sha256s),
            ("parser input", parser_input_object_sha256s),
            ("bodyless packet", bodyless_packet_sha256s),
            ("bodyless readback", bodyless_readback_sha256s),
            ("observation source", observation_source_sha256s),
        )
        for label, inventory in inventories:
            if type(inventory) is not tuple or len(inventory) > MAX_VALUE_PROJECTION_OBSERVATIONS:
                _fail(f"body projection {label} inventory is foreign or over-bound")
            for identity in inventory:
                _exact_sha256(identity, field_name=f"body projection {label} identity")
        if type(projection) is not ValueProjectionReceiptV1:
            _fail("body projection builder requires one exact shared projection DTO")
        replayed = ValueProjectionReceiptV1.from_row(projection.to_row())
        if (
            replayed.projection_sha256 != expected_projection_sha256
            or replayed.raw_authority_bundle_sha256 != raw_authority_bundle_sha256
            or len(body_blob_sha256s) != len(body_blob_readback_sha256s)
            or len(body_blob_sha256s) != len(parser_input_object_sha256s)
            or len(bodyless_packet_sha256s) != len(bodyless_readback_sha256s)
            or len(body_blob_sha256s) != replayed.parser_input_observation_count
            or len(bodyless_packet_sha256s) != replayed.bodyless_observation_count
            or len(observation_source_sha256s) != replayed.observation_count
        ):
            _fail("body projection builder sources differ from the shared projection")
        _exact_nonnegative(
            body_blob_byte_count,
            field_name="body blob byte count",
            maximum=_MAX_ORDINAL,
        )
        _exact_nonnegative(
            bodyless_packet_byte_count,
            field_name="bodyless packet byte count",
            maximum=_MAX_ORDINAL,
        )
        values: dict[str, object] = {
            "raw_authority_bundle_sha256": raw_authority_bundle_sha256,
            "body_projection_policy_sha256": body_projection_policy_sha256,
            "body_blob_inventory_sha256": body_blob_inventory_sha256,
            "body_blob_count": len(body_blob_sha256s),
            "body_blob_root_sha256": _length_framed_root(
                kind=_BODY_BLOB_ROOT_KIND,
                raw_authority_bundle_sha256=raw_authority_bundle_sha256,
                item_sha256s=body_blob_sha256s,
                maximum=MAX_VALUE_PROJECTION_OBSERVATIONS,
            ),
            "body_blob_readback_count": len(body_blob_readback_sha256s),
            "body_blob_readback_root_sha256": _length_framed_root(
                kind=_BODY_READBACK_ROOT_KIND,
                raw_authority_bundle_sha256=raw_authority_bundle_sha256,
                item_sha256s=body_blob_readback_sha256s,
                maximum=MAX_VALUE_PROJECTION_OBSERVATIONS,
            ),
            "body_blob_byte_count": body_blob_byte_count,
            "parser_input_object_count": len(parser_input_object_sha256s),
            "parser_input_object_root_sha256": _length_framed_root(
                kind=_PARSER_INPUT_ROOT_KIND,
                raw_authority_bundle_sha256=raw_authority_bundle_sha256,
                item_sha256s=parser_input_object_sha256s,
                maximum=MAX_VALUE_PROJECTION_OBSERVATIONS,
            ),
            "declared_bodyless_authority_sha256": declared_bodyless_authority_sha256,
            "bodyless_packet_count": len(bodyless_packet_sha256s),
            "bodyless_packet_root_sha256": _length_framed_root(
                kind=_BODYLESS_PACKET_ROOT_KIND,
                raw_authority_bundle_sha256=raw_authority_bundle_sha256,
                item_sha256s=bodyless_packet_sha256s,
                maximum=MAX_VALUE_PROJECTION_OBSERVATIONS,
            ),
            "bodyless_readback_count": len(bodyless_readback_sha256s),
            "bodyless_readback_root_sha256": _length_framed_root(
                kind=_BODYLESS_READBACK_ROOT_KIND,
                raw_authority_bundle_sha256=raw_authority_bundle_sha256,
                item_sha256s=bodyless_readback_sha256s,
                maximum=MAX_VALUE_PROJECTION_OBSERVATIONS,
            ),
            "bodyless_packet_byte_count": bodyless_packet_byte_count,
            "observation_source_count": len(observation_source_sha256s),
            "observation_source_root_sha256": _length_framed_root(
                kind=_OBSERVATION_SOURCE_ROOT_KIND,
                raw_authority_bundle_sha256=raw_authority_bundle_sha256,
                item_sha256s=observation_source_sha256s,
                maximum=MAX_VALUE_PROJECTION_OBSERVATIONS,
            ),
            "projection_sha256": replayed.projection_sha256,
            "projection_partition_count": replayed.partition_count,
            "projection_partition_root_sha256": replayed.partition_root_sha256,
            "projection_item_count": replayed.item_count,
            "projection_item_root_sha256": replayed.item_root_sha256,
        }
        payload = {"schema_version": cls.schema_version, "kind": cls.kind, **values}
        return cls(receipt_sha256=_canonical_sha256(payload), **cast("Any", values))

    def identity_payload(self) -> dict[str, object]:
        return _identity_payload(self, kind=self.kind, digest_field="receipt_sha256")

    def to_row(self) -> dict[str, object]:
        return _to_row(self)

    @classmethod
    def from_row(cls, value: object) -> Self:
        row = _strict_dataclass_row(value, cls=cls, label="body value-projection receipt row")
        try:
            return cls(**cast("Any", {item.name: row[item.name] for item in fields(cls)}))
        except ValueProjectionError:
            raise
        except (TypeError, ValueError, RecursionError):
            _fail("body value-projection receipt row failed semantic reconstruction")

    def canonical_bytes(self) -> bytes:
        return _canonical_row_bytes(self, maximum_bytes=_MAX_RECEIPT_BYTES)

    @classmethod
    def from_canonical_bytes(cls, value: object) -> Self:
        return cls.from_row(
            _row_from_canonical_bytes(
                value,
                cls=cls,
                label="body value-projection receipt",
                maximum_bytes=_MAX_RECEIPT_BYTES,
            )
        )
