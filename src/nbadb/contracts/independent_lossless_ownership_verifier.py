"""Independent plain-row verifier for exhaustive lossless ownership.

The verifier is intentionally dependency-pure.  It accepts only exact built-in
row projections and externally supplied trust pins, then reimplements the
public-unit and lossless-ownership digest, root, partition, and receipt algebra.
It never imports an authority, decoder, schema, extraction, or orchestration
module and never treats a receipt as evidence for a missing source row.
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from typing import ClassVar, Final, Never, cast

__all__ = [
    "FROZEN_LOSSLESS_OWNERSHIP_SOURCE_SHA256",
    "FROZEN_LOSSLESS_OWNERSHIP_TEST_SHA256",
    "IndependentLosslessOwnershipVerificationV1",
    "IndependentLosslessOwnershipVerifierError",
    "verify_independent_lossless_ownership",
]


FROZEN_LOSSLESS_OWNERSHIP_SOURCE_SHA256: Final = (
    "3821abe4475dd85624ae814fa0dedadd5a771bdd9589bc9ea5cda70aa97a21aa"
)
FROZEN_LOSSLESS_OWNERSHIP_TEST_SHA256: Final = (
    "e9c2edba8811f53faa2684938126a9fd2fb3f497c60290524ae8bc68d15f81f9"
)

_SCHEMA_VERSION: Final = 1
_RAW_SCHEMA_VERSION: Final = 2
_MAX_UNITS: Final = 100_000
_MAX_OBSERVATIONS: Final = _MAX_UNITS
_MAX_PARTITIONS: Final = _MAX_UNITS * 2
_MAX_BINDINGS: Final = 14_000_000
_MAX_ORDINAL: Final = (1 << 63) - 1
_MAX_ROW_BYTES: Final = 64 * 1024
_MAX_INVENTORY_BYTES: Final = 64 * 1024 * 1024
_MAX_INVENTORY_ROW_BYTES: Final = (_MAX_INVENTORY_BYTES * 2) + 4_096
_MAX_GRAPH_NODES: Final = (_MAX_UNITS * 24) + 1_024
_MAX_DEPTH: Final = 8
_MAX_INVENTORY_JSON_TOKENS: Final = (_MAX_GRAPH_NODES * 4) + 1_024
_SHA256_RE: Final = re.compile(r"[0-9a-f]{64}\Z")

_UNIT_KIND: Final = "nbadb_expected_value_unit_v1"
_INVENTORY_KIND: Final = "nbadb_expected_value_unit_inventory_v1"
_ASSIGNMENT_KIND: Final = "nbadb_value_representation_assignment_v1"
_UNIT_ROOT_KIND: Final = "nbadb_expected_value_unit_ordered_root_v1"
_BINDING_KIND: Final = "nbadb_lossless_ownership_binding_v1"
_PARTITION_KIND: Final = "nbadb_lossless_ownership_partition_v1"
_OBSERVATION_KIND: Final = "nbadb_lossless_observation_ownership_v1"
_RECEIPT_KIND: Final = "nbadb_lossless_ownership_receipt_v1"
_PARTITION_BINDING_ROOT_KIND: Final = "nbadb_lossless_partition_bindings_v1"
_PARTITION_RECORD_ROOT_KIND: Final = "nbadb_lossless_partition_source_records_v1"
_OBSERVATION_PARTITION_ROOT_KIND: Final = "nbadb_lossless_observation_partitions_v1"
_OBSERVATION_BINDING_ROOT_KIND: Final = "nbadb_lossless_observation_bindings_v1"
_OBSERVATION_RECORD_ROOT_KIND: Final = "nbadb_lossless_observation_source_records_v1"
_ASSIGNMENT_ROOT_KIND: Final = "nbadb_lossless_representation_assignments_v1"
_AUTHORITY_OBSERVATION_ROOT_KIND: Final = "nbadb_lossless_owned_observations_v1"
_AUTHORITY_PARTITION_ROOT_KIND: Final = "nbadb_lossless_ownership_partitions_v1"
_AUTHORITY_BINDING_ROOT_KIND: Final = "nbadb_lossless_ownership_bindings_v1"
_AUTHORITY_RECORD_ROOT_KIND: Final = "nbadb_lossless_owned_source_records_v1"
_FIXED_ZERO_LANDING_ROOT_KIND: Final = "nbadb_lossless_fixed_zero_landings_v1"
_VERIFICATION_KIND: Final = "nbadb_independent_lossless_ownership_verification_v1"

_SOURCE_INPUT_KINDS: Final = frozenset({"parser_input_body", "declared_bodyless_packet"})
_UNIT_KINDS: Final = frozenset({"result_occurrence", "response_residual", "response_fixed_zero"})
_RAW_SOURCE_FAMILIES: Final = frozenset({"stats", "live", "static"})
_RAW_SELECTED_LIFECYCLES: Final = frozenset({"selected_terminal"})
_RAW_SUCCESS_OUTCOMES: Final = frozenset(
    {"success_nonempty", "success_empty", "static_snapshot_success"}
)
_RAW_BODY_DISPOSITIONS: Final = frozenset({"public_parser_input", "declared_bodyless"})
_RAW_LANDING_DISPOSITIONS: Final = frozenset({"wide_only", "lossless_only", "wide_plus_lossless"})
_RAW_LANDING_SEMANTICS: Final = frozenset(
    {
        "occurrence_bound",
        "conditional_lossless",
        "response_fixed_zero",
        "response_canonical_alias",
    }
)
_SOURCE_OWNER_KINDS: Final = frozenset({"result_occurrence", "response_residual"})
_RESPONSE_PARTITION_KINDS: Final = frozenset({"response_residual", "response_fixed_zero"})
_RESULT_REPRESENTATIONS: Final = frozenset(
    {
        "rectangular_result_cells_v1",
        "stats_lossless_records_v1",
        "live_lossless_nodes_v1",
    }
)
_REPRESENTATIONS: Final = frozenset(
    {
        *_RESULT_REPRESENTATIONS,
        "response_lossless_records_v1",
        "response_fixed_zero_v1",
    }
)

# These are value-free projections, not alternate authority DTOs.  Callers must
# project the named columns in this exact order from already verified public
# relations.  No provider value, payload, header, path, or local material enters
# this ownership-only boundary.
_RAW_OBSERVATION_FIELDS: Final = (
    "schema_version",
    "observation_sha256",
    "observation_record_sha256",
    "logical_invocation_sha256",
    "semantic_request_sha256",
    "provider_call_ordinal",
    "page_ordinal",
    "provider_call_role",
    "provider_call_sha256",
    "retry_ordinal",
    "request_ordinal",
    "source_family",
    "lifecycle",
    "outcome",
    "body_disposition",
    "result_occurrence_count",
    "result_occurrences_sha256",
    "route_landing_count",
    "route_landings_sha256",
)
_RAW_OCCURRENCE_FIELDS: Final = (
    "schema_version",
    "occurrence_sha256",
    "observation_sha256",
    "occurrence_ordinal",
    "landing_disposition",
)
_RAW_LANDING_FIELDS: Final = (
    "schema_version",
    "landing_sha256",
    "observation_sha256",
    "route_ordinal",
    "landing_semantic",
    "source_occurrence_count",
    "source_occurrences_sha256",
    "persisted_row_count",
)
_RESULT_CELL_FIELDS: Final = (
    "schema_version",
    "cell_sha256",
    "observation_sha256",
    "occurrence_sha256",
    "cell_ordinal",
)
_STATS_SOURCE_FIELDS: Final = (
    "schema_version",
    "record_sha256",
    "raw_authority_bundle_sha256",
    "observation_record_sha256",
    "observation_sha256",
    "global_record_ordinal",
    "owner_kind",
    "occurrence_sha256",
    "representation_kind",
)
_LIVE_SOURCE_FIELDS: Final = (
    "schema_version",
    "source_item_sha256",
    "raw_authority_bundle_sha256",
    "observation_record_sha256",
    "observation_sha256",
    "global_record_ordinal",
    "observation_record_ordinal",
    "ownership_kind",
    "raw_occurrence_sha256",
    "representation_kind",
    "expected_unit_sha256",
    "expected_unit_ordinal",
    "representation_assignment_sha256",
)
_UNIT_FIELDS: Final = (
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
_INVENTORY_FIELDS: Final = (
    "schema_version",
    "inventory_sha256",
    "raw_authority_bundle_sha256",
    "unit_count",
    "unit_root_sha256",
    "units_json",
)
_ASSIGNMENT_FIELDS: Final = (
    "schema_version",
    "assignment_sha256",
    "raw_authority_bundle_sha256",
    "unit_sha256",
    "unit_ordinal",
    "source_input_kind",
    "representation_kind",
)
_OWNERSHIP_BINDING_FIELDS: Final = (
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
_OWNERSHIP_PARTITION_FIELDS: Final = (
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
_OWNERSHIP_OBSERVATION_FIELDS: Final = (
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
_OWNERSHIP_RECEIPT_FIELDS: Final = (
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


class IndependentLosslessOwnershipVerifierError(ValueError):
    """The independently reconstructed ownership closure is invalid."""


def _fail(message: str) -> Never:
    raise IndependentLosslessOwnershipVerifierError(message)


def _exact_sha(value: object, *, label: str) -> str:
    if type(value) is not str or _SHA256_RE.fullmatch(value) is None:
        _fail(f"{label} must be one lowercase full SHA-256")
    return value


def _optional_sha(value: object, *, label: str) -> str | None:
    if value is None:
        return None
    return _exact_sha(value, label=label)


def _exact_int(value: object, *, label: str, maximum: int) -> int:
    if type(value) is not int or value < 0 or value > maximum:
        _fail(f"{label} must be one bounded nonnegative exact integer")
    return value


def _optional_int(value: object, *, label: str, maximum: int) -> int | None:
    if value is None:
        return None
    return _exact_int(value, label=label, maximum=maximum)


def _exact_literal(value: object, *, choices: frozenset[str], label: str) -> str:
    if type(value) is not str or value not in choices:
        _fail(f"{label} is outside its closed literal domain")
    return value


def _preflight_graph(value: object, *, maximum_bytes: int) -> None:
    stack: list[tuple[object, int]] = [(value, 0)]
    nodes = 0
    string_bytes = 0
    while stack:
        item, depth = stack.pop()
        nodes += 1
        if nodes > _MAX_GRAPH_NODES or depth > _MAX_DEPTH:
            _fail("independent ownership input exceeds its structural bound")
        if item is None or type(item) is bool:
            continue
        if type(item) is int:
            if item < -_MAX_ORDINAL or item > _MAX_ORDINAL:
                _fail("independent ownership input contains an unbounded integer")
            continue
        if type(item) is str:
            try:
                string_bytes += len(item.encode("utf-8", errors="strict"))
            except UnicodeEncodeError:
                _fail("independent ownership input contains invalid Unicode")
            if string_bytes > maximum_bytes:
                _fail("independent ownership input exceeds its UTF-8 byte bound")
            continue
        if type(item) in {tuple, list}:
            sequence = cast("tuple[object, ...] | list[object]", item)
            stack.extend((child, depth + 1) for child in reversed(sequence))
            continue
        if type(item) is dict:
            mapping = cast("dict[object, object]", item)
            for key, child in reversed(tuple(mapping.items())):
                if type(key) is not str:
                    _fail("independent ownership input contains a non-string key")
                try:
                    string_bytes += len(key.encode("utf-8", errors="strict"))
                except UnicodeEncodeError:
                    _fail("independent ownership input contains invalid Unicode")
                if string_bytes > maximum_bytes:
                    _fail("independent ownership input exceeds its UTF-8 byte bound")
                stack.append((child, depth + 1))
            continue
        _fail("independent ownership input contains a foreign exact type")


def _canonical_bytes(value: object, *, maximum_bytes: int = _MAX_ROW_BYTES) -> bytes:
    _preflight_graph(value, maximum_bytes=maximum_bytes)
    try:
        encoded = json.dumps(
            value,
            allow_nan=False,
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        ).encode("utf-8", errors="strict")
    except (RecursionError, TypeError, UnicodeEncodeError, ValueError):
        _fail("independent ownership input is not canonical JSON")
    if not encoded or len(encoded) > maximum_bytes:
        _fail("independent ownership canonical JSON exceeds its byte bound")
    return encoded


def _canonical_sha(value: object, *, maximum_bytes: int = _MAX_ROW_BYTES) -> str:
    return hashlib.sha256(_canonical_bytes(value, maximum_bytes=maximum_bytes)).hexdigest()


def _ordered_root(*, kind: str, items: tuple[str, ...], maximum: int) -> str:
    if type(items) is not tuple or len(items) > maximum:
        _fail("independent ownership ordered root is foreign or over-bound")
    digest = hashlib.sha256()
    digest.update(b'{"count":')
    digest.update(str(len(items)).encode("ascii"))
    digest.update(b',"items":[')
    for ordinal, item in enumerate(items):
        _exact_sha(item, label="ordered-root item")
        if ordinal:
            digest.update(b",")
        digest.update(_canonical_bytes(item, maximum_bytes=256))
    digest.update(b'],"kind":')
    digest.update(_canonical_bytes(kind, maximum_bytes=256))
    digest.update(b',"schema_version":1}')
    return digest.hexdigest()


def _unit_root(*, raw_bundle_sha256: str, unit_rows: tuple[dict[str, object], ...]) -> str:
    digest = hashlib.sha256()
    digest.update(b'{"count":')
    digest.update(str(len(unit_rows)).encode("ascii"))
    digest.update(b',"items":[')
    for ordinal, row in enumerate(unit_rows):
        if ordinal:
            digest.update(b",")
        digest.update(_canonical_bytes(row["unit_sha256"], maximum_bytes=256))
    digest.update(b'],"kind":')
    digest.update(_canonical_bytes(_UNIT_ROOT_KIND, maximum_bytes=256))
    digest.update(b',"raw_authority_bundle_sha256":')
    digest.update(_canonical_bytes(raw_bundle_sha256, maximum_bytes=256))
    digest.update(b',"schema_version":1}')
    return digest.hexdigest()


def _strict_row(
    value: object,
    *,
    fields: tuple[str, ...],
    schema_version: int,
    label: str,
    maximum_bytes: int = _MAX_ROW_BYTES,
) -> dict[str, object]:
    if (
        type(maximum_bytes) is not int
        or maximum_bytes < 1
        or maximum_bytes > _MAX_INVENTORY_ROW_BYTES
    ):
        _fail("independent ownership row byte bound is invalid")
    if type(value) is not dict:
        _fail(f"{label} does not have its exact ordered plain-row shape")
    object_row = cast("dict[object, object]", value)
    if any(type(key) is not str for key in object_row) or tuple(object_row) != fields:
        _fail(f"{label} does not have its exact ordered plain-row shape")
    row = cast("dict[str, object]", value)
    if type(row["schema_version"]) is not int or row["schema_version"] != schema_version:
        _fail(f"{label} schema version is invalid")
    _preflight_graph(row, maximum_bytes=maximum_bytes)
    return row


def _strict_rows(
    value: object,
    *,
    fields: tuple[str, ...],
    schema_version: int,
    maximum: int,
    label: str,
) -> tuple[dict[str, object], ...]:
    if type(value) is not tuple or len(value) > maximum:
        _fail(f"{label} inventory is foreign or over-bound")
    return tuple(
        _strict_row(item, fields=fields, schema_version=schema_version, label=label)
        for item in value
    )


def _same_exact(left: object, right: object) -> bool:
    if type(left) is not type(right):
        return False
    if left is None:
        return True
    if type(left) in {str, int, bool}:
        return bool(left == right)
    if type(left) is tuple:
        left_tuple = left
        right_tuple = cast("tuple[object, ...]", right)
        return len(left_tuple) == len(right_tuple) and all(
            _same_exact(a, b) for a, b in zip(left_tuple, right_tuple, strict=True)
        )
    if type(left) is list:
        left_list = cast("list[object]", left)
        right_list = cast("list[object]", right)
        return len(left_list) == len(right_list) and all(
            _same_exact(a, b) for a, b in zip(left_list, right_list, strict=True)
        )
    if type(left) is dict:
        left_dict = cast("dict[str, object]", left)
        right_dict = cast("dict[str, object]", right)
        if tuple(left_dict) != tuple(right_dict):
            return False
        return all(_same_exact(left_dict[key], right_dict[key]) for key in left_dict)
    return False


def _identity_digest(
    row: dict[str, object],
    *,
    kind: str,
    digest_field: str,
) -> str:
    return _canonical_sha(
        {
            "schema_version": _SCHEMA_VERSION,
            "kind": kind,
            **{
                key: value
                for key, value in row.items()
                if key not in {"schema_version", digest_field}
            },
        }
    )


def _reject_duplicate_keys(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            _fail("expected-unit inventory JSON contains duplicate keys")
        result[key] = value
    return result


def _bounded_integer(token: str) -> int:
    if len(token) > 20:
        _fail("expected-unit inventory JSON contains an over-bound integer")
    value = int(token)
    if value < -_MAX_ORDINAL or value > _MAX_ORDINAL:
        _fail("expected-unit inventory JSON contains an over-bound integer")
    return value


def _reject_number(_token: str) -> Never:
    _fail("expected-unit inventory JSON contains a non-integer number")


def _preflight_inventory_json(encoded: bytes) -> None:
    """Bound JSON structure iteratively before the recursive stdlib decoder."""

    depth = 0
    nodes = 0
    tokens = 0
    index = 0
    while index < len(encoded):
        current = encoded[index]
        if current in b" \t\r\n":
            index += 1
            continue

        tokens += 1
        if tokens > _MAX_INVENTORY_JSON_TOKENS:
            _fail("expected-unit inventory JSON exceeds its lexical token bound")

        if current == 0x22:  # '"'
            nodes += 1
            index += 1
            while index < len(encoded):
                current = encoded[index]
                if current == 0x22:
                    index += 1
                    break
                if current < 0x20:
                    _fail("expected-unit inventory JSON contains an invalid string token")
                if current == 0x5C:  # '\\'
                    index += 2
                    if index > len(encoded):
                        _fail("expected-unit inventory JSON contains an incomplete escape")
                    continue
                index += 1
            else:
                _fail("expected-unit inventory JSON contains an unterminated string")
        elif current in {0x5B, 0x7B}:  # '[', '{'
            nodes += 1
            depth += 1
            if depth > _MAX_DEPTH + 1:
                _fail("expected-unit inventory JSON exceeds its lexical depth bound")
            index += 1
        elif current in {0x5D, 0x7D}:  # ']', '}'
            if depth == 0:
                _fail("expected-unit inventory JSON has an unmatched closing token")
            depth -= 1
            index += 1
        elif current in {0x2C, 0x3A}:  # ',', ':'
            index += 1
        else:
            nodes += 1
            index += 1
            while index < len(encoded) and encoded[index] not in b" \t\r\n[]{}:,":
                index += 1

        if nodes > _MAX_GRAPH_NODES:
            _fail("expected-unit inventory JSON exceeds its lexical node bound")

    if depth != 0:
        _fail("expected-unit inventory JSON has an unterminated container")


def _decode_inventory_units(value: object) -> tuple[dict[str, object], ...]:
    if type(value) is not str:
        _fail("expected-unit inventory JSON must be exact text")
    try:
        encoded = value.encode("utf-8", errors="strict")
    except UnicodeEncodeError:
        _fail("expected-unit inventory JSON is not strict UTF-8")
    if len(encoded) < 2 or len(encoded) > _MAX_INVENTORY_BYTES:
        _fail("expected-unit inventory JSON exceeds its byte bound")
    _preflight_inventory_json(encoded)
    try:
        decoded = json.loads(
            encoded,
            object_pairs_hook=_reject_duplicate_keys,
            parse_int=_bounded_integer,
            parse_float=_reject_number,
            parse_constant=_reject_number,
        )
    except IndependentLosslessOwnershipVerifierError:
        raise
    except (RecursionError, json.JSONDecodeError, TypeError, UnicodeDecodeError, ValueError):
        _fail("expected-unit inventory JSON is invalid")
    if type(decoded) is not list or len(decoded) > _MAX_UNITS:
        _fail("expected-unit inventory JSON must contain one bounded exact array")
    _preflight_graph(decoded, maximum_bytes=_MAX_INVENTORY_BYTES)
    if _canonical_bytes(decoded, maximum_bytes=_MAX_INVENTORY_BYTES) != encoded:
        _fail("expected-unit inventory JSON is not canonical")
    rows: list[dict[str, object]] = []
    for item in cast("list[object]", decoded):
        if type(item) is not dict:
            _fail("expected-unit inventory JSON contains a non-row member")
        decoded_row = cast("dict[str, object]", item)
        if tuple(decoded_row) != tuple(sorted(_UNIT_FIELDS)):
            _fail("expected-unit inventory JSON contains a noncanonical unit row")
        rows.append({field: decoded_row[field] for field in _UNIT_FIELDS})
    return tuple(rows)


@dataclass(frozen=True, slots=True)
class _SourceRecord:
    source_record_sha256: str
    observation_sha256: str
    observation_record_sha256: str
    owner_kind: str
    occurrence_sha256: str | None
    representation_kind: str
    expected_unit_sha256: str | None
    expected_unit_ordinal: int | None
    assignment_sha256: str | None


@dataclass(frozen=True, slots=True)
class _LiveLocalOwner:
    expected_unit_sha256: str
    expected_unit_ordinal: int
    assignment_sha256: str
    semantic_owner: tuple[object, ...]


@dataclass(frozen=True, slots=True)
class _LiveSourceClosure:
    records: tuple[_SourceRecord, ...]
    semantic_owner_vector: tuple[tuple[object, ...], ...]


@dataclass(frozen=True, slots=True)
class IndependentLosslessOwnershipVerificationV1:
    """Immutable value-free result of one independent ownership traversal."""

    verification_sha256: str
    raw_authority_bundle_sha256: str
    ownership_receipt_sha256: str
    expected_unit_inventory_sha256: str
    expected_unit_root_sha256: str
    representation_assignment_root_sha256: str
    observation_count: int
    occurrence_count: int
    partition_count: int
    binding_count: int
    result_cell_count: int
    stats_lossless_record_count: int
    live_lossless_record_count: int
    source_record_count: int
    source_record_root_sha256: str

    schema_version: ClassVar[int] = _SCHEMA_VERSION
    kind: ClassVar[str] = _VERIFICATION_KIND


def _check_unit_rows(
    value: object,
    *,
    raw_bundle_sha256: str,
) -> tuple[dict[str, object], ...]:
    rows = _strict_rows(
        value,
        fields=_UNIT_FIELDS,
        schema_version=_SCHEMA_VERSION,
        maximum=_MAX_UNITS,
        label="expected-unit row",
    )
    seen_units: set[str] = set()
    seen_occurrences: set[tuple[str, str]] = set()
    active_observation: str | None = None
    active_observation_ordinal = -1
    completed_observations: set[str] = set()
    expected_occurrence_ordinal = 0
    response_seen = False
    for ordinal, row in enumerate(rows):
        unit_sha256 = _exact_sha(row["unit_sha256"], label="expected-unit identity")
        unit_bundle_sha256 = _exact_sha(
            row["raw_authority_bundle_sha256"],
            label="expected-unit raw-authority bundle",
        )
        if unit_bundle_sha256 != raw_bundle_sha256:
            _fail("expected-unit row belongs to a foreign raw bundle")
        if (
            _exact_int(row["unit_ordinal"], label="expected-unit ordinal", maximum=_MAX_ORDINAL)
            != ordinal
        ):
            _fail("expected-unit order differs from its declared ordinal")
        observation_sha256 = _exact_sha(
            row["observation_sha256"], label="expected-unit observation"
        )
        observation_ordinal = _exact_int(
            row["observation_ordinal"],
            label="expected-unit observation ordinal",
            maximum=_MAX_OBSERVATIONS - 1,
        )
        unit_kind = row["unit_kind"]
        if type(unit_kind) is not str or unit_kind not in _UNIT_KINDS:
            _fail("expected-unit kind is outside its closed domain")
        occurrence_sha256 = _optional_sha(
            row["occurrence_sha256"], label="expected-unit occurrence"
        )
        occurrence_ordinal = _optional_int(
            row["occurrence_ordinal"],
            label="expected-unit occurrence ordinal",
            maximum=_MAX_UNITS - 1,
        )
        if unit_kind == "result_occurrence":
            if occurrence_sha256 is None or occurrence_ordinal is None:
                _fail("result-occurrence unit lacks exact occurrence identity")
        elif occurrence_sha256 is not None or occurrence_ordinal is not None:
            _fail("response unit fabricates occurrence identity")
        payload = {
            "kind": _UNIT_KIND,
            "schema_version": _SCHEMA_VERSION,
            "raw_authority_bundle_sha256": raw_bundle_sha256,
            "unit_ordinal": ordinal,
            "observation_sha256": observation_sha256,
            "observation_ordinal": observation_ordinal,
            "unit_kind": unit_kind,
            "occurrence_sha256": occurrence_sha256,
            "occurrence_ordinal": occurrence_ordinal,
        }
        if unit_sha256 != _canonical_sha(payload):
            _fail("expected-unit digest differs from its exact identity")
        if unit_sha256 in seen_units:
            _fail("expected-unit inventory contains a duplicate identity")
        seen_units.add(unit_sha256)

        if observation_sha256 != active_observation:
            if observation_sha256 in completed_observations:
                _fail("expected-unit inventory reopens a completed observation")
            completed_observations.add(observation_sha256)
            active_observation = observation_sha256
            active_observation_ordinal += 1
            expected_occurrence_ordinal = 0
            response_seen = False
        if observation_ordinal != active_observation_ordinal:
            _fail("expected-unit observation order is not canonical and contiguous")
        if unit_kind == "result_occurrence":
            if response_seen or occurrence_ordinal != expected_occurrence_ordinal:
                _fail("expected-unit occurrence order is not canonical and contiguous")
            occurrence_identity = (observation_sha256, cast("str", occurrence_sha256))
            if occurrence_identity in seen_occurrences:
                _fail("expected-unit inventory contains a duplicate occurrence")
            seen_occurrences.add(occurrence_identity)
            expected_occurrence_ordinal += 1
        else:
            if response_seen:
                _fail("expected-unit observation contains several response units")
            if unit_kind == "response_fixed_zero" and expected_occurrence_ordinal != 0:
                _fail("fixed-zero response unit follows a result occurrence")
            response_seen = True
    return rows


def _check_inventory_row(
    value: object,
    *,
    raw_bundle_sha256: str,
    unit_rows: tuple[dict[str, object], ...],
) -> dict[str, object]:
    row = _strict_row(
        value,
        fields=_INVENTORY_FIELDS,
        schema_version=_SCHEMA_VERSION,
        label="expected-unit inventory row",
        maximum_bytes=_MAX_INVENTORY_ROW_BYTES,
    )
    inventory_bundle_sha256 = _exact_sha(
        row["raw_authority_bundle_sha256"],
        label="expected-unit inventory raw-authority bundle",
    )
    if inventory_bundle_sha256 != raw_bundle_sha256:
        _fail("expected-unit inventory belongs to a foreign raw bundle")
    count = _exact_int(row["unit_count"], label="expected-unit inventory count", maximum=_MAX_UNITS)
    if count != len(unit_rows):
        _fail("expected-unit inventory count differs from supplied unit rows")
    decoded_rows = _decode_inventory_units(row["units_json"])
    if not _same_exact(decoded_rows, unit_rows):
        _fail("expected-unit inventory JSON differs from supplied unit rows")
    unit_root_sha256 = _exact_sha(row["unit_root_sha256"], label="expected-unit inventory root")
    expected_root = _unit_root(raw_bundle_sha256=raw_bundle_sha256, unit_rows=unit_rows)
    if unit_root_sha256 != expected_root:
        _fail("expected-unit inventory root differs from its ordered denominator")
    inventory_sha256 = _exact_sha(row["inventory_sha256"], label="expected-unit inventory identity")
    identity = {
        "kind": _INVENTORY_KIND,
        "schema_version": _SCHEMA_VERSION,
        "raw_authority_bundle_sha256": raw_bundle_sha256,
        "unit_count": len(unit_rows),
        "unit_root_sha256": expected_root,
        "units": list(unit_rows),
    }
    if inventory_sha256 != _canonical_sha(identity, maximum_bytes=_MAX_INVENTORY_BYTES):
        _fail("expected-unit inventory digest differs from its exact contents")
    return row


def _check_assignment_rows(
    value: object,
    *,
    raw_bundle_sha256: str,
    unit_rows: tuple[dict[str, object], ...],
) -> tuple[dict[str, object], ...]:
    rows = _strict_rows(
        value,
        fields=_ASSIGNMENT_FIELDS,
        schema_version=_SCHEMA_VERSION,
        maximum=_MAX_UNITS,
        label="representation-assignment row",
    )
    if len(rows) != len(unit_rows):
        _fail("representation-assignment denominator differs from expected units")
    seen: set[str] = set()
    for ordinal, (row, unit) in enumerate(zip(rows, unit_rows, strict=True)):
        assignment_sha256 = _exact_sha(row["assignment_sha256"], label="representation assignment")
        assignment_bundle_sha256 = _exact_sha(
            row["raw_authority_bundle_sha256"],
            label="representation-assignment raw-authority bundle",
        )
        assignment_unit_sha256 = _exact_sha(
            row["unit_sha256"], label="representation-assignment expected unit"
        )
        assignment_unit_ordinal = _exact_int(
            row["unit_ordinal"],
            label="representation-assignment unit ordinal",
            maximum=_MAX_UNITS - 1,
        )
        if assignment_sha256 in seen:
            _fail("representation-assignment inventory contains a duplicate")
        seen.add(assignment_sha256)
        if (
            assignment_bundle_sha256 != raw_bundle_sha256
            or assignment_unit_sha256 != unit["unit_sha256"]
            or assignment_unit_ordinal != ordinal
        ):
            _fail("representation assignment references a foreign or reordered unit")
        source_input_kind = row["source_input_kind"]
        representation_kind = row["representation_kind"]
        if type(source_input_kind) is not str or source_input_kind not in _SOURCE_INPUT_KINDS:
            _fail("representation assignment has a foreign source-input kind")
        if type(representation_kind) is not str or representation_kind not in _REPRESENTATIONS:
            _fail("representation assignment has a foreign representation kind")
        unit_kind = unit["unit_kind"]
        if unit_kind == "result_occurrence":
            if representation_kind not in _RESULT_REPRESENTATIONS:
                _fail("result-occurrence unit uses a response representation")
        elif unit_kind == "response_residual":
            if representation_kind != "response_lossless_records_v1":
                _fail("response-residual unit uses a foreign representation")
        elif representation_kind != "response_fixed_zero_v1":
            _fail("fixed-zero unit uses a foreign representation")
        identity = {
            "kind": _ASSIGNMENT_KIND,
            "schema_version": _SCHEMA_VERSION,
            "raw_authority_bundle_sha256": raw_bundle_sha256,
            "unit_sha256": unit["unit_sha256"],
            "unit_ordinal": ordinal,
            "source_input_kind": source_input_kind,
            "representation_kind": representation_kind,
        }
        if assignment_sha256 != _canonical_sha(identity):
            _fail("representation-assignment digest differs from its exact identity")
    return rows


def _check_raw_observations(value: object) -> tuple[dict[str, object], ...]:
    rows = _strict_rows(
        value,
        fields=_RAW_OBSERVATION_FIELDS,
        schema_version=_RAW_SCHEMA_VERSION,
        maximum=_MAX_OBSERVATIONS,
        label="raw observation projection row",
    )
    seen_observations: set[str] = set()
    seen_records: set[str] = set()
    seen_semantic_coordinates: set[tuple[object, ...]] = set()
    semantic_keys: list[tuple[object, ...]] = []
    for row in rows:
        observation_sha256 = _exact_sha(row["observation_sha256"], label="raw observation")
        observation_record_sha256 = _exact_sha(
            row["observation_record_sha256"], label="raw observation record"
        )
        if observation_sha256 in seen_observations or observation_record_sha256 in seen_records:
            _fail("raw observation inventory contains a duplicate identity")
        seen_observations.add(observation_sha256)
        seen_records.add(observation_record_sha256)
        logical_invocation_sha256 = _exact_sha(
            row["logical_invocation_sha256"], label="raw observation logical invocation"
        )
        semantic_request_sha256 = _exact_sha(
            row["semantic_request_sha256"], label="raw observation semantic request"
        )
        provider_call_ordinal = _exact_int(
            row["provider_call_ordinal"],
            label="raw observation provider-call ordinal",
            maximum=_MAX_ORDINAL,
        )
        page_ordinal = _optional_int(
            row["page_ordinal"],
            label="raw observation page ordinal",
            maximum=_MAX_ORDINAL,
        )
        provider_call_role = row["provider_call_role"]
        if type(provider_call_role) is not str or not provider_call_role:
            _fail("raw observation provider-call role must be exact nonempty text")
        provider_call_sha256 = _exact_sha(
            row["provider_call_sha256"], label="raw observation provider call"
        )
        retry_ordinal = _exact_int(
            row["retry_ordinal"],
            label="raw observation retry ordinal",
            maximum=_MAX_ORDINAL,
        )
        request_ordinal = _exact_int(
            row["request_ordinal"],
            label="raw observation request ordinal",
            maximum=_MAX_ORDINAL,
        )
        source_family = _exact_literal(
            row["source_family"],
            choices=_RAW_SOURCE_FAMILIES,
            label="raw observation source family",
        )
        page_discriminator = 0 if page_ordinal is None else 1
        canonical_page_ordinal = 0 if page_ordinal is None else page_ordinal
        semantic_key = (
            logical_invocation_sha256,
            semantic_request_sha256,
            provider_call_ordinal,
            page_discriminator,
            canonical_page_ordinal,
            provider_call_role,
            provider_call_sha256,
            retry_ordinal,
            request_ordinal,
            observation_sha256,
        )
        coordinate = semantic_key[:-1]
        if coordinate in seen_semantic_coordinates:
            _fail("raw observation inventory repeats one semantic-order coordinate")
        seen_semantic_coordinates.add(coordinate)
        semantic_keys.append(semantic_key)
        _exact_literal(
            row["lifecycle"],
            choices=_RAW_SELECTED_LIFECYCLES,
            label="raw observation lifecycle",
        )
        outcome = _exact_literal(
            row["outcome"],
            choices=_RAW_SUCCESS_OUTCOMES,
            label="raw observation outcome",
        )
        body_disposition = _exact_literal(
            row["body_disposition"],
            choices=_RAW_BODY_DISPOSITIONS,
            label="raw observation body disposition",
        )
        if (source_family == "static") != (outcome == "static_snapshot_success"):
            _fail("raw observation source family contradicts its successful outcome")
        if (source_family == "static") != (body_disposition == "declared_bodyless"):
            _fail("raw observation source family contradicts its exact input authority")
        _exact_int(
            row["result_occurrence_count"],
            label="raw observation occurrence count",
            maximum=_MAX_UNITS,
        )
        _exact_sha(row["result_occurrences_sha256"], label="raw observation occurrence root")
        _exact_int(
            row["route_landing_count"],
            label="raw observation landing count",
            maximum=_MAX_PARTITIONS,
        )
        _exact_sha(row["route_landings_sha256"], label="raw observation landing root")
    if semantic_keys != sorted(semantic_keys):
        _fail("raw observations are not in canonical semantic order")
    return rows


def _observation_source_input(row: dict[str, object]) -> str:
    if row["body_disposition"] == "public_parser_input":
        return "parser_input_body"
    return "declared_bodyless_packet"


def _check_raw_occurrences(
    value: object,
    *,
    observations: tuple[dict[str, object], ...],
) -> tuple[dict[str, object], ...]:
    rows = _strict_rows(
        value,
        fields=_RAW_OCCURRENCE_FIELDS,
        schema_version=_RAW_SCHEMA_VERSION,
        maximum=_MAX_UNITS,
        label="raw occurrence projection row",
    )
    observation_order = {
        cast("str", row["observation_sha256"]): ordinal for ordinal, row in enumerate(observations)
    }
    grouped: dict[str, list[str]] = {key: [] for key in observation_order}
    seen: set[str] = set()
    last_observation_ordinal = -1
    for row in rows:
        occurrence_sha256 = _exact_sha(row["occurrence_sha256"], label="raw occurrence")
        observation_sha256 = _exact_sha(
            row["observation_sha256"], label="raw occurrence observation"
        )
        observation_ordinal = observation_order.get(observation_sha256)
        if observation_ordinal is None:
            _fail("raw occurrence references a foreign observation")
        if observation_ordinal < last_observation_ordinal:
            _fail("raw occurrence inventory reopens a completed observation")
        last_observation_ordinal = observation_ordinal
        expected_ordinal = len(grouped[observation_sha256])
        if (
            _exact_int(
                row["occurrence_ordinal"],
                label="raw occurrence ordinal",
                maximum=_MAX_UNITS - 1,
            )
            != expected_ordinal
        ):
            _fail("raw occurrence order is not canonical and contiguous")
        _exact_literal(
            row["landing_disposition"],
            choices=_RAW_LANDING_DISPOSITIONS,
            label="raw occurrence landing disposition",
        )
        if occurrence_sha256 in seen:
            _fail("raw occurrence inventory contains a duplicate identity")
        seen.add(occurrence_sha256)
        grouped[observation_sha256].append(occurrence_sha256)

    for observation in observations:
        observation_sha256 = cast("str", observation["observation_sha256"])
        occurrence_ids = grouped[observation_sha256]
        if observation["result_occurrence_count"] != len(occurrence_ids) or observation[
            "result_occurrences_sha256"
        ] != _canonical_sha(occurrence_ids, maximum_bytes=_MAX_INVENTORY_BYTES):
            _fail("raw observation occurrence denominator differs from occurrence rows")
    return rows


def _occurrence_representation(
    *,
    observation: dict[str, object],
    occurrence: dict[str, object],
) -> str:
    disposition = occurrence["landing_disposition"]
    source_family = observation["source_family"]
    if source_family in {"stats", "static"} and disposition == "wide_only":
        return "rectangular_result_cells_v1"
    if source_family == "stats" and disposition in {
        "lossless_only",
        "wide_plus_lossless",
    }:
        return "stats_lossless_records_v1"
    if source_family == "live" and disposition in {
        "wide_only",
        "lossless_only",
        "wide_plus_lossless",
    }:
        return "live_lossless_nodes_v1"
    _fail("raw occurrence has no closed public-value representation")


def _check_raw_landings(
    value: object,
    *,
    observations: tuple[dict[str, object], ...],
) -> tuple[dict[str, object], ...]:
    rows = _strict_rows(
        value,
        fields=_RAW_LANDING_FIELDS,
        schema_version=_RAW_SCHEMA_VERSION,
        maximum=_MAX_PARTITIONS,
        label="raw landing projection row",
    )
    observation_order = {
        cast("str", row["observation_sha256"]): ordinal for ordinal, row in enumerate(observations)
    }
    grouped: dict[str, list[str]] = {key: [] for key in observation_order}
    seen: set[str] = set()
    last_observation_ordinal = -1
    empty_source_root = _canonical_sha([], maximum_bytes=_MAX_INVENTORY_BYTES)
    for row in rows:
        landing_sha256 = _exact_sha(row["landing_sha256"], label="raw landing")
        observation_sha256 = _exact_sha(row["observation_sha256"], label="raw landing observation")
        observation_ordinal = observation_order.get(observation_sha256)
        if observation_ordinal is None:
            _fail("raw landing references a foreign observation")
        if observation_ordinal < last_observation_ordinal:
            _fail("raw landing inventory reopens a completed observation")
        last_observation_ordinal = observation_ordinal
        expected_ordinal = len(grouped[observation_sha256])
        if (
            _exact_int(
                row["route_ordinal"],
                label="raw landing route ordinal",
                maximum=_MAX_PARTITIONS - 1,
            )
            != expected_ordinal
        ):
            _fail("raw landing order is not canonical and contiguous")
        if landing_sha256 in seen:
            _fail("raw landing inventory contains a duplicate identity")
        seen.add(landing_sha256)
        grouped[observation_sha256].append(landing_sha256)
        landing_semantic = _exact_literal(
            row["landing_semantic"],
            choices=_RAW_LANDING_SEMANTICS,
            label="raw landing semantic",
        )
        source_count = _exact_int(
            row["source_occurrence_count"],
            label="raw landing source occurrence count",
            maximum=_MAX_UNITS,
        )
        source_root = _exact_sha(
            row["source_occurrences_sha256"], label="raw landing source occurrence root"
        )
        persisted_count = _exact_int(
            row["persisted_row_count"],
            label="raw landing persisted row count",
            maximum=_MAX_BINDINGS,
        )
        if landing_semantic == "response_fixed_zero" and (
            source_count != 0 or source_root != empty_source_root or persisted_count != 0
        ):
            _fail("fixed-zero landing contradicts its exact empty proof")

    for observation in observations:
        observation_sha256 = cast("str", observation["observation_sha256"])
        landing_ids = grouped[observation_sha256]
        if observation["route_landing_count"] != len(landing_ids) or observation[
            "route_landings_sha256"
        ] != _canonical_sha(landing_ids, maximum_bytes=_MAX_INVENTORY_BYTES):
            _fail("raw observation landing denominator differs from landing rows")
    return rows


def _check_result_cell_sources(
    value: object,
    *,
    observations_by_sha: dict[str, dict[str, object]],
    occurrence_owner: dict[str, str],
    occurrences_by_sha: dict[str, dict[str, object]],
) -> tuple[_SourceRecord, ...]:
    rows = _strict_rows(
        value,
        fields=_RESULT_CELL_FIELDS,
        schema_version=_RAW_SCHEMA_VERSION,
        maximum=_MAX_BINDINGS,
        label="result-cell source projection row",
    )
    expected_cell_ordinal: dict[str, int] = {}
    completed_occurrences: set[str] = set()
    active_occurrence: str | None = None
    last_occurrence_position = -1
    occurrence_positions = {key: index for index, key in enumerate(occurrences_by_sha)}
    result: list[_SourceRecord] = []
    for row in rows:
        source_sha256 = _exact_sha(row["cell_sha256"], label="result-cell source")
        observation_sha256 = _exact_sha(row["observation_sha256"], label="result-cell observation")
        occurrence_sha256 = _exact_sha(row["occurrence_sha256"], label="result-cell occurrence")
        observation = observations_by_sha.get(observation_sha256)
        occurrence = occurrences_by_sha.get(occurrence_sha256)
        if (
            observation is None
            or occurrence is None
            or occurrence_owner.get(occurrence_sha256) != observation_sha256
            or observation["source_family"] not in {"stats", "static"}
            or _occurrence_representation(
                observation=observation,
                occurrence=occurrence,
            )
            != "rectangular_result_cells_v1"
        ):
            _fail("result-cell source references a foreign occurrence or observation")
        occurrence_position = occurrence_positions[occurrence_sha256]
        if occurrence_position < last_occurrence_position:
            _fail("result-cell source inventory reopens a completed occurrence")
        last_occurrence_position = occurrence_position
        if occurrence_sha256 != active_occurrence:
            if occurrence_sha256 in completed_occurrences:
                _fail("result-cell source inventory reopens a completed occurrence")
            completed_occurrences.add(occurrence_sha256)
            active_occurrence = occurrence_sha256
        ordinal = expected_cell_ordinal.get(occurrence_sha256, 0)
        if (
            _exact_int(row["cell_ordinal"], label="result-cell ordinal", maximum=_MAX_BINDINGS - 1)
            != ordinal
        ):
            _fail("result-cell source order is not canonical and contiguous")
        expected_cell_ordinal[occurrence_sha256] = ordinal + 1
        result.append(
            _SourceRecord(
                source_record_sha256=source_sha256,
                observation_sha256=observation_sha256,
                observation_record_sha256=cast("str", observation["observation_record_sha256"]),
                owner_kind="result_occurrence",
                occurrence_sha256=occurrence_sha256,
                representation_kind="rectangular_result_cells_v1",
                expected_unit_sha256=None,
                expected_unit_ordinal=None,
                assignment_sha256=None,
            )
        )
    return tuple(result)


def _check_stats_sources(
    value: object,
    *,
    raw_bundle_sha256: str,
    observations_by_sha: dict[str, dict[str, object]],
    occurrence_owner: dict[str, str],
) -> tuple[_SourceRecord, ...]:
    rows = _strict_rows(
        value,
        fields=_STATS_SOURCE_FIELDS,
        schema_version=_SCHEMA_VERSION,
        maximum=_MAX_BINDINGS,
        label="stats-lossless source projection row",
    )
    result: list[_SourceRecord] = []
    next_observation_ordinal: dict[str, int] = {}
    last_observation_position = -1
    observation_positions = {key: index for index, key in enumerate(observations_by_sha)}
    for row in rows:
        source_sha256 = _exact_sha(row["record_sha256"], label="stats-lossless source")
        observation_sha256 = _exact_sha(
            row["observation_sha256"], label="stats-lossless observation"
        )
        source_bundle_sha256 = _exact_sha(
            row["raw_authority_bundle_sha256"],
            label="stats-lossless raw-authority bundle",
        )
        observation_record_sha256 = _exact_sha(
            row["observation_record_sha256"],
            label="stats-lossless observation record",
        )
        observation = observations_by_sha.get(observation_sha256)
        if (
            source_bundle_sha256 != raw_bundle_sha256
            or observation is None
            or observation_record_sha256 != observation["observation_record_sha256"]
            or observation["source_family"] != "stats"
        ):
            _fail("stats-lossless source belongs to a foreign bundle or observation")
        position = observation_positions[observation_sha256]
        if position < last_observation_position:
            _fail("stats-lossless source inventory reopens a completed observation")
        last_observation_position = position
        expected_observation_ordinal = next_observation_ordinal.get(observation_sha256, 0)
        if (
            _exact_int(
                row["global_record_ordinal"],
                label="stats-lossless global record ordinal",
                maximum=_MAX_BINDINGS - 1,
            )
            != expected_observation_ordinal
        ):
            _fail("stats-lossless observation source order is not canonical and contiguous")
        next_observation_ordinal[observation_sha256] = expected_observation_ordinal + 1
        owner_kind = _exact_literal(
            row["owner_kind"],
            choices=_SOURCE_OWNER_KINDS,
            label="stats-lossless ownership discriminator",
        )
        occurrence_sha256 = _optional_sha(
            row["occurrence_sha256"], label="stats-lossless occurrence"
        )
        representation_kind = _exact_literal(
            row["representation_kind"],
            choices=_REPRESENTATIONS,
            label="stats-lossless representation kind",
        )
        if owner_kind == "result_occurrence":
            if (
                occurrence_sha256 is None
                or occurrence_owner.get(occurrence_sha256) != observation_sha256
                or representation_kind != "stats_lossless_records_v1"
            ):
                _fail("stats-lossless result source has a foreign ownership shape")
        elif owner_kind == "response_residual" and (
            occurrence_sha256 is not None or representation_kind != "response_lossless_records_v1"
        ):
            _fail("stats-lossless residual source has a foreign ownership shape")
        result.append(
            _SourceRecord(
                source_record_sha256=source_sha256,
                observation_sha256=observation_sha256,
                observation_record_sha256=cast("str", observation["observation_record_sha256"]),
                owner_kind=owner_kind,
                occurrence_sha256=occurrence_sha256,
                representation_kind=representation_kind,
                expected_unit_sha256=None,
                expected_unit_ordinal=None,
                assignment_sha256=None,
            )
        )
    return tuple(result)


def _live_local_owner(
    *,
    raw_bundle_sha256: str,
    unit_ordinal: int,
    observation_sha256: str,
    observation_ordinal: int,
    unit_kind: str,
    occurrence_sha256: str | None,
    occurrence_ordinal: int | None,
    source_input_kind: str,
    representation_kind: str,
) -> _LiveLocalOwner:
    unit_identity = {
        "kind": _UNIT_KIND,
        "schema_version": _SCHEMA_VERSION,
        "raw_authority_bundle_sha256": raw_bundle_sha256,
        "unit_ordinal": unit_ordinal,
        "observation_sha256": observation_sha256,
        "observation_ordinal": observation_ordinal,
        "unit_kind": unit_kind,
        "occurrence_sha256": occurrence_sha256,
        "occurrence_ordinal": occurrence_ordinal,
    }
    expected_unit_sha256 = _canonical_sha(unit_identity)
    assignment_sha256 = _canonical_sha(
        {
            "kind": _ASSIGNMENT_KIND,
            "schema_version": _SCHEMA_VERSION,
            "raw_authority_bundle_sha256": raw_bundle_sha256,
            "unit_sha256": expected_unit_sha256,
            "unit_ordinal": unit_ordinal,
            "source_input_kind": source_input_kind,
            "representation_kind": representation_kind,
        }
    )
    return _LiveLocalOwner(
        expected_unit_sha256=expected_unit_sha256,
        expected_unit_ordinal=unit_ordinal,
        assignment_sha256=assignment_sha256,
        semantic_owner=(
            observation_sha256,
            unit_kind,
            occurrence_sha256,
            occurrence_ordinal,
            source_input_kind,
            representation_kind,
        ),
    )


def _check_live_sources(
    value: object,
    *,
    raw_bundle_sha256: str,
    observations: tuple[dict[str, object], ...],
    raw_occurrences: tuple[dict[str, object], ...],
) -> _LiveSourceClosure:
    rows = _strict_rows(
        value,
        fields=_LIVE_SOURCE_FIELDS,
        schema_version=_SCHEMA_VERSION,
        maximum=_MAX_BINDINGS,
        label="live-lossless source projection row",
    )
    result: list[_SourceRecord] = []
    next_observation_ordinal: dict[str, int] = {}
    last_observation_position = -1
    observations_by_sha = {cast("str", row["observation_sha256"]): row for row in observations}
    observation_positions = {
        cast("str", row["observation_sha256"]): index for index, row in enumerate(observations)
    }
    occurrence_owner = {
        cast("str", row["occurrence_sha256"]): cast("str", row["observation_sha256"])
        for row in raw_occurrences
    }
    for ordinal, row in enumerate(rows):
        source_sha256 = _exact_sha(row["source_item_sha256"], label="live-lossless source")
        observation_sha256 = _exact_sha(
            row["observation_sha256"], label="live-lossless observation"
        )
        source_bundle_sha256 = _exact_sha(
            row["raw_authority_bundle_sha256"],
            label="live-lossless raw-authority bundle",
        )
        observation_record_sha256 = _exact_sha(
            row["observation_record_sha256"],
            label="live-lossless observation record",
        )
        observation = observations_by_sha.get(observation_sha256)
        if (
            source_bundle_sha256 != raw_bundle_sha256
            or observation is None
            or observation_record_sha256 != observation["observation_record_sha256"]
            or observation["source_family"] != "live"
        ):
            _fail("live-lossless source belongs to a foreign bundle or observation")
        position = observation_positions[observation_sha256]
        if position < last_observation_position:
            _fail("live-lossless source inventory reopens a completed observation")
        last_observation_position = position
        if (
            _exact_int(
                row["global_record_ordinal"],
                label="live-lossless global record ordinal",
                maximum=_MAX_BINDINGS - 1,
            )
            != ordinal
        ):
            _fail("live-lossless global source order is not canonical and contiguous")
        expected_observation_ordinal = next_observation_ordinal.get(observation_sha256, 0)
        if (
            _exact_int(
                row["observation_record_ordinal"],
                label="live-lossless observation record ordinal",
                maximum=_MAX_BINDINGS - 1,
            )
            != expected_observation_ordinal
        ):
            _fail("live-lossless observation source order is not canonical and contiguous")
        next_observation_ordinal[observation_sha256] = expected_observation_ordinal + 1
        owner_kind = _exact_literal(
            row["ownership_kind"],
            choices=_SOURCE_OWNER_KINDS,
            label="live-lossless ownership discriminator",
        )
        occurrence_sha256 = _optional_sha(
            row["raw_occurrence_sha256"], label="live-lossless occurrence"
        )
        representation_kind = _exact_literal(
            row["representation_kind"],
            choices=_REPRESENTATIONS,
            label="live-lossless representation kind",
        )
        if owner_kind == "result_occurrence":
            if (
                occurrence_sha256 is None
                or occurrence_owner.get(occurrence_sha256) != observation_sha256
                or representation_kind != "live_lossless_nodes_v1"
            ):
                _fail("live-lossless result source has a foreign ownership shape")
        elif owner_kind == "response_residual" and (
            occurrence_sha256 is not None or representation_kind != "response_lossless_records_v1"
        ):
            _fail("live-lossless residual source has a foreign ownership shape")
        result.append(
            _SourceRecord(
                source_record_sha256=source_sha256,
                observation_sha256=observation_sha256,
                observation_record_sha256=cast("str", observation["observation_record_sha256"]),
                owner_kind=owner_kind,
                occurrence_sha256=occurrence_sha256,
                representation_kind=representation_kind,
                expected_unit_sha256=_exact_sha(
                    row["expected_unit_sha256"], label="live-lossless expected unit"
                ),
                expected_unit_ordinal=_exact_int(
                    row["expected_unit_ordinal"],
                    label="live-lossless expected-unit ordinal",
                    maximum=_MAX_UNITS - 1,
                ),
                assignment_sha256=_exact_sha(
                    row["representation_assignment_sha256"],
                    label="live-lossless representation assignment",
                ),
            )
        )

    live_observations = tuple(row for row in observations if row["source_family"] == "live")
    occurrences_by_observation: dict[str, list[dict[str, object]]] = {
        cast("str", row["observation_sha256"]): [] for row in live_observations
    }
    for occurrence in raw_occurrences:
        observation_sha256 = cast("str", occurrence["observation_sha256"])
        if observation_sha256 in occurrences_by_observation:
            occurrences_by_observation[observation_sha256].append(occurrence)
    residual_observations = {
        source.observation_sha256 for source in result if source.owner_kind == "response_residual"
    }

    local_owners: dict[tuple[str, str, str | None], _LiveLocalOwner] = {}
    semantic_owner_vector: list[tuple[object, ...]] = []
    next_unit_ordinal = 0
    for observation_ordinal, observation in enumerate(live_observations):
        observation_sha256 = cast("str", observation["observation_sha256"])
        source_input_kind = _observation_source_input(observation)
        for occurrence in occurrences_by_observation[observation_sha256]:
            occurrence_sha256 = cast("str", occurrence["occurrence_sha256"])
            occurrence_ordinal = cast("int", occurrence["occurrence_ordinal"])
            owner = _live_local_owner(
                raw_bundle_sha256=raw_bundle_sha256,
                unit_ordinal=next_unit_ordinal,
                observation_sha256=observation_sha256,
                observation_ordinal=observation_ordinal,
                unit_kind="result_occurrence",
                occurrence_sha256=occurrence_sha256,
                occurrence_ordinal=occurrence_ordinal,
                source_input_kind=source_input_kind,
                representation_kind="live_lossless_nodes_v1",
            )
            local_owners[(observation_sha256, "result_occurrence", occurrence_sha256)] = owner
            semantic_owner_vector.append(owner.semantic_owner)
            next_unit_ordinal += 1
        if observation_sha256 in residual_observations:
            owner = _live_local_owner(
                raw_bundle_sha256=raw_bundle_sha256,
                unit_ordinal=next_unit_ordinal,
                observation_sha256=observation_sha256,
                observation_ordinal=observation_ordinal,
                unit_kind="response_residual",
                occurrence_sha256=None,
                occurrence_ordinal=None,
                source_input_kind=source_input_kind,
                representation_kind="response_lossless_records_v1",
            )
            local_owners[(observation_sha256, "response_residual", None)] = owner
            semantic_owner_vector.append(owner.semantic_owner)
            next_unit_ordinal += 1

    for source in result:
        owner = local_owners.get(
            (source.observation_sha256, source.owner_kind, source.occurrence_sha256)
        )
        if owner is None or (
            source.expected_unit_sha256 != owner.expected_unit_sha256
            or source.expected_unit_ordinal != owner.expected_unit_ordinal
            or source.assignment_sha256 != owner.assignment_sha256
            or source.representation_kind != owner.semantic_owner[-1]
        ):
            _fail("live source contradicts its genuine local unit or assignment identity")
    return _LiveSourceClosure(
        records=tuple(result),
        semantic_owner_vector=tuple(semantic_owner_vector),
    )


def _check_ownership_bindings(value: object) -> tuple[dict[str, object], ...]:
    rows = _strict_rows(
        value,
        fields=_OWNERSHIP_BINDING_FIELDS,
        schema_version=_SCHEMA_VERSION,
        maximum=_MAX_BINDINGS,
        label="lossless-ownership binding row",
    )
    for row in rows:
        for field in (
            "binding_sha256",
            "raw_authority_bundle_sha256",
            "observation_record_sha256",
            "observation_sha256",
            "source_record_sha256",
            "unit_sha256",
            "assignment_sha256",
        ):
            _exact_sha(row[field], label=f"ownership binding {field}")
        for field, maximum in (
            ("observation_ordinal", _MAX_OBSERVATIONS - 1),
            ("binding_ordinal", _MAX_BINDINGS - 1),
            ("observation_record_ordinal", _MAX_BINDINGS - 1),
            ("partition_ordinal", _MAX_PARTITIONS - 1),
            ("unit_ordinal", _MAX_UNITS - 1),
        ):
            _exact_int(row[field], label=f"ownership binding {field}", maximum=maximum)
        owner_kind = _exact_literal(
            row["ownership_kind"],
            choices=_SOURCE_OWNER_KINDS,
            label="ownership binding discriminator",
        )
        occurrence_sha256 = _optional_sha(
            row["occurrence_sha256"], label="ownership binding occurrence"
        )
        occurrence_ordinal = _optional_int(
            row["occurrence_ordinal"],
            label="ownership binding occurrence ordinal",
            maximum=_MAX_UNITS - 1,
        )
        if owner_kind == "result_occurrence":
            if occurrence_sha256 is None or occurrence_ordinal is None:
                _fail("result-occurrence binding lacks exact occurrence ownership")
        elif occurrence_sha256 is not None or occurrence_ordinal is not None:
            _fail("response-residual binding fabricates occurrence ownership")
        if row["binding_sha256"] != _identity_digest(
            row, kind=_BINDING_KIND, digest_field="binding_sha256"
        ):
            _fail("ownership binding digest differs from its exact identity")
    return rows


def _check_ownership_partitions(value: object) -> tuple[dict[str, object], ...]:
    rows = _strict_rows(
        value,
        fields=_OWNERSHIP_PARTITION_FIELDS,
        schema_version=_SCHEMA_VERSION,
        maximum=_MAX_PARTITIONS,
        label="lossless-ownership partition row",
    )
    empty_record_root = _ordered_root(
        kind=_PARTITION_RECORD_ROOT_KIND, items=(), maximum=_MAX_BINDINGS
    )
    empty_binding_root = _ordered_root(
        kind=_PARTITION_BINDING_ROOT_KIND, items=(), maximum=_MAX_BINDINGS
    )
    for row in rows:
        for field in (
            "partition_sha256",
            "raw_authority_bundle_sha256",
            "observation_record_sha256",
            "observation_sha256",
            "record_root_sha256",
            "binding_root_sha256",
        ):
            _exact_sha(row[field], label=f"ownership partition {field}")
        for field, maximum in (
            ("observation_ordinal", _MAX_OBSERVATIONS - 1),
            ("partition_ordinal", _MAX_PARTITIONS - 1),
            ("observation_partition_ordinal", _MAX_PARTITIONS - 1),
            ("record_count", _MAX_BINDINGS),
        ):
            _exact_int(row[field], label=f"ownership partition {field}", maximum=maximum)
        partition_kind = row["partition_kind"]
        if type(partition_kind) is not str or partition_kind not in _UNIT_KINDS:
            _fail("ownership partition has a foreign discriminator")
        occurrence_sha256 = _optional_sha(
            row["occurrence_sha256"], label="ownership partition occurrence"
        )
        occurrence_ordinal = _optional_int(
            row["occurrence_ordinal"],
            label="ownership partition occurrence ordinal",
            maximum=_MAX_UNITS - 1,
        )
        unit_sha256 = _optional_sha(row["unit_sha256"], label="ownership partition unit")
        unit_ordinal = _optional_int(
            row["unit_ordinal"],
            label="ownership partition unit ordinal",
            maximum=_MAX_UNITS - 1,
        )
        assignment_sha256 = _optional_sha(
            row["assignment_sha256"], label="ownership partition assignment"
        )
        fixed_zero_landing_sha256 = _optional_sha(
            row["fixed_zero_landing_sha256"], label="ownership fixed-zero landing"
        )
        unit_present = (
            unit_sha256 is not None and unit_ordinal is not None and assignment_sha256 is not None
        )
        unit_absent = unit_sha256 is None and unit_ordinal is None and assignment_sha256 is None
        if not unit_present and not unit_absent:
            _fail("ownership partition contains a partial unit binding")
        record_count = cast("int", row["record_count"])
        if partition_kind == "result_occurrence":
            if (
                occurrence_sha256 is None
                or occurrence_ordinal is None
                or not unit_present
                or fixed_zero_landing_sha256 is not None
            ):
                _fail("result-occurrence partition has an invalid ownership shape")
        elif partition_kind == "response_residual":
            if (
                occurrence_sha256 is not None
                or occurrence_ordinal is not None
                or fixed_zero_landing_sha256 is not None
                or (record_count > 0 and not unit_present)
                or (record_count == 0 and not unit_absent)
            ):
                _fail("response-residual partition has an invalid zero/unit shape")
        elif (
            occurrence_sha256 is not None
            or occurrence_ordinal is not None
            or not unit_present
            or record_count != 0
            or fixed_zero_landing_sha256 is None
        ):
            _fail("fixed-zero partition has an invalid ownership shape")
        if (record_count == 0) != (row["record_root_sha256"] == empty_record_root) or (
            record_count == 0
        ) != (row["binding_root_sha256"] == empty_binding_root):
            _fail("ownership partition zero proof is inconsistent")
        if row["partition_sha256"] != _identity_digest(
            row, kind=_PARTITION_KIND, digest_field="partition_sha256"
        ):
            _fail("ownership partition digest differs from its exact identity")
    return rows


def _check_ownership_observations(value: object) -> tuple[dict[str, object], ...]:
    rows = _strict_rows(
        value,
        fields=_OWNERSHIP_OBSERVATION_FIELDS,
        schema_version=_SCHEMA_VERSION,
        maximum=_MAX_OBSERVATIONS,
        label="lossless observation ownership row",
    )
    for row in rows:
        for field in (
            "observation_ownership_sha256",
            "raw_authority_bundle_sha256",
            "observation_record_sha256",
            "observation_sha256",
            "partition_root_sha256",
            "record_root_sha256",
            "binding_root_sha256",
        ):
            _exact_sha(row[field], label=f"ownership observation {field}")
        _exact_literal(
            row["source_input_kind"],
            choices=_SOURCE_INPUT_KINDS,
            label="ownership observation source-input kind",
        )
        _exact_literal(
            row["response_partition_kind"],
            choices=_RESPONSE_PARTITION_KINDS,
            label="ownership observation response partition kind",
        )
        for field, maximum in (
            ("observation_ordinal", _MAX_OBSERVATIONS - 1),
            ("first_partition_ordinal", _MAX_PARTITIONS - 1),
            ("partition_count", _MAX_PARTITIONS),
            ("result_occurrence_partition_count", _MAX_UNITS),
            ("zero_result_occurrence_partition_count", _MAX_UNITS),
            ("result_occurrence_record_count", _MAX_BINDINGS),
            ("response_record_count", _MAX_BINDINGS),
            ("record_count", _MAX_BINDINGS),
            ("binding_count", _MAX_BINDINGS),
        ):
            _exact_int(row[field], label=f"ownership observation {field}", maximum=maximum)
        fixed_zero_landing_sha256 = _optional_sha(
            row["fixed_zero_landing_sha256"], label="ownership observation fixed-zero landing"
        )
        result_partition_count = cast("int", row["result_occurrence_partition_count"])
        zero_result_count = cast("int", row["zero_result_occurrence_partition_count"])
        result_record_count = cast("int", row["result_occurrence_record_count"])
        response_record_count = cast("int", row["response_record_count"])
        record_count = cast("int", row["record_count"])
        if (
            row["partition_count"] != result_partition_count + 1
            or zero_result_count > result_partition_count
            or record_count != result_record_count + response_record_count
            or row["binding_count"] != record_count
        ):
            _fail("ownership observation aggregate denominators are inconsistent")
        if result_record_count < result_partition_count - zero_result_count:
            _fail("ownership observation has a nonempty occurrence without a source record")
        if row["response_partition_kind"] == "response_fixed_zero":
            if (
                result_partition_count != 0
                or zero_result_count != 0
                or result_record_count != 0
                or response_record_count != 0
                or record_count != 0
                or fixed_zero_landing_sha256 is None
            ):
                _fail("fixed-zero observation contradicts its exact empty algebra")
        elif fixed_zero_landing_sha256 is not None:
            _fail("response-residual observation fabricates a fixed-zero landing")
        elif result_partition_count == 0 and response_record_count == 0:
            _fail("empty observation lacks its mandatory fixed-zero response partition")
        if row["observation_ownership_sha256"] != _identity_digest(
            row,
            kind=_OBSERVATION_KIND,
            digest_field="observation_ownership_sha256",
        ):
            _fail("ownership observation digest differs from its exact identity")
    return rows


def _check_receipt_shape(value: object) -> dict[str, object]:
    row = _strict_row(
        value,
        fields=_OWNERSHIP_RECEIPT_FIELDS,
        schema_version=_SCHEMA_VERSION,
        label="lossless-ownership receipt row",
    )
    for field in (
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
        _exact_sha(row[field], label=f"ownership receipt {field}")
    for field, maximum in (
        ("expected_unit_count", _MAX_UNITS),
        ("representation_assignment_count", _MAX_UNITS),
        ("observation_count", _MAX_OBSERVATIONS),
        ("partition_count", _MAX_PARTITIONS),
        ("result_occurrence_partition_count", _MAX_UNITS),
        ("zero_result_occurrence_partition_count", _MAX_UNITS),
        ("result_occurrence_record_count", _MAX_BINDINGS),
        ("response_residual_partition_count", _MAX_OBSERVATIONS),
        ("positive_response_residual_partition_count", _MAX_OBSERVATIONS),
        ("zero_response_residual_partition_count", _MAX_OBSERVATIONS),
        ("response_residual_record_count", _MAX_BINDINGS),
        ("response_fixed_zero_partition_count", _MAX_OBSERVATIONS),
        ("binding_count", _MAX_BINDINGS),
        ("source_record_count", _MAX_BINDINGS),
    ):
        _exact_int(row[field], label=f"ownership receipt {field}", maximum=maximum)
    if row["receipt_sha256"] != _identity_digest(
        row, kind=_RECEIPT_KIND, digest_field="receipt_sha256"
    ):
        _fail("ownership receipt digest differs from its exact identity")
    return row


def _unit_for_owner(
    *,
    unit_rows: tuple[dict[str, object], ...],
    observation_sha256: str,
    owner_kind: str,
    occurrence_sha256: str | None,
) -> dict[str, object] | None:
    matches = tuple(
        unit
        for unit in unit_rows
        if unit["observation_sha256"] == observation_sha256
        and unit["unit_kind"] == owner_kind
        and unit["occurrence_sha256"] == occurrence_sha256
    )
    if len(matches) > 1:
        _fail("expected-unit inventory contains a duplicate owner identity")
    return None if not matches else matches[0]


def _expected_partition_specs(
    *,
    raw_observations: tuple[dict[str, object], ...],
    raw_occurrences: tuple[dict[str, object], ...],
    raw_landings: tuple[dict[str, object], ...],
    sources: tuple[_SourceRecord, ...],
    unit_rows: tuple[dict[str, object], ...],
    assignment_rows: tuple[dict[str, object], ...],
) -> tuple[tuple[dict[str, object] | None, dict[str, object] | None, str | None], ...]:
    specs: list[tuple[dict[str, object] | None, dict[str, object] | None, str | None]] = []
    expected_units: list[tuple[str, int, str, str | None, int | None]] = []
    for observation_ordinal, observation in enumerate(raw_observations):
        observation_sha256 = cast("str", observation["observation_sha256"])
        occurrence_rows = tuple(
            row for row in raw_occurrences if row["observation_sha256"] == observation_sha256
        )
        for occurrence in occurrence_rows:
            occurrence_sha256 = cast("str", occurrence["occurrence_sha256"])
            occurrence_ordinal = cast("int", occurrence["occurrence_ordinal"])
            expected_units.append(
                (
                    observation_sha256,
                    observation_ordinal,
                    "result_occurrence",
                    occurrence_sha256,
                    occurrence_ordinal,
                )
            )
        residual_sources = tuple(
            source
            for source in sources
            if source.observation_sha256 == observation_sha256
            and source.owner_kind == "response_residual"
        )
        response_kind = (
            "response_residual" if occurrence_rows or residual_sources else "response_fixed_zero"
        )
        if residual_sources:
            expected_units.append(
                (
                    observation_sha256,
                    observation_ordinal,
                    "response_residual",
                    None,
                    None,
                )
            )
        elif not occurrence_rows:
            expected_units.append(
                (
                    observation_sha256,
                    observation_ordinal,
                    "response_fixed_zero",
                    None,
                    None,
                )
            )

        for occurrence in occurrence_rows:
            unit = _unit_for_owner(
                unit_rows=unit_rows,
                observation_sha256=observation_sha256,
                owner_kind="result_occurrence",
                occurrence_sha256=cast("str", occurrence["occurrence_sha256"]),
            )
            if unit is None:
                _fail("ownership denominator omits one selected result occurrence")
            assignment = assignment_rows[cast("int", unit["unit_ordinal"])]
            if assignment["representation_kind"] != _occurrence_representation(
                observation=observation,
                occurrence=occurrence,
            ):
                _fail("occurrence representation differs from its raw landing disposition")
            if assignment["source_input_kind"] != _observation_source_input(observation):
                _fail("occurrence assignment differs from its raw source-input authority")
            specs.append((unit, assignment, None))

        if response_kind == "response_residual":
            response_unit = _unit_for_owner(
                unit_rows=unit_rows,
                observation_sha256=observation_sha256,
                owner_kind="response_residual",
                occurrence_sha256=None,
            )
            if residual_sources and response_unit is None:
                _fail("positive response residual lacks its mandatory expected unit")
            if not residual_sources and response_unit is not None:
                _fail("explicit zero response residual fabricates an expected unit")
            assignment = (
                None
                if response_unit is None
                else assignment_rows[cast("int", response_unit["unit_ordinal"])]
            )
            if assignment is not None and assignment[
                "source_input_kind"
            ] != _observation_source_input(observation):
                _fail("response assignment differs from its raw source-input authority")
            specs.append((response_unit, assignment, None))
        else:
            fixed_unit = _unit_for_owner(
                unit_rows=unit_rows,
                observation_sha256=observation_sha256,
                owner_kind="response_fixed_zero",
                occurrence_sha256=None,
            )
            if fixed_unit is None:
                _fail("empty observation lacks its mandatory fixed-zero expected unit")
            fixed_landings = tuple(
                row
                for row in raw_landings
                if row["observation_sha256"] == observation_sha256
                and row["landing_semantic"] == "response_fixed_zero"
            )
            if len(fixed_landings) != 1:
                _fail("fixed-zero observation lacks one unambiguous raw landing")
            fixed_assignment = assignment_rows[cast("int", fixed_unit["unit_ordinal"])]
            if fixed_assignment["source_input_kind"] != _observation_source_input(observation):
                _fail("fixed-zero assignment differs from its raw source-input authority")
            specs.append(
                (
                    fixed_unit,
                    fixed_assignment,
                    cast("str", fixed_landings[0]["landing_sha256"]),
                )
            )

    if len(expected_units) != len(unit_rows):
        _fail("expected-unit denominator has an extra or missing derived unit")
    for ordinal, (expected, actual) in enumerate(zip(expected_units, unit_rows, strict=True)):
        observation_sha256, observation_ordinal, kind, occurrence_sha256, occurrence_ordinal = (
            expected
        )
        if (
            actual["unit_ordinal"] != ordinal
            or actual["observation_sha256"] != observation_sha256
            or actual["observation_ordinal"] != observation_ordinal
            or actual["unit_kind"] != kind
            or actual["occurrence_sha256"] != occurrence_sha256
            or actual["occurrence_ordinal"] != occurrence_ordinal
        ):
            _fail("expected-unit denominator differs from independently derived owners")

    return tuple(specs)


def verify_independent_lossless_ownership(
    *,
    expected_raw_authority_bundle_sha256: object,
    expected_ownership_receipt_sha256: object,
    lossless_ownership_source_sha256: object,
    lossless_ownership_test_sha256: object,
    raw_observation_rows: object,
    raw_occurrence_rows: object,
    raw_landing_rows: object,
    result_cell_rows: object,
    stats_lossless_rows: object,
    live_lossless_rows: object,
    expected_unit_inventory_row: object,
    expected_unit_rows: object,
    representation_assignment_rows: object,
    ownership_observation_rows: object,
    ownership_partition_rows: object,
    ownership_binding_rows: object,
    ownership_receipt_row: object,
) -> IndependentLosslessOwnershipVerificationV1:
    """Reconstruct one exhaustive ownership receipt from disjoint plain rows.

    The four external pins are checked before any row inventory is traversed.
    Every row inventory must be an exact tuple of exact ordered built-in dicts.
    """

    # Trust pins are deliberately first.  A stale verifier/fixture pair or a
    # foreign bundle/receipt fails before any hostile row graph is inspected.
    raw_bundle_sha256 = _exact_sha(
        expected_raw_authority_bundle_sha256, label="expected raw-authority bundle"
    )
    expected_receipt_sha256 = _exact_sha(
        expected_ownership_receipt_sha256, label="expected ownership receipt"
    )
    source_pin = _exact_sha(lossless_ownership_source_sha256, label="lossless-ownership source pin")
    test_pin = _exact_sha(lossless_ownership_test_sha256, label="lossless-ownership test pin")
    if source_pin != FROZEN_LOSSLESS_OWNERSHIP_SOURCE_SHA256:
        _fail("lossless-ownership source pin differs from the frozen authority")
    if test_pin != FROZEN_LOSSLESS_OWNERSHIP_TEST_SHA256:
        _fail("lossless-ownership test pin differs from the frozen authority fixture")

    receipt = _check_receipt_shape(ownership_receipt_row)
    if (
        receipt["receipt_sha256"] != expected_receipt_sha256
        or receipt["raw_authority_bundle_sha256"] != raw_bundle_sha256
    ):
        _fail("ownership receipt differs from its external bundle or receipt pin")

    raw_observations = _check_raw_observations(raw_observation_rows)
    raw_occurrences = _check_raw_occurrences(raw_occurrence_rows, observations=raw_observations)
    raw_landings = _check_raw_landings(raw_landing_rows, observations=raw_observations)
    observations_by_sha = {cast("str", row["observation_sha256"]): row for row in raw_observations}
    occurrence_owner = {
        cast("str", row["occurrence_sha256"]): cast("str", row["observation_sha256"])
        for row in raw_occurrences
    }
    occurrences_by_sha = {cast("str", row["occurrence_sha256"]): row for row in raw_occurrences}
    result_sources = _check_result_cell_sources(
        result_cell_rows,
        observations_by_sha=observations_by_sha,
        occurrence_owner=occurrence_owner,
        occurrences_by_sha=occurrences_by_sha,
    )
    stats_sources = _check_stats_sources(
        stats_lossless_rows,
        raw_bundle_sha256=raw_bundle_sha256,
        observations_by_sha=observations_by_sha,
        occurrence_owner=occurrence_owner,
    )
    live_closure = _check_live_sources(
        live_lossless_rows,
        raw_bundle_sha256=raw_bundle_sha256,
        observations=raw_observations,
        raw_occurrences=raw_occurrences,
    )
    live_sources = live_closure.records
    sources = (*result_sources, *stats_sources, *live_sources)
    source_by_sha: dict[str, _SourceRecord] = {}
    for source in sources:
        if source.source_record_sha256 in source_by_sha:
            _fail("public source relations duplicate one source-record identity")
        source_by_sha[source.source_record_sha256] = source

    units = _check_unit_rows(expected_unit_rows, raw_bundle_sha256=raw_bundle_sha256)
    inventory = _check_inventory_row(
        expected_unit_inventory_row,
        raw_bundle_sha256=raw_bundle_sha256,
        unit_rows=units,
    )
    assignments = _check_assignment_rows(
        representation_assignment_rows,
        raw_bundle_sha256=raw_bundle_sha256,
        unit_rows=units,
    )
    central_live_semantic_owner_vector = tuple(
        (
            unit["observation_sha256"],
            unit["unit_kind"],
            unit["occurrence_sha256"],
            unit["occurrence_ordinal"],
            assignment["source_input_kind"],
            assignment["representation_kind"],
        )
        for unit, assignment in zip(units, assignments, strict=True)
        if observations_by_sha[cast("str", unit["observation_sha256"])]["source_family"] == "live"
        and unit["unit_kind"] != "response_fixed_zero"
    )
    if central_live_semantic_owner_vector != live_closure.semantic_owner_vector:
        _fail("live-lossless side assignments differ from central semantic owners")
    ownership_observations = _check_ownership_observations(ownership_observation_rows)
    partitions = _check_ownership_partitions(ownership_partition_rows)
    bindings = _check_ownership_bindings(ownership_binding_rows)

    if len(ownership_observations) != len(raw_observations):
        _fail("ownership observation denominator differs from selected raw observations")
    for ordinal, (raw_observation, owned_observation) in enumerate(
        zip(raw_observations, ownership_observations, strict=True)
    ):
        if (
            owned_observation["raw_authority_bundle_sha256"] != raw_bundle_sha256
            or owned_observation["observation_ordinal"] != ordinal
            or owned_observation["observation_sha256"] != raw_observation["observation_sha256"]
            or owned_observation["observation_record_sha256"]
            != raw_observation["observation_record_sha256"]
            or owned_observation["source_input_kind"] != _observation_source_input(raw_observation)
        ):
            _fail("ownership observation is foreign, reordered, or source-inconsistent")

    partition_specs = _expected_partition_specs(
        raw_observations=raw_observations,
        raw_occurrences=raw_occurrences,
        raw_landings=raw_landings,
        sources=sources,
        unit_rows=units,
        assignment_rows=assignments,
    )
    if len(partition_specs) != len(partitions):
        _fail("ownership partition denominator differs from independently derived owners")

    observation_partition_counts: dict[int, int] = {}
    partition_by_ordinal: dict[int, dict[str, object]] = {}
    used_units: set[int] = set()
    for ordinal, (partition, spec) in enumerate(zip(partitions, partition_specs, strict=True)):
        unit, assignment, fixed_zero_landing_sha256 = spec
        observation_ordinal = cast("int", partition["observation_ordinal"])
        if observation_ordinal >= len(raw_observations):
            _fail("ownership partition references a foreign observation")
        raw_observation = raw_observations[observation_ordinal]
        expected_observation_partition = observation_partition_counts.get(observation_ordinal, 0)
        observation_partition_counts[observation_ordinal] = expected_observation_partition + 1
        if (
            partition["partition_ordinal"] != ordinal
            or partition["observation_partition_ordinal"] != expected_observation_partition
            or partition["raw_authority_bundle_sha256"] != raw_bundle_sha256
            or partition["observation_sha256"] != raw_observation["observation_sha256"]
            or partition["observation_record_sha256"]
            != raw_observation["observation_record_sha256"]
        ):
            _fail("ownership partition is foreign, reordered, or cross-observation")
        partition_by_ordinal[ordinal] = partition
        if unit is None:
            if (
                partition["partition_kind"] != "response_residual"
                or partition["unit_sha256"] is not None
                or partition["unit_ordinal"] is not None
                or partition["assignment_sha256"] is not None
                or partition["occurrence_sha256"] is not None
                or partition["occurrence_ordinal"] is not None
            ):
                _fail("zero response partition differs from its explicit empty owner")
        else:
            unit_ordinal = cast("int", unit["unit_ordinal"])
            if unit_ordinal in used_units:
                _fail("ownership partitions dual-assign one expected unit")
            used_units.add(unit_ordinal)
            if assignment is None or (
                partition["partition_kind"] != unit["unit_kind"]
                or partition["unit_sha256"] != unit["unit_sha256"]
                or partition["unit_ordinal"] != unit_ordinal
                or partition["assignment_sha256"] != assignment["assignment_sha256"]
                or partition["occurrence_sha256"] != unit["occurrence_sha256"]
                or partition["occurrence_ordinal"] != unit["occurrence_ordinal"]
            ):
                _fail("ownership partition has a foreign unit or assignment binding")
        if partition["fixed_zero_landing_sha256"] != fixed_zero_landing_sha256:
            _fail("ownership fixed-zero partition differs from its exact raw landing")
    if used_units != set(range(len(units))):
        _fail("ownership partitions leave an expected unit orphaned")

    seen_binding_sha256s: set[str] = set()
    seen_source_sha256s: set[str] = set()
    next_observation_record_ordinal: dict[int, int] = {}
    last_binding_observation = -1
    bindings_by_partition: dict[int, list[dict[str, object]]] = {
        ordinal: [] for ordinal in partition_by_ordinal
    }
    bindings_by_observation: dict[int, list[dict[str, object]]] = {
        ordinal: [] for ordinal in range(len(raw_observations))
    }
    for ordinal, binding in enumerate(bindings):
        observation_ordinal = cast("int", binding["observation_ordinal"])
        partition_ordinal = cast("int", binding["partition_ordinal"])
        if observation_ordinal >= len(raw_observations):
            _fail("ownership binding references a foreign observation")
        raw_observation = raw_observations[observation_ordinal]
        partition = partition_by_ordinal.get(partition_ordinal)
        if (
            binding["binding_ordinal"] != ordinal
            or binding["raw_authority_bundle_sha256"] != raw_bundle_sha256
            or partition is None
            or partition["observation_ordinal"] != observation_ordinal
            or binding["observation_sha256"] != raw_observation["observation_sha256"]
            or binding["observation_record_sha256"] != raw_observation["observation_record_sha256"]
        ):
            _fail("ownership binding is orphaned, foreign, or reordered")
        if observation_ordinal < last_binding_observation:
            _fail("ownership bindings reopen a completed observation")
        last_binding_observation = observation_ordinal
        expected_record_ordinal = next_observation_record_ordinal.get(observation_ordinal, 0)
        if binding["observation_record_ordinal"] != expected_record_ordinal:
            _fail("ownership observation record order is not contiguous")
        next_observation_record_ordinal[observation_ordinal] = expected_record_ordinal + 1
        binding_sha256 = cast("str", binding["binding_sha256"])
        source_sha256 = cast("str", binding["source_record_sha256"])
        if binding_sha256 in seen_binding_sha256s or source_sha256 in seen_source_sha256s:
            _fail("ownership binding inventory dual-assigns one source record")
        seen_binding_sha256s.add(binding_sha256)
        seen_source_sha256s.add(source_sha256)
        unit_ordinal = cast("int", binding["unit_ordinal"])
        if unit_ordinal >= len(units):
            _fail("ownership binding references a foreign expected unit")
        unit = units[unit_ordinal]
        assignment = assignments[unit_ordinal]
        if (
            binding["unit_sha256"] != unit["unit_sha256"]
            or binding["assignment_sha256"] != assignment["assignment_sha256"]
            or binding["ownership_kind"] != unit["unit_kind"]
            or binding["occurrence_sha256"] != unit["occurrence_sha256"]
            or binding["occurrence_ordinal"] != unit["occurrence_ordinal"]
            or binding["unit_sha256"] != partition["unit_sha256"]
            or binding["unit_ordinal"] != partition["unit_ordinal"]
            or binding["assignment_sha256"] != partition["assignment_sha256"]
            or binding["ownership_kind"] != partition["partition_kind"]
            or binding["occurrence_sha256"] != partition["occurrence_sha256"]
            or binding["occurrence_ordinal"] != partition["occurrence_ordinal"]
        ):
            _fail("ownership binding disagrees with its partition or expected unit")
        source = source_by_sha.get(source_sha256)
        if source is None:
            _fail("ownership binding references a missing public source record")
        if (
            source.observation_sha256 != binding["observation_sha256"]
            or source.observation_record_sha256 != binding["observation_record_sha256"]
            or source.owner_kind != binding["ownership_kind"]
            or source.occurrence_sha256 != binding["occurrence_sha256"]
            or source.representation_kind != assignment["representation_kind"]
            or assignment["source_input_kind"] != _observation_source_input(raw_observation)
        ):
            _fail("ownership binding contradicts its public source or representation")
        bindings_by_partition[partition_ordinal].append(binding)
        bindings_by_observation[observation_ordinal].append(binding)
    if seen_source_sha256s != set(source_by_sha):
        _fail("public source inventory contains an orphan or missing ownership binding")

    for ordinal, partition in enumerate(partitions):
        owned = bindings_by_partition[ordinal]
        expected_record_root = _ordered_root(
            kind=_PARTITION_RECORD_ROOT_KIND,
            items=tuple(cast("str", item["source_record_sha256"]) for item in owned),
            maximum=_MAX_BINDINGS,
        )
        expected_binding_root = _ordered_root(
            kind=_PARTITION_BINDING_ROOT_KIND,
            items=tuple(cast("str", item["binding_sha256"]) for item in owned),
            maximum=_MAX_BINDINGS,
        )
        if (
            partition["record_count"] != len(owned)
            or partition["record_root_sha256"] != expected_record_root
            or partition["binding_root_sha256"] != expected_binding_root
        ):
            _fail("ownership partition roots differ from its exact public bindings")

    partitions_by_observation: dict[int, list[dict[str, object]]] = {
        ordinal: [] for ordinal in range(len(raw_observations))
    }
    for partition in partitions:
        partitions_by_observation[cast("int", partition["observation_ordinal"])].append(partition)
    for ordinal, owned_observation in enumerate(ownership_observations):
        owned_partitions = partitions_by_observation[ordinal]
        owned_bindings = bindings_by_observation[ordinal]
        occurrence_partitions = owned_partitions[:-1]
        response_partition = owned_partitions[-1]
        expected_values: dict[str, object] = {
            "raw_authority_bundle_sha256": raw_bundle_sha256,
            "observation_record_sha256": raw_observations[ordinal]["observation_record_sha256"],
            "observation_sha256": raw_observations[ordinal]["observation_sha256"],
            "observation_ordinal": ordinal,
            "source_input_kind": _observation_source_input(raw_observations[ordinal]),
            "first_partition_ordinal": owned_partitions[0]["partition_ordinal"],
            "partition_count": len(owned_partitions),
            "partition_root_sha256": _ordered_root(
                kind=_OBSERVATION_PARTITION_ROOT_KIND,
                items=tuple(cast("str", item["partition_sha256"]) for item in owned_partitions),
                maximum=_MAX_PARTITIONS,
            ),
            "result_occurrence_partition_count": len(occurrence_partitions),
            "zero_result_occurrence_partition_count": sum(
                item["record_count"] == 0 for item in occurrence_partitions
            ),
            "result_occurrence_record_count": sum(
                cast("int", item["record_count"]) for item in occurrence_partitions
            ),
            "response_partition_kind": response_partition["partition_kind"],
            "response_record_count": response_partition["record_count"],
            "fixed_zero_landing_sha256": response_partition["fixed_zero_landing_sha256"],
            "record_count": len(owned_bindings),
            "record_root_sha256": _ordered_root(
                kind=_OBSERVATION_RECORD_ROOT_KIND,
                items=tuple(cast("str", item["source_record_sha256"]) for item in owned_bindings),
                maximum=_MAX_BINDINGS,
            ),
            "binding_count": len(owned_bindings),
            "binding_root_sha256": _ordered_root(
                kind=_OBSERVATION_BINDING_ROOT_KIND,
                items=tuple(cast("str", item["binding_sha256"]) for item in owned_bindings),
                maximum=_MAX_BINDINGS,
            ),
        }
        for field, expected_value in expected_values.items():
            if owned_observation[field] != expected_value:
                _fail("ownership observation differs from exact partitions and bindings")

    assignment_root_sha256 = _ordered_root(
        kind=_ASSIGNMENT_ROOT_KIND,
        items=tuple(cast("str", item["assignment_sha256"]) for item in assignments),
        maximum=_MAX_UNITS,
    )
    observation_root_sha256 = _ordered_root(
        kind=_AUTHORITY_OBSERVATION_ROOT_KIND,
        items=tuple(
            cast("str", item["observation_ownership_sha256"]) for item in ownership_observations
        ),
        maximum=_MAX_OBSERVATIONS,
    )
    partition_root_sha256 = _ordered_root(
        kind=_AUTHORITY_PARTITION_ROOT_KIND,
        items=tuple(cast("str", item["partition_sha256"]) for item in partitions),
        maximum=_MAX_PARTITIONS,
    )
    binding_root_sha256 = _ordered_root(
        kind=_AUTHORITY_BINDING_ROOT_KIND,
        items=tuple(cast("str", item["binding_sha256"]) for item in bindings),
        maximum=_MAX_BINDINGS,
    )
    source_record_root_sha256 = _ordered_root(
        kind=_AUTHORITY_RECORD_ROOT_KIND,
        items=tuple(cast("str", item["source_record_sha256"]) for item in bindings),
        maximum=_MAX_BINDINGS,
    )
    occurrence_partitions = tuple(
        item for item in partitions if item["partition_kind"] == "result_occurrence"
    )
    residual_partitions = tuple(
        item for item in partitions if item["partition_kind"] == "response_residual"
    )
    fixed_partitions = tuple(
        item for item in partitions if item["partition_kind"] == "response_fixed_zero"
    )
    fixed_zero_landing_root_sha256 = _ordered_root(
        kind=_FIXED_ZERO_LANDING_ROOT_KIND,
        items=tuple(cast("str", item["fixed_zero_landing_sha256"]) for item in fixed_partitions),
        maximum=_MAX_OBSERVATIONS,
    )
    expected_receipt_values: dict[str, object] = {
        "raw_authority_bundle_sha256": raw_bundle_sha256,
        "expected_unit_count": len(units),
        "expected_unit_inventory_sha256": inventory["inventory_sha256"],
        "expected_unit_root_sha256": inventory["unit_root_sha256"],
        "representation_assignment_count": len(assignments),
        "representation_assignment_root_sha256": assignment_root_sha256,
        "observation_count": len(ownership_observations),
        "observation_root_sha256": observation_root_sha256,
        "partition_count": len(partitions),
        "partition_root_sha256": partition_root_sha256,
        "result_occurrence_partition_count": len(occurrence_partitions),
        "zero_result_occurrence_partition_count": sum(
            item["record_count"] == 0 for item in occurrence_partitions
        ),
        "result_occurrence_record_count": sum(
            cast("int", item["record_count"]) for item in occurrence_partitions
        ),
        "response_residual_partition_count": len(residual_partitions),
        "positive_response_residual_partition_count": sum(
            cast("int", item["record_count"]) > 0 for item in residual_partitions
        ),
        "zero_response_residual_partition_count": sum(
            item["record_count"] == 0 for item in residual_partitions
        ),
        "response_residual_record_count": sum(
            cast("int", item["record_count"]) for item in residual_partitions
        ),
        "response_fixed_zero_partition_count": len(fixed_partitions),
        "fixed_zero_landing_root_sha256": fixed_zero_landing_root_sha256,
        "binding_count": len(bindings),
        "binding_root_sha256": binding_root_sha256,
        "source_record_count": len(bindings),
        "source_record_root_sha256": source_record_root_sha256,
    }
    for field, expected_value in expected_receipt_values.items():
        if receipt[field] != expected_value:
            _fail("ownership receipt differs from independently reconstructed closure")

    verification_values: dict[str, object] = {
        "raw_authority_bundle_sha256": raw_bundle_sha256,
        "ownership_receipt_sha256": expected_receipt_sha256,
        "expected_unit_inventory_sha256": inventory["inventory_sha256"],
        "expected_unit_root_sha256": inventory["unit_root_sha256"],
        "representation_assignment_root_sha256": assignment_root_sha256,
        "observation_count": len(raw_observations),
        "occurrence_count": len(raw_occurrences),
        "partition_count": len(partitions),
        "binding_count": len(bindings),
        "result_cell_count": len(result_sources),
        "stats_lossless_record_count": len(stats_sources),
        "live_lossless_record_count": len(live_sources),
        "source_record_count": len(sources),
        "source_record_root_sha256": source_record_root_sha256,
    }
    verification_sha256 = _canonical_sha(
        {
            "schema_version": _SCHEMA_VERSION,
            "kind": _VERIFICATION_KIND,
            "lossless_ownership_source_sha256": source_pin,
            "lossless_ownership_test_sha256": test_pin,
            **verification_values,
        }
    )
    return IndependentLosslessOwnershipVerificationV1(
        verification_sha256=verification_sha256,
        raw_authority_bundle_sha256=raw_bundle_sha256,
        ownership_receipt_sha256=expected_receipt_sha256,
        expected_unit_inventory_sha256=cast("str", inventory["inventory_sha256"]),
        expected_unit_root_sha256=cast("str", inventory["unit_root_sha256"]),
        representation_assignment_root_sha256=assignment_root_sha256,
        observation_count=len(raw_observations),
        occurrence_count=len(raw_occurrences),
        partition_count=len(partitions),
        binding_count=len(bindings),
        result_cell_count=len(result_sources),
        stats_lossless_record_count=len(stats_sources),
        live_lossless_record_count=len(live_sources),
        source_record_count=len(sources),
        source_record_root_sha256=source_record_root_sha256,
    )
