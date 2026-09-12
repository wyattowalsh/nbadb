"""Strict public-table-only value projection authority for W2.

This module is deliberately downstream of the value-free projection plan.  It
admits the five mandatory non-operation public relations and never receives
body bytes, parser output, staging state, or value-bearing receipt material.
Only the result-cell, stats-lossless, and live-lossless relations contribute
values; the assignment and route-field relations are value-free closure proof.
"""

from __future__ import annotations

import hashlib
import json
import math
import re
from dataclasses import dataclass, fields
from typing import Any, ClassVar, Final, Never, Self, cast

from nbadb.contracts.live_lossless_value_authority import (
    LIVE_LOSSLESS_NODE_SCHEMA_SHA256,
    MAX_LIVE_LOSSLESS_RECORDS,
    LiveLosslessNodeRecordV1,
    LiveLosslessValueAuthorityError,
)
from nbadb.contracts.public_value_types import (
    MAX_PUBLIC_VALUE_EXPECTED_UNITS,
    PublicValueTypesError,
    ValueRepresentationAssignmentV1,
)
from nbadb.contracts.stats_lossless_value_authority import (
    MAX_STATS_LOSSLESS_RECORDS,
    STATS_LOSSLESS_RECORD_SCHEMA_SHA256,
    StatsLosslessRecordV1,
    StatsLosslessValueAuthorityError,
)
from nbadb.contracts.value_projection import (
    MAX_VALUE_PROJECTION_ITEMS,
    VALUE_PROJECTION_COORDINATE_FIELDS_V1,
    ValueProjectionError,
    ValueProjectionItemV1,
    ValueProjectionPartitionV1,
    ValueProjectionReceiptV1,
)
from nbadb.contracts.value_projection_plan import (
    ValueProjectionPlanError,
    ValueProjectionPlanOccurrenceV1,
    ValueProjectionPlanOwnershipPartitionV1,
    ValueProjectionPlanSourceRecordV1,
    ValueProjectionPlanV1,
)

__all__ = [
    "PUBLIC_TABLE_VALUE_PROJECTION_SCHEMA_VERSION",
    "RAW_NBA_API_RESULT_CELL_SCHEMA_SHA256",
    "RAW_NBA_API_ROUTE_FIELD_LANDING_SCHEMA_SHA256",
    "RAW_NBA_API_VALUE_REPRESENTATION_SCHEMA_SHA256",
    "PublicTableValueProjectionError",
    "PublicTableValueProjectionReceiptV1",
    "PublicTableValueProjectionV1",
    "build_public_table_value_projection",
]


PUBLIC_TABLE_VALUE_PROJECTION_SCHEMA_VERSION: Final = 1
_SHA256_RE: Final = re.compile(r"[0-9a-f]{64}\Z")
_MAX_ROW_BYTES: Final = 64 * 1024 * 1024
_MAX_RECEIPT_BYTES: Final = 256 * 1024
_MAX_JSON_DEPTH: Final = 64
_MAX_JSON_NODES: Final = 2_000_000
_MAX_NUMBER_TOKEN_BYTES: Final = 128
_MAX_INTEGER_ABS: Final = (1 << 63) - 1
_MAX_RESULT_CELL_ROWS: Final = 2_000_000
_MAX_ROUTE_FIELD_LANDING_ROWS: Final = 10_000_000
_RECEIPT_KIND: Final = "nbadb_public_table_value_projection_receipt_v1"
_RELATION_ROOT_KINDS: Final = {
    "result_cell": "nbadb_public_projection_result_cell_rows_v1",
    "stats_lossless": "nbadb_public_projection_stats_lossless_rows_v1",
    "live_lossless": "nbadb_public_projection_live_lossless_rows_v1",
    "value_representation": "nbadb_public_projection_value_representation_rows_v1",
    "route_field_landing": "nbadb_public_projection_route_field_landing_rows_v1",
}
_PARTITION_ROOT_KIND: Final = "nbadb_public_projection_partitions_v1"
_ITEM_ROOT_KIND: Final = "nbadb_public_projection_items_v1"
_VALUE_PROJECTION_PARTITION_ROOT_KIND: Final = "nbadb_value_projection_partitions_v1"
_VALUE_PROJECTION_ITEM_ROOT_KIND: Final = "nbadb_value_projection_items_v1"
_VALUE_PROJECTION_SOURCE_RECORD_ROOT_KIND: Final = "nbadb_value_projection_source_records_v1"
_VALUE_PROJECTION_BINDING_ROOT_KIND: Final = "nbadb_value_projection_bindings_v1"
_VALUE_PROJECTION_PARTITION_ITEM_ROOT_KIND: Final = "nbadb_value_projection_partition_items_v1"
_VALUE_PROJECTION_PARTITION_RECORD_ROOT_KIND: Final = "nbadb_value_projection_partition_records_v1"
_VALUE_PROJECTION_PARTITION_BINDING_ROOT_KIND: Final = (
    "nbadb_value_projection_partition_bindings_v1"
)

_RESULT_CELL_FIELDS: Final = (
    "schema_version",
    "cell_sha256",
    "observation_sha256",
    "occurrence_sha256",
    "cell_ordinal",
    "row_ordinal",
    "header_ordinal",
    "header_name",
    "presence_kind",
    "value_kind",
    "canonical_json",
    "canonical_json_sha256",
)
_RESULT_CELL_SCHEMA_DESCRIPTOR: Final = (
    ("schema_version", "int", False),
    ("cell_sha256", "str", False),
    ("observation_sha256", "str", False),
    ("occurrence_sha256", "str", False),
    ("cell_ordinal", "int", False),
    ("row_ordinal", "int", False),
    ("header_ordinal", "int", False),
    ("header_name", "str", False),
    ("presence_kind", "str", False),
    ("value_kind", "str", False),
    ("canonical_json", "str", False),
    ("canonical_json_sha256", "str", False),
)

_VALUE_REPRESENTATION_FIELDS: Final = (
    "schema_version",
    "assignment_sha256",
    "raw_authority_bundle_sha256",
    "unit_sha256",
    "unit_ordinal",
    "source_input_kind",
    "representation_kind",
)
_VALUE_REPRESENTATION_SCHEMA_DESCRIPTOR: Final = (
    ("schema_version", "int", False),
    ("assignment_sha256", "str", False),
    ("raw_authority_bundle_sha256", "str", False),
    ("unit_sha256", "str", False),
    ("unit_ordinal", "int", False),
    ("source_input_kind", "str", False),
    ("representation_kind", "str", False),
)

_ROUTE_FIELD_LANDING_FIELDS: Final = (
    "schema_version",
    "landing_field_sha256",
    "landing_field_ordinal",
    "route_receipt_ordinal",
    "raw_authority_bundle_sha256",
    "route_landing_receipt_sha256",
    "raw_route_landing_sha256",
    "observation_sha256",
    "route_ordinal",
    "route_id",
    "staging_key",
    "unit_sha256",
    "unit_ordinal",
    "unit_kind",
    "occurrence_sha256",
    "occurrence_ordinal",
    "assignment_sha256",
    "source_input_kind",
    "representation_kind",
    "row_kind",
    "field_ordinal",
    "field_name",
    "field_authority_sha256",
    "field_origin",
    "logical_type_sha256",
)
_ROUTE_FIELD_LANDING_SCHEMA_DESCRIPTOR: Final = (
    ("schema_version", "int", False),
    ("landing_field_sha256", "str", False),
    ("landing_field_ordinal", "int", False),
    ("route_receipt_ordinal", "int", False),
    ("raw_authority_bundle_sha256", "str", False),
    ("route_landing_receipt_sha256", "str", False),
    ("raw_route_landing_sha256", "str", False),
    ("observation_sha256", "str", False),
    ("route_ordinal", "int", False),
    ("route_id", "str", False),
    ("staging_key", "str", False),
    ("unit_sha256", "str", False),
    ("unit_ordinal", "int", False),
    ("unit_kind", "str", False),
    ("occurrence_sha256", "str", True),
    ("occurrence_ordinal", "int", True),
    ("assignment_sha256", "str", False),
    ("source_input_kind", "str", False),
    ("representation_kind", "str", False),
    ("row_kind", "str", False),
    ("field_ordinal", "int", True),
    ("field_name", "str", True),
    ("field_authority_sha256", "str", True),
    ("field_origin", "str", True),
    ("logical_type_sha256", "str", True),
)
_SAFE_PUBLIC_ID_RE: Final = re.compile(r"[A-Za-z0-9_][A-Za-z0-9_.:-]{0,511}\Z", re.ASCII)
_ROUTE_ROW_KINDS: Final = frozenset({"field_binding", "route_only"})
_ROUTE_FIELD_ORIGINS: Final = frozenset(
    {"provider_bound", "provider_multi_bound", "lossless_bound", "storage_only"}
)
_UNIT_KINDS: Final = frozenset({"result_occurrence", "response_residual", "response_fixed_zero"})
_SOURCE_INPUT_KINDS: Final = frozenset({"parser_input_body", "declared_bodyless_packet"})
_REPRESENTATION_KINDS: Final = frozenset(
    {
        "rectangular_result_cells_v1",
        "stats_lossless_records_v1",
        "live_lossless_nodes_v1",
        "response_lossless_records_v1",
        "response_fixed_zero_v1",
    }
)
_RESULT_REPRESENTATION_KINDS: Final = frozenset(
    {
        "rectangular_result_cells_v1",
        "stats_lossless_records_v1",
        "live_lossless_nodes_v1",
    }
)
_ROUTE_FIELD_SENSITIVE_COMPONENTS: Final = frozenset(
    {"auth", "authorization", "cookie", "credential", "password", "secret", "session", "token"}
)
_CAMEL_ACRONYM_BOUNDARY_RE: Final = re.compile(r"([A-Z]+)([A-Z][a-z])", re.ASCII)
_CAMEL_WORD_BOUNDARY_RE: Final = re.compile(r"([a-z0-9])([A-Z])", re.ASCII)
_KEY_SEPARATOR_RE: Final = re.compile(r"[^A-Za-z0-9]+", re.ASCII)
_SENSITIVE_PUBLIC_KEY_RE: Final = re.compile(
    r"(?:authorization|proxy_authorization|authentication|cookie|set_cookie|credential|"
    r"client_secret|client_key|access_token|refresh_token|id_token|api_key|apikey|"
    r"password|passwd|proxy_url|proxy_host|vpn_server|vpn_ip|vpn_password|"
    r"request_headers|response_headers|runner_path|workspace_path|local_path|file_path|"
    r"github_token|gh_token|pat|private_key|secret_key|personal_access_token|"
    r"ssh_private_key)\Z",
    re.ASCII,
)
_AUTHORIZATION_SECRET_RE: Final = re.compile(
    r"authorization\s*:\s*(?:bearer|basic)\s+[A-Za-z0-9._~+/=-]{8,}",
    re.ASCII | re.IGNORECASE,
)
_BEARER_SECRET_RE: Final = re.compile(
    r"bearer\s+[A-Za-z0-9._~+/=-]{20,}(?![A-Za-z0-9._~+/=-])",
    re.ASCII | re.IGNORECASE,
)
_BASIC_SECRET_RE: Final = re.compile(
    r"basic\s+[A-Za-z0-9+/=]{12,}(?![A-Za-z0-9+/=])",
    re.ASCII | re.IGNORECASE,
)
_LOCAL_PATH_RE: Final = re.compile(
    r"(?:/Users/[^/\x00\s]+(?=/|\s|\Z)|/home/[^/\x00\s]+(?=/|\s|\Z)|"
    r"/private/var(?![A-Za-z0-9_])|[A-Za-z]:\\Users\\)"
)
_ROUTE_FIELD_EMBEDDED_SECRET_RE: Final = re.compile(
    r"(?:\bgh[opurs]_[A-Za-z0-9]{20,}\b|\bAKIA[0-9A-Z]{16}\b|"
    r"\bxox[baprs]-[A-Za-z0-9-]{10,}\b|"
    r"\bAIza[0-9A-Za-z_-]{35}\b|"
    r"\beyJ[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}\b|"
    r"-----BEGIN (?:[A-Z0-9]+ )*PRIVATE KEY-----|"
    r"https?://[^/\s:@]+:[^/\s@]+@)",
    re.ASCII,
)


class PublicTableValueProjectionError(ValueError):
    """A public-table projection or its public-row proof is invalid."""


def _fail(message: str) -> Never:
    raise PublicTableValueProjectionError(message)


def _exact_sha256(value: object, *, label: str) -> str:
    if type(value) is not str or _SHA256_RE.fullmatch(value) is None:
        _fail(f"{label} must be one lowercase full SHA-256")
    return value


def _exact_count(value: object, *, label: str, maximum: int) -> int:
    if type(value) is not int or value < 0 or value > maximum:
        _fail(f"{label} must be one bounded nonnegative exact integer")
    return value


def _canonical_json_bytes(value: object, *, maximum_bytes: int) -> bytes:
    nodes = 0
    stack: list[tuple[object, int]] = [(value, 0)]
    while stack:
        item, depth = stack.pop()
        nodes += 1
        if nodes > _MAX_JSON_NODES or depth > _MAX_JSON_DEPTH:
            _fail("public projection JSON exceeds its structure bound")
        if item is None or type(item) in {bool, int, float, str}:
            if type(item) is int and abs(item) > _MAX_INTEGER_ABS:
                _fail("public projection JSON integer exceeds its exact bound")
            if type(item) is float and (
                not math.isfinite(cast("float", item))
                or (item == 0.0 and math.copysign(1.0, item) < 0)
            ):
                _fail("public projection JSON number is noncanonical")
            continue
        if type(item) is list:
            stack.extend((child, depth + 1) for child in reversed(cast("list[object]", item)))
            continue
        if type(item) is dict:
            mapping = cast("dict[object, object]", item)
            if any(type(key) is not str for key in mapping):
                _fail("public projection JSON has a foreign object key")
            stack.extend((child, depth + 1) for child in reversed(tuple(mapping.values())))
            continue
        _fail("public projection JSON contains a foreign exact type")
    try:
        encoded = json.dumps(
            value,
            allow_nan=False,
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        ).encode("utf-8", errors="strict")
    except (TypeError, ValueError, UnicodeError, RecursionError):
        raise PublicTableValueProjectionError(
            "public projection JSON cannot be canonically encoded"
        ) from None
    if len(encoded) > maximum_bytes:
        _fail("public projection JSON exceeds its byte bound")
    return encoded


def _preflight_json(raw: bytes) -> None:
    depth = 0
    nodes = 1
    in_string = False
    escaped = False
    index = 0
    while index < len(raw):
        byte = raw[index]
        if in_string:
            if escaped:
                escaped = False
            elif byte == 0x5C:
                escaped = True
            elif byte == 0x22:
                in_string = False
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
                _fail("public projection JSON is structurally invalid")
        elif byte in (0x2C, 0x3A):
            nodes += 1
        elif byte == 0x2D or 0x30 <= byte <= 0x39:
            end = index + 1
            while end < len(raw) and raw[end] not in b" \t\r\n,]}":
                end += 1
            if end - index > _MAX_NUMBER_TOKEN_BYTES:
                _fail("public projection JSON contains an oversized number token")
            index = end - 1
        if depth > _MAX_JSON_DEPTH or nodes > _MAX_JSON_NODES:
            _fail("public projection JSON exceeds its lexical structure bound")
        index += 1
    if in_string or escaped or depth != 0:
        _fail("public projection JSON is structurally invalid")


def _reject_duplicate_keys(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            _fail("public projection JSON contains a duplicate object key")
        result[key] = value
    return result


def _bounded_int(token: str) -> int:
    if len(token) > _MAX_NUMBER_TOKEN_BYTES:
        _fail("public projection JSON contains an oversized integer token")
    try:
        value = int(token)
    except ValueError:
        raise PublicTableValueProjectionError(
            "public projection JSON contains an invalid integer"
        ) from None
    if abs(value) > _MAX_INTEGER_ABS:
        _fail("public projection JSON integer exceeds its exact bound")
    return value


def _bounded_float(token: str) -> float:
    if len(token) > _MAX_NUMBER_TOKEN_BYTES:
        _fail("public projection JSON contains an oversized number token")
    try:
        value = float(token)
    except ValueError:
        raise PublicTableValueProjectionError(
            "public projection JSON contains an invalid number"
        ) from None
    if not math.isfinite(value) or (value == 0.0 and math.copysign(1.0, value) < 0):
        _fail("public projection JSON number is noncanonical")
    return value


def _decode_canonical_json(value: object, *, label: str) -> object:
    if type(value) is not str:
        _fail(f"{label} must be exact canonical JSON text")
    try:
        raw = value.encode("utf-8", errors="strict")
    except UnicodeError:
        raise PublicTableValueProjectionError(f"{label} is not valid UTF-8") from None
    if not raw or len(raw) > _MAX_ROW_BYTES:
        _fail(f"{label} exceeds its exact byte bound")
    _preflight_json(raw)
    try:
        decoded = json.loads(
            value,
            object_pairs_hook=_reject_duplicate_keys,
            parse_int=_bounded_int,
            parse_float=_bounded_float,
            parse_constant=lambda _value: _fail("public projection JSON is non-finite"),
        )
    except PublicTableValueProjectionError:
        raise
    except (TypeError, ValueError, OverflowError, UnicodeError, RecursionError):
        raise PublicTableValueProjectionError(f"{label} cannot be decoded") from None
    if _canonical_json_bytes(decoded, maximum_bytes=_MAX_ROW_BYTES) != raw:
        _fail(f"{label} is not in canonical byte form")
    return decoded


def _canonical_sha256(value: object) -> str:
    return hashlib.sha256(_canonical_json_bytes(value, maximum_bytes=_MAX_ROW_BYTES)).hexdigest()


RAW_NBA_API_RESULT_CELL_SCHEMA_SHA256: Final = _canonical_sha256(
    [list(item) for item in _RESULT_CELL_SCHEMA_DESCRIPTOR]
)
RAW_NBA_API_VALUE_REPRESENTATION_SCHEMA_SHA256: Final = _canonical_sha256(
    [list(item) for item in _VALUE_REPRESENTATION_SCHEMA_DESCRIPTOR]
)
RAW_NBA_API_ROUTE_FIELD_LANDING_SCHEMA_SHA256: Final = _canonical_sha256(
    [list(item) for item in _ROUTE_FIELD_LANDING_SCHEMA_DESCRIPTOR]
)


def _length_framed_root(*, kind: str, bundle: str, values: tuple[str, ...]) -> str:
    _exact_sha256(bundle, label="ordered-root Raw bundle")
    digest = hashlib.sha256()
    digest.update(b"nbadb-public-table-value-projection-root-v1\x00")

    def feed(raw: bytes) -> None:
        digest.update(len(raw).to_bytes(8, "big", signed=False))
        digest.update(raw)

    feed(kind.encode("utf-8"))
    feed(bundle.encode("ascii"))
    feed(str(len(values)).encode("ascii"))
    for ordinal, value in enumerate(values):
        _exact_sha256(value, label="ordered-root item")
        feed(str(ordinal).encode("ascii"))
        feed(value.encode("ascii"))
    return digest.hexdigest()


def _value_projection_ordered_root(*, kind: str, bundle: str, values: tuple[str, ...]) -> str:
    """Reproduce the frozen value-projection leaf root without private imports."""

    _exact_sha256(bundle, label="projection ordered-root Raw bundle")
    digest = hashlib.sha256()
    digest.update(b"nbadb-value-projection-length-framed-root-v1\x00")

    def feed(raw: bytes) -> None:
        digest.update(len(raw).to_bytes(8, "big", signed=False))
        digest.update(raw)

    feed(b"1")
    feed(kind.encode("utf-8"))
    feed(bundle.encode("ascii"))
    feed(str(len(values)).encode("ascii"))
    for ordinal, value in enumerate(values):
        _exact_sha256(value, label="projection ordered-root item")
        feed(str(ordinal).encode("ascii"))
        feed(value.encode("ascii"))
    return digest.hexdigest()


def _legacy_root(*, kind: str, values: tuple[str, ...]) -> str:
    return _canonical_sha256(
        {"count": len(values), "items": list(values), "kind": kind, "schema_version": 1}
    )


def _empty_coordinate() -> dict[str, object]:
    return {name: None for name in VALUE_PROJECTION_COORDINATE_FIELDS_V1}


def _value_kind(value: object) -> str:
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
    _fail("public value has a foreign JSON type")


def _presence_kind(value: object) -> str:
    if value is None:
        return "null"
    if type(value) is list and not value:
        return "empty_array"
    if type(value) is dict and not value:
        return "empty_object"
    return "present"


def _normalized_public_key(value: str) -> str:
    separated = _CAMEL_ACRONYM_BOUNDARY_RE.sub(r"\1_\2", value)
    separated = _CAMEL_WORD_BOUNDARY_RE.sub(r"\1_\2", separated)
    return _KEY_SEPARATOR_RE.sub("_", separated).strip("_").lower()


def _is_secret_shaped_text(value: str) -> bool:
    stripped = value.strip()
    return (
        _AUTHORIZATION_SECRET_RE.search(stripped) is not None
        or _BEARER_SECRET_RE.search(stripped) is not None
        or _BASIC_SECRET_RE.search(stripped) is not None
        or _LOCAL_PATH_RE.search(value) is not None
        or _ROUTE_FIELD_EMBEDDED_SECRET_RE.search(value) is not None
    )


def _is_public_safe_key(value: str) -> bool:
    normalized = _normalized_public_key(value)
    return not (
        _SENSITIVE_PUBLIC_KEY_RE.fullmatch(normalized) is not None
        or any(
            component in _ROUTE_FIELD_SENSITIVE_COMPONENTS for component in normalized.split("_")
        )
        or _is_secret_shaped_text(value)
    )


def _require_public_safe_json(value: object) -> None:
    stack: list[object] = [value]
    nodes = 0
    while stack:
        item = stack.pop()
        nodes += 1
        if nodes > _MAX_JSON_NODES:
            _fail("public relation value exceeds its exact node bound")
        if type(item) is dict:
            mapping = cast("dict[str, object]", item)
            if any(not _is_public_safe_key(key) for key in mapping):
                _fail("public relation value contains a sensitive object key")
            stack.extend(reversed(tuple(mapping.values())))
        elif type(item) is list:
            stack.extend(reversed(cast("list[object]", item)))
        elif type(item) is str and _is_secret_shaped_text(item):
            _fail("public relation value contains secret-shaped text")


@dataclass(frozen=True, slots=True)
class _ResultCellRow:
    cell_sha256: str
    observation_sha256: str
    occurrence_sha256: str
    cell_ordinal: int
    row_ordinal: int
    header_ordinal: int
    header_name: str
    presence_kind: str
    value_kind: str
    canonical_json: str
    canonical_json_sha256: str
    value: object


def _decode_result_cell_row(value: object) -> _ResultCellRow:
    if type(value) is not dict:
        _fail("result-cell public row must be one exact built-in dict")
    raw = cast("dict[object, object]", value)
    if any(type(key) is not str for key in raw) or tuple(raw) != _RESULT_CELL_FIELDS:
        _fail("result-cell public row fields are missing, additive, reordered, or foreign")
    row = cast("dict[str, object]", raw)
    if type(row["schema_version"]) is not int or row["schema_version"] != 2:
        _fail("result-cell public row schema version is invalid")
    for name in ("cell_sha256", "observation_sha256", "occurrence_sha256"):
        _exact_sha256(row[name], label=f"result-cell {name}")
    for name in ("cell_ordinal", "row_ordinal", "header_ordinal"):
        _exact_count(row[name], label=f"result-cell {name}", maximum=(1 << 63) - 1)
    if (
        type(row["header_name"]) is not str
        or not row["header_name"]
        or len(cast("str", row["header_name"])) > 256
        or not _is_public_safe_key(cast("str", row["header_name"]))
    ):
        _fail("result-cell header name is not exact public-safe text")
    decoded = _decode_canonical_json(row["canonical_json"], label="result-cell canonical value")
    _require_public_safe_json(decoded)
    canonical_json = cast("str", row["canonical_json"])
    digest = hashlib.sha256(canonical_json.encode("utf-8")).hexdigest()
    if (
        row["canonical_json_sha256"] != digest
        or row["value_kind"] != _value_kind(decoded)
        or row["presence_kind"] != _presence_kind(decoded)
    ):
        _fail("result-cell value tags or digest differ from its canonical value")
    identity = {
        "schema_version": 2,
        "kind": "raw_nba_api_result_cell_v2",
        **{name: row[name] for name in _RESULT_CELL_FIELDS[1:] if name != "cell_sha256"},
    }
    if row["cell_sha256"] != _canonical_sha256(identity):
        _fail("result-cell digest differs from its exact semantic projection")
    return _ResultCellRow(
        **cast("Any", {name: row[name] for name in _RESULT_CELL_FIELDS[1:]}),
        value=decoded,
    )


@dataclass(frozen=True, slots=True)
class _RouteFieldLandingRow:
    landing_field_sha256: str
    landing_field_ordinal: int
    route_receipt_ordinal: int
    raw_authority_bundle_sha256: str
    route_landing_receipt_sha256: str
    raw_route_landing_sha256: str
    observation_sha256: str
    route_ordinal: int
    route_id: str
    staging_key: str
    unit_sha256: str
    unit_ordinal: int
    unit_kind: str
    occurrence_sha256: str | None
    occurrence_ordinal: int | None
    assignment_sha256: str
    source_input_kind: str
    representation_kind: str
    row_kind: str
    field_ordinal: int | None
    field_name: str | None
    field_authority_sha256: str | None
    field_origin: str | None
    logical_type_sha256: str | None


def _safe_route_field_name(value: object) -> str:
    if type(value) is not str or not value or len(value) > 1_024:
        _fail("route-field landing field name is absent or over-bound")
    try:
        encoded = value.encode("utf-8", errors="strict")
    except UnicodeError:
        raise PublicTableValueProjectionError(
            "route-field landing field name is not valid UTF-8"
        ) from None
    if (
        len(encoded) > 8_192
        or any(ord(character) < 0x20 for character in value)
        or not _is_public_safe_key(value)
    ):
        _fail("route-field landing field name is not public-safe")
    return value


def _decode_route_field_landing_row(value: object) -> _RouteFieldLandingRow:
    if type(value) is not dict:
        _fail("route-field landing public row must be one exact built-in dict")
    raw = cast("dict[object, object]", value)
    if any(type(key) is not str for key in raw) or tuple(raw) != _ROUTE_FIELD_LANDING_FIELDS:
        _fail("route-field landing public row has a foreign ordered shape")
    row = cast("dict[str, object]", raw)
    if type(row["schema_version"]) is not int or row["schema_version"] != 1:
        _fail("route-field landing public row schema version is invalid")
    for name in (
        "landing_field_sha256",
        "raw_authority_bundle_sha256",
        "route_landing_receipt_sha256",
        "raw_route_landing_sha256",
        "observation_sha256",
        "unit_sha256",
        "assignment_sha256",
    ):
        _exact_sha256(row[name], label=f"route-field landing {name}")
    for name, maximum in (
        ("landing_field_ordinal", 9_999_999),
        ("route_receipt_ordinal", 999_999),
        ("route_ordinal", 999_999),
        ("unit_ordinal", 99_999),
    ):
        _exact_count(row[name], label=f"route-field landing {name}", maximum=maximum)
    for name in ("route_id", "staging_key"):
        if (
            type(row[name]) is not str
            or _SAFE_PUBLIC_ID_RE.fullmatch(cast("str", row[name])) is None
        ):
            _fail(f"route-field landing {name} is not one exact public identifier")
    if type(row["unit_kind"]) is not str or row["unit_kind"] not in _UNIT_KINDS:
        _fail("route-field landing unit kind is outside its closed domain")
    if (
        type(row["source_input_kind"]) is not str
        or row["source_input_kind"] not in _SOURCE_INPUT_KINDS
    ):
        _fail("route-field landing source-input kind is outside its closed domain")
    if (
        type(row["representation_kind"]) is not str
        or row["representation_kind"] not in _REPRESENTATION_KINDS
    ):
        _fail("route-field landing representation kind is outside its closed domain")
    if row["unit_kind"] == "result_occurrence":
        _exact_sha256(row["occurrence_sha256"], label="route-field landing occurrence")
        _exact_count(
            row["occurrence_ordinal"],
            label="route-field landing occurrence ordinal",
            maximum=99_999,
        )
        if row["representation_kind"] not in _RESULT_REPRESENTATION_KINDS:
            _fail("route-field result unit uses a response-level representation")
    else:
        if row["occurrence_sha256"] is not None or row["occurrence_ordinal"] is not None:
            _fail("route-field response unit fabricates occurrence identity")
        expected_representation = (
            "response_lossless_records_v1"
            if row["unit_kind"] == "response_residual"
            else "response_fixed_zero_v1"
        )
        if row["representation_kind"] != expected_representation:
            _fail("route-field response unit has the wrong representation")
    try:
        ValueRepresentationAssignmentV1(
            assignment_sha256=cast("str", row["assignment_sha256"]),
            raw_authority_bundle_sha256=cast("str", row["raw_authority_bundle_sha256"]),
            unit_sha256=cast("str", row["unit_sha256"]),
            unit_ordinal=cast("int", row["unit_ordinal"]),
            source_input_kind=cast("Any", row["source_input_kind"]),
            representation_kind=cast("Any", row["representation_kind"]),
        )
    except PublicValueTypesError:
        raise PublicTableValueProjectionError(
            "route-field landing assignment binding failed exact replay"
        ) from None
    if type(row["row_kind"]) is not str or row["row_kind"] not in _ROUTE_ROW_KINDS:
        _fail("route-field landing row kind is outside its closed domain")
    field_values = (
        row["field_ordinal"],
        row["field_name"],
        row["field_authority_sha256"],
        row["field_origin"],
        row["logical_type_sha256"],
    )
    if row["row_kind"] == "route_only":
        if any(item is not None for item in field_values):
            _fail("route-only landing fabricates field authority")
    else:
        if any(item is None for item in field_values):
            _fail("field-binding landing omits field authority")
        _exact_count(row["field_ordinal"], label="route-field field ordinal", maximum=4_095)
        _safe_route_field_name(row["field_name"])
        _exact_sha256(row["field_authority_sha256"], label="route-field field authority")
        if type(row["field_origin"]) is not str or row["field_origin"] not in (
            _ROUTE_FIELD_ORIGINS
        ):
            _fail("route-field field origin is outside its closed domain")
        _exact_sha256(row["logical_type_sha256"], label="route-field logical type")
    identity = {
        "kind": "raw_nba_api_route_field_landing_v1",
        **{
            name: row[name]
            for name in _ROUTE_FIELD_LANDING_FIELDS
            if name != "landing_field_sha256"
        },
    }
    if row["landing_field_sha256"] != _canonical_sha256(identity):
        _fail("route-field landing digest differs from its exact semantic row")
    return _RouteFieldLandingRow(
        **cast(
            "Any",
            {name: row[name] for name in _ROUTE_FIELD_LANDING_FIELDS if name != "schema_version"},
        )
    )


@dataclass(frozen=True, slots=True)
class PublicTableValueProjectionReceiptV1:
    """Separate seal over public relation rows and reconstructed projection."""

    receipt_sha256: str
    raw_authority_bundle_sha256: str
    ownership_receipt_sha256: str
    plan_sha256: str
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
    projection_sha256: str
    projection_partition_count: int
    projection_partition_root_sha256: str
    projection_item_count: int
    projection_item_root_sha256: str

    schema_version: ClassVar[int] = PUBLIC_TABLE_VALUE_PROJECTION_SCHEMA_VERSION
    kind: ClassVar[str] = _RECEIPT_KIND

    def __post_init__(self) -> None:
        for item in fields(self):
            value = getattr(self, item.name)
            if item.name.endswith("_sha256"):
                _exact_sha256(value, label=item.name)
            elif item.name.endswith("_count"):
                _exact_count(value, label=item.name, maximum=MAX_VALUE_PROJECTION_ITEMS)
        if self.receipt_sha256 != _canonical_sha256(self.identity_payload()):
            _fail("public-table projection receipt digest differs from its exact identity")

    def identity_payload(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "kind": self.kind,
            **{
                item.name: getattr(self, item.name)
                for item in fields(self)
                if item.name != "receipt_sha256"
            },
        }

    @classmethod
    def build(cls, **values: object) -> Self:
        if cls is not PublicTableValueProjectionReceiptV1:
            _fail("public-table projection receipt builder requires its exact DTO type")
        payload = {"schema_version": cls.schema_version, "kind": cls.kind, **values}
        try:
            return cls(receipt_sha256=_canonical_sha256(payload), **cast("Any", values))
        except PublicTableValueProjectionError:
            raise
        except Exception:
            raise PublicTableValueProjectionError(
                "public-table projection receipt builder failed exact construction"
            ) from None

    def to_row(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            **{item.name: getattr(self, item.name) for item in fields(self)},
        }

    @classmethod
    def from_row(cls, value: object) -> Self:
        if cls is not PublicTableValueProjectionReceiptV1 or type(value) is not dict:
            _fail("public-table projection receipt row has a foreign exact type")
        row = cast("dict[object, object]", value)
        expected = ("schema_version", *(item.name for item in fields(cls)))
        if any(type(key) is not str for key in row) or tuple(row) != expected:
            _fail("public-table projection receipt row has a foreign ordered shape")
        if type(row["schema_version"]) is not int or row["schema_version"] != cls.schema_version:
            _fail("public-table projection receipt row schema version is invalid")
        try:
            return cls(**cast("Any", {item.name: row[item.name] for item in fields(cls)}))
        except PublicTableValueProjectionError:
            raise
        except Exception:
            raise PublicTableValueProjectionError(
                "public-table projection receipt row failed exact replay"
            ) from None

    def canonical_bytes(self) -> bytes:
        return _canonical_json_bytes(self.to_row(), maximum_bytes=_MAX_RECEIPT_BYTES)

    @classmethod
    def from_canonical_bytes(cls, value: object) -> Self:
        if cls is not PublicTableValueProjectionReceiptV1 or type(value) is not bytes:
            _fail("public-table projection receipt bytes have a foreign exact type")
        raw = value
        if not raw or len(raw) > _MAX_RECEIPT_BYTES:
            _fail("public-table projection receipt bytes exceed their exact bound")
        try:
            text = raw.decode("utf-8", errors="strict")
        except UnicodeError:
            raise PublicTableValueProjectionError(
                "public-table projection receipt bytes are not UTF-8"
            ) from None
        decoded = _decode_canonical_json(text, label="public-table projection receipt")
        if type(decoded) is not dict:
            _fail("public-table projection receipt bytes do not contain one row")
        mapping = cast("dict[str, object]", decoded)
        expected = ("schema_version", *(item.name for item in fields(cls)))
        if tuple(mapping) != tuple(sorted(expected)):
            _fail("public-table projection receipt bytes have foreign fields")
        return cast("Self", cls.from_row({name: mapping[name] for name in expected}))


@dataclass(frozen=True, slots=True)
class PublicTableValueProjectionV1:
    """Exact reconstructed projection plus its separate public-table seal."""

    receipt: PublicTableValueProjectionReceiptV1
    projection: ValueProjectionReceiptV1
    partitions: tuple[ValueProjectionPartitionV1, ...]
    items: tuple[ValueProjectionItemV1, ...]

    def __post_init__(self) -> None:
        if type(self.receipt) is not PublicTableValueProjectionReceiptV1:
            _fail("public-table projection aggregate has a foreign receipt")
        if type(self.projection) is not ValueProjectionReceiptV1:
            _fail("public-table projection aggregate has a foreign projection")
        if type(self.partitions) is not tuple or any(
            type(item) is not ValueProjectionPartitionV1 for item in self.partitions
        ):
            _fail("public-table projection aggregate has foreign partitions")
        if type(self.items) is not tuple or any(
            type(item) is not ValueProjectionItemV1 for item in self.items
        ):
            _fail("public-table projection aggregate has foreign items")
        try:
            replayed_receipt = PublicTableValueProjectionReceiptV1.from_row(self.receipt.to_row())
            replayed_projection = ValueProjectionReceiptV1.from_row(self.projection.to_row())
            replayed_partitions = tuple(
                ValueProjectionPartitionV1.from_row(item.to_row()) for item in self.partitions
            )
            replayed_items = tuple(
                ValueProjectionItemV1.from_row(item.to_row()) for item in self.items
            )
        except PublicTableValueProjectionError:
            raise
        except (ValueProjectionError, AttributeError, TypeError, ValueError, RecursionError):
            raise PublicTableValueProjectionError(
                "public-table projection aggregate child failed exact replay"
            ) from None
        if (
            replayed_receipt != self.receipt
            or replayed_projection != self.projection
            or replayed_partitions != self.partitions
            or replayed_items != self.items
        ):
            _fail("public-table projection aggregate child differs after exact replay")
        bundle = self.receipt.raw_authority_bundle_sha256
        partition_ids = tuple(item.partition_sha256 for item in replayed_partitions)
        item_ids = tuple(item.item_sha256 for item in replayed_items)
        source_record_ids = tuple(item.source_record_sha256 for item in replayed_items)
        binding_ids = tuple(item.ownership_binding_sha256 for item in replayed_items)
        if (
            self.receipt.projection_sha256 != self.projection.projection_sha256
            or self.receipt.projection_partition_count != len(self.partitions)
            or self.receipt.projection_item_count != len(self.items)
            or self.receipt.raw_authority_bundle_sha256
            != self.projection.raw_authority_bundle_sha256
            or self.receipt.ownership_receipt_sha256 != self.projection.ownership_receipt_sha256
            or self.projection.partition_count != len(self.partitions)
            or self.projection.item_count != len(self.items)
            or self.projection.source_record_count != len(self.items)
            or self.projection.binding_count != len(self.items)
            or self.receipt.projection_partition_root_sha256
            != _length_framed_root(
                kind=_PARTITION_ROOT_KIND,
                bundle=bundle,
                values=partition_ids,
            )
            or self.receipt.projection_item_root_sha256
            != _length_framed_root(kind=_ITEM_ROOT_KIND, bundle=bundle, values=item_ids)
            or self.projection.partition_root_sha256
            != _value_projection_ordered_root(
                kind=_VALUE_PROJECTION_PARTITION_ROOT_KIND,
                bundle=bundle,
                values=partition_ids,
            )
            or self.projection.item_root_sha256
            != _value_projection_ordered_root(
                kind=_VALUE_PROJECTION_ITEM_ROOT_KIND,
                bundle=bundle,
                values=item_ids,
            )
            or self.projection.source_record_root_sha256
            != _value_projection_ordered_root(
                kind=_VALUE_PROJECTION_SOURCE_RECORD_ROOT_KIND,
                bundle=bundle,
                values=source_record_ids,
            )
            or self.projection.binding_root_sha256
            != _value_projection_ordered_root(
                kind=_VALUE_PROJECTION_BINDING_ROOT_KIND,
                bundle=bundle,
                values=binding_ids,
            )
        ):
            _fail("public-table projection aggregate differs from its receipt")
        partition_by_ordinal = {item.partition_ordinal: item for item in replayed_partitions}
        items_by_partition: dict[int, list[ValueProjectionItemV1]] = {
            item.partition_ordinal: [] for item in replayed_partitions
        }
        for global_ordinal, item in enumerate(replayed_items):
            partition = partition_by_ordinal.get(item.partition_ordinal)
            if partition is None:
                _fail("public-table projection item references a foreign partition")
            local_items = items_by_partition[item.partition_ordinal]
            if (
                item.global_item_ordinal != global_ordinal
                or item.partition_item_ordinal != len(local_items)
                or item.raw_authority_bundle_sha256 != bundle
                or item.ownership_partition_sha256 != partition.ownership_partition_sha256
                or item.observation_record_sha256 != partition.observation_record_sha256
                or item.observation_sha256 != partition.observation_sha256
                or item.observation_ordinal != partition.observation_ordinal
                or item.unit_sha256 != partition.unit_sha256
                or item.unit_ordinal != partition.unit_ordinal
                or item.assignment_sha256 != partition.assignment_sha256
                or item.source_input_kind != partition.source_input_kind
                or item.representation_kind != partition.representation_kind
                or item.unit_kind != partition.partition_kind
                or item.occurrence_sha256 != partition.occurrence_sha256
                or item.occurrence_ordinal != partition.occurrence_ordinal
            ):
                _fail("public-table projection item differs from its exact partition binding")
            local_items.append(item)
        for ordinal, partition in enumerate(replayed_partitions):
            partition_items = items_by_partition[partition.partition_ordinal]
            partition_item_ids = tuple(item.item_sha256 for item in partition_items)
            partition_source_ids = tuple(item.source_record_sha256 for item in partition_items)
            partition_binding_ids = tuple(item.ownership_binding_sha256 for item in partition_items)
            expected_first = None if not partition_items else partition_items[0].global_item_ordinal
            if (
                partition.partition_ordinal != ordinal
                or partition.raw_authority_bundle_sha256 != bundle
                or partition.item_count != len(partition_items)
                or partition.source_record_count != len(partition_items)
                or partition.binding_count != len(partition_items)
                or partition.first_global_item_ordinal != expected_first
                or partition.item_root_sha256
                != _value_projection_ordered_root(
                    kind=_VALUE_PROJECTION_PARTITION_ITEM_ROOT_KIND,
                    bundle=bundle,
                    values=partition_item_ids,
                )
                or partition.source_record_root_sha256
                != _value_projection_ordered_root(
                    kind=_VALUE_PROJECTION_PARTITION_RECORD_ROOT_KIND,
                    bundle=bundle,
                    values=partition_source_ids,
                )
                or partition.binding_root_sha256
                != _value_projection_ordered_root(
                    kind=_VALUE_PROJECTION_PARTITION_BINDING_ROOT_KIND,
                    bundle=bundle,
                    values=partition_binding_ids,
                )
            ):
                _fail("public-table projection partition differs from its exact item slice")


def _result_path(occurrence: ValueProjectionPlanOccurrenceV1) -> str:
    if occurrence.result_path is not None:
        return occurrence.result_path
    if occurrence.provider_result_ordinal is not None:
        return f"$.resultSets[{occurrence.provider_result_ordinal}]"
    if occurrence.canonical_result_ordinal is not None:
        return f"$.expectedResults[{occurrence.canonical_result_ordinal}]"
    if occurrence.expected_result_ordinal is not None:
        return f"$.expectedResults[{occurrence.expected_result_ordinal}]"
    _fail("projection plan occurrence has no deterministic result path")


def _result_coordinate(occurrence: ValueProjectionPlanOccurrenceV1) -> dict[str, object]:
    coordinate = _empty_coordinate()
    coordinate.update(
        {
            "result_name": occurrence.result_name,
            "result_duplicate_ordinal": occurrence.result_duplicate_ordinal,
            "provider_result_ordinal": occurrence.provider_result_ordinal,
            "expected_result_ordinal": occurrence.expected_result_ordinal,
            "canonical_result_ordinal": occurrence.canonical_result_ordinal,
            "result_path": _result_path(occurrence),
            "container_kind": occurrence.container_kind,
            "result_presence": occurrence.result_presence,
        }
    )
    return coordinate


def _item_kwargs(
    source: ValueProjectionPlanSourceRecordV1,
    partition: ValueProjectionPlanOwnershipPartitionV1,
    *,
    partition_item_ordinal: int,
) -> dict[str, object]:
    return {
        "raw_authority_bundle_sha256": source.raw_authority_bundle_sha256,
        "ownership_binding_sha256": source.binding_sha256,
        "ownership_binding_ordinal": source.binding_ordinal,
        "source_record_sha256": source.source_record_sha256,
        "observation_record_sha256": source.observation_record_sha256,
        "observation_sha256": source.observation_sha256,
        "observation_ordinal": source.observation_ordinal,
        "ownership_partition_sha256": source.partition_sha256,
        "partition_ordinal": source.partition_ordinal,
        "unit_sha256": source.unit_sha256,
        "unit_ordinal": source.unit_ordinal,
        "assignment_sha256": source.assignment_sha256,
        "source_input_kind": source.source_input_kind,
        "representation_kind": source.representation_kind,
        "unit_kind": source.unit_kind,
        "occurrence_sha256": source.occurrence_sha256,
        "occurrence_ordinal": source.occurrence_ordinal,
        "global_item_ordinal": source.source_record_plan_ordinal,
        "partition_item_ordinal": partition_item_ordinal,
        "record_kind": source.projection_record_kind,
    }


def _stats_value_shape(record: StatsLosslessRecordV1) -> dict[str, object]:
    if record.record_kind == "response":
        return {"value_state": "absent"}
    if record.canonical_json is None:
        if record.record_kind == "json_node" and record.value_kind in {"array", "object"}:
            return {
                "value_state": "structural_container",
                "structural_value_kind": record.value_kind,
            }
        _fail("stats-lossless source record omits required canonical value material")
    return {"value": record.value()}


def _live_value_shape(
    record: LiveLosslessNodeRecordV1, payload: dict[str, object]
) -> dict[str, object]:
    if record.record_kind in {"result_declaration", "result_occurrence"}:
        return {"value_state": "absent"}
    presence = payload["presence_kind"]
    value_kind = payload["value_kind"]
    canonical_json = payload["canonical_json"]
    if presence == "missing":
        return {"value_state": "missing", "missing_presence_kind": "missing"}
    if canonical_json is None:
        if presence == "present" and value_kind in {"array", "object"}:
            return {
                "value_state": "structural_container",
                "structural_value_kind": value_kind,
            }
        _fail("live-lossless source record has an incomplete public value shape")
    return {"value": _decode_canonical_json(canonical_json, label="live public value")}


def _ownership_receipt_row(plan: ValueProjectionPlanV1) -> dict[str, object]:
    partitions = plan.ownership_partitions
    result_partitions = tuple(
        item for item in partitions if item.partition_kind == "result_occurrence"
    )
    residual_partitions = tuple(
        item for item in partitions if item.partition_kind == "response_residual"
    )
    fixed_partitions = tuple(
        item for item in partitions if item.partition_kind == "response_fixed_zero"
    )
    fixed_landings = tuple(cast("str", item.fixed_zero_landing_sha256) for item in fixed_partitions)
    return {
        "schema_version": 1,
        "receipt_sha256": plan.ownership_receipt_sha256,
        "raw_authority_bundle_sha256": plan.raw_authority_bundle_sha256,
        "expected_unit_count": plan.expected_unit_count,
        "expected_unit_inventory_sha256": plan.expected_unit_inventory_sha256,
        "expected_unit_root_sha256": plan.expected_unit_authority_root_sha256,
        "representation_assignment_count": plan.assignment_count,
        "representation_assignment_root_sha256": plan.ownership_assignment_root_sha256,
        "observation_count": plan.observation_count,
        "observation_root_sha256": plan.ownership_observation_root_sha256,
        "partition_count": plan.partition_count,
        "partition_root_sha256": plan.ownership_partition_root_sha256,
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
        "fixed_zero_landing_root_sha256": _legacy_root(
            kind="nbadb_lossless_fixed_zero_landings_v1", values=fixed_landings
        ),
        "binding_count": plan.binding_count,
        "binding_root_sha256": plan.ownership_binding_root_sha256,
        "source_record_count": plan.source_record_count,
        "source_record_root_sha256": plan.ownership_source_record_root_sha256,
    }


def build_public_table_value_projection(
    *,
    plan: object,
    expected_plan_sha256: object,
    expected_raw_authority_bundle_sha256: object,
    expected_ownership_receipt_sha256: object,
    result_cell_schema_sha256: object,
    result_cell_rows: object,
    stats_lossless_schema_sha256: object,
    stats_lossless_rows: object,
    live_lossless_schema_sha256: object,
    live_lossless_rows: object,
    value_representation_schema_sha256: object,
    value_representation_rows: object,
    route_field_landing_schema_sha256: object,
    route_field_landing_rows: object,
) -> PublicTableValueProjectionV1:
    """Reconstruct one exact projection and bind all five public relations."""

    expected_plan = _exact_sha256(expected_plan_sha256, label="expected projection plan")
    expected_bundle = _exact_sha256(
        expected_raw_authority_bundle_sha256, label="expected Raw Authority bundle"
    )
    expected_ownership = _exact_sha256(
        expected_ownership_receipt_sha256, label="expected ownership receipt"
    )
    expected_result_schema = _exact_sha256(
        result_cell_schema_sha256, label="result-cell public schema"
    )
    expected_stats_schema = _exact_sha256(
        stats_lossless_schema_sha256, label="stats-lossless public schema"
    )
    expected_live_schema = _exact_sha256(
        live_lossless_schema_sha256, label="live-lossless public schema"
    )
    expected_assignment_schema = _exact_sha256(
        value_representation_schema_sha256, label="value-representation public schema"
    )
    expected_route_schema = _exact_sha256(
        route_field_landing_schema_sha256, label="route-field landing public schema"
    )
    if expected_result_schema != RAW_NBA_API_RESULT_CELL_SCHEMA_SHA256:
        _fail("result-cell public schema differs from the frozen exact contract")
    if expected_stats_schema != STATS_LOSSLESS_RECORD_SCHEMA_SHA256:
        _fail("stats-lossless public schema differs from the frozen exact contract")
    if expected_live_schema != LIVE_LOSSLESS_NODE_SCHEMA_SHA256:
        _fail("live-lossless public schema differs from the frozen exact contract")
    if expected_assignment_schema != RAW_NBA_API_VALUE_REPRESENTATION_SCHEMA_SHA256:
        _fail("value-representation public schema differs from the frozen exact contract")
    if expected_route_schema != RAW_NBA_API_ROUTE_FIELD_LANDING_SCHEMA_SHA256:
        _fail("route-field landing public schema differs from the frozen exact contract")
    if type(plan) is not ValueProjectionPlanV1:
        _fail("public projection plan has a foreign exact DTO type")
    if (
        plan.plan_sha256 != expected_plan
        or plan.raw_authority_bundle_sha256 != expected_bundle
        or plan.ownership_receipt_sha256 != expected_ownership
    ):
        _fail("public projection plan differs from its external pins")
    try:
        exact_plan = ValueProjectionPlanV1.from_row(
            plan.to_row(),
            expected_plan_sha256=expected_plan,
            expected_raw_authority_bundle_sha256=expected_bundle,
            expected_ownership_receipt_sha256=expected_ownership,
        )
    except (ValueProjectionPlanError, AttributeError, TypeError, ValueError, RecursionError):
        raise PublicTableValueProjectionError(
            "public projection plan failed exact external-pin replay"
        ) from None
    relation_inputs = (
        ("result-cell", result_cell_rows, _MAX_RESULT_CELL_ROWS),
        ("stats-lossless", stats_lossless_rows, MAX_STATS_LOSSLESS_RECORDS),
        ("live-lossless", live_lossless_rows, MAX_LIVE_LOSSLESS_RECORDS),
        (
            "value-representation",
            value_representation_rows,
            MAX_PUBLIC_VALUE_EXPECTED_UNITS,
        ),
        (
            "route-field landing",
            route_field_landing_rows,
            _MAX_ROUTE_FIELD_LANDING_ROWS,
        ),
    )
    for label, inventory, maximum in relation_inputs:
        if type(inventory) is not tuple or len(inventory) > maximum:
            _fail(f"{label} public row inventory is foreign or over-bound")
    raw_result_rows = cast("tuple[object, ...]", result_cell_rows)
    raw_stats_rows = cast("tuple[object, ...]", stats_lossless_rows)
    raw_live_rows = cast("tuple[object, ...]", live_lossless_rows)
    raw_assignment_rows = cast("tuple[object, ...]", value_representation_rows)
    raw_route_rows = cast("tuple[object, ...]", route_field_landing_rows)
    try:
        result_rows = tuple(_decode_result_cell_row(item) for item in raw_result_rows)
        stats_rows = tuple(StatsLosslessRecordV1.from_row(item) for item in raw_stats_rows)
        live_rows = tuple(LiveLosslessNodeRecordV1.from_row(item) for item in raw_live_rows)
        assignment_rows = tuple(
            ValueRepresentationAssignmentV1.from_row(item) for item in raw_assignment_rows
        )
        route_rows = tuple(_decode_route_field_landing_row(item) for item in raw_route_rows)
    except PublicTableValueProjectionError:
        raise
    except (
        StatsLosslessValueAuthorityError,
        LiveLosslessValueAuthorityError,
        PublicValueTypesError,
    ):
        raise PublicTableValueProjectionError(
            "public relation row failed exact semantic replay"
        ) from None
    expected_assignment_rows = tuple(item.to_row() for item in exact_plan.assignments)
    if tuple(item.to_row() for item in assignment_rows) != expected_assignment_rows:
        _fail("value-representation rows differ from the exact ordered plan assignments")

    units_by_sha256 = {item.unit_sha256: item for item in exact_plan.expected_units}
    assignments_by_sha256 = {item.assignment_sha256: item for item in exact_plan.assignments}
    route_ids: set[str] = set()
    route_semantic_keys: set[tuple[object, ...]] = set()
    covered_route_units: set[str] = set()
    for ordinal, route in enumerate(route_rows):
        if route.landing_field_sha256 in route_ids:
            _fail("route-field landing rows contain a duplicate identity")
        route_ids.add(route.landing_field_sha256)
        semantic_key = (
            route.route_landing_receipt_sha256,
            route.raw_route_landing_sha256,
            route.unit_sha256,
            route.row_kind,
            route.field_ordinal,
        )
        if semantic_key in route_semantic_keys:
            _fail("route-field landing rows repeat one semantic unit-field binding")
        route_semantic_keys.add(semantic_key)
        covered_route_units.add(route.unit_sha256)
        unit = units_by_sha256.get(route.unit_sha256)
        assignment = assignments_by_sha256.get(route.assignment_sha256)
        if (
            route.landing_field_ordinal != ordinal
            or route.raw_authority_bundle_sha256 != expected_bundle
            or unit is None
            or assignment is None
            or route.unit_ordinal != unit.unit_ordinal
            or route.unit_kind != unit.unit_kind
            or route.observation_sha256 != unit.observation_sha256
            or route.occurrence_sha256 != unit.occurrence_sha256
            or route.occurrence_ordinal != unit.occurrence_ordinal
            or assignment.unit_sha256 != unit.unit_sha256
            or assignment.unit_ordinal != unit.unit_ordinal
            or route.source_input_kind != assignment.source_input_kind
            or route.representation_kind != assignment.representation_kind
        ):
            _fail("route-field landing row is foreign, orphaned, or reordered")
    if covered_route_units != set(units_by_sha256):
        _fail("route-field landing rows omit one or more exact planned units")
    result_ids = tuple(item.cell_sha256 for item in result_rows)
    stats_ids = tuple(item.record_sha256 for item in stats_rows)
    live_source_ids = tuple(item.source_item_sha256 for item in live_rows)
    assignment_ids = tuple(item.assignment_sha256 for item in assignment_rows)
    route_field_ids = tuple(item.landing_field_sha256 for item in route_rows)
    expected_relation_ids: dict[str, list[str]] = {
        "result_cell_v1": [],
        "stats_lossless_record_v1": [],
        "live_lossless_node_v1": [],
    }
    for source in exact_plan.source_record_plans:
        expected_relation_ids[source.source_relation_kind].append(source.source_record_sha256)
    for actual, relation, label in (
        (result_ids, "result_cell_v1", "result-cell"),
        (stats_ids, "stats_lossless_record_v1", "stats-lossless"),
        (live_source_ids, "live_lossless_node_v1", "live-lossless"),
    ):
        if actual != tuple(expected_relation_ids[relation]) or len(set(actual)) != len(actual):
            _fail(f"{label} public rows are missing, foreign, duplicated, or reordered")
    result_by_id = dict(zip(result_ids, result_rows, strict=True))
    stats_by_id = dict(zip(stats_ids, stats_rows, strict=True))
    live_by_id = dict(zip(live_source_ids, live_rows, strict=True))
    occurrence_by_partition = {item.partition_ordinal: item for item in exact_plan.occurrence_plans}
    partition_by_ordinal = {
        item.partition_ordinal: item for item in exact_plan.ownership_partitions
    }
    assignment_by_sha256 = {item.assignment_sha256: item for item in exact_plan.assignments}
    observation_by_ordinal = {
        item.observation_ordinal: item for item in exact_plan.ownership_observations
    }
    source_by_partition: dict[int, list[ValueProjectionPlanSourceRecordV1]] = {
        item.partition_ordinal: [] for item in exact_plan.ownership_partitions
    }
    for source in exact_plan.source_record_plans:
        source_by_partition[source.partition_ordinal].append(source)

    result_row_sha: dict[tuple[int, int], str] = {}
    result_row_duplicate: dict[tuple[int, int], int] = {}
    result_header_duplicates: dict[tuple[int, int], int] = {}
    for partition_ordinal, sources in source_by_partition.items():
        occurrence = occurrence_by_partition.get(partition_ordinal)
        if occurrence is None or occurrence.representation_kind != "rectangular_result_cells_v1":
            continue
        headers = occurrence.ordered_headers()
        header_seen: dict[str, int] = {}
        for ordinal, header in enumerate(headers):
            result_header_duplicates[(partition_ordinal, ordinal)] = header_seen.get(header, 0)
            header_seen[header] = header_seen.get(header, 0) + 1
        rows: list[list[object]] = [[] for _ in range(occurrence.row_count)]
        for source in sources:
            cell = result_by_id[source.source_record_sha256]
            if (
                cell.observation_sha256 != source.observation_sha256
                or cell.occurrence_sha256 != source.occurrence_sha256
                or cell.cell_ordinal
                != len(rows[cell.row_ordinal]) + cell.row_ordinal * occurrence.header_count
                or cell.row_ordinal >= occurrence.row_count
                or cell.header_ordinal >= occurrence.header_count
                or cell.header_name != headers[cell.header_ordinal]
            ):
                _fail("result-cell public row differs from its exact plan coordinates")
            rows[cell.row_ordinal].append(cell.value)
        seen_rows: dict[str, int] = {}
        for row_ordinal, row in enumerate(rows):
            if len(row) != occurrence.header_count:
                _fail("result-cell public row inventory is not one complete rectangle")
            digest = _canonical_sha256(row)
            result_row_sha[(partition_ordinal, row_ordinal)] = digest
            result_row_duplicate[(partition_ordinal, row_ordinal)] = seen_rows.get(digest, 0)
            seen_rows[digest] = seen_rows.get(digest, 0) + 1

    stats_slots: dict[int, tuple[dict[str, object], ...]] = {}
    stats_row_sha: dict[tuple[int, int], str] = {}
    stats_row_duplicate: dict[tuple[int, int], int] = {}
    stats_header_duplicate: dict[tuple[int, int], int] = {}
    for partition_ordinal, sources in source_by_partition.items():
        occurrence = occurrence_by_partition.get(partition_ordinal)
        if occurrence is None or occurrence.representation_kind != "stats_lossless_records_v1":
            continue
        records = [stats_by_id[item.source_record_sha256] for item in sources]
        raw_headers = next((item for item in records if item.record_kind == "raw_headers"), None)
        raw_rows = next((item for item in records if item.record_kind == "raw_rows"), None)
        if raw_headers is None or raw_rows is None:
            _fail("stats-lossless result partition omits raw header or row containers")
        headers_value = raw_headers.value()
        rows_value = raw_rows.value()
        if type(headers_value) is not list or type(rows_value) is not list:
            _fail("stats-lossless raw header or row container is not an exact array")
        header_records = [item for item in records if item.record_kind == "header"]
        row_records = [item for item in records if item.record_kind == "row"]
        cell_records = [item for item in records if item.record_kind == "cell"]
        maximum_width = (
            0
            if occurrence.result_presence == "missing"
            else max(
                [len(cast("list[object]", headers_value))]
                + [
                    len(cast("list[object]", row))
                    for row in cast("list[object]", rows_value)
                    if type(row) is list
                ]
            )
        )
        slots: list[dict[str, object]] = []
        digest_seen: dict[str, int] = {}
        for ordinal in range(maximum_width):
            if ordinal >= len(cast("list[object]", headers_value)):
                slots.append(
                    {
                        "header_reference_kind": "out_of_range",
                        "header_name": None,
                        "header_value_sha256": None,
                    }
                )
                continue
            header = cast("list[object]", headers_value)[ordinal]
            header_sha = _canonical_sha256(header)
            slots.append(
                {
                    "header_reference_kind": "named" if type(header) is str else "non_string",
                    "header_name": header if type(header) is str else None,
                    "header_value_sha256": header_sha,
                }
            )
            stats_header_duplicate[(partition_ordinal, ordinal)] = digest_seen.get(header_sha, 0)
            digest_seen[header_sha] = digest_seen.get(header_sha, 0) + 1
        stats_slots[partition_ordinal] = tuple(slots)
        if occurrence.result_presence == "missing":
            if header_records or row_records or cell_records:
                _fail("missing stats-lossless result fabricates observed value records")
        elif len(header_records) != len(cast("list[object]", headers_value)):
            _fail("stats-lossless header record denominator differs from raw headers")
        seen_rows: dict[str, int] = {}
        for row_record in row_records:
            assert row_record.row_ordinal is not None
            row_sha = cast("str", row_record.canonical_json_sha256)
            stats_row_sha[(partition_ordinal, row_record.row_ordinal)] = row_sha
            stats_row_duplicate[(partition_ordinal, row_record.row_ordinal)] = seen_rows.get(
                row_sha, 0
            )
            seen_rows[row_sha] = seen_rows.get(row_sha, 0) + 1
        if len(cell_records) != sum(
            len(cast("list[object]", row))
            for row in cast("list[object]", rows_value)
            if type(row) is list
        ):
            _fail("stats-lossless cell record denominator differs from raw rows")

    live_payload_by_id: dict[str, dict[str, object]] = {}
    live_occurrence_nodes: set[tuple[str, int]] = set()
    for record in live_rows:
        payload = _decode_canonical_json(record.payload_json, label="live-lossless payload")
        if type(payload) is not dict:
            _fail("live-lossless payload is not one exact object")
        exact_payload = cast("dict[str, object]", payload)
        live_payload_by_id[record.source_item_sha256] = exact_payload
        if record.record_kind == "result_occurrence":
            live_occurrence_nodes.add(
                (record.observation_sha256, cast("int", exact_payload["node_ordinal"]))
            )

    partition_local_counts: dict[int, int] = {
        item.partition_ordinal: 0 for item in exact_plan.ownership_partitions
    }
    cell_local_counts: dict[int, int] = {
        item.partition_ordinal: 0 for item in exact_plan.ownership_partitions
    }
    value_duplicates: dict[tuple[int, str, int, str], int] = {}
    items: list[ValueProjectionItemV1] = []
    for source in exact_plan.source_record_plans:
        partition = partition_by_ordinal[source.partition_ordinal]
        occurrence = occurrence_by_partition.get(source.partition_ordinal)
        local_ordinal = partition_local_counts[source.partition_ordinal]
        kwargs = _item_kwargs(source, partition, partition_item_ordinal=local_ordinal)
        coordinate = _empty_coordinate() if occurrence is None else _result_coordinate(occurrence)
        value_shape: dict[str, object]
        if source.source_relation_kind == "result_cell_v1":
            cell = result_by_id[source.source_record_sha256]
            row_key = (source.partition_ordinal, cell.row_ordinal)
            duplicate_key = (
                source.partition_ordinal,
                "header",
                cell.header_ordinal,
                cell.canonical_json_sha256,
            )
            duplicate_ordinal = value_duplicates.get(duplicate_key, 0)
            value_duplicates[duplicate_key] = duplicate_ordinal + 1
            coordinate.update(
                {
                    "header_name": cell.header_name,
                    "header_ordinal": cell.header_ordinal,
                    "header_duplicate_ordinal": result_header_duplicates[
                        (source.partition_ordinal, cell.header_ordinal)
                    ],
                    "row_ordinal": cell.row_ordinal,
                    "row_duplicate_ordinal": result_row_duplicate[row_key],
                    "row_value_sha256": result_row_sha[row_key],
                    "cell_ordinal": cell.cell_ordinal,
                    "value_duplicate_ordinal": duplicate_ordinal,
                }
            )
            value_shape = {"value": cell.value}
        elif source.source_relation_kind == "stats_lossless_record_v1":
            record = stats_by_id[source.source_record_sha256]
            if (
                record.raw_authority_bundle_sha256 != expected_bundle
                or record.observation_record_sha256 != source.observation_record_sha256
                or record.observation_sha256 != source.observation_sha256
                or record.occurrence_sha256 != source.occurrence_sha256
                or record.record_kind != source.projection_record_kind
            ):
                _fail("stats-lossless public row differs from its exact plan binding")
            if record.header_ordinal is not None:
                slot_inventory = stats_slots[source.partition_ordinal]
                if record.header_ordinal >= len(slot_inventory):
                    _fail("stats-lossless header ordinal is outside its exact slot inventory")
                slot = slot_inventory[record.header_ordinal]
                coordinate.update(
                    {
                        "header_reference_kind": slot["header_reference_kind"],
                        "header_name": slot["header_name"],
                        "header_ordinal": record.header_ordinal,
                        "header_value_sha256": slot["header_value_sha256"],
                        "header_duplicate_ordinal": stats_header_duplicate.get(
                            (source.partition_ordinal, record.header_ordinal)
                        ),
                    }
                )
            if record.row_ordinal is not None:
                row_key = (source.partition_ordinal, record.row_ordinal)
                coordinate.update(
                    {
                        "row_ordinal": record.row_ordinal,
                        "row_duplicate_ordinal": stats_row_duplicate[row_key],
                        "row_value_sha256": stats_row_sha[row_key],
                    }
                )
            if record.record_kind == "cell":
                assert record.header_ordinal is not None
                digest_key = cast("str", record.canonical_json_sha256)
                duplicate_key = (
                    source.partition_ordinal,
                    "header",
                    record.header_ordinal,
                    digest_key,
                )
                duplicate_ordinal = value_duplicates.get(duplicate_key, 0)
                value_duplicates[duplicate_key] = duplicate_ordinal + 1
                coordinate["cell_ordinal"] = cell_local_counts[source.partition_ordinal]
                cell_local_counts[source.partition_ordinal] += 1
                coordinate["value_duplicate_ordinal"] = duplicate_ordinal
            elif record.record_kind == "json_node":
                coordinate.update(
                    {
                        "node_ordinal": record.node_ordinal,
                        "parent_node_ordinal": record.parent_node_ordinal,
                        "json_path": record.json_path,
                        "parent_json_path": record.parent_json_path,
                        "depth": record.depth,
                        "object_key": record.object_key,
                        "object_key_ordinal": record.object_key_ordinal,
                        "array_ordinal": record.array_ordinal,
                    }
                )
            value_shape = _stats_value_shape(record)
        else:
            record = live_by_id[source.source_record_sha256]
            payload = live_payload_by_id[source.source_record_sha256]
            if (
                record.raw_authority_bundle_sha256 != expected_bundle
                or record.observation_record_sha256 != source.observation_record_sha256
                or record.observation_sha256 != source.observation_sha256
                or record.raw_occurrence_sha256 != source.occurrence_sha256
                or record.record_kind != source.projection_record_kind
            ):
                _fail("live-lossless public row differs from its exact plan binding")
            if record.record_kind == "result_declaration":
                coordinate.update(
                    {
                        "declaration_parent_result_name": payload["parent_result_set_name"],
                        "declaration_parent_field_name": payload["parent_field_name"],
                    }
                )
            elif record.record_kind == "result_occurrence":
                coordinate.update(
                    {
                        "node_ordinal": payload["node_ordinal"],
                        "json_path": payload["json_path"],
                        "result_occurrence_global_ordinal": payload["global_ordinal"],
                        "result_occurrence_ordinal": payload["occurrence_ordinal"],
                        "result_occurrence_parent_result_name": payload["parent_result_set_name"],
                        "result_occurrence_parent_result_ordinal": payload[
                            "parent_result_set_ordinal"
                        ],
                        "result_occurrence_presence_kind": payload["presence_kind"],
                        "result_occurrence_row_count": payload["row_count"],
                        "decoder_value_sha256": payload["value_sha256"],
                    }
                )
            elif record.record_kind == "node":
                coordinate.update(
                    {
                        "node_ordinal": payload["node_ordinal"],
                        "parent_node_ordinal": payload["parent_node_ordinal"],
                        "json_path": payload["json_path"],
                        "parent_json_path": payload["parent_json_path"],
                        "depth": payload["depth"],
                        "object_key": payload["object_key"],
                        "object_key_ordinal": payload["object_key_ordinal"],
                        "array_ordinal": payload["array_ordinal"],
                    }
                )
                if source.representation_kind == "live_lossless_nodes_v1":
                    coordinate.update(
                        {
                            "row_ordinal": payload["result_set_row_ordinal"],
                            "context_result_name": payload["result_set_name"],
                            "context_result_ordinal": payload["result_set_ordinal"],
                            "context_result_occurrence": payload["result_set_occurrence"],
                            "known_contract_field": payload["known_contract_field"],
                            "decoder_value_sha256": payload["value_sha256"],
                            "matches_result_occurrence": (
                                record.observation_sha256,
                                cast("int", payload["node_ordinal"]),
                            )
                            in live_occurrence_nodes,
                        }
                    )
            else:
                digest_key = cast("str", payload["value_sha256"])
                field_ordinal = cast("int", payload["field_ordinal"])
                duplicate_key = (source.partition_ordinal, "field", field_ordinal, digest_key)
                duplicate_ordinal = value_duplicates.get(duplicate_key, 0)
                value_duplicates[duplicate_key] = duplicate_ordinal + 1
                coordinate.update(
                    {
                        "field_name": payload["field_name"],
                        "field_ordinal": field_ordinal,
                        "row_ordinal": payload["owner_row_ordinal"],
                        "cell_ordinal": cell_local_counts[source.partition_ordinal],
                        "value_duplicate_ordinal": duplicate_ordinal,
                        "node_ordinal": payload["node_ordinal"],
                        "json_path": payload["concrete_json_path"],
                        "key_presence": payload["key_presence"],
                        "owner_result_name": payload["owner_result_set_name"],
                        "owner_result_ordinal": payload["owner_result_set_ordinal"],
                        "owner_result_occurrence": payload["owner_result_set_occurrence"],
                        "context_result_name": payload["context_result_set_name"],
                        "context_result_ordinal": payload["context_result_set_ordinal"],
                        "context_result_occurrence": payload["context_result_set_occurrence"],
                        "known_contract_field": True,
                        "decoder_value_sha256": payload["value_sha256"],
                    }
                )
                cell_local_counts[source.partition_ordinal] += 1
            value_shape = _live_value_shape(record, payload)
        try:
            item = ValueProjectionItemV1.build(
                **cast("Any", kwargs), coordinate=coordinate, **cast("Any", value_shape)
            )
        except ValueProjectionError:
            raise PublicTableValueProjectionError(
                "public source row cannot form its exact projection item"
            ) from None
        items.append(item)
        partition_local_counts[source.partition_ordinal] = local_ordinal + 1

    items_by_partition: dict[int, list[ValueProjectionItemV1]] = {
        item.partition_ordinal: [] for item in exact_plan.ownership_partitions
    }
    for item in items:
        items_by_partition[item.partition_ordinal].append(item)
    projection_partitions: list[ValueProjectionPartitionV1] = []
    for partition in exact_plan.ownership_partitions:
        partition_items = tuple(items_by_partition[partition.partition_ordinal])
        occurrence = occurrence_by_partition.get(partition.partition_ordinal)
        representation_kind = (
            None
            if partition.assignment_sha256 is None
            else assignment_by_sha256[partition.assignment_sha256].representation_kind
        )
        build_values: dict[str, object] = {
            "raw_authority_bundle_sha256": expected_bundle,
            "ownership_partition_sha256": partition.partition_sha256,
            "observation_record_sha256": partition.observation_record_sha256,
            "observation_sha256": partition.observation_sha256,
            "observation_ordinal": partition.observation_ordinal,
            "partition_ordinal": partition.partition_ordinal,
            "observation_partition_ordinal": partition.observation_partition_ordinal,
            "partition_kind": partition.partition_kind,
            "source_input_kind": observation_by_ordinal[
                partition.observation_ordinal
            ].source_input_kind,
            "items": partition_items,
            "occurrence_sha256": partition.occurrence_sha256,
            "occurrence_ordinal": partition.occurrence_ordinal,
            "unit_sha256": partition.unit_sha256,
            "unit_ordinal": partition.unit_ordinal,
            "assignment_sha256": partition.assignment_sha256,
            "representation_kind": representation_kind,
            "fixed_zero_landing_sha256": partition.fixed_zero_landing_sha256,
        }
        if occurrence is not None:
            build_values.update(
                {
                    "result_name": occurrence.result_name,
                    "result_duplicate_ordinal": occurrence.result_duplicate_ordinal,
                    "provider_result_ordinal": occurrence.provider_result_ordinal,
                    "expected_result_ordinal": occurrence.expected_result_ordinal,
                    "canonical_result_ordinal": occurrence.canonical_result_ordinal,
                    "result_path": _result_path(occurrence),
                    "container_kind": occurrence.container_kind,
                    "result_presence": occurrence.result_presence,
                    "row_count": occurrence.row_count,
                    "cell_count": occurrence.cell_count,
                    "representation_output_sha256": occurrence.representation_output_sha256,
                }
            )
            if occurrence.representation_kind == "stats_lossless_records_v1":
                slot_inventory = stats_slots[partition.partition_ordinal]
                build_values.update(
                    {
                        "ordered_header_slots": slot_inventory,
                        "header_record_count": sum(
                            item.record_kind == "header" for item in partition_items
                        ),
                        "header_slot_count": len(slot_inventory),
                    }
                )
            else:
                build_values.update(
                    {
                        "ordered_headers": occurrence.ordered_headers(),
                        "header_count": occurrence.header_count,
                    }
                )
            if occurrence.representation_kind == "live_lossless_nodes_v1":
                build_values.update(
                    {
                        "field_count": occurrence.header_count,
                        "node_count": sum(item.record_kind == "node" for item in partition_items),
                    }
                )
        elif partition.record_count > 0:
            source_rows = source_by_partition[partition.partition_ordinal]
            first = source_rows[0]
            if first.source_relation_kind == "stats_lossless_record_v1":
                output = stats_by_id[first.source_record_sha256].canonical_payload_sha256
            else:
                output = live_by_id[first.source_record_sha256].decoder_response_sha256
            build_values.update(
                {
                    "node_count": sum(
                        item.record_kind in {"node", "json_node"} for item in partition_items
                    ),
                    "representation_output_sha256": output,
                }
            )
        try:
            projection_partitions.append(
                ValueProjectionPartitionV1.build(**cast("Any", build_values))
            )
        except ValueProjectionError:
            raise PublicTableValueProjectionError(
                "public rows cannot form their exact projection partition"
            ) from None

    exact_items = tuple(items)
    exact_partitions = tuple(projection_partitions)
    try:
        projection = ValueProjectionReceiptV1.build(
            raw_authority_bundle_sha256=expected_bundle,
            ownership_receipt_row=_ownership_receipt_row(exact_plan),
            expected_unit_rows=tuple(item.to_row() for item in exact_plan.expected_units),
            representation_assignment_rows=tuple(item.to_row() for item in exact_plan.assignments),
            ownership_observation_rows=tuple(
                item.to_row() for item in exact_plan.ownership_observations
            ),
            ownership_partition_rows=tuple(
                item.to_row() for item in exact_plan.ownership_partitions
            ),
            ownership_binding_rows=tuple(item.to_row() for item in exact_plan.ownership_bindings),
            partitions=exact_partitions,
            items=exact_items,
        )
    except ValueProjectionError:
        raise PublicTableValueProjectionError(
            "public projection aggregate differs from the exact value-free plan"
        ) from None
    receipt = PublicTableValueProjectionReceiptV1.build(
        raw_authority_bundle_sha256=expected_bundle,
        ownership_receipt_sha256=expected_ownership,
        plan_sha256=expected_plan,
        result_cell_schema_sha256=expected_result_schema,
        result_cell_row_count=len(result_rows),
        result_cell_row_root_sha256=_length_framed_root(
            kind=_RELATION_ROOT_KINDS["result_cell"], bundle=expected_bundle, values=result_ids
        ),
        stats_lossless_schema_sha256=expected_stats_schema,
        stats_lossless_row_count=len(stats_rows),
        stats_lossless_row_root_sha256=_length_framed_root(
            kind=_RELATION_ROOT_KINDS["stats_lossless"], bundle=expected_bundle, values=stats_ids
        ),
        live_lossless_schema_sha256=expected_live_schema,
        live_lossless_row_count=len(live_rows),
        live_lossless_row_root_sha256=_length_framed_root(
            kind=_RELATION_ROOT_KINDS["live_lossless"],
            bundle=expected_bundle,
            values=tuple(item.record_sha256 for item in live_rows),
        ),
        value_representation_schema_sha256=expected_assignment_schema,
        value_representation_row_count=len(assignment_rows),
        value_representation_row_root_sha256=_length_framed_root(
            kind=_RELATION_ROOT_KINDS["value_representation"],
            bundle=expected_bundle,
            values=assignment_ids,
        ),
        route_field_landing_schema_sha256=expected_route_schema,
        route_field_landing_row_count=len(route_rows),
        route_field_landing_row_root_sha256=_length_framed_root(
            kind=_RELATION_ROOT_KINDS["route_field_landing"],
            bundle=expected_bundle,
            values=route_field_ids,
        ),
        projection_sha256=projection.projection_sha256,
        projection_partition_count=len(exact_partitions),
        projection_partition_root_sha256=_length_framed_root(
            kind=_PARTITION_ROOT_KIND,
            bundle=expected_bundle,
            values=tuple(item.partition_sha256 for item in exact_partitions),
        ),
        projection_item_count=len(exact_items),
        projection_item_root_sha256=_length_framed_root(
            kind=_ITEM_ROOT_KIND,
            bundle=expected_bundle,
            values=tuple(item.item_sha256 for item in exact_items),
        ),
    )
    return PublicTableValueProjectionV1(
        receipt=receipt,
        projection=projection,
        partitions=exact_partitions,
        items=exact_items,
    )
