"""Receipt-bound relational projection for unknown-dynamic stats responses.

The exact parser-input body remains private replay authority.  This module
projects only a captured observation into the existing conditional stats
lossless table.  It preserves deterministic object/array order, duplicate
result/header occurrences, zero-width rows, typed values, and exact authority
digests without inventing a provider schema or a curated video model.
"""

from __future__ import annotations

import hashlib
import json
import re
from collections import Counter
from collections.abc import Mapping, Sequence
from typing import Any, cast

import polars as pl
from nba_api.stats.endpoints import VideoDetails, VideoDetailsAsset, VideoEvents
from nba_api.stats.endpoints.videoeventsasset import VideoEventsAsset

from nbadb.core.errors import ResponseContractError
from nbadb.core.nba_api_provenance import expected_nba_api_provider_authority
from nbadb.core.nba_api_runtime_contract import (
    endpoint_contract_sha256,
    pinned_endpoint_contract,
)
from nbadb.extract.nba_api_adapter import (
    LOSSLESS_FALLBACK_SCHEMA,
    NbaApiLosslessFallback,
    NbaApiUnknownResponse,
)

_SHA256_RE = re.compile(r"[0-9a-f]{64}")
_VIDEO_ENDPOINTS = frozenset(
    {
        ("VideoDetails", "videodetails"),
        ("VideoDetailsAsset", "videodetailsasset"),
        ("VideoEvents", "videoevents"),
        ("VideoEventsAsset", "videoeventsasset"),
    }
)
_VIDEO_ENDPOINT_CLASSES = {
    "VideoDetails": VideoDetails,
    "VideoDetailsAsset": VideoDetailsAsset,
    "VideoEvents": VideoEvents,
    "VideoEventsAsset": VideoEventsAsset,
}
_UNKNOWN_STATES = frozenset(
    {
        "missing_result_envelope",
        "unknown_result_envelope",
        "generic_nested_json",
        "legacy_present_empty",
        "legacy_present_nonempty",
    }
)
_VALUE_KINDS = frozenset({"null", "boolean", "integer", "number", "string", "array", "object"})
_PRESENCE_KINDS = frozenset({"present", "null", "empty_object", "empty_array"})
_RECORD_KINDS = frozenset({"response", "result_set", "header", "row", "cell", "json_node"})
_PathToken = str | int


def _canonical_json(value: object) -> str:
    try:
        return json.dumps(
            value,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
            allow_nan=False,
        )
    except (TypeError, ValueError, OverflowError) as exc:
        raise ResponseContractError("unknown stats lossless value is not canonical JSON") from exc


def _value_kind(value: object) -> str:
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "boolean"
    if isinstance(value, int):
        return "integer"
    if isinstance(value, float):
        return "number"
    if isinstance(value, str):
        return "string"
    if isinstance(value, list):
        return "array"
    if isinstance(value, Mapping):
        if any(not isinstance(key, str) for key in value):
            raise ResponseContractError("unknown stats lossless object contains a non-string key")
        return "object"
    raise ResponseContractError("unknown stats lossless value is not JSON")


def _presence_kind(value: object) -> str:
    if value is None:
        return "null"
    if isinstance(value, Mapping) and not value:
        return "empty_object"
    if isinstance(value, list) and not value:
        return "empty_array"
    return "present"


def _decode_canonical_json(value: object, *, label: str) -> object:
    if not isinstance(value, str):
        raise ResponseContractError(f"unknown stats lossless {label} omitted its value")
    try:
        decoded = json.loads(value)
    except (TypeError, ValueError, json.JSONDecodeError) as exc:
        raise ResponseContractError(f"unknown stats lossless {label} is not valid JSON") from exc
    if _canonical_json(decoded) != value:
        raise ResponseContractError(f"unknown stats lossless {label} is not canonical")
    return decoded


def _json_path(tokens: Sequence[_PathToken]) -> str:
    path = "$"
    for token in tokens:
        if isinstance(token, int):
            path += f"[{token}]"
        else:
            path += f"[{_canonical_json(token)}]"
    return path


def _has_observed_drift(observation: NbaApiUnknownResponse, payload: Mapping[str, Any]) -> bool:
    if observation.occurrences:
        return True
    if observation.legacy_envelope_name is None:
        return bool(payload)
    return any(key != observation.legacy_envelope_name for key in payload)


def build_unknown_stats_lossless_fallback(
    observation: NbaApiUnknownResponse,
    *,
    expected_response_receipt_sha256: str | None = None,
    expected_parameters_sha256: str | None = None,
    expected_parser_input_sha256: str | None = None,
) -> NbaApiLosslessFallback | None:
    """Build one conditional projection, or ``None`` when no drift exists.

    Uncaptured observations never materialize a public conditional route.  The
    response and request/body digests can be supplied from an independently
    reloaded capture receipt to reject otherwise well-formed rebinding.
    """

    if not isinstance(observation, NbaApiUnknownResponse):
        raise ResponseContractError("unknown stats lossless source has an invalid type")
    if (observation.endpoint_id, observation.endpoint_slug) not in _VIDEO_ENDPOINTS:
        raise ResponseContractError("unknown stats lossless source is outside exact video scope")
    receipt = observation.response_receipt_sha256
    if receipt is None:
        return None
    for expected, actual, field_name in (
        (expected_response_receipt_sha256, receipt, "response receipt"),
        (expected_parameters_sha256, observation.parameters_sha256, "request parameters"),
        (expected_parser_input_sha256, observation.parser_input_sha256, "parser input"),
    ):
        if expected is not None and expected != actual:
            raise ResponseContractError(f"unknown stats lossless {field_name} was rebound")

    try:
        payload = json.loads(observation.canonical_payload_json)
    except (TypeError, ValueError, json.JSONDecodeError) as exc:  # pragma: no cover - typed source
        raise ResponseContractError("unknown stats lossless payload is invalid") from exc
    if not isinstance(payload, dict):  # pragma: no cover - typed source
        raise ResponseContractError("unknown stats lossless payload root is not an object")
    if not _has_observed_drift(observation, payload):
        return None

    anomaly_codes_json = _canonical_json(["unknown_dynamic_response"])

    def base_row(record_kind: str) -> dict[str, object | None]:
        return {
            "response_receipt_sha256": receipt,
            "provider_authority_sha256": observation.provider_authority_sha256,
            "endpoint_contract_sha256": observation.endpoint_contract_sha256,
            "response_mode_authority_sha256": observation.response_mode_authority_sha256,
            "parser_input_sha256": observation.parser_input_sha256,
            "canonical_payload_sha256": observation.canonical_payload_sha256,
            "parameters_sha256": observation.parameters_sha256,
            "endpoint_id": observation.endpoint_id,
            "endpoint_slug": observation.endpoint_slug,
            "response_state": observation.state,
            "legacy_envelope_name": observation.legacy_envelope_name,
            "record_kind": record_kind,
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
            "anomaly_codes_json": anomaly_codes_json,
        }

    rows: list[dict[str, object | None]] = [base_row("response")]
    name_occurrences: Counter[str] = Counter()
    for occurrence in observation.occurrences:
        name_occurrence = name_occurrences[occurrence.name]
        name_occurrences[occurrence.name] += 1
        identity = {
            "result_set_name": occurrence.name,
            "result_set_occurrence": name_occurrence,
            "provider_index": occurrence.provider_index,
        }
        result_row = base_row("result_set")
        result_row.update(identity)
        result_row["presence_kind"] = "present"
        rows.append(result_row)
        for header_ordinal, header_name in enumerate(occurrence.headers):
            header_row = base_row("header")
            header_row.update(identity)
            header_row.update(
                {
                    "header_name": header_name,
                    "header_ordinal": header_ordinal,
                    "presence_kind": "present",
                    "value_kind": "string",
                    "canonical_json": _canonical_json(header_name),
                }
            )
            rows.append(header_row)
        for row_ordinal, cells in enumerate(occurrence.rows):
            decoded_cells = [json.loads(cell.canonical_json) for cell in cells]
            row_record = base_row("row")
            row_record.update(identity)
            row_record.update(
                {
                    "row_ordinal": row_ordinal,
                    "presence_kind": _presence_kind(decoded_cells),
                    "value_kind": "array",
                    "canonical_json": _canonical_json(decoded_cells),
                }
            )
            rows.append(row_record)
            for header_ordinal, cell in enumerate(cells):
                cell_record = base_row("cell")
                cell_record.update(identity)
                cell_record.update(
                    {
                        "header_name": occurrence.headers[header_ordinal],
                        "header_ordinal": header_ordinal,
                        "row_ordinal": row_ordinal,
                        "presence_kind": _presence_kind(json.loads(cell.canonical_json)),
                        "value_kind": cell.value_kind,
                        "canonical_json": cell.canonical_json,
                    }
                )
                rows.append(cell_record)

    node_count = 0

    def visit(
        value: object,
        *,
        tokens: tuple[_PathToken, ...],
        parent_node_ordinal: int | None,
        object_key: str | None,
        object_key_ordinal: int | None,
        array_ordinal: int | None,
    ) -> None:
        nonlocal node_count
        node_ordinal = node_count
        node_count += 1
        kind = _value_kind(value)
        presence = _presence_kind(value)
        node = base_row("json_node")
        node.update(
            {
                "node_ordinal": node_ordinal,
                "parent_node_ordinal": parent_node_ordinal,
                "json_path": _json_path(tokens),
                "parent_json_path": _json_path(tokens[:-1]) if tokens else None,
                "depth": len(tokens),
                "object_key": object_key,
                "object_key_ordinal": object_key_ordinal,
                "array_ordinal": array_ordinal,
                "presence_kind": presence,
                "value_kind": kind,
                "canonical_json": (
                    _canonical_json(value)
                    if kind not in {"object", "array"} or presence != "present"
                    else None
                ),
            }
        )
        rows.append(node)
        if isinstance(value, Mapping):
            for key_ordinal, (key, child) in enumerate(value.items()):
                visit(
                    child,
                    tokens=(*tokens, cast("str", key)),
                    parent_node_ordinal=node_ordinal,
                    object_key=cast("str", key),
                    object_key_ordinal=key_ordinal,
                    array_ordinal=None,
                )
        elif isinstance(value, list):
            for child_ordinal, child in enumerate(value):
                visit(
                    child,
                    tokens=(*tokens, child_ordinal),
                    parent_node_ordinal=node_ordinal,
                    object_key=None,
                    object_key_ordinal=None,
                    array_ordinal=child_ordinal,
                )

    visit(
        payload,
        tokens=(),
        parent_node_ordinal=None,
        object_key=None,
        object_key_ordinal=None,
        array_ordinal=None,
    )
    frame = pl.DataFrame(rows, schema=LOSSLESS_FALLBACK_SCHEMA, orient="row")
    validate_unknown_stats_lossless_frame(
        frame,
        expected_response_receipt_sha256=receipt,
    )
    return NbaApiLosslessFallback(
        endpoint_slug=observation.endpoint_slug,
        reason_codes=("unknown_dynamic_response",),
        provider_result_set_count=len(observation.occurrences),
        expected_result_set_count=0,
        result_set_receipts=observation.result_set_receipts,
        frame=frame,
        response_receipt_sha256=receipt,
    )


def _decoded_node_tree(node_rows: list[dict[str, Any]]) -> object:
    if [row["node_ordinal"] for row in node_rows] != list(range(len(node_rows))):
        raise ResponseContractError("unknown stats lossless node ordinals are not contiguous")
    if not node_rows:
        raise ResponseContractError("unknown stats lossless projection omitted its JSON root")
    values: list[object] = []
    tokens_by_ordinal: list[tuple[_PathToken, ...]] = []
    object_child_ordinals: dict[int, int] = {}
    array_child_ordinals: dict[int, int] = {}
    for row in node_rows:
        ordinal = cast("int", row["node_ordinal"])
        parent = row["parent_node_ordinal"]
        value_kind = row["value_kind"]
        presence = row["presence_kind"]
        canonical_json = row["canonical_json"]
        if value_kind not in _VALUE_KINDS or presence not in _PRESENCE_KINDS:
            raise ResponseContractError("unknown stats lossless node value tag is invalid")
        if value_kind == "object":
            value: object = {}
        elif value_kind == "array":
            value = []
        else:
            value = _decode_canonical_json(canonical_json, label="scalar")
        if _value_kind(value) != value_kind:
            raise ResponseContractError("unknown stats lossless node value kind drifted")
        if presence in {"null", "empty_object", "empty_array"}:
            if canonical_json != _canonical_json(value) or _presence_kind(value) != presence:
                raise ResponseContractError("unknown stats lossless empty/null value drifted")
        elif value_kind in {"object", "array"}:
            if canonical_json is not None:
                raise ResponseContractError(
                    "unknown stats lossless container duplicated its subtree value"
                )
        elif canonical_json != _canonical_json(value):
            raise ResponseContractError("unknown stats lossless scalar is not canonical")

        if ordinal == 0:
            if (
                parent is not None
                or row["json_path"] != "$"
                or row["parent_json_path"] is not None
                or row["depth"] != 0
                or row["object_key"] is not None
                or row["object_key_ordinal"] is not None
                or row["array_ordinal"] is not None
            ):
                raise ResponseContractError("unknown stats lossless JSON root is invalid")
            tokens: tuple[_PathToken, ...] = ()
        else:
            if not isinstance(parent, int) or isinstance(parent, bool) or not 0 <= parent < ordinal:
                raise ResponseContractError("unknown stats lossless node parent is invalid")
            parent_value = values[parent]
            parent_tokens = tokens_by_ordinal[parent]
            if isinstance(parent_value, dict):
                key = row["object_key"]
                key_ordinal = row["object_key_ordinal"]
                expected_ordinal = object_child_ordinals.get(parent, 0)
                if (
                    not isinstance(key, str)
                    or key_ordinal != expected_ordinal
                    or row["array_ordinal"] is not None
                    or key in parent_value
                ):
                    raise ResponseContractError(
                        "unknown stats lossless object child identity is invalid"
                    )
                object_child_ordinals[parent] = expected_ordinal + 1
                parent_value[key] = value
                tokens = (*parent_tokens, key)
            elif isinstance(parent_value, list):
                array_ordinal = row["array_ordinal"]
                expected_ordinal = array_child_ordinals.get(parent, 0)
                if (
                    array_ordinal != expected_ordinal
                    or row["object_key"] is not None
                    or row["object_key_ordinal"] is not None
                ):
                    raise ResponseContractError(
                        "unknown stats lossless array child identity is invalid"
                    )
                array_child_ordinals[parent] = expected_ordinal + 1
                parent_value.append(value)
                tokens = (*parent_tokens, expected_ordinal)
            else:
                raise ResponseContractError("unknown stats lossless scalar has a child")
            if (
                row["json_path"] != _json_path(tokens)
                or row["parent_json_path"] != _json_path(parent_tokens)
                or row["depth"] != len(tokens)
            ):
                raise ResponseContractError("unknown stats lossless JSON path was rebound")
        values.append(value)
        tokens_by_ordinal.append(tokens)
    if any(isinstance(value, dict) and list(value) != sorted(value) for value in values):
        raise ResponseContractError(
            "unknown stats lossless object children are not in canonical key order"
        )
    return values[0]


def validate_unknown_stats_lossless_frame(
    frame: pl.DataFrame,
    *,
    expected_response_receipt_sha256: str | None = None,
) -> None:
    """Validate and reconstruct one materialized unknown-dynamic response."""

    if frame.columns != list(LOSSLESS_FALLBACK_SCHEMA) or dict(frame.schema) != (
        LOSSLESS_FALLBACK_SCHEMA
    ):
        raise ResponseContractError("unknown stats lossless frame schema differs")
    rows = frame.to_dicts()
    if not rows:
        raise ResponseContractError("unknown stats lossless frame is empty")
    identity_fields = (
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
        "anomaly_codes_json",
    )
    identity = {field: rows[0][field] for field in identity_fields}
    if any(any(row[field] != value for field, value in identity.items()) for row in rows):
        raise ResponseContractError("unknown stats lossless response identity is inconsistent")
    for field_name in (
        "response_receipt_sha256",
        "provider_authority_sha256",
        "endpoint_contract_sha256",
        "response_mode_authority_sha256",
        "parser_input_sha256",
        "canonical_payload_sha256",
        "parameters_sha256",
    ):
        if (
            not isinstance(identity[field_name], str)
            or _SHA256_RE.fullmatch(cast("str", identity[field_name])) is None
        ):
            raise ResponseContractError(f"unknown stats lossless {field_name} is invalid")
    if (
        expected_response_receipt_sha256 is not None
        and identity["response_receipt_sha256"] != expected_response_receipt_sha256
    ):
        raise ResponseContractError("unknown stats lossless response receipt was rebound")
    if (identity["endpoint_id"], identity["endpoint_slug"]) not in _VIDEO_ENDPOINTS:
        raise ResponseContractError("unknown stats lossless endpoint identity is invalid")
    endpoint_cls = _VIDEO_ENDPOINT_CLASSES[cast("str", identity["endpoint_id"])]
    endpoint_contract = pinned_endpoint_contract(endpoint_cls)
    response_mode = endpoint_contract.response_contract
    if (
        identity["provider_authority_sha256"]
        != expected_nba_api_provider_authority()["authority_sha256"]
        or identity["endpoint_contract_sha256"] != endpoint_contract_sha256(endpoint_contract)
        or response_mode.response_mode != "unknown_dynamic_response"
        or identity["response_mode_authority_sha256"] != response_mode.authority_sha256
    ):
        raise ResponseContractError(
            "unknown stats lossless authority differs from the pinned provider"
        )
    if identity["response_state"] not in _UNKNOWN_STATES:
        raise ResponseContractError("unknown stats lossless response state is invalid")
    if identity["anomaly_codes_json"] != '["unknown_dynamic_response"]':
        raise ResponseContractError("unknown stats lossless anomaly authority is invalid")
    if any(row["record_kind"] not in _RECORD_KINDS for row in rows):
        raise ResponseContractError("unknown stats lossless record kind is invalid")
    if any(row["canonical_index"] is not None for row in rows):
        raise ResponseContractError(
            "unknown stats lossless projection invented a canonical result identity"
        )

    result_selector_fields = (
        "result_set_name",
        "result_set_occurrence",
        "provider_index",
        "header_name",
        "header_ordinal",
        "row_ordinal",
    )
    node_selector_fields = (
        "node_ordinal",
        "parent_node_ordinal",
        "json_path",
        "parent_json_path",
        "depth",
        "object_key",
        "object_key_ordinal",
        "array_ordinal",
    )
    if any(
        row[field] is not None
        for row in rows
        if row["record_kind"] == "json_node"
        for field in result_selector_fields
    ):
        raise ResponseContractError(
            "unknown stats lossless JSON node contains a result-set selector"
        )
    if any(
        row[field] is not None
        for row in rows
        if row["record_kind"] != "json_node"
        for field in node_selector_fields
    ):
        raise ResponseContractError(
            "unknown stats lossless structured record contains a JSON-node selector"
        )

    response_rows = [row for row in rows if row["record_kind"] == "response"]
    if len(response_rows) != 1 or any(
        response_rows[0][field] is not None
        for field in (
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
        )
    ):
        raise ResponseContractError("unknown stats lossless response record is invalid")

    node_rows = [row for row in rows if row["record_kind"] == "json_node"]
    payload = _decoded_node_tree(node_rows)
    if not isinstance(payload, dict):
        raise ResponseContractError("unknown stats lossless payload root is not an object")
    payload_json = _canonical_json(payload)
    if (
        hashlib.sha256(payload_json.encode("utf-8")).hexdigest()
        != identity["canonical_payload_sha256"]
    ):
        raise ResponseContractError("unknown stats lossless payload digest differs")

    result_rows = [row for row in rows if row["record_kind"] == "result_set"]
    header_rows = [row for row in rows if row["record_kind"] == "header"]
    data_rows = [row for row in rows if row["record_kind"] == "row"]
    cell_rows = [row for row in rows if row["record_kind"] == "cell"]
    if [row["provider_index"] for row in result_rows] != list(range(len(result_rows))):
        raise ResponseContractError("unknown stats lossless result ordinals are not contiguous")
    provider_indexes = set(range(len(result_rows)))
    if any(
        row["provider_index"] not in provider_indexes
        for row in (*header_rows, *data_rows, *cell_rows)
    ):
        raise ResponseContractError("unknown stats lossless child has no result occurrence")
    name_occurrences: Counter[str] = Counter()
    structured: list[dict[str, object]] = []
    for result in result_rows:
        provider_index = cast("int", result["provider_index"])
        name = result["result_set_name"]
        if not isinstance(name, str) or not name:
            raise ResponseContractError("unknown stats lossless result name is invalid")
        occurrence = name_occurrences[name]
        name_occurrences[name] += 1
        if (
            result["result_set_occurrence"] != occurrence
            or result["header_name"] is not None
            or result["header_ordinal"] is not None
            or result["row_ordinal"] is not None
            or result["presence_kind"] != "present"
            or result["value_kind"] is not None
            or result["canonical_json"] is not None
        ):
            raise ResponseContractError("unknown stats lossless result identity drifted")
        headers = [row for row in header_rows if row["provider_index"] == provider_index]
        observed_rows = [row for row in data_rows if row["provider_index"] == provider_index]
        if [row["header_ordinal"] for row in headers] != list(range(len(headers))):
            raise ResponseContractError("unknown stats lossless header ordinals drifted")
        if [row["row_ordinal"] for row in observed_rows] != list(range(len(observed_rows))):
            raise ResponseContractError("unknown stats lossless row ordinals drifted")
        header_names = [row["header_name"] for row in headers]
        if any(not isinstance(header, str) or not header for header in header_names):
            raise ResponseContractError("unknown stats lossless header identity is invalid")
        result_identity = (name, occurrence, provider_index)
        for header_ordinal, header in enumerate(headers):
            if (
                (
                    header["result_set_name"],
                    header["result_set_occurrence"],
                    header["provider_index"],
                )
                != result_identity
                or header["header_ordinal"] != header_ordinal
                or header["row_ordinal"] is not None
                or header["presence_kind"] != "present"
                or header["value_kind"] != "string"
                or _decode_canonical_json(
                    header["canonical_json"],
                    label="header value",
                )
                != header["header_name"]
            ):
                raise ResponseContractError("unknown stats lossless header record drifted")
        decoded_rows: list[list[object]] = []
        for row in observed_rows:
            row_ordinal = cast("int", row["row_ordinal"])
            decoded = _decode_canonical_json(row["canonical_json"], label="row value")
            cells = [
                cell
                for cell in cell_rows
                if cell["provider_index"] == provider_index and cell["row_ordinal"] == row_ordinal
            ]
            if (
                (
                    row["result_set_name"],
                    row["result_set_occurrence"],
                    row["provider_index"],
                )
                != result_identity
                or row["header_name"] is not None
                or row["header_ordinal"] is not None
                or row["value_kind"] != "array"
                or not isinstance(decoded, list)
                or row["presence_kind"] != _presence_kind(decoded)
                or len(decoded) != len(header_names)
            ):
                raise ResponseContractError("unknown stats lossless row width drifted")
            decoded_row = cast("list[object]", decoded)
            if [cell["header_ordinal"] for cell in cells] != list(range(len(cells))):
                raise ResponseContractError("unknown stats lossless cell ordinals drifted")
            decoded_cells = [
                _decode_canonical_json(cell["canonical_json"], label="cell value") for cell in cells
            ]
            if len(cells) != len(header_names) or decoded_cells != decoded_row:
                raise ResponseContractError("unknown stats lossless cells do not rebuild row")
            if [cell["header_name"] for cell in cells] != header_names:
                raise ResponseContractError("unknown stats lossless cell header was rebound")
            if any(
                (
                    cell["result_set_name"],
                    cell["result_set_occurrence"],
                    cell["provider_index"],
                )
                != result_identity
                or cell["row_ordinal"] != row_ordinal
                or cell["header_ordinal"] != header_ordinal
                or cell["value_kind"] != _value_kind(decoded_cells[header_ordinal])
                or cell["presence_kind"] != _presence_kind(decoded_cells[header_ordinal])
                for header_ordinal, cell in enumerate(cells)
            ):
                raise ResponseContractError("unknown stats lossless cell record drifted")
            decoded_rows.append(decoded_row)
        structured.append({"name": name, "headers": header_names, "rowSet": decoded_rows})

    envelope_name = identity["legacy_envelope_name"]
    if envelope_name is None:
        if result_rows or identity["response_state"].startswith("legacy_"):
            raise ResponseContractError("unknown stats lossless legacy identity is absent")
    else:
        raw_envelope = payload.get(cast("str", envelope_name))
        normalized_envelope = [raw_envelope] if isinstance(raw_envelope, dict) else raw_envelope
        if (
            not isinstance(normalized_envelope, list)
            or len(normalized_envelope) != len(structured)
            or any(
                not isinstance(raw_result, dict)
                or raw_result.get("name") != projected["name"]
                or raw_result.get("headers") != projected["headers"]
                or raw_result.get("rowSet") != projected["rowSet"]
                for raw_result, projected in zip(
                    normalized_envelope,
                    structured,
                    strict=True,
                )
            )
        ):
            raise ResponseContractError("unknown stats lossless legacy result projection differs")
        has_rows = any(cast("list[object]", item["rowSet"]) for item in structured)
        expected_state = "legacy_present_nonempty" if has_rows else "legacy_present_empty"
        if identity["response_state"] != expected_state:
            raise ResponseContractError("unknown stats lossless legacy response state differs")

    if envelope_name is None:
        expected_state = (
            "missing_result_envelope"
            if not payload
            else (
                "generic_nested_json"
                if any(isinstance(value, dict | list) for value in payload.values())
                else "unknown_result_envelope"
            )
        )
        if identity["response_state"] != expected_state:
            raise ResponseContractError("unknown stats lossless nonlegacy state differs")
        observed_drift = bool(payload)
    else:
        observed_drift = bool(structured) or any(key != envelope_name for key in payload)
    if not observed_drift:
        raise ResponseContractError("unknown stats lossless frame contains no observed drift")


__all__ = [
    "build_unknown_stats_lossless_fallback",
    "validate_unknown_stats_lossless_frame",
]
