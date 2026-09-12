"""Deterministic relational projection of pinned ``nba_api`` live JSON.

The private parser-input body remains the byte authority.  This module derives
an ordered node tree that can be landed and queried without losing JSON paths,
object-key order, array occurrence identity, duplicate observations, or the
difference between missing, null, and empty values.
"""

from __future__ import annotations

import json
import math
import re
from collections import Counter
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any, cast

import polars as pl

from nbadb.core.errors import ResponseContractError

if TYPE_CHECKING:
    from nbadb.core.nba_api_runtime_contract import (
        LiveEndpointContract,
        LiveResultSetContract,
    )
    from nbadb.extract.bronze import ResultSetReceipt

LIVE_LOSSLESS_STAGING_KEY = "stg_nba_api_live_lossless_nodes"
LIVE_LOSSLESS_SCHEMA: dict[str, pl.DataType | type[pl.DataType]] = {
    "response_receipt_sha256": pl.String,
    "provider_authority_sha256": pl.String,
    "endpoint_contract_sha256": pl.String,
    "endpoint_id": pl.String,
    "endpoint_slug": pl.String,
    "request_parameters_json": pl.String,
    "snapshot_at": pl.Datetime(time_unit="us", time_zone="UTC"),
    "snapshot_date": pl.Date,
    "record_kind": pl.String,
    "result_set_name": pl.String,
    "result_set_ordinal": pl.Int64,
    "result_set_occurrence": pl.Int64,
    "result_set_row_ordinal": pl.Int64,
    "contract_json_path": pl.String,
    "container_kind": pl.String,
    "node_ordinal": pl.Int64,
    "parent_node_ordinal": pl.Int64,
    "json_path": pl.String,
    "parent_json_path": pl.String,
    "depth": pl.Int64,
    "object_key": pl.String,
    "object_key_ordinal": pl.Int64,
    "contract_field_ordinal": pl.Int64,
    "array_ordinal": pl.Int64,
    "presence_kind": pl.String,
    "value_kind": pl.String,
    "canonical_json": pl.String,
    "known_contract_field": pl.Boolean,
    "anomaly_codes_json": pl.String,
}

_SHA256_RE = re.compile(r"[0-9a-f]{64}")
_RECORD_KINDS = frozenset({"result_set_declaration", "json_node"})
_PRESENCE_KINDS = frozenset(
    {"declared", "present", "null", "empty_object", "empty_array", "missing"}
)
_VALUE_KINDS = frozenset(
    {"object", "array", "null", "boolean", "integer", "number", "string", "missing"}
)
_PathToken = str | int


def _canonical_json(value: object, *, sort_keys: bool = False) -> str:
    """Encode JSON without lossy string coercion or non-finite numbers."""

    try:
        return json.dumps(
            value,
            allow_nan=False,
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=sort_keys,
        )
    except (TypeError, ValueError, OverflowError) as exc:
        raise ResponseContractError("live JSON cannot be represented canonically") from exc


def _value_kind(value: object) -> str:
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "boolean"
    if isinstance(value, int):
        return "integer"
    if isinstance(value, float):
        if not math.isfinite(value):
            raise ResponseContractError("live JSON contains a non-finite number")
        return "number"
    if isinstance(value, str):
        return "string"
    if isinstance(value, list):
        return "array"
    if isinstance(value, Mapping):
        if any(not isinstance(key, str) for key in value):
            raise ResponseContractError("live JSON object contains a non-string key")
        return "object"
    raise ResponseContractError("live response contains a non-JSON value")


def _concrete_json_path(tokens: Sequence[_PathToken]) -> str:
    path = "$"
    for token in tokens:
        if isinstance(token, int):
            path += f"[{token}]"
        else:
            path += f"[{_canonical_json(token)}]"
    return path


def _path_matches(pattern: Sequence[str], tokens: Sequence[_PathToken]) -> bool:
    return len(pattern) == len(tokens) and all(
        (expected == "*" and isinstance(observed, int)) or expected == observed
        for expected, observed in zip(pattern, tokens, strict=True)
    )


def _result_set_at_path(
    contract: LiveEndpointContract,
    tokens: Sequence[_PathToken],
) -> LiveResultSetContract | None:
    matches = tuple(
        result_set
        for result_set in contract.result_sets
        if _path_matches(result_set.traversal_path, tokens)
    )
    if len(matches) > 1:
        raise ResponseContractError("live JSON path matches multiple result-set contracts")
    return matches[0] if matches else None


def _child_result_set_fields(
    contract: LiveEndpointContract,
    result_set: LiveResultSetContract,
) -> frozenset[str]:
    return frozenset(
        child.parent_field_name
        for child in contract.result_sets
        if child.parent_result_set_name == result_set.name and child.parent_field_name is not None
    )


@dataclass(frozen=True, slots=True)
class _ResultContext:
    contract: LiveResultSetContract
    occurrence: int
    row_ordinal: int | None


class _NodeProjector:
    def __init__(
        self,
        *,
        contract: LiveEndpointContract,
        payload: Mapping[str, Any],
        endpoint_slug: str,
        request_parameters_json: str,
        provider_authority_sha256: str,
        endpoint_contract_sha256: str,
        anomaly_codes: tuple[str, ...],
    ) -> None:
        self.contract = contract
        self.payload = payload
        self.endpoint_slug = endpoint_slug
        self.request_parameters_json = request_parameters_json
        self.provider_authority_sha256 = provider_authority_sha256
        self.endpoint_contract_sha256 = endpoint_contract_sha256
        self.anomaly_codes = anomaly_codes
        self.rows: list[dict[str, object | None]] = []
        self.result_occurrences: Counter[str] = Counter()
        self.node_count = 0

    def project(self) -> pl.DataFrame:
        for result_set in self.contract.result_sets:
            self.rows.append(
                self._base_row(
                    record_kind="result_set_declaration",
                    result_set=result_set,
                    presence_kind="declared",
                    container_kind=result_set.container_kind,
                )
            )
        self._visit(
            self.payload,
            tokens=(),
            parent_node_ordinal=None,
            object_key=None,
            object_key_ordinal=None,
            array_ordinal=None,
            inherited_context=None,
            record_contract=None,
        )
        frame = pl.DataFrame(self.rows, schema=LIVE_LOSSLESS_SCHEMA, orient="row")
        validate_live_lossless_frame(
            frame,
            expected_result_set_count=len(self.contract.result_sets),
        )
        return frame

    def _base_row(
        self,
        *,
        record_kind: str,
        result_set: LiveResultSetContract | None = None,
        presence_kind: str,
        container_kind: str | None = None,
    ) -> dict[str, object | None]:
        return {
            "response_receipt_sha256": None,
            "provider_authority_sha256": self.provider_authority_sha256,
            "endpoint_contract_sha256": self.endpoint_contract_sha256,
            "endpoint_id": self.contract.endpoint_id,
            "endpoint_slug": self.endpoint_slug,
            "request_parameters_json": self.request_parameters_json,
            "snapshot_at": None,
            "snapshot_date": None,
            "record_kind": record_kind,
            "result_set_name": result_set.name if result_set is not None else None,
            "result_set_ordinal": result_set.ordinal if result_set is not None else None,
            "result_set_occurrence": None,
            "result_set_row_ordinal": None,
            "contract_json_path": result_set.json_path if result_set is not None else None,
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
            "anomaly_codes_json": _canonical_json(list(self.anomaly_codes)),
        }

    def _matched_context(
        self,
        tokens: Sequence[_PathToken],
        *,
        value: object,
    ) -> _ResultContext | None:
        result_set = _result_set_at_path(self.contract, tokens)
        if result_set is None:
            return None
        occurrence = self.result_occurrences[result_set.name]
        self.result_occurrences[result_set.name] += 1
        row_ordinal = 0 if isinstance(value, Mapping) else None
        return _ResultContext(result_set, occurrence, row_ordinal)

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
        record_contract: LiveResultSetContract | None,
    ) -> None:
        matched_context = self._matched_context(tokens, value=value)
        context = matched_context or inherited_context
        value_kind = _value_kind(value)
        node_ordinal = self._next_node_ordinal()
        field_ordinal: int | None = None
        known_field: bool | None = None
        if object_key is not None and record_contract is not None:
            fields = {field.name: ordinal for ordinal, field in enumerate(record_contract.fields)}
            child_fields = _child_result_set_fields(self.contract, record_contract)
            field_ordinal = fields.get(object_key)
            known_field = object_key in fields or object_key in child_fields

        presence_kind = "present"
        canonical_json: str | None = None
        if value is None:
            presence_kind = "null"
            canonical_json = "null"
        elif isinstance(value, Mapping) and not value:
            presence_kind = "empty_object"
            canonical_json = "{}"
        elif isinstance(value, list) and not value:
            presence_kind = "empty_array"
            canonical_json = "[]"
        elif value_kind not in {"object", "array"}:
            canonical_json = _canonical_json(value)

        result_set = context.contract if context is not None else None
        row = self._base_row(
            record_kind="json_node",
            result_set=result_set,
            presence_kind=presence_kind,
            container_kind=(
                matched_context.contract.container_kind if matched_context is not None else None
            ),
        )
        row.update(
            {
                "result_set_occurrence": context.occurrence if context is not None else None,
                "result_set_row_ordinal": (context.row_ordinal if context is not None else None),
                "node_ordinal": node_ordinal,
                "parent_node_ordinal": parent_node_ordinal,
                "json_path": _concrete_json_path(tokens),
                "parent_json_path": (_concrete_json_path(tokens[:-1]) if tokens else None),
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
        self.rows.append(row)

        if isinstance(value, Mapping):
            active_record = (
                matched_context.contract
                if matched_context is not None
                and matched_context.contract.container_kind == "nba_api_live_json_object"
                else record_contract
            )
            for key_ordinal, (raw_key, child) in enumerate(value.items()):
                key = cast("str", raw_key)
                self._visit(
                    child,
                    tokens=(*tokens, key),
                    parent_node_ordinal=node_ordinal,
                    object_key=key,
                    object_key_ordinal=key_ordinal,
                    array_ordinal=None,
                    inherited_context=context,
                    record_contract=active_record,
                )
            if active_record is not None:
                present = set(value)
                for expected_ordinal, field in enumerate(active_record.fields):
                    if field.name not in present:
                        self._visit_missing(
                            tokens=(*tokens, field.name),
                            parent_node_ordinal=node_ordinal,
                            object_key=field.name,
                            inherited_context=context,
                            record_contract=active_record,
                            contract_field_ordinal=expected_ordinal,
                        )
        elif isinstance(value, list):
            item_record = (
                matched_context.contract
                if matched_context is not None
                and matched_context.contract.container_kind == "nba_api_live_json_array"
                else None
            )
            for item_ordinal, child in enumerate(value):
                child_context = context
                if context is not None and item_record is not None:
                    child_context = replace(context, row_ordinal=item_ordinal)
                self._visit(
                    child,
                    tokens=(*tokens, item_ordinal),
                    parent_node_ordinal=node_ordinal,
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
        record_contract: LiveResultSetContract,
        contract_field_ordinal: int,
    ) -> None:
        matched = self._matched_context(tokens, value=None)
        context = matched or inherited_context
        node_ordinal = self._next_node_ordinal()
        result_set = context.contract if context is not None else None
        row = self._base_row(
            record_kind="json_node",
            result_set=result_set,
            presence_kind="missing",
            container_kind=(matched.contract.container_kind if matched is not None else None),
        )
        row.update(
            {
                "result_set_occurrence": context.occurrence if context is not None else None,
                "result_set_row_ordinal": (context.row_ordinal if context is not None else None),
                "node_ordinal": node_ordinal,
                "parent_node_ordinal": parent_node_ordinal,
                "json_path": _concrete_json_path(tokens),
                "parent_json_path": _concrete_json_path(tokens[:-1]),
                "depth": len(tokens),
                "object_key": object_key,
                "object_key_ordinal": None,
                "contract_field_ordinal": contract_field_ordinal,
                "array_ordinal": None,
                "value_kind": "missing",
                "canonical_json": None,
                "known_contract_field": True,
            }
        )
        self.rows.append(row)

    def _next_node_ordinal(self) -> int:
        ordinal = self.node_count
        self.node_count += 1
        return ordinal


@dataclass(frozen=True, slots=True)
class NbaApiLiveLosslessLanding:
    """One complete deterministic node landing for a successful live response."""

    endpoint_id: str
    endpoint_slug: str
    reason_codes: tuple[str, ...]
    expected_result_set_count: int
    result_set_receipts: tuple[ResultSetReceipt, ...]
    frame: pl.DataFrame
    response_receipt_sha256: str | None = None
    snapshot_at: datetime | None = None

    def __post_init__(self) -> None:
        if not self.endpoint_id or not self.endpoint_slug:
            raise ResponseContractError("live lossless endpoint identity must be nonempty")
        if self.reason_codes != tuple(sorted(set(self.reason_codes))):
            raise ResponseContractError("live lossless anomaly codes must be sorted and unique")
        if (
            isinstance(self.expected_result_set_count, bool)
            or not isinstance(self.expected_result_set_count, int)
            or self.expected_result_set_count <= 0
        ):
            raise ResponseContractError("live lossless result-set count must be positive")
        if len(self.result_set_receipts) != self.expected_result_set_count:
            raise ResponseContractError("live lossless result-set receipt inventory is incomplete")
        if [receipt.canonical_index for receipt in self.result_set_receipts] != list(
            range(self.expected_result_set_count)
        ) or len({receipt.name for receipt in self.result_set_receipts}) != len(
            self.result_set_receipts
        ):
            raise ResponseContractError("live lossless result-set receipts are not canonical")
        validate_live_lossless_frame(
            self.frame,
            expected_response_receipt_sha256=self.response_receipt_sha256,
            expected_result_set_count=self.expected_result_set_count,
            expected_snapshot_at=self.snapshot_at,
            expected_endpoint_id=self.endpoint_id,
            expected_endpoint_slug=self.endpoint_slug,
            expected_anomaly_codes=self.reason_codes,
        )

    def bind_response_receipt(self, receipt_sha256: str) -> NbaApiLiveLosslessLanding:
        if _SHA256_RE.fullmatch(receipt_sha256) is None:
            raise ResponseContractError("live lossless response receipt must be a SHA-256")
        return replace(
            self,
            response_receipt_sha256=receipt_sha256,
            frame=self.frame.with_columns(
                pl.lit(receipt_sha256, dtype=pl.String).alias("response_receipt_sha256")
            ),
        )

    def bind_snapshot(self, snapshot_at: datetime) -> NbaApiLiveLosslessLanding:
        if snapshot_at.tzinfo is None:
            snapshot_at = snapshot_at.replace(tzinfo=UTC)
        normalized = snapshot_at.astimezone(UTC)
        return replace(
            self,
            snapshot_at=normalized,
            frame=self.frame.with_columns(
                pl.lit(normalized, dtype=pl.Datetime("us", "UTC")).alias("snapshot_at"),
                pl.lit(normalized.date(), dtype=pl.Date).alias("snapshot_date"),
            ),
        )


def build_live_lossless_landing(
    payload: Mapping[str, Any],
    *,
    contract: LiveEndpointContract,
    endpoint_slug: str,
    request_parameters: Mapping[str, Any],
    provider_authority_sha256: str,
    endpoint_contract_sha256: str,
    result_set_receipts: Sequence[ResultSetReceipt],
    anomaly_codes: Sequence[str] = (),
) -> NbaApiLiveLosslessLanding:
    """Project a validated decoded body while retaining every JSON node."""

    for digest in (provider_authority_sha256, endpoint_contract_sha256):
        if _SHA256_RE.fullmatch(digest) is None:
            raise ResponseContractError("live lossless authority digest must be a SHA-256")
    reason_codes = tuple(sorted(set(anomaly_codes)))
    request_parameters_json = _canonical_json(dict(request_parameters), sort_keys=True)
    projector = _NodeProjector(
        contract=contract,
        payload=payload,
        endpoint_slug=endpoint_slug,
        request_parameters_json=request_parameters_json,
        provider_authority_sha256=provider_authority_sha256,
        endpoint_contract_sha256=endpoint_contract_sha256,
        anomaly_codes=reason_codes,
    )
    return NbaApiLiveLosslessLanding(
        endpoint_id=contract.endpoint_id,
        endpoint_slug=endpoint_slug,
        reason_codes=reason_codes,
        expected_result_set_count=len(contract.result_sets),
        result_set_receipts=tuple(result_set_receipts),
        frame=projector.project(),
    )


def validate_live_lossless_frame(
    frame: pl.DataFrame,
    *,
    expected_response_receipt_sha256: str | None = None,
    expected_result_set_count: int | None = None,
    expected_snapshot_at: datetime | None = None,
    expected_endpoint_id: str | None = None,
    expected_endpoint_slug: str | None = None,
    expected_anomaly_codes: Sequence[str] | None = None,
) -> None:
    """Fail closed when a live node landing cannot be replayed unambiguously."""

    if frame.columns != list(LIVE_LOSSLESS_SCHEMA) or dict(frame.schema) != (LIVE_LOSSLESS_SCHEMA):
        raise ResponseContractError("live lossless frame schema differs from its contract")
    if frame.is_empty():
        raise ResponseContractError("live lossless frame must retain response nodes")
    rows = frame.to_dicts()
    if any(row["record_kind"] not in _RECORD_KINDS for row in rows):
        raise ResponseContractError("live lossless record kind is invalid")
    if any(row["presence_kind"] not in _PRESENCE_KINDS for row in rows):
        raise ResponseContractError("live lossless presence kind is invalid")

    declarations = [row for row in rows if row["record_kind"] == "result_set_declaration"]
    nodes = [row for row in rows if row["record_kind"] == "json_node"]
    if expected_result_set_count is not None and len(declarations) != expected_result_set_count:
        raise ResponseContractError("live lossless result-set declaration inventory is incomplete")
    if [row["result_set_ordinal"] for row in declarations] != list(range(len(declarations))):
        raise ResponseContractError("live lossless result-set ordinals are not contiguous")
    declaration_names = [row["result_set_name"] for row in declarations]
    if any(not isinstance(name, str) or not name for name in declaration_names) or len(
        set(declaration_names)
    ) != len(declaration_names):
        raise ResponseContractError("live lossless result-set declarations are invalid")
    declared_by_ordinal = {
        cast("int", row["result_set_ordinal"]): cast("str", row["result_set_name"])
        for row in declarations
    }
    if [row["node_ordinal"] for row in nodes] != list(range(len(nodes))):
        raise ResponseContractError("live lossless node ordinals are not contiguous")
    if not nodes or nodes[0]["json_path"] != "$" or nodes[0]["parent_node_ordinal"] is not None:
        raise ResponseContractError("live lossless root node is invalid")
    paths: set[str] = set()
    nodes_by_ordinal: dict[int, dict[str, Any]] = {}
    object_child_ordinals: dict[int, list[int]] = {}
    array_child_ordinals: dict[int, list[int]] = {}
    result_occurrences: dict[str, list[int]] = {}
    for row in nodes:
        value_kind = row["value_kind"]
        if value_kind not in _VALUE_KINDS:
            raise ResponseContractError("live lossless value kind is invalid")
        ordinal = cast("int", row["node_ordinal"])
        nodes_by_ordinal[ordinal] = row
        result_set_ordinal = row["result_set_ordinal"]
        result_set_name = row["result_set_name"]
        if result_set_ordinal is not None and (
            not isinstance(result_set_ordinal, int)
            or declared_by_ordinal.get(result_set_ordinal) != result_set_name
        ):
            raise ResponseContractError("live lossless node result-set identity is invalid")
        if row["container_kind"] is not None:
            occurrence = row["result_set_occurrence"]
            if not isinstance(result_set_name, str) or not isinstance(occurrence, int):
                raise ResponseContractError("live lossless result-set occurrence is invalid")
            result_occurrences.setdefault(result_set_name, []).append(occurrence)
        parent = row["parent_node_ordinal"]
        if ordinal and (not isinstance(parent, int) or parent < 0 or parent >= ordinal):
            raise ResponseContractError("live lossless parent node is invalid")
        path = row["json_path"]
        if not isinstance(path, str) or path in paths:
            raise ResponseContractError("live lossless JSON path is duplicated or invalid")
        paths.add(path)
        depth = row["depth"]
        if not isinstance(depth, int) or depth < 0:
            raise ResponseContractError("live lossless node depth is invalid")
        if ordinal == 0:
            if (
                path != "$"
                or depth != 0
                or row["parent_json_path"] is not None
                or row["object_key"] is not None
                or row["object_key_ordinal"] is not None
                or row["array_ordinal"] is not None
            ):
                raise ResponseContractError("live lossless root edge is invalid")
        else:
            parent_row = nodes_by_ordinal[cast("int", parent)]
            parent_path = cast("str", parent_row["json_path"])
            if row["parent_json_path"] != parent_path or depth != parent_row["depth"] + 1:
                raise ResponseContractError("live lossless parent path is invalid")
            if parent_row["value_kind"] == "object":
                object_key = row["object_key"]
                key_ordinal = row["object_key_ordinal"]
                if (
                    not isinstance(object_key, str)
                    or row["array_ordinal"] is not None
                    or (row["presence_kind"] != "missing" and not isinstance(key_ordinal, int))
                    or (row["presence_kind"] == "missing" and key_ordinal is not None)
                    or path != f"{parent_path}[{_canonical_json(object_key)}]"
                ):
                    raise ResponseContractError("live lossless object edge is invalid")
                if isinstance(key_ordinal, int):
                    object_child_ordinals.setdefault(cast("int", parent), []).append(key_ordinal)
            elif parent_row["value_kind"] == "array":
                item_ordinal = row["array_ordinal"]
                if (
                    not isinstance(item_ordinal, int)
                    or row["object_key"] is not None
                    or row["object_key_ordinal"] is not None
                    or row["presence_kind"] == "missing"
                    or path != f"{parent_path}[{item_ordinal}]"
                ):
                    raise ResponseContractError("live lossless array edge is invalid")
                array_child_ordinals.setdefault(cast("int", parent), []).append(item_ordinal)
            else:
                raise ResponseContractError("live lossless scalar node cannot have children")
        if row["presence_kind"] == "missing":
            if value_kind != "missing" or row["canonical_json"] is not None:
                raise ResponseContractError("live lossless missing node is invalid")
            continue
        encoded = row["canonical_json"]
        if value_kind in {"object", "array"}:
            expected_empty = "{}" if value_kind == "object" else "[]"
            if encoded not in {None, expected_empty}:
                raise ResponseContractError("live lossless container value is invalid")
        else:
            if not isinstance(encoded, str):
                raise ResponseContractError("live lossless scalar value is absent")
            decoded = json.loads(encoded)
            if _value_kind(decoded) != value_kind or _canonical_json(decoded) != encoded:
                raise ResponseContractError("live lossless scalar tag differs from its value")

    for child_ordinals in (*object_child_ordinals.values(), *array_child_ordinals.values()):
        if child_ordinals != list(range(len(child_ordinals))):
            raise ResponseContractError("live lossless child ordinals are not contiguous")
    for occurrences in result_occurrences.values():
        if occurrences != list(range(len(occurrences))):
            raise ResponseContractError("live lossless result-set occurrences are not contiguous")

    for digest_column in ("provider_authority_sha256", "endpoint_contract_sha256"):
        digests = {row[digest_column] for row in rows}
        if len(digests) != 1 or _SHA256_RE.fullmatch(cast("str", next(iter(digests)))) is None:
            raise ResponseContractError("live lossless authority identity is invalid")
    for identity_column in ("endpoint_id", "endpoint_slug"):
        identities = {row[identity_column] for row in rows}
        if (
            len(identities) != 1
            or not isinstance(next(iter(identities)), str)
            or not next(iter(identities))
        ):
            raise ResponseContractError("live lossless endpoint identity is invalid")
    if expected_endpoint_id is not None and {row["endpoint_id"] for row in rows} != {
        expected_endpoint_id
    }:
        raise ResponseContractError("live lossless frame endpoint id is inconsistent")
    if expected_endpoint_slug is not None and {row["endpoint_slug"] for row in rows} != {
        expected_endpoint_slug
    }:
        raise ResponseContractError("live lossless frame endpoint slug is inconsistent")
    parameter_values = {row["request_parameters_json"] for row in rows}
    if len(parameter_values) != 1:
        raise ResponseContractError("live lossless request scope is inconsistent")
    parameter_json = cast("str", next(iter(parameter_values)))
    try:
        decoded_parameters = json.loads(parameter_json)
    except (TypeError, json.JSONDecodeError) as exc:
        raise ResponseContractError("live lossless request scope is invalid") from exc
    if (
        not isinstance(decoded_parameters, dict)
        or _canonical_json(decoded_parameters, sort_keys=True) != parameter_json
    ):
        raise ResponseContractError("live lossless request scope is not canonical")
    anomaly_values = {row["anomaly_codes_json"] for row in rows}
    if len(anomaly_values) != 1:
        raise ResponseContractError("live lossless anomaly inventory is inconsistent")
    anomaly_json = cast("str", next(iter(anomaly_values)))
    try:
        decoded_anomalies = json.loads(anomaly_json)
    except (TypeError, json.JSONDecodeError) as exc:
        raise ResponseContractError("live lossless anomaly inventory is invalid") from exc
    if (
        not isinstance(decoded_anomalies, list)
        or any(not isinstance(item, str) or not item for item in decoded_anomalies)
        or decoded_anomalies != sorted(set(decoded_anomalies))
        or _canonical_json(decoded_anomalies) != anomaly_json
    ):
        raise ResponseContractError("live lossless anomaly inventory is not canonical")
    if expected_anomaly_codes is not None and decoded_anomalies != list(expected_anomaly_codes):
        raise ResponseContractError("live lossless frame anomaly inventory is inconsistent")

    receipts = {row["response_receipt_sha256"] for row in rows}
    if expected_response_receipt_sha256 is None:
        if receipts != {None}:
            raise ResponseContractError("unbound live lossless frame contains a response receipt")
    elif _SHA256_RE.fullmatch(expected_response_receipt_sha256) is None or receipts != {
        expected_response_receipt_sha256
    }:
        raise ResponseContractError("live lossless frame differs from its response receipt")

    snapshots = {row["snapshot_at"] for row in rows}
    snapshot_dates = {row["snapshot_date"] for row in rows}
    if expected_snapshot_at is None:
        if snapshots != {None} or snapshot_dates != {None}:
            raise ResponseContractError("unbound live lossless frame contains snapshot metadata")
    else:
        normalized = (
            expected_snapshot_at.replace(tzinfo=UTC)
            if expected_snapshot_at.tzinfo is None
            else expected_snapshot_at.astimezone(UTC)
        )
        if snapshots != {normalized} or snapshot_dates != {normalized.date()}:
            raise ResponseContractError("live lossless frame differs from its snapshot")
    reconstruct_live_payload(frame)


def reconstruct_live_payload(frame: pl.DataFrame) -> dict[str, Any]:
    """Rebuild the decoded response, ignoring explicit missing-field sentinels."""

    node_rows = [
        row
        for row in frame.to_dicts()
        if row["record_kind"] == "json_node" and row["presence_kind"] != "missing"
    ]
    values: dict[int, object] = {}
    root: object | None = None
    for row in node_rows:
        ordinal = cast("int", row["node_ordinal"])
        kind = row["value_kind"]
        if kind == "object":
            value: object = {}
        elif kind == "array":
            value = []
        else:
            value = json.loads(cast("str", row["canonical_json"]))
        values[ordinal] = value
        parent_ordinal = row["parent_node_ordinal"]
        if parent_ordinal is None:
            if root is not None:
                raise ResponseContractError("live lossless frame contains multiple roots")
            root = value
            continue
        parent = values.get(cast("int", parent_ordinal))
        object_key = row["object_key"]
        array_ordinal = row["array_ordinal"]
        if isinstance(parent, dict) and isinstance(object_key, str):
            cast("dict[str, object]", parent)[object_key] = value
        elif isinstance(parent, list) and isinstance(array_ordinal, int):
            parent_list = cast("list[object]", parent)
            if array_ordinal != len(parent_list):
                raise ResponseContractError("live lossless array ordinals are not contiguous")
            parent_list.append(value)
        else:
            raise ResponseContractError("live lossless child edge is invalid")
    if not isinstance(root, dict):
        raise ResponseContractError("live lossless response root must be an object")
    return root


def project_known_live_container(
    value: object,
    *,
    result_set: LiveResultSetContract,
    contract: LiveEndpointContract,
) -> object:
    """Return the pinned wide projection while excluding additive drift nodes."""

    child_by_field = {
        child.parent_field_name: child
        for child in contract.result_sets
        if child.parent_result_set_name == result_set.name and child.parent_field_name is not None
    }
    known_fields = {field.name for field in result_set.fields} | set(child_by_field)

    def project_record(record: object) -> object:
        if not isinstance(record, Mapping):
            return record
        output: dict[str, object] = {}
        for raw_key, child_value in record.items():
            key = cast("str", raw_key)
            if key not in known_fields:
                continue
            child_contract = child_by_field.get(key)
            output[key] = (
                project_known_live_container(
                    child_value,
                    result_set=child_contract,
                    contract=contract,
                )
                if child_contract is not None and child_value is not None
                else child_value
            )
        return output

    if result_set.container_kind == "nba_api_live_json_array":
        if not isinstance(value, list):
            return value
        return [project_record(item) for item in value]
    return project_record(value)


__all__ = [
    "LIVE_LOSSLESS_SCHEMA",
    "LIVE_LOSSLESS_STAGING_KEY",
    "NbaApiLiveLosslessLanding",
    "build_live_lossless_landing",
    "project_known_live_container",
    "reconstruct_live_payload",
    "validate_live_lossless_frame",
]
