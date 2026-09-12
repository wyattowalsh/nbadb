"""Normalized public value authority for stats and static result packets.

The table defined by this module stores one canonical JSON value per rectangular
provider cell.  It is deliberately normalized under the existing observation
and result-occurrence relations: route and committed-chunk authority remains a
transitive occurrence-to-landing join rather than being repeated on each cell.
"""

from __future__ import annotations

import hashlib
import json
import math
import re
from collections import defaultdict
from dataclasses import dataclass, fields
from datetime import UTC, datetime
from typing import TYPE_CHECKING, ClassVar, Literal, Never, Self, cast

if TYPE_CHECKING:
    from collections.abc import Iterable

    from pydantic import BaseModel

from nbadb.contracts.raw_request_authority import (
    MAX_JSON_NODES,
    MAX_PARSER_INPUT_BYTES,
    RAW_REQUEST_AUTHORITY_SCHEMA_VERSION,
    ObservationRouteLandingV2,
    ParserInputObjectV2,
    RawRequestAuthorityBundleV2,
    RequestAttemptIdentityV2,
    RequestObservationV2,
    ResultOccurrenceV2,
    canonical_json_bytes,
    validate_raw_request_authority_bundle,
)
from nbadb.contracts.raw_transport_contract import (
    LiveHttpTransportV1,
    StaticSnapshotTransportV1,
    StatsHttpTransportV1,
)

__all__ = [
    "CellPresenceKind",
    "CellValueKind",
    "RawNbaApiResultCellV2",
    "RawResultCellAuthorityError",
    "RawResultCellAuthorityReceiptV2",
    "RawResultCellPublicTableProofV2",
    "validate_raw_result_cell_authority",
    "validate_raw_result_cell_authority_receipt",
    "validate_raw_result_cell_public_table",
]

CellPresenceKind = Literal["present", "null", "empty_object", "empty_array"]
CellValueKind = Literal["null", "boolean", "integer", "number", "string", "array", "object"]

_PRESENCE_KINDS = {"present", "null", "empty_object", "empty_array"}
_VALUE_KINDS = {"null", "boolean", "integer", "number", "string", "array", "object"}
_SHA256_RE = re.compile(r"[0-9a-f]{64}\Z")
_MAX_INTEGER_ABS = (1 << 63) - 1
_MAX_DEPTH = 64
_MAX_NUMBER_TOKEN_BYTES = 128
_MAX_RESULT_HEADERS = 4_096
_MAX_RESULT_ROWS = 1_000_000
_MAX_RESULT_OCCURRENCES = 1_000_000
_MAX_RESULT_CELLS = MAX_JSON_NODES
_MAX_GLOBAL_RESULT_ROWS = MAX_JSON_NODES
_MAX_GLOBAL_RESULT_HEADERS = MAX_JSON_NODES
_MAX_GLOBAL_HEADER_BYTES = MAX_PARSER_INPUT_BYTES
_MAX_GLOBAL_CELL_BYTES = MAX_PARSER_INPUT_BYTES
_CELL_KIND = "raw_nba_api_result_cell_v2"
_PUBLIC_TABLE_PROOF_KIND = "raw_nba_api_result_cell_public_table_proof_v2"
_OBSERVATION_INVENTORY_ROOT_KIND = "raw_nba_api_result_cell_observation_inventory_root_v2"
_OCCURRENCE_INVENTORY_ROOT_KIND = "raw_nba_api_result_cell_occurrence_inventory_root_v2"
_ELIGIBLE_OCCURRENCE_INVENTORY_ROOT_KIND = (
    "raw_nba_api_result_cell_eligible_occurrence_inventory_root_v2"
)
_CELL_INVENTORY_ROOT_KIND = "raw_nba_api_result_cell_inventory_root_v2"
_CELL_ROWS_ROOT_KIND = "raw_nba_api_result_cell_rows_root_v2"
_AUTHORIZATION_HEADER_SECRET_RE = re.compile(
    r"authorization\s*:\s*(?:bearer|basic)\s+[A-Za-z0-9._~+/=-]{8,}",
    flags=re.ASCII | re.IGNORECASE,
)
_CAMEL_ACRONYM_BOUNDARY_RE = re.compile(r"([A-Z]+)([A-Z][a-z])", flags=re.ASCII)
_CAMEL_WORD_BOUNDARY_RE = re.compile(r"([a-z0-9])([A-Z])", flags=re.ASCII)
_KEY_SEPARATOR_RE = re.compile(r"[^A-Za-z0-9]+", flags=re.ASCII)
_SENSITIVE_OBJECT_KEY_RE = re.compile(
    r"(?:authorization|cookie|set_cookie|credential|client_secret|access_token|"
    r"refresh_token|api_key|password|proxy_url|proxy_host|vpn_server|vpn_ip|"
    r"request_headers|response_headers|runner_path|workspace_path|local_path|file_path|"
    r"github_token|private_key|secret_key|personal_access_token|ssh_private_key)\Z",
    flags=re.ASCII,
)
_GENERIC_SENSITIVE_KEY_COMPONENTS = frozenset({"auth", "session", "secret", "token"})
_LOCAL_PATH_VALUE_RE = re.compile(
    r"(?:/Users/[^/\x00\s]+(?=/|\s|\Z)|/home/[^/\x00\s]+(?=/|\s|\Z)|"
    r"/private/var(?![A-Za-z0-9_])|[A-Za-z]:\\Users\\)"
)
_BEARER_SECRET_RE = re.compile(
    r"bearer\s+[A-Za-z0-9._~+/=-]{20,}(?![A-Za-z0-9._~+/=-])",
    flags=re.ASCII | re.IGNORECASE,
)
_BASIC_SECRET_RE = re.compile(
    r"basic\s+[A-Za-z0-9+/=]{12,}(?![A-Za-z0-9+/=])",
    flags=re.ASCII | re.IGNORECASE,
)
_EMBEDDED_SECRET_RES = (
    re.compile(r"\bgh[opurs]_[A-Za-z0-9]{20,}\b", flags=re.ASCII),
    re.compile(r"\bAKIA[0-9A-Z]{16}\b", flags=re.ASCII),
    re.compile(r"\bxox[baprs]-[A-Za-z0-9-]{10,}\b", flags=re.ASCII),
    re.compile(r"\bAIza[0-9A-Za-z_-]{35}\b", flags=re.ASCII),
    re.compile(
        r"\beyJ[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}\b",
        flags=re.ASCII,
    ),
    re.compile(r"-----BEGIN (?:[A-Z0-9]+ )*PRIVATE KEY-----", flags=re.ASCII),
    re.compile(r"https?://[^/\s:@]+:[^/\s@]+@", flags=re.ASCII | re.IGNORECASE),
)


class RawResultCellAuthorityError(ValueError):
    """A normalized raw result-cell row or closed inventory is invalid."""


def _fail(message: str) -> Never:
    raise RawResultCellAuthorityError(message)


def _sha256(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _canonical_sha256(value: object) -> str:
    return _sha256(canonical_json_bytes(value, maximum_bytes=MAX_PARSER_INPUT_BYTES))


def _canonical_ordered_root_sha256(
    *,
    kind: str,
    count: int,
    values: Iterable[object],
) -> str:
    """Hash one count- and domain-bound canonical array without materializing it."""

    _exact_nonnegative(count, field_name="ordered_root_count")
    digest = hashlib.sha256()
    digest.update(b'{"count":')
    digest.update(str(count).encode("ascii"))
    digest.update(b',"items":[')
    seen = 0
    for ordinal, value in enumerate(values):
        if ordinal:
            digest.update(b",")
        digest.update(
            canonical_json_bytes(
                value,
                maximum_bytes=MAX_PARSER_INPUT_BYTES * 3,
            )
        )
        seen += 1
    if seen != count:
        _fail("ordered authority root count differs from its item denominator")
    digest.update(b'],"kind":')
    digest.update(canonical_json_bytes(kind, maximum_bytes=256))
    digest.update(b',"schema_version":2}')
    return digest.hexdigest()


def _exact_nonnegative(value: object, *, field_name: str) -> int:
    if type(value) is not int or value < 0 or value > 2**63 - 1:
        _fail(f"{field_name} must be a nonnegative bounded exact integer")
    return value


def _exact_sha256(value: object, *, field_name: str) -> str:
    if type(value) is not str or _SHA256_RE.fullmatch(value) is None:
        _fail(f"{field_name} must be a lowercase full SHA-256")
    return value


def _exact_model_storage(
    value: object,
    *,
    expected_type: type[BaseModel],
    label: str,
) -> dict[str, object]:
    """Expose one exact Pydantic field map without invoking model methods."""

    if type(value) is not expected_type:
        _fail(f"{label} has a foreign exact DTO type")
    storage = object.__getattribute__(value, "__dict__")
    if type(storage) is not dict:
        _fail(f"{label} has foreign model storage")
    object_storage = cast("dict[object, object]", storage)
    if any(type(key) is not str for key in object_storage):
        _fail(f"{label} has foreign model storage keys")
    expected_fields = tuple(expected_type.model_fields)
    if tuple(object_storage) != expected_fields:
        _fail(f"{label} does not have its exact ordered model fields")
    return cast("dict[str, object]", storage)


def _preflight_exact_builtin_graph(value: object, *, label: str) -> None:
    """Reject hostile nested values before equality, hashing, or model methods."""

    stack = [value]
    nodes = 0
    while stack:
        item = stack.pop()
        nodes += 1
        if nodes > MAX_JSON_NODES:
            _fail(f"{label} exceeds its nested preflight bound")
        if type(item) in {type(None), bool, int, float, str, bytes, datetime}:
            continue
        if type(item) in {tuple, list}:
            stack.extend(cast("tuple[object, ...] | list[object]", item))
            continue
        if type(item) is dict:
            mapping = cast("dict[object, object]", item)
            if any(type(key) is not str for key in mapping):
                _fail(f"{label} contains a foreign nested mapping key")
            stack.extend(mapping.values())
            continue
        _fail(f"{label} contains a foreign nested value")


def _preflight_request_attempt(value: object) -> None:
    storage = _exact_model_storage(
        value,
        expected_type=RequestAttemptIdentityV2,
        label="result-cell request attempt",
    )
    for item in storage.values():
        _preflight_exact_builtin_graph(item, label="result-cell request attempt")


def _preflight_raw_transport(value: object) -> None:
    transport_type = type(value)
    if transport_type not in {
        StatsHttpTransportV1,
        LiveHttpTransportV1,
        StaticSnapshotTransportV1,
    }:
        _fail("result-cell request observation has a foreign transport DTO")
    storage = _exact_model_storage(
        value,
        expected_type=cast("type[BaseModel]", transport_type),
        label="result-cell raw transport",
    )
    for item in storage.values():
        _preflight_exact_builtin_graph(item, label="result-cell raw transport")


def _preflight_request_observation(value: object) -> None:
    storage = _exact_model_storage(
        value,
        expected_type=RequestObservationV2,
        label="result-cell request observation",
    )
    _preflight_request_attempt(storage["attempt"])
    _preflight_raw_transport(storage["transport"])
    started_at = storage["started_at"]
    finished_at = storage["finished_at"]
    if type(started_at) is not datetime or started_at.tzinfo is not UTC:
        _fail("result-cell request observation started timestamp is not trusted UTC")
    if finished_at is not None and (
        type(finished_at) is not datetime or finished_at.tzinfo is not UTC
    ):
        _fail("result-cell request observation finished timestamp is not trusted UTC")
    for field_name, item in storage.items():
        if field_name not in {"attempt", "transport"}:
            _preflight_exact_builtin_graph(item, label="result-cell request observation")


def _preflight_parser_input_object(value: object) -> None:
    storage = _exact_model_storage(
        value,
        expected_type=ParserInputObjectV2,
        label="result-cell parser-input object",
    )
    for item in storage.values():
        _preflight_exact_builtin_graph(item, label="result-cell parser-input object")


def _preflight_result_occurrence(value: object) -> None:
    storage = _exact_model_storage(
        value,
        expected_type=ResultOccurrenceV2,
        label="result-cell result occurrence",
    )
    for item in storage.values():
        _preflight_exact_builtin_graph(item, label="result-cell result occurrence")


def _preflight_route_landing(value: object) -> None:
    storage = _exact_model_storage(
        value,
        expected_type=ObservationRouteLandingV2,
        label="result-cell route landing",
    )
    live_snapshot_at = storage["live_snapshot_at"]
    if live_snapshot_at is not None and (
        type(live_snapshot_at) is not datetime or live_snapshot_at.tzinfo is not UTC
    ):
        _fail("result-cell route landing snapshot timestamp is not trusted UTC")
    for item in storage.values():
        _preflight_exact_builtin_graph(item, label="result-cell route landing")


def _reject_secret_shaped_public_text(value: str) -> None:
    """Reject narrowly recognizable credential material without echoing it."""

    stripped = value.strip()
    if (
        _AUTHORIZATION_HEADER_SECRET_RE.search(stripped) is not None
        or _BEARER_SECRET_RE.search(stripped) is not None
        or _BASIC_SECRET_RE.search(stripped) is not None
        or _LOCAL_PATH_VALUE_RE.search(value) is not None
        or any(pattern.search(value) is not None for pattern in _EMBEDDED_SECRET_RES)
    ):
        _fail("result-cell value contains secret-shaped public text")


def _normalized_public_key(value: str) -> str:
    separated = _CAMEL_ACRONYM_BOUNDARY_RE.sub(r"\1_\2", value)
    separated = _CAMEL_WORD_BOUNDARY_RE.sub(r"\1_\2", separated)
    return _KEY_SEPARATOR_RE.sub("_", separated).strip("_").lower()


def _reject_sensitive_public_key(value: str) -> None:
    normalized = _normalized_public_key(value)
    if _SENSITIVE_OBJECT_KEY_RE.fullmatch(normalized) is not None or any(
        component in _GENERIC_SENSITIVE_KEY_COMPONENTS for component in normalized.split("_")
    ):
        _fail("result-cell value contains secret-shaped public material")


def _validate_header_name(value: object) -> str:
    if type(value) is not str or not value or len(value) > 256:
        _fail("result-cell header name is absent or over bound")
    header = cast("str", value)
    _reject_sensitive_public_key(header)
    _reject_secret_shaped_public_text(header)
    return header


def _reject_duplicate_keys(pairs: list[tuple[str, object]]) -> dict[str, object]:
    value: dict[str, object] = {}
    for key, item in pairs:
        if key in value:
            _fail("result-cell canonical JSON contains a duplicate object key")
        value[key] = item
    return value


def _reject_nonfinite_constant(value: str) -> Never:
    _fail("result-cell canonical JSON contains a non-finite number")


def _preflight_canonical_json_bytes(raw: bytes) -> None:
    """Bound JSON structure and numeric tokens before decoder allocation."""

    depth = 0
    maximum_depth = 0
    nodes = 1
    in_string = False
    escaped = False
    index = 0
    while index < len(raw):
        byte = raw[index]
        if in_string:
            if escaped:
                escaped = False
            elif byte == 0x5C:  # backslash
                escaped = True
            elif byte == 0x22:  # quote
                in_string = False
            index += 1
            continue
        if byte == 0x22:
            in_string = True
            index += 1
            continue
        if byte in (0x7B, 0x5B):  # { [
            depth += 1
            maximum_depth = max(maximum_depth, depth)
            nodes += 1
        elif byte in (0x7D, 0x5D):  # } ]
            depth -= 1
            if depth < 0:
                _fail("result-cell canonical JSON is structurally invalid")
        elif byte in (0x2C, 0x3A):  # , :
            nodes += 1
        elif byte == 0x2D or 0x30 <= byte <= 0x39:  # - or digit
            end = index + 1
            while end < len(raw) and raw[end] not in b" \t\r\n,]}":
                end += 1
            if end - index > _MAX_NUMBER_TOKEN_BYTES:
                _fail("result-cell canonical JSON contains an oversized number token")
            index = end
            if maximum_depth > _MAX_DEPTH or nodes > MAX_JSON_NODES:
                _fail("result-cell canonical JSON exceeds its structure bound")
            continue
        if maximum_depth > _MAX_DEPTH or nodes > MAX_JSON_NODES:
            _fail("result-cell canonical JSON exceeds its structure bound")
        index += 1
    if in_string or escaped or depth != 0:
        _fail("result-cell canonical JSON is structurally invalid")


def _bounded_integer_token(token: str) -> int:
    if len(token) > _MAX_NUMBER_TOKEN_BYTES:
        _fail("result-cell canonical JSON contains an oversized number token")
    try:
        value = int(token)
    except ValueError:
        raise RawResultCellAuthorityError(
            "result-cell canonical JSON contains an invalid number"
        ) from None
    if abs(value) > _MAX_INTEGER_ABS:
        _fail("result-cell canonical JSON integer exceeds its exact bound")
    return value


def _bounded_float_token(token: str) -> float:
    if len(token) > _MAX_NUMBER_TOKEN_BYTES:
        _fail("result-cell canonical JSON contains an oversized number token")
    try:
        value = float(token)
    except ValueError:
        raise RawResultCellAuthorityError(
            "result-cell canonical JSON contains an invalid number"
        ) from None
    if not math.isfinite(value):
        _fail("result-cell canonical JSON contains a non-finite number")
    return value


def _decode_canonical_value(encoded: object) -> tuple[str, object]:
    if type(encoded) is not str or not encoded:
        _fail("result-cell canonical JSON must be nonempty exact text")
    try:
        raw = encoded.encode("utf-8", errors="strict")
    except UnicodeEncodeError:
        raise RawResultCellAuthorityError("result-cell canonical JSON is not UTF-8") from None
    if len(raw) > MAX_PARSER_INPUT_BYTES:
        _fail("result-cell canonical JSON exceeds its exact byte bound")
    _preflight_canonical_json_bytes(raw)
    try:
        value = json.loads(
            encoded,
            object_pairs_hook=_reject_duplicate_keys,
            parse_constant=_reject_nonfinite_constant,
            parse_float=_bounded_float_token,
            parse_int=_bounded_integer_token,
        )
    except RawResultCellAuthorityError:
        raise
    except (UnicodeError, ValueError, OverflowError, RecursionError):
        raise RawResultCellAuthorityError("result-cell canonical JSON cannot be decoded") from None
    nodes = 0
    stack: list[tuple[object, int]] = [(value, 0)]
    while stack:
        item, depth = stack.pop()
        nodes += 1
        if nodes > MAX_JSON_NODES or depth > _MAX_DEPTH:
            _fail("result-cell canonical JSON exceeds its node or depth bound")
        if type(item) is dict:
            mapping = cast("dict[str, object]", item)
            for key, child in mapping.items():
                _reject_sensitive_public_key(key)
                _reject_secret_shaped_public_text(key)
                stack.append((child, depth + 1))
        elif type(item) is list:
            stack.extend((child, depth + 1) for child in cast("list[object]", item))
        elif type(item) is str:
            _reject_secret_shaped_public_text(item)
        elif type(item) is int and abs(item) > _MAX_INTEGER_ABS:
            _fail("result-cell canonical JSON integer exceeds its exact bound")
        elif type(item) is float:
            if not math.isfinite(item):
                _fail("result-cell canonical JSON contains a non-finite number")
            if item == 0.0 and math.copysign(1.0, item) < 0:
                _fail("result-cell canonical JSON contains negative zero")
    try:
        canonical = canonical_json_bytes(value, maximum_bytes=MAX_PARSER_INPUT_BYTES)
    except ValueError:
        raise RawResultCellAuthorityError(
            "result-cell value cannot be encoded as bounded canonical JSON"
        ) from None
    if canonical != raw:
        _fail("result-cell JSON text is not the exact canonical encoding")
    return encoded, value


def _value_kind(value: object) -> CellValueKind:
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
    _fail("result-cell value has an unsupported JSON runtime type")


def _presence_kind(value: object) -> CellPresenceKind:
    if value is None:
        return "null"
    if type(value) is list and not value:
        return "empty_array"
    if type(value) is dict and not value:
        return "empty_object"
    return "present"


def _validate_runtime_json_value(value: object) -> None:
    """Reject subclasses and unsafe numeric values before canonical encoding."""

    nodes = 0
    stack: list[tuple[object, int]] = [(value, 0)]
    while stack:
        item, depth = stack.pop()
        nodes += 1
        if nodes > MAX_JSON_NODES or depth > _MAX_DEPTH:
            _fail("result-cell runtime value exceeds its node or depth bound")
        if item is None or type(item) is bool:
            continue
        if type(item) is str:
            _reject_secret_shaped_public_text(item)
            continue
        if type(item) is int:
            if abs(item) > _MAX_INTEGER_ABS:
                _fail("result-cell runtime integer exceeds its exact bound")
            continue
        if type(item) is float:
            number = cast("float", item)
            if not math.isfinite(number) or (number == 0.0 and math.copysign(1.0, number) < 0):
                _fail("result-cell runtime number is non-finite or negative zero")
            continue
        if type(item) is list:
            stack.extend((child, depth + 1) for child in cast("list[object]", item))
            continue
        if type(item) is dict:
            mapping = cast("dict[object, object]", item)
            if any(type(key) is not str for key in mapping):
                _fail("result-cell runtime object has a non-string exact key")
            for key in mapping:
                exact_key = cast("str", key)
                _reject_sensitive_public_key(exact_key)
                _reject_secret_shaped_public_text(exact_key)
            stack.extend((child, depth + 1) for child in mapping.values())
            continue
        _fail("result-cell runtime value contains a foreign JSON type")


def _cell_identity_payload(
    *,
    observation_sha256: str,
    occurrence_sha256: str,
    cell_ordinal: int,
    row_ordinal: int,
    header_ordinal: int,
    header_name: str,
    presence_kind: CellPresenceKind,
    value_kind: CellValueKind,
    canonical_json: str,
    canonical_json_sha256: str,
) -> dict[str, object]:
    return {
        "kind": _CELL_KIND,
        "schema_version": RAW_REQUEST_AUTHORITY_SCHEMA_VERSION,
        "observation_sha256": observation_sha256,
        "occurrence_sha256": occurrence_sha256,
        "cell_ordinal": cell_ordinal,
        "row_ordinal": row_ordinal,
        "header_ordinal": header_ordinal,
        "header_name": header_name,
        "presence_kind": presence_kind,
        "value_kind": value_kind,
        "canonical_json": canonical_json,
        "canonical_json_sha256": canonical_json_sha256,
    }


@dataclass(frozen=True, slots=True)
class RawNbaApiResultCellV2:
    """One exact duplicate-preserving provider cell under one result occurrence."""

    cell_sha256: str
    observation_sha256: str
    occurrence_sha256: str
    cell_ordinal: int
    row_ordinal: int
    header_ordinal: int
    header_name: str
    presence_kind: CellPresenceKind
    value_kind: CellValueKind
    canonical_json: str
    canonical_json_sha256: str

    schema_version: ClassVar[int] = RAW_REQUEST_AUTHORITY_SCHEMA_VERSION
    kind: ClassVar[str] = _CELL_KIND

    def __post_init__(self) -> None:
        for field_name in (
            "cell_sha256",
            "observation_sha256",
            "occurrence_sha256",
            "canonical_json_sha256",
        ):
            _exact_sha256(getattr(self, field_name), field_name=field_name)
        for field_name in ("cell_ordinal", "row_ordinal", "header_ordinal"):
            _exact_nonnegative(getattr(self, field_name), field_name=field_name)
        _validate_header_name(self.header_name)
        if type(self.presence_kind) is not str or self.presence_kind not in _PRESENCE_KINDS:
            _fail("result-cell presence kind is unsupported")
        if type(self.value_kind) is not str or self.value_kind not in _VALUE_KINDS:
            _fail("result-cell value kind is unsupported")
        canonical_json, value = _decode_canonical_value(self.canonical_json)
        if (
            self.canonical_json_sha256 != _sha256(canonical_json.encode("utf-8"))
            or self.value_kind != _value_kind(value)
            or self.presence_kind != _presence_kind(value)
        ):
            _fail("result-cell canonical value digest or kind projection is invalid")
        expected_cell = _canonical_sha256(
            _cell_identity_payload(
                observation_sha256=self.observation_sha256,
                occurrence_sha256=self.occurrence_sha256,
                cell_ordinal=self.cell_ordinal,
                row_ordinal=self.row_ordinal,
                header_ordinal=self.header_ordinal,
                header_name=self.header_name,
                presence_kind=self.presence_kind,
                value_kind=self.value_kind,
                canonical_json=self.canonical_json,
                canonical_json_sha256=self.canonical_json_sha256,
            )
        )
        if self.cell_sha256 != expected_cell:
            _fail("result-cell digest differs from its exact semantic projection")

    @classmethod
    def build(
        cls,
        *,
        observation_sha256: str,
        occurrence_sha256: str,
        cell_ordinal: int,
        row_ordinal: int,
        header_ordinal: int,
        header_name: str,
        value: object,
    ) -> Self:
        _validate_header_name(header_name)
        _validate_runtime_json_value(value)
        try:
            canonical_json = canonical_json_bytes(
                value,
                maximum_bytes=MAX_PARSER_INPUT_BYTES,
            ).decode("utf-8")
        except ValueError as exc:
            raise RawResultCellAuthorityError(
                "result-cell runtime value cannot be canonically encoded"
            ) from exc
        canonical_json, exact_value = _decode_canonical_value(canonical_json)
        canonical_json_sha256 = _sha256(canonical_json.encode("utf-8"))
        payload = _cell_identity_payload(
            observation_sha256=observation_sha256,
            occurrence_sha256=occurrence_sha256,
            cell_ordinal=cell_ordinal,
            row_ordinal=row_ordinal,
            header_ordinal=header_ordinal,
            header_name=header_name,
            presence_kind=_presence_kind(exact_value),
            value_kind=_value_kind(exact_value),
            canonical_json=canonical_json,
            canonical_json_sha256=canonical_json_sha256,
        )
        return cls(
            cell_sha256=_canonical_sha256(payload),
            observation_sha256=observation_sha256,
            occurrence_sha256=occurrence_sha256,
            cell_ordinal=cell_ordinal,
            row_ordinal=row_ordinal,
            header_ordinal=header_ordinal,
            header_name=header_name,
            presence_kind=_presence_kind(exact_value),
            value_kind=_value_kind(exact_value),
            canonical_json=canonical_json,
            canonical_json_sha256=canonical_json_sha256,
        )

    def value(self) -> object:
        """Return a new exact JSON value graph for reconstruction."""

        _encoded, value = _decode_canonical_value(self.canonical_json)
        return value

    def to_row(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "cell_sha256": self.cell_sha256,
            "observation_sha256": self.observation_sha256,
            "occurrence_sha256": self.occurrence_sha256,
            "cell_ordinal": self.cell_ordinal,
            "row_ordinal": self.row_ordinal,
            "header_ordinal": self.header_ordinal,
            "header_name": self.header_name,
            "presence_kind": self.presence_kind,
            "value_kind": self.value_kind,
            "canonical_json": self.canonical_json,
            "canonical_json_sha256": self.canonical_json_sha256,
        }

    @classmethod
    def from_row(cls, value: object) -> Self:
        expected = ("schema_version", *(field.name for field in fields(cls)))
        if type(value) is not dict:
            _fail("result-cell table row does not have its exact ordered contract columns")
        object_row = cast("dict[object, object]", value)
        if any(type(key) is not str for key in object_row) or tuple(object_row) != expected:
            _fail("result-cell table row does not have its exact ordered contract columns")
        row = cast("dict[str, object]", value)
        schema_version = row["schema_version"]
        if type(schema_version) is not int or (
            schema_version != RAW_REQUEST_AUTHORITY_SCHEMA_VERSION
        ):
            _fail("result-cell row schema version must be the exact integer 2")
        kwargs = {field.name: row[field.name] for field in fields(cls)}
        try:
            return cls(**kwargs)  # ty: ignore[invalid-argument-type]
        except (TypeError, ValueError) as exc:
            raise RawResultCellAuthorityError(
                "result-cell table row failed semantic reconstruction"
            ) from exc


@dataclass(frozen=True, slots=True)
class RawResultCellPublicTableProofV2:
    """Body-independent proof over exact public structured rows.

    This proof deliberately has no Raw Authority bundle label.  A caller may
    verify public observations, occurrences, and cells without acquiring the
    right to claim that those rows belong to an arbitrary bundle root.
    """

    proof_sha256: str
    observation_count: int
    observation_inventory_sha256: str
    occurrence_count: int
    occurrence_inventory_sha256: str
    eligible_occurrence_count: int
    eligible_occurrence_inventory_sha256: str
    cell_count: int
    cell_inventory_sha256: str
    cell_rows_sha256: str
    cells: tuple[RawNbaApiResultCellV2, ...]

    schema_version: ClassVar[int] = RAW_REQUEST_AUTHORITY_SCHEMA_VERSION
    kind: ClassVar[str] = _PUBLIC_TABLE_PROOF_KIND

    def __post_init__(self) -> None:
        for field_name in (
            "proof_sha256",
            "observation_inventory_sha256",
            "occurrence_inventory_sha256",
            "eligible_occurrence_inventory_sha256",
            "cell_inventory_sha256",
            "cell_rows_sha256",
        ):
            _exact_sha256(getattr(self, field_name), field_name=field_name)
        for field_name in (
            "observation_count",
            "occurrence_count",
            "eligible_occurrence_count",
            "cell_count",
        ):
            _exact_nonnegative(getattr(self, field_name), field_name=field_name)
        if (
            self.observation_count > _MAX_RESULT_OCCURRENCES
            or self.occurrence_count > _MAX_RESULT_OCCURRENCES
            or self.eligible_occurrence_count > _MAX_RESULT_OCCURRENCES
        ):
            _fail("result-cell public-table proof exceeds an explicit denominator bound")
        if self.cell_count > _MAX_RESULT_CELLS:
            _fail("result-cell public-table proof exceeds its total row bound")
        if (
            self.eligible_occurrence_count > self.occurrence_count
            or (self.occurrence_count > 0 and self.observation_count == 0)
            or (self.eligible_occurrence_count > 0 and self.occurrence_count == 0)
            or (self.cell_count > 0 and self.eligible_occurrence_count == 0)
        ):
            _fail("result-cell public-table proof denominators are inconsistent")
        if type(self.cells) is not tuple or len(self.cells) != self.cell_count:
            _fail("result-cell public-table proof count differs from its exact rows")
        if any(type(item) is not RawNbaApiResultCellV2 for item in self.cells):
            _fail("result-cell public-table proof contains a foreign DTO")
        cumulative_canonical_bytes = 0
        for item in self.cells:
            encoded = item.canonical_json
            if type(encoded) is not str:
                _fail("result-cell public-table proof DTO lacks exact canonical JSON text")
            try:
                cumulative_canonical_bytes += len(encoded.encode("utf-8", errors="strict"))
            except UnicodeEncodeError as exc:
                raise RawResultCellAuthorityError(
                    "result-cell public-table proof DTO canonical JSON is not UTF-8"
                ) from exc
            if cumulative_canonical_bytes > _MAX_GLOBAL_CELL_BYTES:
                _fail("result-cell public-table proof exceeds its cumulative canonical byte bound")
        try:
            rebuilt_cells = tuple(
                RawNbaApiResultCellV2.from_row(item.to_row()) for item in self.cells
            )
        except (TypeError, ValueError) as exc:
            raise RawResultCellAuthorityError(
                "result-cell public-table proof contains an invalid DTO"
            ) from exc
        if rebuilt_cells != self.cells:
            _fail("result-cell public-table proof DTO reconstruction drifted")
        if self.cell_inventory_sha256 != _canonical_ordered_root_sha256(
            kind=_CELL_INVENTORY_ROOT_KIND,
            count=self.cell_count,
            values=(item.cell_sha256 for item in rebuilt_cells),
        ) or self.cell_rows_sha256 != _canonical_ordered_root_sha256(
            kind=_CELL_ROWS_ROOT_KIND,
            count=self.cell_count,
            values=(item.to_row() for item in rebuilt_cells),
        ):
            _fail("result-cell public-table proof cell roots are invalid")
        if self.proof_sha256 != _canonical_sha256(self.identity_payload()):
            _fail("result-cell public-table proof digest is invalid")

    def identity_payload(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "kind": self.kind,
            "observation_count": self.observation_count,
            "observation_inventory_sha256": self.observation_inventory_sha256,
            "occurrence_count": self.occurrence_count,
            "occurrence_inventory_sha256": self.occurrence_inventory_sha256,
            "eligible_occurrence_count": self.eligible_occurrence_count,
            "eligible_occurrence_inventory_sha256": (self.eligible_occurrence_inventory_sha256),
            "cell_count": self.cell_count,
            "cell_inventory_sha256": self.cell_inventory_sha256,
            "cell_rows_sha256": self.cell_rows_sha256,
        }


def _preflight_public_table_proof_members(value: object) -> RawResultCellPublicTableProofV2:
    """Bound a receipt's proof container before any DTO reconstruction."""

    if type(value) is not RawResultCellPublicTableProofV2:
        _fail("result-cell authority receipt contains a foreign public-table proof")
    proof = value
    for field_name in (
        "proof_sha256",
        "observation_inventory_sha256",
        "occurrence_inventory_sha256",
        "eligible_occurrence_inventory_sha256",
        "cell_inventory_sha256",
        "cell_rows_sha256",
    ):
        _exact_sha256(getattr(proof, field_name), field_name=field_name)
    for field_name in (
        "observation_count",
        "occurrence_count",
        "eligible_occurrence_count",
        "cell_count",
    ):
        _exact_nonnegative(getattr(proof, field_name), field_name=field_name)
    if (
        proof.observation_count > _MAX_RESULT_OCCURRENCES
        or proof.occurrence_count > _MAX_RESULT_OCCURRENCES
        or proof.eligible_occurrence_count > _MAX_RESULT_OCCURRENCES
        or proof.cell_count > _MAX_RESULT_CELLS
        or proof.eligible_occurrence_count > proof.occurrence_count
    ):
        _fail("result-cell authority receipt proof denominators are invalid or over bound")
    cells = proof.cells
    if type(cells) is not tuple or len(cells) != proof.cell_count:
        _fail("result-cell authority receipt proof cell container is invalid")
    if any(type(item) is not RawNbaApiResultCellV2 for item in cells):
        _fail("result-cell authority receipt proof contains a foreign cell DTO")
    cumulative_canonical_bytes = 0
    for item in cells:
        encoded = item.canonical_json
        if type(encoded) is not str:
            _fail("result-cell authority receipt proof cell JSON is not exact text")
        try:
            cumulative_canonical_bytes += len(encoded.encode("utf-8", errors="strict"))
        except UnicodeEncodeError:
            raise RawResultCellAuthorityError(
                "result-cell authority receipt proof cell JSON is not UTF-8"
            ) from None
        if cumulative_canonical_bytes > _MAX_GLOBAL_CELL_BYTES:
            _fail("result-cell authority receipt proof exceeds its cumulative byte bound")
    return proof


@dataclass(frozen=True, slots=True)
class RawResultCellAuthorityReceiptV2:
    """Composite receipt emitted only after full Raw-bundle admission."""

    authority_sha256: str
    raw_authority_bundle_sha256: str
    public_table_proof_sha256: str
    public_table_proof: RawResultCellPublicTableProofV2

    schema_version: ClassVar[int] = RAW_REQUEST_AUTHORITY_SCHEMA_VERSION
    kind: ClassVar[str] = "raw_nba_api_result_cell_authority_receipt_v2"

    def __post_init__(self) -> None:
        for field_name in (
            "authority_sha256",
            "raw_authority_bundle_sha256",
            "public_table_proof_sha256",
        ):
            _exact_sha256(getattr(self, field_name), field_name=field_name)
        proof = _preflight_public_table_proof_members(self.public_table_proof)
        try:
            rebuilt_proof = RawResultCellPublicTableProofV2(
                **{field.name: getattr(proof, field.name) for field in fields(proof)}
            )
        except (TypeError, ValueError):
            raise RawResultCellAuthorityError(
                "result-cell authority receipt contains an invalid public-table proof"
            ) from None
        if rebuilt_proof != proof or self.public_table_proof_sha256 != rebuilt_proof.proof_sha256:
            _fail("result-cell authority receipt public-table proof binding is invalid")
        if self.authority_sha256 != _canonical_sha256(self.identity_payload()):
            _fail("result-cell authority receipt digest is invalid")

    def identity_payload(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "kind": self.kind,
            "raw_authority_bundle_sha256": self.raw_authority_bundle_sha256,
            "public_table_proof_sha256": self.public_table_proof_sha256,
        }


def _observation_semantic_order_key(
    observation: RequestObservationV2,
) -> tuple[object, ...]:
    attempt = observation.attempt
    page_discriminator = 0 if attempt.page_ordinal is None else 1
    page_ordinal = 0 if attempt.page_ordinal is None else attempt.page_ordinal
    return (
        attempt.logical_invocation_sha256,
        attempt.semantic_request_sha256,
        attempt.provider_call_ordinal,
        page_discriminator,
        page_ordinal,
        attempt.provider_call_role,
        attempt.provider_call_sha256,
        attempt.retry_ordinal,
        attempt.request_ordinal,
    )


def _canonical_observation_inventory(
    observations: tuple[RequestObservationV2, ...],
) -> tuple[tuple[RequestObservationV2, ...], dict[str, tuple[object, ...]]]:
    observation_by_sha: dict[str, RequestObservationV2] = {}
    semantic_owner: dict[tuple[object, ...], str] = {}
    order_by_sha: dict[str, tuple[object, ...]] = {}
    for observation in observations:
        observation_sha256 = observation.attempt.observation_sha256
        if observation_sha256 in observation_by_sha:
            _fail("structured result-cell observations contain duplicate identities")
        semantic_key = _observation_semantic_order_key(observation)
        prior_owner = semantic_owner.get(semantic_key)
        if prior_owner is not None and prior_owner != observation_sha256:
            _fail("structured result-cell observations collide on semantic order coordinates")
        observation_by_sha[observation_sha256] = observation
        semantic_owner[semantic_key] = observation_sha256
        order_by_sha[observation_sha256] = (*semantic_key, observation_sha256)
    ordered = tuple(
        sorted(
            observations,
            key=lambda item: order_by_sha[item.attempt.observation_sha256],
        )
    )
    return ordered, order_by_sha


def _exact_observation_sequence(value: object) -> tuple[RequestObservationV2, ...]:
    if type(value) not in {tuple, list}:
        _fail("result-cell public observations must be one exact structured row sequence")
    rows = cast("tuple[object, ...] | list[object]", value)
    if len(rows) > _MAX_RESULT_OCCURRENCES:
        _fail("result-cell public observations exceed their explicit row bound")
    if any(type(item) is not RequestObservationV2 for item in rows):
        _fail("result-cell public observations contain a foreign structured row type")
    rebuilt: list[RequestObservationV2] = []
    for item in cast("tuple[RequestObservationV2, ...] | list[RequestObservationV2]", rows):
        _preflight_request_observation(item)
        try:
            rebuilt.append(RequestObservationV2.from_canonical_bytes(item.to_canonical_bytes()))
        except (TypeError, ValueError) as exc:
            raise RawResultCellAuthorityError(
                "result-cell public observation failed exact DTO reconstruction"
            ) from exc
    return tuple(rebuilt)


def _preflight_occurrence_header_bounds(occurrence: ResultOccurrenceV2) -> None:
    _exact_nonnegative(occurrence.header_count, field_name="header_count")
    if occurrence.header_count > _MAX_RESULT_HEADERS:
        _fail("stats/static occurrence exceeds its explicit header bound")
    if type(occurrence.ordered_headers_json) is not str:
        _fail("stats/static occurrence ordered headers must be exact text")
    try:
        ordered_header_bytes = len(occurrence.ordered_headers_json.encode("utf-8", errors="strict"))
    except UnicodeEncodeError as exc:
        raise RawResultCellAuthorityError(
            "stats/static occurrence ordered headers are not UTF-8"
        ) from exc
    if ordered_header_bytes > MAX_PARSER_INPUT_BYTES:
        _fail("stats/static occurrence exceeds its explicit header byte bound")


def _exact_occurrence_sequence(value: object) -> tuple[ResultOccurrenceV2, ...]:
    if type(value) not in {tuple, list}:
        _fail("result-cell public occurrences must be one exact structured row sequence")
    rows = cast("tuple[object, ...] | list[object]", value)
    if len(rows) > _MAX_RESULT_OCCURRENCES:
        _fail("result-cell public occurrences exceed their explicit row bound")
    if any(type(item) is not ResultOccurrenceV2 for item in rows):
        _fail("result-cell public occurrences contain a foreign structured row type")
    rebuilt: list[ResultOccurrenceV2] = []
    for item in cast("tuple[ResultOccurrenceV2, ...] | list[ResultOccurrenceV2]", rows):
        _preflight_result_occurrence(item)
        _preflight_occurrence_header_bounds(item)
        try:
            rebuilt.append(ResultOccurrenceV2.from_canonical_bytes(item.to_canonical_bytes()))
        except (TypeError, ValueError) as exc:
            raise RawResultCellAuthorityError(
                "result-cell public occurrence failed exact DTO reconstruction"
            ) from exc
    return tuple(rebuilt)


def _canonical_occurrence_inventory(
    *,
    observations: tuple[RequestObservationV2, ...],
    occurrences: tuple[ResultOccurrenceV2, ...],
    observation_order: dict[str, tuple[object, ...]],
) -> tuple[tuple[ResultOccurrenceV2, ...], dict[str, tuple[object, ...]]]:
    by_observation: defaultdict[str, list[ResultOccurrenceV2]] = defaultdict(list)
    occurrence_by_sha: dict[str, ResultOccurrenceV2] = {}
    order_by_sha: dict[str, tuple[object, ...]] = {}
    seen_coordinates: set[tuple[str, int]] = set()
    for occurrence in occurrences:
        if occurrence.occurrence_sha256 in occurrence_by_sha:
            _fail("structured result-cell occurrences contain duplicate identities")
        if occurrence.observation_sha256 not in observation_order:
            _fail("structured result-cell occurrence references a missing observation")
        coordinate = (occurrence.observation_sha256, occurrence.occurrence_ordinal)
        if coordinate in seen_coordinates:
            _fail("structured result-cell occurrences collide on semantic order coordinates")
        seen_coordinates.add(coordinate)
        occurrence_by_sha[occurrence.occurrence_sha256] = occurrence
        by_observation[occurrence.observation_sha256].append(occurrence)
        order_by_sha[occurrence.occurrence_sha256] = (
            *observation_order[occurrence.observation_sha256],
            occurrence.occurrence_ordinal,
        )

    for observation in observations:
        observation_sha256 = observation.attempt.observation_sha256
        rows = tuple(
            sorted(
                by_observation.get(observation_sha256, ()),
                key=lambda item: item.occurrence_ordinal,
            )
        )
        if tuple(item.occurrence_ordinal for item in rows) != tuple(range(len(rows))):
            _fail("structured result-cell occurrence ordinals are not contiguous")
        if observation.result_occurrence_count != len(
            rows
        ) or observation.result_occurrences_sha256 != _canonical_sha256(
            [item.occurrence_sha256 for item in rows]
        ):
            _fail("structured result-cell observation occurrence closure is invalid")

    ordered = tuple(sorted(occurrences, key=lambda item: order_by_sha[item.occurrence_sha256]))
    return ordered, order_by_sha


def _eligible_occurrence_inventory(
    observations: tuple[RequestObservationV2, ...],
    occurrences: tuple[ResultOccurrenceV2, ...],
) -> tuple[
    tuple[ResultOccurrenceV2, ...],
    dict[str, RequestObservationV2],
    dict[str, ResultOccurrenceV2],
    dict[str, tuple[object, ...]],
    int,
    tuple[RequestObservationV2, ...],
    tuple[ResultOccurrenceV2, ...],
]:
    """Validate every eligible shape and derive its bundle-owned row order."""

    canonical_observations, observation_order = _canonical_observation_inventory(observations)
    canonical_occurrences, occurrence_order = _canonical_occurrence_inventory(
        observations=canonical_observations,
        occurrences=occurrences,
        observation_order=observation_order,
    )
    observation_by_sha = {item.attempt.observation_sha256: item for item in canonical_observations}
    occurrence_by_sha = {item.occurrence_sha256: item for item in canonical_occurrences}
    expected: list[ResultOccurrenceV2] = []
    occurrence_count_by_observation: defaultdict[str, int] = defaultdict(int)
    row_count_by_observation: defaultdict[str, int] = defaultdict(int)
    header_count_by_observation: defaultdict[str, int] = defaultdict(int)
    header_bytes_by_observation: defaultdict[str, int] = defaultdict(int)
    cell_count_by_observation: defaultdict[str, int] = defaultdict(int)
    expected_cell_count = 0
    global_occurrence_count = 0
    global_row_count = 0
    global_header_count = 0
    global_header_bytes = 0
    global_cell_count = 0

    for occurrence in canonical_occurrences:
        observation = observation_by_sha.get(occurrence.observation_sha256)
        if observation is None:
            _fail("structured result-cell occurrence references a missing observation")
        source_family = observation.attempt.source_family
        if source_family not in {"stats", "static"}:
            continue
        expected_container = (
            "nba_api_result_set" if source_family == "stats" else "nba_api_static_records"
        )
        if occurrence.container_kind != expected_container:
            _fail("result-cell occurrence container differs from its source family")
        for field_name in ("header_count", "row_count", "cell_count"):
            _exact_nonnegative(getattr(occurrence, field_name), field_name=field_name)
        if occurrence.header_count > _MAX_RESULT_HEADERS:
            _fail("stats/static occurrence exceeds its explicit header bound")
        if occurrence.row_count > _MAX_RESULT_ROWS:
            _fail("stats/static occurrence exceeds its explicit row bound")
        if occurrence.cell_count != occurrence.header_count * occurrence.row_count:
            _fail("stats/static occurrence is not an exact rectangular value packet")
        if occurrence.cell_count > _MAX_RESULT_CELLS:
            _fail("stats/static occurrence exceeds its explicit cell bound")
        if type(occurrence.ordered_headers_json) is not str:
            _fail("stats/static occurrence ordered headers must be exact text")
        try:
            ordered_header_bytes = len(
                occurrence.ordered_headers_json.encode("utf-8", errors="strict")
            )
        except UnicodeEncodeError as exc:
            raise RawResultCellAuthorityError(
                "stats/static occurrence ordered headers are not UTF-8"
            ) from exc
        if ordered_header_bytes > MAX_PARSER_INPUT_BYTES:
            _fail("stats/static occurrence exceeds its explicit header byte bound")
        headers = occurrence.ordered_headers()
        if occurrence.header_count != len(headers):
            _fail("stats/static occurrence header denominator is inconsistent")
        for header in headers:
            _validate_header_name(header)

        observation_sha256 = occurrence.observation_sha256
        occurrence_count_by_observation[observation_sha256] += 1
        row_count_by_observation[observation_sha256] += occurrence.row_count
        header_count_by_observation[observation_sha256] += occurrence.header_count
        header_bytes_by_observation[observation_sha256] += ordered_header_bytes
        cell_count_by_observation[observation_sha256] += occurrence.cell_count
        global_occurrence_count += 1
        global_row_count += occurrence.row_count
        global_header_count += occurrence.header_count
        global_header_bytes += ordered_header_bytes
        global_cell_count += occurrence.cell_count
        if (
            occurrence_count_by_observation[observation_sha256] > _MAX_RESULT_OCCURRENCES
            or row_count_by_observation[observation_sha256] > _MAX_RESULT_ROWS
            or header_count_by_observation[observation_sha256] > _MAX_RESULT_HEADERS
            or header_bytes_by_observation[observation_sha256] > MAX_PARSER_INPUT_BYTES
            or cell_count_by_observation[observation_sha256] > _MAX_RESULT_CELLS
            or global_occurrence_count > _MAX_RESULT_OCCURRENCES
            or global_row_count > _MAX_GLOBAL_RESULT_ROWS
            or global_header_count > _MAX_GLOBAL_RESULT_HEADERS
            or global_header_bytes > _MAX_GLOBAL_HEADER_BYTES
            or global_cell_count > _MAX_RESULT_CELLS
        ):
            _fail("result-cell observation or bundle exceeds its cumulative shape bound")

        # `wide_plus_lossless` is a route-admission fact, not a second value
        # representation. Its sealed occurrence output includes fallback
        # anomaly material and therefore belongs solely to the lossless table.
        if occurrence.landing_disposition != "wide_only":
            continue
        if len(expected) >= _MAX_RESULT_OCCURRENCES:
            _fail("result-cell authority exceeds its explicit occurrence bound")
        expected_cell_count += occurrence.cell_count
        if expected_cell_count > _MAX_RESULT_CELLS:
            _fail("result-cell observation or bundle exceeds its cumulative shape bound")
        expected.append(occurrence)

    if len(expected) > _MAX_RESULT_OCCURRENCES:
        _fail("result-cell authority exceeds its explicit occurrence bound")
    return (
        tuple(expected),
        observation_by_sha,
        occurrence_by_sha,
        occurrence_order,
        expected_cell_count,
        canonical_observations,
        canonical_occurrences,
    )


def _occurrence_output_sha256(
    occurrence: ResultOccurrenceV2,
    cells: tuple[RawNbaApiResultCellV2, ...],
) -> str:
    """Stream the exact normalized packet without decoding numeric tokens."""

    if type(occurrence) is not ResultOccurrenceV2:
        _fail("result-cell output reconstruction requires an exact occurrence DTO")
    _preflight_result_occurrence(occurrence)
    _preflight_occurrence_header_bounds(occurrence)
    for field_name in ("header_count", "row_count", "cell_count"):
        _exact_nonnegative(getattr(occurrence, field_name), field_name=field_name)
    if occurrence.header_count > _MAX_RESULT_HEADERS:
        _fail("stats/static occurrence exceeds its explicit header bound")
    if occurrence.row_count > _MAX_RESULT_ROWS:
        _fail("stats/static occurrence exceeds its explicit row bound")
    if occurrence.cell_count != occurrence.header_count * occurrence.row_count:
        _fail("stats/static occurrence is not an exact rectangular value packet")
    if occurrence.cell_count > _MAX_RESULT_CELLS:
        _fail("stats/static occurrence exceeds its explicit cell bound")
    try:
        ordered_header_bytes = len(occurrence.ordered_headers_json.encode("utf-8", errors="strict"))
    except UnicodeEncodeError as exc:
        raise RawResultCellAuthorityError(
            "stats/static occurrence ordered headers are not UTF-8"
        ) from exc
    if ordered_header_bytes > MAX_PARSER_INPUT_BYTES:
        _fail("stats/static occurrence exceeds its explicit header byte bound")
    try:
        occurrence = ResultOccurrenceV2.from_canonical_bytes(occurrence.to_canonical_bytes())
    except (TypeError, ValueError) as exc:
        raise RawResultCellAuthorityError(
            "result-cell occurrence failed exact DTO reconstruction"
        ) from exc
    if occurrence.landing_disposition != "wide_only":
        _fail("result occurrence is not assigned the rectangular-cell representation")
    if len(cells) != occurrence.cell_count:
        _fail("result-cell inventory is missing or additive for one occurrence")
    headers = occurrence.ordered_headers()
    if occurrence.header_count != len(headers):
        _fail("stats/static occurrence header denominator is inconsistent")
    for header in headers:
        _validate_header_name(header)

    output = hashlib.sha256()
    output.update(b'{"headers":')
    output.update(canonical_json_bytes(list(headers), maximum_bytes=MAX_PARSER_INPUT_BYTES))
    output.update(b',"rows":[')
    for expected_ordinal, cell in enumerate(cells):
        row_ordinal, header_ordinal = divmod(expected_ordinal, occurrence.header_count)
        if (
            cell.cell_ordinal != expected_ordinal
            or cell.row_ordinal != row_ordinal
            or cell.header_ordinal != header_ordinal
            or row_ordinal >= occurrence.row_count
            or cell.header_name != headers[header_ordinal]
        ):
            _fail("result-cell Cartesian ordinal or header join is invalid")

    cursor = 0
    for row_ordinal in range(occurrence.row_count):
        if row_ordinal:
            output.update(b",")
        output.update(b"[")
        for header_ordinal in range(occurrence.header_count):
            if header_ordinal:
                output.update(b",")
            output.update(cells[cursor].canonical_json.encode("utf-8"))
            cursor += 1
        output.update(b"]")
    output.update(b"]}")
    if cursor != len(cells):
        _fail("result-cell reconstruction did not consume its exact denominator")
    return output.hexdigest()


def validate_raw_result_cell_public_table(
    *,
    observations: object,
    occurrences: object,
    cells: object,
) -> RawResultCellPublicTableProofV2:
    """Verify only structured public rows without claiming a Raw bundle root.

    This function deliberately performs no raw-bundle admission, parser-input
    decoding, provider parsing, or staging-route mapping. The composition
    wrapper below owns full-bundle admission and is the only function here that
    emits a bundle-bound authority receipt.
    """

    structured_observations = _exact_observation_sequence(observations)
    structured_occurrences = _exact_occurrence_sequence(occurrences)
    (
        expected_occurrence_inventory,
        observation_by_sha,
        occurrence_by_sha,
        occurrence_order,
        expected_cell_count,
        canonical_observations,
        canonical_occurrences,
    ) = _eligible_occurrence_inventory(structured_observations, structured_occurrences)
    expected_occurrences = {item.occurrence_sha256: item for item in expected_occurrence_inventory}
    if type(cells) not in {tuple, list}:
        _fail("result-cell authority rows must be one exact sequence")
    raw_sequence = cast("tuple[object, ...] | list[object]", cells)
    if len(raw_sequence) > _MAX_RESULT_CELLS:
        _fail("result-cell authority exceeds its total row bound")
    if len(raw_sequence) != expected_cell_count:
        _fail("result-cell authority count differs from its eligible Cartesian denominator")
    raw_cells = raw_sequence if type(raw_sequence) is tuple else tuple(raw_sequence)
    global_cell_bytes = 0
    for raw_cell in raw_cells:
        if type(raw_cell) is RawNbaApiResultCellV2:
            encoded = raw_cell.canonical_json
        elif type(raw_cell) is dict:
            object_row = cast("dict[object, object]", raw_cell)
            expected_columns = (
                "schema_version",
                *(field.name for field in fields(RawNbaApiResultCellV2)),
            )
            if any(type(key) is not str for key in object_row) or (
                tuple(object_row) != expected_columns
            ):
                _fail("result-cell table row does not have its exact ordered contract columns")
            encoded = cast("dict[str, object]", raw_cell)["canonical_json"]
        else:
            encoded = None
        if type(encoded) is not str:
            _fail("result-cell authority row lacks exact canonical JSON text")
        try:
            global_cell_bytes += len(encoded.encode("utf-8", errors="strict"))
        except UnicodeEncodeError as exc:
            raise RawResultCellAuthorityError(
                "result-cell authority row canonical JSON is not UTF-8"
            ) from exc
        if global_cell_bytes > _MAX_GLOBAL_CELL_BYTES:
            _fail("result-cell bundle exceeds its cumulative canonical byte bound")
    exact_cells = tuple(
        RawNbaApiResultCellV2.from_row(item.to_row())
        if type(item) is RawNbaApiResultCellV2
        else RawNbaApiResultCellV2.from_row(item)
        for item in raw_cells
    )
    cells_by_occurrence: defaultdict[str, list[RawNbaApiResultCellV2]] = defaultdict(list)
    bytes_by_observation: defaultdict[str, int] = defaultdict(int)
    count_by_observation: defaultdict[str, int] = defaultdict(int)
    for cell in exact_cells:
        occurrence = occurrence_by_sha.get(cell.occurrence_sha256)
        if occurrence is None or occurrence.observation_sha256 != cell.observation_sha256:
            _fail("result cell references a missing or cross-observation occurrence")
        observation = observation_by_sha.get(cell.observation_sha256)
        if observation is None or observation.attempt.source_family not in {"stats", "static"}:
            _fail("result-cell authority contains a live or foreign-family cell")
        if cell.occurrence_sha256 not in expected_occurrences:
            _fail("result-cell authority contains foreign occurrence membership")
        cells_by_occurrence[cell.occurrence_sha256].append(cell)
        bytes_by_observation[cell.observation_sha256] += len(cell.canonical_json.encode("utf-8"))
        count_by_observation[cell.observation_sha256] += 1
        if (
            bytes_by_observation[cell.observation_sha256] > MAX_PARSER_INPUT_BYTES
            or count_by_observation[cell.observation_sha256] > _MAX_RESULT_CELLS
        ):
            _fail("result-cell observation exceeds its cumulative row or byte bound")

    canonical_order = tuple(
        sorted(
            exact_cells,
            key=lambda item: (
                *occurrence_order[item.occurrence_sha256],
                item.cell_ordinal,
            ),
        )
    )
    if exact_cells != canonical_order:
        _fail("result-cell authority rows are not in canonical occurrence order")
    if (
        len({item.cell_sha256 for item in exact_cells}) != len(exact_cells)
        or len({(item.occurrence_sha256, item.cell_ordinal) for item in exact_cells})
        != len(exact_cells)
        or len(
            {
                (item.occurrence_sha256, item.row_ordinal, item.header_ordinal)
                for item in exact_cells
            }
        )
        != len(exact_cells)
    ):
        _fail("result-cell authority contains duplicate keys or Cartesian positions")
    if len(exact_cells) != expected_cell_count:
        _fail("result-cell authority count differs from its eligible Cartesian denominator")

    for occurrence in expected_occurrence_inventory:
        occurrence_cells = tuple(cells_by_occurrence.get(occurrence.occurrence_sha256, ()))
        if _occurrence_output_sha256(occurrence, occurrence_cells) != occurrence.output_sha256:
            _fail("result-cell values do not reconstruct the exact occurrence output digest")

    inventory_sha256 = _canonical_ordered_root_sha256(
        kind=_CELL_INVENTORY_ROOT_KIND,
        count=len(exact_cells),
        values=(item.cell_sha256 for item in exact_cells),
    )
    rows_sha256 = _canonical_ordered_root_sha256(
        kind=_CELL_ROWS_ROOT_KIND,
        count=len(exact_cells),
        values=(item.to_row() for item in exact_cells),
    )
    observation_inventory_sha256 = _canonical_ordered_root_sha256(
        kind=_OBSERVATION_INVENTORY_ROOT_KIND,
        count=len(canonical_observations),
        values=(item.observation_record_sha256 for item in canonical_observations),
    )
    occurrence_inventory_sha256 = _canonical_ordered_root_sha256(
        kind=_OCCURRENCE_INVENTORY_ROOT_KIND,
        count=len(canonical_occurrences),
        values=(item.occurrence_sha256 for item in canonical_occurrences),
    )
    eligible_occurrence_inventory_sha256 = _canonical_ordered_root_sha256(
        kind=_ELIGIBLE_OCCURRENCE_INVENTORY_ROOT_KIND,
        count=len(expected_occurrence_inventory),
        values=(item.occurrence_sha256 for item in expected_occurrence_inventory),
    )
    payload = {
        "schema_version": RAW_REQUEST_AUTHORITY_SCHEMA_VERSION,
        "kind": RawResultCellPublicTableProofV2.kind,
        "observation_count": len(canonical_observations),
        "observation_inventory_sha256": observation_inventory_sha256,
        "occurrence_count": len(canonical_occurrences),
        "occurrence_inventory_sha256": occurrence_inventory_sha256,
        "eligible_occurrence_count": len(expected_occurrence_inventory),
        "eligible_occurrence_inventory_sha256": (eligible_occurrence_inventory_sha256),
        "cell_count": len(exact_cells),
        "cell_inventory_sha256": inventory_sha256,
        "cell_rows_sha256": rows_sha256,
    }
    return RawResultCellPublicTableProofV2(
        proof_sha256=_canonical_sha256(payload),
        observation_count=len(canonical_observations),
        observation_inventory_sha256=observation_inventory_sha256,
        occurrence_count=len(canonical_occurrences),
        occurrence_inventory_sha256=occurrence_inventory_sha256,
        eligible_occurrence_count=len(expected_occurrence_inventory),
        eligible_occurrence_inventory_sha256=eligible_occurrence_inventory_sha256,
        cell_count=len(exact_cells),
        cell_inventory_sha256=inventory_sha256,
        cell_rows_sha256=rows_sha256,
        cells=exact_cells,
    )


def _exact_raw_request_authority_bundle(
    value: object,
) -> RawRequestAuthorityBundleV2:
    """Canonical-reconstruct every bundle member before full admission."""

    bundle_storage = _exact_model_storage(
        value,
        expected_type=RawRequestAuthorityBundleV2,
        label="result-cell raw request bundle",
    )
    schema_version = bundle_storage["schema_version"]
    bundle_sha256 = bundle_storage["bundle_sha256"]
    if type(schema_version) is not int or schema_version != RAW_REQUEST_AUTHORITY_SCHEMA_VERSION:
        _fail("result-cell raw request bundle schema version is invalid")
    _exact_sha256(bundle_sha256, field_name="raw_authority_bundle_sha256")

    member_contracts = (
        (
            "objects",
            bundle_storage["objects"],
            ParserInputObjectV2,
            _preflight_parser_input_object,
        ),
        (
            "observations",
            bundle_storage["observations"],
            RequestObservationV2,
            _preflight_request_observation,
        ),
        (
            "occurrences",
            bundle_storage["occurrences"],
            ResultOccurrenceV2,
            _preflight_result_occurrence,
        ),
        (
            "landings",
            bundle_storage["landings"],
            ObservationRouteLandingV2,
            _preflight_route_landing,
        ),
    )
    for field_name, rows, expected_type, preflight in member_contracts:
        if type(rows) is not tuple:
            _fail(f"result-cell raw request bundle {field_name} sequence is invalid or over bound")
        exact_rows = rows
        if len(exact_rows) > _MAX_RESULT_OCCURRENCES:
            _fail(f"result-cell raw request bundle {field_name} sequence is invalid or over bound")
        if any(type(item) is not expected_type for item in exact_rows):
            _fail(f"result-cell raw request bundle {field_name} contains a foreign DTO")
        for item in exact_rows:
            preflight(item)

    bundle = cast("RawRequestAuthorityBundleV2", value)

    try:
        object_bytes = tuple(item.to_canonical_bytes() for item in bundle.objects)
        observation_bytes = tuple(item.to_canonical_bytes() for item in bundle.observations)
        occurrence_bytes = tuple(item.to_canonical_bytes() for item in bundle.occurrences)
        landing_bytes = tuple(item.to_canonical_bytes() for item in bundle.landings)
        objects = tuple(
            ParserInputObjectV2.from_canonical_bytes(encoded) for encoded in object_bytes
        )
        observations = tuple(
            RequestObservationV2.from_canonical_bytes(encoded) for encoded in observation_bytes
        )
        occurrences = tuple(
            ResultOccurrenceV2.from_canonical_bytes(encoded) for encoded in occurrence_bytes
        )
        landings = tuple(
            ObservationRouteLandingV2.from_canonical_bytes(encoded) for encoded in landing_bytes
        )
        rebuilt = validate_raw_request_authority_bundle(
            {
                "schema_version": schema_version,
                "bundle_sha256": bundle_sha256,
                "objects": objects,
                "observations": observations,
                "occurrences": occurrences,
                "landings": landings,
            }
        )
    except (TypeError, ValueError) as exc:
        raise RawResultCellAuthorityError(
            "result-cell authority received an invalid raw request bundle"
        ) from exc
    rebuilt_member_bytes = (
        tuple(item.to_canonical_bytes() for item in rebuilt.objects),
        tuple(item.to_canonical_bytes() for item in rebuilt.observations),
        tuple(item.to_canonical_bytes() for item in rebuilt.occurrences),
        tuple(item.to_canonical_bytes() for item in rebuilt.landings),
    )
    if (
        rebuilt.schema_version != schema_version
        or rebuilt.bundle_sha256 != bundle_sha256
        or rebuilt_member_bytes
        != (object_bytes, observation_bytes, occurrence_bytes, landing_bytes)
    ):
        _fail("result-cell raw request bundle canonical reconstruction drifted")
    return rebuilt


def validate_raw_result_cell_authority(
    authority_bundle: RawRequestAuthorityBundleV2,
    cells: object,
) -> RawResultCellAuthorityReceiptV2:
    """Admit one full raw bundle, then close its structured stats/static cells."""

    bundle = _exact_raw_request_authority_bundle(authority_bundle)
    proof = validate_raw_result_cell_public_table(
        observations=bundle.observations,
        occurrences=bundle.occurrences,
        cells=cells,
    )
    payload = {
        "schema_version": RAW_REQUEST_AUTHORITY_SCHEMA_VERSION,
        "kind": RawResultCellAuthorityReceiptV2.kind,
        "raw_authority_bundle_sha256": bundle.bundle_sha256,
        "public_table_proof_sha256": proof.proof_sha256,
    }
    return RawResultCellAuthorityReceiptV2(
        authority_sha256=_canonical_sha256(payload),
        raw_authority_bundle_sha256=bundle.bundle_sha256,
        public_table_proof_sha256=proof.proof_sha256,
        public_table_proof=proof,
    )


def validate_raw_result_cell_authority_receipt(
    authority_bundle: RawRequestAuthorityBundleV2,
    receipt: object,
) -> RawResultCellAuthorityReceiptV2:
    """Recompute a composite receipt against its exact bundle and public rows."""

    if type(receipt) is not RawResultCellAuthorityReceiptV2:
        _fail("result-cell authority receipt has a foreign DTO type")
    candidate = receipt
    for field_name in (
        "authority_sha256",
        "raw_authority_bundle_sha256",
        "public_table_proof_sha256",
    ):
        _exact_sha256(getattr(candidate, field_name), field_name=field_name)
    bundle_storage = _exact_model_storage(
        authority_bundle,
        expected_type=RawRequestAuthorityBundleV2,
        label="result-cell receipt external raw request bundle",
    )
    bundle_schema_version = bundle_storage["schema_version"]
    bundle_sha256 = _exact_sha256(
        bundle_storage["bundle_sha256"],
        field_name="receipt_external_raw_authority_bundle_sha256",
    )
    if (
        type(bundle_schema_version) is not int
        or bundle_schema_version != RAW_REQUEST_AUTHORITY_SCHEMA_VERSION
        or candidate.raw_authority_bundle_sha256 != bundle_sha256
    ):
        _fail("result-cell authority receipt does not bind its external raw bundle root")
    proof = _preflight_public_table_proof_members(candidate.public_table_proof)
    if candidate.public_table_proof_sha256 != proof.proof_sha256:
        _fail("result-cell authority receipt differs from its external public-table proof root")
    try:
        rebuilt_candidate = RawResultCellAuthorityReceiptV2(
            **{
                field.name: getattr(candidate, field.name)
                for field in fields(RawResultCellAuthorityReceiptV2)
            }
        )
    except (TypeError, ValueError):
        raise RawResultCellAuthorityError(
            "result-cell authority receipt failed exact DTO reconstruction"
        ) from None
    expected = validate_raw_result_cell_authority(
        authority_bundle,
        rebuilt_candidate.public_table_proof.cells,
    )
    if rebuilt_candidate != candidate or rebuilt_candidate != expected:
        _fail("result-cell authority receipt does not bind the admitted raw bundle")
    return expected
