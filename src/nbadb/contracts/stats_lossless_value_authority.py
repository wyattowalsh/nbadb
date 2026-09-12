"""Public value authority for lossless NBA Stats fallback records.

This contract is intentionally versioned independently from Raw Authority V2.
It describes public structured rows only: parser-input bytes and production
parser/staging objects are outside this module's trust boundary.
"""

from __future__ import annotations

import hashlib
import json
import math
import re
from collections import Counter
from dataclasses import dataclass, fields
from typing import TYPE_CHECKING, ClassVar, Final, Literal, Never, Self, cast

from nbadb.contracts.public_value_types import (
    ExpectedValueUnitInventoryV1,
    ExpectedValueUnitV1,
    ValueRepresentationAssignmentV1,
)

if TYPE_CHECKING:
    from collections.abc import Iterable, Mapping, Sequence
    from typing import Any

__all__ = [
    "MAX_STATS_LOSSLESS_CANONICAL_BYTES",
    "MAX_STATS_LOSSLESS_CELLS",
    "MAX_STATS_LOSSLESS_HEADERS",
    "MAX_STATS_LOSSLESS_RECORDS",
    "MAX_STATS_LOSSLESS_RESULTS",
    "MAX_STATS_LOSSLESS_ROWS",
    "MAX_STATS_LOSSLESS_TOTAL_CANONICAL_BYTES",
    "PUBLIC_VALUE_AUTHORITY_SCHEMA_VERSION",
    "RESPONSE_LOSSLESS_REPRESENTATION_KIND",
    "STATS_LOSSLESS_RECORD_COLUMNS",
    "STATS_LOSSLESS_RECORD_SCHEMA_SHA256",
    "STATS_LOSSLESS_REPRESENTATION_KIND",
    "STATS_LOSSLESS_SOURCE_COLUMNS",
    "STATS_LOSSLESS_SOURCE_SCHEMA_SHA256",
    "StatsLosslessOwnerKind",
    "StatsLosslessManifestV1",
    "StatsLosslessRecordV1",
    "StatsLosslessResultV1",
    "StatsLosslessValueAuthorityV1",
    "StatsLosslessValueAuthorityError",
    "StatsLosslessValueAuthorityReceiptV1",
    "build_stats_lossless_value_authority",
    "canonical_json_bytes",
    "canonical_ordered_root_sha256",
    "canonical_sha256",
    "json_presence_kind",
    "json_value_kind",
    "stats_lossless_result_declaration_value",
]

PUBLIC_VALUE_AUTHORITY_SCHEMA_VERSION: Final = 1
STATS_LOSSLESS_REPRESENTATION_KIND: Final = "stats_lossless_records_v1"
RESPONSE_LOSSLESS_REPRESENTATION_KIND: Final = "response_lossless_records_v1"

MAX_STATS_LOSSLESS_RESULTS: Final = 256
MAX_STATS_LOSSLESS_HEADERS: Final = 4_096
MAX_STATS_LOSSLESS_ROWS: Final = 1_000_000
MAX_STATS_LOSSLESS_RECORDS: Final = 10_000_000
MAX_STATS_LOSSLESS_CELLS: Final = 10_000_000
MAX_STATS_LOSSLESS_JSON_NODES: Final = 2_000_000
MAX_STATS_LOSSLESS_CANONICAL_BYTES: Final = 64 * 1024 * 1024
MAX_STATS_LOSSLESS_TOTAL_CANONICAL_BYTES: Final = 256 * 1024 * 1024
MAX_STATS_LOSSLESS_DEPTH: Final = 64
MAX_STATS_LOSSLESS_INTEGER_ABS: Final = (1 << 63) - 1

StatsLosslessRecordKind = Literal[
    "response",
    "json_node",
    "result_set",
    "missing_expected",
    "raw_headers",
    "raw_rows",
    "header",
    "row",
    "cell",
]
StatsLosslessOwnerKind = Literal["result_occurrence", "response_residual"]
StatsLosslessResultPresence = Literal["present", "present_empty", "missing"]
JsonPresenceKind = Literal["present", "null", "empty_object", "empty_array"]
JsonValueKind = Literal["null", "boolean", "integer", "number", "string", "array", "object"]

_RECORD_KINDS = frozenset(
    {
        "response",
        "json_node",
        "result_set",
        "missing_expected",
        "raw_headers",
        "raw_rows",
        "header",
        "row",
        "cell",
    }
)
_OWNER_KINDS = frozenset({"result_occurrence", "response_residual"})
_RESPONSE_STATES = frozenset(
    {
        "missing_result_envelope",
        "unknown_result_envelope",
        "generic_nested_json",
        "legacy_present_empty",
        "legacy_present_nonempty",
    }
)
_RESULT_PRESENCES = frozenset({"present", "present_empty", "missing"})
_PRESENCE_KINDS = frozenset({"present", "null", "empty_object", "empty_array"})
_VALUE_KINDS = frozenset({"null", "boolean", "integer", "number", "string", "array", "object"})
_PER_RESULT_ANOMALY_CODES = frozenset(
    {
        "additive_header",
        "duplicate_header",
        "heterogeneous_column",
        "non_sequence_row",
        "ragged_row",
        "removed_header",
        "reordered_header",
        "unsupported_header_shape",
        "unsupported_row_container",
    }
)
_GLOBAL_ANOMALY_CODES = frozenset(
    {
        *_PER_RESULT_ANOMALY_CODES,
        "additive_result_set",
        "duplicate_result_set_name",
        "missing_result_set",
        "unknown_dynamic_response",
        "unrepresentable_typed_frame",
    }
)
_CONTAINER_KINDS = frozenset({"array", "boolean", "integer", "null", "number", "object", "string"})
_SHA256_RE = re.compile(r"[0-9a-f]{64}\Z")
_SAFE_ID_RE = re.compile(r"[A-Za-z0-9_][A-Za-z0-9_.:-]{0,511}\Z")
_RESULT_NAME_RE = re.compile(r"[A-Za-z0-9_][A-Za-z0-9_.:-]{0,255}\Z")
_AUTHORIZATION_HEADER_SECRET_RE = re.compile(
    r"authorization\s*:\s*(?:bearer|basic)\s+"
    r"[A-Za-z0-9._~+/=-]{8,}(?![A-Za-z0-9._~+/=-])",
    flags=re.ASCII | re.IGNORECASE,
)
_CAMEL_ACRONYM_BOUNDARY_RE = re.compile(r"([A-Z]+)([A-Z][a-z])", flags=re.ASCII)
_CAMEL_WORD_BOUNDARY_RE = re.compile(r"([a-z0-9])([A-Z])", flags=re.ASCII)
_KEY_SEPARATOR_RE = re.compile(r"[^A-Za-z0-9]+", flags=re.ASCII)
_SENSITIVE_OBJECT_KEY_RE = re.compile(
    r"(?:authorization|proxy_authorization|authentication|cookie|set_cookie|credential|"
    r"secret|token|client_secret|client_key|access_token|refresh_token|id_token|api_key|"
    r"apikey|password|passwd|proxy_url|proxy_host|vpn_server|vpn_ip|vpn_password|"
    r"request_headers|response_headers|runner_path|workspace_path|local_path|file_path|"
    r"github_token|gh_token|pat|private_key|secret_key|personal_access_token|"
    r"ssh_private_key)\Z",
    flags=re.ASCII,
)
_GENERIC_SENSITIVE_KEY_COMPONENTS = frozenset({"auth", "session", "secret", "token"})
_BEARER_SECRET_RE = re.compile(
    r"bearer\s+(?=[A-Za-z0-9._~+/=-]{20,}(?![A-Za-z0-9._~+/=-]))"
    r"(?=[A-Za-z0-9._~+/=-]*[0-9._~+/=-])"
    r"[A-Za-z0-9._~+/=-]{20,}(?![A-Za-z0-9._~+/=-])",
    flags=re.ASCII | re.IGNORECASE,
)
_BASIC_SECRET_RE = re.compile(
    r"basic\s+(?=[A-Za-z0-9+/=]{12,}(?![A-Za-z0-9+/=]))"
    r"(?=[A-Za-z0-9+/=]*[0-9+/=])"
    r"[A-Za-z0-9+/=]{12,}(?![A-Za-z0-9+/=])",
    flags=re.ASCII | re.IGNORECASE,
)
_LOCAL_PATH_VALUE_RE = re.compile(
    r"(?:/Users/[^/\x00\s]+(?=/|\s|\Z)|/home/[^/\x00\s]+(?=/|\s|\Z)|"
    r"/private/var(?![A-Za-z0-9_])|[A-Za-z]:\\Users\\)"
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

STATS_LOSSLESS_SOURCE_COLUMNS: Final = (
    "response_receipt_sha256",
    "provider_authority_sha256",
    "endpoint_contract_sha256",
    "response_mode_authority_sha256",
    "parser_input_sha256",
    "canonical_payload_sha256",
    "parameters_sha256",
    "endpoint_id",
    "endpoint_slug",
    "response_state",
    "legacy_envelope_name",
    "record_kind",
    "result_set_name",
    "result_set_occurrence",
    "provider_index",
    "canonical_index",
    "header_name",
    "header_ordinal",
    "row_ordinal",
    "node_ordinal",
    "parent_node_ordinal",
    "json_path",
    "parent_json_path",
    "depth",
    "object_key",
    "object_key_ordinal",
    "array_ordinal",
    "presence_kind",
    "value_kind",
    "canonical_json",
    "anomaly_codes_json",
)


class StatsLosslessValueAuthorityError(ValueError):
    """One public stats-lossless value row or closed authority is invalid."""


def _fail(message: str) -> Never:
    raise StatsLosslessValueAuthorityError(message)


def _sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _reject_duplicate_keys(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            _fail("stats-lossless canonical JSON contains a duplicate object key")
        result[key] = value
    return result


def _reject_nonfinite_constant(_value: str) -> Never:
    _fail("stats-lossless canonical JSON contains a non-finite number")


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
        _fail("stats-lossless public value contains secret-shaped text")


def _normalized_public_key(value: str) -> str:
    separated = _CAMEL_ACRONYM_BOUNDARY_RE.sub(r"\1_\2", value)
    separated = _CAMEL_WORD_BOUNDARY_RE.sub(r"\1_\2", separated)
    return _KEY_SEPARATOR_RE.sub("_", separated).strip("_").lower()


def _reject_sensitive_public_key(value: str) -> None:
    normalized = _normalized_public_key(value)
    if _SENSITIVE_OBJECT_KEY_RE.fullmatch(normalized) is not None or any(
        component in _GENERIC_SENSITIVE_KEY_COMPONENTS for component in normalized.split("_")
    ):
        _fail("stats-lossless public value contains secret-shaped material")


def _validate_json_graph(value: object, *, maximum_bytes: int) -> None:
    nodes = 0
    estimated_bytes = 0
    stack: list[tuple[object, int]] = [(value, 0)]
    while stack:
        item, depth = stack.pop()
        nodes += 1
        if nodes > MAX_STATS_LOSSLESS_JSON_NODES or depth > MAX_STATS_LOSSLESS_DEPTH:
            _fail("stats-lossless JSON exceeds its node or depth bound")
        if item is None:
            estimated_bytes += 4
            continue
        if type(item) is bool:
            estimated_bytes += 5
            continue
        if type(item) is str:
            text = item
            if len(text) > maximum_bytes:
                _fail("stats-lossless JSON string exceeds its preallocation bound")
            _reject_secret_shaped_public_text(text)
            estimated_bytes += 6 * len(text) + 2
            if estimated_bytes > maximum_bytes:
                _fail("stats-lossless JSON exceeds its preallocation bound")
            continue
        if type(item) is int:
            if abs(cast("int", item)) > MAX_STATS_LOSSLESS_INTEGER_ABS:
                _fail("stats-lossless JSON integer exceeds its exact bound")
            estimated_bytes += 20
            continue
        if type(item) is float:
            number = cast("float", item)
            if not math.isfinite(number) or (number == 0.0 and math.copysign(1.0, number) < 0):
                _fail("stats-lossless JSON number is non-finite or negative zero")
            estimated_bytes += 32
            continue
        if type(item) is list:
            children = cast("list[object]", item)
            if len(children) > MAX_STATS_LOSSLESS_JSON_NODES - nodes - len(stack):
                _fail("stats-lossless JSON exceeds its node bound before traversal")
            estimated_bytes += len(children) + 2
            if estimated_bytes > maximum_bytes:
                _fail("stats-lossless JSON exceeds its preallocation bound")
            stack.extend((child, depth + 1) for child in children)
            continue
        if type(item) is dict:
            mapping = cast("dict[object, object]", item)
            if any(type(key) is not str for key in mapping):
                _fail("stats-lossless JSON object has a non-string exact key")
            if len(mapping) > MAX_STATS_LOSSLESS_JSON_NODES - nodes - len(stack):
                _fail("stats-lossless JSON exceeds its node bound before traversal")
            for key in mapping:
                exact_key = cast("str", key)
                if len(exact_key) > maximum_bytes:
                    _fail("stats-lossless JSON object key exceeds its preallocation bound")
                _reject_sensitive_public_key(exact_key)
                _reject_secret_shaped_public_text(exact_key)
                estimated_bytes += 6 * len(exact_key) + 3
            estimated_bytes += len(mapping) + 2
            if estimated_bytes > maximum_bytes:
                _fail("stats-lossless JSON exceeds its preallocation bound")
            stack.extend((child, depth + 1) for child in mapping.values())
            continue
        _fail("stats-lossless JSON contains a foreign runtime type")
        if estimated_bytes > maximum_bytes:
            _fail("stats-lossless JSON exceeds its preallocation bound")


def canonical_json_bytes(value: object, *, maximum_bytes: int) -> bytes:
    """Encode one exact built-in JSON graph with a hard byte bound."""

    if (
        type(maximum_bytes) is not int
        or maximum_bytes < 1
        or maximum_bytes > MAX_STATS_LOSSLESS_TOTAL_CANONICAL_BYTES
    ):
        _fail("canonical JSON byte bound is invalid")
    _validate_json_graph(value, maximum_bytes=maximum_bytes)
    try:
        encoded = json.dumps(
            value,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
            allow_nan=False,
        ).encode("utf-8", errors="strict")
    except (TypeError, ValueError, UnicodeEncodeError, RecursionError) as exc:
        raise StatsLosslessValueAuthorityError(
            "stats-lossless value is not bounded canonical JSON"
        ) from exc
    if len(encoded) > maximum_bytes:
        _fail("stats-lossless canonical JSON exceeds its exact byte bound")
    return encoded


def _preflight_json_text(raw: bytes) -> None:
    """Bound JSON nesting and structural work before decoder allocation."""

    containers: list[int] = []
    nodes = 1
    in_string = False
    escaped = False
    for byte in raw:
        if in_string:
            if escaped:
                escaped = False
            elif byte == 0x5C:  # backslash
                escaped = True
            elif byte == 0x22:  # quote
                in_string = False
            continue
        if byte == 0x22:
            in_string = True
        elif byte in {0x5B, 0x7B}:  # [ {
            containers.append(byte)
            nodes += 1
            if len(containers) > MAX_STATS_LOSSLESS_DEPTH:
                _fail("stats-lossless canonical JSON exceeds its depth bound")
        elif byte in {0x5D, 0x7D}:  # ] }
            expected = 0x5B if byte == 0x5D else 0x7B
            if not containers or containers.pop() != expected:
                _fail("stats-lossless canonical JSON has malformed lexical structure")
        elif byte == 0x2C:  # comma
            nodes += 1
        if nodes > MAX_STATS_LOSSLESS_JSON_NODES:
            _fail("stats-lossless canonical JSON exceeds its lexical node bound")
    if in_string or escaped or containers:
        _fail("stats-lossless canonical JSON has incomplete lexical structure")


def _bounded_json_integer(token: str) -> int:
    if len(token) > 64:
        _fail("stats-lossless canonical JSON integer token exceeds its bound")
    try:
        value = int(token)
    except ValueError:
        raise StatsLosslessValueAuthorityError(
            "stats-lossless canonical JSON integer token is invalid"
        ) from None
    if abs(value) > MAX_STATS_LOSSLESS_INTEGER_ABS:
        _fail("stats-lossless canonical JSON integer exceeds its exact bound")
    return value


def _bounded_json_float(token: str) -> float:
    if len(token) > 64:
        _fail("stats-lossless canonical JSON number token exceeds its bound")
    try:
        value = float(token)
    except ValueError:
        raise StatsLosslessValueAuthorityError(
            "stats-lossless canonical JSON number token is invalid"
        ) from None
    if not math.isfinite(value) or (value == 0.0 and math.copysign(1.0, value) < 0):
        _fail("stats-lossless canonical JSON number is non-finite or negative zero")
    return value


def _decode_canonical_json(encoded: object, *, nullable: bool = False) -> object:
    if encoded is None and nullable:
        return None
    if type(encoded) is not str or not encoded:
        _fail("stats-lossless canonical JSON must be nonempty exact text")
    text = cast("str", encoded)
    if len(text) > MAX_STATS_LOSSLESS_CANONICAL_BYTES:
        _fail("stats-lossless canonical JSON exceeds its pre-copy character bound")
    try:
        raw = text.encode("utf-8", errors="strict")
    except UnicodeEncodeError as exc:
        raise StatsLosslessValueAuthorityError(
            "stats-lossless canonical JSON is not UTF-8"
        ) from exc
    if len(raw) > MAX_STATS_LOSSLESS_CANONICAL_BYTES:
        _fail("stats-lossless canonical JSON exceeds its exact byte bound")
    _preflight_json_text(raw)
    try:
        value = json.loads(
            raw,
            object_pairs_hook=_reject_duplicate_keys,
            parse_float=_bounded_json_float,
            parse_int=_bounded_json_integer,
            parse_constant=_reject_nonfinite_constant,
        )
    except StatsLosslessValueAuthorityError:
        raise
    except (UnicodeError, ValueError, OverflowError, RecursionError, TypeError):
        raise StatsLosslessValueAuthorityError(
            "stats-lossless canonical JSON cannot be decoded"
        ) from None
    _validate_json_graph(value, maximum_bytes=MAX_STATS_LOSSLESS_CANONICAL_BYTES)
    if canonical_json_bytes(value, maximum_bytes=MAX_STATS_LOSSLESS_CANONICAL_BYTES) != raw:
        _fail("stats-lossless JSON text is not the exact canonical encoding")
    return value


def canonical_sha256(value: object) -> str:
    return _sha256_bytes(
        canonical_json_bytes(value, maximum_bytes=MAX_STATS_LOSSLESS_CANONICAL_BYTES)
    )


def canonical_ordered_root_sha256(
    *,
    kind: str,
    count: int,
    values: Iterable[object],
) -> str:
    """Stream one domain/count-bound ordered root without materializing its items."""

    _exact_text(kind, field_name="ordered root kind", maximum=200)
    _exact_nonnegative(count, field_name="ordered root count", maximum=MAX_STATS_LOSSLESS_RECORDS)
    digest = hashlib.sha256()
    digest.update(b'{"count":')
    digest.update(str(count).encode("ascii"))
    digest.update(b',"items":[')
    seen = 0
    for ordinal, value in enumerate(values):
        if ordinal:
            digest.update(b",")
        digest.update(canonical_json_bytes(value, maximum_bytes=MAX_STATS_LOSSLESS_CANONICAL_BYTES))
        seen += 1
        if seen > count:
            _fail("ordered root contains more items than its declared denominator")
    if seen != count:
        _fail("ordered root count differs from its exact item denominator")
    digest.update(b'],"kind":')
    digest.update(canonical_json_bytes(kind, maximum_bytes=2_048))
    digest.update(b',"schema_version":1}')
    return digest.hexdigest()


def json_value_kind(value: object) -> JsonValueKind:
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
    _fail("stats-lossless value has a foreign JSON type")


def json_presence_kind(value: object) -> JsonPresenceKind:
    if value is None:
        return "null"
    if type(value) is list and not value:
        return "empty_array"
    if type(value) is dict and not value:
        return "empty_object"
    return "present"


def _exact_sha256(value: object, *, field_name: str) -> str:
    if type(value) is not str or _SHA256_RE.fullmatch(value) is None:
        _fail(f"{field_name} must be one exact lowercase SHA-256")
    return value


def _optional_sha256(value: object, *, field_name: str) -> str | None:
    if value is None:
        return None
    return _exact_sha256(value, field_name=field_name)


def _exact_nonnegative(value: object, *, field_name: str, maximum: int) -> int:
    if type(value) is not int or value < 0 or value > maximum:
        _fail(f"{field_name} must be a bounded nonnegative exact integer")
    return value


def _optional_nonnegative(value: object, *, field_name: str, maximum: int) -> int | None:
    if value is None:
        return None
    return _exact_nonnegative(value, field_name=field_name, maximum=maximum)


def _validate_stats_lossless_denominators(
    *,
    provider_result_set_count: object,
    expected_result_set_count: object,
    occurrence_count: object,
    result_count: object,
    record_count: object,
    response_residual_record_count: object,
    label: str,
) -> tuple[int, int, int, int, int, int]:
    """Apply one exact denominator algebra to manifests and final receipts."""

    provider = _exact_nonnegative(
        provider_result_set_count,
        field_name="provider_result_set_count",
        maximum=MAX_STATS_LOSSLESS_RESULTS,
    )
    expected = _exact_nonnegative(
        expected_result_set_count,
        field_name="expected_result_set_count",
        maximum=MAX_STATS_LOSSLESS_RESULTS,
    )
    occurrences = _exact_nonnegative(
        occurrence_count,
        field_name="occurrence_count",
        maximum=MAX_STATS_LOSSLESS_RESULTS,
    )
    results = _exact_nonnegative(
        result_count,
        field_name="result_count",
        maximum=MAX_STATS_LOSSLESS_RESULTS,
    )
    records = _exact_nonnegative(
        record_count,
        field_name="record_count",
        maximum=MAX_STATS_LOSSLESS_RECORDS,
    )
    response_residual_records = _exact_nonnegative(
        response_residual_record_count,
        field_name="response_residual_record_count",
        maximum=MAX_STATS_LOSSLESS_RECORDS,
    )
    if (
        occurrences != results
        or provider > results
        or expected > results
        or records < (3 * results) + response_residual_records
        or response_residual_records > records
        or (expected < 1 and response_residual_records < 1)
        or (results < 1 and response_residual_records < 1)
    ):
        _fail(f"{label} denominators are inconsistent")
    return provider, expected, occurrences, results, records, response_residual_records


def _exact_text(value: object, *, field_name: str, maximum: int = 512) -> str:
    if (
        type(value) is not str
        or not value
        or len(value) > maximum
        or value.strip() != value
        or len(value.encode("utf-8", errors="strict")) > maximum
    ):
        _fail(f"{field_name} must be bounded nonempty exact text")
    return cast("str", value)


def _bounded_public_text(
    value: object,
    *,
    field_name: str,
    maximum: int,
    allow_empty: bool,
) -> str:
    if type(value) is not str:
        _fail(f"{field_name} must be bounded exact public text")
    text = value
    if (not allow_empty and not text) or len(text) > maximum:
        _fail(f"{field_name} must be bounded exact public text")
    _reject_secret_shaped_public_text(text)
    return text


def _exact_public_sequence(
    value: object,
    *,
    field_name: str,
    maximum: int,
) -> list[object] | tuple[object, ...]:
    if type(value) not in {list, tuple}:
        _fail(f"{field_name} must be an exact bounded public sequence")
    sequence = cast("list[object] | tuple[object, ...]", value)
    if len(sequence) > maximum:
        _fail(f"{field_name} exceeds its bound before copying")
    return sequence


def _safe_id(value: object, *, field_name: str) -> str:
    text = _exact_text(value, field_name=field_name)
    if _SAFE_ID_RE.fullmatch(text) is None:
        _fail(f"{field_name} is not a safe public identifier")
    return text


def _result_name(value: object) -> str:
    text = _exact_text(value, field_name="result_set_name", maximum=256)
    if _RESULT_NAME_RE.fullmatch(text) is None:
        _fail("result_set_name is not a safe exact result identity")
    return text


def _optional_result_name(value: object) -> str | None:
    if value is None:
        return None
    return _result_name(value)


def _optional_public_text(
    value: object,
    *,
    field_name: str,
    maximum: int,
    allow_empty: bool = False,
) -> str | None:
    if value is None:
        return None
    return _bounded_public_text(
        value,
        field_name=field_name,
        maximum=maximum,
        allow_empty=allow_empty,
    )


def _canonical_string_list(
    encoded: object,
    digest: object,
    *,
    field_name: str,
    allowed: frozenset[str] | None = None,
    allow_empty: bool = True,
) -> tuple[str, ...]:
    value = _decode_canonical_json(encoded)
    if type(value) is not list or any(type(item) is not str for item in value):
        _fail(f"{field_name} must be an exact canonical string array")
    result = tuple(cast("list[str]", value))
    if (not allow_empty and not result) or result != tuple(sorted(set(result))):
        _fail(f"{field_name} must be sorted, unique, and canonical")
    if any(not item or (allowed is not None and item not in allowed) for item in result):
        _fail(f"{field_name} contains an unsupported value")
    if _exact_sha256(digest, field_name=f"{field_name}_sha256") != _sha256_bytes(
        cast("str", encoded).encode("utf-8")
    ):
        _fail(f"{field_name} digest is invalid")
    return result


def _dataclass_row(value: object, *, cls: type[object], label: str) -> dict[str, object]:
    expected = ("schema_version", *(item.name for item in fields(cls)))
    if type(value) is not dict:
        _fail(f"{label} does not have its exact ordered public columns")
    mapping = cast("dict[object, object]", value)
    if any(type(key) is not str for key in mapping) or tuple(mapping) != expected:
        _fail(f"{label} does not have its exact ordered public columns")
    row = cast("dict[str, object]", value)
    if (
        type(row["schema_version"]) is not int
        or row["schema_version"] != PUBLIC_VALUE_AUTHORITY_SCHEMA_VERSION
    ):
        _fail(f"{label} schema version must be the exact integer 1")
    return row


def _schema_identity(kind: str, columns: Sequence[tuple[str, str, bool]]) -> str:
    return canonical_sha256(
        {
            "kind": kind,
            "schema_version": PUBLIC_VALUE_AUTHORITY_SCHEMA_VERSION,
            "columns": [
                {"name": name, "logical_type": logical_type, "nullable": nullable}
                for name, logical_type, nullable in columns
            ],
        }
    )


_STATS_LOSSLESS_SOURCE_SCHEMA_DESCRIPTOR: Final = tuple(
    (
        name,
        (
            "int64"
            if name.endswith("_ordinal")
            or name
            in {
                "result_set_occurrence",
                "provider_index",
                "canonical_index",
                "depth",
            }
            else "utf8"
        ),
        name
        not in {
            "response_receipt_sha256",
            "provider_authority_sha256",
            "endpoint_contract_sha256",
            "response_mode_authority_sha256",
            "parser_input_sha256",
            "canonical_payload_sha256",
            "parameters_sha256",
            "endpoint_id",
            "endpoint_slug",
            "response_state",
            "record_kind",
            "anomaly_codes_json",
        },
    )
    for name in STATS_LOSSLESS_SOURCE_COLUMNS
)
STATS_LOSSLESS_SOURCE_SCHEMA_SHA256: Final = _schema_identity(
    "stats_lossless_source_row_schema_v1",
    _STATS_LOSSLESS_SOURCE_SCHEMA_DESCRIPTOR,
)


def _source_row_payload_values(record: Mapping[str, object]) -> dict[str, object]:
    row = {column: None for column in STATS_LOSSLESS_SOURCE_COLUMNS}
    row.update(
        {
            "response_receipt_sha256": record["response_receipt_sha256"],
            "provider_authority_sha256": record["provider_authority_sha256"],
            "endpoint_contract_sha256": record["endpoint_contract_sha256"],
            "response_mode_authority_sha256": record["response_mode_authority_sha256"],
            "parser_input_sha256": record["parser_input_sha256"],
            "canonical_payload_sha256": record["canonical_payload_sha256"],
            "parameters_sha256": record["parameters_sha256"],
            "endpoint_id": record["endpoint_id"],
            "endpoint_slug": record["endpoint_slug"],
            "response_state": record["response_state"],
            "legacy_envelope_name": record["legacy_envelope_name"],
            "record_kind": record["record_kind"],
            "result_set_name": record["result_set_name"],
            "result_set_occurrence": record["result_set_occurrence"],
            "provider_index": record["provider_result_ordinal"],
            "canonical_index": record["canonical_result_ordinal"],
            "header_name": record["header_name"],
            "header_ordinal": record["header_ordinal"],
            "row_ordinal": record["row_ordinal"],
            "node_ordinal": record["node_ordinal"],
            "parent_node_ordinal": record["parent_node_ordinal"],
            "json_path": record["json_path"],
            "parent_json_path": record["parent_json_path"],
            "depth": record["depth"],
            "object_key": record["object_key"],
            "object_key_ordinal": record["object_key_ordinal"],
            "array_ordinal": record["array_ordinal"],
            "presence_kind": record["presence_kind"],
            "value_kind": record["value_kind"],
            "canonical_json": record["canonical_json"],
            "anomaly_codes_json": record["global_anomaly_codes_json"],
        }
    )
    return row


def _source_row_payload(record: StatsLosslessRecordV1) -> dict[str, object]:
    return _source_row_payload_values(
        {item.name: getattr(record, item.name) for item in fields(record)}
    )


_RESULT_DECLARATION_COLUMNS: Final = (
    "anomaly_codes",
    "expected_headers",
    "header_record_count",
    "normalized_output_sha256",
    "presence",
    "raw_cell_count",
    "raw_row_occurrence_count",
    "sequence_row_count",
)


def _validated_result_declaration(value: object) -> dict[str, object]:
    if type(value) is not dict:
        _fail("stats-lossless result declaration must be one exact public object")
    raw = cast("dict[object, object]", value)
    if any(type(key) is not str for key in raw) or tuple(raw) != _RESULT_DECLARATION_COLUMNS:
        _fail("stats-lossless result declaration has foreign or unordered fields")
    declaration = cast("dict[str, object]", value)
    presence = _exact_text(declaration["presence"], field_name="result declaration presence")
    if presence not in _RESULT_PRESENCES:
        _fail("stats-lossless result declaration presence is unsupported")
    expected_headers_value = declaration["expected_headers"]
    if expected_headers_value is not None:
        if type(expected_headers_value) is not list:
            _fail("stats-lossless expected headers must be one exact array")
        expected_headers = cast("list[object]", expected_headers_value)
        if len(expected_headers) > MAX_STATS_LOSSLESS_HEADERS:
            _fail("stats-lossless expected headers exceed their bound before copying")
        for header in expected_headers:
            text = _bounded_public_text(
                header,
                field_name="expected header",
                maximum=1_024,
                allow_empty=False,
            )
            _reject_sensitive_public_key(text)
    anomalies_value = declaration["anomaly_codes"]
    if type(anomalies_value) is not list:
        _fail("stats-lossless declaration anomalies must be one exact array")
    anomalies = cast("list[object]", anomalies_value)
    if len(anomalies) > len(_PER_RESULT_ANOMALY_CODES) or any(
        type(item) is not str or item not in _PER_RESULT_ANOMALY_CODES for item in anomalies
    ):
        _fail("stats-lossless declaration contains an unsupported anomaly")
    if tuple(cast("list[str]", anomalies)) != tuple(sorted(set(cast("list[str]", anomalies)))):
        _fail("stats-lossless declaration anomalies are not canonical")
    for field_name, maximum in (
        ("header_record_count", MAX_STATS_LOSSLESS_HEADERS),
        ("raw_row_occurrence_count", MAX_STATS_LOSSLESS_ROWS),
        ("sequence_row_count", MAX_STATS_LOSSLESS_ROWS),
        ("raw_cell_count", MAX_STATS_LOSSLESS_CELLS),
    ):
        _exact_nonnegative(declaration[field_name], field_name=field_name, maximum=maximum)
    _exact_sha256(declaration["normalized_output_sha256"], field_name="normalized_output_sha256")
    if presence == "missing" and (
        expected_headers_value is None
        or anomalies
        or any(
            cast("int", declaration[name]) != 0
            for name in (
                "header_record_count",
                "raw_row_occurrence_count",
                "sequence_row_count",
                "raw_cell_count",
            )
        )
    ):
        _fail("stats-lossless missing-result declaration is inconsistent")
    return declaration


def stats_lossless_result_declaration_value(
    *,
    presence: StatsLosslessResultPresence,
    expected_headers: Sequence[str] | None,
    anomaly_codes: Sequence[str],
    normalized_output_sha256: str,
    header_record_count: int,
    raw_row_occurrence_count: int,
    sequence_row_count: int,
    raw_cell_count: int,
) -> dict[str, object]:
    """Build the exact value-bearing declaration stored in the record relation."""

    expected_values: list[object] | None = None
    if expected_headers is not None:
        expected_values = list(
            _exact_public_sequence(
                expected_headers,
                field_name="expected headers",
                maximum=MAX_STATS_LOSSLESS_HEADERS,
            )
        )
    anomaly_values = list(
        _exact_public_sequence(
            anomaly_codes,
            field_name="per-result anomaly codes",
            maximum=len(_PER_RESULT_ANOMALY_CODES),
        )
    )
    value: dict[str, object] = {
        "anomaly_codes": anomaly_values,
        "expected_headers": expected_values,
        "header_record_count": header_record_count,
        "normalized_output_sha256": normalized_output_sha256,
        "presence": presence,
        "raw_cell_count": raw_cell_count,
        "raw_row_occurrence_count": raw_row_occurrence_count,
        "sequence_row_count": sequence_row_count,
    }
    _validated_result_declaration(value)
    return value


@dataclass(frozen=True, slots=True)
class StatsLosslessRecordV1:
    """One ordered occurrence-owned or response-residual public record."""

    record_sha256: str
    source_row_sha256: str
    representation_kind: str
    owner_kind: StatsLosslessOwnerKind
    raw_authority_bundle_sha256: str
    observation_record_sha256: str
    observation_sha256: str
    occurrence_sha256: str | None
    route_id: str
    route_authority_sha256: str
    committed_receipt_sha256: str
    response_receipt_sha256: str
    provider_authority_sha256: str
    endpoint_contract_sha256: str
    response_mode_authority_sha256: str
    parser_input_sha256: str
    canonical_payload_sha256: str
    parameters_sha256: str
    endpoint_id: str
    endpoint_slug: str
    response_state: str
    legacy_envelope_name: str | None
    global_record_ordinal: int
    occurrence_record_ordinal: int | None
    response_record_ordinal: int | None
    record_kind: StatsLosslessRecordKind
    result_set_name: str | None
    result_set_occurrence: int | None
    provider_result_ordinal: int | None
    expected_result_ordinal: int | None
    canonical_result_ordinal: int | None
    header_name: str | None
    header_ordinal: int | None
    row_ordinal: int | None
    node_ordinal: int | None
    parent_node_ordinal: int | None
    json_path: str | None
    parent_json_path: str | None
    depth: int | None
    object_key: str | None
    object_key_ordinal: int | None
    array_ordinal: int | None
    presence_kind: JsonPresenceKind | None
    value_kind: JsonValueKind | None
    canonical_json: str | None
    canonical_json_sha256: str | None
    global_anomaly_codes_json: str
    global_anomaly_codes_sha256: str

    schema_version: ClassVar[int] = PUBLIC_VALUE_AUTHORITY_SCHEMA_VERSION
    kind: ClassVar[str] = "raw_nba_api_stats_lossless_record_v1"

    def __post_init__(self) -> None:
        for name in (
            "record_sha256",
            "source_row_sha256",
            "raw_authority_bundle_sha256",
            "observation_record_sha256",
            "observation_sha256",
            "route_authority_sha256",
            "committed_receipt_sha256",
            "response_receipt_sha256",
            "provider_authority_sha256",
            "endpoint_contract_sha256",
            "response_mode_authority_sha256",
            "parser_input_sha256",
            "canonical_payload_sha256",
            "parameters_sha256",
        ):
            _exact_sha256(getattr(self, name), field_name=name)
        _optional_sha256(self.occurrence_sha256, field_name="occurrence_sha256")
        if type(self.owner_kind) is not str or self.owner_kind not in _OWNER_KINDS:
            _fail("stats-lossless record owner kind is unsupported")
        representation_kind = _exact_text(
            self.representation_kind,
            field_name="representation_kind",
            maximum=128,
        )
        expected_representation = (
            STATS_LOSSLESS_REPRESENTATION_KIND
            if self.owner_kind == "result_occurrence"
            else RESPONSE_LOSSLESS_REPRESENTATION_KIND
        )
        if representation_kind != expected_representation:
            _fail("stats-lossless record representation differs from its exact owner")
        _safe_id(self.route_id, field_name="route_id")
        for name in ("endpoint_id", "endpoint_slug"):
            _safe_id(getattr(self, name), field_name=name)
        response_state = _safe_id(self.response_state, field_name="response_state")
        if response_state not in _RESPONSE_STATES:
            _fail("stats-lossless response state is unsupported")
        _optional_result_name(self.legacy_envelope_name)
        _exact_nonnegative(
            self.global_record_ordinal,
            field_name="global_record_ordinal",
            maximum=MAX_STATS_LOSSLESS_RECORDS - 1,
        )
        if type(self.record_kind) is not str or self.record_kind not in _RECORD_KINDS:
            _fail("stats-lossless record kind is unsupported")
        _optional_result_name(self.result_set_name)
        _optional_nonnegative(
            self.result_set_occurrence,
            field_name="result_set_occurrence",
            maximum=MAX_STATS_LOSSLESS_RESULTS - 1,
        )
        for name, maximum in (
            ("occurrence_record_ordinal", MAX_STATS_LOSSLESS_RECORDS - 1),
            ("response_record_ordinal", MAX_STATS_LOSSLESS_RECORDS - 1),
            ("provider_result_ordinal", MAX_STATS_LOSSLESS_RESULTS - 1),
            ("expected_result_ordinal", MAX_STATS_LOSSLESS_RESULTS - 1),
            ("canonical_result_ordinal", MAX_STATS_LOSSLESS_RESULTS - 1),
            ("header_ordinal", MAX_STATS_LOSSLESS_HEADERS - 1),
            ("row_ordinal", MAX_STATS_LOSSLESS_ROWS - 1),
            ("node_ordinal", MAX_STATS_LOSSLESS_JSON_NODES - 1),
            ("parent_node_ordinal", MAX_STATS_LOSSLESS_JSON_NODES - 1),
            ("depth", MAX_STATS_LOSSLESS_DEPTH),
            ("object_key_ordinal", MAX_STATS_LOSSLESS_JSON_NODES - 1),
            ("array_ordinal", MAX_STATS_LOSSLESS_JSON_NODES - 1),
        ):
            _optional_nonnegative(getattr(self, name), field_name=name, maximum=maximum)
        if self.header_name is not None:
            header_name = _bounded_public_text(
                self.header_name,
                field_name="header_name",
                maximum=1_024,
                allow_empty=True,
            )
            _reject_sensitive_public_key(header_name)
        for name in ("json_path", "parent_json_path"):
            _optional_public_text(
                getattr(self, name),
                field_name=name,
                maximum=4_096,
            )
        if self.object_key is not None:
            object_key = _bounded_public_text(
                self.object_key,
                field_name="object_key",
                maximum=1_024,
                allow_empty=True,
            )
            _reject_sensitive_public_key(object_key)

        has_value = self.canonical_json is not None
        if has_value != (self.canonical_json_sha256 is not None):
            _fail("stats-lossless record canonical value digest is incomplete")
        if has_value:
            if self.value_kind is None or self.presence_kind is None:
                _fail("stats-lossless record canonical value tags are incomplete")
            value = _decode_canonical_json(self.canonical_json)
            if (
                self.canonical_json_sha256 != _sha256_bytes(self.canonical_json.encode("utf-8"))
                or self.value_kind != json_value_kind(value)
                or self.presence_kind != json_presence_kind(value)
            ):
                _fail("stats-lossless record canonical value tags or digest are invalid")
        else:
            value = None
            nonmaterialized_container = (
                self.owner_kind == "response_residual"
                and self.record_kind == "json_node"
                and self.value_kind in {"array", "object"}
                and self.presence_kind == "present"
            )
            if not nonmaterialized_container and (
                self.value_kind is not None or self.presence_kind is not None
            ):
                _fail("stats-lossless non-value record contains value tags")

        occurrence_node_values = (
            self.node_ordinal,
            self.parent_node_ordinal,
            self.json_path,
            self.parent_json_path,
            self.depth,
            self.object_key,
            self.object_key_ordinal,
            self.array_ordinal,
        )
        result_identity_values = (
            self.result_set_name,
            self.result_set_occurrence,
            self.provider_result_ordinal,
            self.expected_result_ordinal,
            self.canonical_result_ordinal,
            self.header_name,
            self.header_ordinal,
            self.row_ordinal,
        )
        if self.owner_kind == "result_occurrence":
            if (
                self.occurrence_sha256 is None
                or self.occurrence_record_ordinal is None
                or self.response_record_ordinal is not None
                or self.record_kind in {"response", "json_node"}
                or self.result_set_name is None
                or self.result_set_occurrence is None
                or any(item is not None for item in occurrence_node_values)
            ):
                _fail("stats-lossless occurrence-owned record shape is invalid")
        elif (
            self.occurrence_sha256 is not None
            or self.occurrence_record_ordinal is not None
            or self.response_record_ordinal is None
            or self.record_kind not in {"response", "json_node"}
            or any(item is not None for item in result_identity_values)
        ):
            _fail("stats-lossless response-residual record shape is invalid")

        if self.record_kind == "response":
            if any(item is not None for item in occurrence_node_values) or has_value:
                _fail("stats-lossless response marker contains node or value material")
        elif self.record_kind == "json_node":
            if (
                self.node_ordinal is None
                or self.json_path is None
                or self.depth is None
                or self.value_kind is None
                or self.presence_kind is None
            ):
                _fail("stats-lossless residual JSON node omits its exact identity")
            if self.parent_node_ordinal is None:
                if (
                    self.node_ordinal != 0
                    or self.json_path != "$"
                    or self.parent_json_path is not None
                    or self.depth != 0
                    or self.object_key is not None
                    or self.object_key_ordinal is not None
                    or self.array_ordinal is not None
                ):
                    _fail("stats-lossless residual JSON root is invalid")
            elif (
                self.parent_node_ordinal >= self.node_ordinal
                or self.parent_json_path is None
                or self.depth < 1
                or (
                    self.object_key is not None
                    and (self.object_key_ordinal is None or self.array_ordinal is not None)
                )
                or (
                    self.object_key is None
                    and (self.object_key_ordinal is not None or self.array_ordinal is None)
                )
            ):
                _fail("stats-lossless residual JSON child identity is invalid")
        elif self.record_kind in {"result_set", "missing_expected"}:
            if (
                any(
                    value is not None
                    for value in (
                        self.header_name,
                        self.header_ordinal,
                        self.row_ordinal,
                    )
                )
                or self.canonical_json is None
            ):
                _fail("stats-lossless result declaration contains child/value selectors")
            declaration = _validated_result_declaration(value)
            expected_presence = (
                "missing"
                if self.record_kind == "missing_expected"
                else ("present" if declaration["presence"] == "present" else "present_empty")
            )
            if declaration["presence"] != expected_presence:
                _fail("stats-lossless result declaration kind differs from its presence")
        elif self.record_kind in {"raw_headers", "raw_rows"}:
            if (
                self.header_name is not None
                or self.header_ordinal is not None
                or self.row_ordinal is not None
                or self.canonical_json is None
            ):
                _fail("stats-lossless raw-container record shape is invalid")
        elif self.record_kind == "header":
            if (
                self.provider_result_ordinal is None
                or self.header_ordinal is None
                or self.row_ordinal is not None
                or self.canonical_json is None
            ):
                _fail("stats-lossless header record shape is invalid")
        elif self.record_kind == "row":
            if (
                self.provider_result_ordinal is None
                or self.header_name is not None
                or self.header_ordinal is not None
                or self.row_ordinal is None
                or self.canonical_json is None
            ):
                _fail("stats-lossless row record shape is invalid")
        elif self.record_kind == "cell" and (
            self.provider_result_ordinal is None
            or self.header_ordinal is None
            or self.row_ordinal is None
            or self.canonical_json is None
        ):
            _fail("stats-lossless cell record shape is invalid")
        if self.owner_kind == "result_occurrence" and self.record_kind == "missing_expected":
            if self.provider_result_ordinal is not None or self.canonical_result_ordinal is None:
                _fail("stats-lossless missing-result record identity is invalid")
        elif self.owner_kind == "result_occurrence" and self.record_kind in {
            "raw_headers",
            "raw_rows",
        }:
            if self.provider_result_ordinal is None and self.canonical_result_ordinal is None:
                _fail("stats-lossless missing raw-container record omits canonical identity")
        elif self.owner_kind == "result_occurrence" and self.provider_result_ordinal is None:
            _fail("stats-lossless present record omits its provider result ordinal")

        _canonical_string_list(
            self.global_anomaly_codes_json,
            self.global_anomaly_codes_sha256,
            field_name="global_anomaly_codes",
            allowed=_GLOBAL_ANOMALY_CODES,
            allow_empty=False,
        )
        if self.source_row_sha256 != canonical_sha256(_source_row_payload(self)):
            _fail("stats-lossless source-row digest differs from its exact fixed-schema row")
        if self.record_sha256 != canonical_sha256(self.identity_payload()):
            _fail("stats-lossless record digest differs from its exact identity")

    @classmethod
    def build(
        cls,
        *,
        raw_authority_bundle_sha256: str,
        observation_record_sha256: str,
        observation_sha256: str,
        owner_kind: StatsLosslessOwnerKind,
        occurrence_sha256: str | None,
        route_id: str,
        route_authority_sha256: str,
        committed_receipt_sha256: str,
        response_receipt_sha256: str,
        provider_authority_sha256: str,
        endpoint_contract_sha256: str,
        response_mode_authority_sha256: str,
        parser_input_sha256: str,
        canonical_payload_sha256: str,
        parameters_sha256: str,
        endpoint_id: str,
        endpoint_slug: str,
        response_state: str,
        legacy_envelope_name: str | None,
        global_record_ordinal: int,
        occurrence_record_ordinal: int | None,
        response_record_ordinal: int | None,
        record_kind: StatsLosslessRecordKind,
        result_set_name: str | None,
        result_set_occurrence: int | None,
        provider_result_ordinal: int | None,
        expected_result_ordinal: int | None,
        canonical_result_ordinal: int | None,
        header_name: str | None = None,
        header_ordinal: int | None = None,
        row_ordinal: int | None = None,
        node_ordinal: int | None = None,
        parent_node_ordinal: int | None = None,
        json_path: str | None = None,
        parent_json_path: str | None = None,
        depth: int | None = None,
        object_key: str | None = None,
        object_key_ordinal: int | None = None,
        array_ordinal: int | None = None,
        value_present: bool = False,
        value: object = None,
        explicit_presence_kind: JsonPresenceKind | None = None,
        explicit_value_kind: JsonValueKind | None = None,
        global_anomaly_codes: Sequence[str],
    ) -> Self:
        if type(value_present) is not bool:
            _fail("stats-lossless value-present marker must be an exact boolean")
        anomaly_sequence = _exact_public_sequence(
            global_anomaly_codes,
            field_name="global_anomaly_codes",
            maximum=len(_GLOBAL_ANOMALY_CODES),
        )
        canonical_json = (
            canonical_json_bytes(
                value,
                maximum_bytes=MAX_STATS_LOSSLESS_CANONICAL_BYTES,
            ).decode("utf-8")
            if value_present
            else None
        )
        value_kind = json_value_kind(value) if value_present else explicit_value_kind
        presence_kind = json_presence_kind(value) if value_present else explicit_presence_kind
        if value_present and (
            explicit_value_kind is not None or explicit_presence_kind is not None
        ):
            _fail("stats-lossless canonical value cannot override its derived tags")
        anomaly_json = canonical_json_bytes(
            list(anomaly_sequence),
            maximum_bytes=MAX_STATS_LOSSLESS_CANONICAL_BYTES,
        ).decode("utf-8")
        values: dict[str, object] = {
            "source_row_sha256": "0" * 64,
            "representation_kind": (
                STATS_LOSSLESS_REPRESENTATION_KIND
                if owner_kind == "result_occurrence"
                else RESPONSE_LOSSLESS_REPRESENTATION_KIND
            ),
            "owner_kind": owner_kind,
            "raw_authority_bundle_sha256": raw_authority_bundle_sha256,
            "observation_record_sha256": observation_record_sha256,
            "observation_sha256": observation_sha256,
            "occurrence_sha256": occurrence_sha256,
            "route_id": route_id,
            "route_authority_sha256": route_authority_sha256,
            "committed_receipt_sha256": committed_receipt_sha256,
            "response_receipt_sha256": response_receipt_sha256,
            "provider_authority_sha256": provider_authority_sha256,
            "endpoint_contract_sha256": endpoint_contract_sha256,
            "response_mode_authority_sha256": response_mode_authority_sha256,
            "parser_input_sha256": parser_input_sha256,
            "canonical_payload_sha256": canonical_payload_sha256,
            "parameters_sha256": parameters_sha256,
            "endpoint_id": endpoint_id,
            "endpoint_slug": endpoint_slug,
            "response_state": response_state,
            "legacy_envelope_name": legacy_envelope_name,
            "global_record_ordinal": global_record_ordinal,
            "occurrence_record_ordinal": occurrence_record_ordinal,
            "response_record_ordinal": response_record_ordinal,
            "record_kind": record_kind,
            "result_set_name": result_set_name,
            "result_set_occurrence": result_set_occurrence,
            "provider_result_ordinal": provider_result_ordinal,
            "expected_result_ordinal": expected_result_ordinal,
            "canonical_result_ordinal": canonical_result_ordinal,
            "header_name": header_name,
            "header_ordinal": header_ordinal,
            "row_ordinal": row_ordinal,
            "node_ordinal": node_ordinal,
            "parent_node_ordinal": parent_node_ordinal,
            "json_path": json_path,
            "parent_json_path": parent_json_path,
            "depth": depth,
            "object_key": object_key,
            "object_key_ordinal": object_key_ordinal,
            "array_ordinal": array_ordinal,
            "presence_kind": presence_kind,
            "value_kind": value_kind,
            "canonical_json": canonical_json,
            "canonical_json_sha256": (
                None if canonical_json is None else _sha256_bytes(canonical_json.encode("utf-8"))
            ),
            "global_anomaly_codes_json": anomaly_json,
            "global_anomaly_codes_sha256": _sha256_bytes(anomaly_json.encode("utf-8")),
        }
        source_row_sha256 = canonical_sha256(_source_row_payload_values(values))
        values["source_row_sha256"] = source_row_sha256
        payload = {"schema_version": 1, "kind": cls.kind, **values}
        return cls(record_sha256=canonical_sha256(payload), **values)  # type: ignore[arg-type]

    def identity_payload(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "kind": self.kind,
            **{
                item.name: getattr(self, item.name)
                for item in fields(self)
                if item.name != "record_sha256"
            },
        }

    def source_row(self) -> dict[str, object]:
        """Return the exact declared fallback row committed by ``source_row_sha256``."""

        return _source_row_payload(self)

    def value(self) -> object:
        if self.canonical_json is None:
            _fail("stats-lossless declaration record has no canonical value")
        return _decode_canonical_json(self.canonical_json)

    def to_row(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            **{item.name: getattr(self, item.name) for item in fields(self)},
        }

    @classmethod
    def from_row(cls, value: object) -> Self:
        row = _dataclass_row(value, cls=cls, label="stats-lossless record row")
        try:
            return cast("Any", cls)(**{item.name: row[item.name] for item in fields(cls)})
        except (TypeError, ValueError, RecursionError):
            raise StatsLosslessValueAuthorityError(
                "stats-lossless record row failed semantic reconstruction"
            ) from None


@dataclass(frozen=True, slots=True)
class StatsLosslessResultV1:
    """One complete raw header/row container and its public record partition."""

    result_sha256: str
    representation_kind: str
    raw_authority_bundle_sha256: str
    observation_record_sha256: str
    observation_sha256: str
    occurrence_sha256: str
    route_id: str
    route_authority_sha256: str
    committed_receipt_sha256: str
    response_receipt_sha256: str
    result_ordinal: int
    result_set_name: str
    result_set_occurrence: int
    provider_result_ordinal: int | None
    expected_result_ordinal: int | None
    canonical_result_ordinal: int | None
    occurrence_canonical_result_ordinal: int | None
    presence: StatsLosslessResultPresence
    expected_headers_sha256: str | None
    raw_headers_sha256: str
    raw_rows_sha256: str
    raw_header_container_kind: str
    raw_row_container_kind: str
    header_record_count: int
    raw_row_occurrence_count: int
    sequence_row_count: int
    raw_cell_count: int
    anomaly_codes_sha256: str
    normalized_output_sha256: str
    first_global_record_ordinal: int
    record_count: int
    record_inventory_sha256: str
    source_rows_sha256: str

    schema_version: ClassVar[int] = PUBLIC_VALUE_AUTHORITY_SCHEMA_VERSION
    kind: ClassVar[str] = "raw_nba_api_stats_lossless_result_v1"

    def __post_init__(self) -> None:
        for name in (
            "result_sha256",
            "raw_authority_bundle_sha256",
            "observation_record_sha256",
            "observation_sha256",
            "occurrence_sha256",
            "route_authority_sha256",
            "committed_receipt_sha256",
            "response_receipt_sha256",
            "raw_headers_sha256",
            "raw_rows_sha256",
            "normalized_output_sha256",
            "record_inventory_sha256",
            "source_rows_sha256",
        ):
            _exact_sha256(getattr(self, name), field_name=name)
        representation_kind = _exact_text(
            self.representation_kind,
            field_name="representation_kind",
            maximum=128,
        )
        if representation_kind != STATS_LOSSLESS_REPRESENTATION_KIND:
            _fail("stats-lossless result has a foreign representation kind")
        _safe_id(self.route_id, field_name="route_id")
        _result_name(self.result_set_name)
        for name, maximum in (
            ("result_ordinal", MAX_STATS_LOSSLESS_RESULTS - 1),
            ("result_set_occurrence", MAX_STATS_LOSSLESS_RESULTS - 1),
            ("provider_result_ordinal", MAX_STATS_LOSSLESS_RESULTS - 1),
            ("expected_result_ordinal", MAX_STATS_LOSSLESS_RESULTS - 1),
            ("canonical_result_ordinal", MAX_STATS_LOSSLESS_RESULTS - 1),
            ("occurrence_canonical_result_ordinal", MAX_STATS_LOSSLESS_RESULTS - 1),
            ("header_record_count", MAX_STATS_LOSSLESS_HEADERS),
            ("raw_row_occurrence_count", MAX_STATS_LOSSLESS_ROWS),
            ("sequence_row_count", MAX_STATS_LOSSLESS_ROWS),
            ("raw_cell_count", MAX_STATS_LOSSLESS_CELLS),
            ("first_global_record_ordinal", MAX_STATS_LOSSLESS_RECORDS - 1),
            ("record_count", MAX_STATS_LOSSLESS_RECORDS),
        ):
            if name in {
                "provider_result_ordinal",
                "expected_result_ordinal",
                "canonical_result_ordinal",
                "occurrence_canonical_result_ordinal",
            }:
                _optional_nonnegative(getattr(self, name), field_name=name, maximum=maximum)
            else:
                _exact_nonnegative(getattr(self, name), field_name=name, maximum=maximum)
        if type(self.presence) is not str or self.presence not in _RESULT_PRESENCES:
            _fail("stats-lossless result presence is unsupported")
        _optional_sha256(self.expected_headers_sha256, field_name="expected_headers_sha256")
        _exact_sha256(self.anomaly_codes_sha256, field_name="anomaly_codes_sha256")
        for field_name in ("raw_header_container_kind", "raw_row_container_kind"):
            container_kind = _exact_text(
                getattr(self, field_name),
                field_name=field_name,
                maximum=32,
            )
            if container_kind not in _CONTAINER_KINDS:
                _fail("stats-lossless result has an unsupported raw container kind")
        if self.presence == "missing":
            if (
                self.provider_result_ordinal is not None
                or self.canonical_result_ordinal is None
                or self.expected_headers_sha256 is None
                or any(
                    value > 0
                    for value in (
                        self.header_record_count,
                        self.raw_row_occurrence_count,
                        self.sequence_row_count,
                        self.raw_cell_count,
                    )
                )
                or self.record_count < 3
            ):
                _fail("stats-lossless missing-result authority is invalid")
        elif self.provider_result_ordinal is None:
            _fail("stats-lossless present result omits its provider ordinal")
        if self.result_sha256 != canonical_sha256(self.identity_payload()):
            _fail("stats-lossless result digest differs from its exact identity")

    @classmethod
    def build(
        cls,
        *,
        raw_authority_bundle_sha256: str,
        observation_record_sha256: str,
        observation_sha256: str,
        occurrence_sha256: str,
        route_id: str,
        route_authority_sha256: str,
        committed_receipt_sha256: str,
        response_receipt_sha256: str,
        result_ordinal: int,
        result_set_name: str,
        result_set_occurrence: int,
        provider_result_ordinal: int | None,
        expected_result_ordinal: int | None,
        canonical_result_ordinal: int | None,
        occurrence_canonical_result_ordinal: int | None,
        presence: StatsLosslessResultPresence,
        expected_headers: Sequence[str] | None,
        raw_headers: object,
        raw_rows: object,
        header_record_count: int,
        raw_row_occurrence_count: int,
        sequence_row_count: int,
        raw_cell_count: int,
        anomaly_codes: Sequence[str],
        normalized_output_sha256: str,
        first_global_record_ordinal: int,
        records: Sequence[StatsLosslessRecordV1],
    ) -> Self:
        record_sequence = _exact_public_sequence(
            records,
            field_name="result records",
            maximum=MAX_STATS_LOSSLESS_RECORDS,
        )
        if not record_sequence or any(
            type(item) is not StatsLosslessRecordV1 for item in record_sequence
        ):
            _fail("stats-lossless result records are absent or have a foreign type")
        exact_records = tuple(
            StatsLosslessRecordV1.from_row(item.to_row())
            for item in cast(
                "list[StatsLosslessRecordV1] | tuple[StatsLosslessRecordV1, ...]",
                record_sequence,
            )
        )
        expected_sequence: list[object] | tuple[object, ...] | None = None
        if expected_headers is not None:
            expected_sequence = _exact_public_sequence(
                expected_headers,
                field_name="expected headers",
                maximum=MAX_STATS_LOSSLESS_HEADERS,
            )
        anomaly_sequence = _exact_public_sequence(
            anomaly_codes,
            field_name="per-result anomaly codes",
            maximum=len(_PER_RESULT_ANOMALY_CODES),
        )
        expected_values = None if expected_sequence is None else list(expected_sequence)
        expected_json = (
            None
            if expected_values is None
            else canonical_json_bytes(
                expected_values,
                maximum_bytes=MAX_STATS_LOSSLESS_CANONICAL_BYTES,
            )
        )
        raw_headers_json = canonical_json_bytes(
            raw_headers, maximum_bytes=MAX_STATS_LOSSLESS_CANONICAL_BYTES
        )
        raw_rows_json = canonical_json_bytes(
            raw_rows, maximum_bytes=MAX_STATS_LOSSLESS_CANONICAL_BYTES
        )
        anomaly_json = canonical_json_bytes(
            list(anomaly_sequence), maximum_bytes=MAX_STATS_LOSSLESS_CANONICAL_BYTES
        )
        declaration = stats_lossless_result_declaration_value(
            presence=presence,
            expected_headers=(
                None if expected_values is None else cast("list[str]", expected_values)
            ),
            anomaly_codes=cast("Sequence[str]", anomaly_sequence),
            normalized_output_sha256=normalized_output_sha256,
            header_record_count=header_record_count,
            raw_row_occurrence_count=raw_row_occurrence_count,
            sequence_row_count=sequence_row_count,
            raw_cell_count=raw_cell_count,
        )
        declaration_kind = "missing_expected" if presence == "missing" else "result_set"
        if len(exact_records) < 3 or (
            exact_records[0].record_kind != declaration_kind
            or exact_records[0].value() != declaration
            or exact_records[1].record_kind != "raw_headers"
            or exact_records[1].value() != raw_headers
            or exact_records[2].record_kind != "raw_rows"
            or exact_records[2].value() != raw_rows
        ):
            _fail("stats-lossless result omits its declaration or raw-container records")
        if any(
            record.owner_kind != "result_occurrence"
            or record.representation_kind != STATS_LOSSLESS_REPRESENTATION_KIND
            or record.raw_authority_bundle_sha256 != raw_authority_bundle_sha256
            or record.observation_record_sha256 != observation_record_sha256
            or record.observation_sha256 != observation_sha256
            or record.occurrence_sha256 != occurrence_sha256
            or record.route_id != route_id
            or record.route_authority_sha256 != route_authority_sha256
            or record.committed_receipt_sha256 != committed_receipt_sha256
            or record.response_receipt_sha256 != response_receipt_sha256
            or record.result_set_name != result_set_name
            or record.result_set_occurrence != result_set_occurrence
            or record.provider_result_ordinal != provider_result_ordinal
            or record.expected_result_ordinal != expected_result_ordinal
            or record.canonical_result_ordinal != canonical_result_ordinal
            or record.occurrence_record_ordinal != ordinal
            or record.response_record_ordinal is not None
            or record.global_record_ordinal != first_global_record_ordinal + ordinal
            for ordinal, record in enumerate(exact_records)
        ):
            _fail("stats-lossless result record partition was rebound or reordered")
        total_canonical_bytes = sum(
            0 if record.canonical_json is None else len(record.canonical_json.encode("utf-8"))
            for record in exact_records
        )
        if total_canonical_bytes > MAX_STATS_LOSSLESS_TOTAL_CANONICAL_BYTES:
            _fail("stats-lossless result exceeds its aggregate canonical byte bound")
        values: dict[str, object] = {
            "representation_kind": STATS_LOSSLESS_REPRESENTATION_KIND,
            "raw_authority_bundle_sha256": raw_authority_bundle_sha256,
            "observation_record_sha256": observation_record_sha256,
            "observation_sha256": observation_sha256,
            "occurrence_sha256": occurrence_sha256,
            "route_id": route_id,
            "route_authority_sha256": route_authority_sha256,
            "committed_receipt_sha256": committed_receipt_sha256,
            "response_receipt_sha256": response_receipt_sha256,
            "result_ordinal": result_ordinal,
            "result_set_name": result_set_name,
            "result_set_occurrence": result_set_occurrence,
            "provider_result_ordinal": provider_result_ordinal,
            "expected_result_ordinal": expected_result_ordinal,
            "canonical_result_ordinal": canonical_result_ordinal,
            "occurrence_canonical_result_ordinal": occurrence_canonical_result_ordinal,
            "presence": presence,
            "expected_headers_sha256": (
                None if expected_json is None else _sha256_bytes(expected_json)
            ),
            "raw_headers_sha256": _sha256_bytes(raw_headers_json),
            "raw_rows_sha256": _sha256_bytes(raw_rows_json),
            "raw_header_container_kind": json_value_kind(raw_headers),
            "raw_row_container_kind": json_value_kind(raw_rows),
            "header_record_count": header_record_count,
            "raw_row_occurrence_count": raw_row_occurrence_count,
            "sequence_row_count": sequence_row_count,
            "raw_cell_count": raw_cell_count,
            "anomaly_codes_sha256": _sha256_bytes(anomaly_json),
            "normalized_output_sha256": normalized_output_sha256,
            "first_global_record_ordinal": first_global_record_ordinal,
            "record_count": len(exact_records),
            "record_inventory_sha256": canonical_ordered_root_sha256(
                kind="stats_lossless_result_record_inventory_v1",
                count=len(exact_records),
                values=(item.record_sha256 for item in exact_records),
            ),
            "source_rows_sha256": canonical_ordered_root_sha256(
                kind="stats_lossless_result_source_rows_v1",
                count=len(exact_records),
                values=(item.source_row_sha256 for item in exact_records),
            ),
        }
        payload = {"schema_version": 1, "kind": cls.kind, **values}
        return cls(result_sha256=canonical_sha256(payload), **values)  # type: ignore[arg-type]

    def identity_payload(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "kind": self.kind,
            **{
                item.name: getattr(self, item.name)
                for item in fields(self)
                if item.name != "result_sha256"
            },
        }

    def to_row(self) -> dict[str, object]:
        """Return the value-free non-relational result receipt DTO."""
        return {
            "schema_version": self.schema_version,
            **{item.name: getattr(self, item.name) for item in fields(self)},
        }

    @classmethod
    def from_row(cls, value: object) -> Self:
        row = _dataclass_row(value, cls=cls, label="stats-lossless result row")
        try:
            return cast("Any", cls)(**{item.name: row[item.name] for item in fields(cls)})
        except (TypeError, ValueError, RecursionError):
            raise StatsLosslessValueAuthorityError(
                "stats-lossless result row failed semantic reconstruction"
            ) from None


def _same_canonical_value(left: object, right: object) -> bool:
    return canonical_json_bytes(
        left,
        maximum_bytes=MAX_STATS_LOSSLESS_CANONICAL_BYTES,
    ) == canonical_json_bytes(
        right,
        maximum_bytes=MAX_STATS_LOSSLESS_CANONICAL_BYTES,
    )


def _json_path_for_tokens(tokens: Sequence[str | int]) -> str:
    path = "$"
    for token in tokens:
        if type(token) is int:
            path += f"[{token}]"
        else:
            encoded = canonical_json_bytes(token, maximum_bytes=4_096).decode("utf-8")
            path += f"[{encoded}]"
    return path


def _rederive_response_residual_partition(
    records: tuple[StatsLosslessRecordV1, ...],
) -> object | None:
    """Reconstruct the exact response-wide JSON tree from residual records."""

    if not records:
        return None
    if len(records) < 2 or records[0].record_kind != "response":
        _fail("stats-lossless response residual omits its response marker or JSON root")
    if tuple(item.response_record_ordinal for item in records) != tuple(range(len(records))):
        _fail("stats-lossless response-residual ordinals are not contiguous")
    if any(item.owner_kind != "response_residual" for item in records):
        _fail("stats-lossless response residual contains an occurrence-owned record")
    node_records = records[1:]
    if any(item.record_kind != "json_node" for item in node_records) or tuple(
        item.node_ordinal for item in node_records
    ) != tuple(range(len(node_records))):
        _fail("stats-lossless response residual JSON-node inventory is noncanonical")

    values: list[object] = []
    tokens_by_ordinal: list[tuple[str | int, ...]] = []
    object_child_ordinals: dict[int, int] = {}
    array_child_ordinals: dict[int, int] = {}
    for ordinal, record in enumerate(node_records):
        if record.canonical_json is None:
            value: object = {} if record.value_kind == "object" else []
        else:
            value = record.value()
        if ordinal == 0:
            tokens: tuple[str | int, ...] = ()
        else:
            parent_ordinal = record.parent_node_ordinal
            if parent_ordinal is None or parent_ordinal >= ordinal:
                _fail("stats-lossless response residual JSON parent is invalid")
            parent = values[parent_ordinal]
            parent_tokens = tokens_by_ordinal[parent_ordinal]
            if type(parent) is dict:
                key = record.object_key
                expected_child_ordinal = object_child_ordinals.get(parent_ordinal, 0)
                if (
                    key is None
                    or record.object_key_ordinal != expected_child_ordinal
                    or record.array_ordinal is not None
                    or key in cast("dict[str, object]", parent)
                ):
                    _fail("stats-lossless response residual object child is noncanonical")
                object_child_ordinals[parent_ordinal] = expected_child_ordinal + 1
                cast("dict[str, object]", parent)[key] = value
                tokens = (*parent_tokens, key)
            elif type(parent) is list:
                expected_child_ordinal = array_child_ordinals.get(parent_ordinal, 0)
                if (
                    record.object_key is not None
                    or record.object_key_ordinal is not None
                    or record.array_ordinal != expected_child_ordinal
                ):
                    _fail("stats-lossless response residual array child is noncanonical")
                array_child_ordinals[parent_ordinal] = expected_child_ordinal + 1
                cast("list[object]", parent).append(value)
                tokens = (*parent_tokens, expected_child_ordinal)
            else:
                _fail("stats-lossless response residual scalar cannot own a child")
            if record.parent_json_path != _json_path_for_tokens(
                parent_tokens
            ) or record.depth != len(tokens):
                _fail("stats-lossless response residual parent path or depth drifted")
        if record.json_path != _json_path_for_tokens(tokens):
            _fail("stats-lossless response residual JSON path drifted")
        values.append(value)
        tokens_by_ordinal.append(tokens)

    for record, value in zip(node_records, values, strict=True):
        if record.value_kind != json_value_kind(
            value
        ) or record.presence_kind != json_presence_kind(value):
            _fail("stats-lossless response residual node tags differ from its subtree")
        if record.canonical_json is None:
            if type(value) not in {dict, list} or not cast(
                "dict[object, object] | list[object]", value
            ):
                _fail("stats-lossless response residual omitted an empty container value")
        elif not _same_canonical_value(record.value(), value):
            _fail("stats-lossless response residual canonical node value drifted")
    root = values[0]
    if canonical_sha256(root) != records[0].canonical_payload_sha256:
        _fail("stats-lossless response residual differs from its canonical payload")
    return root


def _derived_partition_anomalies(
    *,
    expected_headers: tuple[str, ...] | None,
    raw_headers: object,
    observed_header_names: tuple[str | None, ...],
    raw_rows: object,
) -> tuple[str, ...]:
    reasons: set[str] = set()
    if type(raw_headers) is not list or any(name is None for name in observed_header_names):
        reasons.add("unsupported_header_shape")
    observed_headers = tuple(name for name in observed_header_names if name is not None)
    if len(set(observed_headers)) != len(observed_headers):
        reasons.add("duplicate_header")
    if expected_headers is not None:
        expected_counter = Counter(expected_headers)
        observed_counter = Counter(observed_headers)
        if observed_counter - expected_counter:
            reasons.add("additive_header")
        if expected_counter - observed_counter:
            reasons.add("removed_header")
        if expected_counter == observed_counter and expected_headers != observed_headers:
            reasons.add("reordered_header")
    if type(raw_rows) is not list:
        reasons.add("unsupported_row_container")
        return tuple(sorted(reasons))

    widths: set[int] = set()
    kinds_by_ordinal: dict[int, set[str]] = {}
    for raw_row in cast("list[object]", raw_rows):
        if type(raw_row) is not list:
            reasons.add("non_sequence_row")
            continue
        row = cast("list[object]", raw_row)
        if len(row) > MAX_STATS_LOSSLESS_CELLS:
            _fail("stats-lossless raw row exceeds its exact cell bound")
        widths.add(len(row))
        if len(row) != len(observed_header_names):
            reasons.add("ragged_row")
        for ordinal, value in enumerate(row):
            kind = json_value_kind(value)
            if kind != "null":
                kinds_by_ordinal.setdefault(ordinal, set()).add(kind)
    if len(widths) > 1:
        reasons.add("ragged_row")
    if any(len(kinds) > 1 for kinds in kinds_by_ordinal.values()):
        reasons.add("heterogeneous_column")
    return tuple(sorted(reasons))


def _rederive_result_from_record_partition(
    *,
    result: StatsLosslessResultV1,
    result_ordinal: int,
    records: tuple[StatsLosslessRecordV1, ...],
) -> StatsLosslessResultV1:
    """Rebuild every result commitment from its exact value-bearing records."""

    if len(records) < 3:
        _fail("stats-lossless manifest result partition is incomplete")
    if result.occurrence_canonical_result_ordinal is not None:
        _fail(
            "stats-lossless result receipt differs from its exact record partition "
            "occurrence identity"
        )
    declaration_record, raw_headers_record, raw_rows_record = records[:3]
    if (
        declaration_record.record_kind not in {"result_set", "missing_expected"}
        or raw_headers_record.record_kind != "raw_headers"
        or raw_rows_record.record_kind != "raw_rows"
    ):
        _fail("stats-lossless manifest result partition omits its exact leading records")
    declaration = _validated_result_declaration(declaration_record.value())
    presence = cast("StatsLosslessResultPresence", declaration["presence"])
    expected_value = declaration["expected_headers"]
    expected_headers = None if expected_value is None else tuple(cast("list[str]", expected_value))
    raw_headers = raw_headers_record.value()
    raw_rows = raw_rows_record.value()
    cursor = 3
    observed_header_names: list[str | None] = []

    if presence == "missing":
        if (
            declaration_record.record_kind != "missing_expected"
            or expected_headers is None
            or not _same_canonical_value(raw_headers, list(expected_headers))
            or not _same_canonical_value(raw_rows, [])
        ):
            _fail("stats-lossless missing result differs from its exact record partition")
        anomalies: tuple[str, ...] = ()
        header_record_count = 0
        raw_row_occurrence_count = 0
        sequence_row_count = 0
        raw_cell_count = 0
        normalized_output_sha256 = canonical_sha256({"headers": list(expected_headers), "rows": []})
    else:
        if declaration_record.record_kind != "result_set":
            _fail("stats-lossless present result has a missing declaration record")
        header_values = cast("list[object]", raw_headers) if type(raw_headers) is list else []
        for header_ordinal, header_value in enumerate(header_values):
            if cursor >= len(records):
                _fail("stats-lossless manifest header partition ended early")
            record = records[cursor]
            expected_header_name = header_value if type(header_value) is str else None
            if (
                record.record_kind != "header"
                or record.header_name != expected_header_name
                or record.header_ordinal != header_ordinal
                or record.row_ordinal is not None
                or not _same_canonical_value(record.value(), header_value)
            ):
                _fail("stats-lossless manifest header record differs from its raw container")
            observed_header_names.append(record.header_name)
            cursor += 1

        row_values = cast("list[object]", raw_rows) if type(raw_rows) is list else []
        sequence_rows = 0
        raw_cell_count = 0
        for row_ordinal, raw_row in enumerate(row_values):
            if cursor >= len(records):
                _fail("stats-lossless manifest row partition ended early")
            row_record = records[cursor]
            if (
                row_record.record_kind != "row"
                or row_record.header_name is not None
                or row_record.header_ordinal is not None
                or row_record.row_ordinal != row_ordinal
                or not _same_canonical_value(row_record.value(), raw_row)
            ):
                _fail("stats-lossless manifest row record differs from its raw container")
            cursor += 1
            if type(raw_row) is not list:
                continue
            sequence_rows += 1
            row = cast("list[object]", raw_row)
            raw_cell_count += len(row)
            if raw_cell_count > MAX_STATS_LOSSLESS_CELLS:
                _fail("stats-lossless manifest result exceeds its exact cell bound")
            for header_ordinal, cell in enumerate(row):
                if cursor >= len(records):
                    _fail("stats-lossless manifest cell partition ended early")
                cell_record = records[cursor]
                expected_header_name = (
                    observed_header_names[header_ordinal]
                    if header_ordinal < len(observed_header_names)
                    else None
                )
                if (
                    cell_record.record_kind != "cell"
                    or cell_record.header_name != expected_header_name
                    or cell_record.header_ordinal != header_ordinal
                    or cell_record.row_ordinal != row_ordinal
                    or not _same_canonical_value(cell_record.value(), cell)
                ):
                    _fail("stats-lossless manifest cell record differs from its raw row")
                cursor += 1
        header_record_count = len(header_values)
        raw_row_occurrence_count = len(row_values)
        sequence_row_count = sequence_rows
        anomalies = _derived_partition_anomalies(
            expected_headers=expected_headers,
            raw_headers=raw_headers,
            observed_header_names=tuple(observed_header_names),
            raw_rows=raw_rows,
        )
        expected_presence: StatsLosslessResultPresence = (
            "present" if raw_row_occurrence_count else "present_empty"
        )
        if presence != expected_presence:
            _fail("stats-lossless result presence differs from its exact raw rows")
        normalized_output_sha256 = canonical_sha256(
            {"headers": raw_headers, "rows": raw_rows, "anomalies": list(anomalies)}
        )
    if cursor != len(records):
        _fail("stats-lossless manifest result partition contains extra records")

    declared_anomalies = tuple(cast("list[str]", declaration["anomaly_codes"]))
    if (
        declared_anomalies != anomalies
        or declaration["normalized_output_sha256"] != normalized_output_sha256
        or declaration["header_record_count"] != header_record_count
        or declaration["raw_row_occurrence_count"] != raw_row_occurrence_count
        or declaration["sequence_row_count"] != sequence_row_count
        or declaration["raw_cell_count"] != raw_cell_count
    ):
        _fail("stats-lossless result declaration differs from its exact raw containers")

    occurrence_sha256 = declaration_record.occurrence_sha256
    result_set_name = declaration_record.result_set_name
    result_set_occurrence = declaration_record.result_set_occurrence
    if occurrence_sha256 is None or result_set_name is None or result_set_occurrence is None:
        _fail("stats-lossless result partition has no exact occurrence identity")

    rebuilt = StatsLosslessResultV1.build(
        raw_authority_bundle_sha256=declaration_record.raw_authority_bundle_sha256,
        observation_record_sha256=declaration_record.observation_record_sha256,
        observation_sha256=declaration_record.observation_sha256,
        occurrence_sha256=occurrence_sha256,
        route_id=declaration_record.route_id,
        route_authority_sha256=declaration_record.route_authority_sha256,
        committed_receipt_sha256=declaration_record.committed_receipt_sha256,
        response_receipt_sha256=declaration_record.response_receipt_sha256,
        result_ordinal=result_ordinal,
        result_set_name=result_set_name,
        result_set_occurrence=result_set_occurrence,
        provider_result_ordinal=declaration_record.provider_result_ordinal,
        expected_result_ordinal=declaration_record.expected_result_ordinal,
        canonical_result_ordinal=declaration_record.canonical_result_ordinal,
        occurrence_canonical_result_ordinal=None,
        presence=presence,
        expected_headers=expected_headers,
        raw_headers=raw_headers,
        raw_rows=raw_rows,
        header_record_count=header_record_count,
        raw_row_occurrence_count=raw_row_occurrence_count,
        sequence_row_count=sequence_row_count,
        raw_cell_count=raw_cell_count,
        anomaly_codes=anomalies,
        normalized_output_sha256=normalized_output_sha256,
        first_global_record_ordinal=records[0].global_record_ordinal,
        records=records,
    )
    if rebuilt != result:
        _fail("stats-lossless result receipt differs from its exact record partition")
    return rebuilt


def _derive_stats_lossless_result_denominators(
    results: tuple[StatsLosslessResultV1, ...],
    *,
    allow_empty_expected: bool,
) -> tuple[int, int]:
    provider_results = tuple(
        result for result in results if result.provider_result_ordinal is not None
    )
    missing_results = tuple(result for result in results if result.provider_result_ordinal is None)
    if results != provider_results + missing_results or tuple(
        result.provider_result_ordinal for result in provider_results
    ) != tuple(range(len(provider_results))):
        _fail("stats-lossless results are not in provider-then-missing canonical order")

    expected_by_ordinal: dict[int, tuple[str, str]] = {}
    for result in results:
        expected_ordinal = result.expected_result_ordinal
        if expected_ordinal is None:
            if (
                result.expected_headers_sha256 is not None
                or result.canonical_result_ordinal is not None
            ):
                _fail("stats-lossless additive result has a pinned expected identity")
            continue
        if result.expected_headers_sha256 is None:
            _fail("stats-lossless pinned result omits its expected-header commitment")
        candidate = (result.result_set_name, result.expected_headers_sha256)
        previous = expected_by_ordinal.setdefault(expected_ordinal, candidate)
        if previous != candidate:
            _fail("stats-lossless expected result ordinal was rebound")
    if not expected_by_ordinal and not allow_empty_expected:
        _fail("stats-lossless expected-result denominator is empty or noncontiguous")
    if tuple(sorted(expected_by_ordinal)) != tuple(range(len(expected_by_ordinal))):
        _fail("stats-lossless expected-result denominator is empty or noncontiguous")
    expected_names = tuple(
        expected_by_ordinal[ordinal][0] for ordinal in range(len(expected_by_ordinal))
    )
    if len(set(expected_names)) != len(expected_names):
        _fail("stats-lossless expected result names are duplicated")

    provider_name_counts = Counter(result.result_set_name for result in provider_results)
    duplicate_ordinals: Counter[str] = Counter()
    represented_expected: set[int] = set()
    for result in provider_results:
        expected_occurrence = duplicate_ordinals[result.result_set_name]
        duplicate_ordinals[result.result_set_name] += 1
        expected_ordinal = result.expected_result_ordinal
        expected_canonical = (
            expected_ordinal
            if expected_ordinal is not None and provider_name_counts[result.result_set_name] == 1
            else None
        )
        if (
            result.presence == "missing"
            or result.result_set_occurrence != expected_occurrence
            or result.canonical_result_ordinal != expected_canonical
        ):
            _fail("stats-lossless provider result identity is noncanonical")
        if expected_ordinal is not None:
            represented_expected.add(expected_ordinal)

    missing_ordinals = tuple(
        ordinal
        for ordinal in range(len(expected_by_ordinal))
        if ordinal not in represented_expected
    )
    if len(missing_results) != len(missing_ordinals):
        _fail("stats-lossless missing-result denominator is incomplete")
    for result, expected_ordinal in zip(missing_results, missing_ordinals, strict=True):
        expected_name, _expected_headers_sha256 = expected_by_ordinal[expected_ordinal]
        if (
            result.presence != "missing"
            or result.result_set_name != expected_name
            or result.result_set_occurrence != 0
            or result.expected_result_ordinal != expected_ordinal
            or result.canonical_result_ordinal != expected_ordinal
        ):
            _fail("stats-lossless missing result identity is noncanonical")
    return len(provider_results), len(expected_by_ordinal)


@dataclass(frozen=True, slots=True)
class StatsLosslessManifestV1:
    """Value-free response receipt derived from the single public record relation."""

    manifest_sha256: str
    representation_kind: str
    record_schema_sha256: str
    source_schema_sha256: str
    raw_authority_bundle_sha256: str
    observation_record_sha256: str
    observation_sha256: str
    route_id: str
    route_authority_sha256: str
    committed_receipt_sha256: str
    response_receipt_sha256: str
    endpoint_id: str
    endpoint_slug: str
    provider_authority_sha256: str
    endpoint_contract_sha256: str
    parameters_sha256: str
    global_anomaly_codes_sha256: str
    provider_result_set_count: int
    expected_result_set_count: int
    occurrence_count: int
    occurrence_inventory_sha256: str
    result_count: int
    result_inventory_sha256: str
    response_residual_record_count: int
    response_residual_records_sha256: str
    record_count: int
    record_inventory_sha256: str
    source_rows_sha256: str

    schema_version: ClassVar[int] = PUBLIC_VALUE_AUTHORITY_SCHEMA_VERSION
    kind: ClassVar[str] = "raw_nba_api_stats_lossless_manifest_v1"

    def __post_init__(self) -> None:
        for name in (
            "manifest_sha256",
            "record_schema_sha256",
            "source_schema_sha256",
            "raw_authority_bundle_sha256",
            "observation_record_sha256",
            "observation_sha256",
            "route_authority_sha256",
            "committed_receipt_sha256",
            "response_receipt_sha256",
            "provider_authority_sha256",
            "endpoint_contract_sha256",
            "parameters_sha256",
            "occurrence_inventory_sha256",
            "result_inventory_sha256",
            "response_residual_records_sha256",
            "record_inventory_sha256",
            "source_rows_sha256",
        ):
            _exact_sha256(getattr(self, name), field_name=name)
        representation_kind = _exact_text(
            self.representation_kind,
            field_name="representation_kind",
            maximum=128,
        )
        if representation_kind != STATS_LOSSLESS_REPRESENTATION_KIND:
            _fail("stats-lossless manifest has a foreign representation kind")
        if (
            self.record_schema_sha256 != STATS_LOSSLESS_RECORD_SCHEMA_SHA256
            or self.source_schema_sha256 != STATS_LOSSLESS_SOURCE_SCHEMA_SHA256
        ):
            _fail("stats-lossless manifest names a foreign frozen schema")
        for name in ("route_id", "endpoint_id", "endpoint_slug"):
            _safe_id(getattr(self, name), field_name=name)
        _exact_sha256(
            self.global_anomaly_codes_sha256,
            field_name="global_anomaly_codes_sha256",
        )
        _validate_stats_lossless_denominators(
            provider_result_set_count=self.provider_result_set_count,
            expected_result_set_count=self.expected_result_set_count,
            occurrence_count=self.occurrence_count,
            result_count=self.result_count,
            record_count=self.record_count,
            response_residual_record_count=self.response_residual_record_count,
            label="stats-lossless manifest",
        )
        if self.manifest_sha256 != canonical_sha256(self.identity_payload()):
            _fail("stats-lossless manifest digest differs from its exact identity")

    @classmethod
    def build(
        cls,
        *,
        raw_authority_bundle_sha256: str,
        observation_record_sha256: str,
        observation_sha256: str,
        route_id: str,
        route_authority_sha256: str,
        committed_receipt_sha256: str,
        response_receipt_sha256: str,
        endpoint_id: str,
        endpoint_slug: str,
        provider_authority_sha256: str,
        endpoint_contract_sha256: str,
        parameters_sha256: str,
        global_anomaly_codes: Sequence[str],
        provider_result_set_count: int,
        expected_result_set_count: int,
        results: Sequence[StatsLosslessResultV1],
        records: Sequence[StatsLosslessRecordV1],
    ) -> Self:
        result_sequence = _exact_public_sequence(
            results,
            field_name="manifest results",
            maximum=MAX_STATS_LOSSLESS_RESULTS,
        )
        record_sequence = _exact_public_sequence(
            records,
            field_name="manifest records",
            maximum=MAX_STATS_LOSSLESS_RECORDS,
        )
        anomaly_sequence = _exact_public_sequence(
            global_anomaly_codes,
            field_name="global anomaly codes",
            maximum=len(_GLOBAL_ANOMALY_CODES),
        )
        if any(type(item) is not StatsLosslessResultV1 for item in result_sequence):
            _fail("stats-lossless manifest results have a foreign type")
        if any(type(item) is not StatsLosslessRecordV1 for item in record_sequence):
            _fail("stats-lossless manifest records have a foreign type")
        total_canonical_bytes = 0
        for item in cast(
            "list[StatsLosslessRecordV1] | tuple[StatsLosslessRecordV1, ...]",
            record_sequence,
        ):
            encoded = item.canonical_json
            if encoded is None:
                continue
            if type(encoded) is not str:
                _fail("stats-lossless manifest record value has a foreign exact type")
            if len(encoded) > MAX_STATS_LOSSLESS_CANONICAL_BYTES:
                _fail("stats-lossless manifest record value exceeds its pre-copy bound")
            total_canonical_bytes += len(encoded.encode("utf-8", errors="strict"))
            if total_canonical_bytes > MAX_STATS_LOSSLESS_TOTAL_CANONICAL_BYTES:
                _fail("stats-lossless manifest exceeds its aggregate canonical byte bound")
        exact_results = tuple(
            StatsLosslessResultV1.from_row(item.to_row())
            for item in cast(
                "list[StatsLosslessResultV1] | tuple[StatsLosslessResultV1, ...]",
                result_sequence,
            )
        )
        exact_records = tuple(
            StatsLosslessRecordV1.from_row(item.to_row())
            for item in cast(
                "list[StatsLosslessRecordV1] | tuple[StatsLosslessRecordV1, ...]",
                record_sequence,
            )
        )
        if any(
            type(item) is not str or item not in _GLOBAL_ANOMALY_CODES for item in anomaly_sequence
        ) or tuple(cast("Sequence[str]", anomaly_sequence)) != tuple(
            sorted(set(cast("Sequence[str]", anomaly_sequence)))
        ):
            _fail("stats-lossless global anomalies are unsupported or noncanonical")
        global_json = canonical_json_bytes(
            list(anomaly_sequence), maximum_bytes=MAX_STATS_LOSSLESS_CANONICAL_BYTES
        )
        if any(
            result.result_ordinal != ordinal
            or result.raw_authority_bundle_sha256 != raw_authority_bundle_sha256
            or result.observation_record_sha256 != observation_record_sha256
            or result.observation_sha256 != observation_sha256
            or result.route_id != route_id
            or result.route_authority_sha256 != route_authority_sha256
            or result.committed_receipt_sha256 != committed_receipt_sha256
            or result.response_receipt_sha256 != response_receipt_sha256
            for ordinal, result in enumerate(exact_results)
        ):
            _fail("stats-lossless manifest result inventory was rebound or reordered")
        if not exact_records:
            _fail("stats-lossless manifest cannot infer an empty public relation")
        response_metadata = (
            exact_records[0].response_mode_authority_sha256,
            exact_records[0].parser_input_sha256,
            exact_records[0].canonical_payload_sha256,
            exact_records[0].response_state,
            exact_records[0].legacy_envelope_name,
        )
        if any(
            record.global_record_ordinal != ordinal
            or record.raw_authority_bundle_sha256 != raw_authority_bundle_sha256
            or record.observation_record_sha256 != observation_record_sha256
            or record.observation_sha256 != observation_sha256
            or record.route_id != route_id
            or record.route_authority_sha256 != route_authority_sha256
            or record.committed_receipt_sha256 != committed_receipt_sha256
            or record.response_receipt_sha256 != response_receipt_sha256
            or record.provider_authority_sha256 != provider_authority_sha256
            or record.endpoint_contract_sha256 != endpoint_contract_sha256
            or record.parameters_sha256 != parameters_sha256
            or record.endpoint_id != endpoint_id
            or record.endpoint_slug != endpoint_slug
            or (
                record.response_mode_authority_sha256,
                record.parser_input_sha256,
                record.canonical_payload_sha256,
                record.response_state,
                record.legacy_envelope_name,
            )
            != response_metadata
            or record.global_anomaly_codes_json != global_json.decode("utf-8")
            for ordinal, record in enumerate(exact_records)
        ):
            _fail("stats-lossless manifest record inventory was rebound or reordered")
        record_offset = 0
        rebuilt_results: list[StatsLosslessResultV1] = []
        for result_ordinal, result in enumerate(exact_results):
            if (
                result.first_global_record_ordinal != record_offset
                or result.record_count > len(exact_records) - record_offset
            ):
                _fail("stats-lossless manifest result partition is out of bounds")
            partition = exact_records[record_offset : record_offset + result.record_count]
            if len(partition) != result.record_count or any(
                record.owner_kind != "result_occurrence"
                or record.occurrence_sha256 != result.occurrence_sha256
                for record in partition
            ):
                _fail("stats-lossless manifest result partition differs from its records")
            rebuilt_results.append(
                _rederive_result_from_record_partition(
                    result=result,
                    result_ordinal=result_ordinal,
                    records=partition,
                )
            )
            record_offset += result.record_count
        response_residual_records = exact_records[record_offset:]
        _rederive_response_residual_partition(response_residual_records)
        exact_results = tuple(rebuilt_results)
        derived_provider_count, derived_expected_count = _derive_stats_lossless_result_denominators(
            exact_results,
            allow_empty_expected=bool(response_residual_records),
        )
        _validate_stats_lossless_denominators(
            provider_result_set_count=provider_result_set_count,
            expected_result_set_count=expected_result_set_count,
            occurrence_count=len(exact_results),
            result_count=len(exact_results),
            record_count=len(exact_records),
            response_residual_record_count=len(response_residual_records),
            label="stats-lossless manifest input",
        )
        if (
            type(provider_result_set_count) is not int
            or provider_result_set_count != derived_provider_count
            or type(expected_result_set_count) is not int
            or expected_result_set_count != derived_expected_count
        ):
            _fail("stats-lossless manifest denominators differ from reconstructed results")
        values: dict[str, object] = {
            "representation_kind": STATS_LOSSLESS_REPRESENTATION_KIND,
            "record_schema_sha256": STATS_LOSSLESS_RECORD_SCHEMA_SHA256,
            "source_schema_sha256": STATS_LOSSLESS_SOURCE_SCHEMA_SHA256,
            "raw_authority_bundle_sha256": raw_authority_bundle_sha256,
            "observation_record_sha256": observation_record_sha256,
            "observation_sha256": observation_sha256,
            "route_id": route_id,
            "route_authority_sha256": route_authority_sha256,
            "committed_receipt_sha256": committed_receipt_sha256,
            "response_receipt_sha256": response_receipt_sha256,
            "endpoint_id": endpoint_id,
            "endpoint_slug": endpoint_slug,
            "provider_authority_sha256": provider_authority_sha256,
            "endpoint_contract_sha256": endpoint_contract_sha256,
            "parameters_sha256": parameters_sha256,
            "global_anomaly_codes_sha256": _sha256_bytes(global_json),
            "provider_result_set_count": derived_provider_count,
            "expected_result_set_count": derived_expected_count,
            "occurrence_count": len(exact_results),
            "occurrence_inventory_sha256": canonical_ordered_root_sha256(
                kind="stats_lossless_occurrence_inventory_v1",
                count=len(exact_results),
                values=(item.occurrence_sha256 for item in exact_results),
            ),
            "result_count": len(exact_results),
            "result_inventory_sha256": canonical_ordered_root_sha256(
                kind="stats_lossless_result_inventory_v1",
                count=len(exact_results),
                values=(item.result_sha256 for item in exact_results),
            ),
            "response_residual_record_count": len(response_residual_records),
            "response_residual_records_sha256": canonical_ordered_root_sha256(
                kind="stats_lossless_response_residual_records_v1",
                count=len(response_residual_records),
                values=(item.record_sha256 for item in response_residual_records),
            ),
            "record_count": len(exact_records),
            "record_inventory_sha256": canonical_ordered_root_sha256(
                kind="stats_lossless_record_inventory_v1",
                count=len(exact_records),
                values=(item.record_sha256 for item in exact_records),
            ),
            "source_rows_sha256": canonical_ordered_root_sha256(
                kind="stats_lossless_source_rows_v1",
                count=len(exact_records),
                values=(item.source_row_sha256 for item in exact_records),
            ),
        }
        payload = {"schema_version": 1, "kind": cls.kind, **values}
        return cls(manifest_sha256=canonical_sha256(payload), **values)  # type: ignore[arg-type]

    def identity_payload(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "kind": self.kind,
            **{
                item.name: getattr(self, item.name)
                for item in fields(self)
                if item.name != "manifest_sha256"
            },
        }

    def to_row(self) -> dict[str, object]:
        """Return the value-free non-relational manifest receipt DTO."""
        return {
            "schema_version": self.schema_version,
            **{item.name: getattr(self, item.name) for item in fields(self)},
        }

    @classmethod
    def from_row(cls, value: object) -> Self:
        row = _dataclass_row(value, cls=cls, label="stats-lossless manifest row")
        try:
            return cast("Any", cls)(**{item.name: row[item.name] for item in fields(cls)})
        except (TypeError, ValueError, RecursionError):
            raise StatsLosslessValueAuthorityError(
                "stats-lossless manifest row failed semantic reconstruction"
            ) from None


# The only physical public relation is the exact ordered record row.
STATS_LOSSLESS_RECORD_COLUMNS: Final = (
    "schema_version",
    *(item.name for item in fields(StatsLosslessRecordV1)),
)


def _row_descriptor(cls: type[object]) -> tuple[tuple[str, str, bool], ...]:
    nullable_names = {
        "occurrence_sha256",
        "occurrence_record_ordinal",
        "response_record_ordinal",
        "legacy_envelope_name",
        "result_set_name",
        "result_set_occurrence",
        "provider_result_ordinal",
        "expected_result_ordinal",
        "canonical_result_ordinal",
        "occurrence_canonical_result_ordinal",
        "header_name",
        "header_ordinal",
        "row_ordinal",
        "node_ordinal",
        "parent_node_ordinal",
        "json_path",
        "parent_json_path",
        "depth",
        "object_key",
        "object_key_ordinal",
        "array_ordinal",
        "presence_kind",
        "value_kind",
        "canonical_json",
        "canonical_json_sha256",
        "expected_headers_sha256",
    }
    integer_names = {
        "global_record_ordinal",
        "occurrence_record_ordinal",
        "response_record_ordinal",
        "result_set_occurrence",
        "provider_result_ordinal",
        "expected_result_ordinal",
        "canonical_result_ordinal",
        "occurrence_canonical_result_ordinal",
        "header_ordinal",
        "row_ordinal",
        "node_ordinal",
        "parent_node_ordinal",
        "depth",
        "object_key_ordinal",
        "array_ordinal",
        "result_ordinal",
        "header_record_count",
        "raw_row_occurrence_count",
        "sequence_row_count",
        "raw_cell_count",
        "first_global_record_ordinal",
        "record_count",
        "provider_result_set_count",
        "expected_result_set_count",
        "occurrence_count",
        "result_count",
        "response_residual_record_count",
    }
    return (
        ("schema_version", "int64", False),
        *(
            (
                item.name,
                "int64" if item.name in integer_names else "utf8",
                item.name in nullable_names,
            )
            for item in fields(cls)
        ),
    )


STATS_LOSSLESS_RECORD_SCHEMA_SHA256: Final = _schema_identity(
    "raw_nba_api_stats_lossless_record_schema_v1",
    _row_descriptor(StatsLosslessRecordV1),
)


@dataclass(frozen=True, slots=True)
class StatsLosslessValueAuthorityReceiptV1:
    """Value-free receipt emitted only after exact public-table reconstruction."""

    authority_sha256: str
    manifest_sha256: str
    record_schema_sha256: str
    source_schema_sha256: str
    raw_authority_bundle_sha256: str
    observation_record_sha256: str
    observation_sha256: str
    route_id: str
    route_authority_sha256: str
    committed_receipt_sha256: str
    response_receipt_sha256: str
    endpoint_id: str
    endpoint_slug: str
    provider_authority_sha256: str
    endpoint_contract_sha256: str
    parameters_sha256: str
    global_anomaly_codes_sha256: str
    provider_result_set_count: int
    expected_result_set_count: int
    occurrence_count: int
    occurrence_inventory_sha256: str
    result_count: int
    result_inventory_sha256: str
    response_residual_record_count: int
    response_residual_records_sha256: str
    record_count: int
    record_inventory_sha256: str
    source_rows_sha256: str

    schema_version: ClassVar[int] = PUBLIC_VALUE_AUTHORITY_SCHEMA_VERSION
    kind: ClassVar[str] = "stats_lossless_value_authority_receipt_v1"

    def __post_init__(self) -> None:
        for name in (
            "authority_sha256",
            "manifest_sha256",
            "record_schema_sha256",
            "source_schema_sha256",
            "raw_authority_bundle_sha256",
            "observation_record_sha256",
            "observation_sha256",
            "route_authority_sha256",
            "committed_receipt_sha256",
            "response_receipt_sha256",
            "provider_authority_sha256",
            "endpoint_contract_sha256",
            "parameters_sha256",
            "global_anomaly_codes_sha256",
            "occurrence_inventory_sha256",
            "result_inventory_sha256",
            "response_residual_records_sha256",
            "record_inventory_sha256",
            "source_rows_sha256",
        ):
            _exact_sha256(getattr(self, name), field_name=name)
        for name in ("route_id", "endpoint_id", "endpoint_slug"):
            _safe_id(getattr(self, name), field_name=name)
        _validate_stats_lossless_denominators(
            provider_result_set_count=self.provider_result_set_count,
            expected_result_set_count=self.expected_result_set_count,
            occurrence_count=self.occurrence_count,
            result_count=self.result_count,
            record_count=self.record_count,
            response_residual_record_count=self.response_residual_record_count,
            label="stats-lossless authority receipt",
        )
        if self.authority_sha256 != canonical_sha256(self.identity_payload()):
            _fail("stats-lossless authority receipt digest is invalid")

    @classmethod
    def from_verified_manifest(cls, manifest: StatsLosslessManifestV1) -> Self:
        if type(manifest) is not StatsLosslessManifestV1:
            _fail("stats-lossless authority requires an exact verified manifest")
        try:
            verified = StatsLosslessManifestV1.from_row(manifest.to_row())
        except (TypeError, ValueError, RecursionError):
            raise StatsLosslessValueAuthorityError(
                "stats-lossless authority manifest failed canonical reconstruction"
            ) from None
        values = {
            "manifest_sha256": verified.manifest_sha256,
            "record_schema_sha256": verified.record_schema_sha256,
            "source_schema_sha256": verified.source_schema_sha256,
            "raw_authority_bundle_sha256": verified.raw_authority_bundle_sha256,
            "observation_record_sha256": verified.observation_record_sha256,
            "observation_sha256": verified.observation_sha256,
            "route_id": verified.route_id,
            "route_authority_sha256": verified.route_authority_sha256,
            "committed_receipt_sha256": verified.committed_receipt_sha256,
            "response_receipt_sha256": verified.response_receipt_sha256,
            "endpoint_id": verified.endpoint_id,
            "endpoint_slug": verified.endpoint_slug,
            "provider_authority_sha256": verified.provider_authority_sha256,
            "endpoint_contract_sha256": verified.endpoint_contract_sha256,
            "parameters_sha256": verified.parameters_sha256,
            "global_anomaly_codes_sha256": verified.global_anomaly_codes_sha256,
            "provider_result_set_count": verified.provider_result_set_count,
            "expected_result_set_count": verified.expected_result_set_count,
            "occurrence_count": verified.occurrence_count,
            "occurrence_inventory_sha256": verified.occurrence_inventory_sha256,
            "result_count": verified.result_count,
            "result_inventory_sha256": verified.result_inventory_sha256,
            "response_residual_record_count": verified.response_residual_record_count,
            "response_residual_records_sha256": verified.response_residual_records_sha256,
            "record_count": verified.record_count,
            "record_inventory_sha256": verified.record_inventory_sha256,
            "source_rows_sha256": verified.source_rows_sha256,
        }
        payload = {"schema_version": 1, "kind": cls.kind, **values}
        return cls(authority_sha256=canonical_sha256(payload), **values)

    def identity_payload(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "kind": self.kind,
            **{
                item.name: getattr(self, item.name)
                for item in fields(self)
                if item.name != "authority_sha256"
            },
        }


def _expected_units_and_assignments(
    *,
    manifest: StatsLosslessManifestV1,
    results: tuple[StatsLosslessResultV1, ...],
) -> tuple[ExpectedValueUnitInventoryV1, tuple[ValueRepresentationAssignmentV1, ...]]:
    units: list[ExpectedValueUnitV1] = []
    for result in results:
        unit = ExpectedValueUnitV1.build(
            raw_authority_bundle_sha256=manifest.raw_authority_bundle_sha256,
            unit_ordinal=len(units),
            observation_sha256=manifest.observation_sha256,
            observation_ordinal=0,
            unit_kind="result_occurrence",
            occurrence_sha256=result.occurrence_sha256,
            occurrence_ordinal=result.result_ordinal,
        )
        units.append(unit)
    if manifest.response_residual_record_count:
        units.append(
            ExpectedValueUnitV1.build(
                raw_authority_bundle_sha256=manifest.raw_authority_bundle_sha256,
                unit_ordinal=len(units),
                observation_sha256=manifest.observation_sha256,
                observation_ordinal=0,
                unit_kind="response_residual",
            )
        )
    inventory = ExpectedValueUnitInventoryV1.build(
        raw_authority_bundle_sha256=manifest.raw_authority_bundle_sha256,
        units=tuple(units),
    )
    assignments = tuple(
        ValueRepresentationAssignmentV1.build(
            expected_unit=unit,
            source_input_kind="parser_input_body",
            representation_kind=(
                STATS_LOSSLESS_REPRESENTATION_KIND
                if unit.unit_kind == "result_occurrence"
                else RESPONSE_LOSSLESS_REPRESENTATION_KIND
            ),
        )
        for unit in inventory.units
    )
    return inventory, assignments


@dataclass(frozen=True, slots=True)
class StatsLosslessValueAuthorityV1:
    """In-memory closure for the singular mandatory stats record relation."""

    receipt: StatsLosslessValueAuthorityReceiptV1
    manifest: StatsLosslessManifestV1
    expected_unit_inventory: ExpectedValueUnitInventoryV1
    representation_assignments: tuple[ValueRepresentationAssignmentV1, ...]
    results: tuple[StatsLosslessResultV1, ...]
    records: tuple[StatsLosslessRecordV1, ...]

    def __post_init__(self) -> None:
        if (
            type(self.receipt) is not StatsLosslessValueAuthorityReceiptV1
            or type(self.manifest) is not StatsLosslessManifestV1
            or type(self.expected_unit_inventory) is not ExpectedValueUnitInventoryV1
            or type(self.representation_assignments) is not tuple
            or type(self.results) is not tuple
            or type(self.records) is not tuple
        ):
            _fail("stats-lossless authority contains a foreign aggregate member")
        if any(type(item) is not StatsLosslessResultV1 for item in self.results) or any(
            type(item) is not StatsLosslessRecordV1 for item in self.records
        ):
            _fail("stats-lossless authority contains a foreign public DTO")
        if any(
            type(item) is not ValueRepresentationAssignmentV1
            for item in self.representation_assignments
        ):
            _fail("stats-lossless authority contains a foreign representation assignment")
        manifest = StatsLosslessManifestV1.from_row(self.manifest.to_row())
        receipt = StatsLosslessValueAuthorityReceiptV1.from_verified_manifest(manifest)
        if receipt != self.receipt:
            _fail("stats-lossless authority receipt differs from its verified manifest")
        if any(
            item.source_input_kind != "parser_input_body"
            for item in self.representation_assignments
        ):
            _fail("stats-lossless authority requires the Raw-V2 parser-input source")
        expected_inventory, expected_assignments = _expected_units_and_assignments(
            manifest=manifest,
            results=self.results,
        )
        if (
            ExpectedValueUnitInventoryV1.from_row(self.expected_unit_inventory.to_row())
            != expected_inventory
            or tuple(
                ValueRepresentationAssignmentV1.from_row(item.to_row())
                for item in self.representation_assignments
            )
            != expected_assignments
        ):
            _fail("stats-lossless authority expected-unit representations are incomplete")
        if not self.records:
            _fail("stats-lossless authority cannot infer an empty public relation")
        global_anomalies = _canonical_string_list(
            self.records[0].global_anomaly_codes_json,
            self.records[0].global_anomaly_codes_sha256,
            field_name="global_anomaly_codes",
            allowed=_GLOBAL_ANOMALY_CODES,
            allow_empty=False,
        )
        rebuilt_manifest = StatsLosslessManifestV1.build(
            raw_authority_bundle_sha256=manifest.raw_authority_bundle_sha256,
            observation_record_sha256=manifest.observation_record_sha256,
            observation_sha256=manifest.observation_sha256,
            route_id=manifest.route_id,
            route_authority_sha256=manifest.route_authority_sha256,
            committed_receipt_sha256=manifest.committed_receipt_sha256,
            response_receipt_sha256=manifest.response_receipt_sha256,
            endpoint_id=manifest.endpoint_id,
            endpoint_slug=manifest.endpoint_slug,
            provider_authority_sha256=manifest.provider_authority_sha256,
            endpoint_contract_sha256=manifest.endpoint_contract_sha256,
            parameters_sha256=manifest.parameters_sha256,
            global_anomaly_codes=global_anomalies,
            provider_result_set_count=manifest.provider_result_set_count,
            expected_result_set_count=manifest.expected_result_set_count,
            results=self.results,
            records=self.records,
        )
        if rebuilt_manifest != manifest:
            _fail("stats-lossless authority manifest differs from its exact records")

    def public_rows(self) -> tuple[dict[str, object], ...]:
        return tuple(item.to_row() for item in self.records)


def build_stats_lossless_value_authority(
    *,
    raw_authority_bundle_sha256: str,
    observation_record_sha256: str,
    observation_sha256: str,
    route_id: str,
    route_authority_sha256: str,
    committed_receipt_sha256: str,
    response_receipt_sha256: str,
    endpoint_id: str,
    endpoint_slug: str,
    provider_authority_sha256: str,
    endpoint_contract_sha256: str,
    parameters_sha256: str,
    global_anomaly_codes: Sequence[str],
    provider_result_set_count: int,
    expected_result_set_count: int,
    results: Sequence[StatsLosslessResultV1],
    records: Sequence[StatsLosslessRecordV1],
) -> StatsLosslessValueAuthorityV1:
    """Build and independently replay one complete mandatory stats authority."""

    result_sequence = _exact_public_sequence(
        results,
        field_name="stats-lossless authority results",
        maximum=MAX_STATS_LOSSLESS_RESULTS,
    )
    record_sequence = _exact_public_sequence(
        records,
        field_name="stats-lossless authority records",
        maximum=MAX_STATS_LOSSLESS_RECORDS,
    )
    exact_results = tuple(cast("Sequence[StatsLosslessResultV1]", result_sequence))
    exact_records = tuple(cast("Sequence[StatsLosslessRecordV1]", record_sequence))
    manifest = StatsLosslessManifestV1.build(
        raw_authority_bundle_sha256=raw_authority_bundle_sha256,
        observation_record_sha256=observation_record_sha256,
        observation_sha256=observation_sha256,
        route_id=route_id,
        route_authority_sha256=route_authority_sha256,
        committed_receipt_sha256=committed_receipt_sha256,
        response_receipt_sha256=response_receipt_sha256,
        endpoint_id=endpoint_id,
        endpoint_slug=endpoint_slug,
        provider_authority_sha256=provider_authority_sha256,
        endpoint_contract_sha256=endpoint_contract_sha256,
        parameters_sha256=parameters_sha256,
        global_anomaly_codes=global_anomaly_codes,
        provider_result_set_count=provider_result_set_count,
        expected_result_set_count=expected_result_set_count,
        results=exact_results,
        records=exact_records,
    )
    receipt = StatsLosslessValueAuthorityReceiptV1.from_verified_manifest(manifest)
    inventory, assignments = _expected_units_and_assignments(
        manifest=manifest,
        results=exact_results,
    )
    return StatsLosslessValueAuthorityV1(
        receipt=receipt,
        manifest=manifest,
        expected_unit_inventory=inventory,
        representation_assignments=assignments,
        results=exact_results,
        records=exact_records,
    )
