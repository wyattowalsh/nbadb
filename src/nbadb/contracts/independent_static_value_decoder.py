"""Dependency-pure decoding of exact pinned NBA static packet values.

The decoder reads only the frozen generated contract resource and caller-supplied
canonical packet bytes.  It deliberately does not import the provider runtime,
the production NBA API adapter, staging code, or orchestration code.
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
    from collections.abc import Mapping


MAX_PARSER_INPUT_BYTES: Final = 64 * 1024 * 1024
MAX_PINNED_CONTRACT_BYTES: Final = 2 * 1024 * 1024
MAX_JSON_DEPTH: Final = 32
MAX_JSON_NODES: Final = 1_000_000
MAX_JSON_CONTAINER_ITEMS: Final = 1_000_000
MAX_JSON_STRING_BYTES: Final = 4 * 1024 * 1024
MAX_JSON_TOTAL_STRING_BYTES: Final = 64 * 1024 * 1024
MAX_JSON_NUMBER_TOKEN_BYTES: Final = 64
MAX_JSON_INTEGER_ABS: Final = (1 << 63) - 1
MAX_STATIC_DATASETS: Final = 16
MAX_STATIC_FIELDS: Final = 128
MAX_STATIC_RECORDS: Final = 100_000
MAX_STATIC_CELLS: Final = 10_000_000
MAX_CANONICAL_VALUE_BYTES: Final = 8 * 1024 * 1024
MAX_CANONICAL_INVENTORY_BYTES: Final = 256 * 1024 * 1024

_RUNTIME_CONTRACT_RESOURCE: Final = "nba_api_runtime_contract_v1_11_4.json"
_PINNED_STATIC_CONTRACTS_SHA256: Final = (
    "ccd209d3d89356c9d368b8d45db94cf9c119d1329b2dc4764fbc112a1990caff"
)
_PINNED_DATASET_IDS: Final = frozenset(
    {"static_players", "static_teams", "static_wnba_players", "static_wnba_teams"}
)
_PINNED_DATASET_COUNT: Final = 4
_PINNED_FIELD_COUNT: Final = 26

_SHA256_RE: Final = re.compile(r"[0-9a-f]{64}\Z")
_SAMPLE_TYPES: Final = frozenset({"bool", "int", "list", "str"})
_PRESENCE_KINDS: Final = frozenset({"present", "null", "empty_array", "empty_object", "missing"})
_VALUE_KINDS: Final = frozenset(
    {"array", "boolean", "integer", "missing", "null", "number", "object", "string"}
)

_STATIC_DATASET_FIELDS: Final = frozenset(
    {
        "contract_sha256",
        "data_source_path",
        "data_source_sha256",
        "dataset_id",
        "declared_update_marker",
        "disposition_reason",
        "evidence",
        "extraction_coverage_effect",
        "gate_effects",
        "getter_name",
        "implementation_status",
        "model_disposition",
        "owner",
        "projected_fields",
        "projected_records_sha256",
        "provider_module",
        "provider_source_path",
        "provider_source_sha256",
        "raw_fields",
        "raw_records_sha256",
        "revalidation_path",
        "row_count",
        "source_family",
        "source_rows_sha256",
        "source_symbol",
        "unique_id_count",
    }
)
_STATIC_FIELD_FIELDS: Final = frozenset(
    {
        "disposition_reason",
        "extraction_coverage_effect",
        "model_disposition",
        "name",
        "ordinal",
        "owner",
        "provider_projection_disposition",
        "revalidation_path",
        "sample_type",
    }
)

StaticPresenceKind = Literal["present", "null", "empty_array", "empty_object", "missing"]
StaticValueKind = Literal[
    "array", "boolean", "integer", "missing", "null", "number", "object", "string"
]


class IndependentStaticValueDecoderError(ValueError):
    """Raised when packet bytes cannot prove the exact pinned static snapshot."""


def _fail(message: str) -> IndependentStaticValueDecoderError:
    return IndependentStaticValueDecoderError(message)


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
        raise _fail("static value is not bounded canonical JSON") from exc
    if len(encoded) > maximum:
        raise _fail("static canonical value bytes exceed their bound")
    return encoded


def _canonical_json_text(value: object) -> str:
    return _canonical_json_bytes(value, maximum=MAX_CANONICAL_VALUE_BYTES).decode("utf-8")


def _canonical_sha256(value: object, *, maximum: int = MAX_CANONICAL_INVENTORY_BYTES) -> str:
    return hashlib.sha256(_canonical_json_bytes(value, maximum=maximum)).hexdigest()


def _validate_sha256(value: object, *, label: str) -> str:
    if type(value) is not str or _SHA256_RE.fullmatch(value) is None:
        raise _fail(f"{label} must be a lowercase full SHA-256")
    return value


def _integer(value: object, *, label: str, maximum: int, minimum: int = 0) -> int:
    if type(value) is not int or value < minimum or value > maximum:
        raise _fail(f"{label} must be a bounded exact integer")
    return value


def _string(value: object, *, label: str) -> str:
    if type(value) is not str or not value:
        raise _fail(f"{label} must be a nonempty exact string")
    return value


def _exact_object(value: object, fields: frozenset[str], *, label: str) -> dict[str, object]:
    if type(value) is not dict or set(value) != fields:
        raise _fail(f"{label} fields differ from the frozen schema")
    return cast("dict[str, object]", value)


def _reject_duplicate_object_keys(pairs: list[tuple[str, object]]) -> dict[str, object]:
    output: dict[str, object] = {}
    for key, value in pairs:
        if key in output:
            raise _fail("static packet contains duplicate JSON object keys")
        output[key] = value
    return output


def _bounded_json_integer(token: str) -> int:
    if len(token) > MAX_JSON_NUMBER_TOKEN_BYTES:
        raise _fail("static JSON integer token exceeds its bound")
    try:
        value = int(token)
    except ValueError as exc:
        raise _fail("static JSON integer token is invalid") from exc
    if abs(value) > MAX_JSON_INTEGER_ABS:
        raise _fail("static JSON integer exceeds the signed 64-bit value bound")
    return value


def _bounded_json_float(token: str) -> float:
    if len(token) > MAX_JSON_NUMBER_TOKEN_BYTES:
        raise _fail("static JSON number token exceeds its bound")
    try:
        value = float(token)
    except ValueError as exc:
        raise _fail("static JSON number token is invalid") from exc
    if not math.isfinite(value):
        raise _fail("static JSON contains a non-finite number")
    return value


def _reject_json_constant(_token: str) -> object:
    raise _fail("static JSON contains a non-finite constant")


def _lexical_json_budget(text: str) -> None:
    """Reject deep or oversized tokens before the recursive decoder allocates them."""

    depth = 0
    index = 0
    in_string = False
    escaped = False
    string_bytes = 0
    total_string_bytes = 0
    structural_nodes = 1
    container_separators = 0
    while index < len(text):
        char = text[index]
        if in_string:
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == '"':
                in_string = False
                if string_bytes > MAX_JSON_STRING_BYTES:
                    raise _fail("static JSON string token exceeds its bound")
                string_bytes = 0
            else:
                encoded_length = len(char.encode("utf-8", errors="strict"))
                string_bytes += encoded_length
                total_string_bytes += encoded_length
                if total_string_bytes > MAX_JSON_TOTAL_STRING_BYTES:
                    raise _fail("static JSON cumulative string bytes exceed their bound")
            index += 1
            continue
        if char == '"':
            in_string = True
            string_bytes = 0
            index += 1
            continue
        if char in "[{":
            depth += 1
            structural_nodes += 1
            if depth > MAX_JSON_DEPTH:
                raise _fail("static JSON depth exceeds its bound")
        elif char in "]}":
            depth -= 1
            if depth < 0:
                raise _fail("static JSON container nesting is malformed")
        elif char == "-" or char.isdigit():
            end = index + 1
            while end < len(text) and text[end] in "0123456789+-.eE":
                end += 1
            if end - index > MAX_JSON_NUMBER_TOKEN_BYTES:
                raise _fail("static JSON number token exceeds its bound")
            index = end
            continue
        elif char == ",":
            container_separators += 1
            structural_nodes += 1
            if container_separators > MAX_JSON_CONTAINER_ITEMS:
                raise _fail("static JSON container item count exceeds its bound")
        if structural_nodes > MAX_JSON_NODES:
            raise _fail("static JSON node count exceeds its bound")
        index += 1
    if in_string or depth != 0:
        raise _fail("static JSON lexical structure is incomplete")


def _validate_json_budget(value: object) -> None:
    nodes = 0
    container_items = 0
    string_bytes = 0
    stack: list[tuple[object, int]] = [(value, 0)]
    while stack:
        item, depth = stack.pop()
        nodes += 1
        if nodes > MAX_JSON_NODES:
            raise _fail("static JSON node count exceeds its bound")
        if depth > MAX_JSON_DEPTH:
            raise _fail("static JSON depth exceeds its bound")
        if type(item) is dict:
            exact = cast("dict[str, object]", item)
            container_items += len(exact)
            for key, child in reversed(tuple(exact.items())):
                encoded = key.encode("utf-8", errors="strict")
                if len(encoded) > MAX_JSON_STRING_BYTES:
                    raise _fail("static JSON object key exceeds its bound")
                string_bytes += len(encoded)
                stack.append((child, depth + 1))
        elif type(item) is list:
            exact_list = cast("list[object]", item)
            container_items += len(exact_list)
            stack.extend((child, depth + 1) for child in reversed(exact_list))
        elif type(item) is str:
            encoded = item.encode("utf-8", errors="strict")
            if len(encoded) > MAX_JSON_STRING_BYTES:
                raise _fail("static JSON string value exceeds its bound")
            string_bytes += len(encoded)
        elif type(item) is int:
            if abs(item) > MAX_JSON_INTEGER_ABS:
                raise _fail("static JSON integer exceeds the signed 64-bit value bound")
        elif type(item) is float:
            if not math.isfinite(item):
                raise _fail("static JSON contains a non-finite number")
        elif item is not None and type(item) is not bool:
            raise _fail("static packet contains a non-JSON value")
        if container_items > MAX_JSON_CONTAINER_ITEMS:
            raise _fail("static JSON container item count exceeds its bound")
        if string_bytes > MAX_JSON_TOTAL_STRING_BYTES:
            raise _fail("static JSON cumulative string bytes exceed their bound")


def _decode_json_bytes(raw: bytes, *, maximum: int, label: str) -> tuple[object, str]:
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
        _validate_json_budget(value)
    except IndependentStaticValueDecoderError:
        raise
    except (
        UnicodeDecodeError,
        UnicodeEncodeError,
        json.JSONDecodeError,
        RecursionError,
        ValueError,
    ) as exc:
        raise _fail(f"{label} is not bounded valid UTF-8 JSON") from exc
    return value, text


def _decode_canonical_fragment(text: object) -> object:
    if type(text) is not str or not text:
        raise _fail("static cell canonical JSON is invalid")
    value, decoded = _decode_json_bytes(
        text.encode("utf-8", errors="strict"),
        maximum=MAX_CANONICAL_VALUE_BYTES,
        label="static cell canonical JSON",
    )
    if _canonical_json_text(value) != decoded:
        raise _fail("static cell value is not canonical JSON")
    return value


@dataclass(frozen=True, slots=True)
class _StaticFieldContract:
    name: str
    ordinal: int
    sample_type: str
    projected: bool


@dataclass(frozen=True, slots=True)
class _StaticDatasetContract:
    dataset_id: str
    source_symbol: str
    contract_sha256: str
    fields: tuple[_StaticFieldContract, ...]
    projected_fields: tuple[str, ...]
    row_count: int
    unique_id_count: int
    source_rows_sha256: str
    raw_records_sha256: str
    projected_records_sha256: str


def _parse_static_contract(raw: object) -> _StaticDatasetContract:
    value = _exact_object(raw, _STATIC_DATASET_FIELDS, label="static dataset contract")
    body = dict(value)
    contract_sha256 = _validate_sha256(body.pop("contract_sha256"), label="static contract digest")
    if _canonical_sha256(body) != contract_sha256:
        raise _fail("static dataset contract digest is invalid")
    if (
        value["source_family"] != "static"
        or value["model_disposition"] != "defined_and_implemented"
        or value["implementation_status"] != "complete"
    ):
        raise _fail("static dataset is not an implemented pinned snapshot")
    dataset_id = _string(value["dataset_id"], label="static dataset id")
    source_symbol = _string(value["source_symbol"], label="static source symbol")
    raw_fields = value["raw_fields"]
    if type(raw_fields) is not list or not raw_fields or len(raw_fields) > MAX_STATIC_FIELDS:
        raise _fail("static field inventory is invalid")
    projected_raw = value["projected_fields"]
    if type(projected_raw) is not list or any(
        type(item) is not str or not item for item in projected_raw
    ):
        raise _fail("static projected-field inventory is invalid")
    projected_fields = tuple(cast("list[str]", projected_raw))
    if len(set(projected_fields)) != len(projected_fields):
        raise _fail("static projected-field inventory contains duplicates")
    projected = set(projected_fields)
    fields: list[_StaticFieldContract] = []
    for ordinal, raw_field in enumerate(cast("list[object]", raw_fields)):
        field = _exact_object(raw_field, _STATIC_FIELD_FIELDS, label="static field contract")
        name = _string(field["name"], label="static field name")
        field_ordinal = _integer(
            field["ordinal"], label="static field ordinal", maximum=MAX_STATIC_FIELDS - 1
        )
        sample_type = _string(field["sample_type"], label="static field sample type")
        if field_ordinal != ordinal or sample_type not in _SAMPLE_TYPES:
            raise _fail("static field ordinal or sample type is invalid")
        is_projected = name in projected
        expected_disposition = (
            "projected_by_provider" if is_projected else "omitted_by_provider_projection"
        )
        if field["provider_projection_disposition"] != expected_disposition:
            raise _fail("static field projection disposition is inconsistent")
        fields.append(
            _StaticFieldContract(
                name=name,
                ordinal=field_ordinal,
                sample_type=sample_type,
                projected=is_projected,
            )
        )
    names = tuple(item.name for item in fields)
    if len(set(names)) != len(names) or any(name not in names for name in projected_fields):
        raise _fail("static field names or projection are inconsistent")
    row_count = _integer(
        value["row_count"], label="static row count", maximum=MAX_STATIC_RECORDS, minimum=1
    )
    unique_id_count = _integer(
        value["unique_id_count"],
        label="static unique id count",
        maximum=MAX_STATIC_RECORDS,
        minimum=1,
    )
    if row_count != unique_id_count:
        raise _fail("static dataset grain is not unique by identifier")
    return _StaticDatasetContract(
        dataset_id=dataset_id,
        source_symbol=source_symbol,
        contract_sha256=contract_sha256,
        fields=tuple(fields),
        projected_fields=projected_fields,
        row_count=row_count,
        unique_id_count=unique_id_count,
        source_rows_sha256=_validate_sha256(
            value["source_rows_sha256"], label="static source-row digest"
        ),
        raw_records_sha256=_validate_sha256(
            value["raw_records_sha256"], label="static raw-record digest"
        ),
        projected_records_sha256=_validate_sha256(
            value["projected_records_sha256"], label="static projected-record digest"
        ),
    )


@lru_cache(maxsize=1)
def _pinned_static_contracts() -> Mapping[str, _StaticDatasetContract]:
    resource = Path(__file__).with_name(_RUNTIME_CONTRACT_RESOURCE)
    raw = resource.read_bytes()
    payload, _text = _decode_json_bytes(
        raw,
        maximum=MAX_PINNED_CONTRACT_BYTES,
        label="pinned runtime contract resource",
    )
    if type(payload) is not dict:
        raise _fail("pinned runtime contract root must be an object")
    exact = cast("dict[str, object]", payload)
    section = exact.get("static_contracts")
    section_sha256 = exact.get("static_contracts_sha256")
    if (
        type(section) is not dict
        or type(section_sha256) is not str
        or section_sha256 != _PINNED_STATIC_CONTRACTS_SHA256
        or _canonical_sha256(section) != section_sha256
    ):
        raise _fail("pinned static contract section differs from its exact pin")
    raw_contracts = cast("dict[object, object]", section)
    if (
        len(raw_contracts) != _PINNED_DATASET_COUNT
        or len(raw_contracts) > MAX_STATIC_DATASETS
        or any(type(name) is not str for name in raw_contracts)
        or set(raw_contracts) != _PINNED_DATASET_IDS
    ):
        raise _fail("pinned static dataset inventory is invalid")
    contracts = {
        cast("str", name): _parse_static_contract(contract)
        for name, contract in sorted(raw_contracts.items(), key=lambda item: cast("str", item[0]))
    }
    if any(contract.dataset_id != name for name, contract in contracts.items()):
        raise _fail("pinned static dataset keys differ from their identities")
    if sum(len(contract.fields) for contract in contracts.values()) != _PINNED_FIELD_COUNT:
        raise _fail("pinned static field census differs from its exact pin")
    return MappingProxyType(contracts)


def pinned_static_decoder_contract_identities() -> Mapping[str, str]:
    """Return the exact dataset-to-contract identities admitted by this decoder."""

    return MappingProxyType(
        {name: contract.contract_sha256 for name, contract in _pinned_static_contracts().items()}
    )


def _value_kind(value: object) -> StaticValueKind:
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
    raise _fail("static packet contains a non-JSON value")


def _presence_kind(value: object) -> StaticPresenceKind:
    if value is None:
        return "null"
    if value == [] and type(value) is list:
        return "empty_array"
    if value == {} and type(value) is dict:
        return "empty_object"
    return "present"


def _headers_sha256(headers: tuple[str, ...]) -> str:
    return hashlib.sha256(
        json.dumps(list(headers), separators=(",", ":")).encode("utf-8")
    ).hexdigest()


def _field_identity(item: DecodedStaticFieldV1) -> dict[str, object]:
    return {
        "name": item.name,
        "ordinal": item.ordinal,
        "projected": item.projected,
        "sample_type": item.sample_type,
    }


@dataclass(frozen=True, slots=True)
class DecodedStaticFieldV1:
    """One exact ordered field declaration from the frozen static contract."""

    name: str
    ordinal: int
    sample_type: str
    projected: bool
    field_sha256: str

    def __post_init__(self) -> None:
        _string(self.name, label="decoded static field name")
        _integer(
            self.ordinal,
            label="decoded static field ordinal",
            maximum=MAX_STATIC_FIELDS - 1,
        )
        if (
            type(self.sample_type) is not str
            or self.sample_type not in _SAMPLE_TYPES
            or type(self.projected) is not bool
        ):
            raise _fail("decoded static field type/projection is invalid")
        _validate_sha256(self.field_sha256, label="decoded static field digest")
        if _canonical_sha256(_field_identity(self)) != self.field_sha256:
            raise _fail("decoded static field digest differs from its identity")

    def to_dict(self) -> dict[str, object]:
        return {**_field_identity(self), "field_sha256": self.field_sha256}


def _cell_identity(item: DecodedStaticCellV1) -> dict[str, object]:
    return {
        "canonical_json": item.canonical_json,
        "cell_ordinal": item.cell_ordinal,
        "duplicate_value_ordinal": item.duplicate_value_ordinal,
        "field_name": item.field_name,
        "field_ordinal": item.field_ordinal,
        "presence_kind": item.presence_kind,
        "record_ordinal": item.record_ordinal,
        "value_kind": item.value_kind,
        "value_sha256": item.value_sha256,
    }


@dataclass(frozen=True, slots=True)
class DecodedStaticCellV1:
    """One ordered, lossless static record-field value occurrence."""

    cell_ordinal: int
    record_ordinal: int
    field_name: str
    field_ordinal: int
    duplicate_value_ordinal: int
    presence_kind: StaticPresenceKind
    value_kind: StaticValueKind
    canonical_json: str
    value_sha256: str
    cell_sha256: str

    def __post_init__(self) -> None:
        _integer(
            self.cell_ordinal,
            label="decoded static cell ordinal",
            maximum=MAX_STATIC_CELLS - 1,
        )
        _integer(
            self.record_ordinal,
            label="decoded static cell record ordinal",
            maximum=MAX_STATIC_RECORDS - 1,
        )
        _integer(
            self.field_ordinal,
            label="decoded static cell field ordinal",
            maximum=MAX_STATIC_FIELDS - 1,
        )
        _integer(
            self.duplicate_value_ordinal,
            label="decoded static duplicate-value ordinal",
            maximum=MAX_STATIC_RECORDS - 1,
        )
        _string(self.field_name, label="decoded static cell field name")
        if (
            type(self.presence_kind) is not str
            or self.presence_kind not in _PRESENCE_KINDS
            or type(self.value_kind) is not str
            or self.value_kind not in _VALUE_KINDS
        ):
            raise _fail("decoded static cell presence/value kind is invalid")
        value = _decode_canonical_fragment(self.canonical_json)
        if (
            self.presence_kind == "missing"
            or _presence_kind(value) != self.presence_kind
            or _value_kind(value) != self.value_kind
        ):
            raise _fail("decoded static cell value differs from its presence/type identity")
        expected_value_sha256 = hashlib.sha256(self.canonical_json.encode("utf-8")).hexdigest()
        _validate_sha256(self.value_sha256, label="decoded static cell value digest")
        _validate_sha256(self.cell_sha256, label="decoded static cell digest")
        if self.value_sha256 != expected_value_sha256:
            raise _fail("decoded static cell value digest differs from its value")
        if _canonical_sha256(_cell_identity(self)) != self.cell_sha256:
            raise _fail("decoded static cell digest differs from its identity")

    def to_dict(self) -> dict[str, object]:
        return {**_cell_identity(self), "cell_sha256": self.cell_sha256}


def _record_identity(item: DecodedStaticRecordV1) -> dict[str, object]:
    return {
        "cell_count": item.cell_count,
        "cell_start_ordinal": item.cell_start_ordinal,
        "container_value_count": item.container_value_count,
        "duplicate_record_ordinal": item.duplicate_record_ordinal,
        "identifier": item.identifier,
        "missing_value_count": item.missing_value_count,
        "null_value_count": item.null_value_count,
        "present_empty_value_count": item.present_empty_value_count,
        "record_ordinal": item.record_ordinal,
        "scalar_value_count": item.scalar_value_count,
        "values_sha256": item.values_sha256,
    }


@dataclass(frozen=True, slots=True)
class DecodedStaticRecordV1:
    """One ordered static record occurrence bound to its exact cell slice."""

    record_ordinal: int
    identifier: int
    duplicate_record_ordinal: int
    cell_start_ordinal: int
    cell_count: int
    missing_value_count: int
    null_value_count: int
    present_empty_value_count: int
    scalar_value_count: int
    container_value_count: int
    values_sha256: str
    record_sha256: str

    def __post_init__(self) -> None:
        _integer(
            self.record_ordinal,
            label="decoded static record ordinal",
            maximum=MAX_STATIC_RECORDS - 1,
        )
        if (
            type(self.identifier) is not int
            or self.identifier <= 0
            or self.identifier > MAX_JSON_INTEGER_ABS
        ):
            raise _fail("decoded static record identifier must be a positive exact integer")
        for value, label, maximum in (
            (
                self.duplicate_record_ordinal,
                "decoded static duplicate-record ordinal",
                MAX_STATIC_RECORDS - 1,
            ),
            (self.cell_start_ordinal, "decoded static cell-start ordinal", MAX_STATIC_CELLS),
            (self.cell_count, "decoded static record cell count", MAX_STATIC_FIELDS),
            (self.missing_value_count, "decoded static record missing count", MAX_STATIC_FIELDS),
            (self.null_value_count, "decoded static record null count", MAX_STATIC_FIELDS),
            (
                self.present_empty_value_count,
                "decoded static record present-empty count",
                MAX_STATIC_FIELDS,
            ),
            (self.scalar_value_count, "decoded static record scalar count", MAX_STATIC_FIELDS),
            (
                self.container_value_count,
                "decoded static record container count",
                MAX_STATIC_FIELDS,
            ),
        ):
            _integer(value, label=label, maximum=maximum)
        if (
            self.missing_value_count
            + self.null_value_count
            + self.scalar_value_count
            + self.container_value_count
            != self.cell_count
        ):
            raise _fail("decoded static record value-kind denominators are inconsistent")
        if self.present_empty_value_count > self.container_value_count:
            raise _fail("decoded static record present-empty denominator is inconsistent")
        _validate_sha256(self.values_sha256, label="decoded static record-values digest")
        _validate_sha256(self.record_sha256, label="decoded static record digest")
        if _canonical_sha256(_record_identity(self)) != self.record_sha256:
            raise _fail("decoded static record digest differs from its identity")

    def to_dict(self) -> dict[str, object]:
        return {**_record_identity(self), "record_sha256": self.record_sha256}


def _response_identity(response: DecodedStaticResponseV1) -> dict[str, object]:
    return {
        "canonical_result_ordinal": response.canonical_result_ordinal,
        "cell_count": response.cell_count,
        "cells_sha256": response.cells_sha256,
        "container_kind": response.container_kind,
        "container_value_count": response.container_value_count,
        "dataset_id": response.dataset_id,
        "duplicate_record_count": response.duplicate_record_count,
        "duplicate_value_count": response.duplicate_value_count,
        "endpoint_contract_sha256": response.endpoint_contract_sha256,
        "field_count": response.field_count,
        "fields_sha256": response.fields_sha256,
        "headers_sha256": response.headers_sha256,
        "missing_value_count": response.missing_value_count,
        "normalized_output_sha256": response.normalized_output_sha256,
        "null_value_count": response.null_value_count,
        "parser_input_length": response.parser_input_length,
        "parser_input_sha256": response.parser_input_sha256,
        "present_empty_value_count": response.present_empty_value_count,
        "projected_fields": list(response.projected_fields),
        "projected_records_sha256": response.projected_records_sha256,
        "provider_result_ordinal": response.provider_result_ordinal,
        "raw_records_sha256": response.raw_records_sha256,
        "record_count": response.record_count,
        "records_sha256": response.records_sha256,
        "result_name": response.result_name,
        "scalar_value_count": response.scalar_value_count,
        "source_rows_sha256": response.source_rows_sha256,
        "source_symbol": response.source_symbol,
        "unique_identifier_count": response.unique_identifier_count,
    }


@dataclass(frozen=True, slots=True)
class DecodedStaticResponseV1:
    """Complete immutable reconstruction of one exact static packet."""

    dataset_id: str
    source_symbol: str
    result_name: str
    container_kind: str
    endpoint_contract_sha256: str
    parser_input_sha256: str
    parser_input_length: int
    provider_result_ordinal: int
    canonical_result_ordinal: int
    projected_fields: tuple[str, ...]
    field_count: int
    record_count: int
    cell_count: int
    unique_identifier_count: int
    duplicate_record_count: int
    duplicate_value_count: int
    missing_value_count: int
    null_value_count: int
    present_empty_value_count: int
    scalar_value_count: int
    container_value_count: int
    headers_sha256: str
    normalized_output_sha256: str
    source_rows_sha256: str
    raw_records_sha256: str
    projected_records_sha256: str
    fields_sha256: str
    records_sha256: str
    cells_sha256: str
    response_sha256: str
    fields: tuple[DecodedStaticFieldV1, ...]
    records: tuple[DecodedStaticRecordV1, ...]
    cells: tuple[DecodedStaticCellV1, ...]

    def __post_init__(self) -> None:
        _validate_static_response(self)

    def to_dict(self) -> dict[str, object]:
        return {
            **_response_identity(self),
            "cells": [item.to_dict() for item in self.cells],
            "fields": [item.to_dict() for item in self.fields],
            "records": [item.to_dict() for item in self.records],
            "response_sha256": self.response_sha256,
        }

    def to_canonical_bytes(self) -> bytes:
        validated = validate_decoded_static_response(self)
        return _canonical_json_bytes(validated.to_dict(), maximum=MAX_CANONICAL_INVENTORY_BYTES)


def _validate_static_rows(
    contract: _StaticDatasetContract,
    rows: list[list[object]],
) -> tuple[list[dict[str, object]], list[dict[str, object]]]:
    if len(rows) != contract.row_count:
        raise _fail("static packet row count differs from pinned authority")
    if len(rows) * len(contract.fields) > MAX_STATIC_CELLS:
        raise _fail("static packet cell count exceeds its bound")
    headers = tuple(field.name for field in contract.fields)
    raw_records: list[dict[str, object]] = []
    identifiers: list[int] = []
    for row in rows:
        if len(row) != len(contract.fields):
            raise _fail("static packet row width differs from pinned authority")
        for field, value in zip(contract.fields, row, strict=True):
            if type(value).__name__ != field.sample_type:
                raise _fail("static packet value type differs from pinned authority")
        identifier = row[0]
        if type(identifier) is not int or identifier <= 0 or identifier > MAX_JSON_INTEGER_ABS:
            raise _fail("static packet identifier is not a positive exact integer")
        identifiers.append(identifier)
        raw_records.append(dict(zip(headers, row, strict=True)))
    projected_records = [
        {name: record[name] for name in contract.projected_fields} for record in raw_records
    ]
    if (
        len(set(identifiers)) != contract.unique_id_count
        or _canonical_sha256(rows) != contract.source_rows_sha256
        or _canonical_sha256(raw_records) != contract.raw_records_sha256
        or _canonical_sha256(projected_records) != contract.projected_records_sha256
    ):
        raise _fail("static packet content differs from pinned authority")
    return raw_records, projected_records


def _record_counts(values: list[object]) -> tuple[int, int, int, int, int]:
    presences = tuple(_presence_kind(value) for value in values)
    kinds = tuple(_value_kind(value) for value in values)
    return (
        presences.count("missing"),
        presences.count("null"),
        sum(item in {"empty_array", "empty_object"} for item in presences),
        sum(item in {"boolean", "integer", "number", "string"} for item in kinds),
        sum(item in {"array", "object"} for item in kinds),
    )


def _validate_static_response(response: DecodedStaticResponseV1) -> None:
    _string(response.dataset_id, label="decoded static dataset id")
    contract = _pinned_static_contracts().get(response.dataset_id)
    if contract is None:
        raise _fail("decoded static response names a foreign dataset")
    for value, label in (
        (response.source_symbol, "decoded static source symbol"),
        (response.result_name, "decoded static result name"),
        (response.container_kind, "decoded static container kind"),
    ):
        _string(value, label=label)
    for digest, label in (
        (response.endpoint_contract_sha256, "decoded static contract digest"),
        (response.parser_input_sha256, "decoded static parser-input digest"),
        (response.headers_sha256, "decoded static headers digest"),
        (response.normalized_output_sha256, "decoded static normalized-output digest"),
        (response.source_rows_sha256, "decoded static source-row digest"),
        (response.raw_records_sha256, "decoded static raw-record digest"),
        (response.projected_records_sha256, "decoded static projected-record digest"),
        (response.fields_sha256, "decoded static field-inventory digest"),
        (response.records_sha256, "decoded static record-inventory digest"),
        (response.cells_sha256, "decoded static cell-inventory digest"),
        (response.response_sha256, "decoded static response digest"),
    ):
        _validate_sha256(digest, label=label)
    for value, label, maximum in (
        (
            response.parser_input_length,
            "decoded static parser-input length",
            MAX_PARSER_INPUT_BYTES,
        ),
        (response.provider_result_ordinal, "decoded static provider ordinal", 0),
        (response.canonical_result_ordinal, "decoded static canonical ordinal", 0),
        (response.field_count, "decoded static field count", MAX_STATIC_FIELDS),
        (response.record_count, "decoded static record count", MAX_STATIC_RECORDS),
        (response.cell_count, "decoded static cell count", MAX_STATIC_CELLS),
        (
            response.unique_identifier_count,
            "decoded static unique-identifier count",
            MAX_STATIC_RECORDS,
        ),
        (
            response.duplicate_record_count,
            "decoded static duplicate-record count",
            MAX_STATIC_RECORDS,
        ),
        (response.duplicate_value_count, "decoded static duplicate-value count", MAX_STATIC_CELLS),
        (response.missing_value_count, "decoded static missing-value count", MAX_STATIC_CELLS),
        (response.null_value_count, "decoded static null-value count", MAX_STATIC_CELLS),
        (
            response.present_empty_value_count,
            "decoded static present-empty count",
            MAX_STATIC_CELLS,
        ),
        (response.scalar_value_count, "decoded static scalar-value count", MAX_STATIC_CELLS),
        (
            response.container_value_count,
            "decoded static container-value count",
            MAX_STATIC_CELLS,
        ),
    ):
        _integer(value, label=label, maximum=maximum)
    if response.parser_input_length == 0:
        raise _fail("decoded static parser-input length must be positive")
    if type(response.projected_fields) is not tuple or any(
        type(item) is not str or not item for item in response.projected_fields
    ):
        raise _fail("decoded static projected-field inventory is invalid")
    if (
        response.source_symbol != contract.source_symbol
        or response.result_name != f"{contract.source_symbol}_shape_1"
        or response.container_kind != "nba_api_static_records"
        or response.endpoint_contract_sha256 != contract.contract_sha256
        or response.projected_fields != contract.projected_fields
    ):
        raise _fail("decoded static response differs from its frozen contract identity")
    if type(response.fields) is not tuple or any(
        type(item) is not DecodedStaticFieldV1 for item in response.fields
    ):
        raise _fail("decoded static field inventory type is invalid")
    if type(response.records) is not tuple or any(
        type(item) is not DecodedStaticRecordV1 for item in response.records
    ):
        raise _fail("decoded static record inventory type is invalid")
    if type(response.cells) is not tuple or any(
        type(item) is not DecodedStaticCellV1 for item in response.cells
    ):
        raise _fail("decoded static cell inventory type is invalid")
    if (
        len(response.fields) != response.field_count
        or len(response.records) != response.record_count
        or len(response.cells) != response.cell_count
        or response.cell_count != response.field_count * response.record_count
    ):
        raise _fail("decoded static inventory counts are incomplete")
    if response.field_count != len(contract.fields) or tuple(
        item.ordinal for item in response.fields
    ) != tuple(range(response.field_count)):
        raise _fail("decoded static field ordinals are not contiguous")
    for observed, expected in zip(response.fields, contract.fields, strict=True):
        if (
            observed.name != expected.name
            or observed.ordinal != expected.ordinal
            or observed.sample_type != expected.sample_type
            or observed.projected != expected.projected
        ):
            raise _fail("decoded static field differs from its frozen contract")
    if tuple(item.record_ordinal for item in response.records) != tuple(
        range(response.record_count)
    ):
        raise _fail("decoded static record ordinals are not contiguous")
    if tuple(item.cell_ordinal for item in response.cells) != tuple(range(response.cell_count)):
        raise _fail("decoded static cell ordinals are not contiguous")

    rows: list[list[object]] = []
    value_duplicates: Counter[tuple[int, str]] = Counter()
    record_duplicates: Counter[str] = Counter()
    missing_count = 0
    null_count = 0
    present_empty_count = 0
    scalar_count = 0
    container_count = 0
    duplicate_value_count = 0
    duplicate_record_count = 0
    for record in response.records:
        if record.cell_start_ordinal != record.record_ordinal * response.field_count:
            raise _fail("decoded static record cell slice is invalid")
        row_cells = response.cells[
            record.cell_start_ordinal : record.cell_start_ordinal + record.cell_count
        ]
        if len(row_cells) != response.field_count:
            raise _fail("decoded static record cell slice is incomplete")
        values: list[object] = []
        for field, cell in zip(response.fields, row_cells, strict=True):
            if (
                cell.record_ordinal != record.record_ordinal
                or cell.field_name != field.name
                or cell.field_ordinal != field.ordinal
            ):
                raise _fail("decoded static cell differs from its record/field binding")
            expected_duplicate = value_duplicates[(field.ordinal, cell.value_sha256)]
            if cell.duplicate_value_ordinal != expected_duplicate:
                raise _fail("decoded static duplicate-value ordinal is invalid")
            value_duplicates[(field.ordinal, cell.value_sha256)] += 1
            duplicate_value_count += expected_duplicate > 0
            value = _decode_canonical_fragment(cell.canonical_json)
            values.append(value)
        row_digest = _canonical_sha256(values)
        expected_record_duplicate = record_duplicates[row_digest]
        if (
            record.identifier != values[0]
            or record.cell_count != response.field_count
            or record.values_sha256 != row_digest
            or record.duplicate_record_ordinal != expected_record_duplicate
        ):
            raise _fail("decoded static record differs from its exact cell values")
        record_duplicates[row_digest] += 1
        duplicate_record_count += expected_record_duplicate > 0
        record_counts = _record_counts(values)
        if record_counts != (
            record.missing_value_count,
            record.null_value_count,
            record.present_empty_value_count,
            record.scalar_value_count,
            record.container_value_count,
        ):
            raise _fail("decoded static record counts differ from its exact cell values")
        missing_count += record_counts[0]
        null_count += record_counts[1]
        present_empty_count += record_counts[2]
        scalar_count += record_counts[3]
        container_count += record_counts[4]
        rows.append(values)

    raw_records, _projected_records = _validate_static_rows(contract, rows)
    headers = tuple(field.name for field in contract.fields)
    parser_bytes = _canonical_json_bytes(rows, maximum=MAX_PARSER_INPUT_BYTES)
    expected_digests = (
        _headers_sha256(headers),
        _canonical_sha256({"headers": list(headers), "rows": rows}),
        _canonical_sha256(rows),
        _canonical_sha256(raw_records),
        _canonical_sha256(
            [{name: row[name] for name in contract.projected_fields} for row in raw_records]
        ),
        _canonical_sha256([item.field_sha256 for item in response.fields]),
        _canonical_sha256([item.record_sha256 for item in response.records]),
        _canonical_sha256([item.cell_sha256 for item in response.cells]),
    )
    if expected_digests != (
        response.headers_sha256,
        response.normalized_output_sha256,
        response.source_rows_sha256,
        response.raw_records_sha256,
        response.projected_records_sha256,
        response.fields_sha256,
        response.records_sha256,
        response.cells_sha256,
    ):
        raise _fail("decoded static response digests differ from reconstructed values")
    if (
        len(parser_bytes) != response.parser_input_length
        or hashlib.sha256(parser_bytes).hexdigest() != response.parser_input_sha256
        or response.record_count != contract.row_count
        or response.unique_identifier_count
        != len({record.identifier for record in response.records})
        or response.unique_identifier_count != contract.unique_id_count
        or response.duplicate_record_count != duplicate_record_count
        or response.duplicate_value_count != duplicate_value_count
        or response.missing_value_count != missing_count
        or response.null_value_count != null_count
        or response.present_empty_value_count != present_empty_count
        or response.scalar_value_count != scalar_count
        or response.container_value_count != container_count
    ):
        raise _fail("decoded static response denominators differ from reconstructed values")
    if _canonical_sha256(_response_identity(response)) != response.response_sha256:
        raise _fail("decoded static response digest differs from its identity")


def decode_static_value_response(
    packet_bytes: bytes,
    *,
    dataset_id: str,
    endpoint_contract_sha256: str,
) -> DecodedStaticResponseV1:
    """Decode one exact canonical static packet against frozen contract authority."""

    _string(dataset_id, label="static dataset id")
    _validate_sha256(endpoint_contract_sha256, label="static endpoint contract digest")
    contract = _pinned_static_contracts().get(dataset_id)
    if contract is None or endpoint_contract_sha256 != contract.contract_sha256:
        raise _fail("static dataset identity differs from the exact frozen contract")
    decoded, text = _decode_json_bytes(
        packet_bytes,
        maximum=MAX_PARSER_INPUT_BYTES,
        label="static packet",
    )
    if type(decoded) is not list:
        raise _fail("static packet root must be an array of row arrays")
    raw_rows = cast("list[object]", decoded)
    if len(raw_rows) > MAX_STATIC_RECORDS or any(type(row) is not list for row in raw_rows):
        raise _fail("static packet root must be an array of row arrays")
    rows = cast("list[list[object]]", raw_rows)
    if _canonical_json_bytes(rows, maximum=MAX_PARSER_INPUT_BYTES).decode("utf-8") != text:
        raise _fail("static packet bytes are not exact canonical row JSON")
    raw_records, projected_records = _validate_static_rows(contract, rows)
    fields: list[DecodedStaticFieldV1] = []
    for field in contract.fields:
        payload = {
            "name": field.name,
            "ordinal": field.ordinal,
            "projected": field.projected,
            "sample_type": field.sample_type,
        }
        fields.append(DecodedStaticFieldV1(**payload, field_sha256=_canonical_sha256(payload)))

    value_duplicates: Counter[tuple[int, str]] = Counter()
    record_duplicates: Counter[str] = Counter()
    cells: list[DecodedStaticCellV1] = []
    records: list[DecodedStaticRecordV1] = []
    for record_ordinal, row in enumerate(rows):
        start = len(cells)
        for field, value in zip(contract.fields, row, strict=True):
            canonical_json = _canonical_json_text(value)
            value_sha256 = hashlib.sha256(canonical_json.encode("utf-8")).hexdigest()
            duplicate_value_ordinal = value_duplicates[(field.ordinal, value_sha256)]
            value_duplicates[(field.ordinal, value_sha256)] += 1
            cell_payload = {
                "canonical_json": canonical_json,
                "cell_ordinal": len(cells),
                "duplicate_value_ordinal": duplicate_value_ordinal,
                "field_name": field.name,
                "field_ordinal": field.ordinal,
                "presence_kind": _presence_kind(value),
                "record_ordinal": record_ordinal,
                "value_kind": _value_kind(value),
                "value_sha256": value_sha256,
            }
            cells.append(
                DecodedStaticCellV1(
                    **cell_payload,
                    cell_sha256=_canonical_sha256(cell_payload),
                )
            )
        values_sha256 = _canonical_sha256(row)
        duplicate_record_ordinal = record_duplicates[values_sha256]
        record_duplicates[values_sha256] += 1
        missing, null, present_empty, scalar, container = _record_counts(row)
        record_payload = {
            "cell_count": len(contract.fields),
            "cell_start_ordinal": start,
            "container_value_count": container,
            "duplicate_record_ordinal": duplicate_record_ordinal,
            "identifier": cast("int", row[0]),
            "missing_value_count": missing,
            "null_value_count": null,
            "present_empty_value_count": present_empty,
            "record_ordinal": record_ordinal,
            "scalar_value_count": scalar,
            "values_sha256": values_sha256,
        }
        records.append(
            DecodedStaticRecordV1(
                **record_payload,
                record_sha256=_canonical_sha256(record_payload),
            )
        )
    field_tuple = tuple(fields)
    record_tuple = tuple(records)
    cell_tuple = tuple(cells)
    headers = tuple(field.name for field in contract.fields)
    presence_counts = Counter(cell.presence_kind for cell in cells)
    value_counts = Counter(cell.value_kind for cell in cells)
    response_payload = {
        "canonical_result_ordinal": 0,
        "cell_count": len(cells),
        "cells_sha256": _canonical_sha256([item.cell_sha256 for item in cells]),
        "container_kind": "nba_api_static_records",
        "container_value_count": value_counts["array"] + value_counts["object"],
        "dataset_id": dataset_id,
        "duplicate_record_count": sum(item.duplicate_record_ordinal > 0 for item in records),
        "duplicate_value_count": sum(item.duplicate_value_ordinal > 0 for item in cells),
        "endpoint_contract_sha256": endpoint_contract_sha256,
        "field_count": len(fields),
        "fields_sha256": _canonical_sha256([item.field_sha256 for item in fields]),
        "headers_sha256": _headers_sha256(headers),
        "missing_value_count": presence_counts["missing"],
        "normalized_output_sha256": _canonical_sha256({"headers": list(headers), "rows": rows}),
        "null_value_count": presence_counts["null"],
        "parser_input_length": len(packet_bytes),
        "parser_input_sha256": hashlib.sha256(packet_bytes).hexdigest(),
        "present_empty_value_count": (
            presence_counts["empty_array"] + presence_counts["empty_object"]
        ),
        "projected_fields": contract.projected_fields,
        "projected_records_sha256": _canonical_sha256(projected_records),
        "provider_result_ordinal": 0,
        "raw_records_sha256": _canonical_sha256(raw_records),
        "record_count": len(records),
        "records_sha256": _canonical_sha256([item.record_sha256 for item in records]),
        "result_name": f"{contract.source_symbol}_shape_1",
        "scalar_value_count": sum(
            value_counts[kind] for kind in ("boolean", "integer", "number", "string")
        ),
        "source_rows_sha256": _canonical_sha256(rows),
        "source_symbol": contract.source_symbol,
        "unique_identifier_count": len({record.identifier for record in records}),
    }
    return DecodedStaticResponseV1(
        **response_payload,
        fields=field_tuple,
        records=record_tuple,
        cells=cell_tuple,
        response_sha256=_canonical_sha256(response_payload),
    )


def decode_static_value_rows(
    packet_bytes: bytes,
    *,
    dataset_id: str,
    endpoint_contract_sha256: str,
) -> tuple[DecodedStaticRecordV1, ...]:
    """Return the immutable ordered record inventory for one exact packet."""

    return decode_static_value_response(
        packet_bytes,
        dataset_id=dataset_id,
        endpoint_contract_sha256=endpoint_contract_sha256,
    ).records


def validate_decoded_static_response(value: object) -> DecodedStaticResponseV1:
    """Strictly rebuild a public response DTO and every nested sealed inventory."""

    if type(value) is not DecodedStaticResponseV1:
        raise _fail("decoded static response has no exact public contract type")
    exact = value
    fields: list[DecodedStaticFieldV1] = []
    for item in exact.fields:
        if type(item) is not DecodedStaticFieldV1:
            raise _fail("decoded static field type is foreign")
        fields.append(replace(item))
    records: list[DecodedStaticRecordV1] = []
    for item in exact.records:
        if type(item) is not DecodedStaticRecordV1:
            raise _fail("decoded static record type is foreign")
        records.append(replace(item))
    cells: list[DecodedStaticCellV1] = []
    for item in exact.cells:
        if type(item) is not DecodedStaticCellV1:
            raise _fail("decoded static cell type is foreign")
        cells.append(replace(item))
    return replace(exact, fields=tuple(fields), records=tuple(records), cells=tuple(cells))


__all__ = [
    "DecodedStaticCellV1",
    "DecodedStaticFieldV1",
    "DecodedStaticRecordV1",
    "DecodedStaticResponseV1",
    "IndependentStaticValueDecoderError",
    "decode_static_value_response",
    "decode_static_value_rows",
    "pinned_static_decoder_contract_identities",
    "validate_decoded_static_response",
]
