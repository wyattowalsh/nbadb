"""V2 typed-field evidence replayed from exact committed authorities.

Wire objects are structural receipts, not self-authorizing claims.  The public
replay validator rebuilds them through the production authority joins from a
V2 Arrow readback, raw-request bundle, field-fate structure, and exact raw
parser/static-record values.  V1 or foreign contract IDs deliberately require
a fresh full extraction.
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from datetime import datetime
from typing import ClassVar, Literal, Self, cast

import pyarrow as pa
import pyarrow.ipc as pa_ipc

from nbadb.contracts.canonical_arrow_value import (
    ArrowLogicalTypeV1,
    CanonicalArrowValueError,
    CanonicalArrowValueV1,
    ValueBudget,
    ValueBudgetLimits,
    canonical_arrow_array_scalar,
    canonical_arrow_scalar,
    canonical_arrow_type,
    checked_add,
    checked_product,
    compare_canonical_arrow_values,
)
from nbadb.contracts.field_fate_structure import (
    ConditionalRouteOccurrenceAuthorityV1,
    FieldFateStructureError,
    FieldFateStructureV1,
    LosslessFieldBindingV1,
    ProviderFieldSourceOccurrenceV1,
    RouteFieldBindingV1,
    RouteLandingFieldJoinV1,
    StatsLosslessFieldBindingV1,
    validate_conditional_route_occurrence_authority,
    validate_field_fate_structure,
)
from nbadb.contracts.independent_live_value_decoder import (
    DecodedLiveFieldCellV1,
    DecodedLiveResponseV1,
    IndependentLiveValueDecoderError,
    decode_live_value_response,
    validate_decoded_live_response,
)
from nbadb.contracts.independent_static_value_decoder import (
    IndependentStaticValueDecoderError,
    decode_static_value_response,
)
from nbadb.contracts.independent_stats_value_decoder import (
    DecodedObservedStatsResponseV1,
    DecodedObservedStatsResultV1,
    IndependentStatsValueDecoderError,
    decode_observed_lossless_stats_response,
    decode_stats_value_rows,
)
from nbadb.contracts.raw_request_authority import (
    LandingDisposition,
    ObservationRouteLandingV2,
    ParserInputObjectV2,
    RawRequestAuthorityBundleV2,
    RawRequestAuthorityError,
    RequestObservationV2,
    ResultContainerKind,
    ResultOccurrenceV2,
    decode_parser_input_object,
    validate_logical_provider_parameter_join,
    validate_raw_request_authority_bundle,
)
from nbadb.contracts.raw_request_reconstruction import (
    LiveSnapshotPlanAuthorityV2,
    RawRequestReconstructionError,
    reconstruct_raw_request_authority,
)
from nbadb.core.errors import ParserInputCaptureIntegrityError, ResponseContractError
from nbadb.core.nba_api_runtime_contract import (
    LiveResultSetContract,
    pinned_live_contracts,
    pinned_runtime_contracts,
)
from nbadb.extract.nba_api_adapter import (
    NbaApiUnknownResponse,
    fetch_static_packet,
    rederive_raw_authority_result_sets,
    rederive_raw_authority_unknown_stats_response,
)
from nbadb.orchestrate.staging_batches import (
    CANONICAL_FRAME_FORMAT,
    FRAME_CONTENT_HASH_CONTRACT,
    FRAME_SCHEMA_HASH_CONTRACT,
    CommittedStagingFrameReadbackV2,
    CommittedStagingRowSliceV2,
    validate_committed_row_partition,
)

SourceFamily = Literal["stats", "live", "static"]
DecoderKind = Literal[
    "stats_result_set_rows_v1",
    "live_record_projection_v1",
    "static_dataset_records_v1",
    "conditional_selected_result_rows_v2",
    "conditional_body_node_rows_v2",
    "conditional_hybrid_result_body_rows_v2",
    "conditional_live_lossless_rows_v2",
    "response_fixed_zero_v2",
]
ConditionalSourceShape = Literal[
    "selected_result_bound",
    "body_node_bound",
    "hybrid_result_body_bound",
    "live_lossless_bound",
]
RouteSourceShape = Literal[
    "result_occurrence_bound",
    "response_fixed_zero",
    "selected_result_bound",
    "body_node_bound",
    "hybrid_result_body_bound",
    "live_lossless_bound",
]
FieldOrigin = Literal[
    "provider_bound",
    "provider_multi_bound",
    "lossless_bound",
    "storage_only",
]
ValueAuthorityKind = Literal["source_verified", "storage_readback_only"]
SourceOccurrencePresence = Literal[
    "present",
    "missing",
    "null",
    "mixed_absent",
    "present_empty",
    "empty_object",
    "empty_array",
    "not_observed_parent_empty",
]

_SOURCE_OCCURRENCE_PRESENCES = {
    "present",
    "missing",
    "null",
    "mixed_absent",
    "present_empty",
    "empty_object",
    "empty_array",
    "not_observed_parent_empty",
}
_SOURCE_CONTAINER_KINDS = {
    "nba_api_result_set",
    "nba_api_static_records",
    "nba_api_live_json_array",
    "nba_api_live_json_object",
}
_LANDING_DISPOSITIONS = {
    "wide_only",
    "lossless_only",
    "wide_plus_lossless",
    "presence_only",
}
_BODY_NODE_INDEPENDENT_COLUMNS = frozenset(
    {
        "response_receipt_sha256",
        "provider_authority_sha256",
        "endpoint_contract_sha256",
        "parser_input_sha256",
        "canonical_payload_sha256",
        "parameters_sha256",
        "endpoint_id",
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
    }
)
_LIVE_INDEPENDENT_COLUMNS = frozenset(
    {
        "response_receipt_sha256",
        "provider_authority_sha256",
        "endpoint_contract_sha256",
        "endpoint_id",
        "endpoint_slug",
        "request_parameters_json",
        "record_kind",
        "result_set_name",
        "result_set_ordinal",
        "result_set_occurrence",
        "result_set_row_ordinal",
        "contract_json_path",
        "container_kind",
        "node_ordinal",
        "parent_node_ordinal",
        "json_path",
        "parent_json_path",
        "depth",
        "object_key",
        "object_key_ordinal",
        "contract_field_ordinal",
        "array_ordinal",
        "presence_kind",
        "value_kind",
        "canonical_json",
        "known_contract_field",
    }
)
_SELECTED_STATS_FALLBACK_COLUMNS = (
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

_DECODER_BY_SOURCE: dict[str, str] = {
    "stats": "stats_result_set_rows_v1",
    "live": "live_record_projection_v1",
    "static": "static_dataset_records_v1",
}
_CONDITIONAL_DECODER_BY_SHAPE: dict[str, str] = {
    "selected_result_bound": "conditional_selected_result_rows_v2",
    "body_node_bound": "conditional_body_node_rows_v2",
    "hybrid_result_body_bound": "conditional_hybrid_result_body_rows_v2",
    "live_lossless_bound": "conditional_live_lossless_rows_v2",
}
_SHA256_RE = re.compile(r"[0-9a-f]{64}\Z")

MAX_ROUTE_FIELDS = 4_096
MAX_ROUTE_ROWS = 1_000_000
MAX_ROUTE_OCCURRENCES = 1_000_000
MAX_ROUTE_CELLS = 10_000_000
MAX_ROUTE_VALUE_NODES = 20_000_000
MAX_ROUTE_VALUE_BYTES = 256 * 1024 * 1024
MAX_ROUTE_BINARY_BYTES = 256 * 1024 * 1024
MAX_ROUTE_CONTAINER_ITEMS = 20_000_000
MAX_ROUTE_CANONICAL_BYTES = 256 * 1024 * 1024
MAX_JSON_DEPTH = 64
MAX_JSON_STRING_TOKEN_BYTES = 4 * 1024 * 1024
MAX_JSON_NUMBER_TOKEN_BYTES = 20
MAX_TEXT_BYTES = 16 * 1024
MAX_CELL_CANONICAL_BYTES = 8 * 1024 * 1024
MAX_OCCURRENCE_CANONICAL_BYTES = 64 * 1024 * 1024


class TypedFieldValueReceiptError(ValueError):
    """Raised when typed-field evidence is stale, foreign, or incomplete."""


def _canonical_json_bytes(value: object, *, maximum_bytes: int) -> bytes:
    try:
        encoded = json.dumps(
            value,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
            allow_nan=False,
        ).encode("utf-8", errors="strict")
    except (TypeError, ValueError, UnicodeEncodeError) as exc:
        raise TypedFieldValueReceiptError("typed-field value is not canonical JSON") from exc
    if len(encoded) > maximum_bytes:
        raise TypedFieldValueReceiptError("typed-field canonical bytes exceed their bound")
    return encoded


def canonical_json_bytes(value: object) -> bytes:
    return _canonical_json_bytes(value, maximum_bytes=MAX_ROUTE_CANONICAL_BYTES)


def canonical_sha256(value: object) -> str:
    return hashlib.sha256(canonical_json_bytes(value)).hexdigest()


def _sha256(value: object, *, field_name: str) -> str:
    if type(value) is not str or _SHA256_RE.fullmatch(value) is None:
        raise TypedFieldValueReceiptError(f"{field_name} must be a lowercase SHA-256")
    return value


def _text(value: object, *, field_name: str) -> str:
    if type(value) is not str or not value or value.strip() != value:
        raise TypedFieldValueReceiptError(f"{field_name} must be nonempty exact text")
    try:
        size = len(value.encode("utf-8", errors="strict"))
    except UnicodeEncodeError as exc:
        raise TypedFieldValueReceiptError(f"{field_name} must be exact UTF-8") from exc
    if size > MAX_TEXT_BYTES:
        raise TypedFieldValueReceiptError(f"{field_name} exceeds its byte bound")
    return value


def _integer(value: object, *, field_name: str, maximum: int) -> int:
    if type(value) is not int or value < 0 or value > maximum:
        raise TypedFieldValueReceiptError(f"{field_name} must be a bounded exact integer")
    return value


def _optional_integer(value: object, *, field_name: str, maximum: int) -> int | None:
    if value is None:
        return None
    return _integer(value, field_name=field_name, maximum=maximum)


def _optional_text(value: object, *, field_name: str) -> str | None:
    if value is None:
        return None
    return _text(value, field_name=field_name)


def _optional_sha256(value: object, *, field_name: str) -> str | None:
    if value is None:
        return None
    return _sha256(value, field_name=field_name)


def _add(left: int, right: int, *, maximum: int, label: str) -> int:
    try:
        return checked_add(left, right, maximum=maximum, label=label)
    except CanonicalArrowValueError as exc:
        raise TypedFieldValueReceiptError(f"{label} exceeds its bounded contract") from exc


def _product(left: int, right: int, *, maximum: int, label: str) -> int:
    try:
        return checked_product(left, right, maximum=maximum, label=label)
    except CanonicalArrowValueError as exc:
        raise TypedFieldValueReceiptError(f"{label} exceeds its bounded contract") from exc


def _sha_tuple(value: object, *, field_name: str, maximum: int) -> tuple[str, ...]:
    if type(value) is not tuple or len(value) > maximum:
        raise TypedFieldValueReceiptError(f"{field_name} must be a bounded immutable tuple")
    result = value
    for item in result:
        _sha256(item, field_name=field_name)
    return cast("tuple[str, ...]", result)


def _dict(payload: object, *, keys: set[str], label: str) -> dict[str, object]:
    if (
        type(payload) is not dict
        or set(payload) != keys
        or any(type(key) is not str for key in payload)
    ):
        raise TypedFieldValueReceiptError(f"{label} keys differ from the exact V2 schema")
    return cast("dict[str, object]", payload)


def _reject_duplicates(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise TypedFieldValueReceiptError("typed-field JSON contains duplicate keys")
        result[key] = value
    return result


def _reject_constant(value: str) -> object:
    raise TypedFieldValueReceiptError("typed-field JSON contains a non-finite number")


def _prescan_json(encoded: bytes, *, maximum_bytes: int, maximum_items: int) -> None:
    """Bound shape and tokens before the allocating JSON parser runs."""

    if type(encoded) is not bytes or not encoded:
        raise TypedFieldValueReceiptError("typed-field input must be nonempty exact bytes")
    if len(encoded) > maximum_bytes:
        raise TypedFieldValueReceiptError("typed-field input exceeds its byte bound")
    depth = nodes = items = 0
    index = 0
    while index < len(encoded):
        byte = encoded[index]
        if byte in b" \t\r\n,:":
            index += 1
            continue
        if byte in (ord("{"), ord("[")):
            depth += 1
            nodes += 1
            if depth > MAX_JSON_DEPTH:
                raise TypedFieldValueReceiptError("typed-field JSON exceeds its depth bound")
            index += 1
            continue
        if byte in (ord("}"), ord("]")):
            depth -= 1
            if depth < 0:
                raise TypedFieldValueReceiptError("typed-field JSON nesting is malformed")
            index += 1
            continue
        if byte == ord('"'):
            cursor = index + 1
            escaped = False
            token_bytes = 0
            while cursor < len(encoded):
                current = encoded[cursor]
                if not escaped and current == ord('"'):
                    break
                escaped = not escaped and current == ord("\\")
                token_bytes += 1
                if token_bytes > MAX_JSON_STRING_TOKEN_BYTES:
                    raise TypedFieldValueReceiptError(
                        "typed-field JSON string token exceeds its bound"
                    )
                cursor += 1
            if cursor >= len(encoded):
                raise TypedFieldValueReceiptError("typed-field JSON string is unterminated")
            nodes += 1
            items += 1
            index = cursor + 1
        elif byte in b"-0123456789":
            cursor = index + 1
            while cursor < len(encoded) and encoded[cursor] in b"+-.0123456789eE":
                cursor += 1
            if cursor - index > MAX_JSON_NUMBER_TOKEN_BYTES:
                raise TypedFieldValueReceiptError("typed-field JSON number token exceeds its bound")
            nodes += 1
            items += 1
            index = cursor
        elif encoded.startswith(b"true", index):
            nodes += 1
            items += 1
            index += 4
        elif encoded.startswith(b"false", index):
            nodes += 1
            items += 1
            index += 5
        elif encoded.startswith(b"null", index):
            nodes += 1
            items += 1
            index += 4
        else:
            raise TypedFieldValueReceiptError("typed-field JSON contains an invalid token")
        if nodes > MAX_ROUTE_VALUE_NODES + MAX_ROUTE_CELLS * 4 or items > maximum_items:
            raise TypedFieldValueReceiptError("typed-field JSON exceeds pre-allocation bounds")
    if depth:
        raise TypedFieldValueReceiptError("typed-field JSON nesting is malformed")


def _decode_object(
    encoded: bytes,
    *,
    maximum_bytes: int,
    maximum_items: int,
) -> dict[str, object]:
    _prescan_json(encoded, maximum_bytes=maximum_bytes, maximum_items=maximum_items)
    try:
        value = json.loads(
            encoded.decode("utf-8", errors="strict"),
            object_pairs_hook=_reject_duplicates,
            parse_constant=_reject_constant,
        )
    except TypedFieldValueReceiptError:
        raise
    except (
        UnicodeDecodeError,
        json.JSONDecodeError,
        RecursionError,
        MemoryError,
        OverflowError,
    ) as exc:
        raise TypedFieldValueReceiptError("typed-field input cannot be decoded") from exc
    if type(value) is not dict:
        raise TypedFieldValueReceiptError("typed-field input root must be an object")
    result = cast("dict[str, object]", value)
    if encoded != _canonical_json_bytes(result, maximum_bytes=maximum_bytes):
        raise TypedFieldValueReceiptError("typed-field input is not byte-canonical JSON")
    return result


def _require_v2(payload: dict[str, object], *, kind: str) -> None:
    if payload.get("schema_version") != 2 or payload.get("kind") != kind:
        raise TypedFieldValueReceiptError(
            "V1 or foreign typed-field evidence requires a fresh full restart"
        )


def _decoder_kind(source_family: SourceFamily) -> DecoderKind:
    if source_family == "stats":
        return "stats_result_set_rows_v1"
    if source_family == "live":
        return "live_record_projection_v1"
    return "static_dataset_records_v1"


def _arrow_type(payload: object) -> ArrowLogicalTypeV1:
    if (
        type(payload) is not dict
        or payload.get("schema_version") != ArrowLogicalTypeV1.schema_version
        or payload.get("kind") != ArrowLogicalTypeV1.kind
    ):
        raise TypedFieldValueReceiptError("foreign Arrow type codec requires a fresh full restart")
    try:
        return ArrowLogicalTypeV1.from_canonical_bytes(
            _canonical_json_bytes(payload, maximum_bytes=MAX_CELL_CANONICAL_BYTES)
        )
    except CanonicalArrowValueError as exc:
        raise TypedFieldValueReceiptError("field Arrow type is invalid") from exc


def _arrow_value(payload: object, *, budget: ValueBudget | None = None) -> CanonicalArrowValueV1:
    if (
        type(payload) is not dict
        or payload.get("schema_version") != CanonicalArrowValueV1.schema_version
        or payload.get("kind") != CanonicalArrowValueV1.kind
    ):
        raise TypedFieldValueReceiptError("foreign Arrow value codec requires a fresh full restart")
    try:
        return CanonicalArrowValueV1.from_canonical_bytes(
            _canonical_json_bytes(payload, maximum_bytes=MAX_CELL_CANONICAL_BYTES),
            budget=budget,
        )
    except CanonicalArrowValueError as exc:
        raise TypedFieldValueReceiptError("cell Arrow value is invalid") from exc


@dataclass(frozen=True, slots=True)
class LandingFieldAuthorityV2:
    field_fate_structure_sha256: str
    route_id: str
    staging_key: str
    storage_ordinal: int
    storage_column: str
    origin: FieldOrigin
    sink_sha256: str
    route_binding_sha256s: tuple[str, ...]
    source_occurrence_sha256s: tuple[str, ...]
    source_endpoint_ids: tuple[str, ...]
    source_result_set_names: tuple[str, ...]
    source_result_set_ordinals: tuple[int, ...]
    source_header_ordinals: tuple[int, ...]
    source_field_names: tuple[str, ...]
    lossless_binding_sha256s: tuple[str, ...]
    logical_type: ArrowLogicalTypeV1
    logical_type_sha256: str
    authority_sha256: str

    schema_version: ClassVar[int] = 2
    kind: ClassVar[str] = "landing_field_authority_v2"

    def __post_init__(self) -> None:
        for name in (
            "field_fate_structure_sha256",
            "sink_sha256",
            "logical_type_sha256",
            "authority_sha256",
        ):
            _sha256(getattr(self, name), field_name=name)
        _text(self.route_id, field_name="route_id")
        _text(self.staging_key, field_name="staging_key")
        _integer(self.storage_ordinal, field_name="storage_ordinal", maximum=MAX_ROUTE_FIELDS - 1)
        _text(self.storage_column, field_name="storage_column")
        if self.origin not in {
            "provider_bound",
            "provider_multi_bound",
            "lossless_bound",
            "storage_only",
        }:
            raise TypedFieldValueReceiptError("field origin is unsupported")
        bindings = _sha_tuple(
            self.route_binding_sha256s,
            field_name="route_binding_sha256s",
            maximum=MAX_ROUTE_FIELDS,
        )
        sources = _sha_tuple(
            self.source_occurrence_sha256s,
            field_name="source_occurrence_sha256s",
            maximum=MAX_ROUTE_FIELDS,
        )
        lossless = _sha_tuple(
            self.lossless_binding_sha256s,
            field_name="lossless_binding_sha256s",
            maximum=MAX_ROUTE_ROWS,
        )
        if type(self.source_header_ordinals) is not tuple or any(
            type(item) is not int or item < 0 or item >= MAX_ROUTE_FIELDS
            for item in self.source_header_ordinals
        ):
            raise TypedFieldValueReceiptError("source header ordinals are invalid")
        if (
            type(self.source_endpoint_ids) is not tuple
            or type(self.source_result_set_names) is not tuple
            or type(self.source_result_set_ordinals) is not tuple
        ):
            raise TypedFieldValueReceiptError("source selector inventories are mutable")
        for endpoint_id in self.source_endpoint_ids:
            _text(endpoint_id, field_name="source_endpoint_id")
        for result_set_name in self.source_result_set_names:
            _text(result_set_name, field_name="source_result_set_name")
        for result_set_ordinal in self.source_result_set_ordinals:
            _integer(
                result_set_ordinal,
                field_name="source_result_set_ordinal",
                maximum=MAX_ROUTE_OCCURRENCES - 1,
            )
        if type(self.source_field_names) is not tuple:
            raise TypedFieldValueReceiptError("source field names must be immutable")
        for item in self.source_field_names:
            _text(item, field_name="source_field_name")
        if not (
            len(sources)
            == len(self.source_endpoint_ids)
            == len(self.source_result_set_names)
            == len(self.source_result_set_ordinals)
            == len(self.source_header_ordinals)
            == len(self.source_field_names)
        ):
            raise TypedFieldValueReceiptError("field source selector denominator is incomplete")
        if self.origin == "storage_only" and (bindings or sources or lossless):
            raise TypedFieldValueReceiptError("storage-only field invents source authority")
        if self.origin == "provider_bound" and len(bindings) != 1:
            raise TypedFieldValueReceiptError("provider-bound multiplicity is invalid")
        if self.origin == "provider_multi_bound" and len(bindings) < 2:
            raise TypedFieldValueReceiptError("multi-bound multiplicity is invalid")
        if self.origin == "lossless_bound":
            if bindings or not lossless or (sources and len(lossless) != len(sources)):
                raise TypedFieldValueReceiptError("lossless authority is incomplete")
        elif len(bindings) != len(sources):
            raise TypedFieldValueReceiptError("field binding/source denominator is incomplete")
        if type(self.logical_type) is not ArrowLogicalTypeV1:
            raise TypedFieldValueReceiptError("field Arrow type has a foreign type")
        if self.logical_type_sha256 != self.logical_type.type_sha256:
            raise TypedFieldValueReceiptError("field Arrow type digest is invalid")
        if self.authority_sha256 != canonical_sha256(self.identity_payload()):
            raise TypedFieldValueReceiptError("field authority digest is invalid")

    def identity_payload(self) -> dict[str, object]:
        return {
            "schema_version": 2,
            "kind": self.kind,
            "field_fate_structure_sha256": self.field_fate_structure_sha256,
            "route_id": self.route_id,
            "staging_key": self.staging_key,
            "storage_ordinal": self.storage_ordinal,
            "storage_column": self.storage_column,
            "origin": self.origin,
            "sink_sha256": self.sink_sha256,
            "route_binding_sha256s": list(self.route_binding_sha256s),
            "source_occurrence_sha256s": list(self.source_occurrence_sha256s),
            "source_endpoint_ids": list(self.source_endpoint_ids),
            "source_result_set_names": list(self.source_result_set_names),
            "source_result_set_ordinals": list(self.source_result_set_ordinals),
            "source_header_ordinals": list(self.source_header_ordinals),
            "source_field_names": list(self.source_field_names),
            "lossless_binding_sha256s": list(self.lossless_binding_sha256s),
            "logical_type": self.logical_type.to_dict(),
            "logical_type_sha256": self.logical_type_sha256,
        }

    def to_dict(self) -> dict[str, object]:
        return self.identity_payload() | {"authority_sha256": self.authority_sha256}

    def to_canonical_bytes(self) -> bytes:
        return _canonical_json_bytes(self.to_dict(), maximum_bytes=MAX_CELL_CANONICAL_BYTES)

    @classmethod
    def from_canonical_bytes(cls, encoded: bytes) -> Self:
        return cls._from_payload(
            _decode_object(
                encoded,
                maximum_bytes=MAX_CELL_CANONICAL_BYTES,
                maximum_items=MAX_ROUTE_FIELDS * 16,
            )
        )

    @classmethod
    def _from_payload(cls, payload: object) -> Self:
        keys = {
            "schema_version",
            "kind",
            "field_fate_structure_sha256",
            "route_id",
            "staging_key",
            "storage_ordinal",
            "storage_column",
            "origin",
            "sink_sha256",
            "route_binding_sha256s",
            "source_occurrence_sha256s",
            "source_endpoint_ids",
            "source_result_set_names",
            "source_result_set_ordinals",
            "source_header_ordinals",
            "source_field_names",
            "lossless_binding_sha256s",
            "logical_type",
            "logical_type_sha256",
            "authority_sha256",
        }
        item = _dict(payload, keys=keys, label="field authority")
        _require_v2(item, kind=cls.kind)
        inventories = (
            "route_binding_sha256s",
            "source_occurrence_sha256s",
            "source_endpoint_ids",
            "source_result_set_names",
            "source_result_set_ordinals",
            "source_header_ordinals",
            "source_field_names",
            "lossless_binding_sha256s",
        )
        if any(type(item[name]) is not list for name in inventories):
            raise TypedFieldValueReceiptError("field authority inventories must be lists")
        return cls(
            field_fate_structure_sha256=cast("str", item["field_fate_structure_sha256"]),
            route_id=cast("str", item["route_id"]),
            staging_key=cast("str", item["staging_key"]),
            storage_ordinal=cast("int", item["storage_ordinal"]),
            storage_column=cast("str", item["storage_column"]),
            origin=cast("FieldOrigin", item["origin"]),
            sink_sha256=cast("str", item["sink_sha256"]),
            route_binding_sha256s=tuple(cast("list[str]", item["route_binding_sha256s"])),
            source_occurrence_sha256s=tuple(cast("list[str]", item["source_occurrence_sha256s"])),
            source_endpoint_ids=tuple(cast("list[str]", item["source_endpoint_ids"])),
            source_result_set_names=tuple(cast("list[str]", item["source_result_set_names"])),
            source_result_set_ordinals=tuple(cast("list[int]", item["source_result_set_ordinals"])),
            source_header_ordinals=tuple(cast("list[int]", item["source_header_ordinals"])),
            source_field_names=tuple(cast("list[str]", item["source_field_names"])),
            lossless_binding_sha256s=tuple(cast("list[str]", item["lossless_binding_sha256s"])),
            logical_type=_arrow_type(item["logical_type"]),
            logical_type_sha256=cast("str", item["logical_type_sha256"]),
            authority_sha256=cast("str", item["authority_sha256"]),
        )


@dataclass(frozen=True, slots=True)
class SourceOccurrenceAuthorityV2:
    """Inspectable exact raw occurrence summary selected as route source authority."""

    raw_bundle_sha256: str
    observation_sha256: str
    occurrence_sha256: str
    source_family: SourceFamily
    endpoint_id: str
    occurrence_ordinal: int
    result_name: str
    duplicate_name_ordinal: int
    provider_result_ordinal: int | None
    canonical_result_ordinal: int | None
    json_path: str | None
    container_kind: str
    presence: SourceOccurrencePresence
    ordered_headers: tuple[str, ...]
    ordered_headers_sha256: str
    header_count: int
    row_count: int
    cell_count: int
    node_count: int
    container_count: int
    missing_count: int
    null_count: int
    parent_state_sha256: str | None
    output_sha256: str
    canonical_route_ids: tuple[str, ...]
    canonical_route_ids_sha256: str
    committed_staging_receipts: tuple[tuple[str, str], ...]
    committed_staging_receipts_sha256: str
    landing_disposition: str
    logical_result_receipt_sha256: str
    route_receipt_sha256: str
    authority_sha256: str

    schema_version: ClassVar[int] = 2
    kind: ClassVar[str] = "source_occurrence_authority_v2"

    def __post_init__(self) -> None:
        for name in (
            "raw_bundle_sha256",
            "observation_sha256",
            "occurrence_sha256",
            "ordered_headers_sha256",
            "canonical_route_ids_sha256",
            "committed_staging_receipts_sha256",
            "logical_result_receipt_sha256",
            "route_receipt_sha256",
            "output_sha256",
            "authority_sha256",
        ):
            _sha256(getattr(self, name), field_name=name)
        if self.source_family not in _DECODER_BY_SOURCE:
            raise TypedFieldValueReceiptError("source occurrence family is unsupported")
        _text(self.endpoint_id, field_name="endpoint_id")
        _integer(
            self.occurrence_ordinal,
            field_name="occurrence_ordinal",
            maximum=MAX_ROUTE_OCCURRENCES - 1,
        )
        _text(self.result_name, field_name="result_name")
        _integer(
            self.duplicate_name_ordinal,
            field_name="duplicate_name_ordinal",
            maximum=MAX_ROUTE_OCCURRENCES - 1,
        )
        for name in ("provider_result_ordinal", "canonical_result_ordinal"):
            _optional_integer(
                getattr(self, name),
                field_name=name,
                maximum=MAX_ROUTE_OCCURRENCES - 1,
            )
        _optional_text(self.json_path, field_name="json_path")
        if self.container_kind not in _SOURCE_CONTAINER_KINDS:
            raise TypedFieldValueReceiptError("source occurrence container kind is invalid")
        if self.presence not in _SOURCE_OCCURRENCE_PRESENCES:
            raise TypedFieldValueReceiptError("source occurrence presence is invalid")
        if type(self.ordered_headers) is not tuple or len(self.ordered_headers) > MAX_ROUTE_FIELDS:
            raise TypedFieldValueReceiptError("source occurrence headers are invalid")
        for header in self.ordered_headers:
            _text(header, field_name="ordered_header")
        expected_headers_sha256 = hashlib.sha256(
            _canonical_json_bytes(
                list(self.ordered_headers), maximum_bytes=MAX_CELL_CANONICAL_BYTES
            )
        ).hexdigest()
        if self.ordered_headers_sha256 != expected_headers_sha256:
            raise TypedFieldValueReceiptError("source occurrence header digest is invalid")
        for name, maximum in (
            ("header_count", MAX_ROUTE_FIELDS),
            ("row_count", MAX_ROUTE_ROWS),
            ("cell_count", MAX_ROUTE_CELLS),
            ("node_count", MAX_ROUTE_VALUE_NODES),
            ("container_count", MAX_ROUTE_VALUE_NODES),
            ("missing_count", MAX_ROUTE_VALUE_NODES),
            ("null_count", MAX_ROUTE_VALUE_NODES),
        ):
            _integer(getattr(self, name), field_name=name, maximum=maximum)
        if self.header_count != len(self.ordered_headers):
            raise TypedFieldValueReceiptError("source occurrence header count is invalid")
        _optional_sha256(self.parent_state_sha256, field_name="parent_state_sha256")
        if self.container_kind == "nba_api_result_set":
            if self.json_path is not None or self.cell_count != self.header_count * self.row_count:
                raise TypedFieldValueReceiptError("stats source occurrence algebra is invalid")
        elif self.json_path is None:
            raise TypedFieldValueReceiptError("non-stats source occurrence omitted its JSON path")
        if (
            self.presence not in {"missing", "mixed_absent", "not_observed_parent_empty"}
            and self.container_count < 1
        ):
            raise TypedFieldValueReceiptError("source occurrence omitted its root container")
        if self.presence == "not_observed_parent_empty":
            if (
                self.container_kind not in {"nba_api_live_json_array", "nba_api_live_json_object"}
                or self.parent_state_sha256 is None
                or any(
                    value != 0
                    for value in (
                        self.row_count,
                        self.cell_count,
                        self.node_count,
                        self.container_count,
                        self.missing_count,
                        self.null_count,
                    )
                )
            ):
                raise TypedFieldValueReceiptError("parent-empty source occurrence is invalid")
        elif self.presence == "missing":
            if (
                self.container_count != 0
                or self.missing_count < 1
                or any(
                    value != 0
                    for value in (
                        self.header_count,
                        self.row_count,
                        self.cell_count,
                        self.node_count,
                        self.null_count,
                    )
                )
            ):
                raise TypedFieldValueReceiptError("missing source occurrence is invalid")
        elif self.presence == "null":
            if self.null_count < 1 or any(
                value != 0
                for value in (
                    self.header_count,
                    self.row_count,
                    self.cell_count,
                    self.missing_count,
                )
            ):
                raise TypedFieldValueReceiptError("null source occurrence is invalid")
        elif self.presence == "mixed_absent":
            if (
                self.container_kind not in {"nba_api_live_json_array", "nba_api_live_json_object"}
                or self.container_count != self.null_count
                or self.missing_count < 1
                or self.null_count < 1
                or self.node_count != self.null_count
                or any(
                    value != 0
                    for value in (
                        self.header_count,
                        self.row_count,
                        self.cell_count,
                    )
                )
            ):
                raise TypedFieldValueReceiptError("mixed-absent source occurrence is invalid")
        elif self.presence == "present_empty":
            if any(
                value != 0
                for value in (
                    self.row_count,
                    self.cell_count,
                    self.node_count,
                    self.missing_count,
                    self.null_count,
                )
            ):
                raise TypedFieldValueReceiptError("present-empty source occurrence is invalid")
        elif self.presence == "empty_object":
            if (
                self.container_kind != "nba_api_live_json_object"
                or self.node_count != 1
                or any(
                    value != 0
                    for value in (
                        self.header_count,
                        self.row_count,
                        self.cell_count,
                        self.missing_count,
                        self.null_count,
                    )
                )
            ):
                raise TypedFieldValueReceiptError("empty-object source occurrence is invalid")
        elif self.presence == "empty_array":
            if (
                self.container_kind not in {"nba_api_static_records", "nba_api_live_json_array"}
                or self.node_count != 1
                or any(
                    value != 0
                    for value in (
                        self.header_count,
                        self.row_count,
                        self.cell_count,
                        self.missing_count,
                        self.null_count,
                    )
                )
            ):
                raise TypedFieldValueReceiptError("empty-array source occurrence is invalid")
        elif self.row_count == 0 and self.node_count == 0:
            raise TypedFieldValueReceiptError("present source occurrence lacks rows or nodes")
        if (
            type(self.canonical_route_ids) is not tuple
            or not self.canonical_route_ids
            or len(self.canonical_route_ids) != len(set(self.canonical_route_ids))
        ):
            raise TypedFieldValueReceiptError("source occurrence route inventory is invalid")
        for route_id in self.canonical_route_ids:
            _text(route_id, field_name="canonical_route_id")
        if (
            self.canonical_route_ids_sha256
            != hashlib.sha256(
                _canonical_json_bytes(
                    list(self.canonical_route_ids), maximum_bytes=MAX_CELL_CANONICAL_BYTES
                )
            ).hexdigest()
        ):
            raise TypedFieldValueReceiptError("source occurrence route digest is invalid")
        if type(self.committed_staging_receipts) is not tuple:
            raise TypedFieldValueReceiptError("source occurrence receipt inventory is mutable")
        receipt_routes: list[str] = []
        for receipt in self.committed_staging_receipts:
            if type(receipt) is not tuple or len(receipt) != 2:
                raise TypedFieldValueReceiptError("source occurrence receipt is invalid")
            route_id, receipt_sha256 = receipt
            _text(route_id, field_name="receipt_route_id")
            _sha256(receipt_sha256, field_name="receipt_sha256")
            if route_id not in self.canonical_route_ids:
                raise TypedFieldValueReceiptError("source occurrence receipt route is foreign")
            receipt_routes.append(route_id)
        if len(receipt_routes) != len(set(receipt_routes)):
            raise TypedFieldValueReceiptError("source occurrence receipt routes are duplicated")
        receipt_payload = [
            {"receipt_sha256": receipt_sha256, "route_id": route_id}
            for route_id, receipt_sha256 in self.committed_staging_receipts
        ]
        if (
            self.committed_staging_receipts_sha256
            != hashlib.sha256(
                _canonical_json_bytes(receipt_payload, maximum_bytes=MAX_CELL_CANONICAL_BYTES)
            ).hexdigest()
        ):
            raise TypedFieldValueReceiptError("source occurrence receipt digest is invalid")
        if self.landing_disposition not in _LANDING_DISPOSITIONS:
            raise TypedFieldValueReceiptError("source occurrence landing disposition is invalid")
        try:
            rebuilt = ResultOccurrenceV2.build(
                observation_sha256=self.observation_sha256,
                occurrence_ordinal=self.occurrence_ordinal,
                result_name=self.result_name,
                duplicate_name_ordinal=self.duplicate_name_ordinal,
                provider_result_ordinal=self.provider_result_ordinal,
                canonical_result_ordinal=self.canonical_result_ordinal,
                json_path=self.json_path,
                container_kind=cast("ResultContainerKind", self.container_kind),
                presence=self.presence,
                ordered_headers=self.ordered_headers,
                row_count=self.row_count,
                cell_count=self.cell_count,
                node_count=self.node_count,
                container_count=self.container_count,
                missing_count=self.missing_count,
                null_count=self.null_count,
                parent_state_sha256=self.parent_state_sha256,
                output_sha256=self.output_sha256,
                canonical_route_ids=self.canonical_route_ids,
                committed_staging_receipts=receipt_payload,
                landing_disposition=cast("LandingDisposition", self.landing_disposition),
            )
        except (RawRequestAuthorityError, ValueError) as exc:
            raise TypedFieldValueReceiptError(
                "source occurrence cannot reconstruct the raw occurrence identity"
            ) from exc
        if (
            rebuilt.ordered_headers_sha256 != self.ordered_headers_sha256
            or rebuilt.canonical_route_ids_sha256 != self.canonical_route_ids_sha256
            or rebuilt.committed_staging_receipts_sha256 != self.committed_staging_receipts_sha256
            or rebuilt.logical_result_receipt_sha256 != self.logical_result_receipt_sha256
            or rebuilt.route_receipt_sha256 != self.route_receipt_sha256
            or rebuilt.occurrence_sha256 != self.occurrence_sha256
        ):
            raise TypedFieldValueReceiptError(
                "source occurrence identity differs from its inspectable payload"
            )
        if self.authority_sha256 != canonical_sha256(self.identity_payload()):
            raise TypedFieldValueReceiptError("source occurrence authority digest is invalid")

    def identity_payload(self) -> dict[str, object]:
        return {
            "schema_version": 2,
            "kind": self.kind,
            "raw_bundle_sha256": self.raw_bundle_sha256,
            "observation_sha256": self.observation_sha256,
            "occurrence_sha256": self.occurrence_sha256,
            "source_family": self.source_family,
            "endpoint_id": self.endpoint_id,
            "occurrence_ordinal": self.occurrence_ordinal,
            "result_name": self.result_name,
            "duplicate_name_ordinal": self.duplicate_name_ordinal,
            "provider_result_ordinal": self.provider_result_ordinal,
            "canonical_result_ordinal": self.canonical_result_ordinal,
            "json_path": self.json_path,
            "container_kind": self.container_kind,
            "presence": self.presence,
            "ordered_headers": list(self.ordered_headers),
            "ordered_headers_sha256": self.ordered_headers_sha256,
            "header_count": self.header_count,
            "row_count": self.row_count,
            "cell_count": self.cell_count,
            "node_count": self.node_count,
            "container_count": self.container_count,
            "missing_count": self.missing_count,
            "null_count": self.null_count,
            "parent_state_sha256": self.parent_state_sha256,
            "output_sha256": self.output_sha256,
            "canonical_route_ids": list(self.canonical_route_ids),
            "canonical_route_ids_sha256": self.canonical_route_ids_sha256,
            "committed_staging_receipts": [
                {"receipt_sha256": receipt_sha256, "route_id": route_id}
                for route_id, receipt_sha256 in self.committed_staging_receipts
            ],
            "committed_staging_receipts_sha256": self.committed_staging_receipts_sha256,
            "landing_disposition": self.landing_disposition,
            "logical_result_receipt_sha256": self.logical_result_receipt_sha256,
            "route_receipt_sha256": self.route_receipt_sha256,
        }

    def to_dict(self) -> dict[str, object]:
        return self.identity_payload() | {"authority_sha256": self.authority_sha256}

    @classmethod
    def _from_payload(cls, payload: object) -> Self:
        keys = {
            "schema_version",
            "kind",
            "raw_bundle_sha256",
            "observation_sha256",
            "occurrence_sha256",
            "source_family",
            "endpoint_id",
            "occurrence_ordinal",
            "result_name",
            "duplicate_name_ordinal",
            "provider_result_ordinal",
            "canonical_result_ordinal",
            "json_path",
            "container_kind",
            "presence",
            "ordered_headers",
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
            "canonical_route_ids",
            "canonical_route_ids_sha256",
            "committed_staging_receipts",
            "committed_staging_receipts_sha256",
            "landing_disposition",
            "logical_result_receipt_sha256",
            "route_receipt_sha256",
            "authority_sha256",
        }
        item = _dict(payload, keys=keys, label="source occurrence authority")
        _require_v2(item, kind=cls.kind)
        for name in (
            "ordered_headers",
            "canonical_route_ids",
            "committed_staging_receipts",
        ):
            if type(item[name]) is not list:
                raise TypedFieldValueReceiptError(
                    "source occurrence inventories must be exact lists"
                )
        receipt_pairs: list[tuple[str, str]] = []
        for receipt in cast("list[object]", item["committed_staging_receipts"]):
            value = _dict(
                receipt,
                keys={"receipt_sha256", "route_id"},
                label="source occurrence staging receipt",
            )
            receipt_pairs.append(
                (cast("str", value["route_id"]), cast("str", value["receipt_sha256"]))
            )
        return cls(
            raw_bundle_sha256=cast("str", item["raw_bundle_sha256"]),
            observation_sha256=cast("str", item["observation_sha256"]),
            occurrence_sha256=cast("str", item["occurrence_sha256"]),
            source_family=cast("SourceFamily", item["source_family"]),
            endpoint_id=cast("str", item["endpoint_id"]),
            occurrence_ordinal=cast("int", item["occurrence_ordinal"]),
            result_name=cast("str", item["result_name"]),
            duplicate_name_ordinal=cast("int", item["duplicate_name_ordinal"]),
            provider_result_ordinal=cast("int | None", item["provider_result_ordinal"]),
            canonical_result_ordinal=cast("int | None", item["canonical_result_ordinal"]),
            json_path=cast("str | None", item["json_path"]),
            container_kind=cast("str", item["container_kind"]),
            presence=cast("SourceOccurrencePresence", item["presence"]),
            ordered_headers=tuple(cast("list[str]", item["ordered_headers"])),
            ordered_headers_sha256=cast("str", item["ordered_headers_sha256"]),
            header_count=cast("int", item["header_count"]),
            row_count=cast("int", item["row_count"]),
            cell_count=cast("int", item["cell_count"]),
            node_count=cast("int", item["node_count"]),
            container_count=cast("int", item["container_count"]),
            missing_count=cast("int", item["missing_count"]),
            null_count=cast("int", item["null_count"]),
            parent_state_sha256=cast("str | None", item["parent_state_sha256"]),
            output_sha256=cast("str", item["output_sha256"]),
            canonical_route_ids=tuple(cast("list[str]", item["canonical_route_ids"])),
            canonical_route_ids_sha256=cast("str", item["canonical_route_ids_sha256"]),
            committed_staging_receipts=tuple(receipt_pairs),
            committed_staging_receipts_sha256=cast(
                "str", item["committed_staging_receipts_sha256"]
            ),
            landing_disposition=cast("str", item["landing_disposition"]),
            logical_result_receipt_sha256=cast("str", item["logical_result_receipt_sha256"]),
            route_receipt_sha256=cast("str", item["route_receipt_sha256"]),
            authority_sha256=cast("str", item["authority_sha256"]),
        )


@dataclass(frozen=True, slots=True)
class OccurrenceLandingAuthorityV2:
    raw_bundle_sha256: str
    observation_sha256: str
    occurrence_sha256: str
    source_occurrence_authority_sha256: str
    source_family: SourceFamily
    decoder_kind: DecoderKind
    endpoint_id: str
    occurrence_order_ordinal: int
    result_name: str
    provider_result_ordinal: int | None
    duplicate_name_ordinal: int
    ordered_headers: tuple[str, ...]
    ordered_headers_sha256: str
    row_slice_receipt_sha256: str
    start_row_ordinal: int
    row_count: int
    authority_sha256: str

    schema_version: ClassVar[int] = 2
    kind: ClassVar[str] = "occurrence_landing_authority_v2"

    def __post_init__(self) -> None:
        for name in (
            "raw_bundle_sha256",
            "observation_sha256",
            "occurrence_sha256",
            "source_occurrence_authority_sha256",
            "ordered_headers_sha256",
            "row_slice_receipt_sha256",
            "authority_sha256",
        ):
            _sha256(getattr(self, name), field_name=name)
        if self.source_family not in _DECODER_BY_SOURCE or (
            self.decoder_kind != _DECODER_BY_SOURCE[self.source_family]
        ):
            raise TypedFieldValueReceiptError("occurrence decoder relabels its source family")
        _text(self.endpoint_id, field_name="endpoint_id")
        _integer(
            self.occurrence_order_ordinal,
            field_name="occurrence_order_ordinal",
            maximum=MAX_ROUTE_OCCURRENCES - 1,
        )
        _text(self.result_name, field_name="result_name")
        if self.provider_result_ordinal is not None:
            _integer(
                self.provider_result_ordinal,
                field_name="provider_result_ordinal",
                maximum=MAX_ROUTE_OCCURRENCES - 1,
            )
        _integer(
            self.duplicate_name_ordinal,
            field_name="duplicate_name_ordinal",
            maximum=MAX_ROUTE_OCCURRENCES - 1,
        )
        if type(self.ordered_headers) is not tuple or len(self.ordered_headers) > MAX_ROUTE_FIELDS:
            raise TypedFieldValueReceiptError("ordered header denominator is invalid")
        for header in self.ordered_headers:
            _text(header, field_name="ordered_header")
        expected_headers_sha = hashlib.sha256(
            _canonical_json_bytes(
                list(self.ordered_headers), maximum_bytes=MAX_CELL_CANONICAL_BYTES
            )
        ).hexdigest()
        if self.ordered_headers_sha256 != expected_headers_sha:
            raise TypedFieldValueReceiptError("ordered header digest is invalid")
        _integer(self.start_row_ordinal, field_name="start_row_ordinal", maximum=MAX_ROUTE_ROWS)
        _integer(self.row_count, field_name="row_count", maximum=MAX_ROUTE_ROWS)
        if self.authority_sha256 != canonical_sha256(self.identity_payload()):
            raise TypedFieldValueReceiptError("occurrence authority digest is invalid")

    def identity_payload(self) -> dict[str, object]:
        return {
            "schema_version": 2,
            "kind": self.kind,
            "raw_bundle_sha256": self.raw_bundle_sha256,
            "observation_sha256": self.observation_sha256,
            "occurrence_sha256": self.occurrence_sha256,
            "source_occurrence_authority_sha256": self.source_occurrence_authority_sha256,
            "source_family": self.source_family,
            "decoder_kind": self.decoder_kind,
            "endpoint_id": self.endpoint_id,
            "occurrence_order_ordinal": self.occurrence_order_ordinal,
            "result_name": self.result_name,
            "provider_result_ordinal": self.provider_result_ordinal,
            "duplicate_name_ordinal": self.duplicate_name_ordinal,
            "ordered_headers": list(self.ordered_headers),
            "ordered_headers_sha256": self.ordered_headers_sha256,
            "row_slice_receipt_sha256": self.row_slice_receipt_sha256,
            "start_row_ordinal": self.start_row_ordinal,
            "row_count": self.row_count,
        }

    def to_dict(self) -> dict[str, object]:
        return self.identity_payload() | {"authority_sha256": self.authority_sha256}

    def to_canonical_bytes(self) -> bytes:
        return _canonical_json_bytes(self.to_dict(), maximum_bytes=MAX_CELL_CANONICAL_BYTES)

    @classmethod
    def from_canonical_bytes(cls, encoded: bytes) -> Self:
        return cls._from_payload(
            _decode_object(
                encoded,
                maximum_bytes=MAX_CELL_CANONICAL_BYTES,
                maximum_items=MAX_ROUTE_FIELDS * 8,
            )
        )

    @classmethod
    def _from_payload(cls, payload: object) -> Self:
        keys = {
            "schema_version",
            "kind",
            "raw_bundle_sha256",
            "observation_sha256",
            "occurrence_sha256",
            "source_occurrence_authority_sha256",
            "source_family",
            "decoder_kind",
            "endpoint_id",
            "occurrence_order_ordinal",
            "result_name",
            "provider_result_ordinal",
            "duplicate_name_ordinal",
            "ordered_headers",
            "ordered_headers_sha256",
            "row_slice_receipt_sha256",
            "start_row_ordinal",
            "row_count",
            "authority_sha256",
        }
        item = _dict(payload, keys=keys, label="occurrence authority")
        _require_v2(item, kind=cls.kind)
        if type(item["ordered_headers"]) is not list:
            raise TypedFieldValueReceiptError("ordered headers must be a list")
        return cls(
            raw_bundle_sha256=cast("str", item["raw_bundle_sha256"]),
            observation_sha256=cast("str", item["observation_sha256"]),
            occurrence_sha256=cast("str", item["occurrence_sha256"]),
            source_occurrence_authority_sha256=cast(
                "str", item["source_occurrence_authority_sha256"]
            ),
            source_family=cast("SourceFamily", item["source_family"]),
            decoder_kind=cast("DecoderKind", item["decoder_kind"]),
            endpoint_id=cast("str", item["endpoint_id"]),
            occurrence_order_ordinal=cast("int", item["occurrence_order_ordinal"]),
            result_name=cast("str", item["result_name"]),
            provider_result_ordinal=cast("int | None", item["provider_result_ordinal"]),
            duplicate_name_ordinal=cast("int", item["duplicate_name_ordinal"]),
            ordered_headers=tuple(cast("list[str]", item["ordered_headers"])),
            ordered_headers_sha256=cast("str", item["ordered_headers_sha256"]),
            row_slice_receipt_sha256=cast("str", item["row_slice_receipt_sha256"]),
            start_row_ordinal=cast("int", item["start_row_ordinal"]),
            row_count=cast("int", item["row_count"]),
            authority_sha256=cast("str", item["authority_sha256"]),
        )


@dataclass(frozen=True, slots=True)
class TypedFieldCellV2:
    occurrence_authority_sha256: str
    field_authority_sha256: str
    source_occurrence_sha256s: tuple[str, ...]
    occurrence_order_ordinal: int
    row_ordinal: int
    absolute_row_ordinal: int
    storage_ordinal: int
    storage_column: str
    logical_type_sha256: str
    value_authority: ValueAuthorityKind
    canonical_value: CanonicalArrowValueV1
    cell_receipt_sha256: str

    schema_version: ClassVar[int] = 2
    kind: ClassVar[str] = "typed_field_cell_v2"

    def __post_init__(self) -> None:
        for name in (
            "occurrence_authority_sha256",
            "field_authority_sha256",
            "logical_type_sha256",
            "cell_receipt_sha256",
        ):
            _sha256(getattr(self, name), field_name=name)
        _sha_tuple(
            self.source_occurrence_sha256s,
            field_name="source_occurrence_sha256s",
            maximum=MAX_ROUTE_FIELDS,
        )
        _integer(
            self.occurrence_order_ordinal,
            field_name="occurrence_order_ordinal",
            maximum=MAX_ROUTE_OCCURRENCES - 1,
        )
        _integer(self.row_ordinal, field_name="row_ordinal", maximum=MAX_ROUTE_ROWS - 1)
        _integer(
            self.absolute_row_ordinal,
            field_name="absolute_row_ordinal",
            maximum=MAX_ROUTE_ROWS - 1,
        )
        _integer(self.storage_ordinal, field_name="storage_ordinal", maximum=MAX_ROUTE_FIELDS - 1)
        _text(self.storage_column, field_name="storage_column")
        if self.value_authority not in {"source_verified", "storage_readback_only"}:
            raise TypedFieldValueReceiptError("cell value authority is invalid")
        if type(self.canonical_value) is not CanonicalArrowValueV1:
            raise TypedFieldValueReceiptError("cell value has a foreign concrete type")
        if self.logical_type_sha256 != self.canonical_value.logical_type_sha256:
            raise TypedFieldValueReceiptError("cell logical type digest is invalid")
        if self.cell_receipt_sha256 != canonical_sha256(self.identity_payload()):
            raise TypedFieldValueReceiptError("cell receipt digest is invalid")

    def identity_payload(self) -> dict[str, object]:
        return {
            "schema_version": 2,
            "kind": self.kind,
            "occurrence_authority_sha256": self.occurrence_authority_sha256,
            "field_authority_sha256": self.field_authority_sha256,
            "source_occurrence_sha256s": list(self.source_occurrence_sha256s),
            "occurrence_order_ordinal": self.occurrence_order_ordinal,
            "row_ordinal": self.row_ordinal,
            "absolute_row_ordinal": self.absolute_row_ordinal,
            "storage_ordinal": self.storage_ordinal,
            "storage_column": self.storage_column,
            "logical_type_sha256": self.logical_type_sha256,
            "value_authority": self.value_authority,
            "canonical_value": self.canonical_value.to_dict(),
        }

    def to_dict(self) -> dict[str, object]:
        return self.identity_payload() | {"cell_receipt_sha256": self.cell_receipt_sha256}

    def to_canonical_bytes(self) -> bytes:
        return _canonical_json_bytes(self.to_dict(), maximum_bytes=MAX_CELL_CANONICAL_BYTES)

    @classmethod
    def from_canonical_bytes(cls, encoded: bytes) -> Self:
        return cls._from_payload(
            _decode_object(
                encoded,
                maximum_bytes=MAX_CELL_CANONICAL_BYTES,
                maximum_items=MAX_ROUTE_VALUE_NODES,
            )
        )

    @classmethod
    def _from_payload(cls, payload: object, *, budget: ValueBudget | None = None) -> Self:
        keys = {
            "schema_version",
            "kind",
            "occurrence_authority_sha256",
            "field_authority_sha256",
            "source_occurrence_sha256s",
            "occurrence_order_ordinal",
            "row_ordinal",
            "absolute_row_ordinal",
            "storage_ordinal",
            "storage_column",
            "logical_type_sha256",
            "value_authority",
            "canonical_value",
            "cell_receipt_sha256",
        }
        item = _dict(payload, keys=keys, label="typed field cell")
        _require_v2(item, kind=cls.kind)
        if type(item["source_occurrence_sha256s"]) is not list:
            raise TypedFieldValueReceiptError("cell source inventory must be a list")
        return cls(
            occurrence_authority_sha256=cast("str", item["occurrence_authority_sha256"]),
            field_authority_sha256=cast("str", item["field_authority_sha256"]),
            source_occurrence_sha256s=tuple(cast("list[str]", item["source_occurrence_sha256s"])),
            occurrence_order_ordinal=cast("int", item["occurrence_order_ordinal"]),
            row_ordinal=cast("int", item["row_ordinal"]),
            absolute_row_ordinal=cast("int", item["absolute_row_ordinal"]),
            storage_ordinal=cast("int", item["storage_ordinal"]),
            storage_column=cast("str", item["storage_column"]),
            logical_type_sha256=cast("str", item["logical_type_sha256"]),
            value_authority=cast("ValueAuthorityKind", item["value_authority"]),
            canonical_value=_arrow_value(item["canonical_value"], budget=budget),
            cell_receipt_sha256=cast("str", item["cell_receipt_sha256"]),
        )


def _value_totals(cells: tuple[TypedFieldCellV2, ...]) -> tuple[int, int, int, int, int, int]:
    nodes = utf8 = binary = items = canonical = 0
    depth = 0
    for cell in cells:
        value = cell.canonical_value
        nodes = _add(
            nodes, value.node_count, maximum=MAX_ROUTE_VALUE_NODES, label="route value nodes"
        )
        utf8 = _add(
            utf8, value.utf8_bytes, maximum=MAX_ROUTE_VALUE_BYTES, label="route UTF-8 bytes"
        )
        binary = _add(
            binary,
            value.binary_bytes,
            maximum=MAX_ROUTE_BINARY_BYTES,
            label="route binary bytes",
        )
        items = _add(
            items,
            value.container_items,
            maximum=MAX_ROUTE_CONTAINER_ITEMS,
            label="route container items",
        )
        canonical = _add(
            canonical,
            len(value.to_canonical_bytes()),
            maximum=MAX_ROUTE_VALUE_BYTES,
            label="route value canonical bytes",
        )
        depth = max(depth, value.max_depth)
    return nodes, depth, utf8, binary, items, canonical


@dataclass(frozen=True, slots=True)
class TypedFieldValueReceiptV2:
    occurrence_authority: OccurrenceLandingAuthorityV2
    field_authority_sha256s: tuple[str, ...]
    row_count: int
    field_count: int
    cell_count: int
    cells: tuple[TypedFieldCellV2, ...]
    value_node_count: int
    value_max_depth: int
    value_utf8_bytes: int
    value_binary_bytes: int
    value_container_items: int
    value_canonical_bytes: int
    cells_sha256: str
    value_receipt_sha256: str

    schema_version: ClassVar[int] = 2
    kind: ClassVar[str] = "typed_field_value_receipt_v2"

    def __post_init__(self) -> None:
        if type(self.occurrence_authority) is not OccurrenceLandingAuthorityV2:
            raise TypedFieldValueReceiptError("value occurrence authority is foreign")
        fields = _sha_tuple(
            self.field_authority_sha256s,
            field_name="field_authority_sha256s",
            maximum=MAX_ROUTE_FIELDS,
        )
        _integer(self.row_count, field_name="row_count", maximum=MAX_ROUTE_ROWS)
        _integer(self.field_count, field_name="field_count", maximum=MAX_ROUTE_FIELDS)
        _integer(self.cell_count, field_name="cell_count", maximum=MAX_ROUTE_CELLS)
        _integer(
            self.value_node_count,
            field_name="value_node_count",
            maximum=MAX_ROUTE_VALUE_NODES,
        )
        _integer(
            self.value_max_depth,
            field_name="value_max_depth",
            maximum=MAX_JSON_DEPTH,
        )
        _integer(
            self.value_utf8_bytes,
            field_name="value_utf8_bytes",
            maximum=MAX_ROUTE_VALUE_BYTES,
        )
        _integer(
            self.value_binary_bytes,
            field_name="value_binary_bytes",
            maximum=MAX_ROUTE_BINARY_BYTES,
        )
        _integer(
            self.value_container_items,
            field_name="value_container_items",
            maximum=MAX_ROUTE_CONTAINER_ITEMS,
        )
        _integer(
            self.value_canonical_bytes,
            field_name="value_canonical_bytes",
            maximum=MAX_ROUTE_CANONICAL_BYTES,
        )
        expected = _product(
            self.row_count,
            self.field_count,
            maximum=MAX_ROUTE_CELLS,
            label="occurrence cell denominator",
        )
        if self.cell_count != expected or len(fields) != self.field_count:
            raise TypedFieldValueReceiptError("value cell denominator is invalid")
        if (
            type(self.cells) is not tuple
            or len(self.cells) != expected
            or any(type(item) is not TypedFieldCellV2 for item in self.cells)
        ):
            raise TypedFieldValueReceiptError("value cell inventory is incomplete")
        for index, cell in enumerate(self.cells):
            row, field = divmod(index, self.field_count)
            if (
                cell.occurrence_authority_sha256 != self.occurrence_authority.authority_sha256
                or cell.occurrence_order_ordinal
                != self.occurrence_authority.occurrence_order_ordinal
                or cell.row_ordinal != row
                or cell.absolute_row_ordinal != self.occurrence_authority.start_row_ordinal + row
                or cell.storage_ordinal != field
                or cell.field_authority_sha256 != fields[field]
            ):
                raise TypedFieldValueReceiptError("value cells are reordered or foreign")
        if _value_totals(self.cells) != (
            self.value_node_count,
            self.value_max_depth,
            self.value_utf8_bytes,
            self.value_binary_bytes,
            self.value_container_items,
            self.value_canonical_bytes,
        ):
            raise TypedFieldValueReceiptError("value resource totals are invalid")
        if self.cells_sha256 != canonical_sha256([item.to_dict() for item in self.cells]):
            raise TypedFieldValueReceiptError("value cell digest is invalid")
        if self.value_receipt_sha256 != canonical_sha256(self.identity_payload()):
            raise TypedFieldValueReceiptError("value receipt digest is invalid")

    def identity_payload(self) -> dict[str, object]:
        return {
            "schema_version": 2,
            "kind": self.kind,
            "occurrence_authority_sha256": self.occurrence_authority.authority_sha256,
            "field_authority_sha256s": list(self.field_authority_sha256s),
            "row_count": self.row_count,
            "field_count": self.field_count,
            "cell_count": self.cell_count,
            "value_node_count": self.value_node_count,
            "value_max_depth": self.value_max_depth,
            "value_utf8_bytes": self.value_utf8_bytes,
            "value_binary_bytes": self.value_binary_bytes,
            "value_container_items": self.value_container_items,
            "value_canonical_bytes": self.value_canonical_bytes,
            "cells_sha256": self.cells_sha256,
        }

    def to_dict(self) -> dict[str, object]:
        return {
            **self.identity_payload(),
            "occurrence_authority": self.occurrence_authority.to_dict(),
            "cells": [item.to_dict() for item in self.cells],
            "value_receipt_sha256": self.value_receipt_sha256,
        }

    def to_canonical_bytes(self) -> bytes:
        return _canonical_json_bytes(self.to_dict(), maximum_bytes=MAX_OCCURRENCE_CANONICAL_BYTES)

    @classmethod
    def from_canonical_bytes(cls, encoded: bytes) -> Self:
        return cls._from_payload(
            _decode_object(
                encoded,
                maximum_bytes=MAX_OCCURRENCE_CANONICAL_BYTES,
                maximum_items=MAX_ROUTE_CELLS * 32,
            )
        )

    @classmethod
    def _from_payload(cls, payload: object, *, budget: ValueBudget | None = None) -> Self:
        keys = {
            "schema_version",
            "kind",
            "occurrence_authority_sha256",
            "occurrence_authority",
            "field_authority_sha256s",
            "row_count",
            "field_count",
            "cell_count",
            "cells",
            "value_node_count",
            "value_max_depth",
            "value_utf8_bytes",
            "value_binary_bytes",
            "value_container_items",
            "value_canonical_bytes",
            "cells_sha256",
            "value_receipt_sha256",
        }
        item = _dict(payload, keys=keys, label="typed value receipt")
        _require_v2(item, kind=cls.kind)
        if type(item["field_authority_sha256s"]) is not list or type(item["cells"]) is not list:
            raise TypedFieldValueReceiptError("value inventories must be lists")
        rows = _integer(item["row_count"], field_name="row_count", maximum=MAX_ROUTE_ROWS)
        fields = _integer(item["field_count"], field_name="field_count", maximum=MAX_ROUTE_FIELDS)
        cells_count = _integer(item["cell_count"], field_name="cell_count", maximum=MAX_ROUTE_CELLS)
        value_node_count = _integer(
            item["value_node_count"],
            field_name="value_node_count",
            maximum=MAX_ROUTE_VALUE_NODES,
        )
        value_max_depth = _integer(
            item["value_max_depth"],
            field_name="value_max_depth",
            maximum=MAX_JSON_DEPTH,
        )
        value_utf8_bytes = _integer(
            item["value_utf8_bytes"],
            field_name="value_utf8_bytes",
            maximum=MAX_ROUTE_VALUE_BYTES,
        )
        value_binary_bytes = _integer(
            item["value_binary_bytes"],
            field_name="value_binary_bytes",
            maximum=MAX_ROUTE_BINARY_BYTES,
        )
        value_container_items = _integer(
            item["value_container_items"],
            field_name="value_container_items",
            maximum=MAX_ROUTE_CONTAINER_ITEMS,
        )
        value_canonical_bytes = _integer(
            item["value_canonical_bytes"],
            field_name="value_canonical_bytes",
            maximum=MAX_ROUTE_CANONICAL_BYTES,
        )
        expected = _product(
            rows, fields, maximum=MAX_ROUTE_CELLS, label="occurrence cell denominator"
        )
        if cells_count != expected or len(cast("list[object]", item["cells"])) != expected:
            raise TypedFieldValueReceiptError("value declared denominator is invalid")
        occurrence = OccurrenceLandingAuthorityV2._from_payload(item["occurrence_authority"])
        if item["occurrence_authority_sha256"] != occurrence.authority_sha256:
            raise TypedFieldValueReceiptError("value occurrence authority is rebound")
        cells = tuple(
            TypedFieldCellV2._from_payload(value, budget=budget)
            for value in cast("list[object]", item["cells"])
        )
        return cls(
            occurrence_authority=occurrence,
            field_authority_sha256s=tuple(cast("list[str]", item["field_authority_sha256s"])),
            row_count=rows,
            field_count=fields,
            cell_count=cells_count,
            cells=cells,
            value_node_count=value_node_count,
            value_max_depth=value_max_depth,
            value_utf8_bytes=value_utf8_bytes,
            value_binary_bytes=value_binary_bytes,
            value_container_items=value_container_items,
            value_canonical_bytes=value_canonical_bytes,
            cells_sha256=cast("str", item["cells_sha256"]),
            value_receipt_sha256=cast("str", item["value_receipt_sha256"]),
        )


@dataclass(frozen=True, slots=True)
class ConditionalSourceRowAuthorityV2:
    """One conditional storage row rebound to its exact raw/body source identity."""

    conditional_authority_sha256: str
    raw_bundle_sha256: str
    readback_receipt_sha256: str
    source_shape: ConditionalSourceShape
    source_family: Literal["stats", "live"]
    decoder_kind: DecoderKind
    route_id: str
    staging_key: str
    row_order_ordinal: int
    row_slice_receipt_sha256: str
    observation_record_sha256: str
    observation_sha256: str
    source_occurrence_sha256: str | None
    body_object_sha256: str | None
    source_presence: str | None
    source_row_count: int | None
    source_parent_state_sha256: str | None
    response_receipt_sha256: str
    observed_response_sha256: str | None
    observed_results_sha256: str | None
    observed_provider_result_set_count: int | None
    observed_expected_result_set_count: int | None
    observed_reason_codes: tuple[str, ...]
    record_kind: str
    result_set_name: str | None
    result_set_ordinal: int | None
    result_set_occurrence: int | None
    provider_result_ordinal: int | None
    canonical_result_ordinal: int | None
    header_name: str | None
    header_ordinal: int | None
    provider_row_ordinal: int | None
    contract_field_ordinal: int | None
    node_ordinal: int | None
    parent_node_ordinal: int | None
    json_path: str | None
    parent_json_path: str | None
    object_key: str | None
    object_key_ordinal: int | None
    array_ordinal: int | None
    presence_kind: str | None
    value_kind: str | None
    source_binding_sha256s: tuple[str, ...]
    selector_columns: tuple[str, ...]
    source_verified_columns: tuple[str, ...]
    source_row_sha256: str
    authority_sha256: str

    schema_version: ClassVar[int] = 2
    kind: ClassVar[str] = "conditional_source_row_authority_v2"

    def __post_init__(self) -> None:
        for name in (
            "conditional_authority_sha256",
            "raw_bundle_sha256",
            "readback_receipt_sha256",
            "row_slice_receipt_sha256",
            "observation_record_sha256",
            "observation_sha256",
            "response_receipt_sha256",
            "source_row_sha256",
            "authority_sha256",
        ):
            _sha256(getattr(self, name), field_name=name)
        if self.source_shape not in _CONDITIONAL_DECODER_BY_SHAPE:
            raise TypedFieldValueReceiptError("conditional row source shape is unsupported")
        expected_family = "live" if self.source_shape == "live_lossless_bound" else "stats"
        if (
            self.source_family != expected_family
            or self.decoder_kind != _CONDITIONAL_DECODER_BY_SHAPE[self.source_shape]
        ):
            raise TypedFieldValueReceiptError("conditional row decoder relabels its source")
        _text(self.route_id, field_name="route_id")
        _text(self.staging_key, field_name="staging_key")
        _integer(
            self.row_order_ordinal,
            field_name="row_order_ordinal",
            maximum=MAX_ROUTE_ROWS - 1,
        )
        source_occurrence = _optional_sha256(
            self.source_occurrence_sha256,
            field_name="source_occurrence_sha256",
        )
        body_object = _optional_sha256(
            self.body_object_sha256,
            field_name="body_object_sha256",
        )
        _optional_text(self.source_presence, field_name="source_presence")
        if (
            self.source_presence is not None
            and self.source_presence not in _SOURCE_OCCURRENCE_PRESENCES
        ):
            raise TypedFieldValueReceiptError("conditional row source presence is invalid")
        _optional_integer(
            self.source_row_count,
            field_name="source_row_count",
            maximum=MAX_ROUTE_ROWS,
        )
        _optional_sha256(
            self.source_parent_state_sha256,
            field_name="source_parent_state_sha256",
        )
        occurrence_state = (
            self.source_presence,
            self.source_row_count,
            self.source_parent_state_sha256,
        )
        has_complete_occurrence_state = all(value is not None for value in occurrence_state)
        has_any_occurrence_state = any(value is not None for value in occurrence_state)
        if source_occurrence is None:
            if has_any_occurrence_state:
                raise TypedFieldValueReceiptError(
                    "conditional row invents a partial occurrence state"
                )
        elif not has_complete_occurrence_state:
            raise TypedFieldValueReceiptError("conditional row omits its complete occurrence state")
        if self.source_shape == "selected_result_bound":
            if source_occurrence is None or body_object is not None:
                raise TypedFieldValueReceiptError(
                    "selected conditional row must name one result occurrence"
                )
        elif self.source_shape == "body_node_bound":
            if source_occurrence is not None or body_object is None or has_any_occurrence_state:
                raise TypedFieldValueReceiptError(
                    "body-node conditional row must name one parser-input object"
                )
        elif self.source_shape == "hybrid_result_body_bound":
            if source_occurrence is None:
                if body_object is None or has_any_occurrence_state:
                    raise TypedFieldValueReceiptError(
                        "hybrid body row must name one parser-input object"
                    )
            elif body_object is not None:
                raise TypedFieldValueReceiptError(
                    "hybrid result row cannot also name a body object"
                )
        elif body_object is None:
            raise TypedFieldValueReceiptError(
                "live conditional row must name its parser-input object"
            )
        observed_digests = (
            self.observed_response_sha256,
            self.observed_results_sha256,
        )
        observed_counts = (
            self.observed_provider_result_set_count,
            self.observed_expected_result_set_count,
        )
        selected_stats_row = self.source_shape == "selected_result_bound" or (
            self.source_shape == "hybrid_result_body_bound" and source_occurrence is not None
        )
        if selected_stats_row:
            for name, value in zip(
                ("observed_response_sha256", "observed_results_sha256"),
                observed_digests,
                strict=True,
            ):
                _sha256(value, field_name=name)
            for name, value in zip(
                (
                    "observed_provider_result_set_count",
                    "observed_expected_result_set_count",
                ),
                observed_counts,
                strict=True,
            ):
                if value is None:
                    raise TypedFieldValueReceiptError(
                        "selected conditional row omits observed response counts"
                    )
                _integer(value, field_name=name, maximum=MAX_ROUTE_OCCURRENCES)
            if (
                (
                    self.observed_expected_result_set_count == 0
                    and self.source_shape != "hybrid_result_body_bound"
                )
                or (
                    self.source_shape == "hybrid_result_body_bound"
                    and self.observed_expected_result_set_count != 0
                )
                or type(self.observed_reason_codes) is not tuple
                or not self.observed_reason_codes
                or (
                    self.source_shape == "hybrid_result_body_bound"
                    and self.observed_reason_codes != ("unknown_dynamic_response",)
                )
            ):
                raise TypedFieldValueReceiptError(
                    "selected conditional row omits observed response reasons"
                )
        elif (
            any(value is not None for value in (*observed_digests, *observed_counts))
            or self.observed_reason_codes
        ):
            raise TypedFieldValueReceiptError(
                "non-selected conditional row invents observed stats response authority"
            )
        if type(self.observed_reason_codes) is not tuple or self.observed_reason_codes != tuple(
            sorted(set(self.observed_reason_codes))
        ):
            raise TypedFieldValueReceiptError("conditional row observed reasons are not canonical")
        for value in self.observed_reason_codes:
            _text(value, field_name="observed_reason_code")
        _text(self.record_kind, field_name="record_kind")
        for name in (
            "result_set_name",
            "header_name",
            "json_path",
            "parent_json_path",
            "object_key",
            "presence_kind",
            "value_kind",
        ):
            _optional_text(getattr(self, name), field_name=name)
        for name, maximum in (
            ("result_set_ordinal", MAX_ROUTE_OCCURRENCES - 1),
            ("result_set_occurrence", MAX_ROUTE_OCCURRENCES - 1),
            ("provider_result_ordinal", MAX_ROUTE_OCCURRENCES - 1),
            ("canonical_result_ordinal", MAX_ROUTE_OCCURRENCES - 1),
            ("header_ordinal", MAX_ROUTE_FIELDS - 1),
            ("provider_row_ordinal", MAX_ROUTE_ROWS - 1),
            ("contract_field_ordinal", MAX_ROUTE_FIELDS - 1),
            ("node_ordinal", MAX_ROUTE_ROWS - 1),
            ("parent_node_ordinal", MAX_ROUTE_ROWS - 1),
            ("object_key_ordinal", MAX_ROUTE_FIELDS - 1),
            ("array_ordinal", MAX_ROUTE_ROWS - 1),
        ):
            _optional_integer(getattr(self, name), field_name=name, maximum=maximum)
        bindings = _sha_tuple(
            self.source_binding_sha256s,
            field_name="source_binding_sha256s",
            maximum=MAX_ROUTE_FIELDS,
        )
        if bindings != tuple(sorted(set(bindings))):
            raise TypedFieldValueReceiptError("conditional row binding inventory is not canonical")
        if (
            self.source_shape
            in {
                "selected_result_bound",
                "body_node_bound",
                "hybrid_result_body_bound",
            }
            and len(bindings) != 1
        ):
            raise TypedFieldValueReceiptError(
                "stats conditional row must name its exact row binding"
            )
        if (
            type(self.selector_columns) is not tuple
            or type(self.source_verified_columns) is not tuple
        ):
            raise TypedFieldValueReceiptError("conditional row selectors must be immutable")
        for value in (*self.selector_columns, *self.source_verified_columns):
            _text(value, field_name="selector_column")
        if (
            self.selector_columns != tuple(sorted(set(self.selector_columns)))
            or self.source_verified_columns != tuple(sorted(set(self.source_verified_columns)))
            or not set(self.source_verified_columns).issubset(self.selector_columns)
        ):
            raise TypedFieldValueReceiptError("conditional row selector inventory is not canonical")
        if self.authority_sha256 != canonical_sha256(self.identity_payload()):
            raise TypedFieldValueReceiptError("conditional row authority digest is invalid")

    def identity_payload(self) -> dict[str, object]:
        return {
            "schema_version": 2,
            "kind": self.kind,
            "conditional_authority_sha256": self.conditional_authority_sha256,
            "raw_bundle_sha256": self.raw_bundle_sha256,
            "readback_receipt_sha256": self.readback_receipt_sha256,
            "source_shape": self.source_shape,
            "source_family": self.source_family,
            "decoder_kind": self.decoder_kind,
            "route_id": self.route_id,
            "staging_key": self.staging_key,
            "row_order_ordinal": self.row_order_ordinal,
            "row_slice_receipt_sha256": self.row_slice_receipt_sha256,
            "observation_record_sha256": self.observation_record_sha256,
            "observation_sha256": self.observation_sha256,
            "source_occurrence_sha256": self.source_occurrence_sha256,
            "body_object_sha256": self.body_object_sha256,
            "source_presence": self.source_presence,
            "source_row_count": self.source_row_count,
            "source_parent_state_sha256": self.source_parent_state_sha256,
            "response_receipt_sha256": self.response_receipt_sha256,
            "observed_response_sha256": self.observed_response_sha256,
            "observed_results_sha256": self.observed_results_sha256,
            "observed_provider_result_set_count": (self.observed_provider_result_set_count),
            "observed_expected_result_set_count": (self.observed_expected_result_set_count),
            "observed_reason_codes": list(self.observed_reason_codes),
            "record_kind": self.record_kind,
            "result_set_name": self.result_set_name,
            "result_set_ordinal": self.result_set_ordinal,
            "result_set_occurrence": self.result_set_occurrence,
            "provider_result_ordinal": self.provider_result_ordinal,
            "canonical_result_ordinal": self.canonical_result_ordinal,
            "header_name": self.header_name,
            "header_ordinal": self.header_ordinal,
            "provider_row_ordinal": self.provider_row_ordinal,
            "contract_field_ordinal": self.contract_field_ordinal,
            "node_ordinal": self.node_ordinal,
            "parent_node_ordinal": self.parent_node_ordinal,
            "json_path": self.json_path,
            "parent_json_path": self.parent_json_path,
            "object_key": self.object_key,
            "object_key_ordinal": self.object_key_ordinal,
            "array_ordinal": self.array_ordinal,
            "presence_kind": self.presence_kind,
            "value_kind": self.value_kind,
            "source_binding_sha256s": list(self.source_binding_sha256s),
            "selector_columns": list(self.selector_columns),
            "source_verified_columns": list(self.source_verified_columns),
            "source_row_sha256": self.source_row_sha256,
        }

    def to_dict(self) -> dict[str, object]:
        return self.identity_payload() | {"authority_sha256": self.authority_sha256}

    @classmethod
    def _from_payload(cls, payload: object) -> Self:
        keys = {
            *cls.__dataclass_fields__,
            "schema_version",
            "kind",
        }
        keys.discard("schema_version")
        keys.discard("kind")
        keys |= {"schema_version", "kind"}
        item = _dict(payload, keys=keys, label="conditional row authority")
        _require_v2(item, kind=cls.kind)
        if (
            type(item["source_binding_sha256s"]) is not list
            or type(item["selector_columns"]) is not list
            or type(item["source_verified_columns"]) is not list
            or type(item["observed_reason_codes"]) is not list
        ):
            raise TypedFieldValueReceiptError("conditional row inventories must be exact lists")
        return cls(
            conditional_authority_sha256=cast("str", item["conditional_authority_sha256"]),
            raw_bundle_sha256=cast("str", item["raw_bundle_sha256"]),
            readback_receipt_sha256=cast("str", item["readback_receipt_sha256"]),
            source_shape=cast("ConditionalSourceShape", item["source_shape"]),
            source_family=cast("Literal['stats', 'live']", item["source_family"]),
            decoder_kind=cast("DecoderKind", item["decoder_kind"]),
            route_id=cast("str", item["route_id"]),
            staging_key=cast("str", item["staging_key"]),
            row_order_ordinal=cast("int", item["row_order_ordinal"]),
            row_slice_receipt_sha256=cast("str", item["row_slice_receipt_sha256"]),
            observation_record_sha256=cast("str", item["observation_record_sha256"]),
            observation_sha256=cast("str", item["observation_sha256"]),
            source_occurrence_sha256=cast("str | None", item["source_occurrence_sha256"]),
            body_object_sha256=cast("str | None", item["body_object_sha256"]),
            source_presence=cast("str | None", item["source_presence"]),
            source_row_count=cast("int | None", item["source_row_count"]),
            source_parent_state_sha256=cast("str | None", item["source_parent_state_sha256"]),
            response_receipt_sha256=cast("str", item["response_receipt_sha256"]),
            observed_response_sha256=cast("str | None", item["observed_response_sha256"]),
            observed_results_sha256=cast("str | None", item["observed_results_sha256"]),
            observed_provider_result_set_count=cast(
                "int | None", item["observed_provider_result_set_count"]
            ),
            observed_expected_result_set_count=cast(
                "int | None", item["observed_expected_result_set_count"]
            ),
            observed_reason_codes=tuple(cast("list[str]", item["observed_reason_codes"])),
            record_kind=cast("str", item["record_kind"]),
            result_set_name=cast("str | None", item["result_set_name"]),
            result_set_ordinal=cast("int | None", item["result_set_ordinal"]),
            result_set_occurrence=cast("int | None", item["result_set_occurrence"]),
            provider_result_ordinal=cast("int | None", item["provider_result_ordinal"]),
            canonical_result_ordinal=cast("int | None", item["canonical_result_ordinal"]),
            header_name=cast("str | None", item["header_name"]),
            header_ordinal=cast("int | None", item["header_ordinal"]),
            provider_row_ordinal=cast("int | None", item["provider_row_ordinal"]),
            contract_field_ordinal=cast("int | None", item["contract_field_ordinal"]),
            node_ordinal=cast("int | None", item["node_ordinal"]),
            parent_node_ordinal=cast("int | None", item["parent_node_ordinal"]),
            json_path=cast("str | None", item["json_path"]),
            parent_json_path=cast("str | None", item["parent_json_path"]),
            object_key=cast("str | None", item["object_key"]),
            object_key_ordinal=cast("int | None", item["object_key_ordinal"]),
            array_ordinal=cast("int | None", item["array_ordinal"]),
            presence_kind=cast("str | None", item["presence_kind"]),
            value_kind=cast("str | None", item["value_kind"]),
            source_binding_sha256s=tuple(cast("list[str]", item["source_binding_sha256s"])),
            selector_columns=tuple(cast("list[str]", item["selector_columns"])),
            source_verified_columns=tuple(cast("list[str]", item["source_verified_columns"])),
            source_row_sha256=cast("str", item["source_row_sha256"]),
            authority_sha256=cast("str", item["authority_sha256"]),
        )


@dataclass(frozen=True, slots=True)
class ConditionalTypedFieldCellV2:
    row_authority_sha256: str
    field_authority_sha256: str
    source_binding_sha256s: tuple[str, ...]
    source_shape: ConditionalSourceShape
    row_order_ordinal: int
    storage_ordinal: int
    storage_column: str
    logical_type_sha256: str
    value_authority: ValueAuthorityKind
    canonical_value: CanonicalArrowValueV1
    cell_receipt_sha256: str

    schema_version: ClassVar[int] = 2
    kind: ClassVar[str] = "conditional_typed_field_cell_v2"

    def __post_init__(self) -> None:
        for name in (
            "row_authority_sha256",
            "field_authority_sha256",
            "logical_type_sha256",
            "cell_receipt_sha256",
        ):
            _sha256(getattr(self, name), field_name=name)
        bindings = _sha_tuple(
            self.source_binding_sha256s,
            field_name="source_binding_sha256s",
            maximum=MAX_ROUTE_FIELDS,
        )
        if bindings != tuple(sorted(set(bindings))):
            raise TypedFieldValueReceiptError("conditional cell binding inventory is not canonical")
        if self.source_shape not in _CONDITIONAL_DECODER_BY_SHAPE:
            raise TypedFieldValueReceiptError("conditional cell source shape is unsupported")
        _integer(
            self.row_order_ordinal,
            field_name="row_order_ordinal",
            maximum=MAX_ROUTE_ROWS - 1,
        )
        _integer(
            self.storage_ordinal,
            field_name="storage_ordinal",
            maximum=MAX_ROUTE_FIELDS - 1,
        )
        _text(self.storage_column, field_name="storage_column")
        if self.value_authority not in {"source_verified", "storage_readback_only"}:
            raise TypedFieldValueReceiptError("conditional cell value authority is invalid")
        if type(self.canonical_value) is not CanonicalArrowValueV1:
            raise TypedFieldValueReceiptError("conditional cell value is foreign")
        if self.logical_type_sha256 != self.canonical_value.logical_type_sha256:
            raise TypedFieldValueReceiptError("conditional cell logical type is invalid")
        if self.cell_receipt_sha256 != canonical_sha256(self.identity_payload()):
            raise TypedFieldValueReceiptError("conditional cell receipt digest is invalid")

    def identity_payload(self) -> dict[str, object]:
        return {
            "schema_version": 2,
            "kind": self.kind,
            "row_authority_sha256": self.row_authority_sha256,
            "field_authority_sha256": self.field_authority_sha256,
            "source_binding_sha256s": list(self.source_binding_sha256s),
            "source_shape": self.source_shape,
            "row_order_ordinal": self.row_order_ordinal,
            "storage_ordinal": self.storage_ordinal,
            "storage_column": self.storage_column,
            "logical_type_sha256": self.logical_type_sha256,
            "value_authority": self.value_authority,
            "canonical_value": self.canonical_value.to_dict(),
        }

    def to_dict(self) -> dict[str, object]:
        return self.identity_payload() | {"cell_receipt_sha256": self.cell_receipt_sha256}

    @classmethod
    def _from_payload(cls, payload: object, *, budget: ValueBudget | None = None) -> Self:
        keys = {
            "schema_version",
            "kind",
            "row_authority_sha256",
            "field_authority_sha256",
            "source_binding_sha256s",
            "source_shape",
            "row_order_ordinal",
            "storage_ordinal",
            "storage_column",
            "logical_type_sha256",
            "value_authority",
            "canonical_value",
            "cell_receipt_sha256",
        }
        item = _dict(payload, keys=keys, label="conditional typed field cell")
        _require_v2(item, kind=cls.kind)
        if type(item["source_binding_sha256s"]) is not list:
            raise TypedFieldValueReceiptError("conditional cell binding inventory must be a list")
        return cls(
            row_authority_sha256=cast("str", item["row_authority_sha256"]),
            field_authority_sha256=cast("str", item["field_authority_sha256"]),
            source_binding_sha256s=tuple(cast("list[str]", item["source_binding_sha256s"])),
            source_shape=cast("ConditionalSourceShape", item["source_shape"]),
            row_order_ordinal=cast("int", item["row_order_ordinal"]),
            storage_ordinal=cast("int", item["storage_ordinal"]),
            storage_column=cast("str", item["storage_column"]),
            logical_type_sha256=cast("str", item["logical_type_sha256"]),
            value_authority=cast("ValueAuthorityKind", item["value_authority"]),
            canonical_value=_arrow_value(item["canonical_value"], budget=budget),
            cell_receipt_sha256=cast("str", item["cell_receipt_sha256"]),
        )


@dataclass(frozen=True, slots=True)
class ConditionalRowValueReceiptV2:
    row_authority: ConditionalSourceRowAuthorityV2
    field_authority_sha256s: tuple[str, ...]
    field_count: int
    cells: tuple[ConditionalTypedFieldCellV2, ...]
    value_node_count: int
    value_max_depth: int
    value_utf8_bytes: int
    value_binary_bytes: int
    value_container_items: int
    value_canonical_bytes: int
    cells_sha256: str
    value_receipt_sha256: str

    schema_version: ClassVar[int] = 2
    kind: ClassVar[str] = "conditional_row_value_receipt_v2"

    def __post_init__(self) -> None:
        if type(self.row_authority) is not ConditionalSourceRowAuthorityV2:
            raise TypedFieldValueReceiptError("conditional value row authority is foreign")
        fields = _sha_tuple(
            self.field_authority_sha256s,
            field_name="field_authority_sha256s",
            maximum=MAX_ROUTE_FIELDS,
        )
        _integer(self.field_count, field_name="field_count", maximum=MAX_ROUTE_FIELDS)
        if (
            len(fields) != self.field_count
            or type(self.cells) is not tuple
            or len(self.cells) != self.field_count
        ):
            raise TypedFieldValueReceiptError("conditional row cell denominator is incomplete")
        if any(type(item) is not ConditionalTypedFieldCellV2 for item in self.cells):
            raise TypedFieldValueReceiptError("conditional row contains foreign cells")
        for ordinal, cell in enumerate(self.cells):
            if (
                cell.row_authority_sha256 != self.row_authority.authority_sha256
                or cell.source_shape != self.row_authority.source_shape
                or cell.row_order_ordinal != self.row_authority.row_order_ordinal
                or cell.storage_ordinal != ordinal
                or cell.field_authority_sha256 != fields[ordinal]
                or not set(cell.source_binding_sha256s).issubset(
                    self.row_authority.source_binding_sha256s
                )
            ):
                raise TypedFieldValueReceiptError("conditional row cells are reordered or rebound")
        for name, maximum in (
            ("value_node_count", MAX_ROUTE_VALUE_NODES),
            ("value_max_depth", MAX_JSON_DEPTH),
            ("value_utf8_bytes", MAX_ROUTE_VALUE_BYTES),
            ("value_binary_bytes", MAX_ROUTE_BINARY_BYTES),
            ("value_container_items", MAX_ROUTE_CONTAINER_ITEMS),
            ("value_canonical_bytes", MAX_ROUTE_CANONICAL_BYTES),
        ):
            _integer(getattr(self, name), field_name=name, maximum=maximum)
        if _conditional_value_totals(self.cells) != (
            self.value_node_count,
            self.value_max_depth,
            self.value_utf8_bytes,
            self.value_binary_bytes,
            self.value_container_items,
            self.value_canonical_bytes,
        ):
            raise TypedFieldValueReceiptError("conditional row value totals are invalid")
        if self.cells_sha256 != canonical_sha256([item.to_dict() for item in self.cells]):
            raise TypedFieldValueReceiptError("conditional row cell digest is invalid")
        if self.value_receipt_sha256 != canonical_sha256(self.identity_payload()):
            raise TypedFieldValueReceiptError("conditional row value digest is invalid")

    def identity_payload(self) -> dict[str, object]:
        return {
            "schema_version": 2,
            "kind": self.kind,
            "row_authority_sha256": self.row_authority.authority_sha256,
            "field_authority_sha256s": list(self.field_authority_sha256s),
            "field_count": self.field_count,
            "value_node_count": self.value_node_count,
            "value_max_depth": self.value_max_depth,
            "value_utf8_bytes": self.value_utf8_bytes,
            "value_binary_bytes": self.value_binary_bytes,
            "value_container_items": self.value_container_items,
            "value_canonical_bytes": self.value_canonical_bytes,
            "cells_sha256": self.cells_sha256,
        }

    def to_dict(self) -> dict[str, object]:
        return {
            **self.identity_payload(),
            "row_authority": self.row_authority.to_dict(),
            "cells": [item.to_dict() for item in self.cells],
            "value_receipt_sha256": self.value_receipt_sha256,
        }

    @classmethod
    def _from_payload(cls, payload: object, *, budget: ValueBudget | None = None) -> Self:
        keys = {
            "schema_version",
            "kind",
            "row_authority_sha256",
            "row_authority",
            "field_authority_sha256s",
            "field_count",
            "cells",
            "value_node_count",
            "value_max_depth",
            "value_utf8_bytes",
            "value_binary_bytes",
            "value_container_items",
            "value_canonical_bytes",
            "cells_sha256",
            "value_receipt_sha256",
        }
        item = _dict(payload, keys=keys, label="conditional row value receipt")
        _require_v2(item, kind=cls.kind)
        if type(item["field_authority_sha256s"]) is not list or type(item["cells"]) is not list:
            raise TypedFieldValueReceiptError("conditional row value inventories must be lists")
        field_count = _integer(
            item["field_count"], field_name="field_count", maximum=MAX_ROUTE_FIELDS
        )
        if len(cast("list[object]", item["cells"])) != field_count:
            raise TypedFieldValueReceiptError(
                "conditional row declared cell denominator is invalid"
            )
        authority = ConditionalSourceRowAuthorityV2._from_payload(item["row_authority"])
        if item["row_authority_sha256"] != authority.authority_sha256:
            raise TypedFieldValueReceiptError("conditional row authority is rebound")
        cells = tuple(
            ConditionalTypedFieldCellV2._from_payload(value, budget=budget)
            for value in cast("list[object]", item["cells"])
        )
        return cls(
            row_authority=authority,
            field_authority_sha256s=tuple(cast("list[str]", item["field_authority_sha256s"])),
            field_count=field_count,
            cells=cells,
            value_node_count=cast("int", item["value_node_count"]),
            value_max_depth=cast("int", item["value_max_depth"]),
            value_utf8_bytes=cast("int", item["value_utf8_bytes"]),
            value_binary_bytes=cast("int", item["value_binary_bytes"]),
            value_container_items=cast("int", item["value_container_items"]),
            value_canonical_bytes=cast("int", item["value_canonical_bytes"]),
            cells_sha256=cast("str", item["cells_sha256"]),
            value_receipt_sha256=cast("str", item["value_receipt_sha256"]),
        )


def _conditional_value_totals(
    cells: tuple[ConditionalTypedFieldCellV2, ...],
) -> tuple[int, int, int, int, int, int]:
    nodes = utf8 = binary = items = canonical = 0
    depth = 0
    for cell in cells:
        value = cell.canonical_value
        nodes = _add(
            nodes, value.node_count, maximum=MAX_ROUTE_VALUE_NODES, label="route value nodes"
        )
        utf8 = _add(
            utf8, value.utf8_bytes, maximum=MAX_ROUTE_VALUE_BYTES, label="route UTF-8 bytes"
        )
        binary = _add(
            binary,
            value.binary_bytes,
            maximum=MAX_ROUTE_BINARY_BYTES,
            label="route binary bytes",
        )
        items = _add(
            items,
            value.container_items,
            maximum=MAX_ROUTE_CONTAINER_ITEMS,
            label="route container items",
        )
        canonical = _add(
            canonical,
            len(value.to_canonical_bytes()),
            maximum=MAX_ROUTE_VALUE_BYTES,
            label="route value canonical bytes",
        )
        depth = max(depth, value.max_depth)
    return nodes, depth, utf8, binary, items, canonical


def _read_table(readback: CommittedStagingFrameReadbackV2) -> pa.Table:
    try:
        source = pa.BufferReader(readback.canonical_frame_bytes)
        with pa_ipc.open_stream(source) as reader:
            schema = reader.schema
            batches = list(reader)
        if source.tell() != len(readback.canonical_frame_bytes) or len(batches) != 1:
            raise TypedFieldValueReceiptError("committed Arrow frame is not one exact batch")
        return pa.Table.from_batches(batches, schema=schema)
    except TypedFieldValueReceiptError:
        raise
    except Exception as exc:
        raise TypedFieldValueReceiptError("committed Arrow frame cannot be decoded") from exc


def _readback(value: object) -> CommittedStagingFrameReadbackV2:
    if type(value) is not CommittedStagingFrameReadbackV2:
        raise TypedFieldValueReceiptError(
            "stale or foreign staging evidence requires a fresh full restart"
        )
    try:
        return CommittedStagingFrameReadbackV2(
            committed_receipt=value.committed_receipt,
            canonical_frame_format=value.canonical_frame_format,
            frame_content_hash_contract=value.frame_content_hash_contract,
            frame_schema_hash_contract=value.frame_schema_hash_contract,
            canonical_frame_bytes=value.canonical_frame_bytes,
            canonical_frame_sha256=value.canonical_frame_sha256,
            canonical_frame_size_bytes=value.canonical_frame_size_bytes,
            recomputed_frame_schema_sha256=value.recomputed_frame_schema_sha256,
            recomputed_frame_content_hash=value.recomputed_frame_content_hash,
            recomputed_persisted_content_sha256=value.recomputed_persisted_content_sha256,
            row_count=value.row_count,
            readback_receipt_sha256=value.readback_receipt_sha256,
        )
    except ParserInputCaptureIntegrityError as exc:
        raise TypedFieldValueReceiptError(
            "stale or foreign staging evidence requires a fresh full restart"
        ) from exc


def _field_authority(
    join: RouteLandingFieldJoinV1,
    *,
    field_fate_sha256: str,
    arrow_field: pa.Field,
) -> LandingFieldAuthorityV2:
    logical_type = canonical_arrow_type(arrow_field.type)
    values: dict[str, object] = {
        "field_fate_structure_sha256": field_fate_sha256,
        "route_id": join.sink.route_id,
        "staging_key": join.sink.staging_key,
        "storage_ordinal": join.sink.storage_ordinal,
        "storage_column": join.sink.storage_column,
        "origin": join.origin,
        "sink_sha256": join.sink.sink_sha256,
        "route_binding_sha256s": tuple(item.binding_sha256 for item in join.route_bindings),
        "source_occurrence_sha256s": tuple(
            item.occurrence_sha256 for item in join.provider_sources
        ),
        "source_endpoint_ids": tuple(item.endpoint_id for item in join.provider_sources),
        "source_result_set_names": tuple(item.result_set_name for item in join.provider_sources),
        "source_result_set_ordinals": tuple(
            item.result_set_ordinal for item in join.provider_sources
        ),
        "source_header_ordinals": tuple(item.field_ordinal for item in join.provider_sources),
        "source_field_names": tuple(item.provider_field_name for item in join.provider_sources),
        "lossless_binding_sha256s": tuple(item.binding_sha256 for item in join.lossless_bindings),
        "logical_type": logical_type,
        "logical_type_sha256": logical_type.type_sha256,
    }
    identity = {
        "schema_version": 2,
        "kind": LandingFieldAuthorityV2.kind,
        **{key: value for key, value in values.items() if key != "logical_type"},
        "route_binding_sha256s": list(values["route_binding_sha256s"]),
        "source_occurrence_sha256s": list(values["source_occurrence_sha256s"]),
        "source_endpoint_ids": list(values["source_endpoint_ids"]),
        "source_result_set_names": list(values["source_result_set_names"]),
        "source_result_set_ordinals": list(values["source_result_set_ordinals"]),
        "source_header_ordinals": list(values["source_header_ordinals"]),
        "source_field_names": list(values["source_field_names"]),
        "lossless_binding_sha256s": list(values["lossless_binding_sha256s"]),
        "logical_type": logical_type.to_dict(),
    }
    return LandingFieldAuthorityV2(**values, authority_sha256=canonical_sha256(identity))


@dataclass(frozen=True, slots=True)
class _DecodedProviderRows:
    """Exact provider-order values recovered without using committed storage rows."""

    ordered_headers: tuple[str, ...]
    values: tuple[tuple[object, ...], ...]
    records: tuple[dict[str, object] | None, ...]

    def __post_init__(self) -> None:
        if (
            type(self.ordered_headers) is not tuple
            or type(self.values) is not tuple
            or type(self.records) is not tuple
            or len(self.values) != len(self.records)
            or len(self.values) > MAX_ROUTE_ROWS
        ):
            raise TypedFieldValueReceiptError("decoded provider row denominator is invalid")
        for row in self.values:
            if type(row) is not tuple or len(row) != len(self.ordered_headers):
                raise TypedFieldValueReceiptError("decoded provider row width is invalid")
        if any(record is not None and type(record) is not dict for record in self.records):
            raise TypedFieldValueReceiptError("decoded provider records have a foreign type")


_USE_COMMITTED_STORAGE_VALUE = object()

LivePlanBinding = tuple[LiveSnapshotPlanAuthorityV2, str]


def _validated_live_plan_bindings(
    value: tuple[LivePlanBinding, ...],
) -> dict[str, LivePlanBinding]:
    """Index exact live-plan projections by observation without trusting mappings."""

    if type(value) is not tuple or len(value) > MAX_ROUTE_OCCURRENCES:
        raise TypedFieldValueReceiptError("live-plan binding denominator is invalid")
    indexed: dict[str, LivePlanBinding] = {}
    for binding in value:
        if type(binding) is not tuple or len(binding) != 2:
            raise TypedFieldValueReceiptError("live-plan binding has a foreign structure")
        plan, expected_sha256 = binding
        if type(plan) is not LiveSnapshotPlanAuthorityV2:
            raise TypedFieldValueReceiptError("live-plan authority has a foreign concrete type")
        expected = _sha256(
            expected_sha256,
            field_name="expected_live_plan_authority_sha256",
        )
        if expected != plan.authority_sha256:
            raise TypedFieldValueReceiptError(
                "live-plan projection differs from its independent expected authority"
            )
        if plan.observation_sha256 in indexed:
            raise TypedFieldValueReceiptError("live-plan observation denominator is duplicated")
        indexed[plan.observation_sha256] = (plan, expected)
    return indexed


def _body_for_observation(
    bundle: RawRequestAuthorityBundleV2,
    observation: RequestObservationV2,
) -> ParserInputObjectV2 | None:
    object_sha256 = observation.body_object_sha256
    if object_sha256 is None:
        if observation.attempt.source_family != "static":
            raise TypedFieldValueReceiptError("body-bearing source omitted parser-input authority")
        return None
    matches = tuple(item for item in bundle.objects if item.object_sha256 == object_sha256)
    if len(matches) != 1:
        raise TypedFieldValueReceiptError("parser-input object denominator is not exact")
    return matches[0]


def _route_source_authority(
    *,
    bundle: RawRequestAuthorityBundleV2,
    readback: CommittedStagingFrameReadbackV2,
    live_plan_bindings: tuple[LivePlanBinding, ...],
) -> tuple[
    tuple[tuple[RequestObservationV2, ObservationRouteLandingV2], ...],
    tuple[tuple[RequestObservationV2, ResultOccurrenceV2], ...],
]:
    """Close the four raw tables and select one readback's exact route authority."""

    receipt = readback.committed_receipt
    plans = _validated_live_plan_bindings(live_plan_bindings)
    observations = {
        item.attempt.observation_sha256: item
        for item in bundle.observations
        if item.lifecycle == "selected_terminal"
    }
    landing_rows = tuple(
        (observations[item.observation_sha256], item)
        for item in bundle.landings
        if item.observation_sha256 in observations and item.route_id == receipt.result_route_id
    )
    if not landing_rows or len(landing_rows) > MAX_ROUTE_OCCURRENCES:
        raise TypedFieldValueReceiptError(
            "readback route lacks its selected response-level landing denominator"
        )
    receipt_fields = (
        "chunk_id",
        "staging_key",
        "canonical_frame_format",
        "frame_content_hash_contract",
        "frame_schema_hash_contract",
        "content_hash",
        "persisted_row_count",
        "persisted_content_sha256",
        "persisted_schema_sha256",
        "logical_call_receipt_sha256",
        "provider_authority_sha256",
        "logical_parameters_sha256",
        "result_route_id",
        "receipt_root_sha256",
    )
    consumed_plan_observations: set[str] = set()
    for observation, landing in landing_rows:
        if landing.receipt_root_sha256 != receipt.receipt_root_sha256 or any(
            getattr(landing, name) != getattr(receipt, name) for name in receipt_fields
        ):
            raise TypedFieldValueReceiptError(
                "response-level route landing differs from committed readback"
            )
        observation_occurrences = tuple(
            sorted(
                (
                    item
                    for item in bundle.occurrences
                    if item.observation_sha256 == observation.attempt.observation_sha256
                ),
                key=lambda item: item.occurrence_ordinal,
            )
        )
        observation_landings = tuple(
            sorted(
                (
                    item
                    for item in bundle.landings
                    if item.observation_sha256 == observation.attempt.observation_sha256
                ),
                key=lambda item: item.route_ordinal,
            )
        )
        plan: LiveSnapshotPlanAuthorityV2 | None = None
        expected_plan_sha256: str | None = None
        if observation.attempt.source_family == "live":
            binding = plans.get(observation.attempt.observation_sha256)
            if binding is None:
                raise TypedFieldValueReceiptError(
                    "live route landing lacks its independent sealed-plan authority"
                )
            plan, expected_plan_sha256 = binding
            consumed_plan_observations.add(observation.attempt.observation_sha256)
        try:
            reconstructed = reconstruct_raw_request_authority(
                _body_for_observation(bundle, observation),
                observation,
                observation_occurrences,
                observation_landings,
                live_plan_authority=plan,
                expected_live_plan_authority_sha256=expected_plan_sha256,
            )
        except (
            RawRequestAuthorityError,
            RawRequestReconstructionError,
            TypeError,
            ValueError,
        ) as exc:
            raise TypedFieldValueReceiptError(
                "response-level route landing cannot be independently reconstructed"
            ) from exc
        matches = tuple(
            item
            for item in reconstructed.route_landings
            if item.route_id == landing.route_id and item.landing_sha256 == landing.landing_sha256
        )
        if len(matches) != 1 or matches[0].receipt_root_sha256 != receipt.receipt_root_sha256:
            raise TypedFieldValueReceiptError(
                "reconstructed route landing is missing, foreign, or relabelled"
            )
    if set(plans) != consumed_plan_observations:
        raise TypedFieldValueReceiptError("live-plan binding inventory contains a foreign row")
    try:
        selected = bundle.selected_terminal_occurrences_for_route(
            receipt.result_route_id,
            receipt.receipt_root_sha256,
        )
    except RawRequestAuthorityError as exc:
        raise TypedFieldValueReceiptError("route occurrence denominator is invalid") from exc
    if len(selected) > MAX_ROUTE_OCCURRENCES:
        raise TypedFieldValueReceiptError("route occurrence denominator exceeds its bound")
    return landing_rows, selected


def _decode_raw_json_object(parser_input: bytes) -> dict[str, object]:
    try:
        decoded = json.loads(
            parser_input,
            object_pairs_hook=_reject_duplicates,
            parse_constant=_reject_constant,
        )
    except TypedFieldValueReceiptError:
        raise
    except (TypeError, ValueError, json.JSONDecodeError, UnicodeDecodeError) as exc:
        raise TypedFieldValueReceiptError("raw parser-input body is not exact JSON") from exc
    if type(decoded) is not dict:
        raise TypedFieldValueReceiptError("raw parser-input body is not one JSON object")
    return cast("dict[str, object]", decoded)


def _rederive_unknown_stats_response(
    *,
    observation: RequestObservationV2,
    parser_input: bytes | None,
) -> NbaApiUnknownResponse | None:
    """Return exact production unknown-mode replay, or ``None`` for other sources."""

    if observation.attempt.source_family != "stats":
        return None
    contract = pinned_runtime_contracts().get(observation.attempt.endpoint_id)
    if contract is None or contract.response_mode != "unknown_dynamic_response":
        return None
    if parser_input is None:
        raise TypedFieldValueReceiptError(
            "unknown-dynamic raw observation omitted parser-input bytes"
        )
    try:
        return rederive_raw_authority_unknown_stats_response(
            endpoint_id=observation.attempt.endpoint_id,
            parser_input=parser_input,
            safe_parameters_json=observation.attempt.safe_parameters_json,
            provider_authority_sha256=observation.attempt.provider_authority_sha256,
            endpoint_contract_sha256_value=(observation.attempt.endpoint_contract_sha256),
        )
    except (ResponseContractError, TypeError, ValueError) as exc:
        raise TypedFieldValueReceiptError(
            "unknown-dynamic raw provider results cannot be rederived"
        ) from exc


def _assert_rederived_occurrence(
    *,
    observation: RequestObservationV2,
    occurrence: ResultOccurrenceV2,
    parser_input: bytes | None,
) -> None:
    """Bind structural occurrence claims back to production raw-authority replay."""

    unknown = _rederive_unknown_stats_response(
        observation=observation,
        parser_input=parser_input,
    )
    if unknown is not None:
        if occurrence.occurrence_ordinal >= len(unknown.occurrences):
            raise TypedFieldValueReceiptError(
                "unknown-dynamic occurrence ordinal is outside its denominator"
            )
        derived_unknown = unknown.occurrences[occurrence.occurrence_ordinal]
        receipt = derived_unknown.receipt
        duplicate_name_ordinal = sum(
            item.name == derived_unknown.name
            for item in unknown.occurrences[: occurrence.occurrence_ordinal]
        )
        expected_presence = "present" if derived_unknown.rows else "present_empty"
        if (
            derived_unknown.name != occurrence.result_name
            or duplicate_name_ordinal != occurrence.duplicate_name_ordinal
            or derived_unknown.provider_index != occurrence.provider_result_ordinal
            or occurrence.canonical_result_ordinal is not None
            or occurrence.json_path is not None
            or occurrence.container_kind != "nba_api_result_set"
            or expected_presence != occurrence.presence
            or derived_unknown.headers != occurrence.ordered_headers()
            or len(derived_unknown.rows) != occurrence.row_count
            or len(derived_unknown.rows) * len(derived_unknown.headers) != occurrence.cell_count
            or occurrence.node_count != 0
            or occurrence.container_count != 1
            or occurrence.missing_count != 0
            or occurrence.null_count != 0
            or receipt.parent_occurrence_states_sha256 != occurrence.parent_state_sha256
            or receipt.normalized_output_sha256 != occurrence.output_sha256
        ):
            raise TypedFieldValueReceiptError(
                "unknown-dynamic result replay differs from occurrence authority"
            )
        return

    try:
        derivations = rederive_raw_authority_result_sets(
            source_family=observation.attempt.source_family,
            endpoint_id=observation.attempt.endpoint_id,
            parser_input=parser_input,
            provider_authority_sha256=observation.attempt.provider_authority_sha256,
            endpoint_contract_sha256_value=observation.attempt.endpoint_contract_sha256,
        )
    except (ResponseContractError, TypeError, ValueError) as exc:
        raise TypedFieldValueReceiptError(
            "raw provider results cannot be rederived by production raw authority"
        ) from exc
    if occurrence.occurrence_ordinal >= len(derivations):
        raise TypedFieldValueReceiptError(
            "raw result occurrence ordinal is outside its denominator"
        )
    derived = derivations[occurrence.occurrence_ordinal]
    result = derived.result_set
    present_containers = result.container_count
    missing_count = result.missing_count
    null_count = result.null_count
    if present_containers == 0:
        if result.parent_observation_count == 0:
            expected_presence = "not_observed_parent_empty"
            expected_headers = derived.ordered_headers
            expected_row_count = expected_cell_count = expected_node_count = 0
            expected_container_count = expected_missing_count = expected_null_count = 0
        elif missing_count > 0 and null_count == 0:
            expected_presence = "missing"
            expected_headers = ()
            expected_row_count = expected_cell_count = expected_node_count = 0
            expected_container_count = 0
            expected_missing_count = missing_count
            expected_null_count = 0
        elif null_count > 0 and missing_count == 0:
            expected_presence = "null"
            expected_headers = ()
            expected_row_count = expected_cell_count = 0
            expected_node_count = expected_container_count = null_count
            expected_missing_count = 0
            expected_null_count = null_count
        elif missing_count > 0 and null_count > 0:
            expected_presence = "mixed_absent"
            expected_headers = ()
            expected_row_count = expected_cell_count = 0
            expected_node_count = expected_container_count = null_count
            expected_missing_count = missing_count
            expected_null_count = null_count
        else:
            raise TypedFieldValueReceiptError(
                "raw provider result has no unique rederived absence state"
            )
    elif result.row_count > 0:
        expected_presence = "present"
        expected_headers = derived.ordered_headers
        expected_row_count = result.row_count
        expected_cell_count = result.row_count * len(expected_headers)
        expected_node_count = (
            0 if result.container_kind == "nba_api_result_set" else result.row_count
        )
        expected_container_count = present_containers + null_count
        expected_missing_count = missing_count
        expected_null_count = null_count
    elif result.container_kind == "nba_api_result_set":
        expected_presence = "present_empty"
        expected_headers = derived.ordered_headers
        expected_row_count = expected_cell_count = expected_node_count = 0
        expected_container_count = present_containers + null_count
        expected_missing_count = missing_count
        expected_null_count = null_count
    elif (
        result.container_kind in {"nba_api_live_json_array", "nba_api_static_records"}
        and present_containers == 1
        and missing_count == 0
        and null_count == 0
    ):
        expected_presence = "empty_array"
        expected_headers = ()
        expected_row_count = expected_cell_count = 0
        expected_node_count = expected_container_count = 1
        expected_missing_count = expected_null_count = 0
    else:
        expected_presence = "present"
        expected_headers = derived.ordered_headers
        expected_row_count = expected_cell_count = 0
        expected_node_count = present_containers
        expected_container_count = present_containers + null_count
        expected_missing_count = missing_count
        expected_null_count = null_count
    expected_json_path = (
        "$"
        if observation.attempt.source_family == "static" and result.json_path is None
        else result.json_path
    )
    if (
        result.name != occurrence.result_name
        or derived.duplicate_name_ordinal != occurrence.duplicate_name_ordinal
        or result.provider_index != occurrence.provider_result_ordinal
        or result.canonical_index != occurrence.canonical_result_ordinal
        or expected_json_path != occurrence.json_path
        or result.container_kind != occurrence.container_kind
        or expected_presence != occurrence.presence
        or expected_headers != occurrence.ordered_headers()
        or expected_row_count != occurrence.row_count
        or expected_cell_count != occurrence.cell_count
        or expected_node_count != occurrence.node_count
        or expected_container_count != occurrence.container_count
        or expected_missing_count != occurrence.missing_count
        or expected_null_count != occurrence.null_count
        or result.parent_occurrence_states_sha256 != occurrence.parent_state_sha256
        or result.normalized_output_sha256 != occurrence.output_sha256
    ):
        raise TypedFieldValueReceiptError(
            "raw provider result derivation differs from occurrence authority"
        )


def _assert_observation_occurrence_denominators(
    bundle: RawRequestAuthorityBundleV2,
    selected: tuple[tuple[RequestObservationV2, ResultOccurrenceV2], ...],
) -> None:
    observations = {
        observation.attempt.observation_sha256: observation for observation, _item in selected
    }
    for observation in observations.values():
        body = _body_for_observation(bundle, observation)
        parser_input = None if body is None else decode_parser_input_object(body)
        unknown = _rederive_unknown_stats_response(
            observation=observation,
            parser_input=parser_input,
        )
        if unknown is not None:
            rederived_occurrence_count = len(unknown.occurrences)
        else:
            try:
                derivations = rederive_raw_authority_result_sets(
                    source_family=observation.attempt.source_family,
                    endpoint_id=observation.attempt.endpoint_id,
                    parser_input=parser_input,
                    provider_authority_sha256=(observation.attempt.provider_authority_sha256),
                    endpoint_contract_sha256_value=(observation.attempt.endpoint_contract_sha256),
                )
            except (ResponseContractError, TypeError, ValueError) as exc:
                raise TypedFieldValueReceiptError(
                    "raw observation occurrence denominator cannot be rederived by raw authority"
                ) from exc
            rederived_occurrence_count = len(derivations)
        declared = tuple(
            sorted(
                (
                    item
                    for item in bundle.occurrences
                    if item.observation_sha256 == observation.attempt.observation_sha256
                ),
                key=lambda item: item.occurrence_ordinal,
            )
        )
        if len(declared) != rederived_occurrence_count or tuple(
            item.occurrence_ordinal for item in declared
        ) != tuple(range(rederived_occurrence_count)):
            raise TypedFieldValueReceiptError(
                "raw observation occurrence denominator omits decoded provider results"
            )
        for occurrence in declared:
            _assert_rederived_occurrence(
                observation=observation,
                occurrence=occurrence,
                parser_input=parser_input,
            )


def _source_occurrence_authority(
    *,
    bundle: RawRequestAuthorityBundleV2,
    observation: RequestObservationV2,
    occurrence: ResultOccurrenceV2,
) -> SourceOccurrenceAuthorityV2:
    """Copy every inspectable raw occurrence claim into one sealed V2 authority."""

    if occurrence.observation_sha256 != observation.attempt.observation_sha256:
        raise TypedFieldValueReceiptError("source occurrence names a foreign observation")
    try:
        headers = occurrence.ordered_headers()
        route_ids = occurrence.canonical_route_ids()
        staging_receipts = tuple(occurrence.committed_staging_receipts_by_route().items())
    except RawRequestAuthorityError as exc:
        raise TypedFieldValueReceiptError("source occurrence inventory is invalid") from exc
    values: dict[str, object] = {
        "raw_bundle_sha256": bundle.bundle_sha256,
        "observation_sha256": observation.attempt.observation_sha256,
        "occurrence_sha256": occurrence.occurrence_sha256,
        "source_family": observation.attempt.source_family,
        "endpoint_id": observation.attempt.endpoint_id,
        "occurrence_ordinal": occurrence.occurrence_ordinal,
        "result_name": occurrence.result_name,
        "duplicate_name_ordinal": occurrence.duplicate_name_ordinal,
        "provider_result_ordinal": occurrence.provider_result_ordinal,
        "canonical_result_ordinal": occurrence.canonical_result_ordinal,
        "json_path": occurrence.json_path,
        "container_kind": occurrence.container_kind,
        "presence": occurrence.presence,
        "ordered_headers": headers,
        "ordered_headers_sha256": occurrence.ordered_headers_sha256,
        "header_count": occurrence.header_count,
        "row_count": occurrence.row_count,
        "cell_count": occurrence.cell_count,
        "node_count": occurrence.node_count,
        "container_count": occurrence.container_count,
        "missing_count": occurrence.missing_count,
        "null_count": occurrence.null_count,
        "parent_state_sha256": occurrence.parent_state_sha256,
        "output_sha256": occurrence.output_sha256,
        "canonical_route_ids": route_ids,
        "canonical_route_ids_sha256": occurrence.canonical_route_ids_sha256,
        "committed_staging_receipts": staging_receipts,
        "committed_staging_receipts_sha256": (occurrence.committed_staging_receipts_sha256),
        "landing_disposition": occurrence.landing_disposition,
        "logical_result_receipt_sha256": occurrence.logical_result_receipt_sha256,
        "route_receipt_sha256": occurrence.route_receipt_sha256,
    }
    identity = {
        "schema_version": 2,
        "kind": SourceOccurrenceAuthorityV2.kind,
        **{
            key: value
            for key, value in values.items()
            if key
            not in {
                "ordered_headers",
                "canonical_route_ids",
                "committed_staging_receipts",
            }
        },
        "ordered_headers": list(headers),
        "canonical_route_ids": list(route_ids),
        "committed_staging_receipts": [
            {"receipt_sha256": receipt_sha256, "route_id": route_id}
            for route_id, receipt_sha256 in staging_receipts
        ],
    }
    return SourceOccurrenceAuthorityV2(
        **values,
        authority_sha256=canonical_sha256(identity),
    )


def _stats_rows_from_independent_decoder(
    *,
    observation: RequestObservationV2,
    occurrence: ResultOccurrenceV2,
    parser_input: bytes,
) -> _DecodedProviderRows:
    try:
        decoded = decode_stats_value_rows(
            endpoint_id=observation.attempt.endpoint_id,
            endpoint_contract_sha256=observation.attempt.endpoint_contract_sha256,
            provider_authority_sha256=observation.attempt.provider_authority_sha256,
            parser_input=parser_input,
        )
    except IndependentStatsValueDecoderError as exc:
        raise TypedFieldValueReceiptError(
            "raw stats values cannot be decoded by the independent grammar"
        ) from exc
    matches = tuple(
        item
        for item in decoded
        if item.result_name == occurrence.result_name
        and item.duplicate_name_ordinal == occurrence.duplicate_name_ordinal
        and (
            occurrence.provider_result_ordinal is None
            or item.provider_ordinal == occurrence.provider_result_ordinal
        )
        and (
            occurrence.canonical_result_ordinal is None
            or item.canonical_ordinal == occurrence.canonical_result_ordinal
        )
    )
    if len(matches) != 1:
        raise TypedFieldValueReceiptError(
            "raw stats occurrence has no unique independent value result"
        )
    result = matches[0]
    headers = occurrence.ordered_headers()
    rows = result.rows
    if (
        result.ordered_headers != headers
        or result.row_count != occurrence.row_count
        or result.normalized_output_sha256 != occurrence.output_sha256
    ):
        raise TypedFieldValueReceiptError(
            "raw stats independent values differ from occurrence authority"
        )
    return _DecodedProviderRows(
        ordered_headers=headers,
        values=rows,
        records=tuple(None for _row in rows),
    )


_LIVE_MISSING_VALUE = object()


def _decoded_live_node_values(response: DecodedLiveResponseV1) -> tuple[object, ...]:
    """Reconstruct mutation-local JSON values from one validated decoder inventory."""

    values: list[object] = []
    for node in response.nodes:
        if node.presence_kind == "missing":
            value: object = _LIVE_MISSING_VALUE
        elif node.value_kind == "object":
            value = {}
        elif node.value_kind == "array":
            value = []
        else:
            if type(node.canonical_json) is not str:
                raise TypedFieldValueReceiptError(
                    "independent live scalar omitted its canonical JSON value"
                )
            try:
                value = json.loads(
                    node.canonical_json,
                    object_pairs_hook=_reject_duplicates,
                    parse_constant=_reject_constant,
                )
            except TypedFieldValueReceiptError:
                raise
            except (TypeError, ValueError, json.JSONDecodeError) as exc:
                raise TypedFieldValueReceiptError(
                    "independent live scalar has invalid canonical JSON"
                ) from exc
        values.append(value)
        parent_ordinal = node.parent_node_ordinal
        if parent_ordinal is None:
            continue
        if parent_ordinal >= len(values) - 1:
            raise TypedFieldValueReceiptError(
                "independent live node parent is not in strict preorder"
            )
        parent = values[parent_ordinal]
        if type(parent) is dict:
            exact_parent = cast("dict[str, object]", parent)
            if value is _LIVE_MISSING_VALUE:
                continue
            if type(node.object_key) is not str or node.object_key in exact_parent:
                raise TypedFieldValueReceiptError(
                    "independent live object edge is absent or duplicated"
                )
            exact_parent[node.object_key] = value
        elif type(parent) is list:
            if value is _LIVE_MISSING_VALUE or node.array_ordinal != len(parent):
                raise TypedFieldValueReceiptError(
                    "independent live array edge is missing or reordered"
                )
            cast("list[object]", parent).append(value)
        else:
            raise TypedFieldValueReceiptError("independent live node is attached below a scalar")
    return tuple(values)


def _expected_live_node_count(
    summary_presence: str,
    *,
    row_count: int,
    container_count: int,
    null_count: int,
) -> int:
    if summary_presence in {"missing", "not_observed_parent_empty"}:
        return 0
    if summary_presence in {"null", "mixed_absent"}:
        return null_count
    if summary_presence == "empty_array":
        return 1
    return row_count if row_count else container_count


def _live_rows_from_independent_decoder(
    *,
    observation: RequestObservationV2,
    occurrence: ResultOccurrenceV2,
    parser_input: bytes,
) -> _DecodedProviderRows:
    """Recover provider rows from the accepted dependency-pure live decoder."""

    try:
        decoded = validate_decoded_live_response(
            decode_live_value_response(
                parser_input,
                endpoint_id=observation.attempt.endpoint_id,
                endpoint_contract_sha256=observation.attempt.endpoint_contract_sha256,
            )
        )
    except IndependentLiveValueDecoderError as exc:
        raise TypedFieldValueReceiptError(
            "raw live values cannot be independently decoded"
        ) from exc
    if (
        decoded.endpoint_id != observation.attempt.endpoint_id
        or decoded.endpoint_contract_sha256 != observation.attempt.endpoint_contract_sha256
        or decoded.parser_input_length != len(parser_input)
        or decoded.parser_input_sha256 != hashlib.sha256(parser_input).hexdigest()
    ):
        raise TypedFieldValueReceiptError(
            "independent live response is rebound to foreign parser authority"
        )
    summaries = tuple(
        item
        for item in decoded.result_sets
        if item.name == occurrence.result_name
        and item.ordinal == occurrence.canonical_result_ordinal
    )
    if (
        len(summaries) != 1
        or occurrence.provider_result_ordinal is not None
        or occurrence.duplicate_name_ordinal != 0
    ):
        raise TypedFieldValueReceiptError(
            "raw live occurrence has no unique independent result summary"
        )
    summary = summaries[0]
    expected_headers = (
        summary.ordered_headers
        if summary.presence in {"present", "not_observed_parent_empty"}
        else ()
    )
    expected_node_count = _expected_live_node_count(
        summary.presence,
        row_count=summary.row_count,
        container_count=summary.container_count,
        null_count=summary.null_count,
    )
    if (
        summary.json_path != occurrence.json_path
        or summary.container_kind != occurrence.container_kind
        or summary.presence != occurrence.presence
        or expected_headers != occurrence.ordered_headers()
        or summary.row_count != occurrence.row_count
        or summary.value_cell_count != occurrence.cell_count
        or expected_node_count != occurrence.node_count
        or summary.container_count + summary.null_count != occurrence.container_count
        or summary.missing_count != occurrence.missing_count
        or summary.null_count != occurrence.null_count
        or summary.parent_occurrence_states_sha256 != occurrence.parent_state_sha256
        or summary.normalized_output_sha256 != occurrence.output_sha256
        or summary.field_cell_count != summary.value_cell_count
    ):
        raise TypedFieldValueReceiptError(
            "independent live result summary differs from raw occurrence authority"
        )
    concrete_occurrences = tuple(
        item
        for item in decoded.result_occurrences
        if item.result_set_name == summary.name and item.result_set_ordinal == summary.ordinal
    )
    if (
        len(concrete_occurrences) != summary.result_occurrence_count
        or len(concrete_occurrences) != summary.parent_observation_count
        or tuple(item.occurrence_ordinal for item in concrete_occurrences)
        != tuple(range(len(concrete_occurrences)))
        or any(item.container_kind != summary.container_kind for item in concrete_occurrences)
        or sum(item.row_count for item in concrete_occurrences) != summary.row_count
        or sum(item.presence_kind not in {"missing", "null"} for item in concrete_occurrences)
        != summary.container_count
        or sum(item.presence_kind == "missing" for item in concrete_occurrences)
        != summary.missing_count
        or sum(item.presence_kind == "null" for item in concrete_occurrences) != summary.null_count
    ):
        raise TypedFieldValueReceiptError(
            "independent live concrete occurrence denominator is incomplete"
        )
    node_values = _decoded_live_node_values(decoded)
    cells_by_row: dict[tuple[int, int], list[DecodedLiveFieldCellV1]] = {}
    for cell in decoded.field_cells:
        if (
            cell.owner_result_set_name != summary.name
            or cell.owner_result_set_ordinal != summary.ordinal
        ):
            continue
        row_ordinal = cell.owner_row_ordinal
        if row_ordinal is None:
            raise TypedFieldValueReceiptError(
                "independent live field cell omitted its provider row ordinal"
            )
        key = (cell.owner_result_set_occurrence, row_ordinal)
        cells_by_row.setdefault(key, []).append(cell)

    values: list[tuple[object, ...]] = []
    records: list[dict[str, object] | None] = []
    headers = expected_headers
    for concrete in concrete_occurrences:
        root = node_values[concrete.node_ordinal]
        if concrete.presence_kind in {"missing", "null"}:
            if (
                concrete.row_count
                or (concrete.presence_kind == "missing" and root is not _LIVE_MISSING_VALUE)
                or (concrete.presence_kind == "null" and root is not None)
            ):
                raise TypedFieldValueReceiptError(
                    "independent live absent occurrence carries provider rows"
                )
            continue
        if concrete.container_kind == "nba_api_live_json_array":
            if type(root) is not list:
                raise TypedFieldValueReceiptError(
                    "independent live array occurrence has a foreign root"
                )
            raw_rows = tuple(cast("list[object]", root))
        elif concrete.container_kind == "nba_api_live_json_object":
            if type(root) is not dict:
                raise TypedFieldValueReceiptError(
                    "independent live object occurrence has a foreign root"
                )
            raw_rows = (root,)
        else:  # pragma: no cover - decoder contract is closed
            raise TypedFieldValueReceiptError(
                "independent live occurrence container is unsupported"
            )
        if len(raw_rows) != concrete.row_count:
            raise TypedFieldValueReceiptError(
                "independent live concrete row denominator is incomplete"
            )
        for row_ordinal, raw_row in enumerate(raw_rows):
            row_cells = cells_by_row.pop((concrete.occurrence_ordinal, row_ordinal), [])
            row_cells.sort(key=lambda item: item.field_ordinal)
            if (
                tuple(item.field_ordinal for item in row_cells) != tuple(range(len(headers)))
                or tuple(item.field_name for item in row_cells) != headers
            ):
                raise TypedFieldValueReceiptError(
                    "independent live row field-cell denominator is incomplete"
                )
            row_values: list[object] = []
            for cell in row_cells:
                cell_value = node_values[cell.node_ordinal]
                if cell.presence_kind == "missing":
                    if cell_value is not _LIVE_MISSING_VALUE:
                        raise TypedFieldValueReceiptError(
                            "independent live missing cell has a concrete value"
                        )
                    projected: object = None
                else:
                    if cell_value is _LIVE_MISSING_VALUE:
                        raise TypedFieldValueReceiptError(
                            "independent live present cell has no concrete value"
                        )
                    projected = cell_value
                if type(raw_row) is dict:
                    exact_record = cast("dict[str, object]", raw_row)
                    if cell.presence_kind == "missing":
                        if cell.field_name in exact_record:
                            raise TypedFieldValueReceiptError(
                                "independent live missing cell exists in its provider record"
                            )
                    elif cell.field_name not in exact_record or (
                        type(exact_record[cell.field_name]) is not type(projected)
                        or exact_record[cell.field_name] != projected
                    ):
                        raise TypedFieldValueReceiptError(
                            "independent live field cell differs from its provider record"
                        )
                row_values.append(projected)
            values.append(tuple(row_values))
            records.append(cast("dict[str, object]", raw_row) if type(raw_row) is dict else None)
    if cells_by_row:
        raise TypedFieldValueReceiptError("independent live field cells name foreign provider rows")
    if len(values) != occurrence.row_count:
        raise TypedFieldValueReceiptError(
            "independent live rows differ from raw occurrence authority"
        )
    if len(values) != len(records):  # pragma: no cover - construction
        raise TypedFieldValueReceiptError("independent live record denominator is incomplete")
    if any(len(row) != len(headers) for row in values):
        raise TypedFieldValueReceiptError("independent live provider row width is incomplete")
    if (
        occurrence.row_count and not headers and any(values)
    ):  # pragma: no cover - no pinned scalar route has zero headers
        raise TypedFieldValueReceiptError(
            "independent live nonempty result omitted provider headers"
        )
    return _DecodedProviderRows(headers, tuple(values), tuple(records))


def _decoded_provider_rows(
    *,
    bundle: RawRequestAuthorityBundleV2,
    observation: RequestObservationV2,
    occurrence: ResultOccurrenceV2,
) -> _DecodedProviderRows:
    body = _body_for_observation(bundle, observation)
    parser_input = None if body is None else decode_parser_input_object(body)
    _assert_rederived_occurrence(
        observation=observation,
        occurrence=occurrence,
        parser_input=parser_input,
    )
    source_family = observation.attempt.source_family
    if source_family == "static":
        try:
            packet = fetch_static_packet(observation.attempt.endpoint_id)
            packet_rows = tuple(tuple(row) for row in packet.frame.rows())
            packet_bytes = _canonical_json_bytes(
                [list(row) for row in packet_rows],
                maximum_bytes=MAX_ROUTE_CANONICAL_BYTES,
            )
            decoded = decode_static_value_response(
                packet_bytes,
                dataset_id=observation.attempt.endpoint_id,
                endpoint_contract_sha256=observation.attempt.endpoint_contract_sha256,
            )
        except (
            IndependentStaticValueDecoderError,
            ResponseContractError,
            TypeError,
            ValueError,
        ) as exc:
            raise TypedFieldValueReceiptError(
                "static record values cannot be independently decoded from exact pinned authority"
            ) from exc
        headers = tuple(field.name for field in decoded.fields)
        rows: list[tuple[object, ...]] = []
        for record in decoded.records:
            cells = decoded.cells[
                record.cell_start_ordinal : record.cell_start_ordinal + record.cell_count
            ]
            if (
                tuple(cell.record_ordinal for cell in cells)
                != (record.record_ordinal,) * record.cell_count
                or tuple(cell.field_ordinal for cell in cells) != tuple(range(record.cell_count))
                or tuple(cell.field_name for cell in cells) != headers
            ):
                raise TypedFieldValueReceiptError(
                    "independent static record cells do not form one exact ordered row"
                )
            try:
                rows.append(tuple(json.loads(cell.canonical_json) for cell in cells))
            except (TypeError, ValueError, json.JSONDecodeError) as exc:  # pragma: no cover
                raise TypedFieldValueReceiptError(
                    "independent static cell value is not canonical JSON"
                ) from exc
        if (
            decoded.result_name != occurrence.result_name
            or decoded.provider_result_ordinal != occurrence.provider_result_ordinal
            or decoded.canonical_result_ordinal != occurrence.canonical_result_ordinal
            or decoded.container_kind != occurrence.container_kind
            or decoded.normalized_output_sha256 != occurrence.output_sha256
            or headers != occurrence.ordered_headers()
            or decoded.record_count != occurrence.row_count
            or decoded.cell_count != occurrence.cell_count
            or len(rows) != occurrence.row_count
        ):
            raise TypedFieldValueReceiptError("static record values differ from raw authority")
        return _DecodedProviderRows(
            headers,
            tuple(rows),
            tuple(None for _row in rows),
        )
    if parser_input is None:  # pragma: no cover - guarded by _body_for_observation
        raise TypedFieldValueReceiptError("raw provider values omitted parser bytes")
    if source_family == "stats":
        return _stats_rows_from_independent_decoder(
            observation=observation,
            occurrence=occurrence,
            parser_input=parser_input,
        )
    if source_family == "live":
        return _live_rows_from_independent_decoder(
            observation=observation,
            occurrence=occurrence,
            parser_input=parser_input,
        )
    raise TypedFieldValueReceiptError("raw provider source family is unsupported")


def _matching_binding_sources(
    join: RouteLandingFieldJoinV1,
    observation: RequestObservationV2,
    occurrence: ResultOccurrenceV2,
) -> tuple[tuple[RouteFieldBindingV1, ProviderFieldSourceOccurrenceV1], ...]:
    source_by_id = {item.occurrence_id: item for item in join.provider_sources}
    headers = occurrence.ordered_headers()
    result_ordinal = (
        occurrence.canonical_result_ordinal
        if occurrence.canonical_result_ordinal is not None
        else occurrence.provider_result_ordinal
    )
    matches: list[tuple[RouteFieldBindingV1, ProviderFieldSourceOccurrenceV1]] = []
    for binding in join.route_bindings:
        source = source_by_id.get(binding.source_occurrence_id)
        if source is None:
            raise TypedFieldValueReceiptError("field-fate binding omitted its provider source")
        if (
            source.source_family != observation.attempt.source_family
            or source.endpoint_id != observation.attempt.endpoint_id
            or source.result_set_name != occurrence.result_name
            or source.result_set_ordinal != result_ordinal
        ):
            continue
        if (
            source.field_ordinal >= len(headers)
            or headers[source.field_ordinal] != source.provider_field_name
        ):
            raise TypedFieldValueReceiptError(
                "provider header ordinal/name differs from source authority"
            )
        if source.endpoint_contract_sha256 != observation.attempt.endpoint_contract_sha256:
            raise TypedFieldValueReceiptError(
                "source endpoint contract differs from request authority"
            )
        matches.append((binding, source))
    if (
        join.origin not in {"storage_only", "lossless_bound"}
        and occurrence.row_count
        and not matches
    ):
        raise TypedFieldValueReceiptError("provider-bound field has no applicable exact source")
    return tuple(matches)


def _applicable_sources(
    join: RouteLandingFieldJoinV1,
    observation: RequestObservationV2,
    occurrence: ResultOccurrenceV2,
) -> tuple[str, ...]:
    return tuple(
        source.occurrence_sha256
        for _binding, source in _matching_binding_sources(join, observation, occurrence)
    )


def _nested_record_value(
    record: dict[str, object],
    *,
    occurrence_path: str | None,
    source_path: str,
) -> object:
    if type(occurrence_path) is not str or not source_path.startswith(f"{occurrence_path}."):
        raise TypedFieldValueReceiptError("nested projection path escapes its result occurrence")
    value: object = record
    for part in source_path[len(occurrence_path) + 1 :].split("."):
        if not part or type(value) is not dict or part not in value:
            raise TypedFieldValueReceiptError("nested projection path is absent from raw record")
        value = cast("dict[str, object]", value)[part]
    return value


def _project_provider_value(
    join: RouteLandingFieldJoinV1,
    *,
    observation: RequestObservationV2,
    occurrence: ResultOccurrenceV2,
    provider_row: tuple[object, ...],
    provider_record: dict[str, object] | None,
) -> object:
    if join.origin == "storage_only":
        return _USE_COMMITTED_STORAGE_VALUE
    if join.origin == "lossless_bound":
        raise TypedFieldValueReceiptError(
            "lossless route values require exact conditional occurrence authority"
        )
    projected: list[object] = []
    for binding, source in _matching_binding_sources(join, observation, occurrence):
        transform = binding.mapping_transform
        field_ordinal = source.field_ordinal
        if transform in {"identity", "rename"}:
            value = provider_row[field_ordinal]
        elif transform == "list_to_canonical_json":
            try:
                value = json.dumps(
                    provider_row[field_ordinal],
                    separators=(",", ":"),
                    ensure_ascii=False,
                    allow_nan=False,
                )
            except (TypeError, ValueError) as exc:
                raise TypedFieldValueReceiptError(
                    "static list projection is not exact canonical JSON"
                ) from exc
        elif transform == "payload_json_record":
            if provider_record is None:
                raise TypedFieldValueReceiptError("payload JSON projection lacks its raw record")
            value = json.dumps(provider_record, sort_keys=True, default=str)
        elif transform == "nested_projection":
            if provider_record is None:
                raise TypedFieldValueReceiptError("nested projection lacks its raw record")
            value = _nested_record_value(
                provider_record,
                occurrence_path=occurrence.json_path,
                source_path=source.source_path,
            )
        else:
            raise TypedFieldValueReceiptError("field-fate mapping transform is unsupported")
        projected.append(value)
    if not projected:
        raise TypedFieldValueReceiptError("provider field projection has no exact binding")
    first = projected[0]
    if any(value != first or type(value) is not type(first) for value in projected[1:]):
        raise TypedFieldValueReceiptError("multi-bound provider projection is ambiguous")
    return first


def _validate_conditional_input(
    value: object,
    *,
    field_fate: FieldFateStructureV1,
    raw_bundle: RawRequestAuthorityBundleV2,
    readback: CommittedStagingFrameReadbackV2,
) -> ConditionalRouteOccurrenceAuthorityV1:
    """Validate shape-specific denominators without inventing provider rows."""

    if type(value) is not ConditionalRouteOccurrenceAuthorityV1:
        raise TypedFieldValueReceiptError("conditional authority has a foreign concrete type")
    try:
        authority = validate_conditional_route_occurrence_authority(value, structure=field_fate)
    except (FieldFateStructureError, TypeError, ValueError) as exc:
        raise TypedFieldValueReceiptError("conditional occurrence authority is invalid") from exc
    if (
        authority.raw_bundle_sha256 != raw_bundle.bundle_sha256
        or authority.raw_bundle.bundle_sha256 != raw_bundle.bundle_sha256
        or authority.readback_receipt_sha256 != readback.readback_receipt_sha256
        or authority.readback.readback_receipt_sha256 != readback.readback_receipt_sha256
        or authority.readback.canonical_frame_bytes != readback.canonical_frame_bytes
        or authority.route_id != readback.committed_receipt.result_route_id
        or authority.committed_receipt_root_sha256 != readback.committed_receipt.receipt_root_sha256
    ):
        raise TypedFieldValueReceiptError("conditional authority is rebound to foreign roots")
    table = _read_table(readback)
    try:
        joins = field_fate.route_landing_fields(
            authority.route_id,
            table.schema,
            conditional_authority=authority,
        )
    except FieldFateStructureError as exc:
        raise TypedFieldValueReceiptError(
            "conditional storage ordinals differ from field-fate authority"
        ) from exc
    if len(joins) != table.num_columns or tuple(
        join.sink.storage_ordinal for join in joins
    ) != tuple(range(table.num_columns)):
        raise TypedFieldValueReceiptError("conditional storage ordinal denominator is incomplete")

    bindings = authority.stats_bindings
    if authority.source_shape == "selected_result_bound":
        if (
            authority.source_family != "stats"
            or not authority.result_occurrence_sha256s
            or authority.body_object_sha256s
            or len(bindings) != table.num_rows
            or tuple(item.staging_row_ordinal for item in bindings) != tuple(range(table.num_rows))
            or any(
                item.binding_kind != "selected_result_bound"
                or item.source_occurrence_sha256 is None
                or item.body_object_sha256 is not None
                for item in bindings
            )
            or {cast("str", item.source_occurrence_sha256) for item in bindings}
            != set(authority.result_occurrence_sha256s)
        ):
            raise TypedFieldValueReceiptError(
                "selected-result conditional row/binding denominator is incomplete"
            )
    elif authority.source_shape == "body_node_bound":
        if (
            authority.source_family != "stats"
            or authority.result_occurrence_sha256s
            or not authority.body_object_sha256s
            or len(bindings) != table.num_rows
            or tuple(item.staging_row_ordinal for item in bindings) != tuple(range(table.num_rows))
            or any(
                item.binding_kind != "body_node_bound"
                or item.source_occurrence_sha256 is not None
                or item.body_object_sha256 is None
                for item in bindings
            )
            or {cast("str", item.body_object_sha256) for item in bindings}
            != set(authority.body_object_sha256s)
        ):
            raise TypedFieldValueReceiptError(
                "body-node conditional row/binding denominator is incomplete"
            )
    elif authority.source_shape == "hybrid_result_body_bound":
        result_bindings = tuple(
            item for item in bindings if item.binding_kind == "selected_result_bound"
        )
        body_bindings = tuple(item for item in bindings if item.binding_kind == "body_node_bound")
        if (
            authority.source_family != "stats"
            or not authority.result_occurrence_sha256s
            or not authority.body_object_sha256s
            or len(bindings) != table.num_rows
            or tuple(item.staging_row_ordinal for item in bindings) != tuple(range(table.num_rows))
            or not result_bindings
            or not body_bindings
            or any(
                item.source_occurrence_sha256 is None or item.body_object_sha256 is not None
                for item in result_bindings
            )
            or any(
                item.source_occurrence_sha256 is not None or item.body_object_sha256 is None
                for item in body_bindings
            )
            or {cast("str", item.source_occurrence_sha256) for item in result_bindings}
            != set(authority.result_occurrence_sha256s)
            or {cast("str", item.body_object_sha256) for item in body_bindings}
            != set(authority.body_object_sha256s)
        ):
            raise TypedFieldValueReceiptError(
                "hybrid conditional row/binding denominator is incomplete"
            )
    elif authority.source_shape == "live_lossless_bound":
        sink_binding_ids = {
            binding_id for sink in authority.sinks for binding_id in sink.binding_ids
        }
        if (
            authority.source_family != "live"
            or not authority.result_occurrence_sha256s
            or authority.stats_bindings
            or not authority.live_binding_ids
            or sink_binding_ids != set(authority.live_binding_ids)
        ):
            raise TypedFieldValueReceiptError(
                "live-lossless conditional occurrence/binding denominator is incomplete"
            )
    else:  # pragma: no cover - exact Literal/type validator guards this branch
        raise TypedFieldValueReceiptError("conditional source shape is unsupported")
    return authority


def _conditional_decoder_kind(source_shape: ConditionalSourceShape) -> DecoderKind:
    return cast("DecoderKind", _CONDITIONAL_DECODER_BY_SHAPE[source_shape])


def _strict_binding_row(binding: StatsLosslessFieldBindingV1) -> dict[str, object]:
    encoded = binding.row_identity_json.encode("utf-8", errors="strict")
    row = _decode_object(
        encoded,
        maximum_bytes=MAX_CELL_CANONICAL_BYTES,
        maximum_items=MAX_ROUTE_FIELDS * 4,
    )
    if canonical_sha256(row) != binding.row_identity_sha256:
        raise TypedFieldValueReceiptError("conditional binding row identity is invalid")
    return row


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
    raise TypedFieldValueReceiptError("conditional source contains a non-JSON value")


def _json_presence_kind(value: object) -> str:
    if value is None:
        return "null"
    if type(value) is dict and not value:
        return "empty_object"
    if type(value) is list and not value:
        return "empty_array"
    return "present"


def _canonical_json_text(value: object) -> str:
    return _canonical_json_bytes(value, maximum_bytes=MAX_CELL_CANONICAL_BYTES).decode("utf-8")


def _require_row_fields(
    row: dict[str, object],
    expected: dict[str, object],
    *,
    label: str,
) -> None:
    if any(
        key not in row or row[key] != value or type(row[key]) is not type(value)
        for key, value in expected.items()
    ):
        raise TypedFieldValueReceiptError(
            f"{label} differs from independently reconstructed source values"
        )


def _observed_stats_fallback_rows(
    response: DecodedObservedStatsResponseV1,
    *,
    response_receipt_sha256: str,
) -> tuple[dict[str, object], ...]:
    """Project the fixed declared-result fallback solely from decoded raw bytes."""

    reason_payload = _canonical_json_text(list(response.reason_codes))
    base: dict[str, object] = {column: None for column in _SELECTED_STATS_FALLBACK_COLUMNS}
    base.update(
        {
            "response_receipt_sha256": response_receipt_sha256,
            "endpoint_slug": response.endpoint_slug,
            "anomaly_codes_json": reason_payload,
        }
    )
    rows: list[dict[str, object]] = []

    def add_record(
        *,
        result: DecodedObservedStatsResultV1,
        record_kind: str,
        header_name: str | None = None,
        header_ordinal: int | None = None,
        row_ordinal: int | None = None,
        value: object = None,
        has_value: bool = False,
    ) -> None:
        record = dict(base)
        record.update(
            {
                "record_kind": record_kind,
                "result_set_name": result.result_name,
                "result_set_occurrence": result.duplicate_name_ordinal,
                "provider_index": result.provider_ordinal,
                "canonical_index": result.canonical_ordinal,
                "header_name": header_name,
                "header_ordinal": header_ordinal,
                "row_ordinal": row_ordinal,
                "value_kind": _json_value_kind(value) if has_value else None,
                "canonical_json": _canonical_json_text(value) if has_value else None,
            }
        )
        if tuple(record) != _SELECTED_STATS_FALLBACK_COLUMNS:
            raise TypedFieldValueReceiptError(
                "selected conditional fallback projection changed schema order"
            )
        rows.append(record)

    for result in response.results:
        if result.presence == "missing":
            add_record(result=result, record_kind="missing_expected")
            continue
        add_record(result=result, record_kind="result_set")
        header_names = result.effective_header_names
        header_values = result.fallback_header_values
        for header_ordinal, header_value in enumerate(header_values):
            add_record(
                result=result,
                record_kind="header",
                header_name=(
                    header_names[header_ordinal] if header_ordinal < len(header_names) else None
                ),
                header_ordinal=header_ordinal,
                value=header_value,
                has_value=True,
            )
        raw_row_container = result.raw_row_container
        row_occurrences = (
            cast("list[object]", raw_row_container) if type(raw_row_container) is list else []
        )
        for row_ordinal, raw_row in enumerate(row_occurrences):
            add_record(
                result=result,
                record_kind="row",
                row_ordinal=row_ordinal,
                value=raw_row,
                has_value=True,
            )
            if type(raw_row) is not list:
                continue
            for header_ordinal, value in enumerate(cast("list[object]", raw_row)):
                add_record(
                    result=result,
                    record_kind="cell",
                    header_name=(
                        header_names[header_ordinal] if header_ordinal < len(header_names) else None
                    ),
                    header_ordinal=header_ordinal,
                    row_ordinal=row_ordinal,
                    value=value,
                    has_value=True,
                )
    return tuple(rows)


def _observed_unknown_stats_result_rows(
    response: DecodedObservedStatsResponseV1,
    *,
    observation: RequestObservationV2,
    body: ParserInputObjectV2,
    response_receipt_sha256: str,
) -> tuple[dict[str, object], ...]:
    """Project strict unknown-dynamic legacy result rows from exact raw bytes."""

    if response.response_mode != "unknown_dynamic_response":
        raise TypedFieldValueReceiptError(
            "unknown-dynamic conditional projection received a declared response"
        )
    parser_input = decode_parser_input_object(body)
    payload = _decode_raw_json_object(parser_input)
    roots = tuple(name for name in ("resultSets", "resultSet") if name in payload)
    contract = pinned_runtime_contracts().get(observation.attempt.endpoint_id)
    if contract is None:
        raise TypedFieldValueReceiptError("unknown-dynamic endpoint lacks a pinned contract")
    response_contract = contract.response_contract
    if (
        len(roots) != 1
        or response.endpoint_id != observation.attempt.endpoint_id
        or response.endpoint_slug != contract.endpoint_slug
        or response_contract.response_mode != "unknown_dynamic_response"
        or response_contract.endpoint_contract_sha256
        != observation.attempt.endpoint_contract_sha256
        or response.provider_result_set_count != len(response.results)
        or response.expected_result_set_count != 0
        or response.reason_codes != ("unknown_dynamic_response",)
    ):
        raise TypedFieldValueReceiptError(
            "unknown-dynamic conditional response identity differs from exact authority"
        )
    state = (
        "legacy_present_nonempty"
        if any(result.row_count for result in response.results)
        else "legacy_present_empty"
    )
    base: dict[str, object] = {column: None for column in _SELECTED_STATS_FALLBACK_COLUMNS}
    base.update(
        {
            "response_receipt_sha256": response_receipt_sha256,
            "provider_authority_sha256": observation.attempt.provider_authority_sha256,
            "endpoint_contract_sha256": observation.attempt.endpoint_contract_sha256,
            "response_mode_authority_sha256": response_contract.authority_sha256,
            "parser_input_sha256": body.response_sha256,
            "canonical_payload_sha256": hashlib.sha256(canonical_json_bytes(payload)).hexdigest(),
            "parameters_sha256": observation.attempt.safe_parameters_sha256,
            "endpoint_id": response.endpoint_id,
            "endpoint_slug": response.endpoint_slug,
            "response_state": state,
            "legacy_envelope_name": roots[0],
            "anomaly_codes_json": _canonical_json_text(list(response.reason_codes)),
        }
    )
    rows: list[dict[str, object]] = []

    def add_record(
        *,
        result: DecodedObservedStatsResultV1,
        record_kind: str,
        header_name: str | None = None,
        header_ordinal: int | None = None,
        row_ordinal: int | None = None,
        value: object = None,
        has_value: bool = False,
    ) -> None:
        record = dict(base)
        record.update(
            {
                "record_kind": record_kind,
                "result_set_name": result.result_name,
                "result_set_occurrence": result.duplicate_name_ordinal,
                "provider_index": result.provider_ordinal,
                "canonical_index": None,
                "header_name": header_name,
                "header_ordinal": header_ordinal,
                "row_ordinal": row_ordinal,
                "presence_kind": _json_presence_kind(value) if has_value else "present",
                "value_kind": _json_value_kind(value) if has_value else None,
                "canonical_json": _canonical_json_text(value) if has_value else None,
            }
        )
        if tuple(record) != _SELECTED_STATS_FALLBACK_COLUMNS:
            raise TypedFieldValueReceiptError(
                "unknown-dynamic conditional projection changed schema order"
            )
        rows.append(record)

    for result in response.results:
        if (
            result.response_mode != "unknown_dynamic_response"
            or result.provider_ordinal is None
            or result.canonical_ordinal is not None
            or result.presence == "missing"
        ):
            raise TypedFieldValueReceiptError(
                "unknown-dynamic conditional result invented a declared identity"
            )
        add_record(result=result, record_kind="result_set")
        for header_ordinal, header_name in enumerate(result.ordered_headers):
            add_record(
                result=result,
                record_kind="header",
                header_name=header_name,
                header_ordinal=header_ordinal,
                value=header_name,
                has_value=True,
            )
        raw_rows = result.raw_row_container
        if type(raw_rows) is not list:
            raise TypedFieldValueReceiptError(
                "unknown-dynamic conditional result rows are not an exact array"
            )
        for row_ordinal, raw_row in enumerate(cast("list[object]", raw_rows)):
            if type(raw_row) is not list:
                raise TypedFieldValueReceiptError(
                    "unknown-dynamic conditional result contains a non-array row"
                )
            row = cast("list[object]", raw_row)
            add_record(
                result=result,
                record_kind="row",
                row_ordinal=row_ordinal,
                value=row,
                has_value=True,
            )
            for header_ordinal, value in enumerate(row):
                add_record(
                    result=result,
                    record_kind="cell",
                    header_name=result.ordered_headers[header_ordinal],
                    header_ordinal=header_ordinal,
                    row_ordinal=row_ordinal,
                    value=value,
                    has_value=True,
                )
    return tuple(rows)


def _stats_binding_source_rows(
    authority: ConditionalRouteOccurrenceAuthorityV1,
    bundle: RawRequestAuthorityBundleV2,
    *,
    bindings: tuple[StatsLosslessFieldBindingV1, ...] | None = None,
) -> tuple[
    tuple[dict[str, object], ...],
    dict[str, DecodedObservedStatsResponseV1],
]:
    """Replay the complete declared-result fallback from exact parser bytes."""

    observation_by_sha = {item.attempt.observation_sha256: item for item in bundle.observations}
    occurrence_by_sha = {item.occurrence_sha256: item for item in bundle.occurrences}
    decoded_by_observation: dict[str, DecodedObservedStatsResponseV1] = {}
    projected_by_observation: dict[str, tuple[dict[str, object], ...]] = {}
    table_columns = tuple(_read_table(authority.readback).schema.names)
    if table_columns != _SELECTED_STATS_FALLBACK_COLUMNS:
        raise TypedFieldValueReceiptError("conditional stats readback has a foreign fixed schema")
    exact_bindings = authority.stats_bindings if bindings is None else bindings
    binding_ordinals = tuple(binding.staging_row_ordinal for binding in exact_bindings)
    if (
        not exact_bindings
        or any(binding.binding_kind != "selected_result_bound" for binding in exact_bindings)
        or binding_ordinals != tuple(sorted(set(binding_ordinals)))
        or (bindings is None and binding_ordinals != tuple(range(len(exact_bindings))))
    ):
        raise TypedFieldValueReceiptError("selected conditional binding order is incomplete")
    rows: list[dict[str, object]] = []
    for binding in exact_bindings:
        row = _strict_binding_row(binding)
        if set(row) != set(_SELECTED_STATS_FALLBACK_COLUMNS):
            raise TypedFieldValueReceiptError(
                "conditional stats binding row has a foreign storage schema"
            )
        observation = observation_by_sha.get(binding.observation_sha256)
        if (
            observation is None
            or observation.observation_record_sha256 != binding.observation_record_sha256
            or observation.capture_response_receipt_sha256 != binding.response_receipt_sha256
        ):
            raise TypedFieldValueReceiptError(
                "conditional stats binding names a foreign observation"
            )
        occurrence_sha = binding.source_occurrence_sha256
        occurrence = occurrence_by_sha.get(occurrence_sha) if occurrence_sha is not None else None
        if (
            occurrence is None
            or occurrence.observation_sha256 != binding.observation_sha256
            or occurrence_sha not in authority.result_occurrence_sha256s
        ):
            raise TypedFieldValueReceiptError(
                "selected conditional binding names a foreign result occurrence"
            )
        decoded_response = decoded_by_observation.get(binding.observation_sha256)
        if decoded_response is None:
            body = _body_for_observation(bundle, observation)
            if body is None:
                raise TypedFieldValueReceiptError(
                    "selected conditional observation omitted parser bytes"
                )
            try:
                decoded_response = decode_observed_lossless_stats_response(
                    endpoint_id=observation.attempt.endpoint_id,
                    endpoint_contract_sha256=(observation.attempt.endpoint_contract_sha256),
                    provider_authority_sha256=(observation.attempt.provider_authority_sha256),
                    parser_input=decode_parser_input_object(body),
                )
            except IndependentStatsValueDecoderError as exc:
                raise TypedFieldValueReceiptError(
                    "selected conditional lossless values cannot be independently decoded"
                ) from exc
            if decoded_response.endpoint_id != observation.attempt.endpoint_id:
                raise TypedFieldValueReceiptError(
                    "selected conditional decoded endpoint identity is rebound"
                )
            decoded_by_observation[binding.observation_sha256] = decoded_response
            projected_by_observation[binding.observation_sha256] = (
                _observed_unknown_stats_result_rows(
                    decoded_response,
                    observation=observation,
                    body=body,
                    response_receipt_sha256=binding.response_receipt_sha256,
                )
                if decoded_response.response_mode == "unknown_dynamic_response"
                else _observed_stats_fallback_rows(
                    decoded_response,
                    response_receipt_sha256=binding.response_receipt_sha256,
                )
            )
        matches = tuple(
            item
            for item in decoded_response.results
            if item.result_name == occurrence.result_name
            and item.duplicate_name_ordinal == occurrence.duplicate_name_ordinal
            and item.provider_ordinal == occurrence.provider_result_ordinal
            and (
                occurrence.provider_result_ordinal is not None
                or item.canonical_ordinal == binding.canonical_index
            )
        )
        if len(matches) != 1:
            raise TypedFieldValueReceiptError(
                "selected conditional result decoder join is ambiguous"
            )
        decoded_result = matches[0]
        occurrence_headers = occurrence.ordered_headers()
        expected_presence = (
            "missing"
            if occurrence.presence == "missing"
            else "present_empty"
            if occurrence.presence == "present_empty"
            else "present"
        )
        if (
            decoded_result.presence != expected_presence
            or (occurrence.presence == "missing" and occurrence_headers != ())
            or (
                occurrence.presence != "missing"
                and bool(occurrence_headers)
                and decoded_result.ordered_headers != occurrence_headers
            )
            or decoded_result.row_count != occurrence.row_count
            or decoded_result.normalized_output_sha256 != occurrence.output_sha256
        ):
            raise TypedFieldValueReceiptError(
                "selected conditional observed result differs from occurrence authority"
            )
        rows.append(row)
    if len(decoded_by_observation) != 1:
        raise TypedFieldValueReceiptError(
            "selected conditional fallback spans response observations"
        )
    only_observation = next(iter(decoded_by_observation))
    if tuple(rows) != projected_by_observation[only_observation]:
        raise TypedFieldValueReceiptError(
            "selected conditional binding inventory omits decoded fallback rows"
        )
    return tuple(rows), decoded_by_observation


def _body_node_source_rows(
    authority: ConditionalRouteOccurrenceAuthorityV1,
    bundle: RawRequestAuthorityBundleV2,
    *,
    bindings: tuple[StatsLosslessFieldBindingV1, ...] | None = None,
) -> tuple[dict[str, object], ...]:
    """Independently replay unknown-dynamic JSON nodes from exact parser bytes."""

    exact_bindings = authority.stats_bindings if bindings is None else bindings
    binding_ordinals = tuple(binding.staging_row_ordinal for binding in exact_bindings)
    if (
        not exact_bindings
        or any(binding.binding_kind != "body_node_bound" for binding in exact_bindings)
        or binding_ordinals != tuple(sorted(set(binding_ordinals)))
        or (bindings is None and binding_ordinals != tuple(range(len(exact_bindings))))
    ):
        raise TypedFieldValueReceiptError("body-node conditional binding order is incomplete")
    rows = tuple(_strict_binding_row(binding) for binding in exact_bindings)
    if not rows:  # pragma: no cover - exact binding guard above
        raise TypedFieldValueReceiptError("body-node conditional row partition is empty")
    binding = exact_bindings[0]
    observation = next(
        (
            item
            for item in bundle.observations
            if item.attempt.observation_sha256 == binding.observation_sha256
        ),
        None,
    )
    body = next(
        (item for item in bundle.objects if item.object_sha256 == binding.body_object_sha256),
        None,
    )
    if (
        observation is None
        or body is None
        or observation.observation_record_sha256 != binding.observation_record_sha256
        or observation.body_object_sha256 != body.object_sha256
        or observation.capture_response_receipt_sha256 != authority.response_receipt_sha256
    ):
        raise TypedFieldValueReceiptError("body-node conditional source identity is foreign")
    raw_payload = _decode_raw_json_object(decode_parser_input_object(body))
    canonical_payload = canonical_json_bytes(raw_payload)
    payload = _decode_raw_json_object(canonical_payload)
    payload_sha256 = hashlib.sha256(canonical_payload).hexdigest()
    identity = {
        "response_receipt_sha256": authority.response_receipt_sha256,
        "provider_authority_sha256": authority.provider_authority_sha256,
        "endpoint_contract_sha256": authority.endpoint_contract_sha256,
        "parser_input_sha256": body.response_sha256,
        "canonical_payload_sha256": payload_sha256,
        "parameters_sha256": observation.attempt.safe_parameters_sha256,
        "endpoint_id": observation.attempt.endpoint_id,
    }
    if any(
        any(
            row.get(key) != value or type(row.get(key)) is not type(value)
            for key, value in identity.items()
        )
        for row in rows
    ):
        raise TypedFieldValueReceiptError(
            "body-node conditional metadata differs from raw authority"
        )
    uniform_columns = (
        "response_mode_authority_sha256",
        "endpoint_slug",
        "response_state",
        "legacy_envelope_name",
        "anomaly_codes_json",
    )
    if any(len({row[name] for row in rows}) != 1 for name in uniform_columns):
        raise TypedFieldValueReceiptError("body-node conditional metadata is not uniform")

    expected_selectors: list[dict[str, object]] = [
        {
            "record_kind": "response",
            "result_set_name": None,
            "result_set_occurrence": None,
            "provider_index": None,
            "canonical_index": None,
            "header_name": None,
            "header_ordinal": None,
            "row_ordinal": None,
            "node_ordinal": None,
            "parent_node_ordinal": None,
            "json_path": None,
            "parent_json_path": None,
            "depth": None,
            "object_key": None,
            "object_key_ordinal": None,
            "array_ordinal": None,
            "presence_kind": None,
            "value_kind": None,
            "canonical_json": None,
        }
    ]
    node_count = 0

    def visit(
        value: object,
        *,
        path_tokens: tuple[str | int, ...],
        parent_node_ordinal: int | None,
        object_key: str | None,
        object_key_ordinal: int | None,
        array_ordinal: int | None,
    ) -> None:
        nonlocal node_count
        ordinal = node_count
        node_count += 1
        value_kind = _json_value_kind(value)
        presence_kind = _json_presence_kind(value)

        def path(tokens: tuple[str | int, ...]) -> str:
            result = "$"
            for token in tokens:
                result += f"[{token}]" if type(token) is int else f"[{_canonical_json_text(token)}]"
            return result

        expected_selectors.append(
            {
                "record_kind": "json_node",
                "result_set_name": None,
                "result_set_occurrence": None,
                "provider_index": None,
                "canonical_index": None,
                "header_name": None,
                "header_ordinal": None,
                "row_ordinal": None,
                "node_ordinal": ordinal,
                "parent_node_ordinal": parent_node_ordinal,
                "json_path": path(path_tokens),
                "parent_json_path": path(path_tokens[:-1]) if path_tokens else None,
                "depth": len(path_tokens),
                "object_key": object_key,
                "object_key_ordinal": object_key_ordinal,
                "array_ordinal": array_ordinal,
                "presence_kind": presence_kind,
                "value_kind": value_kind,
                "canonical_json": (
                    _canonical_json_text(value)
                    if value_kind not in {"object", "array"} or presence_kind != "present"
                    else None
                ),
            }
        )
        if type(value) is dict:
            for child_ordinal, key in enumerate(cast("dict[str, object]", value)):
                visit(
                    cast("dict[str, object]", value)[key],
                    path_tokens=(*path_tokens, key),
                    parent_node_ordinal=ordinal,
                    object_key=key,
                    object_key_ordinal=child_ordinal,
                    array_ordinal=None,
                )
        elif type(value) is list:
            for child_ordinal, child in enumerate(cast("list[object]", value)):
                visit(
                    child,
                    path_tokens=(*path_tokens, child_ordinal),
                    parent_node_ordinal=ordinal,
                    object_key=None,
                    object_key_ordinal=None,
                    array_ordinal=child_ordinal,
                )

    visit(
        payload,
        path_tokens=(),
        parent_node_ordinal=None,
        object_key=None,
        object_key_ordinal=None,
        array_ordinal=None,
    )
    if len(rows) != len(expected_selectors):
        raise TypedFieldValueReceiptError(
            "body-node conditional row denominator differs from raw payload"
        )
    for row, expected in zip(rows, expected_selectors, strict=True):
        _require_row_fields(row, expected, label="body-node conditional row")
    return rows


def _hybrid_stats_source_rows(
    authority: ConditionalRouteOccurrenceAuthorityV1,
    bundle: RawRequestAuthorityBundleV2,
) -> tuple[
    tuple[dict[str, object], ...],
    dict[str, DecodedObservedStatsResponseV1],
]:
    """Replay one exact mixed result/body conditional partition by row authority."""

    selected_bindings = tuple(
        item for item in authority.stats_bindings if item.binding_kind == "selected_result_bound"
    )
    body_bindings = tuple(
        item for item in authority.stats_bindings if item.binding_kind == "body_node_bound"
    )
    selected_rows, observed_responses = _stats_binding_source_rows(
        authority,
        bundle,
        bindings=selected_bindings,
    )
    body_rows = _body_node_source_rows(
        authority,
        bundle,
        bindings=body_bindings,
    )
    rows_by_ordinal = {
        **{
            binding.staging_row_ordinal: row
            for binding, row in zip(selected_bindings, selected_rows, strict=True)
        },
        **{
            binding.staging_row_ordinal: row
            for binding, row in zip(body_bindings, body_rows, strict=True)
        },
    }
    if len(rows_by_ordinal) != len(authority.stats_bindings) or set(rows_by_ordinal) != set(
        range(len(authority.stats_bindings))
    ):
        raise TypedFieldValueReceiptError(
            "hybrid conditional source rows do not form one exact partition"
        )
    return (
        tuple(rows_by_ordinal[ordinal] for ordinal in range(len(rows_by_ordinal))),
        observed_responses,
    )


def _live_source_rows(
    authority: ConditionalRouteOccurrenceAuthorityV1,
    bundle: RawRequestAuthorityBundleV2,
    table: pa.Table,
) -> tuple[dict[str, object], ...]:
    """Independently project live nodes from the pinned contract and exact body."""

    occurrences = tuple(
        item
        for item in bundle.occurrences
        if item.occurrence_sha256 in authority.result_occurrence_sha256s
    )
    if {item.occurrence_sha256 for item in occurrences} != set(authority.result_occurrence_sha256s):
        raise TypedFieldValueReceiptError(
            "live conditional result occurrence denominator is incomplete"
        )
    observation_ids = {item.observation_sha256 for item in occurrences}
    if len(observation_ids) != 1:
        raise TypedFieldValueReceiptError("live conditional result observations are ambiguous")
    observation = next(
        (
            item
            for item in bundle.observations
            if item.attempt.observation_sha256 == next(iter(observation_ids))
        ),
        None,
    )
    if observation is None or observation.body_object_sha256 is None:
        raise TypedFieldValueReceiptError("live conditional observation omitted its body")
    body = next(
        (item for item in bundle.objects if item.object_sha256 == observation.body_object_sha256),
        None,
    )
    if (
        body is None
        or observation.capture_response_receipt_sha256 != authority.response_receipt_sha256
        or observation.attempt.provider_authority_sha256 != authority.provider_authority_sha256
        or observation.attempt.endpoint_contract_sha256 != authority.endpoint_contract_sha256
    ):
        raise TypedFieldValueReceiptError("live conditional observation identity is foreign")
    payload = _decode_raw_json_object(decode_parser_input_object(body))
    contract = pinned_live_contracts().get(observation.attempt.endpoint_id)
    if (
        contract is None
        or contract.contract_sha256 != authority.endpoint_contract_sha256
        or contract.endpoint_id != observation.attempt.endpoint_id
    ):
        raise TypedFieldValueReceiptError("live conditional pinned contract is foreign")
    observed_rows = tuple(cast("dict[str, object]", item) for item in table.to_pylist())
    if not observed_rows:
        raise TypedFieldValueReceiptError("live conditional committed row partition is empty")
    uniform_names = (
        "response_receipt_sha256",
        "provider_authority_sha256",
        "endpoint_contract_sha256",
        "endpoint_id",
        "endpoint_slug",
        "request_parameters_json",
        "snapshot_at",
        "snapshot_date",
        "anomaly_codes_json",
    )
    metadata = {name: observed_rows[0][name] for name in uniform_names}
    if any(any(row[name] != metadata[name] for name in uniform_names) for row in observed_rows):
        raise TypedFieldValueReceiptError("live conditional metadata is not uniform")
    expected_identity = {
        "response_receipt_sha256": authority.response_receipt_sha256,
        "provider_authority_sha256": authority.provider_authority_sha256,
        "endpoint_contract_sha256": authority.endpoint_contract_sha256,
        "endpoint_id": observation.attempt.endpoint_id,
        "endpoint_slug": contract.endpoint_slug,
        "request_parameters_json": observation.attempt.safe_parameters_json,
    }
    if any(metadata[name] != value for name, value in expected_identity.items()):
        raise TypedFieldValueReceiptError("live conditional metadata differs from raw authority")
    snapshot = metadata["snapshot_at"]
    if type(snapshot) is not datetime or metadata["snapshot_date"] != snapshot.date():
        raise TypedFieldValueReceiptError("live conditional snapshot identity is invalid")
    try:
        anomalies = json.loads(cast("str", metadata["anomaly_codes_json"]))
    except (TypeError, ValueError, json.JSONDecodeError) as exc:
        raise TypedFieldValueReceiptError("live conditional anomaly identity is invalid") from exc
    if (
        type(anomalies) is not list
        or anomalies != sorted(set(anomalies))
        or any(type(item) is not str or not item for item in anomalies)
        or _canonical_json_text(anomalies) != metadata["anomaly_codes_json"]
    ):
        raise TypedFieldValueReceiptError("live conditional anomaly identity is invalid")

    result_sets = tuple(sorted(contract.result_sets, key=lambda item: item.ordinal))
    if tuple(item.ordinal for item in result_sets) != tuple(range(len(result_sets))):
        raise TypedFieldValueReceiptError("live conditional result contracts are reordered")

    def base_row(
        record_kind: str,
        *,
        result_set: LiveResultSetContract | None = None,
        presence_kind: str,
        container_kind: str | None = None,
    ) -> dict[str, object]:
        return {
            **metadata,
            "record_kind": record_kind,
            "result_set_name": None if result_set is None else result_set.name,
            "result_set_ordinal": None if result_set is None else result_set.ordinal,
            "result_set_occurrence": None,
            "result_set_row_ordinal": None,
            "contract_json_path": None if result_set is None else result_set.json_path,
            "container_kind": container_kind,
            "node_ordinal": None,
            "parent_node_ordinal": None,
            "json_path": None,
            "parent_json_path": None,
            "depth": None,
            "object_key": None,
            "object_key_ordinal": None,
            "contract_field_ordinal": None,
            "array_ordinal": None,
            "presence_kind": presence_kind,
            "value_kind": None,
            "canonical_json": None,
            "known_contract_field": None,
        }

    expected_rows: list[dict[str, object]] = [
        base_row(
            "result_set_declaration",
            result_set=result_set,
            presence_kind="declared",
            container_kind=result_set.container_kind,
        )
        for result_set in result_sets
    ]
    occurrences_by_name: dict[str, int] = {}
    node_count = 0

    def matching_result_set(
        tokens: tuple[str | int, ...],
    ) -> LiveResultSetContract | None:
        matches = tuple(
            result_set
            for result_set in result_sets
            if len(result_set.traversal_path) == len(tokens)
            and all(
                (expected == "*" and type(actual) is int) or expected == actual
                for expected, actual in zip(result_set.traversal_path, tokens, strict=True)
            )
        )
        if len(matches) > 1:
            raise TypedFieldValueReceiptError(
                "live conditional JSON path matches multiple result contracts"
            )
        return matches[0] if matches else None

    def live_path(tokens: tuple[str | int, ...]) -> str:
        path = "$"
        for token in tokens:
            path += f"[{token}]" if type(token) is int else f"[{_canonical_json_text(token)}]"
        return path

    def visit_missing(
        *,
        tokens: tuple[str | int, ...],
        parent_node_ordinal: int,
        object_key: str,
        context: tuple[LiveResultSetContract, int, int | None] | None,
        record_contract: LiveResultSetContract,
        field_ordinal: int,
    ) -> None:
        nonlocal node_count
        matched = matching_result_set(tokens)
        if matched is None:
            active_context = context
        else:
            name = matched.name
            occurrence = occurrences_by_name.get(name, 0)
            occurrences_by_name[name] = occurrence + 1
            active_context = (matched, occurrence, None)
        ordinal = node_count
        node_count += 1
        result_set = active_context[0] if active_context is not None else None
        row = base_row(
            "json_node",
            result_set=result_set,
            presence_kind="missing",
            container_kind=(matched.container_kind if matched is not None else None),
        )
        row.update(
            {
                "result_set_occurrence": (
                    active_context[1] if active_context is not None else None
                ),
                "result_set_row_ordinal": (
                    active_context[2] if active_context is not None else None
                ),
                "node_ordinal": ordinal,
                "parent_node_ordinal": parent_node_ordinal,
                "json_path": live_path(tokens),
                "parent_json_path": live_path(tokens[:-1]),
                "depth": len(tokens),
                "object_key": object_key,
                "object_key_ordinal": None,
                "contract_field_ordinal": field_ordinal,
                "array_ordinal": None,
                "value_kind": "missing",
                "canonical_json": None,
                "known_contract_field": True,
            }
        )
        expected_rows.append(row)

    def visit(
        value: object,
        *,
        tokens: tuple[str | int, ...],
        parent_node_ordinal: int | None,
        object_key: str | None,
        object_key_ordinal: int | None,
        array_ordinal: int | None,
        inherited_context: tuple[LiveResultSetContract, int, int | None] | None,
        record_contract: LiveResultSetContract | None,
    ) -> None:
        nonlocal node_count
        matched = matching_result_set(tokens)
        if matched is None:
            context = inherited_context
        else:
            name = matched.name
            occurrence = occurrences_by_name.get(name, 0)
            occurrences_by_name[name] = occurrence + 1
            context = (matched, occurrence, 0 if type(value) is dict else None)
        value_kind = _json_value_kind(value)
        ordinal = node_count
        node_count += 1
        field_ordinal: int | None = None
        known_field: bool | None = None
        if object_key is not None and record_contract is not None:
            fields = {field.name: field.ordinal for field in record_contract.fields}
            child_fields = {
                item.parent_field_name
                for item in result_sets
                if item.parent_result_set_name == record_contract.name
                and item.parent_field_name is not None
            }
            field_ordinal = fields.get(object_key)
            known_field = object_key in fields or object_key in child_fields
        presence_kind = _json_presence_kind(value)
        canonical_json = (
            _canonical_json_text(value)
            if value_kind not in {"object", "array"} or presence_kind != "present"
            else None
        )
        result_set = context[0] if context is not None else None
        row = base_row(
            "json_node",
            result_set=result_set,
            presence_kind=presence_kind,
            container_kind=(matched.container_kind if matched is not None else None),
        )
        row.update(
            {
                "result_set_occurrence": context[1] if context is not None else None,
                "result_set_row_ordinal": context[2] if context is not None else None,
                "node_ordinal": ordinal,
                "parent_node_ordinal": parent_node_ordinal,
                "json_path": live_path(tokens),
                "parent_json_path": live_path(tokens[:-1]) if tokens else None,
                "depth": len(tokens),
                "object_key": object_key,
                "object_key_ordinal": object_key_ordinal,
                "contract_field_ordinal": field_ordinal,
                "array_ordinal": array_ordinal,
                "value_kind": value_kind,
                "canonical_json": canonical_json,
                "known_contract_field": known_field,
            }
        )
        expected_rows.append(row)
        if type(value) is dict:
            active_record = (
                matched
                if matched is not None and matched.container_kind == "nba_api_live_json_object"
                else record_contract
            )
            exact = cast("dict[str, object]", value)
            for child_ordinal, (key, child) in enumerate(exact.items()):
                visit(
                    child,
                    tokens=(*tokens, key),
                    parent_node_ordinal=ordinal,
                    object_key=key,
                    object_key_ordinal=child_ordinal,
                    array_ordinal=None,
                    inherited_context=context,
                    record_contract=active_record,
                )
            if active_record is not None:
                for field in active_record.fields:
                    if field.name not in exact:
                        visit_missing(
                            tokens=(*tokens, field.name),
                            parent_node_ordinal=ordinal,
                            object_key=field.name,
                            context=context,
                            record_contract=active_record,
                            field_ordinal=field.ordinal,
                        )
        elif type(value) is list:
            item_record = (
                matched
                if matched is not None and matched.container_kind == "nba_api_live_json_array"
                else None
            )
            for child_ordinal, child in enumerate(cast("list[object]", value)):
                child_context = context
                if context is not None and item_record is not None:
                    child_context = (context[0], context[1], child_ordinal)
                visit(
                    child,
                    tokens=(*tokens, child_ordinal),
                    parent_node_ordinal=ordinal,
                    object_key=None,
                    object_key_ordinal=None,
                    array_ordinal=child_ordinal,
                    inherited_context=child_context,
                    record_contract=item_record,
                )

    visit(
        payload,
        tokens=(),
        parent_node_ordinal=None,
        object_key=None,
        object_key_ordinal=None,
        array_ordinal=None,
        inherited_context=None,
        record_contract=None,
    )
    if len(expected_rows) != len(observed_rows):
        raise TypedFieldValueReceiptError(
            "live conditional row denominator differs from exact body"
        )
    for observed, expected in zip(observed_rows, expected_rows, strict=True):
        if observed != expected:
            raise TypedFieldValueReceiptError(
                "live conditional committed values differ from independent body replay"
            )
    return tuple(expected_rows)


def _default_limits() -> ValueBudgetLimits:
    return ValueBudgetLimits(
        max_nodes=MAX_ROUTE_VALUE_NODES,
        max_depth=MAX_JSON_DEPTH,
        max_utf8_bytes=MAX_ROUTE_VALUE_BYTES,
        max_binary_bytes=MAX_ROUTE_BINARY_BYTES,
        max_container_items=MAX_ROUTE_CONTAINER_ITEMS,
        max_canonical_bytes=MAX_ROUTE_VALUE_BYTES,
    )


@dataclass(frozen=True, slots=True)
class RouteFieldLandingReceiptV2:
    canonical_frame_format: str
    frame_content_hash_contract: str
    frame_schema_hash_contract: str
    readback_receipt_sha256: str
    receipt_root_sha256: str
    raw_bundle_sha256: str
    field_fate_structure_sha256: str
    route_id: str
    staging_key: str
    source_family: SourceFamily
    decoder_kind: DecoderKind
    source_shape: RouteSourceShape
    endpoint_id: str
    conditional_authority_sha256: str | None
    row_partition_receipt_sha256: str
    row_count: int
    occurrence_partition_count: int
    selected_occurrence_count: int
    field_count: int
    cell_count: int
    source_verified_cell_count: int
    storage_readback_only_cell_count: int
    field_authorities: tuple[LandingFieldAuthorityV2, ...]
    occurrence_authorities: tuple[OccurrenceLandingAuthorityV2, ...]
    selected_occurrence_authorities: tuple[SourceOccurrenceAuthorityV2, ...]
    value_receipts: tuple[TypedFieldValueReceiptV2, ...]
    conditional_row_receipts: tuple[ConditionalRowValueReceiptV2, ...]
    selected_occurrence_sha256s: tuple[str, ...]
    row_slice_receipt_sha256s: tuple[str, ...]
    value_node_count: int
    value_max_depth: int
    value_utf8_bytes: int
    value_binary_bytes: int
    value_container_items: int
    value_canonical_bytes: int
    fields_sha256: str
    occurrences_sha256: str
    selected_occurrences_sha256: str
    values_sha256: str
    conditional_rows_sha256: str
    landing_receipt_sha256: str

    schema_version: ClassVar[int] = 2
    kind: ClassVar[str] = "route_field_landing_receipt_v2"

    def __post_init__(self) -> None:
        if (
            self.canonical_frame_format != CANONICAL_FRAME_FORMAT
            or self.frame_content_hash_contract != FRAME_CONTENT_HASH_CONTRACT
            or self.frame_schema_hash_contract != FRAME_SCHEMA_HASH_CONTRACT
        ):
            raise TypedFieldValueReceiptError("stale Arrow contracts require a fresh full restart")
        for name in (
            "readback_receipt_sha256",
            "receipt_root_sha256",
            "raw_bundle_sha256",
            "field_fate_structure_sha256",
            "row_partition_receipt_sha256",
            "fields_sha256",
            "occurrences_sha256",
            "selected_occurrences_sha256",
            "values_sha256",
            "conditional_rows_sha256",
            "landing_receipt_sha256",
        ):
            _sha256(getattr(self, name), field_name=name)
        _text(self.route_id, field_name="route_id")
        _text(self.staging_key, field_name="staging_key")
        if self.source_shape in {"result_occurrence_bound", "response_fixed_zero"}:
            expected_decoder = (
                _DECODER_BY_SOURCE.get(self.source_family)
                if self.source_shape == "result_occurrence_bound"
                else "response_fixed_zero_v2"
            )
            if (
                self.source_family not in _DECODER_BY_SOURCE
                or self.decoder_kind != expected_decoder
                or self.conditional_authority_sha256 is not None
            ):
                raise TypedFieldValueReceiptError("route decoder relabels its source family")
        else:
            _optional_sha256(
                self.conditional_authority_sha256,
                field_name="conditional_authority_sha256",
            )
            expected_family = "live" if self.source_shape == "live_lossless_bound" else "stats"
            if (
                self.conditional_authority_sha256 is None
                or self.source_family != expected_family
                or self.decoder_kind != _CONDITIONAL_DECODER_BY_SHAPE.get(self.source_shape)
            ):
                raise TypedFieldValueReceiptError("conditional route decoder is rebound")
        _text(self.endpoint_id, field_name="endpoint_id")
        _integer(self.row_count, field_name="row_count", maximum=MAX_ROUTE_ROWS)
        _integer(
            self.occurrence_partition_count,
            field_name="occurrence_partition_count",
            maximum=MAX_ROUTE_OCCURRENCES,
        )
        _integer(
            self.selected_occurrence_count,
            field_name="selected_occurrence_count",
            maximum=MAX_ROUTE_OCCURRENCES,
        )
        _integer(self.field_count, field_name="field_count", maximum=MAX_ROUTE_FIELDS)
        _integer(self.cell_count, field_name="cell_count", maximum=MAX_ROUTE_CELLS)
        _integer(
            self.source_verified_cell_count,
            field_name="source_verified_cell_count",
            maximum=MAX_ROUTE_CELLS,
        )
        _integer(
            self.storage_readback_only_cell_count,
            field_name="storage_readback_only_cell_count",
            maximum=MAX_ROUTE_CELLS,
        )
        if (
            self.source_verified_cell_count + self.storage_readback_only_cell_count
            != self.cell_count
        ):
            raise TypedFieldValueReceiptError("route value-authority denominator is invalid")
        _integer(
            self.value_node_count,
            field_name="value_node_count",
            maximum=MAX_ROUTE_VALUE_NODES,
        )
        _integer(
            self.value_max_depth,
            field_name="value_max_depth",
            maximum=MAX_JSON_DEPTH,
        )
        _integer(
            self.value_utf8_bytes,
            field_name="value_utf8_bytes",
            maximum=MAX_ROUTE_VALUE_BYTES,
        )
        _integer(
            self.value_binary_bytes,
            field_name="value_binary_bytes",
            maximum=MAX_ROUTE_BINARY_BYTES,
        )
        _integer(
            self.value_container_items,
            field_name="value_container_items",
            maximum=MAX_ROUTE_CONTAINER_ITEMS,
        )
        _integer(
            self.value_canonical_bytes,
            field_name="value_canonical_bytes",
            maximum=MAX_ROUTE_CANONICAL_BYTES,
        )
        expected = _product(
            self.row_count,
            self.field_count,
            maximum=MAX_ROUTE_CELLS,
            label="route cell denominator",
        )
        if self.cell_count != expected:
            raise TypedFieldValueReceiptError("route cell denominator is invalid")
        if (
            type(self.field_authorities) is not tuple
            or len(self.field_authorities) != self.field_count
        ):
            raise TypedFieldValueReceiptError("route field denominator is incomplete")
        if (
            type(self.occurrence_authorities) is not tuple
            or type(self.selected_occurrence_authorities) is not tuple
            or type(self.value_receipts) is not tuple
            or len(self.occurrence_authorities) != self.occurrence_partition_count
            or len(self.selected_occurrence_authorities) != self.selected_occurrence_count
            or len(self.value_receipts) != self.occurrence_partition_count
        ):
            raise TypedFieldValueReceiptError("route occurrence denominator is incomplete")
        if type(self.conditional_row_receipts) is not tuple or any(
            type(item) is not ConditionalRowValueReceiptV2 for item in self.conditional_row_receipts
        ):
            raise TypedFieldValueReceiptError("conditional row denominator has foreign values")
        selected = _sha_tuple(
            self.selected_occurrence_sha256s,
            field_name="selected_occurrence_sha256s",
            maximum=MAX_ROUTE_OCCURRENCES,
        )
        if len(selected) != self.selected_occurrence_count:
            raise TypedFieldValueReceiptError("selected occurrence denominator is incomplete")
        for ordinal, summary in enumerate(self.selected_occurrence_authorities):
            if (
                type(summary) is not SourceOccurrenceAuthorityV2
                or summary.raw_bundle_sha256 != self.raw_bundle_sha256
                or summary.occurrence_sha256 != selected[ordinal]
                or summary.source_family != self.source_family
                or summary.endpoint_id != self.endpoint_id
            ):
                raise TypedFieldValueReceiptError(
                    "selected occurrence summary is foreign or reordered"
                )
        slices = _sha_tuple(
            self.row_slice_receipt_sha256s,
            field_name="row_slice_receipt_sha256s",
            maximum=MAX_ROUTE_OCCURRENCES,
        )
        expected_slices = (
            self.occurrence_partition_count
            if self.source_shape == "result_occurrence_bound"
            else 0
            if self.source_shape == "response_fixed_zero"
            else self.row_count
        )
        if (
            self.source_shape == "result_occurrence_bound"
            and self.selected_occurrence_count != self.occurrence_partition_count
        ) or len(slices) != expected_slices:
            raise TypedFieldValueReceiptError("route occurrence/slice denominator is incomplete")
        if len(set(selected)) != len(selected) or len(set(slices)) != len(slices):
            raise TypedFieldValueReceiptError("route occurrence/slice multiplicity collapsed")
        field_hashes = tuple(item.authority_sha256 for item in self.field_authorities)
        cursor = cells = 0
        for ordinal, (authority, values) in enumerate(
            zip(self.occurrence_authorities, self.value_receipts, strict=True)
        ):
            if (
                authority.occurrence_order_ordinal != ordinal
                or authority.occurrence_sha256 != selected[ordinal]
                or authority.source_occurrence_authority_sha256
                != self.selected_occurrence_authorities[ordinal].authority_sha256
                or authority.row_slice_receipt_sha256 != slices[ordinal]
                or authority.start_row_ordinal != cursor
                or authority.source_family != self.source_family
                or authority.decoder_kind != self.decoder_kind
                or authority.endpoint_id != self.endpoint_id
                or values.occurrence_authority != authority
                or values.field_authority_sha256s != field_hashes
            ):
                raise TypedFieldValueReceiptError("route occurrence inventory is foreign")
            cursor = _add(cursor, authority.row_count, maximum=MAX_ROUTE_ROWS, label="route rows")
            cells = _add(cells, values.cell_count, maximum=MAX_ROUTE_CELLS, label="route cells")
        if (
            cursor != self.row_count or cells != self.cell_count
        ) and self.source_shape == "result_occurrence_bound":
            raise TypedFieldValueReceiptError("route values omit committed rows or cells")
        conditional_cells = tuple(
            cell for value in self.conditional_row_receipts for cell in value.cells
        )
        if self.source_shape == "result_occurrence_bound":
            if self.conditional_row_receipts:
                raise TypedFieldValueReceiptError("ordinary route contains conditional source rows")
            all_value_totals = _value_totals(
                tuple(cell for value in self.value_receipts for cell in value.cells)
            )
            all_cells: tuple[TypedFieldCellV2 | ConditionalTypedFieldCellV2, ...] = tuple(
                cell for value in self.value_receipts for cell in value.cells
            )
            for values in self.value_receipts:
                source_summary = self.selected_occurrence_authorities[
                    values.occurrence_authority.occurrence_order_ordinal
                ]
                result_set_ordinal = (
                    source_summary.canonical_result_ordinal
                    if source_summary.canonical_result_ordinal is not None
                    else source_summary.provider_result_ordinal
                )
                for cell in values.cells:
                    field = self.field_authorities[cell.storage_ordinal]
                    expected_sources = tuple(
                        source
                        for source, endpoint_id, result_name, result_ordinal in zip(
                            field.source_occurrence_sha256s,
                            field.source_endpoint_ids,
                            field.source_result_set_names,
                            field.source_result_set_ordinals,
                            strict=True,
                        )
                        if endpoint_id == source_summary.endpoint_id
                        and result_name == source_summary.result_name
                        and result_ordinal == result_set_ordinal
                    )
                    expected_authority: ValueAuthorityKind = (
                        "source_verified" if expected_sources else "storage_readback_only"
                    )
                    if (
                        cell.source_occurrence_sha256s != expected_sources
                        or cell.value_authority != expected_authority
                    ):
                        raise TypedFieldValueReceiptError(
                            "ordinary cell source authority differs from its field"
                        )
        elif self.source_shape == "response_fixed_zero":
            if (
                self.row_count
                or self.cell_count
                or self.occurrence_partition_count
                or self.selected_occurrence_count
                or self.occurrence_authorities
                or self.selected_occurrence_authorities
                or self.value_receipts
                or self.conditional_row_receipts
                or self.selected_occurrence_sha256s
                or self.row_slice_receipt_sha256s
            ):
                raise TypedFieldValueReceiptError(
                    "response fixed-zero route fabricates source rows or occurrences"
                )
            all_value_totals = _value_totals(())
            all_cells = ()
        else:
            if (
                self.occurrence_partition_count
                or self.occurrence_authorities
                or self.value_receipts
            ):
                raise TypedFieldValueReceiptError(
                    "conditional route invents provider occurrence partitions"
                )
            if len(self.conditional_row_receipts) != self.row_count:
                raise TypedFieldValueReceiptError(
                    "conditional row denominator omits committed rows"
                )
            storage_columns = {field.storage_column for field in self.field_authorities}
            if self.source_shape in {
                "selected_result_bound",
                "hybrid_result_body_bound",
            }:
                selected_rows = tuple(
                    row
                    for row in self.conditional_row_receipts
                    if row.row_authority.source_occurrence_sha256 is not None
                )
                response_identities = {
                    (
                        row.row_authority.observed_response_sha256,
                        row.row_authority.observed_results_sha256,
                        row.row_authority.observed_provider_result_set_count,
                        row.row_authority.observed_expected_result_set_count,
                        row.row_authority.observed_reason_codes,
                    )
                    for row in selected_rows
                }
                if not selected_rows or len(response_identities) != 1:
                    raise TypedFieldValueReceiptError(
                        "selected conditional rows span observed response authorities"
                    )
                observed_provider_count = next(iter(response_identities))[2]
                if observed_provider_count != sum(
                    summary.provider_result_ordinal is not None
                    for summary in self.selected_occurrence_authorities
                ):
                    raise TypedFieldValueReceiptError(
                        "selected conditional provider-result denominator is invalid"
                    )
            for ordinal, row_values in enumerate(self.conditional_row_receipts):
                if (
                    row_values.row_authority.source_shape != self.source_shape
                    or row_values.row_authority.row_order_ordinal != ordinal
                    or row_values.row_authority.row_slice_receipt_sha256 != slices[ordinal]
                    or row_values.field_authority_sha256s != field_hashes
                    or row_values.field_count != self.field_count
                ):
                    raise TypedFieldValueReceiptError(
                        "conditional row inventory is reordered or foreign"
                    )
                row_authority = row_values.row_authority
                if not set(row_authority.selector_columns).issubset(storage_columns) or not set(
                    row_authority.source_verified_columns
                ).issubset(storage_columns):
                    raise TypedFieldValueReceiptError(
                        "conditional row names a foreign storage selector"
                    )
                source_summary = (
                    None
                    if row_authority.source_occurrence_sha256 is None
                    else {
                        item.occurrence_sha256: item
                        for item in self.selected_occurrence_authorities
                    }.get(row_authority.source_occurrence_sha256)
                )
                if row_authority.source_occurrence_sha256 is not None and (
                    source_summary is None
                    or row_authority.observation_sha256 != source_summary.observation_sha256
                    or row_authority.source_presence != source_summary.presence
                    or row_authority.source_row_count != source_summary.row_count
                    or row_authority.source_parent_state_sha256
                    != source_summary.parent_state_sha256
                ):
                    raise TypedFieldValueReceiptError(
                        "conditional row occurrence summary is absent or rebound"
                    )
                for cell in row_values.cells:
                    field = self.field_authorities[cell.storage_ordinal]
                    expected_bindings = (
                        tuple(
                            sorted(
                                set(row_authority.source_binding_sha256s).intersection(
                                    field.lossless_binding_sha256s
                                )
                            )
                        )
                        if field.origin == "lossless_bound"
                        and field.storage_column in row_authority.source_verified_columns
                        else ()
                    )
                    expected_authority = (
                        "source_verified" if expected_bindings else "storage_readback_only"
                    )
                    if (
                        cell.source_binding_sha256s != expected_bindings
                        or cell.value_authority != expected_authority
                    ):
                        raise TypedFieldValueReceiptError(
                            "conditional cell source authority differs from its field"
                        )
            if len(conditional_cells) != self.cell_count:
                raise TypedFieldValueReceiptError(
                    "conditional route cell denominator is incomplete"
                )
            all_value_totals = _conditional_value_totals(conditional_cells)
            all_cells = conditional_cells
        source_verified = sum(cell.value_authority == "source_verified" for cell in all_cells)
        if (
            source_verified != self.source_verified_cell_count
            or len(all_cells) - source_verified != self.storage_readback_only_cell_count
        ):
            raise TypedFieldValueReceiptError("route cell value-authority counts are invalid")
        if all_value_totals != (
            self.value_node_count,
            self.value_max_depth,
            self.value_utf8_bytes,
            self.value_binary_bytes,
            self.value_container_items,
            self.value_canonical_bytes,
        ):
            raise TypedFieldValueReceiptError("route resource totals are invalid")
        if self.fields_sha256 != canonical_sha256(
            [item.to_dict() for item in self.field_authorities]
        ):
            raise TypedFieldValueReceiptError("route field digest is invalid")
        if self.occurrences_sha256 != canonical_sha256(
            [item.to_dict() for item in self.occurrence_authorities]
        ):
            raise TypedFieldValueReceiptError("route occurrence digest is invalid")
        if self.selected_occurrences_sha256 != canonical_sha256(
            [item.to_dict() for item in self.selected_occurrence_authorities]
        ):
            raise TypedFieldValueReceiptError("selected occurrence summary digest is invalid")
        if self.values_sha256 != canonical_sha256([item.to_dict() for item in self.value_receipts]):
            raise TypedFieldValueReceiptError("route value digest is invalid")
        if self.conditional_rows_sha256 != canonical_sha256(
            [item.to_dict() for item in self.conditional_row_receipts]
        ):
            raise TypedFieldValueReceiptError("conditional row digest is invalid")
        if self.landing_receipt_sha256 != canonical_sha256(self.identity_payload()):
            raise TypedFieldValueReceiptError("route landing digest is invalid")

    def identity_payload(self) -> dict[str, object]:
        return {
            "schema_version": 2,
            "kind": self.kind,
            "canonical_frame_format": self.canonical_frame_format,
            "frame_content_hash_contract": self.frame_content_hash_contract,
            "frame_schema_hash_contract": self.frame_schema_hash_contract,
            "readback_receipt_sha256": self.readback_receipt_sha256,
            "receipt_root_sha256": self.receipt_root_sha256,
            "raw_bundle_sha256": self.raw_bundle_sha256,
            "field_fate_structure_sha256": self.field_fate_structure_sha256,
            "route_id": self.route_id,
            "staging_key": self.staging_key,
            "source_family": self.source_family,
            "decoder_kind": self.decoder_kind,
            "source_shape": self.source_shape,
            "endpoint_id": self.endpoint_id,
            "conditional_authority_sha256": self.conditional_authority_sha256,
            "row_partition_receipt_sha256": self.row_partition_receipt_sha256,
            "row_count": self.row_count,
            "occurrence_partition_count": self.occurrence_partition_count,
            "selected_occurrence_count": self.selected_occurrence_count,
            "field_count": self.field_count,
            "cell_count": self.cell_count,
            "source_verified_cell_count": self.source_verified_cell_count,
            "storage_readback_only_cell_count": self.storage_readback_only_cell_count,
            "selected_occurrence_sha256s": list(self.selected_occurrence_sha256s),
            "row_slice_receipt_sha256s": list(self.row_slice_receipt_sha256s),
            "value_node_count": self.value_node_count,
            "value_max_depth": self.value_max_depth,
            "value_utf8_bytes": self.value_utf8_bytes,
            "value_binary_bytes": self.value_binary_bytes,
            "value_container_items": self.value_container_items,
            "value_canonical_bytes": self.value_canonical_bytes,
            "fields_sha256": self.fields_sha256,
            "occurrences_sha256": self.occurrences_sha256,
            "selected_occurrences_sha256": self.selected_occurrences_sha256,
            "values_sha256": self.values_sha256,
            "conditional_rows_sha256": self.conditional_rows_sha256,
        }

    def to_dict(self) -> dict[str, object]:
        return {
            **self.identity_payload(),
            "field_authorities": [item.to_dict() for item in self.field_authorities],
            "occurrence_authorities": [item.to_dict() for item in self.occurrence_authorities],
            "selected_occurrence_authorities": [
                item.to_dict() for item in self.selected_occurrence_authorities
            ],
            "value_receipts": [item.to_dict() for item in self.value_receipts],
            "conditional_row_receipts": [item.to_dict() for item in self.conditional_row_receipts],
            "landing_receipt_sha256": self.landing_receipt_sha256,
        }

    def to_canonical_bytes(self) -> bytes:
        return _canonical_json_bytes(self.to_dict(), maximum_bytes=MAX_ROUTE_CANONICAL_BYTES)

    @classmethod
    def from_canonical_bytes(cls, encoded: bytes) -> Self:
        item = _decode_object(
            encoded,
            maximum_bytes=MAX_ROUTE_CANONICAL_BYTES,
            maximum_items=MAX_ROUTE_CELLS * 64,
        )
        keys = {
            "schema_version",
            "kind",
            "canonical_frame_format",
            "frame_content_hash_contract",
            "frame_schema_hash_contract",
            "readback_receipt_sha256",
            "receipt_root_sha256",
            "raw_bundle_sha256",
            "field_fate_structure_sha256",
            "route_id",
            "staging_key",
            "source_family",
            "decoder_kind",
            "source_shape",
            "endpoint_id",
            "conditional_authority_sha256",
            "row_partition_receipt_sha256",
            "row_count",
            "occurrence_partition_count",
            "selected_occurrence_count",
            "field_count",
            "cell_count",
            "source_verified_cell_count",
            "storage_readback_only_cell_count",
            "selected_occurrence_sha256s",
            "row_slice_receipt_sha256s",
            "value_node_count",
            "value_max_depth",
            "value_utf8_bytes",
            "value_binary_bytes",
            "value_container_items",
            "value_canonical_bytes",
            "fields_sha256",
            "occurrences_sha256",
            "selected_occurrences_sha256",
            "values_sha256",
            "conditional_rows_sha256",
            "field_authorities",
            "occurrence_authorities",
            "selected_occurrence_authorities",
            "value_receipts",
            "conditional_row_receipts",
            "landing_receipt_sha256",
        }
        payload = _dict(item, keys=keys, label="route landing receipt")
        _require_v2(payload, kind=cls.kind)
        inventories = (
            "selected_occurrence_sha256s",
            "row_slice_receipt_sha256s",
            "field_authorities",
            "occurrence_authorities",
            "selected_occurrence_authorities",
            "value_receipts",
            "conditional_row_receipts",
        )
        if any(type(payload[name]) is not list for name in inventories):
            raise TypedFieldValueReceiptError("route inventories must be exact lists")
        rows = _integer(payload["row_count"], field_name="row_count", maximum=MAX_ROUTE_ROWS)
        fields_count = _integer(
            payload["field_count"], field_name="field_count", maximum=MAX_ROUTE_FIELDS
        )
        occurrences_count = _integer(
            payload["occurrence_partition_count"],
            field_name="occurrence_partition_count",
            maximum=MAX_ROUTE_OCCURRENCES,
        )
        selected_occurrences_count = _integer(
            payload["selected_occurrence_count"],
            field_name="selected_occurrence_count",
            maximum=MAX_ROUTE_OCCURRENCES,
        )
        cells_count = _integer(
            payload["cell_count"], field_name="cell_count", maximum=MAX_ROUTE_CELLS
        )
        source_verified_cell_count = _integer(
            payload["source_verified_cell_count"],
            field_name="source_verified_cell_count",
            maximum=MAX_ROUTE_CELLS,
        )
        storage_readback_only_cell_count = _integer(
            payload["storage_readback_only_cell_count"],
            field_name="storage_readback_only_cell_count",
            maximum=MAX_ROUTE_CELLS,
        )
        value_node_count = _integer(
            payload["value_node_count"],
            field_name="value_node_count",
            maximum=MAX_ROUTE_VALUE_NODES,
        )
        value_max_depth = _integer(
            payload["value_max_depth"],
            field_name="value_max_depth",
            maximum=MAX_JSON_DEPTH,
        )
        value_utf8_bytes = _integer(
            payload["value_utf8_bytes"],
            field_name="value_utf8_bytes",
            maximum=MAX_ROUTE_VALUE_BYTES,
        )
        value_binary_bytes = _integer(
            payload["value_binary_bytes"],
            field_name="value_binary_bytes",
            maximum=MAX_ROUTE_BINARY_BYTES,
        )
        value_container_items = _integer(
            payload["value_container_items"],
            field_name="value_container_items",
            maximum=MAX_ROUTE_CONTAINER_ITEMS,
        )
        value_canonical_bytes = _integer(
            payload["value_canonical_bytes"],
            field_name="value_canonical_bytes",
            maximum=MAX_ROUTE_CANONICAL_BYTES,
        )
        expected = _product(
            rows, fields_count, maximum=MAX_ROUTE_CELLS, label="route cell denominator"
        )
        if cells_count != expected:
            raise TypedFieldValueReceiptError("route declared cell denominator is invalid")
        if (
            len(cast("list[object]", payload["field_authorities"])) != fields_count
            or len(cast("list[object]", payload["occurrence_authorities"])) != occurrences_count
            or len(cast("list[object]", payload["selected_occurrence_authorities"]))
            != selected_occurrences_count
            or len(cast("list[object]", payload["value_receipts"])) != occurrences_count
        ):
            raise TypedFieldValueReceiptError("route declared inventories are incomplete")
        source_shape = payload["source_shape"]
        conditional_count = len(cast("list[object]", payload["conditional_row_receipts"]))
        if (source_shape == "result_occurrence_bound" and conditional_count != 0) or (
            source_shape in _CONDITIONAL_DECODER_BY_SHAPE and conditional_count != rows
        ):
            raise TypedFieldValueReceiptError(
                "route declared conditional row denominator is invalid"
            )
        budget = ValueBudget(limits=_default_limits())
        fields = tuple(
            LandingFieldAuthorityV2._from_payload(value)
            for value in cast("list[object]", payload["field_authorities"])
        )
        occurrences = tuple(
            OccurrenceLandingAuthorityV2._from_payload(value)
            for value in cast("list[object]", payload["occurrence_authorities"])
        )
        selected_occurrences = tuple(
            SourceOccurrenceAuthorityV2._from_payload(value)
            for value in cast("list[object]", payload["selected_occurrence_authorities"])
        )
        values = tuple(
            TypedFieldValueReceiptV2._from_payload(value, budget=budget)
            for value in cast("list[object]", payload["value_receipts"])
        )
        conditional_rows = tuple(
            ConditionalRowValueReceiptV2._from_payload(value, budget=budget)
            for value in cast("list[object]", payload["conditional_row_receipts"])
        )
        return cls(
            canonical_frame_format=cast("str", payload["canonical_frame_format"]),
            frame_content_hash_contract=cast("str", payload["frame_content_hash_contract"]),
            frame_schema_hash_contract=cast("str", payload["frame_schema_hash_contract"]),
            readback_receipt_sha256=cast("str", payload["readback_receipt_sha256"]),
            receipt_root_sha256=cast("str", payload["receipt_root_sha256"]),
            raw_bundle_sha256=cast("str", payload["raw_bundle_sha256"]),
            field_fate_structure_sha256=cast("str", payload["field_fate_structure_sha256"]),
            route_id=cast("str", payload["route_id"]),
            staging_key=cast("str", payload["staging_key"]),
            source_family=cast("SourceFamily", payload["source_family"]),
            decoder_kind=cast("DecoderKind", payload["decoder_kind"]),
            source_shape=cast("RouteSourceShape", payload["source_shape"]),
            endpoint_id=cast("str", payload["endpoint_id"]),
            conditional_authority_sha256=cast(
                "str | None", payload["conditional_authority_sha256"]
            ),
            row_partition_receipt_sha256=cast("str", payload["row_partition_receipt_sha256"]),
            row_count=rows,
            occurrence_partition_count=occurrences_count,
            selected_occurrence_count=selected_occurrences_count,
            field_count=fields_count,
            cell_count=cells_count,
            source_verified_cell_count=source_verified_cell_count,
            storage_readback_only_cell_count=storage_readback_only_cell_count,
            field_authorities=fields,
            occurrence_authorities=occurrences,
            selected_occurrence_authorities=selected_occurrences,
            value_receipts=values,
            conditional_row_receipts=conditional_rows,
            selected_occurrence_sha256s=tuple(
                cast("list[str]", payload["selected_occurrence_sha256s"])
            ),
            row_slice_receipt_sha256s=tuple(
                cast("list[str]", payload["row_slice_receipt_sha256s"])
            ),
            value_node_count=value_node_count,
            value_max_depth=value_max_depth,
            value_utf8_bytes=value_utf8_bytes,
            value_binary_bytes=value_binary_bytes,
            value_container_items=value_container_items,
            value_canonical_bytes=value_canonical_bytes,
            fields_sha256=cast("str", payload["fields_sha256"]),
            occurrences_sha256=cast("str", payload["occurrences_sha256"]),
            selected_occurrences_sha256=cast("str", payload["selected_occurrences_sha256"]),
            values_sha256=cast("str", payload["values_sha256"]),
            conditional_rows_sha256=cast("str", payload["conditional_rows_sha256"]),
            landing_receipt_sha256=cast("str", payload["landing_receipt_sha256"]),
        )

    @classmethod
    def build_from_authorities(
        cls,
        *,
        readback: CommittedStagingFrameReadbackV2,
        raw_bundle: RawRequestAuthorityBundleV2,
        field_fate: FieldFateStructureV1,
        conditional_authority: ConditionalRouteOccurrenceAuthorityV1 | None = None,
        live_plan_bindings: tuple[LivePlanBinding, ...] = (),
        _value_limits: ValueBudgetLimits | None = None,
    ) -> Self:
        exact_readback = _readback(readback)
        try:
            exact_bundle = validate_raw_request_authority_bundle(raw_bundle)
            validate_field_fate_structure(field_fate)
        except (RawRequestAuthorityError, FieldFateStructureError, ValueError) as exc:
            raise TypedFieldValueReceiptError("typed-field source authority is invalid") from exc
        receipt = exact_readback.committed_receipt
        landing_rows, selected = _route_source_authority(
            bundle=exact_bundle,
            readback=exact_readback,
            live_plan_bindings=live_plan_bindings,
        )
        if conditional_authority is not None:
            if any(
                landing.landing_semantic != "conditional_lossless"
                for _observation, landing in landing_rows
            ):
                raise TypedFieldValueReceiptError(
                    "conditional field authority names a non-conditional response landing"
                )
            exact_conditional = _validate_conditional_input(
                conditional_authority,
                field_fate=field_fate,
                raw_bundle=exact_bundle,
                readback=exact_readback,
            )
            return cast(
                "Self",
                _build_conditional_route_receipt(
                    receipt_type=cls,
                    readback=exact_readback,
                    raw_bundle=exact_bundle,
                    field_fate=field_fate,
                    conditional_authority=exact_conditional,
                    value_limits=_value_limits,
                ),
            )
        landing_semantics = {landing.landing_semantic for _observation, landing in landing_rows}
        if landing_semantics == {"response_fixed_zero"}:
            return cast(
                "Self",
                _build_response_fixed_zero_receipt(
                    receipt_type=cls,
                    readback=exact_readback,
                    raw_bundle=exact_bundle,
                    field_fate=field_fate,
                    landing_rows=landing_rows,
                ),
            )
        if landing_semantics != {"occurrence_bound"}:
            raise TypedFieldValueReceiptError(
                "response route semantic is unsupported or inconsistently relabelled"
            )
        if not selected:
            raise TypedFieldValueReceiptError("route occurrence denominator is absent")
        _assert_observation_occurrence_denominators(exact_bundle, selected)
        table = _read_table(exact_readback)
        if table.num_rows > MAX_ROUTE_ROWS or not 0 < table.num_columns <= MAX_ROUTE_FIELDS:
            raise TypedFieldValueReceiptError("committed Arrow dimensions exceed their bounds")
        try:
            joins = field_fate.route_landing_fields(receipt.result_route_id, table.schema)
        except FieldFateStructureError as exc:
            raise TypedFieldValueReceiptError(
                "route fields differ from field-fate authority"
            ) from exc
        if len(joins) != table.num_columns:
            raise TypedFieldValueReceiptError("route field denominator is incomplete")
        fields = tuple(
            _field_authority(
                join,
                field_fate_sha256=field_fate.identity_sha256,
                arrow_field=table.schema[index],
            )
            for index, join in enumerate(joins)
        )
        first = selected[0][0]
        source_family = first.attempt.source_family
        decoder = _decoder_kind(source_family)
        if any(
            observation.attempt.source_family != source_family
            or observation.attempt.endpoint_id != first.attempt.endpoint_id
            or receipt.provider_authority_sha256 != observation.attempt.provider_authority_sha256
            or receipt.logical_call_receipt_sha256 != observation.logical_receipt_sha256
            for observation, _occurrence in selected
        ):
            raise TypedFieldValueReceiptError("staging receipt differs from raw authority")
        try:
            from nbadb.contracts.staging_route_contract import (
                staging_route_contract_bundle,
            )

            route = staging_route_contract_bundle().by_route_id[receipt.result_route_id]
            for observation, _occurrence in selected:
                observation_route_ids = tuple(
                    sorted(
                        landing.route_id
                        for landing in exact_bundle.landings
                        if landing.observation_sha256 == observation.attempt.observation_sha256
                    )
                )
                validate_logical_provider_parameter_join(
                    observation,
                    logical_endpoint_name=route.endpoint_name,
                    logical_parameters_sha256=receipt.logical_parameters_sha256,
                    result_route_ids=observation_route_ids,
                )
        except (KeyError, RawRequestAuthorityError) as exc:
            raise TypedFieldValueReceiptError(
                "staging receipt logical/provider parameters differ from raw authority"
            ) from exc
        if sum(item.row_count for _, item in selected) != table.num_rows:
            raise TypedFieldValueReceiptError("occurrence rows do not conserve committed rows")
        row_slices: list[CommittedStagingRowSliceV2] = []
        cursor = 0
        for ordinal, (_, occurrence) in enumerate(selected):
            try:
                row_slices.append(
                    CommittedStagingRowSliceV2.build(
                        readback=exact_readback,
                        slice_order_ordinal=ordinal,
                        start_row_ordinal=cursor,
                        row_count=occurrence.row_count,
                    )
                )
            except ParserInputCaptureIntegrityError as exc:
                raise TypedFieldValueReceiptError("committed row slice is invalid") from exc
            cursor += occurrence.row_count
        slices = tuple(row_slices)
        try:
            partition = validate_committed_row_partition(exact_readback, slices)
        except ParserInputCaptureIntegrityError as exc:
            raise TypedFieldValueReceiptError("committed row partition is invalid") from exc
        limits = _value_limits or _default_limits()
        if type(limits) is not ValueBudgetLimits:
            raise TypedFieldValueReceiptError("value limits have a foreign type")
        committed_budget = ValueBudget(limits=limits)
        decoder_budget = ValueBudget(limits=limits)
        selected_occurrence_authorities = tuple(
            _source_occurrence_authority(
                bundle=exact_bundle,
                observation=observation,
                occurrence=occurrence,
            )
            for observation, occurrence in selected
        )
        occurrence_authorities: list[OccurrenceLandingAuthorityV2] = []
        value_receipts: list[TypedFieldValueReceiptV2] = []
        for ordinal, ((observation, occurrence), row_slice) in enumerate(
            zip(selected, slices, strict=True)
        ):
            try:
                decoded = _decoded_provider_rows(
                    bundle=exact_bundle,
                    observation=observation,
                    occurrence=occurrence,
                )
            except (RawRequestAuthorityError, ResponseContractError, ValueError) as exc:
                raise TypedFieldValueReceiptError(
                    "raw occurrence values cannot be independently decoded"
                ) from exc
            if len(decoded.values) != occurrence.row_count:
                raise TypedFieldValueReceiptError("raw decoded rows omit occurrence multiplicity")
            headers = occurrence.ordered_headers()
            if decoded.ordered_headers != headers:
                raise TypedFieldValueReceiptError("raw decoded provider ordering drifted")
            occurrence_decoder = _decoder_kind(observation.attempt.source_family)
            occurrence_values: dict[str, object] = {
                "raw_bundle_sha256": exact_bundle.bundle_sha256,
                "observation_sha256": observation.attempt.observation_sha256,
                "occurrence_sha256": occurrence.occurrence_sha256,
                "source_occurrence_authority_sha256": (
                    selected_occurrence_authorities[ordinal].authority_sha256
                ),
                "source_family": observation.attempt.source_family,
                "decoder_kind": occurrence_decoder,
                "endpoint_id": observation.attempt.endpoint_id,
                "occurrence_order_ordinal": ordinal,
                "result_name": occurrence.result_name,
                "provider_result_ordinal": occurrence.provider_result_ordinal,
                "duplicate_name_ordinal": occurrence.duplicate_name_ordinal,
                "ordered_headers": headers,
                "ordered_headers_sha256": occurrence.ordered_headers_sha256,
                "row_slice_receipt_sha256": row_slice.slice_receipt_sha256,
                "start_row_ordinal": row_slice.start_row_ordinal,
                "row_count": row_slice.row_count,
            }
            occurrence_identity = {
                "schema_version": 2,
                "kind": OccurrenceLandingAuthorityV2.kind,
                **occurrence_values,
                "ordered_headers": list(headers),
            }
            occurrence_authority = OccurrenceLandingAuthorityV2(
                raw_bundle_sha256=exact_bundle.bundle_sha256,
                observation_sha256=observation.attempt.observation_sha256,
                occurrence_sha256=occurrence.occurrence_sha256,
                source_occurrence_authority_sha256=(
                    selected_occurrence_authorities[ordinal].authority_sha256
                ),
                source_family=observation.attempt.source_family,
                decoder_kind=occurrence_decoder,
                endpoint_id=observation.attempt.endpoint_id,
                occurrence_order_ordinal=ordinal,
                result_name=occurrence.result_name,
                provider_result_ordinal=occurrence.provider_result_ordinal,
                duplicate_name_ordinal=occurrence.duplicate_name_ordinal,
                ordered_headers=headers,
                ordered_headers_sha256=occurrence.ordered_headers_sha256,
                row_slice_receipt_sha256=row_slice.slice_receipt_sha256,
                start_row_ordinal=row_slice.start_row_ordinal,
                row_count=row_slice.row_count,
                authority_sha256=canonical_sha256(occurrence_identity),
            )
            occurrence_authorities.append(occurrence_authority)
            applicable = tuple(_applicable_sources(join, observation, occurrence) for join in joins)
            cell_count = _product(
                occurrence.row_count,
                table.num_columns,
                maximum=MAX_ROUTE_CELLS,
                label="occurrence cell denominator",
            )
            cells: list[TypedFieldCellV2] = []
            for row_ordinal, (provider_row, provider_record) in enumerate(
                zip(decoded.values, decoded.records, strict=True)
            ):
                absolute_row = row_slice.start_row_ordinal + row_ordinal
                for storage_ordinal, join in enumerate(joins):
                    column = table.column(storage_ordinal)
                    projected_value = _project_provider_value(
                        join,
                        observation=observation,
                        occurrence=occurrence,
                        provider_row=provider_row,
                        provider_record=provider_record,
                    )
                    try:
                        committed_value = canonical_arrow_array_scalar(
                            column, absolute_row, budget=committed_budget
                        )
                        decoded_canonical = canonical_arrow_scalar(
                            (
                                column[absolute_row].as_py()
                                if projected_value is _USE_COMMITTED_STORAGE_VALUE
                                else projected_value
                            ),
                            column.type,
                            dictionary_context=(
                                column if pa.types.is_dictionary(column.type) else None
                            ),
                            budget=decoder_budget,
                        )
                    except CanonicalArrowValueError as exc:
                        raise TypedFieldValueReceiptError(
                            "decoded or committed Arrow value violates its type"
                        ) from exc
                    if not compare_canonical_arrow_values(committed_value, decoded_canonical):
                        raise TypedFieldValueReceiptError(
                            "decoded Arrow value differs from committed dictionary/type context"
                        )
                    field = fields[storage_ordinal]
                    cell_values: dict[str, object] = {
                        "occurrence_authority_sha256": occurrence_authority.authority_sha256,
                        "field_authority_sha256": field.authority_sha256,
                        "source_occurrence_sha256s": applicable[storage_ordinal],
                        "occurrence_order_ordinal": ordinal,
                        "row_ordinal": row_ordinal,
                        "absolute_row_ordinal": absolute_row,
                        "storage_ordinal": storage_ordinal,
                        "storage_column": field.storage_column,
                        "logical_type_sha256": field.logical_type_sha256,
                        "value_authority": (
                            "source_verified"
                            if applicable[storage_ordinal]
                            else "storage_readback_only"
                        ),
                        "canonical_value": committed_value,
                    }
                    cell_identity = {
                        "schema_version": 2,
                        "kind": TypedFieldCellV2.kind,
                        **{
                            key: value
                            for key, value in cell_values.items()
                            if key != "canonical_value"
                        },
                        "source_occurrence_sha256s": list(applicable[storage_ordinal]),
                        "canonical_value": committed_value.to_dict(),
                    }
                    cells.append(
                        TypedFieldCellV2(
                            **cell_values,
                            cell_receipt_sha256=canonical_sha256(cell_identity),
                        )
                    )
            cell_tuple = tuple(cells)
            totals = _value_totals(cell_tuple)
            field_hashes = tuple(item.authority_sha256 for item in fields)
            cells_sha = canonical_sha256([item.to_dict() for item in cell_tuple])
            values: dict[str, object] = {
                "occurrence_authority": occurrence_authority,
                "field_authority_sha256s": field_hashes,
                "row_count": occurrence.row_count,
                "field_count": table.num_columns,
                "cell_count": cell_count,
                "cells": cell_tuple,
                "value_node_count": totals[0],
                "value_max_depth": totals[1],
                "value_utf8_bytes": totals[2],
                "value_binary_bytes": totals[3],
                "value_container_items": totals[4],
                "value_canonical_bytes": totals[5],
                "cells_sha256": cells_sha,
            }
            value_identity = {
                "schema_version": 2,
                "kind": TypedFieldValueReceiptV2.kind,
                "occurrence_authority_sha256": occurrence_authority.authority_sha256,
                **{
                    key: value
                    for key, value in values.items()
                    if key not in {"occurrence_authority", "cells"}
                },
                "field_authority_sha256s": list(field_hashes),
            }
            value_receipts.append(
                TypedFieldValueReceiptV2(
                    **values,
                    value_receipt_sha256=canonical_sha256(value_identity),
                )
            )
        occurrence_tuple = tuple(occurrence_authorities)
        value_tuple = tuple(value_receipts)
        all_cells = tuple(cell for receipt_value in value_tuple for cell in receipt_value.cells)
        totals = _value_totals(all_cells)
        fields_sha = canonical_sha256([item.to_dict() for item in fields])
        occurrences_sha = canonical_sha256([item.to_dict() for item in occurrence_tuple])
        values_sha = canonical_sha256([item.to_dict() for item in value_tuple])
        selected_occurrences_sha = canonical_sha256(
            [item.to_dict() for item in selected_occurrence_authorities]
        )
        source_verified_cell_count = sum(
            cell.value_authority == "source_verified" for cell in all_cells
        )
        route_values: dict[str, object] = {
            "canonical_frame_format": exact_readback.canonical_frame_format,
            "frame_content_hash_contract": exact_readback.frame_content_hash_contract,
            "frame_schema_hash_contract": exact_readback.frame_schema_hash_contract,
            "readback_receipt_sha256": exact_readback.readback_receipt_sha256,
            "receipt_root_sha256": receipt.receipt_root_sha256,
            "raw_bundle_sha256": exact_bundle.bundle_sha256,
            "field_fate_structure_sha256": field_fate.identity_sha256,
            "route_id": receipt.result_route_id,
            "staging_key": receipt.staging_key,
            "source_family": source_family,
            "decoder_kind": decoder,
            "source_shape": "result_occurrence_bound",
            "endpoint_id": first.attempt.endpoint_id,
            "conditional_authority_sha256": None,
            "row_partition_receipt_sha256": partition.partition_receipt_sha256,
            "row_count": table.num_rows,
            "occurrence_partition_count": len(selected),
            "selected_occurrence_count": len(selected),
            "field_count": table.num_columns,
            "cell_count": _product(
                table.num_rows,
                table.num_columns,
                maximum=MAX_ROUTE_CELLS,
                label="route cell denominator",
            ),
            "source_verified_cell_count": source_verified_cell_count,
            "storage_readback_only_cell_count": (len(all_cells) - source_verified_cell_count),
            "field_authorities": fields,
            "occurrence_authorities": occurrence_tuple,
            "selected_occurrence_authorities": selected_occurrence_authorities,
            "value_receipts": value_tuple,
            "conditional_row_receipts": (),
            "selected_occurrence_sha256s": tuple(item.occurrence_sha256 for _, item in selected),
            "row_slice_receipt_sha256s": partition.slice_receipt_sha256s,
            "value_node_count": totals[0],
            "value_max_depth": totals[1],
            "value_utf8_bytes": totals[2],
            "value_binary_bytes": totals[3],
            "value_container_items": totals[4],
            "value_canonical_bytes": totals[5],
            "fields_sha256": fields_sha,
            "occurrences_sha256": occurrences_sha,
            "selected_occurrences_sha256": selected_occurrences_sha,
            "values_sha256": values_sha,
            "conditional_rows_sha256": canonical_sha256([]),
        }
        identity = {
            "schema_version": 2,
            "kind": cls.kind,
            **{
                key: value
                for key, value in route_values.items()
                if key
                not in {
                    "field_authorities",
                    "occurrence_authorities",
                    "selected_occurrence_authorities",
                    "value_receipts",
                    "conditional_row_receipts",
                }
            },
            "selected_occurrence_sha256s": list(route_values["selected_occurrence_sha256s"]),
            "row_slice_receipt_sha256s": list(route_values["row_slice_receipt_sha256s"]),
        }
        return cls(**route_values, landing_receipt_sha256=canonical_sha256(identity))


def _build_response_fixed_zero_receipt(
    *,
    receipt_type: type[RouteFieldLandingReceiptV2],
    readback: CommittedStagingFrameReadbackV2,
    raw_bundle: RawRequestAuthorityBundleV2,
    field_fate: FieldFateStructureV1,
    landing_rows: tuple[tuple[RequestObservationV2, ObservationRouteLandingV2], ...],
) -> RouteFieldLandingReceiptV2:
    """Seal an exact response-level fixed route without inventing result rows."""

    table = _read_table(readback)
    receipt = readback.committed_receipt
    if table.num_rows != 0 or table.num_columns > MAX_ROUTE_FIELDS:
        raise TypedFieldValueReceiptError(
            "response fixed-zero readback must preserve one bounded exact schema"
        )
    identities = {
        (
            observation.attempt.source_family,
            observation.attempt.endpoint_id,
            observation.attempt.provider_authority_sha256,
            observation.attempt.safe_parameters_sha256,
            observation.logical_receipt_sha256,
        )
        for observation, _landing in landing_rows
    }
    if len(identities) != 1:
        raise TypedFieldValueReceiptError(
            "response fixed-zero landings mix request or endpoint identities"
        )
    source_family, endpoint_id, provider_sha, parameter_sha, logical_receipt = next(
        iter(identities)
    )
    if (
        source_family not in _DECODER_BY_SOURCE
        or receipt.provider_authority_sha256 != provider_sha
        or receipt.logical_parameters_sha256 != parameter_sha
        or receipt.logical_call_receipt_sha256 != logical_receipt
        or any(
            landing.landing_semantic != "response_fixed_zero"
            or landing.source_occurrence_count != 0
            for _observation, landing in landing_rows
        )
    ):
        raise TypedFieldValueReceiptError(
            "response fixed-zero landing differs from its exact request authority"
        )
    if table.num_columns == 0:
        joins = ()
    else:
        try:
            joins = field_fate.route_landing_fields(receipt.result_route_id, table.schema)
        except FieldFateStructureError as exc:
            raise TypedFieldValueReceiptError(
                "response fixed-zero fields differ from field-fate authority"
            ) from exc
    if len(joins) != table.num_columns:
        raise TypedFieldValueReceiptError("response fixed-zero field denominator is incomplete")
    fields = tuple(
        _field_authority(
            join,
            field_fate_sha256=field_fate.identity_sha256,
            arrow_field=table.schema[index],
        )
        for index, join in enumerate(joins)
    )
    partition_receipt_sha256 = canonical_sha256(
        {
            "schema_version": 2,
            "kind": "typed_field_empty_row_partition_v2",
            "canonical_frame_format": readback.canonical_frame_format,
            "frame_content_hash_contract": readback.frame_content_hash_contract,
            "frame_schema_hash_contract": readback.frame_schema_hash_contract,
            "readback_receipt_sha256": readback.readback_receipt_sha256,
            "receipt_root_sha256": receipt.receipt_root_sha256,
            "route_id": receipt.result_route_id,
            "staging_key": receipt.staging_key,
            "row_count": 0,
            "slice_count": 0,
            "slice_receipt_sha256s": [],
        }
    )
    route_values: dict[str, object] = {
        "canonical_frame_format": readback.canonical_frame_format,
        "frame_content_hash_contract": readback.frame_content_hash_contract,
        "frame_schema_hash_contract": readback.frame_schema_hash_contract,
        "readback_receipt_sha256": readback.readback_receipt_sha256,
        "receipt_root_sha256": receipt.receipt_root_sha256,
        "raw_bundle_sha256": raw_bundle.bundle_sha256,
        "field_fate_structure_sha256": field_fate.identity_sha256,
        "route_id": receipt.result_route_id,
        "staging_key": receipt.staging_key,
        "source_family": source_family,
        "decoder_kind": "response_fixed_zero_v2",
        "source_shape": "response_fixed_zero",
        "endpoint_id": endpoint_id,
        "conditional_authority_sha256": None,
        "row_partition_receipt_sha256": partition_receipt_sha256,
        "row_count": 0,
        "occurrence_partition_count": 0,
        "selected_occurrence_count": 0,
        "field_count": table.num_columns,
        "cell_count": 0,
        "source_verified_cell_count": 0,
        "storage_readback_only_cell_count": 0,
        "field_authorities": fields,
        "occurrence_authorities": (),
        "selected_occurrence_authorities": (),
        "value_receipts": (),
        "conditional_row_receipts": (),
        "selected_occurrence_sha256s": (),
        "row_slice_receipt_sha256s": (),
        "value_node_count": 0,
        "value_max_depth": 0,
        "value_utf8_bytes": 0,
        "value_binary_bytes": 0,
        "value_container_items": 0,
        "value_canonical_bytes": 0,
        "fields_sha256": canonical_sha256([item.to_dict() for item in fields]),
        "occurrences_sha256": canonical_sha256([]),
        "selected_occurrences_sha256": canonical_sha256([]),
        "values_sha256": canonical_sha256([]),
        "conditional_rows_sha256": canonical_sha256([]),
    }
    identity = {
        "schema_version": 2,
        "kind": receipt_type.kind,
        **{
            key: value
            for key, value in route_values.items()
            if key
            not in {
                "field_authorities",
                "occurrence_authorities",
                "selected_occurrence_authorities",
                "value_receipts",
                "conditional_row_receipts",
            }
        },
        "selected_occurrence_sha256s": [],
        "row_slice_receipt_sha256s": [],
    }
    return receipt_type(
        **route_values,
        landing_receipt_sha256=canonical_sha256(identity),
    )


def _build_conditional_route_receipt(
    *,
    receipt_type: type[RouteFieldLandingReceiptV2],
    readback: CommittedStagingFrameReadbackV2,
    raw_bundle: RawRequestAuthorityBundleV2,
    field_fate: FieldFateStructureV1,
    conditional_authority: ConditionalRouteOccurrenceAuthorityV1,
    value_limits: ValueBudgetLimits | None,
) -> RouteFieldLandingReceiptV2:
    """Build one shape-specific conditional row partition from exact sources."""

    table = _read_table(readback)
    if table.num_rows > MAX_ROUTE_ROWS or not 0 < table.num_columns <= MAX_ROUTE_FIELDS:
        raise TypedFieldValueReceiptError("conditional Arrow dimensions exceed their bounds")
    try:
        joins = field_fate.route_landing_fields(
            conditional_authority.route_id,
            table.schema,
            conditional_authority=conditional_authority,
        )
    except FieldFateStructureError as exc:
        raise TypedFieldValueReceiptError(
            "conditional route fields differ from field-fate authority"
        ) from exc
    if len(joins) != table.num_columns:
        raise TypedFieldValueReceiptError("conditional route field denominator is incomplete")
    fields = tuple(
        _field_authority(
            join,
            field_fate_sha256=field_fate.identity_sha256,
            arrow_field=table.schema[index],
        )
        for index, join in enumerate(joins)
    )
    shape = conditional_authority.source_shape
    observed_responses: dict[str, DecodedObservedStatsResponseV1] = {}
    if shape == "selected_result_bound":
        source_rows, observed_responses = _stats_binding_source_rows(
            conditional_authority,
            raw_bundle,
        )
    elif shape == "body_node_bound":
        source_rows = _body_node_source_rows(conditional_authority, raw_bundle)
    elif shape == "hybrid_result_body_bound":
        source_rows, observed_responses = _hybrid_stats_source_rows(
            conditional_authority,
            raw_bundle,
        )
    elif shape == "live_lossless_bound":
        source_rows = _live_source_rows(conditional_authority, raw_bundle, table)
    else:  # pragma: no cover - validated closed union
        raise TypedFieldValueReceiptError("conditional source shape is unsupported")
    if len(source_rows) != table.num_rows:
        raise TypedFieldValueReceiptError("conditional source rows do not conserve committed rows")

    row_slices: list[CommittedStagingRowSliceV2] = []
    for ordinal in range(table.num_rows):
        try:
            row_slices.append(
                CommittedStagingRowSliceV2.build(
                    readback=readback,
                    slice_order_ordinal=ordinal,
                    start_row_ordinal=ordinal,
                    row_count=1,
                )
            )
        except ParserInputCaptureIntegrityError as exc:
            raise TypedFieldValueReceiptError("conditional committed row slice is invalid") from exc
    slices = tuple(row_slices)
    try:
        partition = validate_committed_row_partition(readback, slices)
    except ParserInputCaptureIntegrityError as exc:
        raise TypedFieldValueReceiptError("conditional committed row partition is invalid") from exc

    limits = value_limits or _default_limits()
    if type(limits) is not ValueBudgetLimits:
        raise TypedFieldValueReceiptError("value limits have a foreign type")
    source_budget = ValueBudget(limits=limits)
    committed_budget = ValueBudget(limits=limits)
    field_hashes = tuple(item.authority_sha256 for item in fields)
    observation_by_sha = {item.attempt.observation_sha256: item for item in raw_bundle.observations}
    occurrence_by_sha = {item.occurrence_sha256: item for item in raw_bundle.occurrences}
    selected_occurrence_authorities: list[SourceOccurrenceAuthorityV2] = []
    for occurrence_sha256 in conditional_authority.result_occurrence_sha256s:
        occurrence = occurrence_by_sha.get(occurrence_sha256)
        observation = (
            None if occurrence is None else observation_by_sha.get(occurrence.observation_sha256)
        )
        if occurrence is None or observation is None:
            raise TypedFieldValueReceiptError(
                "conditional selected occurrence inventory is foreign"
            )
        body = _body_for_observation(raw_bundle, observation)
        _assert_rederived_occurrence(
            observation=observation,
            occurrence=occurrence,
            parser_input=(None if body is None else decode_parser_input_object(body)),
        )
        selected_occurrence_authorities.append(
            _source_occurrence_authority(
                bundle=raw_bundle,
                observation=observation,
                occurrence=occurrence,
            )
        )
    selected_occurrence_tuple = tuple(selected_occurrence_authorities)
    live_binding_by_id = {
        item.binding_id: item
        for item in field_fate.lossless_bindings
        if item.binding_id in conditional_authority.live_binding_ids
    }
    if shape == "live_lossless_bound" and set(live_binding_by_id) != set(
        conditional_authority.live_binding_ids
    ):
        raise TypedFieldValueReceiptError("conditional live binding denominator is incomplete")

    row_receipts: list[ConditionalRowValueReceiptV2] = []
    for row_ordinal, (source_row, row_slice) in enumerate(zip(source_rows, slices, strict=True)):
        stats_binding = (
            conditional_authority.stats_bindings[row_ordinal]
            if shape != "live_lossless_bound"
            else None
        )
        if stats_binding is not None:
            observation = observation_by_sha.get(stats_binding.observation_sha256)
            if observation is None:
                raise TypedFieldValueReceiptError("conditional stats row omitted its observation")
            occurrence = (
                occurrence_by_sha.get(stats_binding.source_occurrence_sha256)
                if stats_binding.source_occurrence_sha256 is not None
                else None
            )
            body_object_sha256 = stats_binding.body_object_sha256
            row_bindings: tuple[LosslessFieldBindingV1 | StatsLosslessFieldBindingV1, ...] = (
                stats_binding,
            )
            selector_columns = stats_binding.selector_columns
            if stats_binding.binding_kind == "selected_result_bound":
                source_verified_columns = selector_columns
            else:
                source_verified_columns = tuple(
                    column
                    for column in selector_columns
                    if column in _BODY_NODE_INDEPENDENT_COLUMNS
                )
        else:
            observation_ids = {
                item.observation_sha256
                for item in raw_bundle.occurrences
                if item.occurrence_sha256 in conditional_authority.result_occurrence_sha256s
            }
            if len(observation_ids) != 1:
                raise TypedFieldValueReceiptError("conditional live row observation is ambiguous")
            observation = observation_by_sha.get(next(iter(observation_ids)))
            if observation is None or observation.body_object_sha256 is None:
                raise TypedFieldValueReceiptError(
                    "conditional live row omitted its body observation"
                )
            body_object_sha256 = observation.body_object_sha256
            result_name = source_row.get("result_set_name")
            result_ordinal = source_row.get("result_set_ordinal")
            result_occurrence = source_row.get("result_set_occurrence")
            candidates = tuple(
                item
                for item in raw_bundle.occurrences
                if item.occurrence_sha256 in conditional_authority.result_occurrence_sha256s
                and item.result_name == result_name
                and (
                    item.canonical_result_ordinal == result_ordinal
                    or item.provider_result_ordinal == result_ordinal
                )
                and (result_occurrence is None or item.duplicate_name_ordinal == result_occurrence)
            )
            if len(candidates) > 1:
                raise TypedFieldValueReceiptError(
                    "conditional live row result occurrence is ambiguous"
                )
            occurrence = candidates[0] if candidates else None
            applicable: list[LosslessFieldBindingV1] = []
            for binding in live_binding_by_id.values():
                if binding.result_set_ordinal != result_ordinal:
                    continue
                if binding.binding_strategy == "object_contract_field":
                    if (
                        source_row.get("record_kind") == "json_node"
                        and source_row.get("contract_field_ordinal") == binding.field_ordinal
                        and source_row.get("object_key") == binding.provider_field_name
                    ):
                        applicable.append(binding)
                elif (
                    source_row.get("record_kind") == "json_node"
                    and source_row.get("canonical_json") is not None
                    and source_row.get("array_ordinal") is not None
                ):
                    applicable.append(binding)
            row_bindings = tuple(sorted(applicable, key=lambda item: item.binding_id))
            selector_columns = tuple(
                sorted({column for binding in row_bindings for column in binding.selector_columns})
            )
            source_verified_columns = tuple(
                column for column in selector_columns if column in _LIVE_INDEPENDENT_COLUMNS
            )

        source_values: list[CanonicalArrowValueV1] = []
        for storage_ordinal, column_name in enumerate(table.schema.names):
            if column_name not in source_row:
                raise TypedFieldValueReceiptError("conditional source row omitted a storage column")
            column = table.column(storage_ordinal)
            try:
                source_values.append(
                    canonical_arrow_scalar(
                        source_row[column_name],
                        column.type,
                        dictionary_context=(
                            column if pa.types.is_dictionary(column.type) else None
                        ),
                        budget=source_budget,
                    )
                )
            except CanonicalArrowValueError as exc:
                raise TypedFieldValueReceiptError(
                    "conditional source value violates its Arrow type"
                ) from exc
        source_row_sha256 = canonical_sha256([item.to_dict() for item in source_values])
        row_binding_hashes = tuple(sorted(item.binding_sha256 for item in row_bindings))
        occurrence_sha256 = occurrence.occurrence_sha256 if occurrence is not None else None
        observed_response = (
            observed_responses.get(observation.attempt.observation_sha256)
            if stats_binding is not None and stats_binding.binding_kind == "selected_result_bound"
            else None
        )
        expects_observed_response = (
            stats_binding is not None and stats_binding.binding_kind == "selected_result_bound"
        )
        if expects_observed_response != (observed_response is not None):
            raise TypedFieldValueReceiptError(
                "conditional row observed response authority is incomplete"
            )
        row_authority_values: dict[str, object] = {
            "conditional_authority_sha256": conditional_authority.authority_sha256,
            "raw_bundle_sha256": raw_bundle.bundle_sha256,
            "readback_receipt_sha256": readback.readback_receipt_sha256,
            "source_shape": shape,
            "source_family": conditional_authority.source_family,
            "decoder_kind": _conditional_decoder_kind(shape),
            "route_id": conditional_authority.route_id,
            "staging_key": conditional_authority.staging_key,
            "row_order_ordinal": row_ordinal,
            "row_slice_receipt_sha256": row_slice.slice_receipt_sha256,
            "observation_record_sha256": observation.observation_record_sha256,
            "observation_sha256": observation.attempt.observation_sha256,
            "source_occurrence_sha256": occurrence_sha256,
            "body_object_sha256": body_object_sha256,
            "source_presence": occurrence.presence if occurrence is not None else None,
            "source_row_count": occurrence.row_count if occurrence is not None else None,
            "source_parent_state_sha256": (
                occurrence.parent_state_sha256 if occurrence is not None else None
            ),
            "response_receipt_sha256": conditional_authority.response_receipt_sha256,
            "observed_response_sha256": (
                None if observed_response is None else observed_response.response_sha256
            ),
            "observed_results_sha256": (
                None if observed_response is None else observed_response.results_sha256
            ),
            "observed_provider_result_set_count": (
                None if observed_response is None else observed_response.provider_result_set_count
            ),
            "observed_expected_result_set_count": (
                None if observed_response is None else observed_response.expected_result_set_count
            ),
            "observed_reason_codes": (
                () if observed_response is None else observed_response.reason_codes
            ),
            "record_kind": cast("str", source_row["record_kind"]),
            "result_set_name": cast("str | None", source_row.get("result_set_name")),
            "result_set_ordinal": cast("int | None", source_row.get("result_set_ordinal")),
            "result_set_occurrence": cast("int | None", source_row.get("result_set_occurrence")),
            "provider_result_ordinal": cast("int | None", source_row.get("provider_index")),
            "canonical_result_ordinal": cast("int | None", source_row.get("canonical_index")),
            "header_name": cast("str | None", source_row.get("header_name")),
            "header_ordinal": cast("int | None", source_row.get("header_ordinal")),
            "provider_row_ordinal": cast(
                "int | None",
                source_row.get("result_set_row_ordinal", source_row.get("row_ordinal")),
            ),
            "contract_field_ordinal": cast("int | None", source_row.get("contract_field_ordinal")),
            "node_ordinal": cast("int | None", source_row.get("node_ordinal")),
            "parent_node_ordinal": cast("int | None", source_row.get("parent_node_ordinal")),
            "json_path": cast("str | None", source_row.get("json_path")),
            "parent_json_path": cast("str | None", source_row.get("parent_json_path")),
            "object_key": cast("str | None", source_row.get("object_key")),
            "object_key_ordinal": cast("int | None", source_row.get("object_key_ordinal")),
            "array_ordinal": cast("int | None", source_row.get("array_ordinal")),
            "presence_kind": cast("str | None", source_row.get("presence_kind")),
            "value_kind": cast("str | None", source_row.get("value_kind")),
            "source_binding_sha256s": row_binding_hashes,
            "selector_columns": selector_columns,
            "source_verified_columns": source_verified_columns,
            "source_row_sha256": source_row_sha256,
        }
        row_authority_identity = {
            "schema_version": 2,
            "kind": ConditionalSourceRowAuthorityV2.kind,
            **{
                key: value
                for key, value in row_authority_values.items()
                if key
                not in {
                    "source_binding_sha256s",
                    "selector_columns",
                    "source_verified_columns",
                    "observed_reason_codes",
                }
            },
            "source_binding_sha256s": list(row_binding_hashes),
            "selector_columns": list(selector_columns),
            "source_verified_columns": list(source_verified_columns),
            "observed_reason_codes": (
                [] if observed_response is None else list(observed_response.reason_codes)
            ),
        }
        row_authority = ConditionalSourceRowAuthorityV2(
            **row_authority_values,
            authority_sha256=canonical_sha256(row_authority_identity),
        )

        cells: list[ConditionalTypedFieldCellV2] = []
        for storage_ordinal, (field, source_value) in enumerate(
            zip(fields, source_values, strict=True)
        ):
            column = table.column(storage_ordinal)
            try:
                committed_value = canonical_arrow_array_scalar(
                    column, row_ordinal, budget=committed_budget
                )
            except CanonicalArrowValueError as exc:
                raise TypedFieldValueReceiptError(
                    "conditional committed value violates its Arrow type"
                ) from exc
            if not compare_canonical_arrow_values(committed_value, source_value):
                raise TypedFieldValueReceiptError(
                    "conditional source value differs from committed Arrow value"
                )
            cell_bindings = tuple(
                sorted(
                    item.binding_sha256
                    for item in row_bindings
                    if field.storage_column in item.selector_columns
                    and field.storage_column in source_verified_columns
                )
            )
            cell_values: dict[str, object] = {
                "row_authority_sha256": row_authority.authority_sha256,
                "field_authority_sha256": field.authority_sha256,
                "source_binding_sha256s": cell_bindings,
                "source_shape": shape,
                "row_order_ordinal": row_ordinal,
                "storage_ordinal": storage_ordinal,
                "storage_column": field.storage_column,
                "logical_type_sha256": field.logical_type_sha256,
                "value_authority": (
                    "source_verified" if cell_bindings else "storage_readback_only"
                ),
                "canonical_value": committed_value,
            }
            cell_identity = {
                "schema_version": 2,
                "kind": ConditionalTypedFieldCellV2.kind,
                **{
                    key: value
                    for key, value in cell_values.items()
                    if key not in {"source_binding_sha256s", "canonical_value"}
                },
                "source_binding_sha256s": list(cell_bindings),
                "canonical_value": committed_value.to_dict(),
            }
            cells.append(
                ConditionalTypedFieldCellV2(
                    **cell_values,
                    cell_receipt_sha256=canonical_sha256(cell_identity),
                )
            )
        cell_tuple = tuple(cells)
        totals = _conditional_value_totals(cell_tuple)
        cells_sha256 = canonical_sha256([item.to_dict() for item in cell_tuple])
        row_values: dict[str, object] = {
            "row_authority": row_authority,
            "field_authority_sha256s": field_hashes,
            "field_count": table.num_columns,
            "cells": cell_tuple,
            "value_node_count": totals[0],
            "value_max_depth": totals[1],
            "value_utf8_bytes": totals[2],
            "value_binary_bytes": totals[3],
            "value_container_items": totals[4],
            "value_canonical_bytes": totals[5],
            "cells_sha256": cells_sha256,
        }
        row_identity = {
            "schema_version": 2,
            "kind": ConditionalRowValueReceiptV2.kind,
            "row_authority_sha256": row_authority.authority_sha256,
            "field_authority_sha256s": list(field_hashes),
            "field_count": table.num_columns,
            "value_node_count": totals[0],
            "value_max_depth": totals[1],
            "value_utf8_bytes": totals[2],
            "value_binary_bytes": totals[3],
            "value_container_items": totals[4],
            "value_canonical_bytes": totals[5],
            "cells_sha256": cells_sha256,
        }
        row_receipts.append(
            ConditionalRowValueReceiptV2(
                **row_values,
                value_receipt_sha256=canonical_sha256(row_identity),
            )
        )

    conditional_rows = tuple(row_receipts)
    all_cells = tuple(cell for row in conditional_rows for cell in row.cells)
    totals = _conditional_value_totals(all_cells)
    fields_sha256 = canonical_sha256([item.to_dict() for item in fields])
    conditional_rows_sha256 = canonical_sha256([item.to_dict() for item in conditional_rows])
    selected_occurrences_sha256 = canonical_sha256(
        [item.to_dict() for item in selected_occurrence_tuple]
    )
    source_verified_cell_count = sum(
        cell.value_authority == "source_verified" for cell in all_cells
    )
    endpoint_ids = {
        row.row_authority.observation_sha256: observation_by_sha[
            row.row_authority.observation_sha256
        ].attempt.endpoint_id
        for row in conditional_rows
    }
    if len(set(endpoint_ids.values())) != 1:
        raise TypedFieldValueReceiptError("conditional route spans endpoint identities")
    route_values: dict[str, object] = {
        "canonical_frame_format": readback.canonical_frame_format,
        "frame_content_hash_contract": readback.frame_content_hash_contract,
        "frame_schema_hash_contract": readback.frame_schema_hash_contract,
        "readback_receipt_sha256": readback.readback_receipt_sha256,
        "receipt_root_sha256": readback.committed_receipt.receipt_root_sha256,
        "raw_bundle_sha256": raw_bundle.bundle_sha256,
        "field_fate_structure_sha256": field_fate.identity_sha256,
        "route_id": conditional_authority.route_id,
        "staging_key": conditional_authority.staging_key,
        "source_family": conditional_authority.source_family,
        "decoder_kind": _conditional_decoder_kind(shape),
        "source_shape": shape,
        "endpoint_id": next(iter(endpoint_ids.values())),
        "conditional_authority_sha256": conditional_authority.authority_sha256,
        "row_partition_receipt_sha256": partition.partition_receipt_sha256,
        "row_count": table.num_rows,
        "occurrence_partition_count": 0,
        "selected_occurrence_count": len(selected_occurrence_tuple),
        "field_count": table.num_columns,
        "cell_count": _product(
            table.num_rows,
            table.num_columns,
            maximum=MAX_ROUTE_CELLS,
            label="conditional route cell denominator",
        ),
        "source_verified_cell_count": source_verified_cell_count,
        "storage_readback_only_cell_count": (len(all_cells) - source_verified_cell_count),
        "field_authorities": fields,
        "occurrence_authorities": (),
        "selected_occurrence_authorities": selected_occurrence_tuple,
        "value_receipts": (),
        "conditional_row_receipts": conditional_rows,
        "selected_occurrence_sha256s": conditional_authority.result_occurrence_sha256s,
        "row_slice_receipt_sha256s": partition.slice_receipt_sha256s,
        "value_node_count": totals[0],
        "value_max_depth": totals[1],
        "value_utf8_bytes": totals[2],
        "value_binary_bytes": totals[3],
        "value_container_items": totals[4],
        "value_canonical_bytes": totals[5],
        "fields_sha256": fields_sha256,
        "occurrences_sha256": canonical_sha256([]),
        "selected_occurrences_sha256": selected_occurrences_sha256,
        "values_sha256": canonical_sha256([]),
        "conditional_rows_sha256": conditional_rows_sha256,
    }
    route_identity = {
        "schema_version": 2,
        "kind": receipt_type.kind,
        **{
            key: value
            for key, value in route_values.items()
            if key
            not in {
                "field_authorities",
                "occurrence_authorities",
                "selected_occurrence_authorities",
                "value_receipts",
                "conditional_row_receipts",
            }
        },
        "selected_occurrence_sha256s": list(conditional_authority.result_occurrence_sha256s),
        "row_slice_receipt_sha256s": list(partition.slice_receipt_sha256s),
    }
    return receipt_type(
        **route_values,
        landing_receipt_sha256=canonical_sha256(route_identity),
    )


def validate_route_field_landing_receipt_replay(
    receipt_bytes: bytes,
    *,
    readback: CommittedStagingFrameReadbackV2,
    raw_bundle: RawRequestAuthorityBundleV2,
    field_fate: FieldFateStructureV1,
    conditional_authority: ConditionalRouteOccurrenceAuthorityV1 | None = None,
    live_plan_bindings: tuple[LivePlanBinding, ...] = (),
) -> RouteFieldLandingReceiptV2:
    """Strict-parse, rebuild through production joins, and byte-compare a V2 receipt."""

    parsed = RouteFieldLandingReceiptV2.from_canonical_bytes(receipt_bytes)
    expected = RouteFieldLandingReceiptV2.build_from_authorities(
        readback=readback,
        raw_bundle=raw_bundle,
        field_fate=field_fate,
        conditional_authority=conditional_authority,
        live_plan_bindings=live_plan_bindings,
    )
    if parsed.to_canonical_bytes() != expected.to_canonical_bytes() or (
        parsed.landing_receipt_sha256 != expected.landing_receipt_sha256
    ):
        raise TypedFieldValueReceiptError(
            "typed-field receipt differs from strict production authority replay"
        )
    return parsed


__all__ = [
    "DecoderKind",
    "LandingFieldAuthorityV2",
    "OccurrenceLandingAuthorityV2",
    "RouteFieldLandingReceiptV2",
    "SourceFamily",
    "TypedFieldCellV2",
    "TypedFieldValueReceiptError",
    "TypedFieldValueReceiptV2",
    "canonical_json_bytes",
    "canonical_sha256",
    "validate_route_field_landing_receipt_replay",
]
