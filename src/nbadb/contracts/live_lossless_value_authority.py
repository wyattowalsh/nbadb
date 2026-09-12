"""Public value authority for recursively lossless NBA Live responses.

The physical public surface is exactly one ordered relation,
``raw_nba_api_live_lossless_node``.  Result declarations, concrete result
occurrences, JSON nodes, and declared field cells use a closed ``record_kind``
discriminator.  Parser bytes are used only while constructing this authority;
they are never carried by a row or receipt.
"""

from __future__ import annotations

import hashlib
import json
import math
import re
from dataclasses import dataclass, fields
from datetime import UTC, datetime
from typing import TYPE_CHECKING, ClassVar, Final, Literal, Never, Self, cast

from nbadb.contracts.public_value_types import (
    MAX_PUBLIC_VALUE_EXPECTED_UNITS,
    PUBLIC_VALUE_AUTHORITY_SCHEMA_VERSION,
    ExpectedValueUnitInventoryV1,
    ExpectedValueUnitKindV1,
    ExpectedValueUnitV1,
    PublicValueRepresentationKindV1,
    PublicValueTypesError,
    ValueRepresentationAssignmentV1,
)

if TYPE_CHECKING:
    from collections.abc import Iterable, Mapping, Sequence
    from typing import Any

__all__ = [
    "LIVE_LOSSLESS_NODE_COLUMNS",
    "LIVE_LOSSLESS_NODE_SCHEMA_SHA256",
    "LIVE_LOSSLESS_REPRESENTATION_KIND",
    "LIVE_LOSSLESS_SOURCE_INPUT_KIND",
    "LIVE_RESPONSE_RESIDUAL_REPRESENTATION_KIND",
    "LIVE_LOSSLESS_VALUE_AUTHORITY_KIND",
    "MAX_LIVE_LOSSLESS_CANONICAL_BYTES",
    "MAX_LIVE_LOSSLESS_ANOMALY_BYTES",
    "MAX_LIVE_LOSSLESS_HEADER_COUNT",
    "MAX_LIVE_LOSSLESS_DEPTH",
    "MAX_LIVE_LOSSLESS_FIELD_CELLS",
    "MAX_LIVE_LOSSLESS_JSON_NODES",
    "MAX_LIVE_LOSSLESS_JSON_PATH_BYTES",
    "MAX_LIVE_LOSSLESS_NODES",
    "MAX_LIVE_LOSSLESS_OBSERVATIONS",
    "MAX_LIVE_LOSSLESS_RECORDS",
    "MAX_LIVE_LOSSLESS_RESULT_OCCURRENCES",
    "MAX_LIVE_LOSSLESS_RESULTS",
    "MAX_LIVE_LOSSLESS_TOTAL_CANONICAL_BYTES",
    "PUBLIC_VALUE_AUTHORITY_SCHEMA_VERSION",
    "LiveLosslessNodeRecordV1",
    "LiveLosslessValueAuthorityError",
    "LiveLosslessValueAuthorityReceiptV1",
    "LiveLosslessValueAuthorityV1",
    "LIVE_LOSSLESS_TEXT_COLUMNS",
    "build_live_lossless_value_authority",
    "canonical_json_bytes",
    "canonical_ordered_root_sha256",
    "canonical_sha256",
]

LIVE_LOSSLESS_REPRESENTATION_KIND: Final = "live_lossless_nodes_v1"
LIVE_RESPONSE_RESIDUAL_REPRESENTATION_KIND: Final = "response_lossless_records_v1"
LIVE_LOSSLESS_SOURCE_INPUT_KIND: Final = "parser_input_body"
LIVE_LOSSLESS_VALUE_AUTHORITY_KIND: Final = "live_lossless_value_authority_receipt_v1"
LIVE_LOSSLESS_ORDERED_ROOT_CONTRACT: Final = "sha256-length-framed-ordered-root-v1"

MAX_LIVE_LOSSLESS_OBSERVATIONS: Final = 100_000
MAX_LIVE_LOSSLESS_RESULTS: Final = 64
MAX_LIVE_LOSSLESS_RESULT_OCCURRENCES: Final = 2_000_000
MAX_LIVE_LOSSLESS_NODES: Final = 2_000_000
MAX_LIVE_LOSSLESS_FIELD_CELLS: Final = 10_000_000
MAX_LIVE_LOSSLESS_RECORDS: Final = 14_000_000
MAX_LIVE_LOSSLESS_DEPTH: Final = 64
MAX_LIVE_LOSSLESS_CANONICAL_BYTES: Final = 64 * 1024 * 1024
MAX_LIVE_LOSSLESS_TOTAL_CANONICAL_BYTES: Final = 256 * 1024 * 1024
MAX_LIVE_LOSSLESS_JSON_NODES: Final = 2_000_000
MAX_LIVE_LOSSLESS_INTEGER_ABS: Final = (1 << 63) - 1
MAX_LIVE_LOSSLESS_ANOMALY_BYTES: Final = 4_096
MAX_LIVE_LOSSLESS_HEADER_COUNT: Final = 1_024
MAX_LIVE_LOSSLESS_JSON_PATH_BYTES: Final = 4_096

LiveLosslessRecordKind = Literal[
    "result_declaration",
    "result_occurrence",
    "node",
    "field_cell",
]
LiveLosslessOwnershipKind = Literal["result_occurrence", "response_residual"]

_RECORD_KIND_ORDER: Final = (
    "result_declaration",
    "result_occurrence",
    "node",
    "field_cell",
)
_RECORD_KINDS = frozenset(_RECORD_KIND_ORDER)
_PRESENCE_KINDS = frozenset(
    {
        "present",
        "null",
        "empty_object",
        "empty_array",
        "missing",
        "mixed_absent",
        "not_observed_parent_empty",
    }
)
_VALUE_KINDS = frozenset(
    {"object", "array", "null", "boolean", "integer", "number", "string", "missing"}
)
_RESULT_PRESENCES = frozenset(
    {"present", "empty_array", "missing", "null", "mixed_absent", "not_observed_parent_empty"}
)
_NODE_PRESENCES = frozenset({"present", "null", "empty_object", "empty_array", "missing"})
_CONTAINER_KINDS = frozenset({"nba_api_live_json_array", "nba_api_live_json_object"})
_KEY_PRESENCES = frozenset({"required", "optional", "optional_or_undocumented"})
_DECODER_ANOMALY_CODES = frozenset(
    {"additive_envelope_root", "reordered_envelope_root", "additive_field"}
)
_RESULT_KEYS = frozenset(
    {
        "container_count",
        "container_kind",
        "field_cell_count",
        "ordered_headers",
        "headers_sha256",
        "json_path",
        "missing_count",
        "name",
        "normalized_output_sha256",
        "null_count",
        "observed_field_orders_sha256",
        "ordinal",
        "parent_field_name",
        "parent_observation_count",
        "parent_result_set_name",
        "parent_occurrence_states_sha256",
        "presence",
        "result_occurrence_count",
        "row_count",
        "value_cell_count",
        "result_set_sha256",
    }
)
_OCCURRENCE_KEYS = frozenset(
    {
        "container_kind",
        "global_ordinal",
        "json_path",
        "node_ordinal",
        "occurrence_ordinal",
        "parent_result_set_name",
        "parent_result_set_ordinal",
        "presence_kind",
        "result_set_name",
        "result_set_ordinal",
        "row_count",
        "value_sha256",
        "occurrence_sha256",
    }
)
_NODE_KEYS = frozenset(
    {
        "array_ordinal",
        "canonical_json",
        "container_kind",
        "contract_field_ordinal",
        "contract_json_path",
        "depth",
        "json_path",
        "known_contract_field",
        "node_ordinal",
        "object_key",
        "object_key_ordinal",
        "parent_json_path",
        "parent_node_ordinal",
        "presence_kind",
        "result_set_name",
        "result_set_occurrence",
        "result_set_ordinal",
        "result_set_row_ordinal",
        "value_kind",
        "value_sha256",
        "node_sha256",
    }
)
_CELL_KEYS = frozenset(
    {
        "cell_ordinal",
        "canonical_json",
        "concrete_json_path",
        "context_result_set_name",
        "context_result_set_occurrence",
        "context_result_set_ordinal",
        "field_json_path",
        "field_name",
        "field_ordinal",
        "key_presence",
        "node_ordinal",
        "owner_result_set_name",
        "owner_result_set_occurrence",
        "owner_result_set_ordinal",
        "owner_row_ordinal",
        "presence_kind",
        "value_kind",
        "value_sha256",
        "cell_sha256",
    }
)
_SHA256_RE = re.compile(r"[0-9a-f]{64}\Z")
_SAFE_ID_RE = re.compile(r"[A-Za-z0-9_][A-Za-z0-9_.:-]{0,511}\Z")
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
    r"authorization\s*:\s*(?:bearer|basic)\s+[A-Za-z0-9._~+/=-]{8,}",
    flags=re.ASCII | re.IGNORECASE,
)
_BEARER_SECRET_RE = re.compile(
    r"bearer\s+[A-Za-z0-9._~+/=-]{20,}(?![A-Za-z0-9._~+/=-])",
    flags=re.ASCII | re.IGNORECASE,
)
_BASIC_SECRET_RE = re.compile(
    r"basic\s+[A-Za-z0-9+/=]{12,}(?![A-Za-z0-9+/=])",
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


class LiveLosslessValueAuthorityError(ValueError):
    """One live-lossless public record or receipt is invalid."""


def _fail(message: str) -> Never:
    raise LiveLosslessValueAuthorityError(message)


def _sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _normalized_public_key(value: str) -> str:
    separated = _CAMEL_ACRONYM_BOUNDARY_RE.sub(r"\1_\2", value)
    separated = _CAMEL_WORD_BOUNDARY_RE.sub(r"\1_\2", separated)
    return _KEY_SEPARATOR_RE.sub("_", separated).strip("_").lower()


def _reject_public_text(value: str, *, key: bool = False) -> None:
    normalized = _normalized_public_key(value)
    if key and (
        _SENSITIVE_OBJECT_KEY_RE.fullmatch(normalized) is not None
        or any(
            component in _GENERIC_SENSITIVE_KEY_COMPONENTS for component in normalized.split("_")
        )
    ):
        _fail("live-lossless public value contains secret-shaped material")
    stripped = value.strip()
    if (
        _AUTHORIZATION_HEADER_SECRET_RE.search(stripped) is not None
        or _BEARER_SECRET_RE.search(stripped) is not None
        or _BASIC_SECRET_RE.search(stripped) is not None
        or _LOCAL_PATH_VALUE_RE.search(value) is not None
        or any(pattern.search(value) is not None for pattern in _EMBEDDED_SECRET_RES)
    ):
        _fail("live-lossless public value contains secret-shaped material")


def _validate_json_graph(value: object, *, maximum_bytes: int) -> None:
    nodes = 0
    estimated_bytes = 0
    stack: list[tuple[object, int]] = [(value, 0)]
    while stack:
        item, depth = stack.pop()
        nodes += 1
        if nodes > MAX_LIVE_LOSSLESS_JSON_NODES or depth > MAX_LIVE_LOSSLESS_DEPTH:
            _fail("live-lossless JSON exceeds its node or depth bound")
        if item is None:
            estimated_bytes += 4
        elif type(item) is bool:
            estimated_bytes += 5
        elif type(item) is int:
            if abs(item) > MAX_LIVE_LOSSLESS_INTEGER_ABS:
                _fail("live-lossless JSON integer exceeds its exact bound")
            estimated_bytes += len(str(item))
        elif type(item) is float:
            if not math.isfinite(item):
                _fail("live-lossless JSON contains a non-finite number")
            estimated_bytes += 32
        elif type(item) is str:
            try:
                encoded = item.encode("utf-8", errors="strict")
            except UnicodeEncodeError:
                raise LiveLosslessValueAuthorityError(
                    "live-lossless JSON contains invalid Unicode"
                ) from None
            estimated_bytes += len(encoded)
            _reject_public_text(item)
        elif type(item) is list:
            estimated_bytes += 2
            stack.extend((child, depth + 1) for child in reversed(item))
        elif type(item) is dict:
            estimated_bytes += 2
            for key, child in reversed(tuple(item.items())):
                if type(key) is not str:
                    _fail("live-lossless JSON object key is not an exact string")
                _reject_public_text(key, key=True)
                try:
                    estimated_bytes += len(key.encode("utf-8", errors="strict"))
                except UnicodeEncodeError:
                    raise LiveLosslessValueAuthorityError(
                        "live-lossless JSON key contains invalid Unicode"
                    ) from None
                stack.append((child, depth + 1))
        else:
            _fail("live-lossless JSON contains a foreign value type")
        if estimated_bytes > maximum_bytes:
            _fail("live-lossless JSON exceeds its canonical byte bound")


def canonical_json_bytes(value: object, *, maximum_bytes: int) -> bytes:
    """Encode bounded public-safe JSON using the exact canonical contract."""

    if type(maximum_bytes) is not int or maximum_bytes < 1:
        _fail("live-lossless canonical byte limit is invalid")
    _validate_json_graph(value, maximum_bytes=maximum_bytes)
    try:
        encoded = json.dumps(
            value,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
            allow_nan=False,
        ).encode("utf-8", errors="strict")
    except (TypeError, ValueError, UnicodeEncodeError, RecursionError):
        raise LiveLosslessValueAuthorityError(
            "live-lossless value is not bounded canonical JSON"
        ) from None
    if len(encoded) > maximum_bytes:
        _fail("live-lossless canonical bytes exceed their bound")
    return encoded


def canonical_sha256(value: object) -> str:
    return _sha256_bytes(
        canonical_json_bytes(value, maximum_bytes=MAX_LIVE_LOSSLESS_CANONICAL_BYTES)
    )


def _exact_sha256(value: object, *, field_name: str) -> str:
    if type(value) is not str or _SHA256_RE.fullmatch(value) is None:
        _fail(f"{field_name} must be an exact lowercase SHA-256")
    return value


def _exact_nonnegative(value: object, *, field_name: str, maximum: int) -> int:
    if type(value) is not int or value < 0 or value > maximum:
        _fail(f"{field_name} is outside its exact nonnegative bound")
    return value


def _safe_id(value: object, *, field_name: str) -> str:
    if type(value) is not str or _SAFE_ID_RE.fullmatch(value) is None:
        _fail(f"{field_name} is not an exact public identifier")
    _reject_public_text(value)
    return value


def _canonical_timestamp(value: object, *, field_name: str) -> str:
    if type(value) is not str:
        _fail(f"{field_name} must be an exact canonical UTC timestamp")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        raise LiveLosslessValueAuthorityError(
            f"{field_name} must be an exact canonical UTC timestamp"
        ) from None
    if parsed.tzinfo is not UTC:
        _fail(f"{field_name} must be an exact canonical UTC timestamp")
    expected = parsed.isoformat(timespec="microseconds").replace("+00:00", "Z")
    if value != expected:
        _fail(f"{field_name} must be an exact canonical UTC timestamp")
    return value


def _exact_model_storage(
    value: object,
    *,
    expected_type: type[object],
    label: str,
) -> dict[str, object]:
    """Read one exact Pydantic model without invoking caller methods."""

    if type(value) is not expected_type:
        _fail(f"{label} has a foreign exact DTO type")
    storage = object.__getattribute__(value, "__dict__")
    if type(storage) is not dict:
        _fail(f"{label} has foreign model storage")
    model_fields = type.__getattribute__(expected_type, "model_fields")
    if type(model_fields) is not dict:
        _fail(f"{label} has foreign model field authority")
    exact = cast("dict[object, object]", storage)
    if any(type(key) is not str for key in exact) or tuple(exact) != tuple(model_fields):
        _fail(f"{label} does not have its exact ordered model fields")
    return cast("dict[str, object]", storage)


def _preflight_trusted_utc_datetime(
    value: object,
    *,
    label: str,
    optional: bool = False,
) -> None:
    """Reject foreign timezone callbacks before any datetime operation."""

    if value is None and optional:
        return
    if type(value) is not datetime:
        _fail(f"{label} is not an exact trusted UTC datetime")
    timezone = object.__getattribute__(value, "tzinfo")
    fold = object.__getattribute__(value, "fold")
    if timezone is not UTC or type(fold) is not int or fold != 0:
        _fail(f"{label} is not an exact trusted UTC datetime")


def _preflight_exact_builtin_graph(value: object, *, label: str) -> None:
    """Reject nested callbacks before model serialization/equality/hash work."""

    stack = [value]
    nodes = 0
    while stack:
        item = stack.pop()
        nodes += 1
        if nodes > MAX_LIVE_LOSSLESS_JSON_NODES:
            _fail(f"{label} exceeds its nested preflight bound")
        if type(item) is datetime:
            _preflight_trusted_utc_datetime(item, label=label)
            continue
        if type(item) in {type(None), bool, int, float, str, bytes}:
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


def _preflight_model_values(
    value: object,
    *,
    expected_type: type[object],
    label: str,
    nested_models: dict[str, tuple[type[object], str]] | None = None,
) -> None:
    storage = _exact_model_storage(value, expected_type=expected_type, label=label)
    children = {} if nested_models is None else nested_models
    for field_name, item in storage.items():
        nested = children.get(field_name)
        if nested is None:
            _preflight_exact_builtin_graph(item, label=label)
        else:
            _preflight_model_values(
                item,
                expected_type=nested[0],
                label=nested[1],
            )


def _preflight_raw_authority_bundle(value: object) -> None:
    """Preflight the entire Raw V2 graph before any Pydantic validator runs."""

    from nbadb.contracts.raw_request_authority import (
        ObservationRouteLandingV2,
        ParserInputObjectV2,
        RawRequestAuthorityBundleV2,
        RequestAttemptIdentityV2,
        RequestObservationV2,
        ResultOccurrenceV2,
    )
    from nbadb.contracts.raw_transport_contract import (
        LiveHttpTransportV1,
        StaticSnapshotTransportV1,
        StatsHttpTransportV1,
    )

    storage = _exact_model_storage(
        value,
        expected_type=RawRequestAuthorityBundleV2,
        label="live-lossless Raw Authority V2 bundle",
    )
    if type(storage["schema_version"]) is not int:
        _fail("live-lossless Raw Authority V2 schema version is foreign")
    _exact_sha256(storage["bundle_sha256"], field_name="raw_authority_bundle_sha256")
    contracts = (
        ("objects", ParserInputObjectV2),
        ("observations", RequestObservationV2),
        ("occurrences", ResultOccurrenceV2),
        ("landings", ObservationRouteLandingV2),
    )
    for field_name, expected_type in contracts:
        rows = storage[field_name]
        if type(rows) is not tuple or len(rows) > MAX_LIVE_LOSSLESS_RECORDS:
            _fail(f"live-lossless Raw Authority V2 {field_name} inventory is foreign or over bound")
        if any(type(item) is not expected_type for item in rows):
            _fail(f"live-lossless Raw Authority V2 {field_name} inventory contains a foreign DTO")

    for item in cast("tuple[object, ...]", storage["objects"]):
        _preflight_model_values(
            item,
            expected_type=ParserInputObjectV2,
            label="live-lossless parser-input object",
        )
    transport_types = {
        StatsHttpTransportV1,
        LiveHttpTransportV1,
        StaticSnapshotTransportV1,
    }
    for item in cast("tuple[object, ...]", storage["observations"]):
        observation = _exact_model_storage(
            item,
            expected_type=RequestObservationV2,
            label="live-lossless request observation",
        )
        _preflight_model_values(
            observation["attempt"],
            expected_type=RequestAttemptIdentityV2,
            label="live-lossless request attempt",
        )
        transport = observation["transport"]
        if type(transport) not in transport_types:
            _fail("live-lossless request observation has a foreign transport DTO")
        _preflight_model_values(
            transport,
            expected_type=type(transport),
            label="live-lossless request transport",
        )
        _preflight_trusted_utc_datetime(
            observation["started_at"],
            label="live-lossless request observation started timestamp",
        )
        _preflight_trusted_utc_datetime(
            observation["finished_at"],
            label="live-lossless request observation finished timestamp",
            optional=True,
        )
        for field_name, field_value in observation.items():
            if field_name not in {"attempt", "transport"}:
                _preflight_exact_builtin_graph(
                    field_value,
                    label="live-lossless request observation",
                )
    for item in cast("tuple[object, ...]", storage["occurrences"]):
        _preflight_model_values(
            item,
            expected_type=ResultOccurrenceV2,
            label="live-lossless result occurrence",
        )
    for item in cast("tuple[object, ...]", storage["landings"]):
        landing = _exact_model_storage(
            item,
            expected_type=ObservationRouteLandingV2,
            label="live-lossless route landing",
        )
        _preflight_trusted_utc_datetime(
            landing["live_snapshot_at"],
            label="live-lossless route landing snapshot timestamp",
            optional=True,
        )
        for field_value in landing.values():
            _preflight_exact_builtin_graph(
                field_value,
                label="live-lossless route landing",
            )


def canonical_ordered_root_sha256(
    *,
    kind: str,
    count: int,
    item_sha256s: Iterable[str],
) -> str:
    """Hash one bounded ordered digest inventory without materializing it."""

    _safe_id(kind, field_name="ordered root kind")
    _exact_nonnegative(count, field_name="ordered root count", maximum=MAX_LIVE_LOSSLESS_RECORDS)
    digest = hashlib.sha256()
    header = canonical_json_bytes(
        {
            "schema_version": PUBLIC_VALUE_AUTHORITY_SCHEMA_VERSION,
            "contract": LIVE_LOSSLESS_ORDERED_ROOT_CONTRACT,
            "kind": kind,
            "count": count,
        },
        maximum_bytes=4_096,
    )
    digest.update(len(header).to_bytes(8, "big"))
    digest.update(header)
    observed = 0
    for value in item_sha256s:
        _exact_sha256(value, field_name="ordered root item")
        observed += 1
        if observed > count:
            _fail("ordered root contains more items than its denominator")
        digest.update(bytes.fromhex(value))
    if observed != count:
        _fail("ordered root item count differs from its denominator")
    return digest.hexdigest()


def _preflight_json_text(raw: bytes, *, field_name: str) -> None:
    """Bound nesting and structural work before ``json.loads`` allocates."""

    depth = 0
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
            depth += 1
            nodes += 1
            if depth > MAX_LIVE_LOSSLESS_DEPTH:
                _fail(f"{field_name} exceeds its canonical depth bound")
        elif byte in {0x5D, 0x7D}:
            depth -= 1
            if depth < 0:
                _fail(f"{field_name} is not valid canonical JSON")
        elif byte == 0x2C:
            nodes += 1
        if nodes > MAX_LIVE_LOSSLESS_JSON_NODES:
            _fail(f"{field_name} exceeds its canonical node bound")
    if in_string or escaped or depth != 0:
        _fail(f"{field_name} is not valid canonical JSON")


def _bounded_json_integer(token: str) -> int:
    if len(token) > 64:
        _fail("live-lossless canonical JSON integer token exceeds its bound")
    try:
        value = int(token)
    except ValueError:
        raise LiveLosslessValueAuthorityError(
            "live-lossless canonical JSON integer token is invalid"
        ) from None
    if abs(value) > MAX_LIVE_LOSSLESS_INTEGER_ABS:
        _fail("live-lossless canonical JSON integer exceeds its bound")
    return value


def _bounded_json_float(token: str) -> float:
    if len(token) > 64:
        _fail("live-lossless canonical JSON number token exceeds its bound")
    try:
        value = float(token)
    except ValueError:
        raise LiveLosslessValueAuthorityError(
            "live-lossless canonical JSON number token is invalid"
        ) from None
    if not math.isfinite(value):
        _fail("live-lossless canonical JSON contains a non-finite number")
    return value


def _decode_canonical_json(
    value: object,
    *,
    field_name: str,
    require: type[list] | type[dict] | None,
    maximum_bytes: int = MAX_LIVE_LOSSLESS_CANONICAL_BYTES,
) -> object:
    if type(value) is not str:
        _fail(f"{field_name} is not exact canonical JSON text")
    try:
        raw = value.encode("utf-8", errors="strict")
    except UnicodeEncodeError:
        raise LiveLosslessValueAuthorityError(f"{field_name} is not valid UTF-8 JSON") from None
    if not raw or len(raw) > maximum_bytes:
        _fail(f"{field_name} exceeds its canonical byte bound")
    _preflight_json_text(raw, field_name=field_name)

    def reject_duplicates(pairs: list[tuple[str, object]]) -> dict[str, object]:
        result: dict[str, object] = {}
        for key, item in pairs:
            if key in result:
                _fail(f"{field_name} contains a duplicate object key")
            result[key] = item
        return result

    def reject_constant(_token: str) -> Never:
        _fail(f"{field_name} contains a non-finite number")

    try:
        decoded = json.loads(
            raw,
            object_pairs_hook=reject_duplicates,
            parse_int=_bounded_json_integer,
            parse_float=_bounded_json_float,
            parse_constant=reject_constant,
        )
    except LiveLosslessValueAuthorityError:
        raise
    except (UnicodeDecodeError, json.JSONDecodeError, RecursionError, TypeError, ValueError):
        raise LiveLosslessValueAuthorityError(f"{field_name} is not valid canonical JSON") from None
    if require is not None and type(decoded) is not require:
        _fail(f"{field_name} has the wrong canonical JSON container type")
    _validate_json_graph(decoded, maximum_bytes=maximum_bytes)
    if canonical_json_bytes(decoded, maximum_bytes=maximum_bytes) != raw:
        _fail(f"{field_name} is not canonical JSON")
    return decoded


def _decode_canonical_object(value: object, *, field_name: str) -> dict[str, object]:
    return cast(
        "dict[str, object]",
        _decode_canonical_json(value, field_name=field_name, require=dict),
    )


def _decode_canonical_array(value: object, *, field_name: str) -> list[object]:
    return cast(
        "list[object]",
        _decode_canonical_json(value, field_name=field_name, require=list),
    )


def _payload_int(
    payload: Mapping[str, object],
    name: str,
    *,
    maximum: int,
    optional: bool = False,
) -> int | None:
    value = payload[name]
    if value is None and optional:
        return None
    return _exact_nonnegative(value, field_name=f"payload {name}", maximum=maximum)


def _payload_text(
    payload: Mapping[str, object],
    name: str,
    *,
    optional: bool = False,
    safe_id: bool = False,
    key: bool = False,
) -> str | None:
    value = payload[name]
    if value is None and optional:
        return None
    if type(value) is not str or not value:
        _fail(f"payload {name} is not an exact nonempty string")
    if safe_id:
        _safe_id(value, field_name=f"payload {name}")
        if key:
            _reject_public_text(value, key=True)
    else:
        _reject_public_text(value, key=key)
    return value


def _validate_json_path(value: object, *, field_name: str, optional: bool = False) -> str | None:
    if value is None and optional:
        return None
    if type(value) is not str or not value.startswith("$"):
        _fail(f"{field_name} is not an exact live JSON path")
    try:
        raw = value.encode("utf-8", errors="strict")
    except UnicodeEncodeError:
        raise LiveLosslessValueAuthorityError(
            f"{field_name} is not a safe live JSON path"
        ) from None
    if len(raw) > MAX_LIVE_LOSSLESS_JSON_PATH_BYTES:
        _fail(f"{field_name} exceeds its live JSON path bound")
    _reject_public_text(value)
    return value


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
    _fail("live-lossless canonical value has a foreign JSON type")


def _validate_value_projection(
    *,
    presence: object,
    value_kind: object,
    canonical_json: object,
    label: str,
) -> object | None:
    if type(presence) is not str or presence not in _NODE_PRESENCES:
        _fail(f"{label} presence is invalid")
    if type(value_kind) is not str or value_kind not in _VALUE_KINDS:
        _fail(f"{label} value kind is invalid")
    if presence == "missing":
        if value_kind != "missing" or canonical_json is not None:
            _fail(f"{label} missing-value algebra is invalid")
        return None
    if presence == "null":
        expected = ("null", "null")
    elif presence == "empty_object":
        expected = ("object", "{}")
    elif presence == "empty_array":
        expected = ("array", "[]")
    else:
        expected = None
    if expected is not None:
        if (value_kind, canonical_json) != expected:
            _fail(f"{label} presence/value algebra is invalid")
        return _decode_canonical_json(
            canonical_json,
            field_name=f"{label} canonical_json",
            require=None,
        )
    if value_kind == "null":
        _fail(f"{label} present value cannot have null semantics")
    if value_kind in {"object", "array"}:
        if canonical_json is not None:
            _fail(f"{label} present-container canonical value must be omitted")
        return None
    decoded = _decode_canonical_json(
        canonical_json,
        field_name=f"{label} canonical_json",
        require=None,
    )
    if _json_value_kind(decoded) != value_kind:
        _fail(f"{label} canonical value differs from its declared kind")
    return decoded


def _validate_payload_contract(kind: str, payload: Mapping[str, object]) -> str:
    expected_keys = {
        "result_declaration": _RESULT_KEYS,
        "result_occurrence": _OCCURRENCE_KEYS,
        "node": _NODE_KEYS,
        "field_cell": _CELL_KEYS,
    }[kind]
    if set(payload) != expected_keys or any(type(key) is not str for key in payload):
        _fail("live-lossless payload fields are missing, additive, or foreign")
    digest_name = {
        "result_declaration": "result_set_sha256",
        "result_occurrence": "occurrence_sha256",
        "node": "node_sha256",
        "field_cell": "cell_sha256",
    }[kind]
    for name, value in payload.items():
        if name.endswith("_sha256"):
            _exact_sha256(value, field_name=f"payload {name}")

    if kind == "result_declaration":
        name = _payload_text(payload, "name", safe_id=True)
        ordinal = _payload_int(payload, "ordinal", maximum=MAX_LIVE_LOSSLESS_RESULTS - 1)
        container_kind = _payload_text(payload, "container_kind", safe_id=True)
        if container_kind not in _CONTAINER_KINDS:
            _fail("live-lossless result container kind is invalid")
        _validate_json_path(payload["json_path"], field_name="payload json_path")
        if not cast("str", payload["json_path"]).startswith("$."):
            _fail("live-lossless result declaration path is not decoder-exact")
        parent_name = _payload_text(payload, "parent_result_set_name", optional=True, safe_id=True)
        parent_field = _payload_text(payload, "parent_field_name", optional=True, safe_id=True)
        if (parent_name is None) != (parent_field is None):
            _fail("live-lossless result parent identity is partial")
        headers = payload["ordered_headers"]
        if (
            type(headers) is not list
            or len(headers) > MAX_LIVE_LOSSLESS_HEADER_COUNT
            or any(type(item) is not str or not item for item in headers)
            or len(set(cast("list[str]", headers))) != len(headers)
        ):
            _fail("live-lossless result headers are invalid or over bound")
        for header in cast("list[str]", headers):
            _safe_id(header, field_name="live-lossless result header")
            _reject_public_text(header, key=True)
        counts = {
            field: cast(
                "int",
                _payload_int(
                    payload,
                    field,
                    maximum=(
                        MAX_LIVE_LOSSLESS_FIELD_CELLS
                        if field in {"field_cell_count", "value_cell_count"}
                        else MAX_LIVE_LOSSLESS_NODES
                        if field == "row_count"
                        else MAX_LIVE_LOSSLESS_RESULT_OCCURRENCES
                    ),
                ),
            )
            for field in (
                "container_count",
                "field_cell_count",
                "missing_count",
                "null_count",
                "parent_observation_count",
                "result_occurrence_count",
                "row_count",
                "value_cell_count",
            )
        }
        if counts["value_cell_count"] != counts["row_count"] * len(headers):
            _fail("live-lossless result value-cell denominator is invalid")
        if counts["field_cell_count"] != counts["value_cell_count"]:
            _fail("live-lossless result field-cell denominator is invalid")
        if counts["result_occurrence_count"] != counts["parent_observation_count"]:
            _fail("live-lossless result occurrence denominator is invalid")
        if (
            counts["container_count"] + counts["missing_count"] + counts["null_count"]
            != counts["parent_observation_count"]
        ):
            _fail("live-lossless result parent-state denominator is invalid")
        if counts["container_count"] == 0:
            if counts["parent_observation_count"] == 0:
                expected_presence = "not_observed_parent_empty"
            elif counts["missing_count"] and counts["null_count"]:
                expected_presence = "mixed_absent"
            elif counts["missing_count"]:
                expected_presence = "missing"
            elif counts["null_count"]:
                expected_presence = "null"
            else:
                _fail("live-lossless absent result lacks an exact parent state")
        elif (
            container_kind == "nba_api_live_json_array"
            and counts["container_count"] == 1
            and counts["row_count"] == 0
            and counts["missing_count"] == 0
            and counts["null_count"] == 0
        ):
            expected_presence = "empty_array"
        else:
            expected_presence = "present"
        if type(payload["presence"]) is not str or payload["presence"] not in _RESULT_PRESENCES:
            _fail("live-lossless result presence is invalid")
        if payload["presence"] != expected_presence:
            _fail("live-lossless result presence differs from its denominators")
        if payload["headers_sha256"] != canonical_sha256(headers):
            _fail("live-lossless result header digest is invalid")
        del name, ordinal
    elif kind == "result_occurrence":
        for field, maximum in (
            ("global_ordinal", MAX_LIVE_LOSSLESS_RESULT_OCCURRENCES - 1),
            ("result_set_ordinal", MAX_LIVE_LOSSLESS_RESULTS - 1),
            ("occurrence_ordinal", MAX_LIVE_LOSSLESS_RESULT_OCCURRENCES - 1),
            ("node_ordinal", MAX_LIVE_LOSSLESS_NODES - 1),
            ("row_count", MAX_LIVE_LOSSLESS_NODES),
        ):
            _payload_int(payload, field, maximum=maximum)
        _payload_text(payload, "result_set_name", safe_id=True)
        parent_name = _payload_text(payload, "parent_result_set_name", optional=True, safe_id=True)
        parent_ordinal = _payload_int(
            payload,
            "parent_result_set_ordinal",
            maximum=MAX_LIVE_LOSSLESS_RESULTS - 1,
            optional=True,
        )
        if (parent_name is None) != (parent_ordinal is None):
            _fail("live-lossless occurrence parent identity is partial")
        container_kind = _payload_text(payload, "container_kind", safe_id=True)
        if container_kind not in _CONTAINER_KINDS:
            _fail("live-lossless occurrence container kind is invalid")
        _validate_json_path(payload["json_path"], field_name="payload json_path")
        presence = payload["presence_kind"]
        if type(presence) is not str or presence not in _NODE_PRESENCES:
            _fail("live-lossless occurrence presence is invalid")
        row_count = cast("int", payload["row_count"])
        if presence in {"missing", "null"} and row_count != 0:
            _fail("live-lossless absent occurrence carries rows")
        if presence == "empty_array" and (
            container_kind != "nba_api_live_json_array" or row_count != 0
        ):
            _fail("live-lossless empty-array occurrence algebra is invalid")
        if presence == "empty_object" and (
            container_kind != "nba_api_live_json_object" or row_count != 1
        ):
            _fail("live-lossless empty-object occurrence algebra is invalid")
        if presence == "present" and (
            (container_kind == "nba_api_live_json_array" and row_count == 0)
            or (container_kind == "nba_api_live_json_object" and row_count != 1)
        ):
            _fail("live-lossless present occurrence row algebra is invalid")
    elif kind == "node":
        _payload_int(payload, "node_ordinal", maximum=MAX_LIVE_LOSSLESS_NODES - 1)
        _payload_int(payload, "depth", maximum=MAX_LIVE_LOSSLESS_DEPTH)
        for field, maximum in (
            ("parent_node_ordinal", MAX_LIVE_LOSSLESS_NODES - 1),
            ("object_key_ordinal", MAX_LIVE_LOSSLESS_NODES - 1),
            ("array_ordinal", MAX_LIVE_LOSSLESS_NODES - 1),
            ("result_set_ordinal", MAX_LIVE_LOSSLESS_RESULTS - 1),
            ("result_set_occurrence", MAX_LIVE_LOSSLESS_RESULT_OCCURRENCES - 1),
            ("result_set_row_ordinal", MAX_LIVE_LOSSLESS_NODES - 1),
            ("contract_field_ordinal", MAX_LIVE_LOSSLESS_HEADER_COUNT - 1),
        ):
            _payload_int(payload, field, maximum=maximum, optional=True)
        _validate_json_path(payload["json_path"], field_name="payload json_path")
        _validate_json_path(
            payload["parent_json_path"], field_name="payload parent_json_path", optional=True
        )
        _validate_json_path(
            payload["contract_json_path"], field_name="payload contract_json_path", optional=True
        )
        _payload_text(payload, "object_key", optional=True, key=True)
        result_context = (
            _payload_text(payload, "result_set_name", optional=True, safe_id=True),
            payload["result_set_ordinal"],
            payload["result_set_occurrence"],
            payload["contract_json_path"],
        )
        if any(item is None for item in result_context) and any(
            item is not None for item in result_context
        ):
            _fail("live-lossless node result context is partial")
        object_key = payload["object_key"]
        object_ordinal = payload["object_key_ordinal"]
        array_ordinal = payload["array_ordinal"]
        if object_key is None and object_ordinal is not None:
            _fail("live-lossless node object edge is partial")
        if array_ordinal is not None and (object_key is not None or object_ordinal is not None):
            _fail("live-lossless node object/array edge ordinals overlap")
        known = payload["known_contract_field"]
        contract_ordinal = payload["contract_field_ordinal"]
        if known is not None and type(known) is not bool:
            _fail("live-lossless known-field flag is foreign")
        if (known is True) != (contract_ordinal is not None):
            _fail("live-lossless known-field ordinal algebra is invalid")
        container = payload["container_kind"]
        if container is not None and (
            type(container) is not str or container not in _CONTAINER_KINDS
        ):
            _fail("live-lossless node container kind is invalid")
        if container is not None and all(item is None for item in result_context):
            _fail("live-lossless matched node omits its result context")
        _validate_value_projection(
            presence=payload["presence_kind"],
            value_kind=payload["value_kind"],
            canonical_json=payload["canonical_json"],
            label="live-lossless node",
        )
    else:
        for field, maximum in (
            ("cell_ordinal", MAX_LIVE_LOSSLESS_FIELD_CELLS - 1),
            ("node_ordinal", MAX_LIVE_LOSSLESS_NODES - 1),
            ("owner_result_set_ordinal", MAX_LIVE_LOSSLESS_RESULTS - 1),
            ("owner_result_set_occurrence", MAX_LIVE_LOSSLESS_RESULT_OCCURRENCES - 1),
            ("owner_row_ordinal", MAX_LIVE_LOSSLESS_NODES - 1),
            ("context_result_set_ordinal", MAX_LIVE_LOSSLESS_RESULTS - 1),
            ("context_result_set_occurrence", MAX_LIVE_LOSSLESS_RESULT_OCCURRENCES - 1),
            ("field_ordinal", MAX_LIVE_LOSSLESS_HEADER_COUNT - 1),
        ):
            _payload_int(
                payload,
                field,
                maximum=maximum,
                optional=field == "owner_row_ordinal",
            )
        for field in (
            "owner_result_set_name",
            "context_result_set_name",
            "field_name",
        ):
            _payload_text(payload, field, safe_id=True, key=field == "field_name")
        _validate_json_path(payload["concrete_json_path"], field_name="payload concrete_json_path")
        _validate_json_path(payload["field_json_path"], field_name="payload field_json_path")
        if (
            type(payload["key_presence"]) is not str
            or payload["key_presence"] not in _KEY_PRESENCES
        ):
            _fail("live-lossless field key-presence policy is invalid")
        _validate_value_projection(
            presence=payload["presence_kind"],
            value_kind=payload["value_kind"],
            canonical_json=payload["canonical_json"],
            label="live-lossless field cell",
        )

    digest = _exact_sha256(payload[digest_name], field_name=f"payload {digest_name}")
    identity = {key: payload[key] for key in payload if key != digest_name}
    if digest != canonical_sha256(identity):
        _fail("live-lossless source item digest differs from its exact payload")
    return digest


def _identity_payload(record: LiveLosslessNodeRecordV1) -> dict[str, object]:
    return {
        "schema_version": record.schema_version,
        "kind": record.kind,
        **{
            item.name: getattr(record, item.name)
            for item in fields(record)
            if item.name != "record_sha256"
        },
    }


@dataclass(frozen=True, slots=True)
class LiveLosslessNodeRecordV1:
    """One row in the sole mandatory live-lossless public relation."""

    record_sha256: str
    source_input_kind: str
    representation_kind: str
    representation_assignment_sha256: str
    expected_unit_sha256: str
    expected_unit_ordinal: int
    ownership_kind: LiveLosslessOwnershipKind
    ownership_occurrence_ordinal: int | None
    response_residual_record_count: int
    response_residual_record_root_sha256: str
    raw_authority_bundle_sha256: str
    observation_record_sha256: str
    observation_sha256: str
    attempt_sha256: str
    semantic_request_sha256: str
    logical_invocation_sha256: str
    provider_call_sha256: str
    request_surface_sha256: str
    runtime_contract_sha256: str
    provider_authority_sha256: str
    endpoint_contract_sha256: str
    parser_input_sha256: str
    parser_input_length: int
    decoder_anomaly_codes_json: str
    decoder_anomaly_codes_sha256: str
    decoder_response_sha256: str
    capture_response_receipt_sha256: str
    route_landings_sha256: str
    raw_result_occurrences_sha256: str
    source_sha: str
    run_id: int
    run_attempt: int
    chain_id: str
    lane_id: str
    endpoint_id: str
    endpoint_slug: str
    live_snapshot_at: str
    provider_call_ordinal: int
    page_ordinal: int | None
    provider_call_role: str
    retry_ordinal: int
    request_ordinal: int
    observation_ordinal: int
    global_record_ordinal: int
    observation_record_ordinal: int
    record_kind: LiveLosslessRecordKind
    raw_occurrence_sha256: str | None
    result_set_name: str | None
    result_set_ordinal: int | None
    result_set_occurrence: int | None
    node_ordinal: int | None
    parent_node_ordinal: int | None
    field_name: str | None
    field_ordinal: int | None
    row_ordinal: int | None
    json_path: str | None
    presence_kind: str | None
    value_kind: str | None
    canonical_json: str | None
    canonical_json_sha256: str | None
    value_sha256: str | None
    source_item_sha256: str
    payload_json: str
    payload_sha256: str

    schema_version: ClassVar[int] = PUBLIC_VALUE_AUTHORITY_SCHEMA_VERSION
    kind: ClassVar[str] = "raw_nba_api_live_lossless_node_v1"

    def __post_init__(self) -> None:
        for name in (
            "record_sha256",
            "representation_assignment_sha256",
            "expected_unit_sha256",
            "response_residual_record_root_sha256",
            "raw_authority_bundle_sha256",
            "observation_record_sha256",
            "observation_sha256",
            "attempt_sha256",
            "semantic_request_sha256",
            "logical_invocation_sha256",
            "provider_call_sha256",
            "request_surface_sha256",
            "runtime_contract_sha256",
            "provider_authority_sha256",
            "endpoint_contract_sha256",
            "parser_input_sha256",
            "decoder_anomaly_codes_sha256",
            "decoder_response_sha256",
            "capture_response_receipt_sha256",
            "route_landings_sha256",
            "raw_result_occurrences_sha256",
            "source_item_sha256",
            "payload_sha256",
        ):
            _exact_sha256(getattr(self, name), field_name=name)
        if self.raw_occurrence_sha256 is not None:
            _exact_sha256(self.raw_occurrence_sha256, field_name="raw_occurrence_sha256")
        if (
            type(self.source_input_kind) is not str
            or self.source_input_kind != LIVE_LOSSLESS_SOURCE_INPUT_KIND
        ):
            _fail("live-lossless record has a foreign source-input kind")
        if type(self.ownership_kind) is not str or self.ownership_kind not in {
            "result_occurrence",
            "response_residual",
        }:
            _fail("live-lossless record has a foreign ownership discriminator")
        if type(self.record_kind) is not str or self.record_kind not in _RECORD_KINDS:
            _fail("live-lossless record kind is invalid")
        _exact_nonnegative(
            self.expected_unit_ordinal,
            field_name="expected_unit_ordinal",
            maximum=MAX_PUBLIC_VALUE_EXPECTED_UNITS - 1,
        )
        _exact_nonnegative(
            self.response_residual_record_count,
            field_name="response_residual_record_count",
            maximum=MAX_LIVE_LOSSLESS_RECORDS,
        )
        if self.ownership_occurrence_ordinal is not None:
            _exact_nonnegative(
                self.ownership_occurrence_ordinal,
                field_name="ownership_occurrence_ordinal",
                maximum=MAX_LIVE_LOSSLESS_RESULT_OCCURRENCES - 1,
            )
        if self.ownership_kind == "result_occurrence":
            if self.raw_occurrence_sha256 is None or self.ownership_occurrence_ordinal is None:
                _fail("occurrence-owned live-lossless record lacks exact occurrence identity")
            if self.representation_kind != LIVE_LOSSLESS_REPRESENTATION_KIND:
                _fail("occurrence-owned live-lossless record has a foreign representation")
        else:
            if (
                self.raw_occurrence_sha256 is not None
                or self.ownership_occurrence_ordinal is not None
            ):
                _fail("response-residual record fabricates occurrence ownership")
            if self.record_kind != "node":
                _fail("only live node records may belong to the response residual")
            if self.representation_kind != LIVE_RESPONSE_RESIDUAL_REPRESENTATION_KIND:
                _fail("response-residual record has a foreign representation")
            if self.response_residual_record_count == 0:
                _fail("response-residual ownership contradicts an explicit zero partition")
        empty_residual_root = canonical_ordered_root_sha256(
            kind="live_lossless_response_residual_source_items_v1",
            count=0,
            item_sha256s=(),
        )
        if (self.response_residual_record_count == 0) != (
            self.response_residual_record_root_sha256 == empty_residual_root
        ):
            _fail("live-lossless response-residual zero proof is inconsistent")
        try:
            expected_unit = ExpectedValueUnitV1(
                unit_sha256=self.expected_unit_sha256,
                raw_authority_bundle_sha256=self.raw_authority_bundle_sha256,
                unit_ordinal=self.expected_unit_ordinal,
                observation_sha256=self.observation_sha256,
                observation_ordinal=self.observation_ordinal,
                unit_kind=cast("ExpectedValueUnitKindV1", self.ownership_kind),
                occurrence_sha256=self.raw_occurrence_sha256,
                occurrence_ordinal=self.ownership_occurrence_ordinal,
            )
            ValueRepresentationAssignmentV1(
                assignment_sha256=self.representation_assignment_sha256,
                raw_authority_bundle_sha256=self.raw_authority_bundle_sha256,
                unit_sha256=self.expected_unit_sha256,
                unit_ordinal=self.expected_unit_ordinal,
                source_input_kind=LIVE_LOSSLESS_SOURCE_INPUT_KIND,
                representation_kind=cast(
                    "PublicValueRepresentationKindV1", self.representation_kind
                ),
            ).validate_for_unit(expected_unit)
        except PublicValueTypesError as exc:
            raise LiveLosslessValueAuthorityError(
                "live-lossless public-value ownership binding is invalid"
            ) from exc
        if (
            type(self.source_sha) is not str
            or re.fullmatch(r"[0-9a-f]{40}", self.source_sha) is None
        ):
            _fail("live-lossless source SHA is invalid")
        for name in (
            "chain_id",
            "lane_id",
            "endpoint_id",
            "endpoint_slug",
            "provider_call_role",
        ):
            _safe_id(getattr(self, name), field_name=name)
        for name, maximum in (
            ("run_id", (1 << 63) - 1),
            ("run_attempt", (1 << 31) - 1),
            ("observation_ordinal", MAX_LIVE_LOSSLESS_OBSERVATIONS - 1),
            ("global_record_ordinal", MAX_LIVE_LOSSLESS_RECORDS - 1),
            ("observation_record_ordinal", MAX_LIVE_LOSSLESS_RECORDS - 1),
            ("parser_input_length", MAX_LIVE_LOSSLESS_CANONICAL_BYTES),
            ("provider_call_ordinal", (1 << 63) - 1),
            ("retry_ordinal", (1 << 31) - 1),
            ("request_ordinal", (1 << 63) - 1),
        ):
            value = _exact_nonnegative(getattr(self, name), field_name=name, maximum=maximum)
            if name in {"run_id", "run_attempt"} and value == 0:
                _fail(f"{name} must be positive")
        if self.page_ordinal is not None:
            _exact_nonnegative(
                self.page_ordinal,
                field_name="page_ordinal",
                maximum=(1 << 63) - 1,
            )
        anomaly_payload = _decode_canonical_array(
            self.decoder_anomaly_codes_json,
            field_name="decoder_anomaly_codes_json",
        )
        if (
            len(self.decoder_anomaly_codes_json.encode("utf-8")) > MAX_LIVE_LOSSLESS_ANOMALY_BYTES
            or any(
                type(item) is not str or item not in _DECODER_ANOMALY_CODES
                for item in anomaly_payload
            )
            or anomaly_payload != sorted(set(cast("list[str]", anomaly_payload)))
            or self.decoder_anomaly_codes_sha256
            != _sha256_bytes(self.decoder_anomaly_codes_json.encode("utf-8"))
        ):
            _fail("live-lossless decoder anomaly inventory is invalid")
        _canonical_timestamp(self.live_snapshot_at, field_name="live_snapshot_at")
        for name, maximum in (
            ("result_set_ordinal", MAX_LIVE_LOSSLESS_RESULTS - 1),
            ("result_set_occurrence", MAX_LIVE_LOSSLESS_RESULT_OCCURRENCES - 1),
            ("node_ordinal", MAX_LIVE_LOSSLESS_NODES - 1),
            ("parent_node_ordinal", MAX_LIVE_LOSSLESS_NODES - 1),
            ("field_ordinal", 1_023),
            ("row_ordinal", MAX_LIVE_LOSSLESS_NODES - 1),
        ):
            value = getattr(self, name)
            if value is not None:
                _exact_nonnegative(value, field_name=name, maximum=maximum)
        for name in ("result_set_name", "field_name"):
            value = getattr(self, name)
            if value is not None:
                _safe_id(value, field_name=name)
                _reject_public_text(value, key=name == "field_name")
        if self.json_path is not None:
            _validate_json_path(self.json_path, field_name="json_path")
        if self.presence_kind is not None and (
            type(self.presence_kind) is not str or self.presence_kind not in _PRESENCE_KINDS
        ):
            _fail("live-lossless presence kind is invalid")
        if self.value_kind is not None and (
            type(self.value_kind) is not str or self.value_kind not in _VALUE_KINDS
        ):
            _fail("live-lossless value kind is invalid")
        if (self.canonical_json is None) != (self.canonical_json_sha256 is None):
            _fail("live-lossless canonical value digest is incomplete")
        if self.canonical_json is not None:
            if type(self.canonical_json) is not str:
                _fail("live-lossless canonical value is not exact text")
            try:
                raw_value = self.canonical_json.encode("utf-8", errors="strict")
            except UnicodeEncodeError:
                raise LiveLosslessValueAuthorityError(
                    "live-lossless canonical value is not valid UTF-8"
                ) from None
            if not raw_value or len(raw_value) > MAX_LIVE_LOSSLESS_CANONICAL_BYTES:
                _fail("live-lossless canonical value exceeds its byte bound")
            _decode_canonical_json(
                self.canonical_json,
                field_name="canonical_json",
                require=None,
            )
            if self.canonical_json_sha256 != _sha256_bytes(raw_value):
                _fail("live-lossless canonical value digest is invalid")
        if self.value_sha256 is not None:
            _exact_sha256(self.value_sha256, field_name="value_sha256")
        payload = _decode_canonical_object(self.payload_json, field_name="payload_json")
        if self.payload_sha256 != _sha256_bytes(self.payload_json.encode("utf-8")):
            _fail("live-lossless payload digest is invalid")
        source_item_sha256 = _validate_payload_contract(self.record_kind, payload)
        if self.source_item_sha256 != source_item_sha256:
            _fail("live-lossless record source digest differs from its exact payload")
        self._validate_payload_projection(payload)
        if self.record_sha256 != canonical_sha256(_identity_payload(self)):
            _fail("live-lossless record digest differs from its exact identity")

    def _validate_payload_projection(self, payload: Mapping[str, object]) -> None:
        expected_result_name = (
            payload.get("name")
            if self.record_kind == "result_declaration"
            else payload.get("result_set_name")
            if self.record_kind in {"result_occurrence", "node"}
            else payload.get("owner_result_set_name")
        )
        expected_result_ordinal = (
            payload.get("ordinal")
            if self.record_kind == "result_declaration"
            else payload.get("result_set_ordinal")
            if self.record_kind in {"result_occurrence", "node"}
            else payload.get("owner_result_set_ordinal")
        )
        expected_occurrence = (
            None
            if self.record_kind == "result_declaration"
            else payload.get("occurrence_ordinal")
            if self.record_kind == "result_occurrence"
            else payload.get("result_set_occurrence")
            if self.record_kind == "node"
            else payload.get("owner_result_set_occurrence")
        )
        expected_node = (
            payload.get("node_ordinal") if self.record_kind != "result_declaration" else None
        )
        expected_parent = payload.get("parent_node_ordinal") if self.record_kind == "node" else None
        expected_field = payload.get("field_name") if self.record_kind == "field_cell" else None
        expected_field_ordinal = (
            payload.get("field_ordinal") if self.record_kind == "field_cell" else None
        )
        expected_row = (
            payload.get("result_set_row_ordinal")
            if self.record_kind == "node"
            else payload.get("owner_row_ordinal")
            if self.record_kind == "field_cell"
            else None
        )
        expected_path = (
            payload.get("json_path")
            if self.record_kind in {"result_declaration", "result_occurrence", "node"}
            else payload.get("concrete_json_path")
        )
        expected_presence = (
            payload.get("presence")
            if self.record_kind == "result_declaration"
            else payload.get("presence_kind")
        )
        expected_value_kind = (
            payload.get("value_kind") if self.record_kind in {"node", "field_cell"} else None
        )
        expected_canonical = (
            payload.get("canonical_json") if self.record_kind in {"node", "field_cell"} else None
        )
        expected_value_sha = (
            payload.get("value_sha256") if self.record_kind != "result_declaration" else None
        )
        exact = (
            self.result_set_name,
            self.result_set_ordinal,
            self.result_set_occurrence,
            self.node_ordinal,
            self.parent_node_ordinal,
            self.field_name,
            self.field_ordinal,
            self.row_ordinal,
            self.json_path,
            self.presence_kind,
            self.value_kind,
            self.canonical_json,
            self.value_sha256,
        )
        expected = (
            expected_result_name,
            expected_result_ordinal,
            expected_occurrence,
            expected_node,
            expected_parent,
            expected_field,
            expected_field_ordinal,
            expected_row,
            expected_path,
            expected_presence,
            expected_value_kind,
            expected_canonical,
            expected_value_sha,
        )
        if not _exact_equal(exact, expected):
            _fail("live-lossless record selectors differ from its payload")
        if (
            self.record_kind in {"result_declaration", "result_occurrence", "field_cell"}
            and self.result_set_name is None
        ):
            _fail("live-lossless typed record omits its result identity")
        if self.record_kind == "node" and self.node_ordinal is None:
            _fail("live-lossless node record omits its node ordinal")

    @classmethod
    def build(cls, **values: object) -> Self:
        payload = values.get("payload")
        if type(payload) is not dict:
            _fail("live-lossless source payload must be an exact object")
        payload_json = canonical_json_bytes(
            payload,
            maximum_bytes=MAX_LIVE_LOSSLESS_CANONICAL_BYTES,
        ).decode("utf-8")
        prepared = {key: value for key, value in values.items() if key != "payload"}
        prepared["payload_json"] = payload_json
        prepared["payload_sha256"] = _sha256_bytes(payload_json.encode("utf-8"))
        identity = {
            "schema_version": cls.schema_version,
            "kind": cls.kind,
            **prepared,
        }
        return cls(record_sha256=canonical_sha256(identity), **cast("Any", prepared))

    def identity_payload(self) -> dict[str, object]:
        return _identity_payload(self)

    def to_row(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            **{item.name: getattr(self, item.name) for item in fields(self)},
        }

    @classmethod
    def from_row(cls, value: object) -> Self:
        if type(value) is not dict:
            _fail("live-lossless public row must be an exact built-in dict")
        row = cast("dict[object, object]", value)
        expected = ("schema_version", *(item.name for item in fields(cls)))
        if any(type(key) is not str for key in row) or tuple(row) != expected:
            _fail("live-lossless public row fields are missing, additive, reordered, or foreign")
        if type(row["schema_version"]) is not int or (
            row["schema_version"] != PUBLIC_VALUE_AUTHORITY_SCHEMA_VERSION
        ):
            _fail("live-lossless public row schema version is invalid")
        try:
            return cast("Any", cls)(**{item.name: row[item.name] for item in fields(cls)})
        except LiveLosslessValueAuthorityError:
            raise
        except (TypeError, ValueError):
            raise LiveLosslessValueAuthorityError(
                "live-lossless public row failed semantic reconstruction"
            ) from None


def _exact_equal(left: object, right: object) -> bool:
    """Compare supported public values without invoking caller equality."""

    if type(left) is not type(right):
        return False
    if left is None:
        return True
    if type(left) in {str, int, float, bool, bytes}:
        return bool(left == right)
    if type(left) is tuple:
        right_tuple = cast("tuple[object, ...]", right)
        left_tuple = left
        return len(left_tuple) == len(right_tuple) and all(
            _exact_equal(a, b) for a, b in zip(left_tuple, right_tuple, strict=True)
        )
    if type(left) is list:
        right_list = cast("list[object]", right)
        left_list = cast("list[object]", left)
        return len(left_list) == len(right_list) and all(
            _exact_equal(a, b) for a, b in zip(left_list, right_list, strict=True)
        )
    if type(left) is dict:
        left_dict = cast("dict[str, object]", left)
        right_dict = cast("dict[str, object]", right)
        if tuple(left_dict) != tuple(right_dict):
            return False
        return all(_exact_equal(left_dict[key], right_dict[key]) for key in left_dict)
    return False


LIVE_LOSSLESS_NODE_COLUMNS: Final = (
    "schema_version",
    *(item.name for item in fields(LiveLosslessNodeRecordV1)),
)
_LIVE_LOSSLESS_NUMERIC_COLUMNS: Final = frozenset(
    {
        "schema_version",
        "expected_unit_ordinal",
        "ownership_occurrence_ordinal",
        "response_residual_record_count",
        "parser_input_length",
        "run_id",
        "run_attempt",
        "provider_call_ordinal",
        "page_ordinal",
        "retry_ordinal",
        "request_ordinal",
        "observation_ordinal",
        "global_record_ordinal",
        "observation_record_ordinal",
        "result_set_ordinal",
        "result_set_occurrence",
        "node_ordinal",
        "parent_node_ordinal",
        "field_ordinal",
        "row_ordinal",
    }
)
LIVE_LOSSLESS_TEXT_COLUMNS: Final = tuple(
    column for column in LIVE_LOSSLESS_NODE_COLUMNS if column not in _LIVE_LOSSLESS_NUMERIC_COLUMNS
)

_LIVE_LOSSLESS_NODE_SCHEMA_DESCRIPTOR: Final = {
    "schema_version": PUBLIC_VALUE_AUTHORITY_SCHEMA_VERSION,
    "kind": "raw_nba_api_live_lossless_node_schema_v1",
    "ordered_columns": list(LIVE_LOSSLESS_NODE_COLUMNS),
    "primary_key": ["record_sha256"],
    "ordering": ["observation_ordinal", "observation_record_ordinal"],
}
LIVE_LOSSLESS_NODE_SCHEMA_SHA256: Final = canonical_sha256(_LIVE_LOSSLESS_NODE_SCHEMA_DESCRIPTOR)


def _public_row_text_bytes(row: Mapping[str, object]) -> int:
    total = 0
    for column in LIVE_LOSSLESS_TEXT_COLUMNS:
        value = row[column]
        if value is None:
            continue
        if type(value) is not str:
            _fail("live-lossless public text column has a foreign value type")
        try:
            total += len(value.encode("utf-8", errors="strict"))
        except UnicodeEncodeError:
            raise LiveLosslessValueAuthorityError(
                "live-lossless public text contains invalid Unicode"
            ) from None
        if total > MAX_LIVE_LOSSLESS_TOTAL_CANONICAL_BYTES:
            _fail("live-lossless public text exceeds its cumulative byte bound")
    return total


def _record_row_without_methods(record: LiveLosslessNodeRecordV1) -> dict[str, object]:
    if type(record) is not LiveLosslessNodeRecordV1:
        _fail("live-lossless authority record inventory contains a foreign DTO")
    return {
        "schema_version": PUBLIC_VALUE_AUTHORITY_SCHEMA_VERSION,
        **{item.name: object.__getattribute__(record, item.name) for item in fields(record)},
    }


def _record_observation_sort_key(record: LiveLosslessNodeRecordV1) -> tuple[object, ...]:
    return (
        record.logical_invocation_sha256,
        record.semantic_request_sha256,
        record.provider_call_ordinal,
        0 if record.page_ordinal is None else 1,
        0 if record.page_ordinal is None else record.page_ordinal,
        record.provider_call_role,
        record.provider_call_sha256,
        record.retry_ordinal,
        record.request_ordinal,
        record.observation_sha256,
    )


@dataclass(frozen=True, slots=True)
class _ObservationOwnershipProjection:
    units: tuple[ExpectedValueUnitV1, ...]
    assignments: tuple[ValueRepresentationAssignmentV1, ...]
    residual_source_item_sha256s: tuple[str, ...]
    residual_root_sha256: str
    residual_partition_sha256: str


@dataclass(frozen=True, slots=True)
class _ValidatedAuthorityInventory:
    records: tuple[LiveLosslessNodeRecordV1, ...]
    selected_observation_count: int
    selected_observations_sha256: str
    record_inventory_sha256: str
    kind_counts: dict[str, int]
    expected_units: ExpectedValueUnitInventoryV1
    assignments: tuple[ValueRepresentationAssignmentV1, ...]
    assignment_inventory_sha256: str
    residual_source_item_sha256s: tuple[str, ...]
    residual_record_inventory_sha256: str
    residual_observation_count: int
    zero_residual_observation_count: int
    residual_partition_inventory_sha256: str


def _unit_and_assignment_from_record(
    record: LiveLosslessNodeRecordV1,
) -> tuple[ExpectedValueUnitV1, ValueRepresentationAssignmentV1]:
    try:
        unit = ExpectedValueUnitV1(
            unit_sha256=record.expected_unit_sha256,
            raw_authority_bundle_sha256=record.raw_authority_bundle_sha256,
            unit_ordinal=record.expected_unit_ordinal,
            observation_sha256=record.observation_sha256,
            observation_ordinal=record.observation_ordinal,
            unit_kind=cast("ExpectedValueUnitKindV1", record.ownership_kind),
            occurrence_sha256=record.raw_occurrence_sha256,
            occurrence_ordinal=record.ownership_occurrence_ordinal,
        )
        assignment = ValueRepresentationAssignmentV1(
            assignment_sha256=record.representation_assignment_sha256,
            raw_authority_bundle_sha256=record.raw_authority_bundle_sha256,
            unit_sha256=record.expected_unit_sha256,
            unit_ordinal=record.expected_unit_ordinal,
            source_input_kind=LIVE_LOSSLESS_SOURCE_INPUT_KIND,
            representation_kind=cast("PublicValueRepresentationKindV1", record.representation_kind),
        ).validate_for_unit(unit)
    except PublicValueTypesError as exc:
        raise LiveLosslessValueAuthorityError(
            "live-lossless ownership row differs from central public-value types"
        ) from exc
    return unit, assignment


def _observation_ownership_projection(
    records: Sequence[LiveLosslessNodeRecordV1],
) -> _ObservationOwnershipProjection:
    if not records:
        _fail("live-lossless ownership projection requires one observation")
    residual_records = tuple(item for item in records if item.ownership_kind == "response_residual")
    residual_source_item_sha256s = tuple(item.source_item_sha256 for item in residual_records)
    residual_root = canonical_ordered_root_sha256(
        kind="live_lossless_response_residual_source_items_v1",
        count=len(residual_source_item_sha256s),
        item_sha256s=residual_source_item_sha256s,
    )
    if any(
        item.response_residual_record_count != len(residual_records)
        or item.response_residual_record_root_sha256 != residual_root
        for item in records
    ):
        _fail("live-lossless rows differ from their exact response-residual partition")

    declaration_records = tuple(
        item for item in records if item.record_kind == "result_declaration"
    )
    occurrence_units: list[ExpectedValueUnitV1] = []
    assignments: list[ValueRepresentationAssignmentV1] = []
    expected_by_owner: dict[
        str | None, tuple[ExpectedValueUnitV1, ValueRepresentationAssignmentV1]
    ] = {}
    for expected_occurrence_ordinal, record in enumerate(declaration_records):
        if (
            record.ownership_kind != "result_occurrence"
            or record.ownership_occurrence_ordinal != expected_occurrence_ordinal
            or record.raw_occurrence_sha256 is None
            or record.raw_occurrence_sha256 in expected_by_owner
        ):
            _fail("live-lossless result declarations do not define exact occurrence ownership")
        unit, assignment = _unit_and_assignment_from_record(record)
        occurrence_units.append(unit)
        assignments.append(assignment)
        expected_by_owner[record.raw_occurrence_sha256] = (unit, assignment)

    response_unit: ExpectedValueUnitV1 | None = None
    if residual_records:
        response_unit, response_assignment = _unit_and_assignment_from_record(residual_records[0])
        assignments.append(response_assignment)
        expected_by_owner[None] = (response_unit, response_assignment)

    for record in records:
        owner = record.raw_occurrence_sha256
        expected = expected_by_owner.get(owner)
        if expected is None:
            _fail("live-lossless row references a foreign or unrepresented owner")
        unit, assignment = _unit_and_assignment_from_record(record)
        if not _exact_equal(
            (
                unit.to_row(),
                assignment.to_row(),
            ),
            (
                expected[0].to_row(),
                expected[1].to_row(),
            ),
        ):
            _fail("live-lossless owner rows disagree on their central assignment")

    units = tuple(occurrence_units) + (() if response_unit is None else (response_unit,))
    assignment_tuple = tuple(assignments)
    if len(units) != len(assignment_tuple):
        _fail("live-lossless ownership units and assignments have different denominators")
    partition_sha256 = canonical_sha256(
        {
            "schema_version": PUBLIC_VALUE_AUTHORITY_SCHEMA_VERSION,
            "kind": "live_lossless_response_residual_partition_v1",
            "observation_sha256": records[0].observation_sha256,
            "observation_ordinal": records[0].observation_ordinal,
            "record_count": len(residual_records),
            "record_inventory_sha256": residual_root,
        }
    )
    return _ObservationOwnershipProjection(
        units=units,
        assignments=assignment_tuple,
        residual_source_item_sha256s=residual_source_item_sha256s,
        residual_root_sha256=residual_root,
        residual_partition_sha256=partition_sha256,
    )


def _selected_observation_receipt_sha256(
    records: Sequence[LiveLosslessNodeRecordV1],
) -> str:
    if not records:
        _fail("live-lossless selected observation record group is empty")
    first = records[0]
    root = canonical_ordered_root_sha256(
        kind="live_lossless_observation_records_v1",
        count=len(records),
        item_sha256s=(item.record_sha256 for item in records),
    )
    ownership = _observation_ownership_projection(records)
    unit_root = canonical_ordered_root_sha256(
        kind="live_lossless_observation_expected_units_v1",
        count=len(ownership.units),
        item_sha256s=(item.unit_sha256 for item in ownership.units),
    )
    assignment_root = canonical_ordered_root_sha256(
        kind="live_lossless_observation_representation_assignments_v1",
        count=len(ownership.assignments),
        item_sha256s=(item.assignment_sha256 for item in ownership.assignments),
    )
    return canonical_sha256(
        {
            "schema_version": PUBLIC_VALUE_AUTHORITY_SCHEMA_VERSION,
            "kind": "live_lossless_selected_observation_receipt_v1",
            "raw_authority_bundle_sha256": first.raw_authority_bundle_sha256,
            "observation_ordinal": first.observation_ordinal,
            "observation_record_sha256": first.observation_record_sha256,
            "observation_sha256": first.observation_sha256,
            "attempt_sha256": first.attempt_sha256,
            "provider_authority_sha256": first.provider_authority_sha256,
            "endpoint_contract_sha256": first.endpoint_contract_sha256,
            "parser_input_sha256": first.parser_input_sha256,
            "decoder_response_sha256": first.decoder_response_sha256,
            "route_landings_sha256": first.route_landings_sha256,
            "raw_result_occurrences_sha256": first.raw_result_occurrences_sha256,
            "live_snapshot_at": first.live_snapshot_at,
            "record_count": len(records),
            "record_inventory_sha256": root,
            "expected_unit_count": len(ownership.units),
            "expected_unit_root_sha256": unit_root,
            "representation_assignment_count": len(ownership.assignments),
            "representation_assignment_root_sha256": assignment_root,
            "response_residual_record_count": len(ownership.residual_source_item_sha256s),
            "response_residual_record_root_sha256": ownership.residual_root_sha256,
            "response_residual_partition_sha256": ownership.residual_partition_sha256,
        }
    )


def _validate_authority_record_inventory(
    records: object,
    *,
    expected_raw_authority_bundle_sha256: str,
) -> _ValidatedAuthorityInventory:
    _exact_sha256(
        expected_raw_authority_bundle_sha256,
        field_name="expected_raw_authority_bundle_sha256",
    )
    if type(records) is not tuple or len(records) > MAX_LIVE_LOSSLESS_RECORDS:
        _fail("live-lossless authority record inventory has a foreign type or exceeds its bound")
    exact_input = records
    if any(type(item) is not LiveLosslessNodeRecordV1 for item in exact_input):
        _fail("live-lossless authority record inventory contains a foreign DTO")
    raw_rows = [
        _record_row_without_methods(cast("LiveLosslessNodeRecordV1", item)) for item in exact_input
    ]
    total_text_bytes = 0
    for row in raw_rows:
        total_text_bytes += _public_row_text_bytes(row)
        if total_text_bytes > MAX_LIVE_LOSSLESS_TOTAL_CANONICAL_BYTES:
            _fail("live-lossless authority public text exceeds its cumulative byte bound")
    rebuilt = tuple(LiveLosslessNodeRecordV1.from_row(row) for row in raw_rows)
    if any(
        not _exact_equal(row, item.to_row()) for row, item in zip(raw_rows, rebuilt, strict=True)
    ):
        _fail("live-lossless authority record reconstruction drifted")
    if any(
        item.raw_authority_bundle_sha256 != expected_raw_authority_bundle_sha256 for item in rebuilt
    ):
        _fail("live-lossless authority records reference a foreign raw authority bundle")
    if tuple(item.global_record_ordinal for item in rebuilt) != tuple(range(len(rebuilt))):
        _fail("live-lossless authority global record ordinals are not contiguous")

    groups: dict[int, list[LiveLosslessNodeRecordV1]] = {}
    for item in rebuilt:
        groups.setdefault(item.observation_ordinal, []).append(item)
    if tuple(groups) != tuple(range(len(groups))):
        _fail("live-lossless authority observation ordinals are not contiguous")
    semantic_keys: list[tuple[object, ...]] = []
    selected_receipts: list[str] = []
    expected_units: list[ExpectedValueUnitV1] = []
    assignments: list[ValueRepresentationAssignmentV1] = []
    residual_source_item_sha256s: list[str] = []
    residual_partitions: list[str] = []
    residual_observation_count = 0
    zero_residual_observation_count = 0
    kind_counts = {kind: 0 for kind in _RECORD_KIND_ORDER}
    common_names = (
        "raw_authority_bundle_sha256",
        "observation_record_sha256",
        "observation_sha256",
        "attempt_sha256",
        "semantic_request_sha256",
        "logical_invocation_sha256",
        "provider_call_sha256",
        "request_surface_sha256",
        "runtime_contract_sha256",
        "provider_authority_sha256",
        "endpoint_contract_sha256",
        "parser_input_sha256",
        "parser_input_length",
        "decoder_anomaly_codes_json",
        "decoder_anomaly_codes_sha256",
        "decoder_response_sha256",
        "capture_response_receipt_sha256",
        "route_landings_sha256",
        "raw_result_occurrences_sha256",
        "source_sha",
        "run_id",
        "run_attempt",
        "chain_id",
        "lane_id",
        "endpoint_id",
        "endpoint_slug",
        "live_snapshot_at",
        "provider_call_ordinal",
        "page_ordinal",
        "provider_call_role",
        "retry_ordinal",
        "request_ordinal",
        "observation_ordinal",
    )
    category_order = {kind: ordinal for ordinal, kind in enumerate(_RECORD_KIND_ORDER)}
    for ordinal in range(len(groups)):
        group = tuple(groups[ordinal])
        first = group[0]
        common = tuple(getattr(first, name) for name in common_names)
        if any(
            not _exact_equal(tuple(getattr(item, name) for name in common_names), common)
            for item in group[1:]
        ):
            _fail("live-lossless authority observation rows disagree on source identity")
        if tuple(item.observation_record_ordinal for item in group) != tuple(range(len(group))):
            _fail("live-lossless authority observation record ordinals are not contiguous")
        partitions = tuple(category_order[item.record_kind] for item in group)
        if partitions != tuple(sorted(partitions)):
            _fail("live-lossless authority record-kind partitions are reordered")
        by_kind = {
            kind: tuple(item for item in group if item.record_kind == kind)
            for kind in _RECORD_KIND_ORDER
        }
        if (
            not by_kind["result_declaration"]
            or not by_kind["result_occurrence"]
            or not by_kind["node"]
        ):
            _fail("live-lossless selected observation omits a mandatory record partition")
        payload_ordinal_fields = {
            "result_declaration": "ordinal",
            "result_occurrence": "global_ordinal",
            "node": "node_ordinal",
            "field_cell": "cell_ordinal",
        }
        for kind, items in by_kind.items():
            kind_counts[kind] += len(items)
            payload_ordinals = tuple(
                cast(
                    "int",
                    _decode_canonical_object(item.payload_json, field_name="payload_json")[
                        payload_ordinal_fields[kind]
                    ],
                )
                for item in items
            )
            if payload_ordinals != tuple(range(len(items))):
                _fail(f"live-lossless {kind} ordinals are not contiguous")
        if len(by_kind["result_declaration"]) > MAX_LIVE_LOSSLESS_RESULTS:
            _fail("live-lossless result declaration count exceeds its bound")
        if len(by_kind["result_occurrence"]) > MAX_LIVE_LOSSLESS_RESULT_OCCURRENCES:
            _fail("live-lossless result occurrence count exceeds its bound")
        if len(by_kind["node"]) > MAX_LIVE_LOSSLESS_NODES:
            _fail("live-lossless node count exceeds its bound")
        if len(by_kind["field_cell"]) > MAX_LIVE_LOSSLESS_FIELD_CELLS:
            _fail("live-lossless field-cell count exceeds its bound")
        semantic_keys.append(_record_observation_sort_key(first))
        ownership = _observation_ownership_projection(group)
        expected_units.extend(ownership.units)
        assignments.extend(ownership.assignments)
        residual_source_item_sha256s.extend(ownership.residual_source_item_sha256s)
        residual_partitions.append(ownership.residual_partition_sha256)
        if ownership.residual_source_item_sha256s:
            residual_observation_count += 1
        else:
            zero_residual_observation_count += 1
        selected_receipts.append(_selected_observation_receipt_sha256(group))
    if semantic_keys != sorted(semantic_keys) or len(set(semantic_keys)) != len(semantic_keys):
        _fail("live-lossless selected observations are not in exact semantic attempt order")
    selected_root = canonical_ordered_root_sha256(
        kind="live_lossless_selected_observations_v1",
        count=len(selected_receipts),
        item_sha256s=selected_receipts,
    )
    record_root = canonical_ordered_root_sha256(
        kind="live_lossless_public_records_v1",
        count=len(rebuilt),
        item_sha256s=(item.record_sha256 for item in rebuilt),
    )
    try:
        expected_unit_inventory = ExpectedValueUnitInventoryV1.build(
            raw_authority_bundle_sha256=expected_raw_authority_bundle_sha256,
            units=tuple(expected_units),
        )
    except PublicValueTypesError as exc:
        raise LiveLosslessValueAuthorityError(
            "live-lossless expected-unit inventory is not canonical"
        ) from exc
    assignment_root = canonical_ordered_root_sha256(
        kind="live_lossless_representation_assignments_v1",
        count=len(assignments),
        item_sha256s=(item.assignment_sha256 for item in assignments),
    )
    residual_root = canonical_ordered_root_sha256(
        kind="live_lossless_response_residual_source_items_v1",
        count=len(residual_source_item_sha256s),
        item_sha256s=residual_source_item_sha256s,
    )
    partition_root = canonical_ordered_root_sha256(
        kind="live_lossless_response_residual_partitions_v1",
        count=len(residual_partitions),
        item_sha256s=residual_partitions,
    )
    return _ValidatedAuthorityInventory(
        records=rebuilt,
        selected_observation_count=len(groups),
        selected_observations_sha256=selected_root,
        record_inventory_sha256=record_root,
        kind_counts=kind_counts,
        expected_units=expected_unit_inventory,
        assignments=tuple(assignments),
        assignment_inventory_sha256=assignment_root,
        residual_source_item_sha256s=tuple(residual_source_item_sha256s),
        residual_record_inventory_sha256=residual_root,
        residual_observation_count=residual_observation_count,
        zero_residual_observation_count=zero_residual_observation_count,
        residual_partition_inventory_sha256=partition_root,
    )


@dataclass(frozen=True, slots=True)
class LiveLosslessValueAuthorityReceiptV1:
    """Value-free root receipt for the one mandatory live public relation."""

    receipt_sha256: str
    source_input_kind: str
    representation_kind: str
    response_residual_representation_kind: str
    node_schema_sha256: str
    raw_authority_bundle_sha256: str
    selected_observation_count: int
    selected_observations_sha256: str
    expected_unit_count: int
    expected_unit_inventory_sha256: str
    expected_unit_root_sha256: str
    representation_assignment_count: int
    representation_assignment_inventory_sha256: str
    response_residual_record_count: int
    response_residual_record_inventory_sha256: str
    response_residual_observation_count: int
    zero_response_residual_observation_count: int
    response_residual_partition_inventory_sha256: str
    record_count: int
    record_inventory_sha256: str
    result_declaration_count: int
    result_occurrence_count: int
    node_count: int
    field_cell_count: int

    schema_version: ClassVar[int] = PUBLIC_VALUE_AUTHORITY_SCHEMA_VERSION
    kind: ClassVar[str] = LIVE_LOSSLESS_VALUE_AUTHORITY_KIND

    def __post_init__(self) -> None:
        for name in (
            "receipt_sha256",
            "node_schema_sha256",
            "raw_authority_bundle_sha256",
            "selected_observations_sha256",
            "expected_unit_inventory_sha256",
            "expected_unit_root_sha256",
            "representation_assignment_inventory_sha256",
            "response_residual_record_inventory_sha256",
            "response_residual_partition_inventory_sha256",
            "record_inventory_sha256",
        ):
            _exact_sha256(getattr(self, name), field_name=name)
        if (
            type(self.source_input_kind) is not str
            or self.source_input_kind != LIVE_LOSSLESS_SOURCE_INPUT_KIND
        ):
            _fail("live-lossless receipt has a foreign source-input kind")
        if (
            type(self.representation_kind) is not str
            or self.representation_kind != LIVE_LOSSLESS_REPRESENTATION_KIND
        ):
            _fail("live-lossless receipt has a foreign representation kind")
        if (
            type(self.response_residual_representation_kind) is not str
            or self.response_residual_representation_kind
            != LIVE_RESPONSE_RESIDUAL_REPRESENTATION_KIND
        ):
            _fail("live-lossless receipt has a foreign response-residual representation")
        if self.node_schema_sha256 != LIVE_LOSSLESS_NODE_SCHEMA_SHA256:
            _fail("live-lossless receipt has a foreign node schema")
        for name, maximum in (
            ("selected_observation_count", MAX_LIVE_LOSSLESS_OBSERVATIONS),
            ("expected_unit_count", MAX_PUBLIC_VALUE_EXPECTED_UNITS),
            ("representation_assignment_count", MAX_PUBLIC_VALUE_EXPECTED_UNITS),
            ("response_residual_record_count", MAX_LIVE_LOSSLESS_RECORDS),
            ("response_residual_observation_count", MAX_LIVE_LOSSLESS_OBSERVATIONS),
            ("zero_response_residual_observation_count", MAX_LIVE_LOSSLESS_OBSERVATIONS),
            ("record_count", MAX_LIVE_LOSSLESS_RECORDS),
            (
                "result_declaration_count",
                MAX_LIVE_LOSSLESS_OBSERVATIONS * MAX_LIVE_LOSSLESS_RESULTS,
            ),
            ("result_occurrence_count", MAX_LIVE_LOSSLESS_RESULT_OCCURRENCES),
            ("node_count", MAX_LIVE_LOSSLESS_NODES),
            ("field_cell_count", MAX_LIVE_LOSSLESS_FIELD_CELLS),
        ):
            _exact_nonnegative(getattr(self, name), field_name=name, maximum=maximum)
        if (
            self.representation_assignment_count != self.expected_unit_count
            or self.response_residual_observation_count
            + self.zero_response_residual_observation_count
            != self.selected_observation_count
        ):
            _fail("live-lossless receipt ownership denominators are inconsistent")
        if (
            self.result_declaration_count
            + self.result_occurrence_count
            + self.node_count
            + self.field_cell_count
            != self.record_count
        ):
            _fail("live-lossless receipt record-kind denominators are incomplete")
        empty_selected_root = canonical_ordered_root_sha256(
            kind="live_lossless_selected_observations_v1",
            count=0,
            item_sha256s=(),
        )
        empty_record_root = canonical_ordered_root_sha256(
            kind="live_lossless_public_records_v1",
            count=0,
            item_sha256s=(),
        )
        empty_units = ExpectedValueUnitInventoryV1.build(
            raw_authority_bundle_sha256=self.raw_authority_bundle_sha256,
            units=(),
        )
        empty_assignment_root = canonical_ordered_root_sha256(
            kind="live_lossless_representation_assignments_v1",
            count=0,
            item_sha256s=(),
        )
        empty_residual_root = canonical_ordered_root_sha256(
            kind="live_lossless_response_residual_source_items_v1",
            count=0,
            item_sha256s=(),
        )
        empty_partition_root = canonical_ordered_root_sha256(
            kind="live_lossless_response_residual_partitions_v1",
            count=0,
            item_sha256s=(),
        )
        if (self.response_residual_record_count == 0) != (
            self.response_residual_observation_count == 0
            and self.response_residual_record_inventory_sha256 == empty_residual_root
        ):
            _fail("live-lossless receipt response-residual zero proof is inconsistent")
        if self.selected_observation_count == 0:
            if (
                self.record_count != 0
                or self.expected_unit_count != 0
                or self.expected_unit_inventory_sha256 != empty_units.inventory_sha256
                or self.expected_unit_root_sha256 != empty_units.unit_root_sha256
                or self.representation_assignment_count != 0
                or self.representation_assignment_inventory_sha256 != empty_assignment_root
                or self.response_residual_record_count != 0
                or self.response_residual_record_inventory_sha256 != empty_residual_root
                or self.response_residual_observation_count != 0
                or self.zero_response_residual_observation_count != 0
                or self.response_residual_partition_inventory_sha256 != empty_partition_root
                or any(
                    value != 0
                    for value in (
                        self.result_declaration_count,
                        self.result_occurrence_count,
                        self.node_count,
                        self.field_cell_count,
                    )
                )
                or self.selected_observations_sha256 != empty_selected_root
                or self.record_inventory_sha256 != empty_record_root
            ):
                _fail("zero-live receipt differs from its canonical empty complement")
        elif (
            self.record_count == 0
            or self.expected_unit_count == 0
            or self.result_declaration_count == 0
            or self.result_occurrence_count == 0
            or self.node_count == 0
        ):
            _fail("selected live receipt omits mandatory public records")
        if self.receipt_sha256 != canonical_sha256(self.identity_payload()):
            _fail("live-lossless receipt digest differs from its exact identity")

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
        identity = {
            "schema_version": cls.schema_version,
            "kind": cls.kind,
            **values,
        }
        return cls(receipt_sha256=canonical_sha256(identity), **cast("Any", values))

    def to_dict(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "kind": self.kind,
            **{item.name: getattr(self, item.name) for item in fields(self)},
        }


@dataclass(frozen=True, slots=True)
class LiveLosslessValueAuthorityV1:
    """In-memory body-derived authority before the sole public relation is persisted."""

    receipt: LiveLosslessValueAuthorityReceiptV1
    records: tuple[LiveLosslessNodeRecordV1, ...]
    expected_units: ExpectedValueUnitInventoryV1
    representation_assignments: tuple[ValueRepresentationAssignmentV1, ...]

    def __post_init__(self) -> None:
        if type(self.receipt) is not LiveLosslessValueAuthorityReceiptV1:
            _fail("live-lossless authority receipt has a foreign type")
        receipt_values = {
            item.name: object.__getattribute__(self.receipt, item.name)
            for item in fields(LiveLosslessValueAuthorityReceiptV1)
        }
        try:
            rebuilt_receipt = LiveLosslessValueAuthorityReceiptV1(**receipt_values)
        except LiveLosslessValueAuthorityError:
            raise
        except (TypeError, ValueError):
            raise LiveLosslessValueAuthorityError(
                "live-lossless authority receipt reconstruction failed"
            ) from None
        if type(self.expected_units) is not ExpectedValueUnitInventoryV1:
            _fail("live-lossless expected-unit inventory has a foreign type")
        if type(self.representation_assignments) is not tuple or any(
            type(item) is not ValueRepresentationAssignmentV1
            for item in self.representation_assignments
        ):
            _fail("live-lossless representation assignment inventory has a foreign type")
        validated = _validate_authority_record_inventory(
            self.records,
            expected_raw_authority_bundle_sha256=(rebuilt_receipt.raw_authority_bundle_sha256),
        )
        if len(validated.records) != rebuilt_receipt.record_count:
            _fail("live-lossless authority record count differs from its receipt")
        if any(
            item.raw_authority_bundle_sha256 != rebuilt_receipt.raw_authority_bundle_sha256
            for item in validated.records
        ):
            _fail("live-lossless records reference a foreign raw authority bundle")
        if not _exact_equal(
            self.expected_units.to_row(),
            validated.expected_units.to_row(),
        ):
            _fail("live-lossless expected-unit inventory differs from its public rows")
        if len(self.representation_assignments) != len(validated.assignments) or any(
            not _exact_equal(left.to_row(), right.to_row())
            for left, right in zip(
                self.representation_assignments,
                validated.assignments,
                strict=True,
            )
        ):
            _fail("live-lossless assignments differ from their public rows")
        if not _exact_equal(
            (
                validated.selected_observation_count,
                validated.selected_observations_sha256,
                validated.record_inventory_sha256,
                validated.expected_units.unit_count,
                validated.expected_units.inventory_sha256,
                validated.expected_units.unit_root_sha256,
                len(validated.assignments),
                validated.assignment_inventory_sha256,
                len(validated.residual_source_item_sha256s),
                validated.residual_record_inventory_sha256,
                validated.residual_observation_count,
                validated.zero_residual_observation_count,
                validated.residual_partition_inventory_sha256,
                validated.kind_counts["result_declaration"],
                validated.kind_counts["result_occurrence"],
                validated.kind_counts["node"],
                validated.kind_counts["field_cell"],
            ),
            (
                rebuilt_receipt.selected_observation_count,
                rebuilt_receipt.selected_observations_sha256,
                rebuilt_receipt.record_inventory_sha256,
                rebuilt_receipt.expected_unit_count,
                rebuilt_receipt.expected_unit_inventory_sha256,
                rebuilt_receipt.expected_unit_root_sha256,
                rebuilt_receipt.representation_assignment_count,
                rebuilt_receipt.representation_assignment_inventory_sha256,
                rebuilt_receipt.response_residual_record_count,
                rebuilt_receipt.response_residual_record_inventory_sha256,
                rebuilt_receipt.response_residual_observation_count,
                rebuilt_receipt.zero_response_residual_observation_count,
                rebuilt_receipt.response_residual_partition_inventory_sha256,
                rebuilt_receipt.result_declaration_count,
                rebuilt_receipt.result_occurrence_count,
                rebuilt_receipt.node_count,
                rebuilt_receipt.field_cell_count,
            ),
        ):
            _fail("live-lossless authority denominators or roots differ from its records")

    def public_rows(self) -> tuple[dict[str, object], ...]:
        return tuple(item.to_row() for item in self.records)


def _observation_sort_key(observation: object) -> tuple[object, ...]:
    attempt = cast("Any", observation).attempt
    return (
        attempt.logical_invocation_sha256,
        attempt.semantic_request_sha256,
        attempt.provider_call_ordinal,
        0 if attempt.page_ordinal is None else 1,
        0 if attempt.page_ordinal is None else attempt.page_ordinal,
        attempt.provider_call_role,
        attempt.provider_call_sha256,
        attempt.retry_ordinal,
        attempt.request_ordinal,
        attempt.observation_sha256,
    )


def _raw_occurrence_by_result(
    raw_occurrences: Sequence[object],
    decoded_results: Sequence[object],
) -> dict[int, object]:
    if len(raw_occurrences) != len(decoded_results):
        _fail("live-lossless raw result denominator differs from decoded declarations")
    by_ordinal: dict[int, object] = {}
    for result in decoded_results:
        exact = cast("Any", result)
        candidates = tuple(
            item
            for item in raw_occurrences
            if cast("Any", item).result_name == exact.name
            and cast("Any", item).canonical_result_ordinal == exact.ordinal
        )
        if len(candidates) != 1:
            _fail("live-lossless declaration lacks one exact raw occurrence")
        raw = cast("Any", candidates[0])
        if (
            raw.observation_sha256 is None
            or raw.json_path != exact.json_path
            or raw.container_kind != exact.container_kind
            or raw.presence != exact.presence
            or raw.row_count != exact.row_count
            or raw.cell_count != exact.value_cell_count
            or raw.container_count != exact.container_count + exact.null_count
            or raw.missing_count != exact.missing_count
            or raw.null_count != exact.null_count
            or raw.parent_state_sha256 != exact.parent_occurrence_states_sha256
            or raw.output_sha256 != exact.normalized_output_sha256
        ):
            _fail("live-lossless raw occurrence differs from independent body decoding")
        raw_headers = raw.ordered_headers()
        expected_headers = (
            ()
            if exact.presence in {"missing", "null", "mixed_absent", "not_observed_parent_empty"}
            else exact.ordered_headers
        )
        if raw_headers != expected_headers:
            _fail("live-lossless raw occurrence headers differ from body decoding")
        by_ordinal[exact.ordinal] = raw
    return by_ordinal


def _record_values(
    *,
    bundle_sha256: str,
    observation: object,
    decoder_response: object,
    snapshot_at: str,
    observation_ordinal: int,
    global_record_ordinal: int,
    observation_record_ordinal: int,
    record_kind: LiveLosslessRecordKind,
    payload: Mapping[str, object],
    raw_occurrence_sha256: str | None,
    expected_unit: ExpectedValueUnitV1,
    representation_assignment: ValueRepresentationAssignmentV1,
    response_residual_record_count: int,
    response_residual_record_root_sha256: str,
) -> dict[str, object]:
    exact_observation = cast("Any", observation)
    attempt = exact_observation.attempt
    decoded = cast("Any", decoder_response)
    source_digest_name = {
        "result_declaration": "result_set_sha256",
        "result_occurrence": "occurrence_sha256",
        "node": "node_sha256",
        "field_cell": "cell_sha256",
    }[record_kind]
    result_set_name = (
        payload.get("name")
        if record_kind == "result_declaration"
        else payload.get("result_set_name")
        if record_kind in {"result_occurrence", "node"}
        else payload.get("owner_result_set_name")
    )
    result_set_ordinal = (
        payload.get("ordinal")
        if record_kind == "result_declaration"
        else payload.get("result_set_ordinal")
        if record_kind in {"result_occurrence", "node"}
        else payload.get("owner_result_set_ordinal")
    )
    result_set_occurrence = (
        None
        if record_kind == "result_declaration"
        else payload.get("occurrence_ordinal")
        if record_kind == "result_occurrence"
        else payload.get("result_set_occurrence")
        if record_kind == "node"
        else payload.get("owner_result_set_occurrence")
    )
    canonical = payload.get("canonical_json") if record_kind in {"node", "field_cell"} else None
    return {
        "source_input_kind": LIVE_LOSSLESS_SOURCE_INPUT_KIND,
        "representation_kind": representation_assignment.representation_kind,
        "representation_assignment_sha256": representation_assignment.assignment_sha256,
        "expected_unit_sha256": expected_unit.unit_sha256,
        "expected_unit_ordinal": expected_unit.unit_ordinal,
        "ownership_kind": expected_unit.unit_kind,
        "ownership_occurrence_ordinal": expected_unit.occurrence_ordinal,
        "response_residual_record_count": response_residual_record_count,
        "response_residual_record_root_sha256": response_residual_record_root_sha256,
        "raw_authority_bundle_sha256": bundle_sha256,
        "observation_record_sha256": exact_observation.observation_record_sha256,
        "observation_sha256": attempt.observation_sha256,
        "attempt_sha256": attempt.attempt_sha256,
        "semantic_request_sha256": attempt.semantic_request_sha256,
        "logical_invocation_sha256": attempt.logical_invocation_sha256,
        "provider_call_sha256": attempt.provider_call_sha256,
        "request_surface_sha256": attempt.request_surface_sha256,
        "runtime_contract_sha256": attempt.runtime_contract_sha256,
        "provider_authority_sha256": attempt.provider_authority_sha256,
        "endpoint_contract_sha256": attempt.endpoint_contract_sha256,
        "parser_input_sha256": decoded.parser_input_sha256,
        "parser_input_length": decoded.parser_input_length,
        "decoder_anomaly_codes_json": canonical_json_bytes(
            list(decoded.anomaly_codes), maximum_bytes=4_096
        ).decode("utf-8"),
        "decoder_anomaly_codes_sha256": _sha256_bytes(
            canonical_json_bytes(list(decoded.anomaly_codes), maximum_bytes=4_096)
        ),
        "decoder_response_sha256": decoded.response_sha256,
        "capture_response_receipt_sha256": exact_observation.capture_response_receipt_sha256,
        "route_landings_sha256": exact_observation.route_landings_sha256,
        "raw_result_occurrences_sha256": exact_observation.result_occurrences_sha256,
        "source_sha": attempt.source_sha,
        "run_id": attempt.run_id,
        "run_attempt": attempt.run_attempt,
        "chain_id": attempt.chain_id,
        "lane_id": attempt.lane_id,
        "endpoint_id": attempt.endpoint_id,
        "endpoint_slug": decoded.endpoint_slug,
        "live_snapshot_at": snapshot_at,
        "provider_call_ordinal": attempt.provider_call_ordinal,
        "page_ordinal": attempt.page_ordinal,
        "provider_call_role": attempt.provider_call_role,
        "retry_ordinal": attempt.retry_ordinal,
        "request_ordinal": attempt.request_ordinal,
        "observation_ordinal": observation_ordinal,
        "global_record_ordinal": global_record_ordinal,
        "observation_record_ordinal": observation_record_ordinal,
        "record_kind": record_kind,
        "raw_occurrence_sha256": raw_occurrence_sha256,
        "result_set_name": result_set_name,
        "result_set_ordinal": result_set_ordinal,
        "result_set_occurrence": result_set_occurrence,
        "node_ordinal": (
            payload.get("node_ordinal") if record_kind != "result_declaration" else None
        ),
        "parent_node_ordinal": (
            payload.get("parent_node_ordinal") if record_kind == "node" else None
        ),
        "field_name": payload.get("field_name") if record_kind == "field_cell" else None,
        "field_ordinal": payload.get("field_ordinal") if record_kind == "field_cell" else None,
        "row_ordinal": (
            payload.get("result_set_row_ordinal")
            if record_kind == "node"
            else payload.get("owner_row_ordinal")
            if record_kind == "field_cell"
            else None
        ),
        "json_path": (
            payload.get("json_path")
            if record_kind in {"result_declaration", "result_occurrence", "node"}
            else payload.get("concrete_json_path")
        ),
        "presence_kind": (
            payload.get("presence")
            if record_kind == "result_declaration"
            else payload.get("presence_kind")
        ),
        "value_kind": payload.get("value_kind") if record_kind in {"node", "field_cell"} else None,
        "canonical_json": canonical,
        "canonical_json_sha256": (
            None if canonical is None else _sha256_bytes(cast("str", canonical).encode("utf-8"))
        ),
        "value_sha256": (
            payload.get("value_sha256") if record_kind != "result_declaration" else None
        ),
        "source_item_sha256": payload[source_digest_name],
        "payload": dict(payload),
    }


def build_live_lossless_value_authority(
    raw_bundle: object,
    *,
    expected_raw_authority_bundle_sha256: str,
) -> LiveLosslessValueAuthorityV1:
    """Derive all mandatory live public records from exact Raw Authority V2 bodies."""

    _exact_sha256(
        expected_raw_authority_bundle_sha256,
        field_name="expected_raw_authority_bundle_sha256",
    )
    try:
        from nbadb.contracts.independent_live_value_decoder import (
            decode_live_value_response,
            validate_decoded_live_response,
        )
        from nbadb.contracts.raw_request_authority import (
            RawRequestAuthorityBundleV2,
            decode_parser_input_object,
            validate_raw_request_authority_bundle,
        )

        if type(raw_bundle) is not RawRequestAuthorityBundleV2:
            _fail("live-lossless source authority must be exact Raw Authority V2")
        _preflight_raw_authority_bundle(raw_bundle)
        bundle = validate_raw_request_authority_bundle(raw_bundle)
    except LiveLosslessValueAuthorityError:
        raise
    except (ImportError, TypeError, ValueError) as exc:
        raise LiveLosslessValueAuthorityError(
            "live-lossless Raw Authority V2 validation failed"
        ) from exc
    if bundle.bundle_sha256 != expected_raw_authority_bundle_sha256:
        _fail("live-lossless source authority differs from its external bundle pin")

    observations = tuple(
        sorted(
            (
                item
                for item in bundle.observations
                if item.lifecycle == "selected_terminal" and item.attempt.source_family == "live"
            ),
            key=_observation_sort_key,
        )
    )
    if len(observations) > MAX_LIVE_LOSSLESS_OBSERVATIONS:
        _fail("live-lossless selected observation count exceeds its bound")
    objects_by_sha = {item.object_sha256: item for item in bundle.objects}
    all_records: list[LiveLosslessNodeRecordV1] = []
    total_public_text_bytes = 0
    next_expected_unit_ordinal = 0

    for observation_ordinal, observation in enumerate(observations):
        body_sha = observation.body_object_sha256
        capture_receipt = observation.capture_response_receipt_sha256
        if (
            body_sha is None
            or capture_receipt is None
            or observation.outcome
            not in {
                "success_nonempty",
                "success_empty",
            }
        ):
            _fail("selected live observation lacks an exact successful public body")
        body = objects_by_sha.get(body_sha)
        if body is None:
            _fail("selected live observation references a missing parser object")
        parser_input = decode_parser_input_object(body)
        response = validate_decoded_live_response(
            decode_live_value_response(
                parser_input,
                endpoint_id=observation.attempt.endpoint_id,
                endpoint_contract_sha256=observation.attempt.endpoint_contract_sha256,
            )
        )
        if response.parser_input_sha256 != body.response_sha256:
            _fail("live-lossless decoder input differs from the exact parser object")
        landings = tuple(
            item
            for item in bundle.landings
            if item.observation_sha256 == observation.attempt.observation_sha256
        )
        snapshots = {item.live_snapshot_at for item in landings}
        if len(snapshots) != 1 or None in snapshots:
            _fail("selected live observation lacks one exact landing snapshot")
        snapshot = next(iter(snapshots))
        assert snapshot is not None
        snapshot_text = (
            snapshot.astimezone(UTC).isoformat(timespec="microseconds").replace("+00:00", "Z")
        )
        raw_occurrences = tuple(
            item
            for item in bundle.occurrences
            if item.observation_sha256 == observation.attempt.observation_sha256
        )
        raw_by_result = _raw_occurrence_by_result(raw_occurrences, response.result_sets)
        observation_records: list[LiveLosslessNodeRecordV1] = []

        inventories: tuple[tuple[LiveLosslessRecordKind, Sequence[object]], ...] = (
            ("result_declaration", response.result_sets),
            ("result_occurrence", response.result_occurrences),
            ("node", response.nodes),
            ("field_cell", response.field_cells),
        )
        observation_record_count = sum(len(inventory) for _kind, inventory in inventories)
        if observation_record_count > MAX_LIVE_LOSSLESS_RECORDS - len(all_records):
            _fail("live-lossless record count exceeds its bound")
        pending_records: list[tuple[LiveLosslessRecordKind, dict[str, object], str | None]] = []
        for record_kind, inventory in inventories:
            for item in inventory:
                payload = cast("dict[str, object]", cast("Any", item).to_dict())
                result_ordinal = (
                    payload.get("ordinal")
                    if record_kind == "result_declaration"
                    else payload.get("result_set_ordinal")
                    if record_kind in {"result_occurrence", "node"}
                    else payload.get("owner_result_set_ordinal")
                )
                raw_occurrence = (
                    raw_by_result.get(result_ordinal) if type(result_ordinal) is int else None
                )
                pending_records.append(
                    (
                        record_kind,
                        payload,
                        None
                        if raw_occurrence is None
                        else cast("str", cast("Any", raw_occurrence).occurrence_sha256),
                    )
                )

        source_digest_names = {
            "result_declaration": "result_set_sha256",
            "result_occurrence": "occurrence_sha256",
            "node": "node_sha256",
            "field_cell": "cell_sha256",
        }
        residual_source_item_sha256s = tuple(
            cast("str", payload[source_digest_names[record_kind]])
            for record_kind, payload, raw_occurrence_sha256 in pending_records
            if raw_occurrence_sha256 is None
        )
        residual_record_root_sha256 = canonical_ordered_root_sha256(
            kind="live_lossless_response_residual_source_items_v1",
            count=len(residual_source_item_sha256s),
            item_sha256s=residual_source_item_sha256s,
        )
        expected_observation_unit_count = len(response.result_sets) + bool(
            residual_source_item_sha256s
        )
        if (
            next_expected_unit_ordinal + expected_observation_unit_count
            > MAX_PUBLIC_VALUE_EXPECTED_UNITS
        ):
            _fail("live-lossless expected-unit inventory exceeds its central bound")
        owner_bindings: dict[
            str | None,
            tuple[ExpectedValueUnitV1, ValueRepresentationAssignmentV1],
        ] = {}
        for occurrence_ordinal, result in enumerate(response.result_sets):
            raw_occurrence = raw_by_result[cast("Any", result).ordinal]
            raw_occurrence_sha256 = cast("str", cast("Any", raw_occurrence).occurrence_sha256)
            unit = ExpectedValueUnitV1.build(
                raw_authority_bundle_sha256=bundle.bundle_sha256,
                unit_ordinal=next_expected_unit_ordinal,
                observation_sha256=observation.attempt.observation_sha256,
                observation_ordinal=observation_ordinal,
                unit_kind="result_occurrence",
                occurrence_sha256=raw_occurrence_sha256,
                occurrence_ordinal=occurrence_ordinal,
            )
            assignment = ValueRepresentationAssignmentV1.build(
                expected_unit=unit,
                source_input_kind=LIVE_LOSSLESS_SOURCE_INPUT_KIND,
                representation_kind=LIVE_LOSSLESS_REPRESENTATION_KIND,
            )
            if raw_occurrence_sha256 in owner_bindings:
                _fail("live-lossless result declarations duplicate one occurrence owner")
            owner_bindings[raw_occurrence_sha256] = (unit, assignment)
            next_expected_unit_ordinal += 1
        if residual_source_item_sha256s:
            unit = ExpectedValueUnitV1.build(
                raw_authority_bundle_sha256=bundle.bundle_sha256,
                unit_ordinal=next_expected_unit_ordinal,
                observation_sha256=observation.attempt.observation_sha256,
                observation_ordinal=observation_ordinal,
                unit_kind="response_residual",
            )
            assignment = ValueRepresentationAssignmentV1.build(
                expected_unit=unit,
                source_input_kind=LIVE_LOSSLESS_SOURCE_INPUT_KIND,
                representation_kind=LIVE_RESPONSE_RESIDUAL_REPRESENTATION_KIND,
            )
            owner_bindings[None] = (unit, assignment)
            next_expected_unit_ordinal += 1

        for record_kind, payload, raw_occurrence_sha256 in pending_records:
            binding = owner_bindings.get(raw_occurrence_sha256)
            if binding is None:
                _fail("live-lossless public record lacks one explicit ownership binding")
            expected_unit, representation_assignment = binding
            values = _record_values(
                bundle_sha256=bundle.bundle_sha256,
                observation=observation,
                decoder_response=response,
                snapshot_at=snapshot_text,
                observation_ordinal=observation_ordinal,
                global_record_ordinal=len(all_records) + len(observation_records),
                observation_record_ordinal=len(observation_records),
                record_kind=record_kind,
                payload=payload,
                raw_occurrence_sha256=raw_occurrence_sha256,
                expected_unit=expected_unit,
                representation_assignment=representation_assignment,
                response_residual_record_count=len(residual_source_item_sha256s),
                response_residual_record_root_sha256=residual_record_root_sha256,
            )
            record = LiveLosslessNodeRecordV1.build(**values)
            total_public_text_bytes += _public_row_text_bytes(record.to_row())
            if total_public_text_bytes > MAX_LIVE_LOSSLESS_TOTAL_CANONICAL_BYTES:
                _fail("live-lossless cumulative public text exceeds its bound")
            observation_records.append(record)
            if len(all_records) + len(observation_records) > MAX_LIVE_LOSSLESS_RECORDS:
                _fail("live-lossless record count exceeds its bound")

        all_records.extend(observation_records)

    records = tuple(all_records)
    validated = _validate_authority_record_inventory(
        records,
        expected_raw_authority_bundle_sha256=bundle.bundle_sha256,
    )
    receipt = LiveLosslessValueAuthorityReceiptV1.build(
        source_input_kind=LIVE_LOSSLESS_SOURCE_INPUT_KIND,
        representation_kind=LIVE_LOSSLESS_REPRESENTATION_KIND,
        response_residual_representation_kind=LIVE_RESPONSE_RESIDUAL_REPRESENTATION_KIND,
        node_schema_sha256=LIVE_LOSSLESS_NODE_SCHEMA_SHA256,
        raw_authority_bundle_sha256=bundle.bundle_sha256,
        selected_observation_count=validated.selected_observation_count,
        selected_observations_sha256=validated.selected_observations_sha256,
        expected_unit_count=validated.expected_units.unit_count,
        expected_unit_inventory_sha256=validated.expected_units.inventory_sha256,
        expected_unit_root_sha256=validated.expected_units.unit_root_sha256,
        representation_assignment_count=len(validated.assignments),
        representation_assignment_inventory_sha256=validated.assignment_inventory_sha256,
        response_residual_record_count=len(validated.residual_source_item_sha256s),
        response_residual_record_inventory_sha256=(validated.residual_record_inventory_sha256),
        response_residual_observation_count=validated.residual_observation_count,
        zero_response_residual_observation_count=validated.zero_residual_observation_count,
        response_residual_partition_inventory_sha256=(
            validated.residual_partition_inventory_sha256
        ),
        record_count=len(records),
        record_inventory_sha256=validated.record_inventory_sha256,
        result_declaration_count=validated.kind_counts["result_declaration"],
        result_occurrence_count=validated.kind_counts["result_occurrence"],
        node_count=validated.kind_counts["node"],
        field_cell_count=validated.kind_counts["field_cell"],
    )
    return LiveLosslessValueAuthorityV1(
        receipt=receipt,
        records=records,
        expected_units=validated.expected_units,
        representation_assignments=validated.assignments,
    )
