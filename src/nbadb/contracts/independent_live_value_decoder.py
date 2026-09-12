"""Dependency-pure, bounded decoding of exact pinned NBA Live response values.

This module intentionally does not import the provider runtime, the production
NBA API adapter, the production live-lossless projector, or orchestration code.
It admits one exact endpoint identity from the frozen generated contract JSON,
decodes the immutable parser-input bytes through a separate JSON path, and
returns sealed immutable value/structure inventories for independent replay.
"""

from __future__ import annotations

import hashlib
import json
import math
import re
from collections import Counter
from dataclasses import dataclass, replace
from functools import lru_cache
from pathlib import Path
from types import MappingProxyType
from typing import TYPE_CHECKING, Final, Literal, cast

if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence


MAX_PARSER_INPUT_BYTES: Final = 64 * 1024 * 1024
MAX_JSON_DEPTH: Final = 64
MAX_JSON_NODES: Final = 2_000_000
MAX_JSON_CONTAINER_ITEMS: Final = 2_000_000
MAX_JSON_STRING_BYTES: Final = 4 * 1024 * 1024
MAX_JSON_TOTAL_STRING_BYTES: Final = 64 * 1024 * 1024
MAX_JSON_NUMBER_TOKEN_BYTES: Final = 64
MAX_JSON_INTEGER_ABS: Final = (1 << 63) - 1
MAX_LIVE_RESULT_SETS: Final = 64
MAX_LIVE_FIELDS_PER_RESULT: Final = 1_024
MAX_LIVE_RESULT_OCCURRENCES: Final = 2_000_000
MAX_LIVE_FIELD_CELLS: Final = 10_000_000
MAX_CANONICAL_INVENTORY_BYTES: Final = 128 * 1024 * 1024
MAX_TOTAL_VALUE_DIGEST_BYTES: Final = 256 * 1024 * 1024
MAX_PINNED_CONTRACT_BYTES: Final = 2 * 1024 * 1024

_RUNTIME_CONTRACT_RESOURCE: Final = "nba_api_runtime_contract_v1_11_4.json"
_PINNED_LIVE_CONTRACTS_SHA256: Final = (
    "18750aec673db6c1a2c7d43b7425ec90b4a354c193491664bf24b34d8cda7543"
)
_PINNED_ENDPOINT_IDS: Final = frozenset({"BoxScore", "Odds", "PlayByPlay", "ScoreBoard"})
_PINNED_RESULT_SET_COUNT: Final = 33
_PINNED_PARSED_FIELD_COUNT: Final = 431

_SHA256_RE: Final = re.compile(r"[0-9a-f]{64}\Z")
_VALUE_KINDS: Final = frozenset(
    {"object", "array", "null", "boolean", "integer", "number", "string", "missing"}
)
_PRESENCE_KINDS: Final = frozenset({"present", "null", "empty_object", "empty_array", "missing"})
_RESULT_PRESENCES: Final = frozenset(
    {
        "present",
        "empty_array",
        "missing",
        "null",
        "mixed_absent",
        "not_observed_parent_empty",
    }
)
_ANOMALY_CODES: Final = frozenset(
    {"additive_envelope_root", "reordered_envelope_root", "additive_field"}
)
_CONTAINER_KINDS: Final = frozenset({"nba_api_live_json_array", "nba_api_live_json_object"})
_JSON_TYPES: Final = frozenset(
    {"array", "boolean", "integer", "null", "number", "object", "string"}
)
_PARENT_STATES: Final = frozenset({"present", "missing", "null"})
_PathToken = str | int

_ENDPOINT_FIELDS: Final = frozenset(
    {
        "base_url",
        "base_url_provenance",
        "contract_sha256",
        "disposition_reason",
        "docs_source_path",
        "docs_source_sha256",
        "documented_url",
        "documented_url_drift",
        "endpoint_id",
        "endpoint_slug",
        "endpoint_url_template",
        "envelope_root_order",
        "evidence",
        "full_url_template",
        "gate_effects",
        "model_disposition",
        "ordered_header_names",
        "ordered_headers_provenance",
        "ordered_headers_sha256",
        "owner",
        "parameters",
        "request_method",
        "request_method_provenance",
        "result_sets",
        "revalidation_path",
        "runtime_module",
        "skipped_shapes",
        "source_family",
        "source_path",
        "source_sha256",
    }
)
_RESULT_SET_FIELDS: Final = frozenset(
    {
        "container_kind",
        "fields",
        "fields_sha256",
        "json_path",
        "name",
        "ordinal",
        "parent_field_name",
        "parent_result_set_name",
        "traversal_path",
    }
)
_FIELD_FIELDS: Final = frozenset(
    {
        "confidence",
        "documented_type",
        "drift_status",
        "json_path",
        "key_presence",
        "name",
        "nested_result_set_name",
        "nullable",
        "ordinal",
        "provenance_source",
        "runtime_sample_type",
        "sample_type",
        "source_field",
    }
)


class IndependentLiveValueDecoderError(ValueError):
    """Raised when raw live bytes cannot prove exact pinned response values."""


def _fail(message: str) -> IndependentLiveValueDecoderError:
    return IndependentLiveValueDecoderError(message)


def _canonical_json_bytes(value: object, *, maximum: int) -> bytes:
    try:
        encoded = json.dumps(
            value,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
            allow_nan=False,
        ).encode("utf-8", errors="strict")
    except (TypeError, ValueError, UnicodeEncodeError, RecursionError) as exc:
        raise _fail("live value is not bounded canonical JSON") from exc
    if len(encoded) > maximum:
        raise _fail("live canonical value bytes exceed their bound")
    return encoded


def _canonical_json_text(value: object, *, sort_keys: bool = False) -> str:
    try:
        return json.dumps(
            value,
            sort_keys=sort_keys,
            separators=(",", ":"),
            ensure_ascii=False,
            allow_nan=False,
        )
    except (TypeError, ValueError, UnicodeEncodeError, RecursionError) as exc:
        raise _fail("live value is not canonical JSON") from exc


def _canonical_sha256(value: object) -> str:
    return hashlib.sha256(
        _canonical_json_bytes(value, maximum=MAX_CANONICAL_INVENTORY_BYTES)
    ).hexdigest()


def _validate_sha256(value: object, *, label: str) -> str:
    if type(value) is not str or _SHA256_RE.fullmatch(value) is None:
        raise _fail(f"{label} must be a lowercase full SHA-256")
    return value


def _reject_duplicate_object_keys(pairs: list[tuple[str, object]]) -> dict[str, object]:
    output: dict[str, object] = {}
    for key, value in pairs:
        if key in output:
            raise _fail("live parser input contains duplicate JSON object keys")
        output[key] = value
    return output


def _bounded_json_integer(token: str) -> int:
    if len(token) > MAX_JSON_NUMBER_TOKEN_BYTES:
        raise _fail("live JSON integer token exceeds its bound")
    try:
        value = int(token)
    except ValueError as exc:
        raise _fail("live JSON integer token is invalid") from exc
    if abs(value) > MAX_JSON_INTEGER_ABS:
        raise _fail("live JSON integer exceeds the signed 64-bit value bound")
    return value


def _bounded_json_float(token: str) -> float:
    if len(token) > MAX_JSON_NUMBER_TOKEN_BYTES:
        raise _fail("live JSON number token exceeds its bound")
    try:
        value = float(token)
    except ValueError as exc:
        raise _fail("live JSON number token is invalid") from exc
    if not math.isfinite(value):
        raise _fail("live JSON contains a non-finite number")
    return value


def _reject_json_constant(_token: str) -> object:
    raise _fail("live JSON contains a non-finite constant")


def _lexical_json_budget(text: str) -> None:
    """Reject deep or oversized tokens before the recursive JSON decoder runs."""

    depth = 0
    index = 0
    length = len(text)
    in_string = False
    escaped = False
    string_bytes = 0
    while index < length:
        char = text[index]
        if in_string:
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == '"':
                in_string = False
                if string_bytes > MAX_JSON_STRING_BYTES:
                    raise _fail("live JSON string token exceeds its bound")
                string_bytes = 0
            else:
                string_bytes += len(char.encode("utf-8", errors="strict"))
            index += 1
            continue
        if char == '"':
            in_string = True
            string_bytes = 0
            index += 1
            continue
        if char in "[{":
            depth += 1
            if depth > MAX_JSON_DEPTH:
                raise _fail("live JSON depth exceeds its bound")
        elif char in "]}":
            depth -= 1
            if depth < 0:
                raise _fail("live JSON container nesting is malformed")
        elif char == "-" or char.isdigit():
            end = index + 1
            while end < length and text[end] in "0123456789+-.eE":
                end += 1
            if end - index > MAX_JSON_NUMBER_TOKEN_BYTES:
                raise _fail("live JSON number token exceeds its bound")
            index = end
            continue
        index += 1
    if in_string or depth != 0:
        raise _fail("live JSON lexical structure is incomplete")


def _validate_json_budget(value: object) -> None:
    nodes = 0
    container_items = 0
    string_bytes = 0
    stack: list[tuple[object, int]] = [(value, 0)]
    while stack:
        item, depth = stack.pop()
        nodes += 1
        if nodes > MAX_JSON_NODES:
            raise _fail("live JSON node count exceeds its bound")
        if depth > MAX_JSON_DEPTH:
            raise _fail("live JSON depth exceeds its bound")
        if type(item) is dict:
            exact = cast("dict[str, object]", item)
            container_items += len(exact)
            for key, child in reversed(tuple(exact.items())):
                encoded = key.encode("utf-8", errors="strict")
                if len(encoded) > MAX_JSON_STRING_BYTES:
                    raise _fail("live JSON object key exceeds its bound")
                string_bytes += len(encoded)
                stack.append((child, depth + 1))
        elif type(item) is list:
            exact_list = cast("list[object]", item)
            container_items += len(exact_list)
            stack.extend((child, depth + 1) for child in reversed(exact_list))
        elif type(item) is str:
            encoded = item.encode("utf-8", errors="strict")
            if len(encoded) > MAX_JSON_STRING_BYTES:
                raise _fail("live JSON string value exceeds its bound")
            string_bytes += len(encoded)
        elif type(item) is int:
            if abs(item) > MAX_JSON_INTEGER_ABS:
                raise _fail("live JSON integer exceeds the signed 64-bit value bound")
        elif type(item) is float:
            if not math.isfinite(item):
                raise _fail("live JSON contains a non-finite number")
        elif item is not None and type(item) is not bool:
            raise _fail("live parser input contains a non-JSON value")
        if container_items > MAX_JSON_CONTAINER_ITEMS:
            raise _fail("live JSON container item count exceeds its bound")
        if string_bytes > MAX_JSON_TOTAL_STRING_BYTES:
            raise _fail("live JSON cumulative string bytes exceed their bound")


def _decode_json_bytes(
    raw: bytes,
    *,
    maximum: int,
    label: str,
    require_object: bool,
) -> object:
    if type(raw) is not bytes or not raw or len(raw) > maximum:
        raise _fail(f"{label} byte length is invalid")
    try:
        text = raw.decode("utf-8", errors="strict")
        _lexical_json_budget(text)
        value = json.loads(
            text,
            object_pairs_hook=_reject_duplicate_object_keys,
            parse_int=_bounded_json_integer,
            parse_float=_bounded_json_float,
            parse_constant=_reject_json_constant,
        )
    except IndependentLiveValueDecoderError:
        raise
    except (UnicodeDecodeError, UnicodeEncodeError, json.JSONDecodeError, RecursionError) as exc:
        raise _fail(f"{label} is not bounded valid UTF-8 JSON") from exc
    try:
        _validate_json_budget(value)
    except UnicodeEncodeError as exc:
        raise _fail(f"{label} is not bounded valid UTF-8 JSON") from exc
    if require_object and type(value) is not dict:
        raise _fail(f"{label} root must be an object")
    return value


def _exact_object(value: object, fields: frozenset[str], *, label: str) -> dict[str, object]:
    if type(value) is not dict or set(value) != fields:
        raise _fail(f"{label} fields differ from the frozen schema")
    return cast("dict[str, object]", value)


def _string(value: object, *, label: str) -> str:
    if type(value) is not str or not value:
        raise _fail(f"{label} must be a nonempty exact string")
    return value


def _optional_string(value: object, *, label: str) -> str | None:
    if value is None:
        return None
    return _string(value, label=label)


def _integer(value: object, *, label: str, maximum: int) -> int:
    if type(value) is not int or value < 0 or value > maximum:
        raise _fail(f"{label} must be a bounded exact integer")
    return value


def _string_tuple(
    value: object,
    *,
    label: str,
    allow_duplicates: bool = False,
) -> tuple[str, ...]:
    if type(value) is not list or any(type(item) is not str or not item for item in value):
        raise _fail(f"{label} must be an array of nonempty exact strings")
    output = tuple(cast("list[str]", value))
    if not allow_duplicates and len(set(output)) != len(output):
        raise _fail(f"{label} contains duplicates")
    return output


def _sample_types(value: object) -> tuple[str, ...]:
    if type(value) is str:
        values = (value,)
    elif type(value) is list:
        values = tuple(cast("list[object]", value))
    else:
        raise _fail("live field sample type has a foreign shape")
    if (
        not values
        or any(type(item) is not str or item not in _JSON_TYPES for item in values)
        or len(set(values)) != len(values)
    ):
        raise _fail("live field sample type is invalid")
    return cast("tuple[str, ...]", values)


@dataclass(frozen=True, slots=True)
class _LiveFieldContract:
    name: str
    ordinal: int
    json_path: str
    sample_types: tuple[str, ...]
    source_field: bool
    key_presence: str
    nested_result_set_name: str | None
    nullable: bool


@dataclass(frozen=True, slots=True)
class _LiveResultSetContract:
    name: str
    ordinal: int
    json_path: str
    traversal_path: tuple[str, ...]
    container_kind: str
    parent_result_set_name: str | None
    parent_field_name: str | None
    fields: tuple[_LiveFieldContract, ...]


@dataclass(frozen=True, slots=True)
class _LiveEndpointContract:
    endpoint_id: str
    endpoint_slug: str
    contract_sha256: str
    envelope_root_order: tuple[str, ...]
    result_sets: tuple[_LiveResultSetContract, ...]


def _parse_field(raw: object) -> _LiveFieldContract:
    value = _exact_object(raw, _FIELD_FIELDS, label="live field contract")
    nullable = value["nullable"]
    source_field = value["source_field"]
    if type(nullable) is not bool or type(source_field) is not bool:
        raise _fail("live field booleans are invalid")
    key_presence = _string(value["key_presence"], label="live field key presence")
    if key_presence not in {"required", "optional", "optional_or_undocumented"}:
        raise _fail("live field key presence is invalid")
    return _LiveFieldContract(
        name=_string(value["name"], label="live field name"),
        ordinal=_integer(
            value["ordinal"],
            label="live field ordinal",
            maximum=MAX_LIVE_FIELDS_PER_RESULT - 1,
        ),
        json_path=_string(value["json_path"], label="live field JSON path"),
        sample_types=_sample_types(value["sample_type"]),
        source_field=source_field,
        key_presence=key_presence,
        nested_result_set_name=_optional_string(
            value["nested_result_set_name"], label="live nested result-set name"
        ),
        nullable=nullable,
    )


def _parse_result_set(raw: object) -> _LiveResultSetContract:
    value = _exact_object(raw, _RESULT_SET_FIELDS, label="live result-set contract")
    raw_fields = value["fields"]
    if type(raw_fields) is not list or len(raw_fields) > MAX_LIVE_FIELDS_PER_RESULT:
        raise _fail("live result-set field inventory is invalid")
    if _canonical_sha256(raw_fields) != _validate_sha256(
        value["fields_sha256"], label="live fields digest"
    ):
        raise _fail("live result-set fields digest differs from its inventory")
    fields = tuple(_parse_field(item) for item in cast("list[object]", raw_fields))
    if tuple(field.ordinal for field in fields) != tuple(range(len(fields))):
        raise _fail("live result-set field ordinals are not contiguous")
    if len({field.name for field in fields}) != len(fields):
        raise _fail("live result-set field names are duplicated")
    container_kind = _string(value["container_kind"], label="live container kind")
    if container_kind not in _CONTAINER_KINDS:
        raise _fail("live result-set container kind is unsupported")
    return _LiveResultSetContract(
        name=_string(value["name"], label="live result-set name"),
        ordinal=_integer(
            value["ordinal"],
            label="live result-set ordinal",
            maximum=MAX_LIVE_RESULT_SETS - 1,
        ),
        json_path=_string(value["json_path"], label="live result-set JSON path"),
        traversal_path=_string_tuple(
            value["traversal_path"],
            label="live traversal path",
            allow_duplicates=True,
        ),
        container_kind=container_kind,
        parent_result_set_name=_optional_string(
            value["parent_result_set_name"], label="live parent result-set name"
        ),
        parent_field_name=_optional_string(
            value["parent_field_name"], label="live parent field name"
        ),
        fields=fields,
    )


def _validate_contract_semantics(contract: _LiveEndpointContract) -> None:
    result_sets = contract.result_sets
    if tuple(item.ordinal for item in result_sets) != tuple(range(len(result_sets))):
        raise _fail("live result-set ordinals are not contiguous")
    if len({item.name for item in result_sets}) != len(result_sets):
        raise _fail("live result-set names are duplicated")
    by_name = {item.name: item for item in result_sets}
    by_path = {tuple(item.json_path.removeprefix("$.").split(".")): item for item in result_sets}
    roots = tuple(item.name for item in result_sets if item.parent_result_set_name is None)
    if roots != contract.envelope_root_order:
        raise _fail("live envelope root order differs from root result sets")
    for result_set in result_sets:
        own_path = tuple(result_set.json_path.removeprefix("$.").split("."))
        if not result_set.json_path.startswith("$.") or not all(own_path):
            raise _fail("live result-set JSON path is invalid")
        traversal: list[str] = []
        for index, segment in enumerate(own_path):
            traversal.append(segment)
            parent_at_path = by_path.get(own_path[: index + 1])
            if (
                parent_at_path is not None
                and parent_at_path.container_kind == "nba_api_live_json_array"
                and index + 1 < len(own_path)
            ):
                traversal.append("*")
        if tuple(traversal) != result_set.traversal_path:
            raise _fail("live result-set traversal path is not derivable")
        if result_set.parent_result_set_name is None:
            if result_set.parent_field_name is not None:
                raise _fail("live root result set has a parent field")
        else:
            parent = by_name.get(result_set.parent_result_set_name)
            if parent is None or parent.ordinal >= result_set.ordinal:
                raise _fail("live nested result set has no prior parent")
            parent_field = next(
                (field for field in parent.fields if field.name == result_set.parent_field_name),
                None,
            )
            if parent_field is None or parent_field.nested_result_set_name != result_set.name:
                raise _fail("live nested result-set field reference is invalid")
        for field in result_set.fields:
            if field.json_path != f"{result_set.json_path}.{field.name}":
                raise _fail("live field JSON path differs from its result set")
            if field.nested_result_set_name is not None:
                child = by_name.get(field.nested_result_set_name)
                if (
                    child is None
                    or child.parent_result_set_name != result_set.name
                    or child.parent_field_name != field.name
                ):
                    raise _fail("live field nested result-set reference is invalid")


def _parse_endpoint(name: str, raw: object) -> _LiveEndpointContract:
    value = _exact_object(raw, _ENDPOINT_FIELDS, label="live endpoint contract")
    body = dict(value)
    digest = _validate_sha256(body.pop("contract_sha256", None), label="live contract digest")
    if _canonical_sha256(body) != digest:
        raise _fail("live endpoint contract digest differs from its body")
    if value["source_family"] != "live" or value["request_method"] != "GET":
        raise _fail("live endpoint request identity is invalid")
    if value["endpoint_id"] != name:
        raise _fail("live endpoint registry key differs from its identity")
    raw_results = value["result_sets"]
    if type(raw_results) is not list or not raw_results or len(raw_results) > MAX_LIVE_RESULT_SETS:
        raise _fail("live endpoint result-set inventory is invalid")
    contract = _LiveEndpointContract(
        endpoint_id=name,
        endpoint_slug=_string(value["endpoint_slug"], label="live endpoint slug"),
        contract_sha256=digest,
        envelope_root_order=_string_tuple(
            value["envelope_root_order"], label="live envelope root order"
        ),
        result_sets=tuple(_parse_result_set(item) for item in cast("list[object]", raw_results)),
    )
    _validate_contract_semantics(contract)
    return contract


@lru_cache(maxsize=1)
def _pinned_live_contracts() -> Mapping[str, _LiveEndpointContract]:
    path = Path(__file__).with_name(_RUNTIME_CONTRACT_RESOURCE)
    try:
        raw = path.read_bytes()
    except OSError as exc:
        raise _fail("frozen live contract resource is unavailable") from exc
    payload = _decode_json_bytes(
        raw,
        maximum=MAX_PINNED_CONTRACT_BYTES,
        label="frozen live contract resource",
        require_object=True,
    )
    exact = cast("dict[str, object]", payload)
    if exact.get("schema_version") != 4 or exact.get("kind") != (
        "nbadb_pinned_nba_api_runtime_contract"
    ):
        raise _fail("frozen live contract resource identity is invalid")
    live_contracts = exact.get("live_contracts")
    if type(live_contracts) is not dict:
        raise _fail("frozen live contract inventory is absent")
    expected_digest = _validate_sha256(
        exact.get("live_contracts_sha256"), label="frozen live contracts digest"
    )
    if (
        expected_digest != _PINNED_LIVE_CONTRACTS_SHA256
        or _canonical_sha256(live_contracts) != expected_digest
    ):
        raise _fail("frozen live contract inventory differs from its exact pin")
    raw_by_id = cast("dict[str, object]", live_contracts)
    if set(raw_by_id) != _PINNED_ENDPOINT_IDS:
        raise _fail("frozen live endpoint inventory is missing or extra")
    contracts = {name: _parse_endpoint(name, raw_by_id[name]) for name in sorted(raw_by_id)}
    if sum(len(item.result_sets) for item in contracts.values()) != _PINNED_RESULT_SET_COUNT:
        raise _fail("frozen live result-set census differs from its exact pin")
    if (
        sum(len(result.fields) for item in contracts.values() for result in item.result_sets)
        != _PINNED_PARSED_FIELD_COUNT
    ):
        raise _fail("frozen live parsed-field census differs from its exact pin")
    return MappingProxyType(contracts)


def pinned_live_decoder_contract_identities() -> Mapping[str, str]:
    """Return a detached read-only endpoint-to-contract digest inventory."""

    return MappingProxyType(
        {name: contract.contract_sha256 for name, contract in _pinned_live_contracts().items()}
    )


LivePresenceKind = Literal["present", "null", "empty_object", "empty_array", "missing"]
LiveValueKind = Literal[
    "object", "array", "null", "boolean", "integer", "number", "string", "missing"
]
LiveResultPresence = Literal[
    "present", "empty_array", "missing", "null", "mixed_absent", "not_observed_parent_empty"
]


def _optional_bounded_ordinal(value: object, *, label: str, maximum: int) -> int | None:
    if value is None:
        return None
    return _integer(value, label=label, maximum=maximum)


def _node_identity(node: DecodedLiveNodeV1) -> dict[str, object]:
    return {
        "array_ordinal": node.array_ordinal,
        "canonical_json": node.canonical_json,
        "container_kind": node.container_kind,
        "contract_field_ordinal": node.contract_field_ordinal,
        "contract_json_path": node.contract_json_path,
        "depth": node.depth,
        "json_path": node.json_path,
        "known_contract_field": node.known_contract_field,
        "node_ordinal": node.node_ordinal,
        "object_key": node.object_key,
        "object_key_ordinal": node.object_key_ordinal,
        "parent_json_path": node.parent_json_path,
        "parent_node_ordinal": node.parent_node_ordinal,
        "presence_kind": node.presence_kind,
        "result_set_name": node.result_set_name,
        "result_set_occurrence": node.result_set_occurrence,
        "result_set_ordinal": node.result_set_ordinal,
        "result_set_row_ordinal": node.result_set_row_ordinal,
        "value_kind": node.value_kind,
        "value_sha256": node.value_sha256,
    }


@dataclass(frozen=True, slots=True)
class DecodedLiveNodeV1:
    """One exact preorder JSON node, including explicit missing-field sentinels."""

    node_ordinal: int
    parent_node_ordinal: int | None
    json_path: str
    parent_json_path: str | None
    depth: int
    object_key: str | None
    object_key_ordinal: int | None
    array_ordinal: int | None
    result_set_name: str | None
    result_set_ordinal: int | None
    result_set_occurrence: int | None
    result_set_row_ordinal: int | None
    contract_json_path: str | None
    container_kind: str | None
    contract_field_ordinal: int | None
    known_contract_field: bool | None
    presence_kind: LivePresenceKind
    value_kind: LiveValueKind
    canonical_json: str | None
    value_sha256: str
    node_sha256: str

    def __post_init__(self) -> None:
        _integer(self.node_ordinal, label="live node ordinal", maximum=MAX_JSON_NODES - 1)
        _optional_bounded_ordinal(
            self.parent_node_ordinal,
            label="live parent node ordinal",
            maximum=MAX_JSON_NODES - 1,
        )
        _integer(self.depth, label="live node depth", maximum=MAX_JSON_DEPTH)
        for value, label, maximum in (
            (self.object_key_ordinal, "live object-key ordinal", MAX_JSON_CONTAINER_ITEMS - 1),
            (self.array_ordinal, "live array ordinal", MAX_JSON_CONTAINER_ITEMS - 1),
            (self.result_set_ordinal, "live result-set ordinal", MAX_LIVE_RESULT_SETS - 1),
            (
                self.result_set_occurrence,
                "live result-set occurrence",
                MAX_LIVE_RESULT_OCCURRENCES - 1,
            ),
            (self.result_set_row_ordinal, "live result row ordinal", MAX_JSON_CONTAINER_ITEMS - 1),
            (
                self.contract_field_ordinal,
                "live contract field ordinal",
                MAX_LIVE_FIELDS_PER_RESULT - 1,
            ),
        ):
            _optional_bounded_ordinal(value, label=label, maximum=maximum)
        if type(self.json_path) is not str or not self.json_path.startswith("$"):
            raise _fail("live node JSON path is invalid")
        if self.parent_json_path is not None and type(self.parent_json_path) is not str:
            raise _fail("live node parent JSON path is invalid")
        if self.object_key is not None and type(self.object_key) is not str:
            raise _fail("live node object key is invalid")
        result_values = (
            self.result_set_name,
            self.result_set_ordinal,
            self.result_set_occurrence,
            self.contract_json_path,
        )
        if any(value is None for value in result_values) and any(
            value is not None for value in result_values
        ):
            raise _fail("live node result-set context is partial")
        if self.result_set_name is not None and (
            type(self.result_set_name) is not str or not self.result_set_name
        ):
            raise _fail("live node result-set name is invalid")
        if self.contract_json_path is not None and type(self.contract_json_path) is not str:
            raise _fail("live node contract path is invalid")
        if self.container_kind is not None and self.container_kind not in _CONTAINER_KINDS:
            raise _fail("live node container kind is invalid")
        if self.known_contract_field is not None and type(self.known_contract_field) is not bool:
            raise _fail("live node known-field flag is invalid")
        if self.presence_kind not in _PRESENCE_KINDS or self.value_kind not in _VALUE_KINDS:
            raise _fail("live node value/presence kind is invalid")
        if self.presence_kind == "missing":
            if self.value_kind != "missing" or self.canonical_json is not None:
                raise _fail("live missing node value identity is invalid")
        elif self.value_kind in {"object", "array"}:
            expected_empty = "{}" if self.value_kind == "object" else "[]"
            if self.canonical_json not in {None, expected_empty}:
                raise _fail("live container node canonical value is invalid")
        elif type(self.canonical_json) is not str:
            raise _fail("live scalar node canonical value is absent")
        _validate_sha256(self.value_sha256, label="live node value digest")
        _validate_sha256(self.node_sha256, label="live node digest")
        if _canonical_sha256(_node_identity(self)) != self.node_sha256:
            raise _fail("live node digest differs from its identity")

    def to_dict(self) -> dict[str, object]:
        """Return a detached canonical identity mapping."""

        return {**_node_identity(self), "node_sha256": self.node_sha256}


def _result_occurrence_identity(item: DecodedLiveResultOccurrenceV1) -> dict[str, object]:
    return {
        "container_kind": item.container_kind,
        "global_ordinal": item.global_ordinal,
        "json_path": item.json_path,
        "node_ordinal": item.node_ordinal,
        "occurrence_ordinal": item.occurrence_ordinal,
        "parent_result_set_name": item.parent_result_set_name,
        "parent_result_set_ordinal": item.parent_result_set_ordinal,
        "presence_kind": item.presence_kind,
        "result_set_name": item.result_set_name,
        "result_set_ordinal": item.result_set_ordinal,
        "row_count": item.row_count,
        "value_sha256": item.value_sha256,
    }


@dataclass(frozen=True, slots=True)
class DecodedLiveResultOccurrenceV1:
    """One concrete present, null, or missing result-container occurrence."""

    global_ordinal: int
    result_set_name: str
    result_set_ordinal: int
    occurrence_ordinal: int
    parent_result_set_name: str | None
    parent_result_set_ordinal: int | None
    node_ordinal: int
    json_path: str
    container_kind: str
    presence_kind: LivePresenceKind
    row_count: int
    value_sha256: str
    occurrence_sha256: str

    def __post_init__(self) -> None:
        for value, label, maximum in (
            (
                self.global_ordinal,
                "live global occurrence ordinal",
                MAX_LIVE_RESULT_OCCURRENCES - 1,
            ),
            (self.result_set_ordinal, "live occurrence result ordinal", MAX_LIVE_RESULT_SETS - 1),
            (
                self.occurrence_ordinal,
                "live occurrence ordinal",
                MAX_LIVE_RESULT_OCCURRENCES - 1,
            ),
            (self.node_ordinal, "live occurrence node ordinal", MAX_JSON_NODES - 1),
            (self.row_count, "live occurrence row count", MAX_JSON_CONTAINER_ITEMS),
        ):
            _integer(value, label=label, maximum=maximum)
        _optional_bounded_ordinal(
            self.parent_result_set_ordinal,
            label="live parent result ordinal",
            maximum=MAX_LIVE_RESULT_SETS - 1,
        )
        if type(self.result_set_name) is not str or not self.result_set_name:
            raise _fail("live occurrence result name is invalid")
        if (self.parent_result_set_name is None) != (self.parent_result_set_ordinal is None):
            raise _fail("live occurrence parent result identity is partial")
        if self.parent_result_set_name is not None and (
            type(self.parent_result_set_name) is not str or not self.parent_result_set_name
        ):
            raise _fail("live occurrence parent result name is invalid")
        if type(self.json_path) is not str or not self.json_path.startswith("$"):
            raise _fail("live occurrence JSON path is invalid")
        if self.container_kind not in _CONTAINER_KINDS:
            raise _fail("live occurrence container kind is invalid")
        if self.presence_kind not in _PRESENCE_KINDS:
            raise _fail("live occurrence presence kind is invalid")
        if self.presence_kind in {"missing", "null"} and self.row_count != 0:
            raise _fail("absent live occurrence carries rows")
        _validate_sha256(self.value_sha256, label="live occurrence value digest")
        _validate_sha256(self.occurrence_sha256, label="live occurrence digest")
        if _canonical_sha256(_result_occurrence_identity(self)) != self.occurrence_sha256:
            raise _fail("live occurrence digest differs from its identity")

    def to_dict(self) -> dict[str, object]:
        return {**_result_occurrence_identity(self), "occurrence_sha256": self.occurrence_sha256}


def _field_cell_identity(cell: DecodedLiveFieldCellV1) -> dict[str, object]:
    return {
        "cell_ordinal": cell.cell_ordinal,
        "canonical_json": cell.canonical_json,
        "concrete_json_path": cell.concrete_json_path,
        "context_result_set_name": cell.context_result_set_name,
        "context_result_set_occurrence": cell.context_result_set_occurrence,
        "context_result_set_ordinal": cell.context_result_set_ordinal,
        "field_json_path": cell.field_json_path,
        "field_name": cell.field_name,
        "field_ordinal": cell.field_ordinal,
        "key_presence": cell.key_presence,
        "node_ordinal": cell.node_ordinal,
        "owner_result_set_name": cell.owner_result_set_name,
        "owner_result_set_occurrence": cell.owner_result_set_occurrence,
        "owner_result_set_ordinal": cell.owner_result_set_ordinal,
        "owner_row_ordinal": cell.owner_row_ordinal,
        "presence_kind": cell.presence_kind,
        "value_kind": cell.value_kind,
        "value_sha256": cell.value_sha256,
    }


@dataclass(frozen=True, slots=True)
class DecodedLiveFieldCellV1:
    """One declared field value, including null, missing, and container values."""

    cell_ordinal: int
    node_ordinal: int
    concrete_json_path: str
    owner_result_set_name: str
    owner_result_set_ordinal: int
    owner_result_set_occurrence: int
    owner_row_ordinal: int | None
    context_result_set_name: str
    context_result_set_ordinal: int
    context_result_set_occurrence: int
    field_name: str
    field_ordinal: int
    field_json_path: str
    key_presence: str
    presence_kind: LivePresenceKind
    value_kind: LiveValueKind
    canonical_json: str | None
    value_sha256: str
    cell_sha256: str

    def __post_init__(self) -> None:
        for value, label, maximum in (
            (self.cell_ordinal, "live field-cell ordinal", MAX_LIVE_FIELD_CELLS - 1),
            (self.node_ordinal, "live field-cell node ordinal", MAX_JSON_NODES - 1),
            (
                self.owner_result_set_ordinal,
                "live field owner result ordinal",
                MAX_LIVE_RESULT_SETS - 1,
            ),
            (
                self.owner_result_set_occurrence,
                "live field owner occurrence",
                MAX_LIVE_RESULT_OCCURRENCES - 1,
            ),
            (
                self.context_result_set_ordinal,
                "live field context result ordinal",
                MAX_LIVE_RESULT_SETS - 1,
            ),
            (
                self.context_result_set_occurrence,
                "live field context occurrence",
                MAX_LIVE_RESULT_OCCURRENCES - 1,
            ),
            (self.field_ordinal, "live field ordinal", MAX_LIVE_FIELDS_PER_RESULT - 1),
        ):
            _integer(value, label=label, maximum=maximum)
        _optional_bounded_ordinal(
            self.owner_row_ordinal,
            label="live field owner row ordinal",
            maximum=MAX_JSON_CONTAINER_ITEMS - 1,
        )
        for value, label in (
            (self.concrete_json_path, "live field concrete path"),
            (self.owner_result_set_name, "live field owner result name"),
            (self.context_result_set_name, "live field context result name"),
            (self.field_name, "live field name"),
            (self.field_json_path, "live field contract path"),
            (self.key_presence, "live field key presence"),
        ):
            if type(value) is not str or not value:
                raise _fail(f"{label} is invalid")
        if self.presence_kind not in _PRESENCE_KINDS or self.value_kind not in _VALUE_KINDS:
            raise _fail("live field-cell value/presence kind is invalid")
        _validate_sha256(self.value_sha256, label="live field-cell value digest")
        _validate_sha256(self.cell_sha256, label="live field-cell digest")
        if _canonical_sha256(_field_cell_identity(self)) != self.cell_sha256:
            raise _fail("live field-cell digest differs from its identity")

    def to_dict(self) -> dict[str, object]:
        return {**_field_cell_identity(self), "cell_sha256": self.cell_sha256}


def _result_set_identity(item: DecodedLiveResultSetV1) -> dict[str, object]:
    return {
        "container_count": item.container_count,
        "container_kind": item.container_kind,
        "field_cell_count": item.field_cell_count,
        "ordered_headers": list(item.ordered_headers),
        "headers_sha256": item.headers_sha256,
        "json_path": item.json_path,
        "missing_count": item.missing_count,
        "name": item.name,
        "normalized_output_sha256": item.normalized_output_sha256,
        "null_count": item.null_count,
        "observed_field_orders_sha256": item.observed_field_orders_sha256,
        "ordinal": item.ordinal,
        "parent_field_name": item.parent_field_name,
        "parent_observation_count": item.parent_observation_count,
        "parent_result_set_name": item.parent_result_set_name,
        "parent_occurrence_states_sha256": item.parent_occurrence_states_sha256,
        "presence": item.presence,
        "result_occurrence_count": item.result_occurrence_count,
        "row_count": item.row_count,
        "value_cell_count": item.value_cell_count,
    }


@dataclass(frozen=True, slots=True)
class DecodedLiveResultSetV1:
    """One canonical result-set declaration plus independently derived counts."""

    name: str
    ordinal: int
    json_path: str
    container_kind: str
    parent_result_set_name: str | None
    parent_field_name: str | None
    ordered_headers: tuple[str, ...]
    headers_sha256: str
    presence: LiveResultPresence
    row_count: int
    value_cell_count: int
    field_cell_count: int
    container_count: int
    missing_count: int
    null_count: int
    parent_observation_count: int
    result_occurrence_count: int
    parent_occurrence_states_sha256: str
    observed_field_orders_sha256: str
    normalized_output_sha256: str
    result_set_sha256: str

    def __post_init__(self) -> None:
        _integer(self.ordinal, label="live result-set ordinal", maximum=MAX_LIVE_RESULT_SETS - 1)
        for value, label, maximum in (
            (self.row_count, "live result row count", MAX_JSON_CONTAINER_ITEMS),
            (self.value_cell_count, "live result value-cell count", MAX_LIVE_FIELD_CELLS),
            (self.field_cell_count, "live result field-cell count", MAX_LIVE_FIELD_CELLS),
            (self.container_count, "live result container count", MAX_LIVE_RESULT_OCCURRENCES),
            (self.missing_count, "live result missing count", MAX_LIVE_RESULT_OCCURRENCES),
            (self.null_count, "live result null count", MAX_LIVE_RESULT_OCCURRENCES),
            (
                self.parent_observation_count,
                "live parent observation count",
                MAX_LIVE_RESULT_OCCURRENCES,
            ),
            (
                self.result_occurrence_count,
                "live result occurrence count",
                MAX_LIVE_RESULT_OCCURRENCES,
            ),
        ):
            _integer(value, label=label, maximum=maximum)
        if type(self.name) is not str or not self.name:
            raise _fail("live result-set name is invalid")
        if type(self.json_path) is not str or not self.json_path.startswith("$."):
            raise _fail("live result-set JSON path is invalid")
        if self.container_kind not in _CONTAINER_KINDS:
            raise _fail("live result-set container kind is invalid")
        if (self.parent_result_set_name is None) != (self.parent_field_name is None):
            raise _fail("live result-set parent identity is partial")
        if type(self.ordered_headers) is not tuple or any(
            type(header) is not str or not header for header in self.ordered_headers
        ):
            raise _fail("live result-set headers are invalid")
        if self.presence not in _RESULT_PRESENCES:
            raise _fail("live result-set presence is invalid")
        if self.value_cell_count != self.row_count * len(self.ordered_headers):
            raise _fail("live result-set value-cell denominator is invalid")
        if self.result_occurrence_count != self.parent_observation_count:
            raise _fail("live result occurrence denominator differs from parent observations")
        if (
            self.container_count + self.missing_count + self.null_count
            != self.parent_observation_count
        ):
            raise _fail("live result parent-state denominators are inconsistent")
        if self.container_count == 0:
            if self.parent_observation_count == 0:
                expected_presence: LiveResultPresence = "not_observed_parent_empty"
            elif self.missing_count and self.null_count:
                expected_presence = "mixed_absent"
            elif self.missing_count:
                expected_presence = "missing"
            elif self.null_count:
                expected_presence = "null"
            else:
                raise _fail("live absent result has no lossless parent state")
        elif (
            self.container_kind == "nba_api_live_json_array"
            and self.container_count == 1
            and self.row_count == 0
            and self.missing_count == 0
            and self.null_count == 0
        ):
            expected_presence = "empty_array"
        else:
            expected_presence = "present"
        if self.presence != expected_presence:
            raise _fail("live result presence differs from its exact denominators")
        for digest, label in (
            (self.headers_sha256, "live headers digest"),
            (
                self.parent_occurrence_states_sha256,
                "live parent-occurrence-states digest",
            ),
            (self.observed_field_orders_sha256, "live observed-field-order digest"),
            (self.normalized_output_sha256, "live normalized-output digest"),
            (self.result_set_sha256, "live result-set digest"),
        ):
            _validate_sha256(digest, label=label)
        if _canonical_sha256(list(self.ordered_headers)) != self.headers_sha256:
            raise _fail("live result-set headers digest differs from its headers")
        if _canonical_sha256(_result_set_identity(self)) != self.result_set_sha256:
            raise _fail("live result-set digest differs from its identity")

    def to_dict(self) -> dict[str, object]:
        return {**_result_set_identity(self), "result_set_sha256": self.result_set_sha256}


def _response_identity(response: DecodedLiveResponseV1) -> dict[str, object]:
    return {
        "anomaly_codes": list(response.anomaly_codes),
        "contract_result_set_count": response.contract_result_set_count,
        "endpoint_contract_sha256": response.endpoint_contract_sha256,
        "endpoint_id": response.endpoint_id,
        "endpoint_slug": response.endpoint_slug,
        "field_cell_count": response.field_cell_count,
        "field_cells_sha256": response.field_cells_sha256,
        "missing_node_count": response.missing_node_count,
        "node_count": response.node_count,
        "nodes_sha256": response.nodes_sha256,
        "null_node_count": response.null_node_count,
        "parser_input_length": response.parser_input_length,
        "parser_input_sha256": response.parser_input_sha256,
        "present_empty_node_count": response.present_empty_node_count,
        "result_occurrence_count": response.result_occurrence_count,
        "result_occurrences_sha256": response.result_occurrences_sha256,
        "result_sets_sha256": response.result_sets_sha256,
    }


@dataclass(frozen=True, slots=True)
class DecodedLiveResponseV1:
    """Complete immutable live response reconstruction from exact parser bytes."""

    endpoint_id: str
    endpoint_slug: str
    endpoint_contract_sha256: str
    parser_input_sha256: str
    parser_input_length: int
    anomaly_codes: tuple[str, ...]
    contract_result_set_count: int
    node_count: int
    result_occurrence_count: int
    field_cell_count: int
    missing_node_count: int
    null_node_count: int
    present_empty_node_count: int
    result_sets_sha256: str
    result_occurrences_sha256: str
    nodes_sha256: str
    field_cells_sha256: str
    response_sha256: str
    result_sets: tuple[DecodedLiveResultSetV1, ...]
    result_occurrences: tuple[DecodedLiveResultOccurrenceV1, ...]
    nodes: tuple[DecodedLiveNodeV1, ...]
    field_cells: tuple[DecodedLiveFieldCellV1, ...]

    def __post_init__(self) -> None:
        if type(self.endpoint_id) is not str or not self.endpoint_id:
            raise _fail("decoded live endpoint id is invalid")
        if type(self.endpoint_slug) is not str or not self.endpoint_slug:
            raise _fail("decoded live endpoint slug is invalid")
        for digest, label in (
            (self.endpoint_contract_sha256, "decoded live contract digest"),
            (self.parser_input_sha256, "decoded live parser-input digest"),
            (self.result_sets_sha256, "decoded live result-set inventory digest"),
            (
                self.result_occurrences_sha256,
                "decoded live result-occurrence inventory digest",
            ),
            (self.nodes_sha256, "decoded live node inventory digest"),
            (self.field_cells_sha256, "decoded live field-cell inventory digest"),
            (self.response_sha256, "decoded live response digest"),
        ):
            _validate_sha256(digest, label=label)
        for value, label, maximum in (
            (self.parser_input_length, "decoded live parser-input length", MAX_PARSER_INPUT_BYTES),
            (self.contract_result_set_count, "decoded live result-set count", MAX_LIVE_RESULT_SETS),
            (self.node_count, "decoded live node count", MAX_JSON_NODES),
            (
                self.result_occurrence_count,
                "decoded live result occurrence count",
                MAX_LIVE_RESULT_OCCURRENCES,
            ),
            (self.field_cell_count, "decoded live field-cell count", MAX_LIVE_FIELD_CELLS),
            (self.missing_node_count, "decoded live missing-node count", MAX_JSON_NODES),
            (self.null_node_count, "decoded live null-node count", MAX_JSON_NODES),
            (
                self.present_empty_node_count,
                "decoded live present-empty-node count",
                MAX_JSON_NODES,
            ),
        ):
            _integer(value, label=label, maximum=maximum)
        if self.parser_input_length == 0:
            raise _fail("decoded live parser-input length must be positive")
        if (
            type(self.anomaly_codes) is not tuple
            or self.anomaly_codes != tuple(sorted(set(self.anomaly_codes)))
            or any(
                type(code) is not str or code not in _ANOMALY_CODES for code in self.anomaly_codes
            )
        ):
            raise _fail("decoded live anomaly inventory is invalid")
        if type(self.result_sets) is not tuple or any(
            type(item) is not DecodedLiveResultSetV1 for item in self.result_sets
        ):
            raise _fail("decoded live result-set inventory type is invalid")
        if type(self.result_occurrences) is not tuple or any(
            type(item) is not DecodedLiveResultOccurrenceV1 for item in self.result_occurrences
        ):
            raise _fail("decoded live result-occurrence inventory type is invalid")
        if type(self.nodes) is not tuple or any(
            type(item) is not DecodedLiveNodeV1 for item in self.nodes
        ):
            raise _fail("decoded live node inventory type is invalid")
        if type(self.field_cells) is not tuple or any(
            type(item) is not DecodedLiveFieldCellV1 for item in self.field_cells
        ):
            raise _fail("decoded live field-cell inventory type is invalid")
        if (
            len(self.result_sets) != self.contract_result_set_count
            or len(self.nodes) != self.node_count
            or len(self.result_occurrences) != self.result_occurrence_count
            or len(self.field_cells) != self.field_cell_count
        ):
            raise _fail("decoded live inventory counts are incomplete")
        if tuple(item.ordinal for item in self.result_sets) != tuple(range(len(self.result_sets))):
            raise _fail("decoded live result-set ordinals are not contiguous")
        contract = _pinned_live_contracts().get(self.endpoint_id)
        if (
            contract is None
            or contract.endpoint_slug != self.endpoint_slug
            or contract.contract_sha256 != self.endpoint_contract_sha256
            or len(contract.result_sets) != self.contract_result_set_count
        ):
            raise _fail("decoded live response differs from its frozen endpoint contract")
        for observed, expected in zip(self.result_sets, contract.result_sets, strict=True):
            if (
                observed.name != expected.name
                or observed.ordinal != expected.ordinal
                or observed.json_path != expected.json_path
                or observed.container_kind != expected.container_kind
                or observed.parent_result_set_name != expected.parent_result_set_name
                or observed.parent_field_name != expected.parent_field_name
                or observed.ordered_headers != tuple(field.name for field in expected.fields)
            ):
                raise _fail("decoded live result-set declaration differs from its contract")
        if tuple(item.node_ordinal for item in self.nodes) != tuple(range(len(self.nodes))):
            raise _fail("decoded live node ordinals are not contiguous")
        if tuple(item.global_ordinal for item in self.result_occurrences) != tuple(
            range(len(self.result_occurrences))
        ):
            raise _fail("decoded live global result-occurrence ordinals are not contiguous")
        if tuple(item.cell_ordinal for item in self.field_cells) != tuple(
            range(len(self.field_cells))
        ):
            raise _fail("decoded live field-cell ordinals are not contiguous")
        if not self.nodes or (
            self.nodes[0].json_path != "$" or self.nodes[0].parent_node_ordinal is not None
        ):
            raise _fail("decoded live root node is invalid")
        if len({item.json_path for item in self.nodes}) != len(self.nodes):
            raise _fail("decoded live node paths are duplicated")
        for item in self.nodes[1:]:
            if item.parent_node_ordinal is None or item.parent_node_ordinal >= item.node_ordinal:
                raise _fail("decoded live node parent order is invalid")
            parent = self.nodes[item.parent_node_ordinal]
            if item.parent_json_path != parent.json_path or item.depth != parent.depth + 1:
                raise _fail("decoded live node parent path is invalid")
        occurrence_counts: Counter[str] = Counter()
        occurrence_by_node: dict[int, DecodedLiveResultOccurrenceV1] = {}
        result_by_name = {item.name: item for item in self.result_sets}
        for item in self.result_occurrences:
            declared = result_by_name.get(item.result_set_name)
            if (
                declared is None
                or item.result_set_ordinal != declared.ordinal
                or item.container_kind != declared.container_kind
                or item.parent_result_set_name != declared.parent_result_set_name
                or (
                    item.parent_result_set_ordinal
                    != (
                        None
                        if declared.parent_result_set_name is None
                        else result_by_name[declared.parent_result_set_name].ordinal
                    )
                )
            ):
                raise _fail("decoded live result occurrence differs from its declaration")
            if item.occurrence_ordinal != occurrence_counts[item.result_set_name]:
                raise _fail("decoded live per-result occurrence ordinals are not contiguous")
            occurrence_counts[item.result_set_name] += 1
            if item.node_ordinal in occurrence_by_node:
                raise _fail("decoded live result occurrences share a node")
            occurrence_by_node[item.node_ordinal] = item
        matched_nodes = {
            item.node_ordinal for item in self.nodes if item.container_kind is not None
        }
        if matched_nodes != set(occurrence_by_node):
            raise _fail("decoded live result occurrences differ from matched nodes")
        for node_ordinal, occurrence in occurrence_by_node.items():
            node = self.nodes[node_ordinal]
            if (
                node.result_set_name != occurrence.result_set_name
                or node.result_set_ordinal != occurrence.result_set_ordinal
                or node.result_set_occurrence != occurrence.occurrence_ordinal
                or node.json_path != occurrence.json_path
                or node.container_kind != occurrence.container_kind
                or node.presence_kind != occurrence.presence_kind
                or node.value_sha256 != occurrence.value_sha256
            ):
                raise _fail("decoded live result occurrence differs from its node")
        cell_counts: Counter[str] = Counter()
        for cell in self.field_cells:
            node = self.nodes[cell.node_ordinal]
            owner = result_by_name.get(cell.owner_result_set_name)
            context = result_by_name.get(cell.context_result_set_name)
            if owner is None or context is None:
                raise _fail("decoded live field cell names an undeclared result set")
            field = next(
                (
                    item
                    for item in contract.result_sets[owner.ordinal].fields
                    if item.name == cell.field_name
                ),
                None,
            )
            if (
                field is None
                or cell.owner_result_set_ordinal != owner.ordinal
                or cell.context_result_set_ordinal != context.ordinal
                or cell.field_ordinal != field.ordinal
                or cell.field_json_path != field.json_path
                or cell.key_presence != field.key_presence
                or cell.concrete_json_path != node.json_path
                or cell.presence_kind != node.presence_kind
                or cell.value_kind != node.value_kind
                or cell.canonical_json != node.canonical_json
                or cell.value_sha256 != node.value_sha256
            ):
                raise _fail("decoded live field cell differs from its node")
            cell_counts[cell.owner_result_set_name] += 1
        if any(
            occurrence_counts[item.name] != item.result_occurrence_count
            or cell_counts[item.name] != item.field_cell_count
            for item in self.result_sets
        ):
            raise _fail("decoded live result-set denominators differ from their inventories")
        if self.missing_node_count != sum(
            item.presence_kind == "missing" for item in self.nodes
        ) or self.null_node_count != sum(item.presence_kind == "null" for item in self.nodes):
            raise _fail("decoded live missing/null denominators are invalid")
        if self.present_empty_node_count != sum(
            item.presence_kind in {"empty_object", "empty_array"} for item in self.nodes
        ):
            raise _fail("decoded live present-empty denominator is invalid")
        expected_digests = (
            _canonical_sha256([item.result_set_sha256 for item in self.result_sets]),
            _canonical_sha256([item.occurrence_sha256 for item in self.result_occurrences]),
            _canonical_sha256([item.node_sha256 for item in self.nodes]),
            _canonical_sha256([item.cell_sha256 for item in self.field_cells]),
        )
        if expected_digests != (
            self.result_sets_sha256,
            self.result_occurrences_sha256,
            self.nodes_sha256,
            self.field_cells_sha256,
        ):
            raise _fail("decoded live inventory digest is invalid")
        if _canonical_sha256(_response_identity(self)) != self.response_sha256:
            raise _fail("decoded live response digest differs from its identity")
        _validate_response_projection(self, contract)

    def to_dict(self) -> dict[str, object]:
        """Return a detached full response representation."""

        return {
            **_response_identity(self),
            "field_cells": [item.to_dict() for item in self.field_cells],
            "nodes": [item.to_dict() for item in self.nodes],
            "response_sha256": self.response_sha256,
            "result_occurrences": [item.to_dict() for item in self.result_occurrences],
            "result_sets": [item.to_dict() for item in self.result_sets],
        }

    def to_canonical_bytes(self) -> bytes:
        """Return a bounded canonical serialization for fixed-point comparison."""

        validated = validate_decoded_live_response(self)
        return _canonical_json_bytes(validated.to_dict(), maximum=MAX_CANONICAL_INVENTORY_BYTES)


@dataclass(frozen=True, slots=True)
class _ResultObservation:
    containers: tuple[object, ...]
    rows: tuple[object, ...]
    parent_states: tuple[str, ...]

    @property
    def missing_count(self) -> int:
        return self.parent_states.count("missing")

    @property
    def null_count(self) -> int:
        return self.parent_states.count("null")


def _json_value_kind(value: object) -> LiveValueKind:
    if value is None:
        return "null"
    if type(value) is bool:
        return "boolean"
    if type(value) is int:
        return "integer"
    if type(value) is float:
        if not math.isfinite(value):
            raise _fail("live JSON contains a non-finite number")
        return "number"
    if type(value) is str:
        return "string"
    if type(value) is list:
        return "array"
    if type(value) is dict:
        return "object"
    raise _fail("live response contains a non-JSON value")


def _presence_kind(value: object) -> LivePresenceKind:
    if value is None:
        return "null"
    if type(value) is dict and not value:
        return "empty_object"
    if type(value) is list and not value:
        return "empty_array"
    return "present"


def _validate_field_value(field: _LiveFieldContract, value: object) -> None:
    value_type = _json_value_kind(value)
    if value_type == "null" and field.nullable:
        return
    if value_type == "integer" and "number" in field.sample_types:
        return
    if value_type not in field.sample_types:
        raise _fail("live field value type differs from the frozen contract")


def _is_scalar_projection(result_set: _LiveResultSetContract) -> bool:
    return (
        len(result_set.fields) == 1
        and not result_set.fields[0].source_field
        and result_set.fields[0].name == "value"
    )


def _validate_result_container(
    result_set: _LiveResultSetContract,
    value: object,
    child_field_names: frozenset[str],
) -> tuple[tuple[object, ...], tuple[str, ...]]:
    if result_set.container_kind == "nba_api_live_json_array":
        if type(value) is not list:
            raise _fail("live result set must be an array")
        records = tuple(cast("list[object]", value))
    elif result_set.container_kind == "nba_api_live_json_object":
        if type(value) is not dict:
            raise _fail("live result set must be an object")
        records = (value,)
    else:  # pragma: no cover - frozen-contract parser rejects this first
        raise _fail("live result set has an unsupported container contract")
    if _is_scalar_projection(result_set):
        for item in records:
            _validate_field_value(result_set.fields[0], item)
        return records, ()
    allowed_fields = {field.name for field in result_set.fields} | set(child_field_names)
    required_fields = {
        field.name for field in result_set.fields if field.key_presence == "required"
    }
    by_name = {field.name: field for field in result_set.fields}
    anomalies: set[str] = set()
    for record in records:
        if type(record) is not dict:
            raise _fail("live result set must contain only objects")
        exact = cast("dict[str, object]", record)
        if set(exact) - allowed_fields:
            anomalies.add("additive_field")
        if required_fields - set(exact):
            raise _fail("live result set omitted required fields")
        for name, item in exact.items():
            field = by_name.get(name)
            if field is not None:
                _validate_field_value(field, item)
    return records, tuple(sorted(anomalies))


def _reject_error_envelope(payload: Mapping[str, object]) -> None:
    meta = payload.get("meta")
    status_candidates = (
        payload.get("statusCode"),
        payload.get("status"),
        payload.get("code"),
        cast("dict[str, object]", meta).get("code") if type(meta) is dict else None,
    )
    if any(type(candidate) is int and candidate >= 400 for candidate in status_candidates):
        raise _fail("live JSON contains an error status envelope")
    has_result_envelope = "resultSets" in payload or "resultSet" in payload
    if not has_result_envelope and any(key in payload for key in ("Message", "message", "error")):
        raise _fail("live JSON contains an application error envelope")


def _validate_envelope(
    contract: _LiveEndpointContract,
    payload: dict[str, object],
) -> tuple[dict[str, _ResultObservation], tuple[str, ...]]:
    _reject_error_envelope(payload)
    expected_roots = contract.envelope_root_order
    actual_roots = tuple(payload)
    if set(expected_roots) - set(actual_roots):
        raise _fail("live response omitted a required envelope root")
    anomalies: set[str] = set()
    if set(actual_roots) - set(expected_roots):
        anomalies.add("additive_envelope_root")
    if tuple(root for root in actual_roots if root in expected_roots) != expected_roots:
        anomalies.add("reordered_envelope_root")
    by_name = {item.name: item for item in contract.result_sets}
    observations: dict[str, _ResultObservation] = {}
    for result_set in contract.result_sets:
        parent_states: list[str] = []
        if result_set.parent_result_set_name is None:
            root_name = result_set.json_path.removeprefix("$.")
            containers = (payload[root_name],)
            parent_states.append("present")
        else:
            parent = observations[result_set.parent_result_set_name]
            parent_field = cast("str", result_set.parent_field_name)
            parent_contract = by_name[result_set.parent_result_set_name]
            field_contract = next(
                (field for field in parent_contract.fields if field.name == parent_field),
                None,
            )
            if field_contract is None:
                raise _fail("live nested result set lacks its parent field contract")
            nested: list[object] = []
            for parent_row in parent.rows:
                if type(parent_row) is not dict:
                    raise _fail("live nested result-set parent is not an object")
                exact_parent = cast("dict[str, object]", parent_row)
                if parent_field not in exact_parent:
                    parent_states.append("missing")
                    if field_contract.key_presence == "required":
                        raise _fail("live response omitted a required nested field")
                    continue
                child = exact_parent[parent_field]
                if child is None:
                    parent_states.append("null")
                    if not field_contract.nullable:
                        raise _fail("live nested result-set field cannot be null")
                    continue
                parent_states.append("present")
                nested.append(child)
            containers = tuple(nested)
        child_fields = frozenset(
            child.parent_field_name
            for child in contract.result_sets
            if child.parent_result_set_name == result_set.name
            and child.parent_field_name is not None
        )
        rows: list[object] = []
        for container in containers:
            records, result_anomalies = _validate_result_container(
                result_set, container, child_fields
            )
            rows.extend(records)
            anomalies.update(result_anomalies)
        observations[result_set.name] = _ResultObservation(
            containers=containers,
            rows=tuple(rows),
            parent_states=tuple(parent_states),
        )
    return observations, tuple(sorted(anomalies))


@dataclass(frozen=True, slots=True)
class _ResultContext:
    contract: _LiveResultSetContract
    occurrence: int
    row_ordinal: int | None


def _path_matches(pattern: Sequence[str], tokens: Sequence[_PathToken]) -> bool:
    return len(pattern) == len(tokens) and all(
        (expected == "*" and type(observed) is int) or expected == observed
        for expected, observed in zip(pattern, tokens, strict=True)
    )


def _concrete_json_path(tokens: Sequence[_PathToken]) -> str:
    path = "$"
    for token in tokens:
        if type(token) is int:
            path += f"[{token}]"
        else:
            path += f"[{_canonical_json_text(token)}]"
    return path


class _ValueDigestBudget:
    def __init__(self) -> None:
        self.consumed = 0

    def digest(self, value: object) -> str:
        encoded = _canonical_json_bytes(value, maximum=MAX_CANONICAL_INVENTORY_BYTES)
        if len(encoded) > MAX_TOTAL_VALUE_DIGEST_BYTES - self.consumed:
            raise _fail("live cumulative canonical value bytes exceed their bound")
        self.consumed += len(encoded)
        return hashlib.sha256(encoded).hexdigest()


class _Projector:
    def __init__(
        self,
        contract: _LiveEndpointContract,
        *,
        value_digest_budget: _ValueDigestBudget,
    ) -> None:
        self.contract = contract
        self.value_digest_budget = value_digest_budget
        self.nodes: list[DecodedLiveNodeV1] = []
        self.result_occurrences: list[DecodedLiveResultOccurrenceV1] = []
        self.field_cells: list[DecodedLiveFieldCellV1] = []
        self.occurrence_counts: Counter[str] = Counter()

    def project(self, payload: dict[str, object]) -> None:
        self._visit(
            payload,
            tokens=(),
            parent_node_ordinal=None,
            object_key=None,
            object_key_ordinal=None,
            array_ordinal=None,
            inherited_context=None,
            record_contract=None,
        )

    def _matching_result_set(self, tokens: tuple[_PathToken, ...]) -> _LiveResultSetContract | None:
        matches = tuple(
            item for item in self.contract.result_sets if _path_matches(item.traversal_path, tokens)
        )
        if len(matches) > 1:
            raise _fail("live JSON path matches multiple frozen result-set contracts")
        return matches[0] if matches else None

    def _new_context(
        self,
        result_set: _LiveResultSetContract,
        *,
        value: object,
    ) -> _ResultContext:
        occurrence = self.occurrence_counts[result_set.name]
        if occurrence >= MAX_LIVE_RESULT_OCCURRENCES:
            raise _fail("live result occurrence count exceeds its bound")
        self.occurrence_counts[result_set.name] += 1
        row_ordinal = 0 if type(value) is dict else None
        return _ResultContext(result_set, occurrence, row_ordinal)

    def _append_result_occurrence(
        self,
        *,
        context: _ResultContext,
        node_ordinal: int,
        path: str,
        value: object,
        presence: LivePresenceKind,
        value_sha256: str,
    ) -> None:
        if len(self.result_occurrences) >= MAX_LIVE_RESULT_OCCURRENCES:
            raise _fail("live global result occurrence count exceeds its bound")
        row_count = (
            len(cast("list[object]", value))
            if type(value) is list
            else (1 if type(value) is dict else 0)
        )
        contract = context.contract
        payload = {
            "container_kind": contract.container_kind,
            "global_ordinal": len(self.result_occurrences),
            "json_path": path,
            "node_ordinal": node_ordinal,
            "occurrence_ordinal": context.occurrence,
            "parent_result_set_name": contract.parent_result_set_name,
            "parent_result_set_ordinal": (
                None
                if contract.parent_result_set_name is None
                else next(
                    item.ordinal
                    for item in self.contract.result_sets
                    if item.name == contract.parent_result_set_name
                )
            ),
            "presence_kind": presence,
            "result_set_name": contract.name,
            "result_set_ordinal": contract.ordinal,
            "row_count": row_count,
            "value_sha256": value_sha256,
        }
        self.result_occurrences.append(
            DecodedLiveResultOccurrenceV1(
                **payload,
                occurrence_sha256=_canonical_sha256(payload),
            )
        )

    def _append_field_cell(
        self,
        *,
        node: DecodedLiveNodeV1,
        field: _LiveFieldContract,
        owner_context: _ResultContext,
        context: _ResultContext,
    ) -> None:
        if len(self.field_cells) >= MAX_LIVE_FIELD_CELLS:
            raise _fail("live field-cell count exceeds its bound")
        payload = {
            "cell_ordinal": len(self.field_cells),
            "canonical_json": node.canonical_json,
            "concrete_json_path": node.json_path,
            "context_result_set_name": context.contract.name,
            "context_result_set_occurrence": context.occurrence,
            "context_result_set_ordinal": context.contract.ordinal,
            "field_json_path": field.json_path,
            "field_name": field.name,
            "field_ordinal": field.ordinal,
            "key_presence": field.key_presence,
            "node_ordinal": node.node_ordinal,
            "owner_result_set_name": owner_context.contract.name,
            "owner_result_set_occurrence": owner_context.occurrence,
            "owner_result_set_ordinal": owner_context.contract.ordinal,
            "owner_row_ordinal": owner_context.row_ordinal,
            "presence_kind": node.presence_kind,
            "value_kind": node.value_kind,
            "value_sha256": node.value_sha256,
        }
        self.field_cells.append(
            DecodedLiveFieldCellV1(**payload, cell_sha256=_canonical_sha256(payload))
        )

    def _build_node(
        self,
        *,
        value: object,
        tokens: tuple[_PathToken, ...],
        parent_node_ordinal: int | None,
        object_key: str | None,
        object_key_ordinal: int | None,
        array_ordinal: int | None,
        context: _ResultContext | None,
        matched: _ResultContext | None,
        field: _LiveFieldContract | None,
        known_field: bool | None,
        missing: bool,
    ) -> DecodedLiveNodeV1:
        if len(self.nodes) >= MAX_JSON_NODES:
            raise _fail("live projected node count exceeds its bound")
        node_ordinal = len(self.nodes)
        if missing:
            presence: LivePresenceKind = "missing"
            value_kind: LiveValueKind = "missing"
            canonical_json = None
        else:
            presence = _presence_kind(value)
            value_kind = _json_value_kind(value)
            canonical_json = (
                _canonical_json_text(value)
                if value_kind not in {"object", "array"} or presence != "present"
                else None
            )
        value_sha256 = self.value_digest_budget.digest(
            {"presence": presence}
            if presence == "missing"
            else {"presence": presence, "value": value}
        )
        payload = {
            "array_ordinal": array_ordinal,
            "canonical_json": canonical_json,
            "container_kind": matched.contract.container_kind if matched is not None else None,
            "contract_field_ordinal": field.ordinal if field is not None else None,
            "contract_json_path": context.contract.json_path if context is not None else None,
            "depth": len(tokens),
            "json_path": _concrete_json_path(tokens),
            "known_contract_field": known_field,
            "node_ordinal": node_ordinal,
            "object_key": object_key,
            "object_key_ordinal": object_key_ordinal,
            "parent_json_path": _concrete_json_path(tokens[:-1]) if tokens else None,
            "parent_node_ordinal": parent_node_ordinal,
            "presence_kind": presence,
            "result_set_name": context.contract.name if context is not None else None,
            "result_set_occurrence": context.occurrence if context is not None else None,
            "result_set_ordinal": context.contract.ordinal if context is not None else None,
            "result_set_row_ordinal": context.row_ordinal if context is not None else None,
            "value_kind": value_kind,
            "value_sha256": value_sha256,
        }
        node = DecodedLiveNodeV1(**payload, node_sha256=_canonical_sha256(payload))
        self.nodes.append(node)
        if matched is not None:
            self._append_result_occurrence(
                context=matched,
                node_ordinal=node_ordinal,
                path=node.json_path,
                value=value,
                presence=presence,
                value_sha256=value_sha256,
            )
        return node

    def _visit(
        self,
        value: object,
        *,
        tokens: tuple[_PathToken, ...],
        parent_node_ordinal: int | None,
        object_key: str | None,
        object_key_ordinal: int | None,
        array_ordinal: int | None,
        inherited_context: _ResultContext | None,
        record_contract: _LiveResultSetContract | None,
    ) -> None:
        matched_contract = self._matching_result_set(tokens)
        matched = (
            None if matched_contract is None else self._new_context(matched_contract, value=value)
        )
        context = matched or inherited_context
        field: _LiveFieldContract | None = None
        known_field: bool | None = None
        owner_context = inherited_context
        if object_key is not None and record_contract is not None:
            field = next((item for item in record_contract.fields if item.name == object_key), None)
            child_fields = {
                item.parent_field_name
                for item in self.contract.result_sets
                if item.parent_result_set_name == record_contract.name
            }
            known_field = field is not None or object_key in child_fields
        elif (
            object_key is None
            and record_contract is not None
            and _is_scalar_projection(record_contract)
            and array_ordinal is not None
        ):
            field = record_contract.fields[0]
            owner_context = inherited_context
        node = self._build_node(
            value=value,
            tokens=tokens,
            parent_node_ordinal=parent_node_ordinal,
            object_key=object_key,
            object_key_ordinal=object_key_ordinal,
            array_ordinal=array_ordinal,
            context=context,
            matched=matched,
            field=(field if object_key is not None else None),
            known_field=known_field,
            missing=False,
        )
        if field is not None and owner_context is not None and context is not None:
            self._append_field_cell(
                node=node,
                field=field,
                owner_context=owner_context,
                context=context,
            )
        if type(value) is dict:
            active_record = (
                matched.contract
                if matched is not None
                and matched.contract.container_kind == "nba_api_live_json_object"
                else record_contract
            )
            exact = cast("dict[str, object]", value)
            for child_ordinal, (key, child) in enumerate(exact.items()):
                self._visit(
                    child,
                    tokens=(*tokens, key),
                    parent_node_ordinal=node.node_ordinal,
                    object_key=key,
                    object_key_ordinal=child_ordinal,
                    array_ordinal=None,
                    inherited_context=context,
                    record_contract=active_record,
                )
            if active_record is not None:
                for expected in active_record.fields:
                    if expected.name not in exact:
                        self._visit_missing(
                            tokens=(*tokens, expected.name),
                            parent_node_ordinal=node.node_ordinal,
                            object_key=expected.name,
                            inherited_context=context,
                            record_contract=active_record,
                            field=expected,
                        )
        elif type(value) is list:
            item_record = (
                matched.contract
                if matched is not None
                and matched.contract.container_kind == "nba_api_live_json_array"
                else None
            )
            for item_ordinal, child in enumerate(cast("list[object]", value)):
                child_context = context
                if context is not None and item_record is not None:
                    child_context = _ResultContext(
                        context.contract, context.occurrence, item_ordinal
                    )
                self._visit(
                    child,
                    tokens=(*tokens, item_ordinal),
                    parent_node_ordinal=node.node_ordinal,
                    object_key=None,
                    object_key_ordinal=None,
                    array_ordinal=item_ordinal,
                    inherited_context=child_context,
                    record_contract=item_record,
                )

    def _visit_missing(
        self,
        *,
        tokens: tuple[_PathToken, ...],
        parent_node_ordinal: int,
        object_key: str,
        inherited_context: _ResultContext | None,
        record_contract: _LiveResultSetContract,
        field: _LiveFieldContract,
    ) -> None:
        matched_contract = self._matching_result_set(tokens)
        matched = (
            None if matched_contract is None else self._new_context(matched_contract, value=None)
        )
        context = matched or inherited_context
        node = self._build_node(
            value=None,
            tokens=tokens,
            parent_node_ordinal=parent_node_ordinal,
            object_key=object_key,
            object_key_ordinal=None,
            array_ordinal=None,
            context=context,
            matched=matched,
            field=field,
            known_field=True,
            missing=True,
        )
        if inherited_context is None or context is None:
            raise _fail("live missing field has no exact result context")
        self._append_field_cell(
            node=node,
            field=field,
            owner_context=inherited_context,
            context=context,
        )


def _result_presence(
    result_set: _LiveResultSetContract,
    observation: _ResultObservation,
) -> LiveResultPresence:
    if not observation.containers:
        if not observation.parent_states:
            return "not_observed_parent_empty"
        if observation.missing_count and not observation.null_count:
            return "missing"
        if observation.null_count and not observation.missing_count:
            return "null"
        if observation.missing_count and observation.null_count:
            return "mixed_absent"
        raise _fail("live absent result has no lossless parent state")
    if (
        result_set.container_kind == "nba_api_live_json_array"
        and len(observation.containers) == 1
        and observation.containers[0] == []
        and not observation.missing_count
        and not observation.null_count
    ):
        return "empty_array"
    return "present"


def _build_result_sets(
    contract: _LiveEndpointContract,
    observations: Mapping[str, _ResultObservation],
    projector: _Projector,
    *,
    value_digest_budget: _ValueDigestBudget,
) -> tuple[DecodedLiveResultSetV1, ...]:
    results: list[DecodedLiveResultSetV1] = []
    occurrence_counts = Counter(item.result_set_name for item in projector.result_occurrences)
    cell_counts = Counter(item.owner_result_set_name for item in projector.field_cells)
    for result_set in contract.result_sets:
        observation = observations[result_set.name]
        headers = tuple(field.name for field in result_set.fields)
        if any(state not in _PARENT_STATES for state in observation.parent_states):
            raise _fail("live parent-state inventory is invalid")
        expected_value_cells = len(observation.rows) * len(headers)
        if occurrence_counts[result_set.name] != len(observation.parent_states):
            raise _fail("live result occurrence denominator is incomplete")
        payload = {
            "container_count": len(observation.containers),
            "container_kind": result_set.container_kind,
            "field_cell_count": cell_counts[result_set.name],
            "ordered_headers": headers,
            "headers_sha256": _canonical_sha256(list(headers)),
            "json_path": result_set.json_path,
            "missing_count": observation.missing_count,
            "name": result_set.name,
            "normalized_output_sha256": value_digest_budget.digest(
                {
                    "containers": list(observation.containers),
                    "missing_count": observation.missing_count,
                    "null_count": observation.null_count,
                }
            ),
            "null_count": observation.null_count,
            "observed_field_orders_sha256": value_digest_budget.digest(
                [list(row) if type(row) is dict else [] for row in observation.rows]
            ),
            "ordinal": result_set.ordinal,
            "parent_field_name": result_set.parent_field_name,
            "parent_observation_count": len(observation.parent_states),
            "parent_result_set_name": result_set.parent_result_set_name,
            "parent_occurrence_states_sha256": value_digest_budget.digest(
                list(observation.parent_states)
            ),
            "presence": _result_presence(result_set, observation),
            "result_occurrence_count": occurrence_counts[result_set.name],
            "row_count": len(observation.rows),
            "value_cell_count": expected_value_cells,
        }
        results.append(
            DecodedLiveResultSetV1(
                **payload,
                result_set_sha256=_canonical_sha256(payload),
            )
        )
    return tuple(results)


def _reconstruct_payload_from_nodes(nodes: Sequence[DecodedLiveNodeV1]) -> dict[str, object]:
    """Rebuild and structurally validate the exact JSON tree carried by node DTOs."""

    if not nodes:
        raise _fail("decoded live node inventory is empty")
    values: dict[int, object] = {}
    object_ordinals: dict[int, list[int]] = {}
    array_ordinals: dict[int, list[int]] = {}
    child_counts: Counter[int] = Counter()
    root: object | None = None
    for node in nodes:
        if node.presence_kind == "missing":
            value: object | None = None
        elif node.value_kind == "object":
            value = {}
        elif node.value_kind == "array":
            value = []
        else:
            if type(node.canonical_json) is not str:
                raise _fail("decoded live scalar canonical value is absent")
            try:
                value = json.loads(
                    node.canonical_json,
                    object_pairs_hook=_reject_duplicate_object_keys,
                    parse_int=_bounded_json_integer,
                    parse_float=_bounded_json_float,
                    parse_constant=_reject_json_constant,
                )
            except IndependentLiveValueDecoderError:
                raise
            except (TypeError, ValueError, json.JSONDecodeError) as exc:
                raise _fail("decoded live scalar canonical value is invalid") from exc
            if (
                _json_value_kind(value) != node.value_kind
                or _canonical_json_text(value) != node.canonical_json
            ):
                raise _fail("decoded live scalar kind differs from its canonical value")
        if node.node_ordinal == 0:
            if (
                node.parent_node_ordinal is not None
                or node.parent_json_path is not None
                or node.json_path != "$"
                or node.depth != 0
                or node.object_key is not None
                or node.object_key_ordinal is not None
                or node.array_ordinal is not None
                or node.presence_kind == "missing"
            ):
                raise _fail("decoded live root edge is invalid")
            root = value
        else:
            parent_ordinal = node.parent_node_ordinal
            if (
                type(parent_ordinal) is not int
                or parent_ordinal < 0
                or parent_ordinal >= node.node_ordinal
            ):
                raise _fail("decoded live node parent ordinal is invalid")
            parent_node = nodes[parent_ordinal]
            parent = values.get(parent_ordinal)
            if (
                node.parent_json_path != parent_node.json_path
                or node.depth != parent_node.depth + 1
            ):
                raise _fail("decoded live node parent path is invalid")
            if type(parent) is dict:
                if (
                    type(node.object_key) is not str
                    or node.array_ordinal is not None
                    or (node.presence_kind == "missing" and node.object_key_ordinal is not None)
                    or (
                        node.presence_kind != "missing" and type(node.object_key_ordinal) is not int
                    )
                    or node.json_path
                    != f"{parent_node.json_path}[{_canonical_json_text(node.object_key)}]"
                ):
                    raise _fail("decoded live object edge is invalid")
                if node.presence_kind != "missing":
                    key_ordinal = cast("int", node.object_key_ordinal)
                    object_ordinals.setdefault(parent_ordinal, []).append(key_ordinal)
                    cast("dict[str, object]", parent)[node.object_key] = cast("object", value)
                    child_counts[parent_ordinal] += 1
            elif type(parent) is list:
                if (
                    type(node.array_ordinal) is not int
                    or node.object_key is not None
                    or node.object_key_ordinal is not None
                    or node.presence_kind == "missing"
                    or node.json_path != f"{parent_node.json_path}[{node.array_ordinal}]"
                ):
                    raise _fail("decoded live array edge is invalid")
                exact_parent = cast("list[object]", parent)
                if node.array_ordinal != len(exact_parent):
                    raise _fail("decoded live array ordinals are not contiguous")
                exact_parent.append(cast("object", value))
                array_ordinals.setdefault(parent_ordinal, []).append(node.array_ordinal)
                child_counts[parent_ordinal] += 1
            else:
                raise _fail("decoded live scalar node has a child")
        if node.presence_kind != "missing":
            values[node.node_ordinal] = cast("object", value)
        else:
            values[node.node_ordinal] = None

    for ordinals in (*object_ordinals.values(), *array_ordinals.values()):
        if ordinals != list(range(len(ordinals))):
            raise _fail("decoded live child ordinals are not contiguous")
    value_budget = _ValueDigestBudget()
    for node in nodes:
        value = values[node.node_ordinal]
        child_count = child_counts[node.node_ordinal]
        if node.presence_kind == "missing":
            if node.value_kind != "missing" or node.canonical_json is not None or child_count:
                raise _fail("decoded live missing-node algebra is invalid")
            digest_payload: object = {"presence": "missing"}
        elif node.presence_kind == "null":
            if node.value_kind != "null" or node.canonical_json != "null" or child_count:
                raise _fail("decoded live null-node algebra is invalid")
            digest_payload = {"presence": "null", "value": None}
        elif node.presence_kind == "empty_object":
            if node.value_kind != "object" or node.canonical_json != "{}" or child_count:
                raise _fail("decoded live empty-object algebra is invalid")
            digest_payload = {"presence": "empty_object", "value": value}
        elif node.presence_kind == "empty_array":
            if node.value_kind != "array" or node.canonical_json != "[]" or child_count:
                raise _fail("decoded live empty-array algebra is invalid")
            digest_payload = {"presence": "empty_array", "value": value}
        elif node.presence_kind == "present":
            if node.value_kind in {"missing", "null"}:
                raise _fail("decoded live present-node kind is invalid")
            if node.value_kind in {"object", "array"}:
                if node.canonical_json is not None or child_count == 0:
                    raise _fail("decoded live present-container algebra is invalid")
            elif type(node.canonical_json) is not str or child_count:
                raise _fail("decoded live present-scalar algebra is invalid")
            digest_payload = {"presence": "present", "value": value}
        else:  # pragma: no cover - DTO enum validation rejects this first
            raise _fail("decoded live node presence is invalid")
        if value_budget.digest(digest_payload) != node.value_sha256:
            raise _fail("decoded live node value digest differs from its reconstructed value")
    if type(root) is not dict:
        raise _fail("decoded live response root must be an object")
    return cast("dict[str, object]", root)


def _validate_response_projection(
    response: DecodedLiveResponseV1,
    contract: _LiveEndpointContract,
) -> None:
    """Require the sealed inventories to be the exact projection of their own tree."""

    payload = _reconstruct_payload_from_nodes(response.nodes)
    observations, anomaly_codes = _validate_envelope(contract, payload)
    value_digest_budget = _ValueDigestBudget()
    projector = _Projector(contract, value_digest_budget=value_digest_budget)
    projector.project(payload)
    result_sets = _build_result_sets(
        contract,
        observations,
        projector,
        value_digest_budget=value_digest_budget,
    )
    if anomaly_codes != response.anomaly_codes:
        raise _fail("decoded live anomaly inventory differs from reconstructed values")
    if tuple(projector.nodes) != response.nodes:
        raise _fail("decoded live nodes differ from the exact reconstructed projection")
    if tuple(projector.result_occurrences) != response.result_occurrences:
        raise _fail("decoded live occurrences differ from the reconstructed projection")
    if tuple(projector.field_cells) != response.field_cells:
        raise _fail("decoded live field cells differ from the reconstructed projection")
    if result_sets != response.result_sets:
        raise _fail("decoded live result summaries differ from reconstructed values")


def decode_live_value_response(
    parser_input: bytes,
    *,
    endpoint_id: str,
    endpoint_contract_sha256: str,
) -> DecodedLiveResponseV1:
    """Decode one exact live response through the frozen independent grammar."""

    if type(endpoint_id) is not str or not endpoint_id:
        raise _fail("live endpoint identity must be a nonempty exact string")
    requested_digest = _validate_sha256(
        endpoint_contract_sha256, label="live endpoint contract digest"
    )
    contract = _pinned_live_contracts().get(endpoint_id)
    if contract is None or contract.contract_sha256 != requested_digest:
        raise _fail("live endpoint identity differs from the exact frozen contract")
    payload_value = _decode_json_bytes(
        parser_input,
        maximum=MAX_PARSER_INPUT_BYTES,
        label="live parser input",
        require_object=True,
    )
    payload = cast("dict[str, object]", payload_value)
    observations, anomaly_codes = _validate_envelope(contract, payload)
    value_digest_budget = _ValueDigestBudget()
    projector = _Projector(contract, value_digest_budget=value_digest_budget)
    projector.project(payload)
    result_sets = _build_result_sets(
        contract,
        observations,
        projector,
        value_digest_budget=value_digest_budget,
    )
    occurrences = tuple(projector.result_occurrences)
    nodes = tuple(projector.nodes)
    cells = tuple(projector.field_cells)
    parser_input_sha256 = hashlib.sha256(parser_input).hexdigest()
    result_sets_sha256 = _canonical_sha256([item.result_set_sha256 for item in result_sets])
    occurrences_sha256 = _canonical_sha256([item.occurrence_sha256 for item in occurrences])
    nodes_sha256 = _canonical_sha256([item.node_sha256 for item in nodes])
    cells_sha256 = _canonical_sha256([item.cell_sha256 for item in cells])
    response_payload = {
        "anomaly_codes": anomaly_codes,
        "contract_result_set_count": len(result_sets),
        "endpoint_contract_sha256": requested_digest,
        "endpoint_id": endpoint_id,
        "endpoint_slug": contract.endpoint_slug,
        "field_cell_count": len(cells),
        "field_cells_sha256": cells_sha256,
        "missing_node_count": sum(item.presence_kind == "missing" for item in nodes),
        "node_count": len(nodes),
        "nodes_sha256": nodes_sha256,
        "null_node_count": sum(item.presence_kind == "null" for item in nodes),
        "parser_input_length": len(parser_input),
        "parser_input_sha256": parser_input_sha256,
        "present_empty_node_count": sum(
            item.presence_kind in {"empty_object", "empty_array"} for item in nodes
        ),
        "result_occurrence_count": len(occurrences),
        "result_occurrences_sha256": occurrences_sha256,
        "result_sets_sha256": result_sets_sha256,
    }
    return DecodedLiveResponseV1(
        **response_payload,
        response_sha256=_canonical_sha256(response_payload),
        result_sets=result_sets,
        result_occurrences=occurrences,
        nodes=nodes,
        field_cells=cells,
    )


def decode_live_value_rows(
    parser_input: bytes,
    *,
    endpoint_id: str,
    endpoint_contract_sha256: str,
) -> tuple[DecodedLiveNodeV1, ...]:
    """Return the exact ordered node projection as a thin response convenience."""

    return decode_live_value_response(
        parser_input,
        endpoint_id=endpoint_id,
        endpoint_contract_sha256=endpoint_contract_sha256,
    ).nodes


def validate_decoded_live_response(value: object) -> DecodedLiveResponseV1:
    """Strictly rebuild a public decoder DTO and every nested sealed inventory."""

    if type(value) is not DecodedLiveResponseV1:
        raise _fail("decoded live response has no exact public contract type")
    exact = value
    result_sets: list[DecodedLiveResultSetV1] = []
    for item in exact.result_sets:
        if type(item) is not DecodedLiveResultSetV1:
            raise _fail("decoded live result-set type is foreign")
        result_sets.append(replace(item))
    occurrences: list[DecodedLiveResultOccurrenceV1] = []
    for item in exact.result_occurrences:
        if type(item) is not DecodedLiveResultOccurrenceV1:
            raise _fail("decoded live result-occurrence type is foreign")
        occurrences.append(replace(item))
    nodes: list[DecodedLiveNodeV1] = []
    for item in exact.nodes:
        if type(item) is not DecodedLiveNodeV1:
            raise _fail("decoded live node type is foreign")
        nodes.append(replace(item))
    cells: list[DecodedLiveFieldCellV1] = []
    for item in exact.field_cells:
        if type(item) is not DecodedLiveFieldCellV1:
            raise _fail("decoded live field-cell type is foreign")
        cells.append(replace(item))
    return replace(
        exact,
        result_sets=tuple(result_sets),
        result_occurrences=tuple(occurrences),
        nodes=tuple(nodes),
        field_cells=tuple(cells),
    )


__all__ = [
    "DecodedLiveFieldCellV1",
    "DecodedLiveNodeV1",
    "DecodedLiveResponseV1",
    "DecodedLiveResultOccurrenceV1",
    "DecodedLiveResultSetV1",
    "IndependentLiveValueDecoderError",
    "decode_live_value_response",
    "decode_live_value_rows",
    "pinned_live_decoder_contract_identities",
    "validate_decoded_live_response",
]
