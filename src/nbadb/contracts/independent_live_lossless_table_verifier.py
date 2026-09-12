"""Dependency-pure verifier for the public live-lossless node relation.

This module deliberately does not import the live decoder, any extraction
adapter/projector, staging code, orchestration code, or parser-input bodies.  It
reconstructs the ordered tree and all receipt roots solely from exact built-in
public rows and externally supplied trust pins.
"""

from __future__ import annotations

import hashlib
import json
import math
import re
from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Final, Never, cast

from nbadb.contracts.live_lossless_value_authority import (
    LIVE_LOSSLESS_NODE_COLUMNS,
    LIVE_LOSSLESS_NODE_SCHEMA_SHA256,
    LIVE_LOSSLESS_REPRESENTATION_KIND,
    LIVE_LOSSLESS_SOURCE_INPUT_KIND,
    LIVE_LOSSLESS_TEXT_COLUMNS,
    LIVE_LOSSLESS_VALUE_AUTHORITY_KIND,
    LIVE_RESPONSE_RESIDUAL_REPRESENTATION_KIND,
    MAX_LIVE_LOSSLESS_ANOMALY_BYTES,
    MAX_LIVE_LOSSLESS_CANONICAL_BYTES,
    MAX_LIVE_LOSSLESS_DEPTH,
    MAX_LIVE_LOSSLESS_FIELD_CELLS,
    MAX_LIVE_LOSSLESS_HEADER_COUNT,
    MAX_LIVE_LOSSLESS_JSON_NODES,
    MAX_LIVE_LOSSLESS_JSON_PATH_BYTES,
    MAX_LIVE_LOSSLESS_NODES,
    MAX_LIVE_LOSSLESS_OBSERVATIONS,
    MAX_LIVE_LOSSLESS_RECORDS,
    MAX_LIVE_LOSSLESS_RESULT_OCCURRENCES,
    MAX_LIVE_LOSSLESS_RESULTS,
    MAX_LIVE_LOSSLESS_TOTAL_CANONICAL_BYTES,
    PUBLIC_VALUE_AUTHORITY_SCHEMA_VERSION,
    LiveLosslessValueAuthorityReceiptV1,
)
from nbadb.contracts.public_value_types import (
    MAX_PUBLIC_VALUE_EXPECTED_UNITS,
    ExpectedValueUnitInventoryV1,
    ExpectedValueUnitKindV1,
    ExpectedValueUnitV1,
    PublicValueRepresentationKindV1,
    PublicValueTypesError,
    ValueRepresentationAssignmentV1,
)

if TYPE_CHECKING:
    from collections.abc import Iterable, Mapping, Sequence

__all__ = [
    "IndependentLiveLosslessTableVerifierError",
    "verify_live_lossless_public_table",
]

_ORDERED_ROOT_CONTRACT: Final = "sha256-length-framed-ordered-root-v1"
_ROW_KIND: Final = "raw_nba_api_live_lossless_node_v1"
_RECORD_KINDS: Final = (
    "result_declaration",
    "result_occurrence",
    "node",
    "field_cell",
)
_RESULT_PRESENCES: Final = frozenset(
    {"present", "empty_array", "missing", "null", "mixed_absent", "not_observed_parent_empty"}
)
_NODE_PRESENCES: Final = frozenset({"present", "null", "empty_object", "empty_array", "missing"})
_VALUE_KINDS: Final = frozenset(
    {"object", "array", "null", "boolean", "integer", "number", "string", "missing"}
)
_CONTAINER_KINDS: Final = frozenset({"nba_api_live_json_array", "nba_api_live_json_object"})
_KEY_PRESENCES: Final = frozenset({"required", "optional", "optional_or_undocumented"})
_ANOMALY_CODES: Final = frozenset(
    {"additive_envelope_root", "reordered_envelope_root", "additive_field"}
)
_SHA256_RE = re.compile(r"[0-9a-f]{64}\Z")
_SAFE_ID_RE = re.compile(r"[A-Za-z0-9_][A-Za-z0-9_.:-]{0,511}\Z", flags=re.ASCII)
_CAMEL_ACRONYM_BOUNDARY_RE = re.compile(r"([A-Z]+)([A-Z][a-z])", flags=re.ASCII)
_CAMEL_WORD_BOUNDARY_RE = re.compile(r"([a-z0-9])([A-Z])", flags=re.ASCII)
_KEY_SEPARATOR_RE = re.compile(r"[^A-Za-z0-9]+", flags=re.ASCII)
_SENSITIVE_KEY_RE = re.compile(
    r"(?:authorization|proxy_authorization|authentication|cookie|set_cookie|credential|"
    r"secret|token|client_secret|client_key|access_token|refresh_token|id_token|api_key|"
    r"apikey|password|passwd|proxy_url|proxy_host|vpn_server|vpn_ip|vpn_password|"
    r"request_headers|response_headers|runner_path|workspace_path|local_path|file_path|"
    r"github_token|gh_token|pat|private_key|secret_key|personal_access_token|"
    r"ssh_private_key)\Z",
    flags=re.ASCII,
)
_GENERIC_SENSITIVE_KEY_COMPONENTS: Final = frozenset({"auth", "session", "secret", "token"})
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
_SECRET_RES = (
    re.compile(r"\bgh[opurs]_[A-Za-z0-9]{20,}\b", flags=re.ASCII),
    re.compile(r"\bAKIA[0-9A-Z]{16}\b", flags=re.ASCII),
    re.compile(r"\bxox[baprs]-[A-Za-z0-9-]{10,}\b", flags=re.ASCII),
    re.compile(r"\bAIza[0-9A-Za-z_-]{35}\b", flags=re.ASCII),
    re.compile(r"-----BEGIN (?:[A-Z0-9]+ )*PRIVATE KEY-----", flags=re.ASCII),
    re.compile(r"https?://[^/\s:@]+:[^/\s@]+@", flags=re.ASCII | re.IGNORECASE),
    re.compile(
        r"\beyJ[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}\b",
        flags=re.ASCII,
    ),
)

_RESULT_KEYS: Final = frozenset(
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
_OCCURRENCE_KEYS: Final = frozenset(
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
_NODE_KEYS: Final = frozenset(
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
_CELL_KEYS: Final = frozenset(
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
_COMMON_COLUMNS: Final = (
    "source_input_kind",
    "response_residual_record_count",
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


class IndependentLiveLosslessTableVerifierError(ValueError):
    """The public live-lossless table cannot reproduce its body-only receipt."""


def _fail(message: str) -> Never:
    raise IndependentLiveLosslessTableVerifierError(message)


def _sha(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _exact_sha(value: object, *, label: str) -> str:
    if type(value) is not str or _SHA256_RE.fullmatch(value) is None:
        _fail(f"{label} is not an exact lowercase SHA-256")
    return value


def _exact_int(value: object, *, label: str, maximum: int, positive: bool = False) -> int:
    if type(value) is not int or value < int(positive) or value > maximum:
        _fail(f"{label} is outside its exact integer bound")
    return value


def _normalized_key(value: str) -> str:
    separated = _CAMEL_ACRONYM_BOUNDARY_RE.sub(r"\1_\2", value)
    separated = _CAMEL_WORD_BOUNDARY_RE.sub(r"\1_\2", separated)
    return _KEY_SEPARATOR_RE.sub("_", separated).strip("_").lower()


def _reject_text(value: str, *, key: bool = False) -> None:
    normalized = _normalized_key(value)
    if key and (
        _SENSITIVE_KEY_RE.fullmatch(normalized) is not None
        or any(
            component in _GENERIC_SENSITIVE_KEY_COMPONENTS for component in normalized.split("_")
        )
    ):
        _fail("live-lossless public row contains secret-shaped material")
    stripped = value.strip()
    if (
        _AUTHORIZATION_HEADER_SECRET_RE.search(stripped) is not None
        or _BEARER_SECRET_RE.search(stripped) is not None
        or _BASIC_SECRET_RE.search(stripped) is not None
        or _LOCAL_PATH_VALUE_RE.search(value) is not None
        or any(pattern.search(value) is not None for pattern in _SECRET_RES)
    ):
        _fail("live-lossless public row contains secret-shaped material")


def _safe_id(value: object, *, label: str, key: bool = False) -> str:
    if type(value) is not str or _SAFE_ID_RE.fullmatch(value) is None:
        _fail(f"{label} is not an exact bounded public identifier")
    _reject_text(value, key=key)
    return value


def _validate_graph(value: object, *, maximum: int) -> None:
    stack: list[tuple[object, int]] = [(value, 0)]
    nodes = 0
    budget = 0
    while stack:
        item, depth = stack.pop()
        nodes += 1
        if nodes > MAX_LIVE_LOSSLESS_JSON_NODES or depth > MAX_LIVE_LOSSLESS_DEPTH:
            _fail("live-lossless public JSON exceeds its graph bound")
        if item is None:
            budget += 4
        elif type(item) is bool:
            budget += 5
        elif type(item) is int:
            if abs(item) > (1 << 63) - 1:
                _fail("live-lossless public JSON integer exceeds its bound")
            budget += len(str(item))
        elif type(item) is float:
            if not math.isfinite(item):
                _fail("live-lossless public JSON contains a non-finite number")
            budget += 32
        elif type(item) is str:
            try:
                budget += len(item.encode("utf-8", errors="strict"))
            except UnicodeEncodeError:
                raise IndependentLiveLosslessTableVerifierError(
                    "live-lossless public JSON contains invalid Unicode"
                ) from None
            _reject_text(item)
        elif type(item) is list:
            budget += 2
            stack.extend((child, depth + 1) for child in reversed(item))
        elif type(item) is dict:
            budget += 2
            for key, child in reversed(tuple(item.items())):
                if type(key) is not str:
                    _fail("live-lossless public JSON key is foreign")
                _reject_text(key, key=True)
                budget += len(key.encode("utf-8", errors="strict"))
                stack.append((child, depth + 1))
        else:
            _fail("live-lossless public JSON value type is foreign")
        if budget > maximum:
            _fail("live-lossless public JSON exceeds its byte bound")


def _canonical_bytes(value: object, *, maximum: int) -> bytes:
    _validate_graph(value, maximum=maximum)
    try:
        raw = json.dumps(
            value,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
            allow_nan=False,
        ).encode("utf-8", errors="strict")
    except (TypeError, ValueError, UnicodeEncodeError, RecursionError):
        raise IndependentLiveLosslessTableVerifierError(
            "live-lossless public value is not canonical JSON"
        ) from None
    if len(raw) > maximum:
        _fail("live-lossless public canonical bytes exceed their bound")
    return raw


def _canonical_sha(value: object) -> str:
    return _sha(_canonical_bytes(value, maximum=MAX_LIVE_LOSSLESS_CANONICAL_BYTES))


def _preflight_json_text(raw: bytes, *, label: str) -> None:
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
                _fail(f"{label} exceeds its depth bound")
        elif byte in {0x5D, 0x7D}:
            depth -= 1
            if depth < 0:
                _fail(f"{label} is invalid canonical JSON")
        elif byte == 0x2C:
            nodes += 1
        if nodes > MAX_LIVE_LOSSLESS_JSON_NODES:
            _fail(f"{label} exceeds its node bound")
    if in_string or escaped or depth != 0:
        _fail(f"{label} is invalid canonical JSON")


def _bounded_int(token: str) -> int:
    if len(token) > 64:
        _fail("live-lossless JSON integer token exceeds its bound")
    try:
        value = int(token)
    except ValueError:
        raise IndependentLiveLosslessTableVerifierError(
            "live-lossless JSON integer token is invalid"
        ) from None
    if abs(value) > (1 << 63) - 1:
        _fail("live-lossless JSON integer exceeds its bound")
    return value


def _bounded_float(token: str) -> float:
    if len(token) > 64:
        _fail("live-lossless JSON number token exceeds its bound")
    try:
        value = float(token)
    except ValueError:
        raise IndependentLiveLosslessTableVerifierError(
            "live-lossless JSON number token is invalid"
        ) from None
    if not math.isfinite(value):
        _fail("live-lossless JSON number is non-finite")
    return value


def _decode_json(
    value: object,
    *,
    label: str,
    require: type[list] | type[dict] | None,
) -> object:
    if type(value) is not str:
        _fail(f"{label} is not exact canonical JSON text")
    try:
        raw = value.encode("utf-8", errors="strict")
    except UnicodeEncodeError:
        raise IndependentLiveLosslessTableVerifierError(
            f"{label} is invalid canonical JSON"
        ) from None
    if not raw or len(raw) > MAX_LIVE_LOSSLESS_CANONICAL_BYTES:
        _fail(f"{label} exceeds its byte bound")
    _preflight_json_text(raw, label=label)

    def reject_pairs(pairs: list[tuple[str, object]]) -> dict[str, object]:
        output: dict[str, object] = {}
        for key, item in pairs:
            if key in output:
                _fail(f"{label} contains a duplicate key")
            output[key] = item
        return output

    def reject_constant(_token: str) -> Never:
        _fail(f"{label} contains a non-finite number")

    try:
        decoded = json.loads(
            raw,
            object_pairs_hook=reject_pairs,
            parse_int=_bounded_int,
            parse_float=_bounded_float,
            parse_constant=reject_constant,
        )
    except IndependentLiveLosslessTableVerifierError:
        raise
    except (json.JSONDecodeError, RecursionError, TypeError, ValueError):
        raise IndependentLiveLosslessTableVerifierError(
            f"{label} is invalid canonical JSON"
        ) from None
    if require is not None and type(decoded) is not require:
        _fail(f"{label} has the wrong JSON container type")
    if _canonical_bytes(decoded, maximum=MAX_LIVE_LOSSLESS_CANONICAL_BYTES) != raw:
        _fail(f"{label} is not canonical JSON")
    return decoded


def _ordered_root(*, kind: str, count: int, values: Iterable[str]) -> str:
    if type(kind) is not str or not kind:
        _fail("live-lossless ordered-root kind is invalid")
    _exact_int(count, label="live-lossless ordered-root count", maximum=MAX_LIVE_LOSSLESS_RECORDS)
    digest = hashlib.sha256()
    header = _canonical_bytes(
        {
            "schema_version": PUBLIC_VALUE_AUTHORITY_SCHEMA_VERSION,
            "contract": _ORDERED_ROOT_CONTRACT,
            "kind": kind,
            "count": count,
        },
        maximum=4_096,
    )
    digest.update(len(header).to_bytes(8, "big"))
    digest.update(header)
    seen = 0
    for value in values:
        _exact_sha(value, label="live-lossless ordered-root item")
        seen += 1
        if seen > count:
            _fail("live-lossless ordered root exceeds its denominator")
        digest.update(bytes.fromhex(value))
    if seen != count:
        _fail("live-lossless ordered root is incomplete")
    return digest.hexdigest()


def _exact_equal(left: object, right: object) -> bool:
    if type(left) is not type(right):
        return False
    if left is None:
        return True
    if type(left) in {str, int, float, bool}:
        return bool(left == right)
    if type(left) is list:
        left_list = cast("list[object]", left)
        right_list = cast("list[object]", right)
        return len(left_list) == len(right_list) and all(
            _exact_equal(a, b) for a, b in zip(left_list, right_list, strict=True)
        )
    if type(left) is tuple:
        left_tuple = left
        right_tuple = cast("tuple[object, ...]", right)
        return len(left_tuple) == len(right_tuple) and all(
            _exact_equal(a, b) for a, b in zip(left_tuple, right_tuple, strict=True)
        )
    if type(left) is dict:
        left_map = cast("dict[str, object]", left)
        right_map = cast("dict[str, object]", right)
        return tuple(left_map) == tuple(right_map) and all(
            _exact_equal(left_map[key], right_map[key]) for key in left_map
        )
    return False


def _load_rows(value: object) -> list[dict[str, object]]:
    if type(value) not in {list, tuple}:
        _fail("live-lossless public table must be an exact list or tuple")
    raw_rows = cast("Sequence[object]", value)
    if len(raw_rows) > MAX_LIVE_LOSSLESS_RECORDS:
        _fail("live-lossless public table count is outside its bound")
    expected_keys = set(LIVE_LOSSLESS_NODE_COLUMNS)
    preflight_rows: list[dict[str, object]] = []
    total_bytes = 0
    for raw_row in raw_rows:
        if type(raw_row) is not dict:
            _fail("live-lossless public row must be an exact built-in dict")
        mapping = cast("dict[object, object]", raw_row)
        if any(type(key) is not str for key in mapping):
            _fail("live-lossless public row key is foreign")
        row = cast("dict[str, object]", mapping)
        if set(row) != expected_keys or tuple(row) != LIVE_LOSSLESS_NODE_COLUMNS:
            _fail("live-lossless public row columns are missing, additive, or reordered")
        if type(row["schema_version"]) is not int or row["schema_version"] != 1:
            _fail("live-lossless public row schema version is invalid")
        if type(row["source_input_kind"]) is not str or (
            row["source_input_kind"] != LIVE_LOSSLESS_SOURCE_INPUT_KIND
        ):
            _fail("live-lossless public row source input is foreign")
        if type(row["representation_kind"]) is not str or row["representation_kind"] not in {
            LIVE_LOSSLESS_REPRESENTATION_KIND,
            LIVE_RESPONSE_RESIDUAL_REPRESENTATION_KIND,
        }:
            _fail("live-lossless public row representation is foreign")
        _validate_public_row_scalars(row)
        for column in LIVE_LOSSLESS_TEXT_COLUMNS:
            text = row[column]
            if text is None:
                continue
            if type(text) is not str:
                _fail("live-lossless public text column has a foreign value type")
            try:
                encoded = text.encode("utf-8", errors="strict")
            except UnicodeEncodeError:
                raise IndependentLiveLosslessTableVerifierError(
                    "live-lossless public text is not valid UTF-8"
                ) from None
            if (
                column == "decoder_anomaly_codes_json"
                and len(encoded) > MAX_LIVE_LOSSLESS_ANOMALY_BYTES
            ):
                _fail("live-lossless decoder anomaly inventory exceeds its byte bound")
            if (
                column in {"payload_json", "canonical_json"}
                and len(encoded) > MAX_LIVE_LOSSLESS_CANONICAL_BYTES
            ):
                _fail("live-lossless canonical text exceeds its per-value byte bound")
            total_bytes += len(encoded)
            if total_bytes > MAX_LIVE_LOSSLESS_TOTAL_CANONICAL_BYTES:
                _fail("live-lossless public table text exceeds its cumulative byte bound")
        preflight_rows.append(dict(row))

    rows: list[dict[str, object]] = []
    for row in preflight_rows:
        payload_text = cast("str", row["payload_json"])
        payload_raw = payload_text.encode("utf-8", errors="strict")
        payload = cast(
            "dict[str, object]",
            _decode_json(payload_text, label="payload_json", require=dict),
        )
        if row["payload_sha256"] != _sha(payload_raw):
            _fail("live-lossless public row payload digest is invalid")
        row_kind = row["record_kind"]
        if type(row_kind) is not str or row_kind not in _RECORD_KINDS:
            _fail("live-lossless public row kind is invalid")
        _validate_payload(row_kind, row, payload)
        identity = {
            "schema_version": 1,
            "kind": _ROW_KIND,
            **{
                column: row[column]
                for column in LIVE_LOSSLESS_NODE_COLUMNS
                if column not in {"schema_version", "record_sha256"}
            },
        }
        if row["record_sha256"] != _canonical_sha(identity):
            _fail("live-lossless public row digest is invalid")
        rows.append(row)
    return rows


def _validate_public_row_scalars(row: Mapping[str, object]) -> None:
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
        _exact_sha(row[name], label=name)
    if row["raw_occurrence_sha256"] is not None:
        _exact_sha(row["raw_occurrence_sha256"], label="raw_occurrence_sha256")
    source_sha = row["source_sha"]
    if type(source_sha) is not str or re.fullmatch(r"[0-9a-f]{40}", source_sha) is None:
        _fail("live-lossless source SHA is invalid")
    for name in (
        "chain_id",
        "lane_id",
        "endpoint_id",
        "endpoint_slug",
        "provider_call_role",
    ):
        _safe_id(row[name], label=name)
    for name, maximum, positive in (
        ("run_id", (1 << 63) - 1, True),
        ("run_attempt", (1 << 31) - 1, True),
        ("parser_input_length", MAX_LIVE_LOSSLESS_CANONICAL_BYTES, True),
        ("provider_call_ordinal", (1 << 63) - 1, False),
        ("retry_ordinal", (1 << 31) - 1, False),
        ("request_ordinal", (1 << 63) - 1, False),
        ("observation_ordinal", MAX_LIVE_LOSSLESS_OBSERVATIONS - 1, False),
        ("global_record_ordinal", MAX_LIVE_LOSSLESS_RECORDS - 1, False),
        ("observation_record_ordinal", MAX_LIVE_LOSSLESS_RECORDS - 1, False),
        ("expected_unit_ordinal", MAX_PUBLIC_VALUE_EXPECTED_UNITS - 1, False),
        ("response_residual_record_count", MAX_LIVE_LOSSLESS_RECORDS, False),
    ):
        _exact_int(row[name], label=name, maximum=maximum, positive=positive)
    if row["ownership_occurrence_ordinal"] is not None:
        _exact_int(
            row["ownership_occurrence_ordinal"],
            label="ownership_occurrence_ordinal",
            maximum=MAX_LIVE_LOSSLESS_RESULT_OCCURRENCES - 1,
        )
    ownership_kind = row["ownership_kind"]
    if type(ownership_kind) is not str or ownership_kind not in {
        "result_occurrence",
        "response_residual",
    }:
        _fail("live-lossless public row ownership kind is foreign")
    if ownership_kind == "result_occurrence":
        if (
            row["raw_occurrence_sha256"] is None
            or row["ownership_occurrence_ordinal"] is None
            or row["representation_kind"] != LIVE_LOSSLESS_REPRESENTATION_KIND
        ):
            _fail("live-lossless occurrence ownership shape is invalid")
    elif (
        row["raw_occurrence_sha256"] is not None
        or row["ownership_occurrence_ordinal"] is not None
        or row["representation_kind"] != LIVE_RESPONSE_RESIDUAL_REPRESENTATION_KIND
        or row["record_kind"] != "node"
        or row["response_residual_record_count"] == 0
    ):
        _fail("live-lossless response-residual ownership shape is invalid")
    empty_residual_root = _ordered_root(
        kind="live_lossless_response_residual_source_items_v1",
        count=0,
        values=(),
    )
    if (row["response_residual_record_count"] == 0) != (
        row["response_residual_record_root_sha256"] == empty_residual_root
    ):
        _fail("live-lossless response-residual zero proof is inconsistent")
    if row["page_ordinal"] is not None:
        _exact_int(row["page_ordinal"], label="page_ordinal", maximum=(1 << 63) - 1)
    snapshot = row["live_snapshot_at"]
    if type(snapshot) is not str:
        _fail("live_snapshot_at is not an exact canonical UTC timestamp")
    try:
        parsed = datetime.fromisoformat(snapshot.replace("Z", "+00:00"))
    except ValueError:
        raise IndependentLiveLosslessTableVerifierError(
            "live_snapshot_at is not an exact canonical UTC timestamp"
        ) from None
    expected = parsed.isoformat(timespec="microseconds").replace("+00:00", "Z")
    if parsed.tzinfo is not UTC or snapshot != expected:
        _fail("live_snapshot_at is not an exact canonical UTC timestamp")
    for name, maximum in (
        ("result_set_ordinal", 63),
        ("result_set_occurrence", 2_000_000 - 1),
        ("node_ordinal", 2_000_000 - 1),
        ("parent_node_ordinal", 2_000_000 - 1),
        ("field_ordinal", 1_023),
        ("row_ordinal", 2_000_000 - 1),
    ):
        if row[name] is not None:
            _exact_int(row[name], label=name, maximum=maximum)
    for name in ("result_set_name", "field_name", "json_path"):
        value = row[name]
        if value is not None and (type(value) is not str or not value):
            _fail(f"{name} is not an exact public string")
        if type(value) is str:
            if name in {"result_set_name", "field_name"}:
                _safe_id(value, label=name, key=name == "field_name")
            else:
                if len(value.encode("utf-8")) > MAX_LIVE_LOSSLESS_JSON_PATH_BYTES:
                    _fail("live-lossless JSON path exceeds its byte bound")
                _reject_text(value)


def _validate_payload(kind: str, row: Mapping[str, object], payload: Mapping[str, object]) -> None:
    expected_keys = {
        "result_declaration": _RESULT_KEYS,
        "result_occurrence": _OCCURRENCE_KEYS,
        "node": _NODE_KEYS,
        "field_cell": _CELL_KEYS,
    }[kind]
    if set(payload) != expected_keys:
        _fail("live-lossless payload fields are missing, additive, or foreign")
    _validate_payload_types(kind, payload)
    digest_name = {
        "result_declaration": "result_set_sha256",
        "result_occurrence": "occurrence_sha256",
        "node": "node_sha256",
        "field_cell": "cell_sha256",
    }[kind]
    digest = payload[digest_name]
    _exact_sha(digest, label="live-lossless source item digest")
    identity = {key: payload[key] for key in payload if key != digest_name}
    if digest != _canonical_sha(identity) or row["source_item_sha256"] != digest:
        _fail("live-lossless source item digest is invalid")

    result_name = (
        payload["name"]
        if kind == "result_declaration"
        else payload["result_set_name"]
        if kind in {"result_occurrence", "node"}
        else payload["owner_result_set_name"]
    )
    result_ordinal = (
        payload["ordinal"]
        if kind == "result_declaration"
        else payload["result_set_ordinal"]
        if kind in {"result_occurrence", "node"}
        else payload["owner_result_set_ordinal"]
    )
    occurrence = (
        None
        if kind == "result_declaration"
        else payload["occurrence_ordinal"]
        if kind == "result_occurrence"
        else payload["result_set_occurrence"]
        if kind == "node"
        else payload["owner_result_set_occurrence"]
    )
    node = payload.get("node_ordinal") if kind != "result_declaration" else None
    parent = payload.get("parent_node_ordinal") if kind == "node" else None
    field = payload.get("field_name") if kind == "field_cell" else None
    field_ordinal = payload.get("field_ordinal") if kind == "field_cell" else None
    row_ordinal = (
        payload.get("result_set_row_ordinal")
        if kind == "node"
        else payload.get("owner_row_ordinal")
        if kind == "field_cell"
        else None
    )
    path = (
        payload["json_path"]
        if kind in {"result_declaration", "result_occurrence", "node"}
        else payload["concrete_json_path"]
    )
    presence = payload["presence"] if kind == "result_declaration" else payload.get("presence_kind")
    value_kind = payload.get("value_kind") if kind in {"node", "field_cell"} else None
    canonical = payload.get("canonical_json") if kind in {"node", "field_cell"} else None
    value_sha = payload.get("value_sha256") if kind != "result_declaration" else None
    actual = (
        row["result_set_name"],
        row["result_set_ordinal"],
        row["result_set_occurrence"],
        row["node_ordinal"],
        row["parent_node_ordinal"],
        row["field_name"],
        row["field_ordinal"],
        row["row_ordinal"],
        row["json_path"],
        row["presence_kind"],
        row["value_kind"],
        row["canonical_json"],
        row["value_sha256"],
    )
    expected = (
        result_name,
        result_ordinal,
        occurrence,
        node,
        parent,
        field,
        field_ordinal,
        row_ordinal,
        path,
        presence,
        value_kind,
        canonical,
        value_sha,
    )
    if not _exact_equal(actual, expected):
        _fail("live-lossless public selectors differ from their payload")
    canonical_text = row["canonical_json"]
    canonical_digest = row["canonical_json_sha256"]
    if (canonical_text is None) != (canonical_digest is None):
        _fail("live-lossless canonical value digest is incomplete")
    if canonical_text is not None:
        _decode_scalar_or_container(canonical_text)
        if canonical_digest != _sha(cast("str", canonical_text).encode("utf-8")):
            _fail("live-lossless canonical value digest is invalid")
    if kind != "node" and row["raw_occurrence_sha256"] is None:
        _fail("live-lossless typed record omits its raw occurrence binding")
    if row["raw_occurrence_sha256"] is not None:
        _exact_sha(row["raw_occurrence_sha256"], label="raw_occurrence_sha256")


def _validate_payload_types(kind: str, payload: Mapping[str, object]) -> None:
    for name, value in payload.items():
        if name.endswith("_sha256"):
            _exact_sha(value, label=f"payload {name}")
    integer_maxima: dict[str, int] = {
        "container_count": MAX_LIVE_LOSSLESS_RESULT_OCCURRENCES,
        "field_cell_count": MAX_LIVE_LOSSLESS_FIELD_CELLS,
        "missing_count": MAX_LIVE_LOSSLESS_RESULT_OCCURRENCES,
        "null_count": MAX_LIVE_LOSSLESS_RESULT_OCCURRENCES,
        "ordinal": MAX_LIVE_LOSSLESS_RESULTS - 1,
        "parent_observation_count": MAX_LIVE_LOSSLESS_RESULT_OCCURRENCES,
        "result_occurrence_count": MAX_LIVE_LOSSLESS_RESULT_OCCURRENCES,
        "row_count": MAX_LIVE_LOSSLESS_NODES,
        "value_cell_count": MAX_LIVE_LOSSLESS_FIELD_CELLS,
        "global_ordinal": MAX_LIVE_LOSSLESS_RESULT_OCCURRENCES - 1,
        "node_ordinal": MAX_LIVE_LOSSLESS_NODES - 1,
        "occurrence_ordinal": MAX_LIVE_LOSSLESS_RESULT_OCCURRENCES - 1,
        "result_set_ordinal": MAX_LIVE_LOSSLESS_RESULTS - 1,
        "depth": MAX_LIVE_LOSSLESS_DEPTH,
        "cell_ordinal": MAX_LIVE_LOSSLESS_FIELD_CELLS - 1,
        "context_result_set_occurrence": MAX_LIVE_LOSSLESS_RESULT_OCCURRENCES - 1,
        "context_result_set_ordinal": MAX_LIVE_LOSSLESS_RESULTS - 1,
        "field_ordinal": MAX_LIVE_LOSSLESS_HEADER_COUNT - 1,
        "owner_result_set_occurrence": MAX_LIVE_LOSSLESS_RESULT_OCCURRENCES - 1,
        "owner_result_set_ordinal": MAX_LIVE_LOSSLESS_RESULTS - 1,
    }
    integer_fields = {
        "result_declaration": (
            "container_count",
            "field_cell_count",
            "missing_count",
            "null_count",
            "ordinal",
            "parent_observation_count",
            "result_occurrence_count",
            "row_count",
            "value_cell_count",
        ),
        "result_occurrence": (
            "global_ordinal",
            "node_ordinal",
            "occurrence_ordinal",
            "result_set_ordinal",
            "row_count",
        ),
        "node": ("depth", "node_ordinal"),
        "field_cell": (
            "cell_ordinal",
            "context_result_set_occurrence",
            "context_result_set_ordinal",
            "field_ordinal",
            "node_ordinal",
            "owner_result_set_occurrence",
            "owner_result_set_ordinal",
        ),
    }[kind]
    for name in integer_fields:
        _exact_int(payload[name], label=f"payload {name}", maximum=integer_maxima[name])
    optional_maxima = {
        "parent_result_set_ordinal": MAX_LIVE_LOSSLESS_RESULTS - 1,
        "array_ordinal": MAX_LIVE_LOSSLESS_NODES - 1,
        "contract_field_ordinal": MAX_LIVE_LOSSLESS_HEADER_COUNT - 1,
        "object_key_ordinal": MAX_LIVE_LOSSLESS_NODES - 1,
        "parent_node_ordinal": MAX_LIVE_LOSSLESS_NODES - 1,
        "result_set_occurrence": MAX_LIVE_LOSSLESS_RESULT_OCCURRENCES - 1,
        "result_set_ordinal": MAX_LIVE_LOSSLESS_RESULTS - 1,
        "result_set_row_ordinal": MAX_LIVE_LOSSLESS_NODES - 1,
        "owner_row_ordinal": MAX_LIVE_LOSSLESS_NODES - 1,
    }
    optional_integer_fields = {
        "result_declaration": (),
        "result_occurrence": ("parent_result_set_ordinal",),
        "node": (
            "array_ordinal",
            "contract_field_ordinal",
            "object_key_ordinal",
            "parent_node_ordinal",
            "result_set_occurrence",
            "result_set_ordinal",
            "result_set_row_ordinal",
        ),
        "field_cell": ("owner_row_ordinal",),
    }[kind]
    for name in optional_integer_fields:
        if payload[name] is not None:
            _exact_int(payload[name], label=f"payload {name}", maximum=optional_maxima[name])
    if (
        kind == "node"
        and payload["known_contract_field"] is not None
        and type(payload["known_contract_field"]) is not bool
    ):
        _fail("payload known-contract-field flag is not exact")
    required_strings = {
        "result_declaration": ("container_kind", "json_path", "name", "presence"),
        "result_occurrence": (
            "container_kind",
            "json_path",
            "presence_kind",
            "result_set_name",
        ),
        "node": ("json_path", "presence_kind", "value_kind"),
        "field_cell": (
            "concrete_json_path",
            "context_result_set_name",
            "field_json_path",
            "field_name",
            "key_presence",
            "owner_result_set_name",
            "presence_kind",
            "value_kind",
        ),
    }[kind]
    for name in required_strings:
        value = payload[name]
        if type(value) is not str or not value:
            _fail(f"payload {name} is not an exact nonempty string")
        if name in {
            "name",
            "result_set_name",
            "owner_result_set_name",
            "context_result_set_name",
            "field_name",
            "container_kind",
            "presence",
            "presence_kind",
            "value_kind",
            "key_presence",
        }:
            _safe_id(value, label=f"payload {name}", key=name == "field_name")
        else:
            if (
                not value.startswith("$")
                or len(value.encode("utf-8")) > MAX_LIVE_LOSSLESS_JSON_PATH_BYTES
            ):
                _fail(f"payload {name} exceeds its path byte bound")
            _reject_text(value)
    if kind == "result_declaration" and not cast("str", payload["json_path"]).startswith("$."):
        _fail("payload result declaration path is not decoder-exact")
    optional_strings = {
        "result_declaration": ("parent_field_name", "parent_result_set_name"),
        "result_occurrence": ("parent_result_set_name",),
        "node": (
            "canonical_json",
            "container_kind",
            "contract_json_path",
            "object_key",
            "parent_json_path",
            "result_set_name",
        ),
        "field_cell": ("canonical_json",),
    }[kind]
    for name in optional_strings:
        value = payload[name]
        if value is not None and (type(value) is not str or not value):
            _fail(f"payload {name} is not an exact optional string")
        if type(value) is str:
            if name in {"parent_field_name", "parent_result_set_name", "result_set_name"}:
                _safe_id(value, label=f"payload {name}", key=name == "parent_field_name")
            elif name == "object_key":
                _reject_text(value, key=True)
            elif name in {"contract_json_path", "parent_json_path"}:
                if (
                    not value.startswith("$")
                    or len(value.encode("utf-8")) > MAX_LIVE_LOSSLESS_JSON_PATH_BYTES
                ):
                    _fail(f"payload {name} exceeds its path byte bound")
                _reject_text(value)
    if kind == "result_declaration":
        headers = payload["ordered_headers"]
        if (
            type(headers) is not list
            or len(headers) > MAX_LIVE_LOSSLESS_HEADER_COUNT
            or any(type(item) is not str or not item for item in headers)
            or len(set(cast("list[str]", headers))) != len(headers)
        ):
            _fail("payload ordered headers are not exact strings")
        for header in cast("list[str]", headers):
            _safe_id(header, label="payload header", key=True)
        if payload["container_kind"] not in _CONTAINER_KINDS:
            _fail("payload result container kind is invalid")
        if payload["presence"] not in _RESULT_PRESENCES:
            _fail("payload result presence is invalid")
    elif kind == "result_occurrence":
        if payload["container_kind"] not in _CONTAINER_KINDS:
            _fail("payload occurrence container kind is invalid")
        if payload["presence_kind"] not in _NODE_PRESENCES:
            _fail("payload occurrence presence is invalid")
        presence = payload["presence_kind"]
        container = payload["container_kind"]
        row_count = cast("int", payload["row_count"])
        if presence in {"missing", "null"} and row_count != 0:
            _fail("payload absent occurrence carries rows")
        if presence == "empty_array" and (container != "nba_api_live_json_array" or row_count != 0):
            _fail("payload empty-array occurrence algebra is invalid")
        if presence == "empty_object" and (
            container != "nba_api_live_json_object" or row_count != 1
        ):
            _fail("payload empty-object occurrence algebra is invalid")
        if presence == "present" and (
            (container == "nba_api_live_json_array" and row_count == 0)
            or (container == "nba_api_live_json_object" and row_count != 1)
        ):
            _fail("payload present occurrence row algebra is invalid")
    elif kind == "node":
        if (
            payload["presence_kind"] not in _NODE_PRESENCES
            or payload["value_kind"] not in _VALUE_KINDS
        ):
            _fail("payload node presence/value kind is invalid")
        if (
            payload["container_kind"] is not None
            and payload["container_kind"] not in _CONTAINER_KINDS
        ):
            _fail("payload node container kind is invalid")
        context = (
            payload["result_set_name"],
            payload["result_set_ordinal"],
            payload["result_set_occurrence"],
            payload["contract_json_path"],
        )
        if payload["container_kind"] is not None and all(item is None for item in context):
            _fail("payload matched node omits its result context")
    else:
        if (
            payload["presence_kind"] not in _NODE_PRESENCES
            or payload["value_kind"] not in _VALUE_KINDS
            or payload["key_presence"] not in _KEY_PRESENCES
        ):
            _fail("payload field-cell semantics are invalid")


def _decode_scalar_or_container(value: object) -> object:
    return _decode_json(value, label="canonical_json", require=None)


def _reconstruct_nodes(nodes: Sequence[Mapping[str, object]]) -> dict[int, object]:
    if not nodes:
        _fail("live-lossless public observation has no root node")
    values: dict[int, object] = {}
    child_counts: Counter[int] = Counter()
    object_ordinals: defaultdict[int, list[int]] = defaultdict(list)
    for expected_ordinal, row in enumerate(nodes):
        payload = cast("dict[str, object]", row["_payload"])
        ordinal = payload["node_ordinal"]
        if type(ordinal) is not int or ordinal != expected_ordinal:
            _fail("live-lossless node ordinals are not exact and contiguous")
        presence = payload["presence_kind"]
        value_kind = payload["value_kind"]
        canonical = payload["canonical_json"]
        if presence == "missing":
            value: object = None
        elif value_kind == "object":
            value = {}
        elif value_kind == "array":
            value = []
        else:
            value = _decode_scalar_or_container(canonical)
        if ordinal == 0:
            if (
                any(
                    payload[name] is not None
                    for name in (
                        "parent_node_ordinal",
                        "parent_json_path",
                        "object_key",
                        "object_key_ordinal",
                        "array_ordinal",
                    )
                )
                or payload["json_path"] != "$"
                or payload["depth"] != 0
            ):
                _fail("live-lossless root node edge is invalid")
        else:
            parent_ordinal = payload["parent_node_ordinal"]
            if type(parent_ordinal) is not int or parent_ordinal < 0 or parent_ordinal >= ordinal:
                _fail("live-lossless node parent ordinal is invalid")
            parent_row = cast("dict[str, object]", nodes[parent_ordinal]["_payload"])
            parent = values[parent_ordinal]
            if (
                payload["parent_json_path"] != parent_row["json_path"]
                or type(payload["depth"]) is not int
                or payload["depth"] != cast("int", parent_row["depth"]) + 1
            ):
                _fail("live-lossless node parent path/depth is invalid")
            if type(parent) is dict:
                key = payload["object_key"]
                key_ordinal = payload["object_key_ordinal"]
                if type(key) is not str or payload["array_ordinal"] is not None:
                    _fail("live-lossless object edge is invalid")
                expected_path = f"{parent_row['json_path']}[{json.dumps(key, ensure_ascii=False)}]"
                if payload["json_path"] != expected_path:
                    _fail("live-lossless object child path is invalid")
                if presence != "missing":
                    if type(key_ordinal) is not int:
                        _fail("live-lossless object child ordinal is invalid")
                    object_ordinals[parent_ordinal].append(key_ordinal)
                    cast("dict[str, object]", parent)[key] = value
                    child_counts[parent_ordinal] += 1
                elif key_ordinal is not None:
                    _fail("live-lossless missing object edge has an ordinal")
            elif type(parent) is list:
                array_ordinal = payload["array_ordinal"]
                if (
                    type(array_ordinal) is not int
                    or array_ordinal != len(cast("list[object]", parent))
                    or payload["object_key"] is not None
                    or payload["object_key_ordinal"] is not None
                    or presence == "missing"
                    or payload["json_path"] != f"{parent_row['json_path']}[{array_ordinal}]"
                ):
                    _fail("live-lossless array edge is invalid")
                cast("list[object]", parent).append(value)
                child_counts[parent_ordinal] += 1
            else:
                _fail("live-lossless scalar node has a child")
        values[ordinal] = value
    if any(ordinals != list(range(len(ordinals))) for ordinals in object_ordinals.values()):
        _fail("live-lossless object-key ordinals are not contiguous")
    for row in nodes:
        payload = cast("dict[str, object]", row["_payload"])
        children = child_counts[cast("int", payload["node_ordinal"])]
        presence = payload["presence_kind"]
        value_kind = payload["value_kind"]
        canonical = payload["canonical_json"]
        ordinal = cast("int", payload["node_ordinal"])
        if presence == "missing" and (value_kind != "missing" or canonical is not None or children):
            _fail("live-lossless missing-node algebra is invalid")
        if presence == "null" and (value_kind != "null" or canonical != "null" or children):
            _fail("live-lossless null-node algebra is invalid")
        if presence == "empty_object" and (value_kind != "object" or canonical != "{}" or children):
            _fail("live-lossless empty-object algebra is invalid")
        if presence == "empty_array" and (value_kind != "array" or canonical != "[]" or children):
            _fail("live-lossless empty-array algebra is invalid")
        if presence == "present":
            if value_kind == "null":
                _fail("live-lossless present-node algebra is invalid")
            if value_kind in {"object", "array"} and (canonical is not None or not children):
                _fail("live-lossless present-container algebra is invalid")
            if value_kind not in {"object", "array"} and (type(canonical) is not str or children):
                _fail("live-lossless present-scalar algebra is invalid")
        digest_payload: object = (
            {"presence": "missing"}
            if presence == "missing"
            else {"presence": presence, "value": values[ordinal]}
        )
        if payload["value_sha256"] != _canonical_sha(digest_payload):
            _fail("live-lossless node value digest differs from reconstructed value")
    return values


@dataclass(frozen=True, slots=True)
class _ObservationVerification:
    receipt_sha256: str
    units: tuple[ExpectedValueUnitV1, ...]
    assignments: tuple[ValueRepresentationAssignmentV1, ...]
    residual_source_item_sha256s: tuple[str, ...]
    residual_record_root_sha256: str
    residual_partition_sha256: str


def _unit_assignment_from_row(
    row: Mapping[str, object],
) -> tuple[ExpectedValueUnitV1, ValueRepresentationAssignmentV1]:
    try:
        unit = ExpectedValueUnitV1(
            unit_sha256=cast("str", row["expected_unit_sha256"]),
            raw_authority_bundle_sha256=cast("str", row["raw_authority_bundle_sha256"]),
            unit_ordinal=cast("int", row["expected_unit_ordinal"]),
            observation_sha256=cast("str", row["observation_sha256"]),
            observation_ordinal=cast("int", row["observation_ordinal"]),
            unit_kind=cast("ExpectedValueUnitKindV1", row["ownership_kind"]),
            occurrence_sha256=cast("str | None", row["raw_occurrence_sha256"]),
            occurrence_ordinal=cast("int | None", row["ownership_occurrence_ordinal"]),
        )
        assignment = ValueRepresentationAssignmentV1(
            assignment_sha256=cast("str", row["representation_assignment_sha256"]),
            raw_authority_bundle_sha256=cast("str", row["raw_authority_bundle_sha256"]),
            unit_sha256=unit.unit_sha256,
            unit_ordinal=unit.unit_ordinal,
            source_input_kind=LIVE_LOSSLESS_SOURCE_INPUT_KIND,
            representation_kind=cast("PublicValueRepresentationKindV1", row["representation_kind"]),
        ).validate_for_unit(unit)
    except PublicValueTypesError as exc:
        raise IndependentLiveLosslessTableVerifierError(
            "live-lossless public-value ownership/raw binding is invalid"
        ) from exc
    return unit, assignment


def _validate_observation(
    rows: Sequence[dict[str, object]],
) -> _ObservationVerification:
    common = tuple(rows[0][name] for name in _COMMON_COLUMNS)
    if any(tuple(row[name] for name in _COMMON_COLUMNS) != common for row in rows[1:]):
        _fail("live-lossless observation rows disagree on source identity")
    if tuple(row["observation_record_ordinal"] for row in rows) != tuple(range(len(rows))):
        _fail("live-lossless observation record ordinals are not contiguous")
    category_order = {kind: index for index, kind in enumerate(_RECORD_KINDS)}
    if tuple(category_order[cast("str", row["record_kind"])] for row in rows) != tuple(
        sorted(category_order[cast("str", row["record_kind"])] for row in rows)
    ):
        _fail("live-lossless record-kind partitions are reordered")

    enriched: list[dict[str, object]] = []
    for row in rows:
        item = dict(row)
        item["_payload"] = _decode_json(item["payload_json"], label="payload_json", require=dict)
        enriched.append(item)
    results = [item for item in enriched if item["record_kind"] == "result_declaration"]
    occurrences = [item for item in enriched if item["record_kind"] == "result_occurrence"]
    nodes = [item for item in enriched if item["record_kind"] == "node"]
    cells = [item for item in enriched if item["record_kind"] == "field_cell"]
    if not results or not occurrences or not nodes:
        _fail("live-lossless observation omits a mandatory typed partition")
    if (
        len(results) > MAX_LIVE_LOSSLESS_RESULTS
        or len(occurrences) > MAX_LIVE_LOSSLESS_RESULT_OCCURRENCES
        or len(nodes) > MAX_LIVE_LOSSLESS_NODES
        or len(cells) > MAX_LIVE_LOSSLESS_FIELD_CELLS
    ):
        _fail("live-lossless observation record-kind count exceeds its bound")

    result_payloads = [cast("dict[str, object]", item["_payload"]) for item in results]
    if tuple(item["ordinal"] for item in result_payloads) != tuple(range(len(results))):
        _fail("live-lossless result declarations are not contiguous")
    residual_rows = tuple(
        item for item in enriched if item["ownership_kind"] == "response_residual"
    )
    residual_source_item_sha256s = tuple(
        cast("str", item["source_item_sha256"]) for item in residual_rows
    )
    residual_record_root_sha256 = _ordered_root(
        kind="live_lossless_response_residual_source_items_v1",
        count=len(residual_source_item_sha256s),
        values=residual_source_item_sha256s,
    )
    if any(
        item["response_residual_record_count"] != len(residual_rows)
        or item["response_residual_record_root_sha256"] != residual_record_root_sha256
        for item in enriched
    ):
        _fail("live-lossless response-residual partition is not exact")

    units: list[ExpectedValueUnitV1] = []
    assignments: list[ValueRepresentationAssignmentV1] = []
    owner_bindings: dict[
        str | None,
        tuple[ExpectedValueUnitV1, ValueRepresentationAssignmentV1],
    ] = {}
    for occurrence_ordinal, row in enumerate(results):
        if (
            row["ownership_kind"] != "result_occurrence"
            or row["ownership_occurrence_ordinal"] != occurrence_ordinal
            or row["raw_occurrence_sha256"] is None
            or row["raw_occurrence_sha256"] in owner_bindings
        ):
            _fail("live-lossless declaration ownership order is not exact")
        unit, assignment = _unit_assignment_from_row(row)
        units.append(unit)
        assignments.append(assignment)
        owner_bindings[cast("str", row["raw_occurrence_sha256"])] = (unit, assignment)
    if residual_rows:
        response_unit, response_assignment = _unit_assignment_from_row(residual_rows[0])
        if response_unit.unit_kind != "response_residual":
            _fail("live-lossless residual partition has a foreign expected-unit kind")
        units.append(response_unit)
        assignments.append(response_assignment)
        owner_bindings[None] = (response_unit, response_assignment)
    for row in enriched:
        binding = owner_bindings.get(cast("str | None", row["raw_occurrence_sha256"]))
        if binding is None:
            _fail("live-lossless row references an unrepresented owner")
        unit, assignment = _unit_assignment_from_row(row)
        if not _exact_equal(
            (unit.to_row(), assignment.to_row()),
            (binding[0].to_row(), binding[1].to_row()),
        ):
            _fail("live-lossless owner rows disagree on their central assignment")
    residual_partition_sha256 = _canonical_sha(
        {
            "schema_version": PUBLIC_VALUE_AUTHORITY_SCHEMA_VERSION,
            "kind": "live_lossless_response_residual_partition_v1",
            "observation_sha256": rows[0]["observation_sha256"],
            "observation_ordinal": rows[0]["observation_ordinal"],
            "record_count": len(residual_rows),
            "record_inventory_sha256": residual_record_root_sha256,
        }
    )
    result_by_name = {cast("str", item["name"]): item for item in result_payloads}
    if len(result_by_name) != len(result_payloads):
        _fail("live-lossless result declaration names are duplicated")
    for result in result_payloads:
        parent_name = result["parent_result_set_name"]
        parent_field = result["parent_field_name"]
        if parent_name is None:
            if parent_field is not None or result["parent_observation_count"] != 1:
                _fail("live-lossless root result parent denominator is invalid")
            continue
        parent = result_by_name.get(cast("str", parent_name))
        if (
            parent is None
            or type(parent_field) is not str
            or cast("int", parent["ordinal"]) >= cast("int", result["ordinal"])
            or parent_field not in cast("list[object]", parent["ordered_headers"])
            or result["json_path"] != f"{parent['json_path']}.{parent_field}"
            or result["parent_observation_count"] != parent["row_count"]
        ):
            _fail("live-lossless nested result parent contract is invalid")
    occurrence_payloads = [cast("dict[str, object]", item["_payload"]) for item in occurrences]
    if tuple(item["global_ordinal"] for item in occurrence_payloads) != tuple(
        range(len(occurrences))
    ):
        _fail("live-lossless concrete occurrence ordinals are not contiguous")
    occurrence_counter: Counter[str] = Counter()
    occurrence_by_node: dict[int, dict[str, object]] = {}
    for row, occurrence in zip(occurrences, occurrence_payloads, strict=True):
        name = occurrence["result_set_name"]
        if type(name) is not str or name not in result_by_name:
            _fail("live-lossless occurrence references an undeclared result")
        declared = result_by_name[name]
        parent_name = declared["parent_result_set_name"]
        parent = None if parent_name is None else result_by_name.get(cast("str", parent_name))
        if parent_name is not None and parent is None:
            _fail("live-lossless occurrence references an undeclared parent result")
        expected_parent_ordinal = None if parent is None else parent["ordinal"]
        if (
            occurrence["result_set_ordinal"] != declared["ordinal"]
            or occurrence["container_kind"] != declared["container_kind"]
            or occurrence["parent_result_set_name"] != declared["parent_result_set_name"]
            or occurrence["parent_result_set_ordinal"] != expected_parent_ordinal
            or occurrence["occurrence_ordinal"] != occurrence_counter[name]
            or row["raw_occurrence_sha256"]
            != next(
                result_row["raw_occurrence_sha256"]
                for result_row in results
                if result_row["result_set_name"] == name
            )
        ):
            _fail("live-lossless occurrence differs from its declaration/raw binding")
        occurrence_counter[name] += 1
        node_ordinal = occurrence["node_ordinal"]
        if type(node_ordinal) is not int or node_ordinal in occurrence_by_node:
            _fail("live-lossless occurrence node binding is invalid")
        occurrence_by_node[node_ordinal] = occurrence

    reconstructed_values = _reconstruct_nodes(nodes)
    if type(reconstructed_values[0]) is not dict:
        _fail("live-lossless reconstructed response root is not an object")
    node_payloads = [cast("dict[str, object]", item["_payload"]) for item in nodes]
    node_paths = [item["json_path"] for item in node_payloads]
    if len(set(cast("list[str]", node_paths))) != len(node_paths):
        _fail("live-lossless node JSON paths are duplicated")
    occurrence_keys = {
        (
            item["result_set_name"],
            item["result_set_ordinal"],
            item["occurrence_ordinal"],
        )
        for item in occurrence_payloads
    }
    raw_by_result = {item["result_set_name"]: item["raw_occurrence_sha256"] for item in results}
    for node in node_payloads:
        node_ordinal = cast("int", node["node_ordinal"])
        matched = occurrence_by_node.get(node_ordinal)
        if matched is not None:
            declaration = result_by_name[cast("str", matched["result_set_name"])]
            reconstructed = reconstructed_values[node_ordinal]
            expected_context = (
                matched["result_set_name"],
                matched["result_set_ordinal"],
                matched["occurrence_ordinal"],
                declaration["json_path"],
                0 if type(reconstructed) is dict else None,
            )
        elif node_ordinal == 0:
            expected_context = (None, None, None, None, None)
        else:
            parent_ordinal = cast("int", node["parent_node_ordinal"])
            parent = node_payloads[parent_ordinal]
            row_ordinal = parent["result_set_row_ordinal"]
            if parent_ordinal in occurrence_by_node and parent["value_kind"] == "array":
                row_ordinal = node["array_ordinal"]
            expected_context = (
                parent["result_set_name"],
                parent["result_set_ordinal"],
                parent["result_set_occurrence"],
                parent["contract_json_path"],
                row_ordinal,
            )
        if not _exact_equal(
            (
                node["result_set_name"],
                node["result_set_ordinal"],
                node["result_set_occurrence"],
                node["contract_json_path"],
                node["result_set_row_ordinal"],
            ),
            expected_context,
        ):
            _fail("live-lossless node result context is not decoder-exact")
    for row, node in zip(nodes, node_payloads, strict=True):
        context = (
            node["result_set_name"],
            node["result_set_ordinal"],
            node["result_set_occurrence"],
            node["contract_json_path"],
        )
        if all(item is None for item in context):
            if row["raw_occurrence_sha256"] is not None:
                _fail("live-lossless envelope node fabricated a raw occurrence binding")
            continue
        if any(item is None for item in context):
            _fail("live-lossless node result context is partial")
        name = cast("str", node["result_set_name"])
        declaration = result_by_name.get(name)
        if (
            declaration is None
            or node["result_set_ordinal"] != declaration["ordinal"]
            or (
                node["result_set_name"],
                node["result_set_ordinal"],
                node["result_set_occurrence"],
            )
            not in occurrence_keys
            or row["raw_occurrence_sha256"] != raw_by_result[name]
        ):
            _fail("live-lossless node context differs from occurrence/declaration authority")
    matched_nodes = {
        cast("int", item["node_ordinal"])
        for item in node_payloads
        if item["container_kind"] is not None
    }
    if matched_nodes != set(occurrence_by_node):
        _fail("live-lossless matched nodes differ from concrete occurrences")
    for node_ordinal, occurrence in occurrence_by_node.items():
        node = node_payloads[node_ordinal]
        reconstructed = reconstructed_values[node_ordinal]
        if occurrence["presence_kind"] in {"missing", "null"}:
            expected_row_count = 0
        elif occurrence["container_kind"] == "nba_api_live_json_array":
            if type(reconstructed) is not list:
                _fail("live-lossless array occurrence has a foreign reconstructed container")
            expected_row_count = len(cast("list[object]", reconstructed))
        else:
            if type(reconstructed) is not dict:
                _fail("live-lossless object occurrence has a foreign reconstructed container")
            expected_row_count = 1
        if not _exact_equal(
            (
                node["result_set_name"],
                node["result_set_ordinal"],
                node["result_set_occurrence"],
                node["json_path"],
                node["container_kind"],
                node["presence_kind"],
                node["value_sha256"],
                node["value_kind"],
                occurrence["row_count"],
            ),
            (
                occurrence["result_set_name"],
                occurrence["result_set_ordinal"],
                occurrence["occurrence_ordinal"],
                occurrence["json_path"],
                occurrence["container_kind"],
                occurrence["presence_kind"],
                occurrence["value_sha256"],
                (
                    "array"
                    if occurrence["presence_kind"] not in {"missing", "null"}
                    and occurrence["container_kind"] == "nba_api_live_json_array"
                    else "object"
                    if occurrence["presence_kind"] not in {"missing", "null"}
                    else occurrence["presence_kind"]
                ),
                expected_row_count,
            ),
        ):
            _fail("live-lossless occurrence differs from its exact node")

    cell_payloads = [cast("dict[str, object]", item["_payload"]) for item in cells]
    if tuple(item["cell_ordinal"] for item in cell_payloads) != tuple(range(len(cells))):
        _fail("live-lossless field-cell ordinals are not exact and contiguous")
    cell_counter: Counter[str] = Counter()
    actual_cell_keys: set[tuple[object, ...]] = set()
    cell_node_ordinals: set[int] = set()
    for row in cells:
        cell = cast("dict[str, object]", row["_payload"])
        node_ordinal = cell["node_ordinal"]
        if type(node_ordinal) is not int or node_ordinal >= len(node_payloads):
            _fail("live-lossless field cell references a foreign node")
        node = node_payloads[node_ordinal]
        if node_ordinal in cell_node_ordinals:
            _fail("live-lossless field cells share one projected node")
        cell_node_ordinals.add(node_ordinal)
        owner = cell["owner_result_set_name"]
        if type(owner) is not str or owner not in result_by_name:
            _fail("live-lossless field cell references an undeclared result")
        declaration = result_by_name[owner]
        context_name = cell["context_result_set_name"]
        context_declaration = result_by_name.get(cast("str", context_name))
        headers = declaration["ordered_headers"]
        field_ordinal = cell["field_ordinal"]
        cell_key = (
            owner,
            cell["owner_result_set_occurrence"],
            cell["owner_row_ordinal"],
            field_ordinal,
        )
        if cell_key in actual_cell_keys:
            _fail("live-lossless field-cell owner coordinates are duplicated")
        actual_cell_keys.add(cell_key)
        object_bound_field = node["object_key"] is not None
        if (
            type(headers) is not list
            or type(field_ordinal) is not int
            or field_ordinal >= len(headers)
            or headers[field_ordinal] != cell["field_name"]
            or cell["owner_result_set_ordinal"] != declaration["ordinal"]
            or (
                cell["owner_result_set_name"],
                cell["owner_result_set_ordinal"],
                cell["owner_result_set_occurrence"],
            )
            not in occurrence_keys
            or context_declaration is None
            or cell["context_result_set_ordinal"] != context_declaration["ordinal"]
            or (
                cell["context_result_set_name"],
                cell["context_result_set_ordinal"],
                cell["context_result_set_occurrence"],
            )
            not in occurrence_keys
            or (
                node["result_set_name"],
                node["result_set_ordinal"],
                node["result_set_occurrence"],
            )
            != (
                cell["context_result_set_name"],
                cell["context_result_set_ordinal"],
                cell["context_result_set_occurrence"],
            )
            or node["contract_json_path"] != context_declaration["json_path"]
            or cell["field_json_path"] != f"{declaration['json_path']}.{cell['field_name']}"
            or (
                object_bound_field
                and (
                    node["object_key"] != cell["field_name"]
                    or node["contract_field_ordinal"] != field_ordinal
                    or node["known_contract_field"] is not True
                )
            )
            or (
                not object_bound_field
                and (
                    headers != ["value"]
                    or cell["field_name"] != "value"
                    or node["array_ordinal"] is None
                    or node["contract_field_ordinal"] is not None
                    or node["known_contract_field"] is not None
                )
            )
            or cell["concrete_json_path"] != node["json_path"]
            or cell["presence_kind"] != node["presence_kind"]
            or cell["value_kind"] != node["value_kind"]
            or cell["canonical_json"] != node["canonical_json"]
            or cell["value_sha256"] != node["value_sha256"]
            or row["raw_occurrence_sha256"]
            != next(
                result_row["raw_occurrence_sha256"]
                for result_row in results
                if result_row["result_set_name"] == owner
            )
        ):
            _fail("live-lossless field cell differs from node/declaration authority")
        cell_counter[owner] += 1

    if any(
        (item["known_contract_field"] is True)
        != (cast("int", item["node_ordinal"]) in cell_node_ordinals)
        for item in node_payloads
        if item["object_key"] is not None
    ):
        _fail("live-lossless known-field nodes differ from field-cell ownership")

    expected_cell_keys: set[tuple[object, ...]] = set()
    for occurrence in occurrence_payloads:
        declaration = result_by_name[cast("str", occurrence["result_set_name"])]
        headers = cast("list[object]", declaration["ordered_headers"])
        reconstructed = reconstructed_values[cast("int", occurrence["node_ordinal"])]
        if occurrence["presence_kind"] in {"missing", "null"}:
            row_ordinals = range(0)
        elif occurrence["container_kind"] == "nba_api_live_json_array":
            row_ordinals = range(len(cast("list[object]", reconstructed)))
        else:
            row_ordinals = range(1)
        expected_cell_keys.update(
            (
                occurrence["result_set_name"],
                occurrence["occurrence_ordinal"],
                row_ordinal,
                field_ordinal,
            )
            for row_ordinal in row_ordinals
            for field_ordinal in range(len(headers))
        )
    if actual_cell_keys != expected_cell_keys:
        _fail("live-lossless field-cell coordinates are not exhaustive")

    for result in result_payloads:
        name = cast("str", result["name"])
        result_occurrences = [
            item for item in occurrence_payloads if item["result_set_name"] == name
        ]
        headers = result["ordered_headers"]
        if type(headers) is not list or any(type(item) is not str or not item for item in headers):
            _fail("live-lossless result headers are invalid")
        if any(type(item) is not str for item in headers):
            _fail("live-lossless result headers contain foreign values")
        for header in cast("list[str]", headers):
            _reject_text(header, key=True)
        if result["headers_sha256"] != _canonical_sha(headers):
            _fail("live-lossless result header digest is invalid")
        missing = sum(item["presence_kind"] == "missing" for item in result_occurrences)
        nulls = sum(item["presence_kind"] == "null" for item in result_occurrences)
        containers = len(result_occurrences) - missing - nulls
        rows_count = sum(cast("int", item["row_count"]) for item in result_occurrences)
        container_values = [
            reconstructed_values[cast("int", item["node_ordinal"])]
            for item in result_occurrences
            if item["presence_kind"] not in {"missing", "null"}
        ]
        observed_rows: list[object] = []
        for item in container_values:
            if result["container_kind"] == "nba_api_live_json_array":
                if type(item) is not list:
                    _fail("live-lossless array result occurrence has a foreign container")
                observed_rows.extend(cast("list[object]", item))
            else:
                observed_rows.append(item)
        parent_states = [
            (
                cast("str", item["presence_kind"])
                if item["presence_kind"] in {"missing", "null"}
                else "present"
            )
            for item in result_occurrences
        ]
        if containers == 0:
            if not result_occurrences:
                expected_presence = "not_observed_parent_empty"
            elif missing and nulls:
                expected_presence = "mixed_absent"
            elif missing:
                expected_presence = "missing"
            elif nulls:
                expected_presence = "null"
            else:
                _fail("live-lossless absent result has no parent state")
        elif (
            result["container_kind"] == "nba_api_live_json_array"
            and containers == 1
            and rows_count == 0
            and not missing
            and not nulls
        ):
            expected_presence = "empty_array"
        else:
            expected_presence = "present"
        if (
            result["result_occurrence_count"] != len(result_occurrences)
            or result["parent_observation_count"] != len(result_occurrences)
            or result["container_count"] != containers
            or result["missing_count"] != missing
            or result["null_count"] != nulls
            or result["row_count"] != rows_count
            or result["value_cell_count"] != rows_count * len(headers)
            or result["field_cell_count"] != cell_counter[name]
            or result["field_cell_count"] != result["value_cell_count"]
            or occurrence_counter[name] != len(result_occurrences)
            or result["presence"] != expected_presence
            or result["parent_occurrence_states_sha256"] != _canonical_sha(parent_states)
            or result["normalized_output_sha256"]
            != _canonical_sha(
                {
                    "containers": container_values,
                    "missing_count": missing,
                    "null_count": nulls,
                }
            )
            or result["observed_field_orders_sha256"]
            != _canonical_sha([list(item) if type(item) is dict else [] for item in observed_rows])
        ):
            _fail("live-lossless result denominators differ from public occurrences/cells")

    item_roots = {
        "result_sets_sha256": _canonical_sha(
            [cast("str", item["source_item_sha256"]) for item in results]
        ),
        "result_occurrences_sha256": _canonical_sha(
            [cast("str", item["source_item_sha256"]) for item in occurrences]
        ),
        "nodes_sha256": _canonical_sha([cast("str", item["source_item_sha256"]) for item in nodes]),
        "field_cells_sha256": _canonical_sha(
            [cast("str", item["source_item_sha256"]) for item in cells]
        ),
    }
    anomaly_json = cast("str", rows[0]["decoder_anomaly_codes_json"])
    anomalies = cast(
        "list[object]",
        _decode_json(anomaly_json, label="decoder_anomaly_codes_json", require=list),
    )
    root_value = cast("dict[str, object]", reconstructed_values[0])
    expected_root_names = tuple(
        cast("str", item["json_path"])[2:]
        for item in result_payloads
        if item["parent_result_set_name"] is None
    )
    actual_root_names = tuple(root_value)
    recomputed_anomalies: set[str] = set()
    if set(actual_root_names) - set(expected_root_names):
        recomputed_anomalies.add("additive_envelope_root")
    if (
        tuple(name for name in actual_root_names if name in expected_root_names)
        != expected_root_names
    ):
        recomputed_anomalies.add("reordered_envelope_root")
    if any(item["known_contract_field"] is False for item in node_payloads):
        recomputed_anomalies.add("additive_field")
    if (
        len(anomaly_json.encode("utf-8")) > MAX_LIVE_LOSSLESS_ANOMALY_BYTES
        or any(type(item) is not str or item not in _ANOMALY_CODES for item in anomalies)
        or anomalies != sorted(set(cast("list[str]", anomalies)))
        or anomalies != sorted(recomputed_anomalies)
    ):
        _fail("live-lossless decoder anomaly inventory is invalid")
    if rows[0]["decoder_anomaly_codes_sha256"] != _sha(anomaly_json.encode("utf-8")):
        _fail("live-lossless decoder anomaly digest is invalid")
    response_payload = {
        "anomaly_codes": anomalies,
        "contract_result_set_count": len(results),
        "endpoint_contract_sha256": rows[0]["endpoint_contract_sha256"],
        "endpoint_id": rows[0]["endpoint_id"],
        "endpoint_slug": rows[0]["endpoint_slug"],
        "field_cell_count": len(cells),
        "field_cells_sha256": item_roots["field_cells_sha256"],
        "missing_node_count": sum(item["presence_kind"] == "missing" for item in node_payloads),
        "node_count": len(nodes),
        "nodes_sha256": item_roots["nodes_sha256"],
        "null_node_count": sum(item["presence_kind"] == "null" for item in node_payloads),
        "parser_input_length": rows[0]["parser_input_length"],
        "parser_input_sha256": rows[0]["parser_input_sha256"],
        "present_empty_node_count": sum(
            item["presence_kind"] in {"empty_object", "empty_array"} for item in node_payloads
        ),
        "result_occurrence_count": len(occurrences),
        "result_occurrences_sha256": item_roots["result_occurrences_sha256"],
        "result_sets_sha256": item_roots["result_sets_sha256"],
    }
    decoder_response_sha = _canonical_sha(response_payload)
    if rows[0]["decoder_response_sha256"] != decoder_response_sha:
        _fail("live-lossless decoder response digest is not reconstructable from public rows")
    observation_root = _ordered_root(
        kind="live_lossless_observation_records_v1",
        count=len(rows),
        values=(cast("str", item["record_sha256"]) for item in rows),
    )
    unit_root = _ordered_root(
        kind="live_lossless_observation_expected_units_v1",
        count=len(units),
        values=(item.unit_sha256 for item in units),
    )
    assignment_root = _ordered_root(
        kind="live_lossless_observation_representation_assignments_v1",
        count=len(assignments),
        values=(item.assignment_sha256 for item in assignments),
    )
    receipt_sha256 = _canonical_sha(
        {
            "schema_version": 1,
            "kind": "live_lossless_selected_observation_receipt_v1",
            "raw_authority_bundle_sha256": rows[0]["raw_authority_bundle_sha256"],
            "observation_ordinal": rows[0]["observation_ordinal"],
            "observation_record_sha256": rows[0]["observation_record_sha256"],
            "observation_sha256": rows[0]["observation_sha256"],
            "attempt_sha256": rows[0]["attempt_sha256"],
            "provider_authority_sha256": rows[0]["provider_authority_sha256"],
            "endpoint_contract_sha256": rows[0]["endpoint_contract_sha256"],
            "parser_input_sha256": rows[0]["parser_input_sha256"],
            "decoder_response_sha256": decoder_response_sha,
            "route_landings_sha256": rows[0]["route_landings_sha256"],
            "raw_result_occurrences_sha256": rows[0]["raw_result_occurrences_sha256"],
            "live_snapshot_at": rows[0]["live_snapshot_at"],
            "record_count": len(rows),
            "record_inventory_sha256": observation_root,
            "expected_unit_count": len(units),
            "expected_unit_root_sha256": unit_root,
            "representation_assignment_count": len(assignments),
            "representation_assignment_root_sha256": assignment_root,
            "response_residual_record_count": len(residual_source_item_sha256s),
            "response_residual_record_root_sha256": residual_record_root_sha256,
            "response_residual_partition_sha256": residual_partition_sha256,
        }
    )
    return _ObservationVerification(
        receipt_sha256=receipt_sha256,
        units=tuple(units),
        assignments=tuple(assignments),
        residual_source_item_sha256s=residual_source_item_sha256s,
        residual_record_root_sha256=residual_record_root_sha256,
        residual_partition_sha256=residual_partition_sha256,
    )


def verify_live_lossless_public_table(
    public_rows: object,
    *,
    expected_raw_authority_bundle_sha256: str,
    expected_receipt_sha256: str,
) -> LiveLosslessValueAuthorityReceiptV1:
    """Rebuild the body-only value receipt solely from exact public rows."""

    _exact_sha(expected_raw_authority_bundle_sha256, label="expected raw authority bundle")
    _exact_sha(expected_receipt_sha256, label="expected live-lossless receipt")
    rows = _load_rows(public_rows)
    if tuple(row["global_record_ordinal"] for row in rows) != tuple(range(len(rows))):
        _fail("live-lossless global record ordinals are not contiguous")
    if any(
        row["raw_authority_bundle_sha256"] != expected_raw_authority_bundle_sha256 for row in rows
    ):
        _fail("live-lossless public rows differ from the externally pinned raw bundle")
    observation_groups: defaultdict[int, list[dict[str, object]]] = defaultdict(list)
    for row in rows:
        ordinal = _exact_int(
            row["observation_ordinal"],
            label="observation_ordinal",
            maximum=100_000 - 1,
        )
        observation_groups[ordinal].append(row)
    if tuple(observation_groups) != tuple(range(len(observation_groups))):
        _fail("live-lossless selected observation ordinals are not contiguous")
    semantic_keys = [
        (
            rows_for_observation[0]["logical_invocation_sha256"],
            rows_for_observation[0]["semantic_request_sha256"],
            rows_for_observation[0]["provider_call_ordinal"],
            0 if rows_for_observation[0]["page_ordinal"] is None else 1,
            0
            if rows_for_observation[0]["page_ordinal"] is None
            else rows_for_observation[0]["page_ordinal"],
            rows_for_observation[0]["provider_call_role"],
            rows_for_observation[0]["provider_call_sha256"],
            rows_for_observation[0]["retry_ordinal"],
            rows_for_observation[0]["request_ordinal"],
            rows_for_observation[0]["observation_sha256"],
        )
        for rows_for_observation in observation_groups.values()
    ]
    if semantic_keys != sorted(semantic_keys) or len(set(semantic_keys)) != len(semantic_keys):
        _fail("live-lossless selected observations are not in semantic attempt order")
    observation_verifications = [
        _validate_observation(observation_groups[ordinal])
        for ordinal in range(len(observation_groups))
    ]
    selected_root = _ordered_root(
        kind="live_lossless_selected_observations_v1",
        count=len(observation_verifications),
        values=(item.receipt_sha256 for item in observation_verifications),
    )
    record_root = _ordered_root(
        kind="live_lossless_public_records_v1",
        count=len(rows),
        values=(cast("str", row["record_sha256"]) for row in rows),
    )
    counts = Counter(cast("str", row["record_kind"]) for row in rows)
    expected_units = tuple(unit for item in observation_verifications for unit in item.units)
    assignments = tuple(
        assignment for item in observation_verifications for assignment in item.assignments
    )
    residual_source_item_sha256s = tuple(
        source_item
        for item in observation_verifications
        for source_item in item.residual_source_item_sha256s
    )
    try:
        expected_unit_inventory = ExpectedValueUnitInventoryV1.build(
            raw_authority_bundle_sha256=expected_raw_authority_bundle_sha256,
            units=expected_units,
        )
    except PublicValueTypesError as exc:
        raise IndependentLiveLosslessTableVerifierError(
            "live-lossless expected-unit inventory is not canonical"
        ) from exc
    assignment_root = _ordered_root(
        kind="live_lossless_representation_assignments_v1",
        count=len(assignments),
        values=(item.assignment_sha256 for item in assignments),
    )
    residual_root = _ordered_root(
        kind="live_lossless_response_residual_source_items_v1",
        count=len(residual_source_item_sha256s),
        values=residual_source_item_sha256s,
    )
    residual_partition_root = _ordered_root(
        kind="live_lossless_response_residual_partitions_v1",
        count=len(observation_verifications),
        values=(item.residual_partition_sha256 for item in observation_verifications),
    )
    residual_observation_count = sum(
        bool(item.residual_source_item_sha256s) for item in observation_verifications
    )
    values: dict[str, object] = {
        "source_input_kind": LIVE_LOSSLESS_SOURCE_INPUT_KIND,
        "representation_kind": LIVE_LOSSLESS_REPRESENTATION_KIND,
        "response_residual_representation_kind": (LIVE_RESPONSE_RESIDUAL_REPRESENTATION_KIND),
        "node_schema_sha256": LIVE_LOSSLESS_NODE_SCHEMA_SHA256,
        "raw_authority_bundle_sha256": expected_raw_authority_bundle_sha256,
        "selected_observation_count": len(observation_verifications),
        "selected_observations_sha256": selected_root,
        "expected_unit_count": expected_unit_inventory.unit_count,
        "expected_unit_inventory_sha256": expected_unit_inventory.inventory_sha256,
        "expected_unit_root_sha256": expected_unit_inventory.unit_root_sha256,
        "representation_assignment_count": len(assignments),
        "representation_assignment_inventory_sha256": assignment_root,
        "response_residual_record_count": len(residual_source_item_sha256s),
        "response_residual_record_inventory_sha256": residual_root,
        "response_residual_observation_count": residual_observation_count,
        "zero_response_residual_observation_count": (
            len(observation_verifications) - residual_observation_count
        ),
        "response_residual_partition_inventory_sha256": residual_partition_root,
        "record_count": len(rows),
        "record_inventory_sha256": record_root,
        "result_declaration_count": counts["result_declaration"],
        "result_occurrence_count": counts["result_occurrence"],
        "node_count": counts["node"],
        "field_cell_count": counts["field_cell"],
    }
    identity = {
        "schema_version": PUBLIC_VALUE_AUTHORITY_SCHEMA_VERSION,
        "kind": LIVE_LOSSLESS_VALUE_AUTHORITY_KIND,
        **values,
    }
    receipt_sha = _canonical_sha(identity)
    if receipt_sha != expected_receipt_sha256:
        if not rows:
            _fail("live-lossless public table count differs from the external receipt")
        _fail("live-lossless public table differs from the external body-only receipt")
    try:
        return LiveLosslessValueAuthorityReceiptV1(
            receipt_sha256=receipt_sha,
            source_input_kind=LIVE_LOSSLESS_SOURCE_INPUT_KIND,
            representation_kind=LIVE_LOSSLESS_REPRESENTATION_KIND,
            response_residual_representation_kind=(LIVE_RESPONSE_RESIDUAL_REPRESENTATION_KIND),
            node_schema_sha256=LIVE_LOSSLESS_NODE_SCHEMA_SHA256,
            raw_authority_bundle_sha256=expected_raw_authority_bundle_sha256,
            selected_observation_count=len(observation_verifications),
            selected_observations_sha256=selected_root,
            expected_unit_count=expected_unit_inventory.unit_count,
            expected_unit_inventory_sha256=expected_unit_inventory.inventory_sha256,
            expected_unit_root_sha256=expected_unit_inventory.unit_root_sha256,
            representation_assignment_count=len(assignments),
            representation_assignment_inventory_sha256=assignment_root,
            response_residual_record_count=len(residual_source_item_sha256s),
            response_residual_record_inventory_sha256=residual_root,
            response_residual_observation_count=residual_observation_count,
            zero_response_residual_observation_count=(
                len(observation_verifications) - residual_observation_count
            ),
            response_residual_partition_inventory_sha256=residual_partition_root,
            record_count=len(rows),
            record_inventory_sha256=record_root,
            result_declaration_count=counts["result_declaration"],
            result_occurrence_count=counts["result_occurrence"],
            node_count=counts["node"],
            field_cell_count=counts["field_cell"],
        )
    except (TypeError, ValueError):
        raise IndependentLiveLosslessTableVerifierError(
            "live-lossless public receipt reconstruction failed"
        ) from None
