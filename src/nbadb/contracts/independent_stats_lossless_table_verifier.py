"""Dependency-pure verifier for public declared-stats lossless tables.

The verifier consumes only exact built-in structured rows.  It independently
checks a plain conditional-route authority row and plain Raw Authority V2 result
occurrence rows, but never imports or calls either production contract.  Exact
public staging rows are mandatory; sidecars and receipts cannot substitute for
the table values they commit.
"""

from __future__ import annotations

import hashlib
import json
import math
import re
from collections import Counter
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Final, Never, cast

from nbadb.contracts.stats_lossless_value_authority import (
    MAX_STATS_LOSSLESS_CANONICAL_BYTES,
    MAX_STATS_LOSSLESS_CELLS,
    MAX_STATS_LOSSLESS_HEADERS,
    MAX_STATS_LOSSLESS_RECORDS,
    MAX_STATS_LOSSLESS_RESULTS,
    MAX_STATS_LOSSLESS_ROWS,
    MAX_STATS_LOSSLESS_TOTAL_CANONICAL_BYTES,
    PUBLIC_VALUE_AUTHORITY_SCHEMA_VERSION,
    RESPONSE_LOSSLESS_REPRESENTATION_KIND,
    STATS_LOSSLESS_RECORD_COLUMNS,
    STATS_LOSSLESS_RECORD_SCHEMA_SHA256,
    STATS_LOSSLESS_REPRESENTATION_KIND,
    STATS_LOSSLESS_SOURCE_COLUMNS,
    STATS_LOSSLESS_SOURCE_SCHEMA_SHA256,
    StatsLosslessValueAuthorityReceiptV1,
)

if TYPE_CHECKING:
    from collections.abc import Iterable, Mapping, Sequence

__all__ = [
    "CONDITIONAL_ROUTE_PUBLIC_COLUMNS",
    "RAW_RESULT_OCCURRENCE_V2_COLUMNS",
    "IndependentStatsLosslessTableVerifierError",
    "verify_stats_lossless_public_tables",
]

_RAW_REQUEST_AUTHORITY_SCHEMA_VERSION: Final = 2
_CONDITIONAL_ROUTE_SCHEMA_VERSION: Final = 1
_LOSSLESS_STAGING_KEY: Final = "stg_nba_api_lossless_result_cells"
_MAX_STATS_LOSSLESS_DEPTH: Final = 64
_MAX_STATS_LOSSLESS_INTEGER_ABS: Final = (1 << 63) - 1
_MAX_STATS_LOSSLESS_JSON_NODES: Final = 2_000_000
_SHA256_RE = re.compile(r"[0-9a-f]{64}\Z")
_SAFE_ID_RE = re.compile(r"[A-Za-z0-9_][A-Za-z0-9_.:-]{0,511}\Z")
_METADATA_KEY_RE = re.compile(r"[^a-z0-9]+")
_IDENTIFIER_RE = re.compile(r"[^A-Za-z0-9]+")
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
_AUTHORIZATION_HEADER_SECRET_RE = re.compile(
    r"authorization\s*:\s*(?:bearer|basic)\s+"
    r"[A-Za-z0-9._~+/=-]{8,}(?![A-Za-z0-9._~+/=-])",
    flags=re.ASCII | re.IGNORECASE,
)
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
_PER_RESULT_ANOMALIES = frozenset(
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
_GLOBAL_ANOMALIES = frozenset(
    {
        *_PER_RESULT_ANOMALIES,
        "additive_result_set",
        "duplicate_result_set_name",
        "missing_result_set",
        "unknown_dynamic_response",
        "unrepresentable_typed_frame",
    }
)
_VALUE_KINDS = frozenset({"null", "boolean", "integer", "number", "string", "array", "object"})
_PRESENCE_KINDS = frozenset({"present", "null", "empty_object", "empty_array"})
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

CONDITIONAL_ROUTE_PUBLIC_COLUMNS: Final = (
    "schema_version",
    "kind",
    "route_id",
    "route_local_ordinal",
    "endpoint_name",
    "source_family",
    "source_shape",
    "staging_key",
    "schema_tier",
    "schema_table",
    "schema_class",
    "storage_role",
    "route_admission_sha256",
    "field_fate_structure_sha256",
    "provider_authority_sha256",
    "endpoint_contract_sha256",
    "committed_logical_parameters_sha256",
    "source_parameters_sha256s",
    "staging_parameters_sha256",
    "raw_bundle_sha256",
    "readback_receipt_sha256",
    "committed_receipt_root_sha256",
    "response_receipt_sha256",
    "observation_record_sha256s",
    "result_occurrence_sha256s",
    "body_object_sha256s",
    "stats_bindings",
    "live_binding_ids",
    "sinks",
    "authority_sha256",
)

RAW_RESULT_OCCURRENCE_V2_COLUMNS: Final = (
    "schema_version",
    "occurrence_sha256",
    "observation_sha256",
    "occurrence_ordinal",
    "result_name",
    "duplicate_name_ordinal",
    "provider_result_ordinal",
    "canonical_result_ordinal",
    "json_path",
    "container_kind",
    "presence",
    "ordered_headers_json",
    "ordered_headers_sha256",
    "header_count",
    "row_count",
    "cell_count",
    "node_count",
    "container_count",
    "missing_count",
    "null_count",
    "parent_state_sha256",
    "output_sha256",
    "canonical_route_ids_json",
    "canonical_route_ids_sha256",
    "committed_staging_receipts_json",
    "committed_staging_receipts_sha256",
    "landing_disposition",
    "logical_result_receipt_sha256",
    "route_receipt_sha256",
)


class IndependentStatsLosslessTableVerifierError(ValueError):
    """One plain public stats-lossless table closure is invalid."""


def _fail(message: str) -> Never:
    raise IndependentStatsLosslessTableVerifierError(message)


def _sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _sha256(value: object, *, field_name: str) -> str:
    if type(value) is not str or _SHA256_RE.fullmatch(value) is None:
        _fail(f"{field_name} must be one exact lowercase SHA-256")
    return value


def _optional_sha256(value: object, *, field_name: str) -> str | None:
    if value is None:
        return None
    return _sha256(value, field_name=field_name)


def _nonnegative(value: object, *, field_name: str, maximum: int) -> int:
    if type(value) is not int or value < 0 or value > maximum:
        _fail(f"{field_name} must be a bounded nonnegative exact integer")
    return value


def _optional_nonnegative(value: object, *, field_name: str, maximum: int) -> int | None:
    if value is None:
        return None
    return _nonnegative(value, field_name=field_name, maximum=maximum)


def _safe_id(value: object, *, field_name: str) -> str:
    if type(value) is not str or _SAFE_ID_RE.fullmatch(value) is None:
        _fail(f"{field_name} must be one exact safe public identifier")
    return value


def _exact_version(value: object, *, expected: int, field_name: str) -> int:
    if type(value) is not int or value != expected:
        _fail(f"{field_name} must be the exact supported integer version")
    return value


def _exact_literal(value: object, *, allowed: frozenset[str], field_name: str) -> str:
    if type(value) is not str or value not in allowed:
        _fail(f"{field_name} is not one exact supported literal")
    return value


def _exact_row(
    value: object,
    *,
    columns: tuple[str, ...],
    label: str,
) -> dict[str, object]:
    if type(value) is not dict:
        _fail(f"{label} does not have its exact ordered public columns")
    mapping = cast("dict[object, object]", value)
    if any(type(key) is not str for key in mapping) or tuple(mapping) != columns:
        _fail(f"{label} does not have its exact ordered public columns")
    return cast("dict[str, object]", value)


def _exact_sequence(
    value: object, *, label: str, maximum: int
) -> list[object] | tuple[object, ...]:
    if type(value) not in {list, tuple}:
        _fail(f"{label} must be one exact structured row sequence")
    rows = cast("list[object] | tuple[object, ...]", value)
    if len(rows) > maximum:
        _fail(f"{label} exceeds its explicit bound before copying")
    return rows


def _reject_duplicate_keys(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            _fail("public stats-lossless JSON contains a duplicate object key")
        result[key] = value
    return result


def _reject_constant(_value: str) -> Never:
    _fail("public stats-lossless JSON contains a non-finite number")


def _reject_secret_shaped_text(value: str) -> None:
    stripped = value.strip()
    if (
        _AUTHORIZATION_HEADER_SECRET_RE.search(stripped) is not None
        or _BEARER_SECRET_RE.search(stripped) is not None
        or _BASIC_SECRET_RE.search(stripped) is not None
        or _LOCAL_PATH_VALUE_RE.search(value) is not None
        or any(pattern.search(value) is not None for pattern in _EMBEDDED_SECRET_RES)
    ):
        _fail("public stats-lossless value contains secret-shaped text")


def _validate_json_graph(value: object, *, maximum_bytes: int) -> None:
    nodes = 0
    estimated_bytes = 0
    stack: list[tuple[object, int]] = [(value, 0)]
    while stack:
        item, depth = stack.pop()
        nodes += 1
        if nodes > 2_000_000 or depth > 64:
            _fail("public stats-lossless JSON exceeds its node or depth bound")
        if item is None:
            estimated_bytes += 4
        elif type(item) is bool:
            estimated_bytes += 5
        elif type(item) is str:
            text = item
            if len(text) > maximum_bytes:
                _fail("public stats-lossless string exceeds its preallocation bound")
            _reject_secret_shaped_text(text)
            estimated_bytes += 6 * len(text) + 2
        elif type(item) is int:
            if abs(cast("int", item)) > (1 << 63) - 1:
                _fail("public stats-lossless integer exceeds its exact bound")
            estimated_bytes += 20
        elif type(item) is float:
            number = cast("float", item)
            if not math.isfinite(number) or (number == 0.0 and math.copysign(1.0, number) < 0):
                _fail("public stats-lossless number is non-finite or negative zero")
            estimated_bytes += 32
        elif type(item) is list:
            children = cast("list[object]", item)
            if len(children) > 2_000_000 - nodes - len(stack):
                _fail("public stats-lossless JSON exceeds its node bound before traversal")
            estimated_bytes += len(children) + 2
            stack.extend((child, depth + 1) for child in children)
        elif type(item) is dict:
            mapping = cast("dict[object, object]", item)
            if any(type(key) is not str for key in mapping):
                _fail("public stats-lossless object contains a non-string exact key")
            if len(mapping) > 2_000_000 - nodes - len(stack):
                _fail("public stats-lossless JSON exceeds its node bound before traversal")
            for key in mapping:
                exact_key = cast("str", key)
                if len(exact_key) > maximum_bytes:
                    _fail("public stats-lossless object key exceeds its preallocation bound")
                _reject_sensitive_public_key(exact_key)
                _reject_secret_shaped_text(exact_key)
                estimated_bytes += 6 * len(exact_key) + 3
            estimated_bytes += len(mapping) + 2
            stack.extend((child, depth + 1) for child in mapping.values())
        else:
            _fail("public stats-lossless JSON contains a foreign runtime type")
        if estimated_bytes > maximum_bytes:
            _fail("public stats-lossless JSON exceeds its preallocation bound")


def _canonical_bytes(value: object, *, maximum_bytes: int) -> bytes:
    if (
        type(maximum_bytes) is not int
        or maximum_bytes < 1
        or maximum_bytes > MAX_STATS_LOSSLESS_TOTAL_CANONICAL_BYTES
    ):
        _fail("public stats-lossless canonical JSON byte bound is invalid")
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
        raise IndependentStatsLosslessTableVerifierError(
            "public stats-lossless value is not bounded canonical JSON"
        ) from exc
    if len(encoded) > maximum_bytes:
        _fail("public stats-lossless canonical JSON exceeds its exact byte bound")
    return encoded


def _json_value_kind(value: object) -> str:
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
    _fail("public stats-lossless value has a foreign JSON kind")


def _json_presence_kind(value: object) -> str:
    if value is None:
        return "null"
    if type(value) is list and not value:
        return "empty_array"
    if type(value) is dict and not value:
        return "empty_object"
    return "present"


def _preflight_json_text(raw: bytes, *, label: str) -> None:
    """Bound JSON nesting and structural work before decoder allocation."""

    containers: list[int] = []
    nodes = 1
    in_string = False
    escaped = False
    for byte in raw:
        if in_string:
            if escaped:
                escaped = False
            elif byte == 0x5C:
                escaped = True
            elif byte == 0x22:
                in_string = False
            continue
        if byte == 0x22:
            in_string = True
        elif byte in {0x5B, 0x7B}:
            containers.append(byte)
            nodes += 1
            if len(containers) > _MAX_STATS_LOSSLESS_DEPTH:
                _fail(f"{label} exceeds its depth bound")
        elif byte in {0x5D, 0x7D}:
            expected = 0x5B if byte == 0x5D else 0x7B
            if not containers or containers.pop() != expected:
                _fail(f"{label} has malformed lexical structure")
        elif byte == 0x2C:
            nodes += 1
        if nodes > _MAX_STATS_LOSSLESS_JSON_NODES:
            _fail(f"{label} exceeds its lexical node bound")
    if in_string or escaped or containers:
        _fail(f"{label} has incomplete lexical structure")


def _bounded_json_integer(token: str) -> int:
    if len(token) > 64:
        _fail("public stats-lossless JSON integer token exceeds its bound")
    try:
        value = int(token)
    except ValueError:
        raise IndependentStatsLosslessTableVerifierError(
            "public stats-lossless JSON integer token is invalid"
        ) from None
    if abs(value) > _MAX_STATS_LOSSLESS_INTEGER_ABS:
        _fail("public stats-lossless JSON integer exceeds its exact bound")
    return value


def _bounded_json_float(token: str) -> float:
    if len(token) > 64:
        _fail("public stats-lossless JSON number token exceeds its bound")
    try:
        value = float(token)
    except ValueError:
        raise IndependentStatsLosslessTableVerifierError(
            "public stats-lossless JSON number token is invalid"
        ) from None
    if not math.isfinite(value) or (value == 0.0 and math.copysign(1.0, value) < 0):
        _fail("public stats-lossless JSON number is non-finite or negative zero")
    return value


def _canonical_value(encoded: object, *, label: str) -> object:
    if type(encoded) is not str or not encoded:
        _fail(f"{label} must be nonempty exact canonical JSON text")
    text = cast("str", encoded)
    if len(text) > MAX_STATS_LOSSLESS_CANONICAL_BYTES:
        _fail(f"{label} exceeds its pre-decode character bound")
    try:
        raw = text.encode("utf-8", errors="strict")
    except UnicodeEncodeError as exc:
        raise IndependentStatsLosslessTableVerifierError(
            "public stats-lossless canonical JSON is not UTF-8"
        ) from exc
    if len(raw) > MAX_STATS_LOSSLESS_CANONICAL_BYTES:
        _fail(f"{label} exceeds its exact byte bound")
    _preflight_json_text(raw, label=label)
    try:
        value = json.loads(
            raw,
            object_pairs_hook=_reject_duplicate_keys,
            parse_float=_bounded_json_float,
            parse_int=_bounded_json_integer,
            parse_constant=_reject_constant,
        )
    except IndependentStatsLosslessTableVerifierError:
        raise
    except (UnicodeError, ValueError, OverflowError, RecursionError, TypeError):
        raise IndependentStatsLosslessTableVerifierError(
            "public stats-lossless canonical JSON cannot be decoded"
        ) from None
    canonical = _canonical_bytes(value, maximum_bytes=MAX_STATS_LOSSLESS_CANONICAL_BYTES)
    if canonical != raw:
        _fail(f"{label} is not the exact canonical encoding")
    return value


def _canonical_array(encoded: object, *, label: str, maximum: int) -> list[object]:
    value = _canonical_value(encoded, label=label)
    if type(value) is not list or len(value) > maximum:
        _fail(f"{label} must be one bounded canonical array")
    return cast("list[object]", value)


def _normalized_public_key(value: str) -> str:
    separated = _CAMEL_ACRONYM_BOUNDARY_RE.sub(r"\1_\2", value)
    separated = _CAMEL_WORD_BOUNDARY_RE.sub(r"\1_\2", separated)
    return _KEY_SEPARATOR_RE.sub("_", separated).strip("_").lower()


def _reject_sensitive_public_key(value: str) -> None:
    normalized = _normalized_public_key(value)
    if _SENSITIVE_OBJECT_KEY_RE.fullmatch(normalized) is not None or any(
        component in _GENERIC_SENSITIVE_KEY_COMPONENTS for component in normalized.split("_")
    ):
        _fail("public stats-lossless object contains secret-shaped material")


def _public_header(value: object, *, allow_empty: bool) -> str:
    if type(value) is not str:
        _fail("public stats-lossless header must be exact text")
    header = value
    if (not allow_empty and not header) or len(header) > 1_024:
        _fail("public stats-lossless header is absent or over bound")
    _reject_sensitive_public_key(header)
    _canonical_bytes(header, maximum_bytes=8_192)
    return header


def _canonical_text_array(
    encoded: object,
    digest: object,
    *,
    label: str,
    maximum: int,
    safe_headers: bool = False,
) -> tuple[str, ...]:
    values = _canonical_array(encoded, label=label, maximum=maximum)
    if any(type(item) is not str for item in values):
        _fail(f"{label} must contain exact strings")
    result = tuple(cast("list[str]", values))
    if safe_headers:
        for header in result:
            _public_header(header, allow_empty=False)
    if _sha256(digest, field_name=f"{label}_sha256") != _sha256_bytes(
        cast("str", encoded).encode("utf-8")
    ):
        _fail(f"{label} digest differs from its exact text")
    return result


def _canonical_hash(value: object) -> str:
    return _sha256_bytes(_canonical_bytes(value, maximum_bytes=MAX_STATS_LOSSLESS_CANONICAL_BYTES))


def _canonical_root(*, kind: str, count: int, values: Iterable[object]) -> str:
    _safe_id(kind, field_name="ordered root kind")
    _nonnegative(count, field_name="ordered root count", maximum=MAX_STATS_LOSSLESS_RECORDS)
    digest = hashlib.sha256()
    digest.update(b'{"count":')
    digest.update(str(count).encode("ascii"))
    digest.update(b',"items":[')
    seen = 0
    for ordinal, value in enumerate(values):
        if ordinal:
            digest.update(b",")
        digest.update(_canonical_bytes(value, maximum_bytes=MAX_STATS_LOSSLESS_CANONICAL_BYTES))
        seen += 1
        if seen > count:
            _fail("public stats-lossless ordered root exceeded its denominator")
    if seen != count:
        _fail("public stats-lossless ordered root differs from its denominator")
    digest.update(b'],"kind":')
    digest.update(_canonical_bytes(kind, maximum_bytes=2_048))
    digest.update(b',"schema_version":1}')
    return digest.hexdigest()


def _route_authority_row(
    value: object,
    *,
    expected_raw_bundle_sha256: str,
    expected_route_authority_sha256: str,
) -> dict[str, object]:
    row = _exact_row(
        value,
        columns=CONDITIONAL_ROUTE_PUBLIC_COLUMNS,
        label="conditional route public authority row",
    )
    _exact_version(
        row["schema_version"],
        expected=_CONDITIONAL_ROUTE_SCHEMA_VERSION,
        field_name="conditional route schema_version",
    )
    _exact_literal(
        row["kind"],
        allowed=frozenset({"conditional_route_occurrence_authority"}),
        field_name="conditional route kind",
    )
    route_id = _safe_id(row["route_id"], field_name="route_id")
    _nonnegative(
        row["route_local_ordinal"],
        field_name="route_local_ordinal",
        maximum=MAX_STATS_LOSSLESS_RESULTS,
    )
    endpoint_name = _safe_id(row["endpoint_name"], field_name="endpoint_name")
    source_family = _exact_literal(
        row["source_family"], allowed=frozenset({"stats"}), field_name="source_family"
    )
    source_shape = _exact_literal(
        row["source_shape"],
        allowed=frozenset({"selected_result_bound", "body_node_bound", "hybrid_result_body_bound"}),
        field_name="source_shape",
    )
    staging_key = _safe_id(row["staging_key"], field_name="staging_key")
    schema_tier = _exact_literal(
        row["schema_tier"], allowed=frozenset({"staging"}), field_name="schema_tier"
    )
    schema_table = _safe_id(row["schema_table"], field_name="schema_table")
    storage_role = _exact_literal(
        row["storage_role"],
        allowed=frozenset({"conditional_lossless"}),
        field_name="storage_role",
    )
    if (
        source_family != "stats"
        or source_shape
        not in {"selected_result_bound", "body_node_bound", "hybrid_result_body_bound"}
        or staging_key != _LOSSLESS_STAGING_KEY
        or schema_tier != "staging"
        or schema_table != _LOSSLESS_STAGING_KEY
        or storage_role != "conditional_lossless"
        or not route_id.startswith(f"{endpoint_name}:")
    ):
        _fail("conditional route public authority is outside declared stats lossless scope")
    if type(row["schema_class"]) is not str or not row["schema_class"]:
        _fail("conditional route public authority omits its schema class")
    for field_name in (
        "route_admission_sha256",
        "field_fate_structure_sha256",
        "provider_authority_sha256",
        "endpoint_contract_sha256",
        "committed_logical_parameters_sha256",
        "raw_bundle_sha256",
        "readback_receipt_sha256",
        "committed_receipt_root_sha256",
        "response_receipt_sha256",
        "authority_sha256",
    ):
        _sha256(row[field_name], field_name=field_name)
    _optional_sha256(row["staging_parameters_sha256"], field_name="staging_parameters_sha256")
    if row["raw_bundle_sha256"] != expected_raw_bundle_sha256:
        _fail("conditional route public authority was rebound to another raw bundle")
    if row["authority_sha256"] != expected_route_authority_sha256:
        _fail("conditional route public authority differs from its admitted root")

    for field_name, maximum, allow_empty in (
        ("source_parameters_sha256s", MAX_STATS_LOSSLESS_RESULTS, False),
        ("observation_record_sha256s", MAX_STATS_LOSSLESS_RESULTS, False),
        ("result_occurrence_sha256s", MAX_STATS_LOSSLESS_RESULTS, True),
        ("body_object_sha256s", MAX_STATS_LOSSLESS_RESULTS, True),
    ):
        sequence = _exact_sequence(row[field_name], label=field_name, maximum=maximum)
        if (not allow_empty and not sequence) or any(
            type(item) is not str or _SHA256_RE.fullmatch(item) is None for item in sequence
        ):
            _fail("conditional route public digest inventory is invalid")
        if tuple(sequence) != tuple(sorted(set(cast("Sequence[str]", sequence)))):
            _fail("conditional route public digest inventory is not canonical")
    if len(cast("Sequence[object]", row["observation_record_sha256s"])) != 1:
        _fail("stats-lossless value authority requires one exact observation")
    result_occurrences = cast("Sequence[str]", row["result_occurrence_sha256s"])
    body_objects = cast("Sequence[str]", row["body_object_sha256s"])
    if (
        (source_shape == "selected_result_bound" and (not result_occurrences or body_objects))
        or (source_shape == "body_node_bound" and (result_occurrences or not body_objects))
        or (
            source_shape == "hybrid_result_body_bound"
            and (not result_occurrences or not body_objects)
        )
    ):
        _fail("conditional route source shape differs from its exact source roots")
    for field_name, allow_empty in (
        ("stats_bindings", False),
        ("live_binding_ids", True),
        ("sinks", False),
    ):
        sequence = _exact_sequence(
            row[field_name],
            label=field_name,
            maximum=MAX_STATS_LOSSLESS_RECORDS,
        )
        if not allow_empty and not sequence:
            _fail("conditional route public authority omits its binding or sink evidence")
        if field_name == "live_binding_ids" and sequence:
            _fail("stats conditional route contains live binding IDs")
    identity_payload = {key: row[key] for key in CONDITIONAL_ROUTE_PUBLIC_COLUMNS[:-1]}
    if _canonical_hash(identity_payload) != row["authority_sha256"]:
        _fail("conditional route public authority digest is invalid")
    return row


def _raw_occurrence_row(value: object) -> dict[str, object]:
    row = _exact_row(
        value,
        columns=RAW_RESULT_OCCURRENCE_V2_COLUMNS,
        label="raw result occurrence public row",
    )
    _exact_version(
        row["schema_version"],
        expected=_RAW_REQUEST_AUTHORITY_SCHEMA_VERSION,
        field_name="raw result occurrence schema_version",
    )
    for field_name in (
        "occurrence_sha256",
        "observation_sha256",
        "ordered_headers_sha256",
        "parent_state_sha256",
        "output_sha256",
        "canonical_route_ids_sha256",
        "committed_staging_receipts_sha256",
        "logical_result_receipt_sha256",
        "route_receipt_sha256",
    ):
        if field_name == "parent_state_sha256":
            _optional_sha256(row[field_name], field_name=field_name)
        else:
            _sha256(row[field_name], field_name=field_name)
    for field_name, maximum in (
        ("occurrence_ordinal", MAX_STATS_LOSSLESS_RESULTS - 1),
        ("duplicate_name_ordinal", MAX_STATS_LOSSLESS_RESULTS - 1),
        ("provider_result_ordinal", MAX_STATS_LOSSLESS_RESULTS - 1),
        ("canonical_result_ordinal", MAX_STATS_LOSSLESS_RESULTS - 1),
        ("header_count", MAX_STATS_LOSSLESS_HEADERS),
        ("row_count", MAX_STATS_LOSSLESS_ROWS),
        ("cell_count", MAX_STATS_LOSSLESS_CELLS),
        ("node_count", MAX_STATS_LOSSLESS_RECORDS),
        ("container_count", MAX_STATS_LOSSLESS_RESULTS),
        ("missing_count", MAX_STATS_LOSSLESS_RESULTS),
        ("null_count", MAX_STATS_LOSSLESS_RESULTS),
    ):
        if field_name in {"provider_result_ordinal", "canonical_result_ordinal"}:
            _optional_nonnegative(row[field_name], field_name=field_name, maximum=maximum)
        else:
            _nonnegative(row[field_name], field_name=field_name, maximum=maximum)
    header_count = _nonnegative(
        row["header_count"],
        field_name="header_count",
        maximum=MAX_STATS_LOSSLESS_HEADERS,
    )
    row_count = _nonnegative(
        row["row_count"],
        field_name="row_count",
        maximum=MAX_STATS_LOSSLESS_ROWS,
    )
    cell_count = _nonnegative(
        row["cell_count"],
        field_name="cell_count",
        maximum=MAX_STATS_LOSSLESS_CELLS,
    )
    container_count = _nonnegative(
        row["container_count"],
        field_name="container_count",
        maximum=MAX_STATS_LOSSLESS_RESULTS,
    )
    missing_count = _nonnegative(
        row["missing_count"],
        field_name="missing_count",
        maximum=MAX_STATS_LOSSLESS_RESULTS,
    )
    _safe_id(row["result_name"], field_name="result_name")
    container_kind = _exact_literal(
        row["container_kind"],
        allowed=frozenset({"nba_api_result_set"}),
        field_name="container_kind",
    )
    presence = _exact_literal(
        row["presence"],
        allowed=frozenset({"present", "present_empty", "missing"}),
        field_name="presence",
    )
    landing_disposition = _exact_literal(
        row["landing_disposition"],
        allowed=frozenset({"lossless_only", "wide_plus_lossless"}),
        field_name="landing_disposition",
    )
    if (
        row["json_path"] is not None
        or container_kind != "nba_api_result_set"
        or presence not in {"present", "present_empty", "missing"}
        or row["node_count"] != 0
        or row["null_count"] != 0
    ):
        _fail("raw result occurrence is outside declared stats result-set grammar")
    headers = _canonical_text_array(
        row["ordered_headers_json"],
        row["ordered_headers_sha256"],
        label="ordered result headers",
        maximum=MAX_STATS_LOSSLESS_HEADERS,
        safe_headers=True,
    )
    if len(headers) != header_count or cell_count != header_count * row_count:
        _fail("raw result occurrence header/row/cell algebra is invalid")
    if row["presence"] == "missing":
        if (
            row["provider_result_ordinal"] is not None
            or headers
            or row_count != 0
            or cell_count != 0
            or container_count != 0
            or missing_count < 1
        ):
            _fail("raw missing result occurrence has invalid counts or identity")
    else:
        expected_presence = "present" if row_count else "present_empty"
        if (
            row["provider_result_ordinal"] is None
            or row["presence"] != expected_presence
            or container_count < 1
            or missing_count != 0
        ):
            _fail("raw present result occurrence has invalid counts or identity")

    route_ids = _canonical_text_array(
        row["canonical_route_ids_json"],
        row["canonical_route_ids_sha256"],
        label="canonical result route IDs",
        maximum=MAX_STATS_LOSSLESS_RESULTS,
    )
    if not route_ids or len(set(route_ids)) != len(route_ids):
        _fail("raw result occurrence route inventory is empty or duplicated")
    for route_id in route_ids:
        _safe_id(route_id, field_name="canonical result route ID")
    receipt_rows = _canonical_array(
        row["committed_staging_receipts_json"],
        label="committed staging receipts",
        maximum=MAX_STATS_LOSSLESS_RESULTS,
    )
    if row["committed_staging_receipts_sha256"] != _sha256_bytes(
        cast("str", row["committed_staging_receipts_json"]).encode("utf-8")
    ):
        _fail("committed staging receipt digest is invalid")
    receipt_routes: list[str] = []
    for receipt in receipt_rows:
        receipt_row = _exact_row(
            receipt,
            columns=("receipt_sha256", "route_id"),
            label="committed staging receipt row",
        )
        receipt_routes.append(_safe_id(receipt_row["route_id"], field_name="receipt route_id"))
        _sha256(receipt_row["receipt_sha256"], field_name="receipt_sha256")
    if len(receipt_routes) != len(set(receipt_routes)) or any(
        route_id not in route_ids for route_id in receipt_routes
    ):
        _fail("committed staging receipt route inventory is invalid")
    if landing_disposition not in {"lossless_only", "wide_plus_lossless"}:
        _fail("declared stats-lossless occurrence has a foreign landing disposition")

    logical_payload = {
        "schema_version": _RAW_REQUEST_AUTHORITY_SCHEMA_VERSION,
        "observation_sha256": row["observation_sha256"],
        "occurrence_ordinal": row["occurrence_ordinal"],
        "result_name": row["result_name"],
        "duplicate_name_ordinal": row["duplicate_name_ordinal"],
        "provider_result_ordinal": row["provider_result_ordinal"],
        "canonical_result_ordinal": row["canonical_result_ordinal"],
        "json_path": row["json_path"],
        "container_kind": row["container_kind"],
        "presence": row["presence"],
        "ordered_headers_sha256": row["ordered_headers_sha256"],
        "header_count": row["header_count"],
        "row_count": row["row_count"],
        "cell_count": row["cell_count"],
        "node_count": row["node_count"],
        "container_count": row["container_count"],
        "missing_count": row["missing_count"],
        "null_count": row["null_count"],
        "parent_state_sha256": row["parent_state_sha256"],
        "output_sha256": row["output_sha256"],
    }
    if _canonical_hash(logical_payload) != row["logical_result_receipt_sha256"]:
        _fail("raw result occurrence logical receipt digest is invalid")
    if (
        _canonical_hash(
            {
                "logical_result_receipt_sha256": row["logical_result_receipt_sha256"],
                "canonical_route_ids_sha256": row["canonical_route_ids_sha256"],
                "landing_disposition": row["landing_disposition"],
            }
        )
        != row["route_receipt_sha256"]
    ):
        _fail("raw result occurrence route receipt digest is invalid")
    occurrence_payload = {
        **logical_payload,
        "ordered_headers_json": row["ordered_headers_json"],
        "canonical_route_ids_json": row["canonical_route_ids_json"],
        "canonical_route_ids_sha256": row["canonical_route_ids_sha256"],
        "committed_staging_receipts_json": row["committed_staging_receipts_json"],
        "committed_staging_receipts_sha256": row["committed_staging_receipts_sha256"],
        "landing_disposition": row["landing_disposition"],
        "logical_result_receipt_sha256": row["logical_result_receipt_sha256"],
        "route_receipt_sha256": row["route_receipt_sha256"],
    }
    # Preserve the exact production payload order only semantically: canonical hashing sorts keys.
    if _canonical_hash(occurrence_payload) != row["occurrence_sha256"]:
        _fail("raw result occurrence digest is invalid")
    return row


def _normalized_metadata_key(value: str) -> str:
    return _METADATA_KEY_RE.sub("_", value.strip().lower()).strip("_")


def _identifier(value: str) -> str:
    return _IDENTIFIER_RE.sub("_", value).strip("_").lower()


def _deduplicate_headers(headers: Sequence[str]) -> tuple[str, ...]:
    result: list[str] = []
    counts: dict[str, int] = {}
    for raw_header in headers:
        header = raw_header.strip()
        if not header:
            continue
        count = counts.get(header, 0) + 1
        counts[header] = count
        result.append(header if count == 1 else f"{header}_{count}")
    return tuple(result)


def _structured_legacy_headers(raw_headers: list[object]) -> tuple[str, ...]:
    records: list[dict[str, object]] = []
    for value in raw_headers:
        if type(value) is not dict or any(
            type(key) is not str for key in cast("dict[object, object]", value)
        ):
            _fail("structured stats header contains a foreign record")
        records.append(cast("dict[str, object]", value))
    columns_record: dict[str, object] | None = None
    for record in records:
        name = record.get("name")
        if type(name) is str and _normalized_metadata_key(name) == "columns":
            if columns_record is not None:
                _fail("structured stats headers contain duplicate columns metadata")
            columns_record = record
    if columns_record is None:
        _fail("structured stats headers omit columns metadata")
    column_names = columns_record.get("columnNames")
    if type(column_names) is not list or len(column_names) > MAX_STATS_LOSSLESS_HEADERS:
        _fail("structured stats column names are not one bounded array")
    if any(type(name) is not str or not name.strip() for name in column_names):
        _fail("structured stats headers contain an invalid column name")
    base_columns = list(cast("list[str]", column_names))
    if not base_columns:
        _fail("structured stats headers contain no columns")

    grouping_records: list[dict[str, object]] = []
    for record in records:
        name = record.get("name")
        if type(name) is str and _normalized_metadata_key(name) == "columns":
            continue
        labels = record.get("columnNames")
        span = record.get("columnSpan")
        if type(labels) is list and type(span) is int and span > 0:
            grouping_records.append(record)
    if not grouping_records:
        return _deduplicate_headers(base_columns)

    primary = grouping_records[0]
    skip_value = primary.get("columnsToSkip", 0)
    span_value = primary["columnSpan"]
    if (
        type(skip_value) is not int
        or skip_value < 0
        or type(span_value) is not int
        or span_value < 1
    ):
        _fail("structured stats header grouping ordinals are invalid")
    labels = primary["columnNames"]
    if type(labels) is not list or len(labels) > MAX_STATS_LOSSLESS_HEADERS:
        _fail("structured stats header labels are not one bounded array")
    if any(type(label) is not str for label in labels):
        _fail("structured stats header grouping label is invalid")
    output = [column for column in base_columns[:skip_value] if column.strip()]
    metrics = base_columns[skip_value:]
    cursor = 0
    for raw_label in cast("list[str]", labels):
        label = _identifier(raw_label)
        if not label:
            continue
        for _offset in range(span_value):
            if cursor >= len(metrics):
                break
            metric = _identifier(metrics[cursor])
            cursor += 1
            if metric:
                output.append(f"{label}_{metric}")
            if len(output) > MAX_STATS_LOSSLESS_HEADERS:
                _fail("structured stats headers exceed their exact output bound")
    output.extend(metrics[cursor:])
    if len(output) > MAX_STATS_LOSSLESS_HEADERS:
        _fail("structured stats headers exceed their exact output bound")
    return _deduplicate_headers(output)


def _observed_header_details(
    raw_headers: object,
) -> tuple[tuple[str | None, ...], tuple[object, ...]]:
    if type(raw_headers) is not list:
        return (), ()
    headers = cast("list[object]", raw_headers)
    if len(headers) > MAX_STATS_LOSSLESS_HEADERS:
        _fail("raw stats headers exceed their exact occurrence bound")
    if all(type(header) is str for header in headers):
        names = tuple(cast("list[str]", headers))
        for name in names:
            _public_header(name, allow_empty=True)
        return names, names
    if headers and all(type(header) is dict for header in headers):
        try:
            structured = _structured_legacy_headers(headers)
        except IndependentStatsLosslessTableVerifierError:
            structured = ()
        if structured:
            for name in structured:
                _public_header(name, allow_empty=True)
            return structured, structured
    names = tuple(header if type(header) is str else None for header in headers)
    for name in names:
        if name is not None:
            _public_header(name, allow_empty=True)
    return names, tuple(headers)


def _per_result_anomalies(
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
            _fail("raw stats row exceeds its exact cell bound")
        widths.add(len(row))
        if len(row) != len(observed_header_names):
            reasons.add("ragged_row")
        for ordinal, value in enumerate(row):
            kind = _json_value_kind(value)
            if kind != "null":
                kinds_by_ordinal.setdefault(ordinal, set()).add(kind)
    if len(widths) > 1:
        reasons.add("ragged_row")
    if any(len(kinds) > 1 for kinds in kinds_by_ordinal.values()):
        reasons.add("heterogeneous_column")
    return tuple(sorted(reasons))


def _canonical_value_text(value: object) -> str:
    return _canonical_bytes(
        value,
        maximum_bytes=MAX_STATS_LOSSLESS_CANONICAL_BYTES,
    ).decode("utf-8")


def _canonical_codes(
    encoded: object,
    digest: object,
    *,
    label: str,
    allowed: frozenset[str],
    allow_empty: bool,
) -> tuple[str, ...]:
    values = _canonical_array(encoded, label=label, maximum=len(allowed))
    if any(type(item) is not str or item not in allowed for item in values):
        _fail(f"{label} contains an unsupported code")
    result = tuple(cast("list[str]", values))
    if result != tuple(sorted(set(result))) or (not allow_empty and not result):
        _fail(f"{label} must be sorted, unique, and canonical")
    if _sha256(digest, field_name=f"{label}_sha256") != _sha256_bytes(
        cast("str", encoded).encode("utf-8")
    ):
        _fail(f"{label} digest differs from its exact text")
    return result


_STATS_BINDING_COLUMNS: Final = (
    "binding_id",
    "binding_kind",
    "route_id",
    "staging_key",
    "staging_row_ordinal",
    "observation_record_sha256",
    "observation_sha256",
    "source_occurrence_sha256",
    "body_object_sha256",
    "response_receipt_sha256",
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
    "selector_columns",
    "row_identity_json",
    "row_identity_sha256",
    "binding_evidence_sha256",
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


@dataclass(frozen=True, slots=True)
class _RecordRow:
    data: dict[str, object]
    decoded_value: object
    decoded_global_anomalies: tuple[str, ...]

    def __getattr__(self, name: str) -> Any:
        try:
            return self.data[name]
        except KeyError as exc:  # pragma: no cover - exact columns are prevalidated
            raise AttributeError(name) from exc

    def source_row(self) -> dict[str, object]:
        return _source_row_payload(self.data)


@dataclass(frozen=True, slots=True)
class _ResultReceipt:
    data: dict[str, object]
    expected_headers: tuple[str, ...] | None
    raw_headers: object
    raw_rows: object
    anomaly_codes: tuple[str, ...]
    records: tuple[_RecordRow, ...]
    landing_disposition: str

    def __getattr__(self, name: str) -> Any:
        try:
            return self.data[name]
        except KeyError as exc:  # pragma: no cover - internal fixed mapping
            raise AttributeError(name) from exc


def _source_row_payload(record: Mapping[str, object]) -> dict[str, object]:
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


def _optional_public_header(value: object) -> str | None:
    if value is None:
        return None
    return _public_header(value, allow_empty=True)


def _load_records(value: object) -> list[_RecordRow]:
    rows = _exact_sequence(
        value,
        label="stats-lossless record rows",
        maximum=MAX_STATS_LOSSLESS_RECORDS,
    )
    records: list[_RecordRow] = []
    cumulative_bytes = 0
    for item in rows:
        raw = _exact_row(
            item,
            columns=STATS_LOSSLESS_RECORD_COLUMNS,
            label="stats-lossless record row",
        )
        _exact_version(
            raw["schema_version"],
            expected=PUBLIC_VALUE_AUTHORITY_SCHEMA_VERSION,
            field_name="stats-lossless record schema_version",
        )
        owner_kind = _exact_literal(
            raw["owner_kind"],
            allowed=_OWNER_KINDS,
            field_name="stats-lossless record owner_kind",
        )
        representation_kind = _exact_literal(
            raw["representation_kind"],
            allowed=frozenset(
                {
                    STATS_LOSSLESS_REPRESENTATION_KIND,
                    RESPONSE_LOSSLESS_REPRESENTATION_KIND,
                }
            ),
            field_name="stats-lossless record representation_kind",
        )
        expected_representation = (
            STATS_LOSSLESS_REPRESENTATION_KIND
            if owner_kind == "result_occurrence"
            else RESPONSE_LOSSLESS_REPRESENTATION_KIND
        )
        if representation_kind != expected_representation:
            _fail("stats-lossless record representation differs from its exact owner")
        record_kind = _exact_literal(
            raw["record_kind"],
            allowed=_RECORD_KINDS,
            field_name="stats-lossless record_kind",
        )
        for field_name in (
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
            "global_anomaly_codes_sha256",
        ):
            _sha256(raw[field_name], field_name=field_name)
        _optional_sha256(raw["occurrence_sha256"], field_name="occurrence_sha256")
        for field_name in ("route_id", "endpoint_id", "endpoint_slug"):
            _safe_id(raw[field_name], field_name=field_name)
        response_state = _safe_id(raw["response_state"], field_name="response_state")
        if response_state not in _RESPONSE_STATES:
            _fail("stats-lossless response state is unsupported")
        for field_name in ("legacy_envelope_name", "result_set_name"):
            item_value = raw[field_name]
            if item_value is not None and (
                type(item_value) is not str
                or len(item_value) > 256
                or _SAFE_ID_RE.fullmatch(item_value) is None
            ):
                _fail(f"{field_name} must be one exact optional result name")
        _nonnegative(
            raw["global_record_ordinal"],
            field_name="global_record_ordinal",
            maximum=MAX_STATS_LOSSLESS_RECORDS - 1,
        )
        for field_name, maximum in (
            ("occurrence_record_ordinal", MAX_STATS_LOSSLESS_RECORDS - 1),
            ("response_record_ordinal", MAX_STATS_LOSSLESS_RECORDS - 1),
            ("result_set_occurrence", MAX_STATS_LOSSLESS_RESULTS - 1),
            ("provider_result_ordinal", MAX_STATS_LOSSLESS_RESULTS - 1),
            ("expected_result_ordinal", MAX_STATS_LOSSLESS_RESULTS - 1),
            ("canonical_result_ordinal", MAX_STATS_LOSSLESS_RESULTS - 1),
            ("header_ordinal", MAX_STATS_LOSSLESS_HEADERS - 1),
            ("row_ordinal", MAX_STATS_LOSSLESS_ROWS - 1),
            ("node_ordinal", _MAX_STATS_LOSSLESS_JSON_NODES - 1),
            ("parent_node_ordinal", _MAX_STATS_LOSSLESS_JSON_NODES - 1),
            ("depth", _MAX_STATS_LOSSLESS_DEPTH),
            ("object_key_ordinal", _MAX_STATS_LOSSLESS_JSON_NODES - 1),
            ("array_ordinal", _MAX_STATS_LOSSLESS_JSON_NODES - 1),
        ):
            _optional_nonnegative(raw[field_name], field_name=field_name, maximum=maximum)
        header_name = _optional_public_header(raw["header_name"])
        for field_name in ("json_path", "parent_json_path"):
            item_value = raw[field_name]
            if item_value is not None:
                if type(item_value) is not str or not item_value or len(item_value) > 4_096:
                    _fail(f"{field_name} must be bounded nonempty exact text")
                _canonical_bytes(item_value, maximum_bytes=MAX_STATS_LOSSLESS_CANONICAL_BYTES)
        object_key = raw["object_key"]
        if object_key is not None:
            if type(object_key) is not str or len(object_key) > 1_024:
                _fail("object_key must be one bounded exact public key")
            _reject_sensitive_public_key(object_key)
            _canonical_bytes(object_key, maximum_bytes=8_192)

        encoded = raw["canonical_json"]
        has_value = encoded is not None
        if has_value:
            if type(encoded) is not str:
                _fail("stats-lossless record canonical value must be exact text")
            if len(encoded) > MAX_STATS_LOSSLESS_CANONICAL_BYTES:
                _fail("stats-lossless record canonical value exceeds its pre-copy bound")
            encoded_bytes = encoded.encode("utf-8", errors="strict")
            if len(encoded_bytes) > MAX_STATS_LOSSLESS_CANONICAL_BYTES:
                _fail("stats-lossless record canonical value exceeds its pre-copy bound")
            cumulative_bytes += len(encoded_bytes)
            if cumulative_bytes > MAX_STATS_LOSSLESS_TOTAL_CANONICAL_BYTES:
                _fail("stats-lossless record rows exceed their cumulative byte bound")
            decoded_value = _canonical_value(
                encoded,
                label="stats-lossless record canonical value",
            )
            canonical_sha = _sha256(
                raw["canonical_json_sha256"],
                field_name="canonical_json_sha256",
            )
            value_kind = _exact_literal(
                raw["value_kind"], allowed=_VALUE_KINDS, field_name="value_kind"
            )
            presence_kind = _exact_literal(
                raw["presence_kind"], allowed=_PRESENCE_KINDS, field_name="presence_kind"
            )
            if (
                canonical_sha != _sha256_bytes(encoded_bytes)
                or value_kind != _json_value_kind(decoded_value)
                or presence_kind != _json_presence_kind(decoded_value)
            ):
                _fail("stats-lossless record value tags or digest are invalid")
        else:
            decoded_value = None
            nonmaterialized_container = (
                owner_kind == "response_residual"
                and record_kind == "json_node"
                and raw["value_kind"] in {"array", "object"}
                and raw["presence_kind"] == "present"
            )
            if raw["canonical_json_sha256"] is not None or (
                not nonmaterialized_container
                and (raw["value_kind"] is not None or raw["presence_kind"] is not None)
            ):
                _fail("stats-lossless non-value record contains value metadata")

        node_values = (
            raw["node_ordinal"],
            raw["parent_node_ordinal"],
            raw["json_path"],
            raw["parent_json_path"],
            raw["depth"],
            raw["object_key"],
            raw["object_key_ordinal"],
            raw["array_ordinal"],
        )
        result_values = (
            raw["result_set_name"],
            raw["result_set_occurrence"],
            raw["provider_result_ordinal"],
            raw["expected_result_ordinal"],
            raw["canonical_result_ordinal"],
            header_name,
            raw["header_ordinal"],
            raw["row_ordinal"],
        )
        if owner_kind == "result_occurrence":
            if (
                raw["occurrence_sha256"] is None
                or raw["occurrence_record_ordinal"] is None
                or raw["response_record_ordinal"] is not None
                or record_kind in {"response", "json_node"}
                or raw["result_set_name"] is None
                or raw["result_set_occurrence"] is None
                or any(item is not None for item in node_values)
            ):
                _fail("stats-lossless occurrence-owned record shape is invalid")
        elif (
            raw["occurrence_sha256"] is not None
            or raw["occurrence_record_ordinal"] is not None
            or raw["response_record_ordinal"] is None
            or record_kind not in {"response", "json_node"}
            or any(item is not None for item in result_values)
        ):
            _fail("stats-lossless response-residual record shape is invalid")

        if record_kind == "response":
            if any(item is not None for item in node_values) or has_value:
                _fail("stats-lossless response marker contains node or value material")
        elif record_kind == "json_node":
            if (
                raw["node_ordinal"] is None
                or raw["json_path"] is None
                or raw["depth"] is None
                or raw["value_kind"] is None
                or raw["presence_kind"] is None
            ):
                _fail("stats-lossless residual JSON node omits its exact identity")
            if raw["parent_node_ordinal"] is None:
                if (
                    raw["node_ordinal"] != 0
                    or raw["json_path"] != "$"
                    or raw["parent_json_path"] is not None
                    or raw["depth"] != 0
                    or raw["object_key"] is not None
                    or raw["object_key_ordinal"] is not None
                    or raw["array_ordinal"] is not None
                ):
                    _fail("stats-lossless residual JSON root is invalid")
            elif (
                cast("int", raw["parent_node_ordinal"]) >= cast("int", raw["node_ordinal"])
                or raw["parent_json_path"] is None
                or cast("int", raw["depth"]) < 1
                or (
                    raw["object_key"] is not None
                    and (raw["object_key_ordinal"] is None or raw["array_ordinal"] is not None)
                )
                or (
                    raw["object_key"] is None
                    and (raw["object_key_ordinal"] is not None or raw["array_ordinal"] is None)
                )
            ):
                _fail("stats-lossless residual JSON child identity is invalid")
        elif record_kind in {"result_set", "missing_expected", "raw_headers", "raw_rows"}:
            if (
                any(
                    item is not None
                    for item in (header_name, raw["header_ordinal"], raw["row_ordinal"])
                )
                or not has_value
            ):
                _fail("stats-lossless declaration/container record shape is invalid")
        elif record_kind == "header":
            if (
                raw["provider_result_ordinal"] is None
                or raw["header_ordinal"] is None
                or raw["row_ordinal"] is not None
                or not has_value
            ):
                _fail("stats-lossless header record shape is invalid")
        elif record_kind == "row":
            if (
                raw["provider_result_ordinal"] is None
                or header_name is not None
                or raw["header_ordinal"] is not None
                or raw["row_ordinal"] is None
                or not has_value
            ):
                _fail("stats-lossless row record shape is invalid")
        elif (
            raw["provider_result_ordinal"] is None
            or raw["header_ordinal"] is None
            or raw["row_ordinal"] is None
            or not has_value
        ):
            _fail("stats-lossless cell record shape is invalid")

        if owner_kind == "result_occurrence" and record_kind == "missing_expected":
            if (
                raw["provider_result_ordinal"] is not None
                or raw["canonical_result_ordinal"] is None
            ):
                _fail("stats-lossless missing declaration identity is invalid")
        elif owner_kind == "result_occurrence" and record_kind in {"raw_headers", "raw_rows"}:
            if raw["provider_result_ordinal"] is None and raw["canonical_result_ordinal"] is None:
                _fail("stats-lossless missing container omits canonical identity")
        elif owner_kind == "result_occurrence" and raw["provider_result_ordinal"] is None:
            _fail("stats-lossless present record omits its provider result ordinal")

        global_anomalies = _canonical_codes(
            raw["global_anomaly_codes_json"],
            raw["global_anomaly_codes_sha256"],
            label="global anomaly codes",
            allowed=_GLOBAL_ANOMALIES,
            allow_empty=False,
        )
        if _canonical_hash(_source_row_payload(raw)) != raw["source_row_sha256"]:
            _fail("stats-lossless record source-row digest is invalid")
        identity = {
            "schema_version": PUBLIC_VALUE_AUTHORITY_SCHEMA_VERSION,
            "kind": "raw_nba_api_stats_lossless_record_v1",
            **{
                column: raw[column]
                for column in STATS_LOSSLESS_RECORD_COLUMNS[1:]
                if column != "record_sha256"
            },
        }
        if _canonical_hash(identity) != raw["record_sha256"]:
            _fail("stats-lossless record identity digest is invalid")
        records.append(_RecordRow(dict(raw), decoded_value, global_anomalies))
    if not records:
        _fail("stats-lossless record relation is empty")
    if tuple(record.global_record_ordinal for record in records) != tuple(range(len(records))):
        _fail("stats-lossless global record ordinals are not exact and contiguous")
    if len({cast("str", record.record_sha256) for record in records}) != len(records):
        _fail("stats-lossless record relation contains duplicate identities")
    return records


def _load_source_rows(value: object) -> list[dict[str, object]]:
    rows = _exact_sequence(
        value,
        label="stats-lossless public source rows",
        maximum=MAX_STATS_LOSSLESS_RECORDS,
    )
    result: list[dict[str, object]] = []
    cumulative_bytes = 0
    for item in rows:
        row = _exact_row(
            item,
            columns=STATS_LOSSLESS_SOURCE_COLUMNS,
            label="stats-lossless public source row",
        )
        encoded = row["canonical_json"]
        if encoded is not None:
            if type(encoded) is not str:
                _fail("stats-lossless public source canonical value must be exact text")
            if len(encoded) > MAX_STATS_LOSSLESS_CANONICAL_BYTES:
                _fail("stats-lossless public source value exceeds its pre-copy bound")
            encoded_bytes = encoded.encode("utf-8", errors="strict")
            if len(encoded_bytes) > MAX_STATS_LOSSLESS_CANONICAL_BYTES:
                _fail("stats-lossless public source value exceeds its pre-copy bound")
            cumulative_bytes += len(encoded_bytes)
            if cumulative_bytes > MAX_STATS_LOSSLESS_TOTAL_CANONICAL_BYTES:
                _fail("stats-lossless public source rows exceed their cumulative byte bound")
            _canonical_value(encoded, label="stats-lossless public source canonical value")
        anomaly_json = row["anomaly_codes_json"]
        if type(anomaly_json) is not str:
            _fail("stats-lossless public source anomaly codes must be exact text")
        _canonical_array(
            anomaly_json,
            label="stats-lossless public source anomaly codes",
            maximum=len(_GLOBAL_ANOMALIES),
        )
        if row["header_name"] is not None:
            _public_header(row["header_name"], allow_empty=True)
        _canonical_bytes(row, maximum_bytes=MAX_STATS_LOSSLESS_CANONICAL_BYTES)
        result.append(row)
    return result


def _load_stats_bindings(
    *,
    route: Mapping[str, object],
    public_sources: Sequence[dict[str, object]],
) -> list[dict[str, object]]:
    raw_bindings = _exact_sequence(
        route["stats_bindings"],
        label="conditional stats bindings",
        maximum=MAX_STATS_LOSSLESS_RECORDS,
    )
    if len(raw_bindings) != len(public_sources):
        _fail("conditional stats binding denominator differs from public source rows")
    bindings_by_ordinal: dict[int, dict[str, object]] = {}
    observation_records = cast("Sequence[str]", route["observation_record_sha256s"])
    occurrence_ids = set(cast("Sequence[str]", route["result_occurrence_sha256s"]))
    body_object_ids = set(cast("Sequence[str]", route["body_object_sha256s"]))
    observed_binding_kinds: set[str] = set()
    for item in raw_bindings:
        binding = _exact_row(
            item,
            columns=_STATS_BINDING_COLUMNS,
            label="conditional stats binding",
        )
        for field_name in ("binding_id", "route_id", "staging_key", "record_kind"):
            _safe_id(binding[field_name], field_name=field_name)
        binding_kind = _exact_literal(
            binding["binding_kind"],
            allowed=frozenset({"selected_result_bound", "body_node_bound"}),
            field_name="binding_kind",
        )
        observed_binding_kinds.add(binding_kind)
        ordinal = _nonnegative(
            binding["staging_row_ordinal"],
            field_name="staging_row_ordinal",
            maximum=MAX_STATS_LOSSLESS_RECORDS - 1,
        )
        if ordinal in bindings_by_ordinal:
            _fail("conditional stats bindings duplicate a staging row ordinal")
        for field_name in (
            "observation_record_sha256",
            "observation_sha256",
            "response_receipt_sha256",
            "row_identity_sha256",
            "binding_evidence_sha256",
        ):
            _sha256(binding[field_name], field_name=field_name)
        source_occurrence_sha256 = _optional_sha256(
            binding["source_occurrence_sha256"], field_name="source_occurrence_sha256"
        )
        body_object_sha256 = _optional_sha256(
            binding["body_object_sha256"], field_name="body_object_sha256"
        )
        if binding_kind == "selected_result_bound":
            if source_occurrence_sha256 not in occurrence_ids or body_object_sha256 is not None:
                _fail("selected-result stats binding has invalid source ownership")
        elif source_occurrence_sha256 is not None or body_object_sha256 not in body_object_ids:
            _fail("body-node stats binding has invalid source ownership")
        for field_name in (
            "result_set_name",
            "header_name",
            "json_path",
            "parent_json_path",
            "object_key",
        ):
            item_value = binding[field_name]
            if item_value is not None:
                if field_name == "header_name":
                    _public_header(item_value, allow_empty=True)
                elif type(item_value) is not str:
                    _fail("conditional stats binding optional text has a foreign type")
        for field_name in (
            "result_set_occurrence",
            "provider_index",
            "canonical_index",
            "header_ordinal",
            "row_ordinal",
            "node_ordinal",
            "parent_node_ordinal",
            "depth",
            "object_key_ordinal",
            "array_ordinal",
        ):
            _optional_nonnegative(
                binding[field_name],
                field_name=field_name,
                maximum=MAX_STATS_LOSSLESS_RECORDS,
            )
        selectors = _exact_sequence(
            binding["selector_columns"],
            label="conditional stats selector columns",
            maximum=len(STATS_LOSSLESS_SOURCE_COLUMNS),
        )
        if any(type(item_value) is not str for item_value in selectors):
            _fail("conditional stats selector columns contain a foreign key")
        selector_names = tuple(cast("Sequence[str]", selectors))
        if selector_names != tuple(sorted(set(selector_names))) or any(
            name not in STATS_LOSSLESS_SOURCE_COLUMNS for name in selector_names
        ):
            _fail("conditional stats selector columns are not canonical")

        row_identity = _canonical_value(
            binding["row_identity_json"],
            label="conditional stats row identity",
        )
        source = public_sources[ordinal] if ordinal < len(public_sources) else None
        if (
            source is None
            or type(row_identity) is not dict
            or tuple(cast("dict[object, object]", row_identity))
            != tuple(sorted(STATS_LOSSLESS_SOURCE_COLUMNS))
        ):
            _fail("conditional stats binding row identity is not one exact source row")
        exact_identity = cast("dict[str, object]", row_identity)
        identity_bytes = _canonical_bytes(
            exact_identity,
            maximum_bytes=MAX_STATS_LOSSLESS_CANONICAL_BYTES,
        )
        source_bytes = _canonical_bytes(
            source,
            maximum_bytes=MAX_STATS_LOSSLESS_CANONICAL_BYTES,
        )
        expected_selectors = tuple(
            sorted(key for key, item_value in source.items() if item_value is not None)
        )
        if (
            identity_bytes != source_bytes
            or _sha256_bytes(identity_bytes) != binding["row_identity_sha256"]
            or selector_names != expected_selectors
            or binding["route_id"] != route["route_id"]
            or binding["staging_key"] != _LOSSLESS_STAGING_KEY
            or binding["observation_record_sha256"] not in observation_records
            or binding["response_receipt_sha256"] != source["response_receipt_sha256"]
            or binding["record_kind"] != source["record_kind"]
            or binding["result_set_name"] != source["result_set_name"]
            or binding["result_set_occurrence"] != source["result_set_occurrence"]
            or binding["provider_index"] != source["provider_index"]
            or binding["canonical_index"] != source["canonical_index"]
            or binding["header_name"] != source["header_name"]
            or binding["header_ordinal"] != source["header_ordinal"]
            or binding["row_ordinal"] != source["row_ordinal"]
            or binding["node_ordinal"] != source["node_ordinal"]
            or binding["parent_node_ordinal"] != source["parent_node_ordinal"]
            or binding["json_path"] != source["json_path"]
            or binding["parent_json_path"] != source["parent_json_path"]
            or binding["depth"] != source["depth"]
            or binding["object_key"] != source["object_key"]
            or binding["object_key_ordinal"] != source["object_key_ordinal"]
            or binding["array_ordinal"] != source["array_ordinal"]
        ):
            _fail("conditional stats binding differs from its exact public source row")
        evidence = {
            column: binding[column]
            for column in _STATS_BINDING_COLUMNS
            if column != "binding_evidence_sha256"
        }
        if _canonical_hash(evidence) != binding["binding_evidence_sha256"]:
            _fail("conditional stats binding evidence digest is invalid")
        bindings_by_ordinal[ordinal] = dict(binding)
    if tuple(sorted(bindings_by_ordinal)) != tuple(range(len(public_sources))):
        _fail("conditional stats bindings are not contiguous")
    source_shape = cast("str", route["source_shape"])
    expected_binding_kinds = {
        "selected_result_bound": {"selected_result_bound"},
        "body_node_bound": {"body_node_bound"},
        "hybrid_result_body_bound": {"selected_result_bound", "body_node_bound"},
    }[source_shape]
    if observed_binding_kinds != expected_binding_kinds:
        _fail("conditional stats binding kinds differ from the route source shape")
    return [bindings_by_ordinal[index] for index in range(len(public_sources))]


def _result_declaration(record: _RecordRow) -> dict[str, object]:
    if type(record.decoded_value) is not dict:
        _fail("stats-lossless result declaration must be one exact object")
    raw = cast("dict[object, object]", record.decoded_value)
    if any(type(key) is not str for key in raw) or tuple(raw) != _RESULT_DECLARATION_COLUMNS:
        _fail("stats-lossless result declaration has foreign or unordered fields")
    declaration = cast("dict[str, object]", record.decoded_value)
    _exact_literal(
        declaration["presence"],
        allowed=frozenset({"present", "present_empty", "missing"}),
        field_name="result declaration presence",
    )
    expected_value = declaration["expected_headers"]
    if expected_value is not None:
        expected_sequence = _exact_sequence(
            expected_value,
            label="result declaration expected headers",
            maximum=MAX_STATS_LOSSLESS_HEADERS,
        )
        if any(type(item_value) is not str or not item_value for item_value in expected_sequence):
            _fail("result declaration expected headers are invalid")
        for header in cast("Sequence[str]", expected_sequence):
            _public_header(header, allow_empty=False)
    anomalies_value = _exact_sequence(
        declaration["anomaly_codes"],
        label="result declaration anomalies",
        maximum=len(_PER_RESULT_ANOMALIES),
    )
    if any(
        type(item_value) is not str or item_value not in _PER_RESULT_ANOMALIES
        for item_value in anomalies_value
    ):
        _fail("result declaration contains an unsupported anomaly")
    anomalies = tuple(cast("Sequence[str]", anomalies_value))
    if anomalies != tuple(sorted(set(anomalies))):
        _fail("result declaration anomalies are not canonical")
    for field_name, maximum in (
        ("header_record_count", MAX_STATS_LOSSLESS_HEADERS),
        ("raw_row_occurrence_count", MAX_STATS_LOSSLESS_ROWS),
        ("sequence_row_count", MAX_STATS_LOSSLESS_ROWS),
        ("raw_cell_count", MAX_STATS_LOSSLESS_CELLS),
    ):
        _nonnegative(declaration[field_name], field_name=field_name, maximum=maximum)
    _sha256(
        declaration["normalized_output_sha256"],
        field_name="normalized_output_sha256",
    )
    if declaration["presence"] == "missing" and (
        expected_value is None
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
        _fail("stats-lossless missing declaration is inconsistent")
    return declaration


def _assert_record(
    record: _RecordRow,
    *,
    kind: str,
    header_name: str | None = None,
    header_ordinal: int | None = None,
    row_ordinal: int | None = None,
    value: object,
) -> None:
    if (
        record.record_kind != kind
        or record.header_name != header_name
        or record.header_ordinal != header_ordinal
        or record.row_ordinal != row_ordinal
        or _canonical_bytes(
            record.decoded_value,
            maximum_bytes=MAX_STATS_LOSSLESS_CANONICAL_BYTES,
        )
        != _canonical_bytes(value, maximum_bytes=MAX_STATS_LOSSLESS_CANONICAL_BYTES)
    ):
        _fail("stats-lossless public record differs from its reconstructed value")


def _result_identity_values(
    *,
    result_ordinal: int,
    occurrence: Mapping[str, object],
    records: tuple[_RecordRow, ...],
    declaration: Mapping[str, object],
    raw_headers: object,
    raw_rows: object,
    route: Mapping[str, object],
) -> dict[str, object]:
    declaration_record = records[0]
    expected_headers_value = declaration["expected_headers"]
    expected_headers_bytes = (
        None
        if expected_headers_value is None
        else _canonical_bytes(
            expected_headers_value,
            maximum_bytes=MAX_STATS_LOSSLESS_CANONICAL_BYTES,
        )
    )
    raw_headers_bytes = _canonical_bytes(
        raw_headers,
        maximum_bytes=MAX_STATS_LOSSLESS_CANONICAL_BYTES,
    )
    raw_rows_bytes = _canonical_bytes(
        raw_rows,
        maximum_bytes=MAX_STATS_LOSSLESS_CANONICAL_BYTES,
    )
    anomaly_bytes = _canonical_bytes(
        declaration["anomaly_codes"],
        maximum_bytes=MAX_STATS_LOSSLESS_CANONICAL_BYTES,
    )
    return {
        "representation_kind": STATS_LOSSLESS_REPRESENTATION_KIND,
        "raw_authority_bundle_sha256": route["raw_bundle_sha256"],
        "observation_record_sha256": declaration_record.observation_record_sha256,
        "observation_sha256": declaration_record.observation_sha256,
        "occurrence_sha256": declaration_record.occurrence_sha256,
        "route_id": route["route_id"],
        "route_authority_sha256": route["authority_sha256"],
        "committed_receipt_sha256": route["committed_receipt_root_sha256"],
        "response_receipt_sha256": route["response_receipt_sha256"],
        "result_ordinal": result_ordinal,
        "result_set_name": declaration_record.result_set_name,
        "result_set_occurrence": declaration_record.result_set_occurrence,
        "provider_result_ordinal": declaration_record.provider_result_ordinal,
        "expected_result_ordinal": declaration_record.expected_result_ordinal,
        "canonical_result_ordinal": declaration_record.canonical_result_ordinal,
        "occurrence_canonical_result_ordinal": occurrence["canonical_result_ordinal"],
        "presence": declaration["presence"],
        "expected_headers_sha256": (
            None if expected_headers_bytes is None else _sha256_bytes(expected_headers_bytes)
        ),
        "raw_headers_sha256": _sha256_bytes(raw_headers_bytes),
        "raw_rows_sha256": _sha256_bytes(raw_rows_bytes),
        "raw_header_container_kind": _json_value_kind(raw_headers),
        "raw_row_container_kind": _json_value_kind(raw_rows),
        "header_record_count": declaration["header_record_count"],
        "raw_row_occurrence_count": declaration["raw_row_occurrence_count"],
        "sequence_row_count": declaration["sequence_row_count"],
        "raw_cell_count": declaration["raw_cell_count"],
        "anomaly_codes_sha256": _sha256_bytes(anomaly_bytes),
        "normalized_output_sha256": declaration["normalized_output_sha256"],
        "first_global_record_ordinal": records[0].global_record_ordinal,
        "record_count": len(records),
        "record_inventory_sha256": _canonical_root(
            kind="stats_lossless_result_record_inventory_v1",
            count=len(records),
            values=(record.record_sha256 for record in records),
        ),
        "source_rows_sha256": _canonical_root(
            kind="stats_lossless_result_source_rows_v1",
            count=len(records),
            values=(record.source_row_sha256 for record in records),
        ),
    }


def _same_canonical_value(left: object, right: object) -> bool:
    return _canonical_bytes(
        left, maximum_bytes=MAX_STATS_LOSSLESS_CANONICAL_BYTES
    ) == _canonical_bytes(right, maximum_bytes=MAX_STATS_LOSSLESS_CANONICAL_BYTES)


def _json_path_for_tokens(tokens: Sequence[str | int]) -> str:
    path = "$"
    for token in tokens:
        if type(token) is int:
            path += f"[{token}]"
        else:
            encoded = _canonical_bytes(token, maximum_bytes=4_096).decode("utf-8")
            path += f"[{encoded}]"
    return path


def _reconstruct_response_residual(records: tuple[_RecordRow, ...]) -> object | None:
    if not records:
        return None
    if len(records) < 2 or records[0].record_kind != "response":
        _fail("stats-lossless response residual omits its response marker or JSON root")
    if tuple(record.response_record_ordinal for record in records) != tuple(range(len(records))):
        _fail("stats-lossless response-residual ordinals are not contiguous")
    if any(record.owner_kind != "response_residual" for record in records):
        _fail("stats-lossless response residual contains an occurrence-owned record")
    node_records = records[1:]
    if any(record.record_kind != "json_node" for record in node_records) or tuple(
        record.node_ordinal for record in node_records
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
            value = record.decoded_value
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
        if record.value_kind != _json_value_kind(
            value
        ) or record.presence_kind != _json_presence_kind(value):
            _fail("stats-lossless response residual node tags differ from its subtree")
        if record.canonical_json is None:
            if type(value) not in {dict, list} or not cast(
                "dict[object, object] | list[object]", value
            ):
                _fail("stats-lossless response residual omitted an empty container value")
        elif not _same_canonical_value(record.decoded_value, value):
            _fail("stats-lossless response residual canonical node value drifted")
    root = values[0]
    if _canonical_hash(root) != records[0].canonical_payload_sha256:
        _fail("stats-lossless response residual differs from its canonical payload")
    return root


def _reconstruct_results(
    *,
    route: Mapping[str, object],
    occurrences: Sequence[dict[str, object]],
    records: Sequence[_RecordRow],
) -> tuple[list[_ResultReceipt], tuple[_RecordRow, ...]]:
    if tuple(
        _nonnegative(
            occurrence["occurrence_ordinal"],
            field_name="occurrence_ordinal",
            maximum=MAX_STATS_LOSSLESS_RESULTS - 1,
        )
        for occurrence in occurrences
    ) != tuple(range(len(occurrences))):
        _fail("raw result occurrence ordinals are not exact and contiguous")

    results: list[_ResultReceipt] = []
    cursor = 0
    for result_ordinal, occurrence in enumerate(occurrences):
        occurrence_sha256 = cast("str", occurrence["occurrence_sha256"])
        start = cursor
        while cursor < len(records) and records[cursor].occurrence_sha256 == occurrence_sha256:
            cursor += 1
        partition = tuple(records[start:cursor])
        if len(partition) < 3:
            _fail("stats-lossless occurrence omits declaration or raw-container records")
        if tuple(record.occurrence_record_ordinal for record in partition) != tuple(
            range(len(partition))
        ):
            _fail("stats-lossless occurrence-local record ordinals are not contiguous")

        declaration_record = partition[0]
        declaration = _result_declaration(declaration_record)
        presence = cast("str", declaration["presence"])
        declaration_kind = "missing_expected" if presence == "missing" else "result_set"
        if declaration_record.record_kind != declaration_kind:
            _fail("stats-lossless declaration kind differs from its presence")
        raw_headers_record = partition[1]
        raw_rows_record = partition[2]
        if (
            raw_headers_record.record_kind != "raw_headers"
            or raw_rows_record.record_kind != "raw_rows"
        ):
            _fail("stats-lossless occurrence raw containers are not in exact order")
        raw_headers = raw_headers_record.decoded_value
        raw_rows = raw_rows_record.decoded_value
        expected_headers = (
            None
            if declaration["expected_headers"] is None
            else tuple(cast("list[str]", declaration["expected_headers"]))
        )
        header_names, header_values = _observed_header_details(raw_headers)
        anomalies = (
            ()
            if presence == "missing"
            else _per_result_anomalies(
                expected_headers=expected_headers,
                raw_headers=raw_headers,
                observed_header_names=header_names,
                raw_rows=raw_rows,
            )
        )
        if tuple(cast("list[str]", declaration["anomaly_codes"])) != anomalies:
            _fail("stats-lossless declaration anomalies differ from raw containers")

        if presence == "missing":
            if expected_headers is None or raw_headers != list(expected_headers) or raw_rows != []:
                _fail("stats-lossless missing raw containers differ from expected headers")
            output_sha256 = _canonical_hash({"headers": list(expected_headers), "rows": []})
            ordered_headers: tuple[str, ...] = ()
            row_count = raw_row_occurrence_count = sequence_row_count = raw_cell_count = 0
            header_record_count = 0
        else:
            row_occurrences = raw_rows if type(raw_rows) is list else []
            sequence_rows = [
                row for row in cast("list[object]", row_occurrences) if type(row) is list
            ]
            row_count = len(row_occurrences)
            raw_row_occurrence_count = len(row_occurrences)
            sequence_row_count = len(sequence_rows)
            raw_cell_count = sum(len(cast("list[object]", row)) for row in sequence_rows)
            header_record_count = len(header_values)
            expected_presence = "present" if row_count else "present_empty"
            if presence != expected_presence:
                _fail("stats-lossless declaration presence differs from raw rows")
            output_sha256 = _canonical_hash(
                {"headers": raw_headers, "rows": raw_rows, "anomalies": list(anomalies)}
            )
            ordered_headers = (
                cast("tuple[str, ...]", header_names)
                if all(type(name) is str and bool(name) for name in header_names)
                else ()
            )
        if (
            declaration["normalized_output_sha256"] != output_sha256
            or declaration["header_record_count"] != header_record_count
            or declaration["raw_row_occurrence_count"] != raw_row_occurrence_count
            or declaration["sequence_row_count"] != sequence_row_count
            or declaration["raw_cell_count"] != raw_cell_count
        ):
            _fail("stats-lossless declaration counts or output digest drifted")

        for record in partition:
            if (
                record.raw_authority_bundle_sha256 != route["raw_bundle_sha256"]
                or record.observation_record_sha256
                not in cast("Sequence[str]", route["observation_record_sha256s"])
                or record.observation_sha256 != occurrence["observation_sha256"]
                or record.occurrence_sha256 != occurrence_sha256
                or record.route_id != route["route_id"]
                or record.route_authority_sha256 != route["authority_sha256"]
                or record.committed_receipt_sha256 != route["committed_receipt_root_sha256"]
                or record.response_receipt_sha256 != route["response_receipt_sha256"]
                or record.endpoint_slug != route["endpoint_name"]
                or record.result_set_name != declaration_record.result_set_name
                or record.result_set_occurrence != declaration_record.result_set_occurrence
                or record.provider_result_ordinal != declaration_record.provider_result_ordinal
                or record.expected_result_ordinal != declaration_record.expected_result_ordinal
                or record.canonical_result_ordinal != declaration_record.canonical_result_ordinal
                or record.global_record_ordinal != start + record.occurrence_record_ordinal
            ):
                _fail("stats-lossless record was rebound from its occurrence or route")

        expected_cursor = 3
        if presence != "missing":
            for header_ordinal, header_value in enumerate(header_values):
                if expected_cursor >= len(partition):
                    _fail("stats-lossless header record partition ended early")
                expected_header_name = (
                    header_names[header_ordinal] if header_ordinal < len(header_names) else None
                )
                _assert_record(
                    partition[expected_cursor],
                    kind="header",
                    header_name=expected_header_name,
                    header_ordinal=header_ordinal,
                    value=header_value,
                )
                expected_cursor += 1
            if type(raw_rows) is list:
                for row_ordinal, raw_row in enumerate(cast("list[object]", raw_rows)):
                    if expected_cursor >= len(partition):
                        _fail("stats-lossless row record partition ended early")
                    _assert_record(
                        partition[expected_cursor],
                        kind="row",
                        row_ordinal=row_ordinal,
                        value=raw_row,
                    )
                    expected_cursor += 1
                    if type(raw_row) is list:
                        for header_ordinal, cell in enumerate(cast("list[object]", raw_row)):
                            if expected_cursor >= len(partition):
                                _fail("stats-lossless cell record partition ended early")
                            _assert_record(
                                partition[expected_cursor],
                                kind="cell",
                                header_name=(
                                    header_names[header_ordinal]
                                    if header_ordinal < len(header_names)
                                    else None
                                ),
                                header_ordinal=header_ordinal,
                                row_ordinal=row_ordinal,
                                value=cell,
                            )
                            expected_cursor += 1
        if expected_cursor != len(partition):
            _fail("stats-lossless occurrence record partition contains extra rows")

        occurrence_headers = _canonical_text_array(
            occurrence["ordered_headers_json"],
            occurrence["ordered_headers_sha256"],
            label="ordered result headers",
            maximum=MAX_STATS_LOSSLESS_HEADERS,
            safe_headers=True,
        )
        if (
            occurrence["result_name"] != declaration_record.result_set_name
            or occurrence["duplicate_name_ordinal"] != declaration_record.result_set_occurrence
            or occurrence["provider_result_ordinal"] != declaration_record.provider_result_ordinal
            or occurrence["canonical_result_ordinal"] is not None
            or occurrence["presence"] != presence
            or occurrence_headers != ordered_headers
            or occurrence["header_count"] != len(ordered_headers)
            or occurrence["row_count"] != row_count
            or occurrence["cell_count"] != len(ordered_headers) * row_count
            or occurrence["output_sha256"] != output_sha256
        ):
            _fail("stats-lossless records do not close the exact Raw Authority V2 occurrence")
        route_ids = _canonical_text_array(
            occurrence["canonical_route_ids_json"],
            occurrence["canonical_route_ids_sha256"],
            label="canonical result route IDs",
            maximum=MAX_STATS_LOSSLESS_RESULTS,
        )
        receipt_rows = _canonical_array(
            occurrence["committed_staging_receipts_json"],
            label="committed staging receipts",
            maximum=MAX_STATS_LOSSLESS_RESULTS,
        )
        committed_by_route: dict[str, str] = {}
        for receipt_item in receipt_rows:
            receipt = _exact_row(
                receipt_item,
                columns=("receipt_sha256", "route_id"),
                label="committed staging receipt row",
            )
            route_id_value = _safe_id(receipt["route_id"], field_name="receipt route_id")
            committed_by_route[route_id_value] = _sha256(
                receipt["receipt_sha256"],
                field_name="receipt_sha256",
            )
        route_id = cast("str", route["route_id"])
        if (
            route_id not in route_ids
            or committed_by_route.get(route_id) != route["committed_receipt_root_sha256"]
        ):
            _fail("stats-lossless occurrence lacks exact committed route membership")

        values = _result_identity_values(
            result_ordinal=result_ordinal,
            occurrence=occurrence,
            records=partition,
            declaration=declaration,
            raw_headers=raw_headers,
            raw_rows=raw_rows,
            route=route,
        )
        result_sha256 = _canonical_hash(
            {
                "schema_version": PUBLIC_VALUE_AUTHORITY_SCHEMA_VERSION,
                "kind": "raw_nba_api_stats_lossless_result_v1",
                **values,
            }
        )
        results.append(
            _ResultReceipt(
                {"result_sha256": result_sha256, **values},
                expected_headers,
                raw_headers,
                raw_rows,
                anomalies,
                partition,
                cast("str", occurrence["landing_disposition"]),
            )
        )
    response_residual = tuple(records[cursor:])
    _reconstruct_response_residual(response_residual)
    return results, response_residual


def _verify_stats_lossless_public_tables(
    *,
    expected_raw_authority_bundle_sha256: object,
    expected_route_authority_sha256: object,
    route_authority_row: object,
    occurrence_rows: object,
    source_rows: object,
    record_rows: object,
) -> StatsLosslessValueAuthorityReceiptV1:
    """Independently close the singular public stats-lossless record relation.

    Values come only from actual conditional staging rows and the singular
    raw_nba_api_stats_lossless_record relation. Raw Authority V2 occurrence rows
    and the conditional route row are admitted public composition inputs.
    """

    raw_bundle_sha256 = _sha256(
        expected_raw_authority_bundle_sha256,
        field_name="expected_raw_authority_bundle_sha256",
    )
    route_authority_sha256 = _sha256(
        expected_route_authority_sha256,
        field_name="expected_route_authority_sha256",
    )
    route = _route_authority_row(
        route_authority_row,
        expected_raw_bundle_sha256=raw_bundle_sha256,
        expected_route_authority_sha256=route_authority_sha256,
    )
    raw_occurrences = _exact_sequence(
        occurrence_rows,
        label="raw result occurrence public rows",
        maximum=MAX_STATS_LOSSLESS_RESULTS,
    )
    occurrences = [_raw_occurrence_row(item) for item in raw_occurrences]
    occurrence_sha256s = [cast("str", row["occurrence_sha256"]) for row in occurrences]
    if len(set(occurrence_sha256s)) != len(occurrence_sha256s) or tuple(
        sorted(occurrence_sha256s)
    ) != tuple(cast("Sequence[str]", route["result_occurrence_sha256s"])):
        _fail("raw result occurrence rows differ from exact conditional route membership")

    public_sources = _load_source_rows(source_rows)
    records = _load_records(record_rows)
    if len(public_sources) != len(records):
        _fail("public source and record relation denominators differ")
    response_metadata = (
        records[0].response_mode_authority_sha256,
        records[0].parser_input_sha256,
        records[0].canonical_payload_sha256,
        records[0].response_state,
        records[0].legacy_envelope_name,
    )
    if any(
        (
            record.response_mode_authority_sha256,
            record.parser_input_sha256,
            record.canonical_payload_sha256,
            record.response_state,
            record.legacy_envelope_name,
        )
        != response_metadata
        for record in records
    ):
        _fail("stats-lossless records span multiple response authorities")
    bindings = _load_stats_bindings(route=route, public_sources=public_sources)
    for ordinal, (source, record, binding) in enumerate(
        zip(public_sources, records, bindings, strict=True)
    ):
        source_bytes = _canonical_bytes(source, maximum_bytes=MAX_STATS_LOSSLESS_CANONICAL_BYTES)
        if (
            record.global_record_ordinal != ordinal
            or source_bytes
            != _canonical_bytes(
                record.source_row(),
                maximum_bytes=MAX_STATS_LOSSLESS_CANONICAL_BYTES,
            )
            or _sha256_bytes(source_bytes) != record.source_row_sha256
            or binding["source_occurrence_sha256"] != record.occurrence_sha256
            or binding["observation_record_sha256"] != record.observation_record_sha256
            or binding["observation_sha256"] != record.observation_sha256
            or (
                binding["binding_kind"] == "selected_result_bound"
                and record.owner_kind != "result_occurrence"
            )
            or (
                binding["binding_kind"] == "body_node_bound"
                and record.owner_kind != "response_residual"
            )
            or record.raw_authority_bundle_sha256 != raw_bundle_sha256
            or record.route_id != route["route_id"]
            or record.route_authority_sha256 != route_authority_sha256
            or record.committed_receipt_sha256 != route["committed_receipt_root_sha256"]
            or record.response_receipt_sha256 != route["response_receipt_sha256"]
            or record.provider_authority_sha256 != route["provider_authority_sha256"]
            or record.endpoint_contract_sha256 != route["endpoint_contract_sha256"]
            or record.parameters_sha256 != route["committed_logical_parameters_sha256"]
            or record.endpoint_id != route["endpoint_name"]
            or record.endpoint_slug != route["endpoint_name"]
        ):
            _fail("public source row, binding, and record sidecar do not close")

    results, response_residual_records = _reconstruct_results(
        route=route,
        occurrences=occurrences,
        records=records,
    )
    expected_by_ordinal: dict[int, tuple[str, tuple[str, ...]]] = {}
    for result in results:
        expected_ordinal = result.expected_result_ordinal
        expected_headers = result.expected_headers
        if expected_ordinal is None:
            if expected_headers is not None:
                _fail("additive result unexpectedly declares pinned headers")
            continue
        if expected_headers is None:
            _fail("pinned result omits exact expected headers")
        candidate = (cast("str", result.result_set_name), expected_headers)
        previous = expected_by_ordinal.setdefault(cast("int", expected_ordinal), candidate)
        if previous != candidate:
            _fail("pinned result ordinal was rebound across declarations")
    if (not expected_by_ordinal and not response_residual_records) or tuple(
        sorted(expected_by_ordinal)
    ) != tuple(range(len(expected_by_ordinal))):
        _fail("expected-result denominator is incomplete or noncontiguous")
    expected_results = tuple(
        expected_by_ordinal[index] for index in range(len(expected_by_ordinal))
    )
    expected_names = tuple(name for name, _headers in expected_results)
    if len(set(expected_names)) != len(expected_names):
        _fail("pinned result names are duplicated")
    expected_name_to_ordinal = {name: ordinal for ordinal, name in enumerate(expected_names)}

    provider_results = [result for result in results if result.provider_result_ordinal is not None]
    missing_results = [result for result in results if result.provider_result_ordinal is None]
    if results != provider_results + missing_results or tuple(
        result.provider_result_ordinal for result in provider_results
    ) != tuple(range(len(provider_results))):
        _fail("stats-lossless results are not in provider-then-missing canonical order")
    provider_names = tuple(cast("str", result.result_set_name) for result in provider_results)
    provider_name_counts = Counter(provider_names)
    duplicate_ordinals: Counter[str] = Counter()
    for result in provider_results:
        result_name = cast("str", result.result_set_name)
        expected_duplicate = duplicate_ordinals[result_name]
        duplicate_ordinals[result_name] += 1
        expected_ordinal = expected_name_to_ordinal.get(result_name)
        expected_headers = (
            None if expected_ordinal is None else expected_results[expected_ordinal][1]
        )
        canonical_ordinal = (
            expected_ordinal
            if expected_ordinal is not None and provider_name_counts[result_name] == 1
            else None
        )
        if (
            result.result_set_occurrence != expected_duplicate
            or result.expected_result_ordinal != expected_ordinal
            or result.expected_headers != expected_headers
            or result.canonical_result_ordinal != canonical_ordinal
        ):
            _fail("provider result identity differs from its pinned denominator")
    expected_missing = tuple(
        (ordinal, name, headers)
        for ordinal, (name, headers) in enumerate(expected_results)
        if provider_name_counts[name] == 0
    )
    if len(missing_results) != len(expected_missing):
        _fail("missing-result denominator is incomplete")
    for result, (ordinal, name, headers) in zip(
        missing_results,
        expected_missing,
        strict=True,
    ):
        if (
            result.result_set_name != name
            or result.result_set_occurrence != 0
            or result.expected_result_ordinal != ordinal
            or result.canonical_result_ordinal != ordinal
            or result.expected_headers != headers
            or result.presence != "missing"
        ):
            _fail("missing result differs from its pinned denominator")

    global_reasons: set[str] = set()
    if Counter(provider_names) - Counter(expected_names):
        global_reasons.add("additive_result_set")
    if Counter(expected_names) - Counter(provider_names):
        global_reasons.add("missing_result_set")
    if any(count > 1 for count in provider_name_counts.values()):
        global_reasons.add("duplicate_result_set_name")
    for result in results:
        global_reasons.update(result.anomaly_codes)
        if result.landing_disposition == "wide_plus_lossless":
            result_name = cast("str", result.result_set_name)
            if not (
                result.anomaly_codes
                or result.expected_result_ordinal is None
                or provider_name_counts[result_name] > 1
                or result.presence == "missing"
                or response_residual_records
            ):
                _fail("wide_plus_lossless occurrence lacks reconstructed lossless drift")
    if response_residual_records:
        global_reasons.add("unknown_dynamic_response")
    if not global_reasons:
        if any(result.landing_disposition == "wide_plus_lossless" for result in results):
            _fail("wide_plus_lossless authority cannot rely on an invented fallback reason")
        global_reasons.add("unrepresentable_typed_frame")
    global_anomalies = tuple(sorted(global_reasons))
    global_anomaly_bytes = _canonical_bytes(
        list(global_anomalies),
        maximum_bytes=MAX_STATS_LOSSLESS_CANONICAL_BYTES,
    )
    for record in records:
        if record.decoded_global_anomalies != global_anomalies:
            _fail("record global anomaly authority differs from reconstructed drift")

    observation_values = {cast("str", record.observation_sha256) for record in records}
    if len(observation_values) != 1:
        _fail("stats-lossless occurrences span multiple observations")
    observation_sha256 = next(iter(observation_values))
    observation_records = cast("Sequence[str]", route["observation_record_sha256s"])
    if len(observation_records) != 1:
        _fail("stats-lossless route does not bind one observation record")

    occurrence_inventory_sha256 = _canonical_root(
        kind="stats_lossless_occurrence_inventory_v1",
        count=len(results),
        values=(result.occurrence_sha256 for result in results),
    )
    result_inventory_sha256 = _canonical_root(
        kind="stats_lossless_result_inventory_v1",
        count=len(results),
        values=(result.result_sha256 for result in results),
    )
    response_residual_records_sha256 = _canonical_root(
        kind="stats_lossless_response_residual_records_v1",
        count=len(response_residual_records),
        values=(record.record_sha256 for record in response_residual_records),
    )
    record_inventory_sha256 = _canonical_root(
        kind="stats_lossless_record_inventory_v1",
        count=len(records),
        values=(record.record_sha256 for record in records),
    )
    source_rows_sha256 = _canonical_root(
        kind="stats_lossless_source_rows_v1",
        count=len(records),
        values=(record.source_row_sha256 for record in records),
    )
    manifest_values: dict[str, object] = {
        "representation_kind": STATS_LOSSLESS_REPRESENTATION_KIND,
        "record_schema_sha256": STATS_LOSSLESS_RECORD_SCHEMA_SHA256,
        "source_schema_sha256": STATS_LOSSLESS_SOURCE_SCHEMA_SHA256,
        "raw_authority_bundle_sha256": raw_bundle_sha256,
        "observation_record_sha256": observation_records[0],
        "observation_sha256": observation_sha256,
        "route_id": route["route_id"],
        "route_authority_sha256": route_authority_sha256,
        "committed_receipt_sha256": route["committed_receipt_root_sha256"],
        "response_receipt_sha256": route["response_receipt_sha256"],
        "endpoint_id": route["endpoint_name"],
        "endpoint_slug": route["endpoint_name"],
        "provider_authority_sha256": route["provider_authority_sha256"],
        "endpoint_contract_sha256": route["endpoint_contract_sha256"],
        "parameters_sha256": route["committed_logical_parameters_sha256"],
        "global_anomaly_codes_sha256": _sha256_bytes(global_anomaly_bytes),
        "provider_result_set_count": len(provider_results),
        "expected_result_set_count": len(expected_results),
        "occurrence_count": len(results),
        "occurrence_inventory_sha256": occurrence_inventory_sha256,
        "result_count": len(results),
        "result_inventory_sha256": result_inventory_sha256,
        "response_residual_record_count": len(response_residual_records),
        "response_residual_records_sha256": response_residual_records_sha256,
        "record_count": len(records),
        "record_inventory_sha256": record_inventory_sha256,
        "source_rows_sha256": source_rows_sha256,
    }
    manifest_sha256 = _canonical_hash(
        {
            "schema_version": PUBLIC_VALUE_AUTHORITY_SCHEMA_VERSION,
            "kind": "raw_nba_api_stats_lossless_manifest_v1",
            **manifest_values,
        }
    )
    receipt_values: dict[str, object] = {
        "manifest_sha256": manifest_sha256,
        **{name: value for name, value in manifest_values.items() if name != "representation_kind"},
    }
    authority_sha256 = _canonical_hash(
        {
            "schema_version": PUBLIC_VALUE_AUTHORITY_SCHEMA_VERSION,
            "kind": "stats_lossless_value_authority_receipt_v1",
            **receipt_values,
        }
    )
    try:
        return StatsLosslessValueAuthorityReceiptV1(
            authority_sha256=authority_sha256,
            manifest_sha256=manifest_sha256,
            record_schema_sha256=STATS_LOSSLESS_RECORD_SCHEMA_SHA256,
            source_schema_sha256=STATS_LOSSLESS_SOURCE_SCHEMA_SHA256,
            raw_authority_bundle_sha256=raw_bundle_sha256,
            observation_record_sha256=observation_records[0],
            observation_sha256=observation_sha256,
            route_id=cast("str", route["route_id"]),
            route_authority_sha256=route_authority_sha256,
            committed_receipt_sha256=cast("str", route["committed_receipt_root_sha256"]),
            response_receipt_sha256=cast("str", route["response_receipt_sha256"]),
            endpoint_id=cast("str", route["endpoint_name"]),
            endpoint_slug=cast("str", route["endpoint_name"]),
            provider_authority_sha256=cast("str", route["provider_authority_sha256"]),
            endpoint_contract_sha256=cast("str", route["endpoint_contract_sha256"]),
            parameters_sha256=cast("str", route["committed_logical_parameters_sha256"]),
            global_anomaly_codes_sha256=_sha256_bytes(global_anomaly_bytes),
            provider_result_set_count=len(provider_results),
            expected_result_set_count=len(expected_results),
            occurrence_count=len(results),
            occurrence_inventory_sha256=occurrence_inventory_sha256,
            result_count=len(results),
            result_inventory_sha256=result_inventory_sha256,
            response_residual_record_count=len(response_residual_records),
            response_residual_records_sha256=response_residual_records_sha256,
            record_count=len(records),
            record_inventory_sha256=record_inventory_sha256,
            source_rows_sha256=source_rows_sha256,
        )
    except (TypeError, ValueError) as exc:
        raise IndependentStatsLosslessTableVerifierError(
            "independent stats-lossless receipt materialization failed"
        ) from exc


def verify_stats_lossless_public_tables(
    *,
    expected_raw_authority_bundle_sha256: object,
    expected_route_authority_sha256: object,
    route_authority_row: object,
    occurrence_rows: object,
    source_rows: object,
    record_rows: object,
) -> StatsLosslessValueAuthorityReceiptV1:
    """Normalize recursion failures at the complete independent-verifier boundary."""

    try:
        return _verify_stats_lossless_public_tables(
            expected_raw_authority_bundle_sha256=expected_raw_authority_bundle_sha256,
            expected_route_authority_sha256=expected_route_authority_sha256,
            route_authority_row=route_authority_row,
            occurrence_rows=occurrence_rows,
            source_rows=source_rows,
            record_rows=record_rows,
        )
    except IndependentStatsLosslessTableVerifierError:
        raise
    except RecursionError:
        raise IndependentStatsLosslessTableVerifierError(
            "independent stats-lossless verification exceeded its recursion bound"
        ) from None
