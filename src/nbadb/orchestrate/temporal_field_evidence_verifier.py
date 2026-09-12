"""Independent verifier for nonterminal temporal-field evidence candidates.

The implementation deliberately imports no primary contract and no ``nbadb``
helper.  It independently parses exact canonical bytes for the parent
candidate/proof, raw assertion-only observations, and the observed candidate;
reconstructs the complete denominator and all evidence partitions; and requires
exact observed-byte equality.  Its proof is candidate-only and always denies
denominator admission, terminality, and release eligibility.
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from typing import TYPE_CHECKING, ClassVar, Literal, Self, cast

if TYPE_CHECKING:
    from collections.abc import Mapping

__all__ = [
    "IndependentTemporalFieldEvidenceError",
    "TemporalFieldEvidenceIndependentProofV1",
    "verify_temporal_field_evidence_candidate_independently",
]

_SCHEMA_VERSION = 1
_SHA256_RE = re.compile(r"[0-9a-f]{64}")
_SAFE_ID_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.:/#-]{0,511}")
_SEASON_RE = re.compile(r"([0-9]{4})-([0-9]{2})")
_DATE_RE = re.compile(r"([0-9]{4})-([0-9]{2})-([0-9]{2})")
_GAME_ID_RE = re.compile(r"[0-9]{10}")
_TEMPORAL_KINDS = frozenset(
    {
        "season",
        "season_type",
        "game_date",
        "game_id",
        "calendar_year",
        "competition",
        "runtime_scope",
    }
)
_OBSERVATION_STATES = frozenset(
    {
        "result_missing",
        "field_missing",
        "null",
        "present_empty",
        "populated",
        "valid_empty",
        "unknown",
        "transient",
    }
)
_UNJOINABLE_REASONS = frozenset(
    {
        "parent_candidate_mismatch",
        "authority_mismatch",
        "cell_absent",
        "cell_identity_mismatch",
    }
)
_MAX_TEXT = 1_024
_MAX_PATH_SEGMENTS = 64
_MAX_PARAMETERS = 4_096
_MAX_CELLS = 5_000_000
_MAX_OBSERVATIONS = 10_000_000
_MAX_CANONICAL_BYTES = 256 * 1024 * 1024


class IndependentTemporalFieldEvidenceError(ValueError):
    """Raised when independent reconstruction disagrees or input is malformed."""


def _canonical_bytes(value: object) -> bytes:
    try:
        return json.dumps(
            value,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=True,
            allow_nan=False,
        ).encode("utf-8")
    except (TypeError, ValueError, RecursionError) as exc:
        raise IndependentTemporalFieldEvidenceError(
            "independent temporal-field input is not canonical JSON data"
        ) from exc


def _sha256(value: object) -> str:
    return hashlib.sha256(_canonical_bytes(value)).hexdigest()


def _sha256_bytes(value: bytes) -> str:
    if type(value) is not bytes:
        raise IndependentTemporalFieldEvidenceError("digest input must be exact bytes")
    return hashlib.sha256(value).hexdigest()


def _exact_typed_equal(left: object, right: object) -> bool:
    if type(left) is not type(right):
        return False
    if type(left) is dict:
        left_map = cast("dict[object, object]", left)
        right_map = cast("dict[object, object]", right)
        return set(left_map) == set(right_map) and all(
            _exact_typed_equal(left_map[key], right_map[key]) for key in left_map
        )
    if type(left) in {list, tuple}:
        left_values = cast("list[object] | tuple[object, ...]", left)
        right_values = cast("list[object] | tuple[object, ...]", right)
        return len(left_values) == len(right_values) and all(
            _exact_typed_equal(first, second)
            for first, second in zip(left_values, right_values, strict=True)
        )
    return left == right


def _mapping(value: object, *, label: str) -> dict[str, object]:
    if type(value) is not dict or any(type(key) is not str for key in value):
        raise IndependentTemporalFieldEvidenceError(f"{label} must be an exact string-keyed object")
    return cast("dict[str, object]", value)


def _array(value: object, *, label: str, maximum: int) -> list[object]:
    if type(value) is not list or len(value) > maximum:
        raise IndependentTemporalFieldEvidenceError(f"{label} must be an exact bounded array")
    return cast("list[object]", value)


def _exact_keys(
    payload: Mapping[str, object],
    *,
    expected: frozenset[str],
    label: str,
) -> None:
    if type(payload) is not dict or frozenset(payload) != expected:
        raise IndependentTemporalFieldEvidenceError(f"{label} has missing or unexpected fields")


def _sha(value: object, *, label: str) -> str:
    if type(value) is not str or _SHA256_RE.fullmatch(value) is None:
        raise IndependentTemporalFieldEvidenceError(f"{label} must be an exact lowercase SHA-256")
    return value


def _safe_id(value: object, *, label: str) -> str:
    if type(value) is not str or _SAFE_ID_RE.fullmatch(value) is None:
        raise IndependentTemporalFieldEvidenceError(
            f"{label} must be an exact bounded safe identifier"
        )
    return value


def _text(value: object, *, label: str) -> str:
    if (
        type(value) is not str
        or not value
        or len(value) > _MAX_TEXT
        or any(ord(character) < 0x20 for character in value)
    ):
        raise IndependentTemporalFieldEvidenceError(
            f"{label} must be exact bounded non-control text"
        )
    return value


def _nonnegative_int(value: object, *, label: str) -> int:
    if type(value) is not int or value < 0:
        raise IndependentTemporalFieldEvidenceError(f"{label} must be a nonnegative integer")
    return value


def _schema(payload: Mapping[str, object], *, kind: str, label: str) -> None:
    if (
        type(payload.get("schema_version")) is not int
        or payload.get("schema_version") != _SCHEMA_VERSION
        or type(payload.get("kind")) is not str
        or payload.get("kind") != kind
    ):
        raise IndependentTemporalFieldEvidenceError(f"{label} schema identity is invalid")


def _decode_canonical_mapping(raw: bytes, *, label: str) -> dict[str, object]:
    if type(raw) is not bytes or not raw or len(raw) > _MAX_CANONICAL_BYTES:
        raise IndependentTemporalFieldEvidenceError(f"{label} canonical byte length is invalid")

    def reject_duplicates(pairs: list[tuple[str, object]]) -> dict[str, object]:
        result: dict[str, object] = {}
        for key, value in pairs:
            if key in result:
                raise IndependentTemporalFieldEvidenceError(
                    f"{label} canonical JSON contains duplicate keys"
                )
            result[key] = value
        return result

    try:
        decoded = json.loads(
            raw.decode("utf-8", errors="strict"),
            object_pairs_hook=reject_duplicates,
            parse_constant=lambda _value: (_ for _ in ()).throw(
                IndependentTemporalFieldEvidenceError(
                    f"{label} canonical JSON contains a non-finite number"
                )
            ),
        )
    except IndependentTemporalFieldEvidenceError:
        raise
    except (UnicodeDecodeError, json.JSONDecodeError, RecursionError) as exc:
        raise IndependentTemporalFieldEvidenceError(
            f"{label} canonical input is not valid JSON"
        ) from exc
    payload = _mapping(decoded, label=f"{label} canonical root")
    if _canonical_bytes(payload) != raw:
        raise IndependentTemporalFieldEvidenceError(f"{label} input is not exact canonical JSON")
    return payload


def _sorted_unique(
    items: list[dict[str, object]],
    *,
    identity_name: str,
    label: str,
) -> list[dict[str, object]]:
    identities = tuple(cast("str", item[identity_name]) for item in items)
    if identities != tuple(sorted(set(identities))):
        raise IndependentTemporalFieldEvidenceError(
            f"{label} must use canonical sorted unique order"
        )
    return items


def _period(kind: object, value: object) -> tuple[str, str | int]:
    if type(kind) is not str or kind not in _TEMPORAL_KINDS:
        raise IndependentTemporalFieldEvidenceError("temporal_scope_kind is invalid")
    if kind == "season":
        text = _text(value, label="season")
        match = _SEASON_RE.fullmatch(text)
        if match is None or int(match.group(2)) != (int(match.group(1)) + 1) % 100:
            raise IndependentTemporalFieldEvidenceError("season value is invalid")
        return kind, text
    if kind == "game_date":
        text = _text(value, label="game_date")
        match = _DATE_RE.fullmatch(text)
        if match is None:
            raise IndependentTemporalFieldEvidenceError("game_date value is invalid")
        year, month, day = (int(part) for part in match.groups())
        try:
            __import__("datetime").date(year, month, day)
        except ValueError as exc:
            raise IndependentTemporalFieldEvidenceError(
                "game_date value is not a calendar date"
            ) from exc
        return kind, text
    if kind == "game_id":
        text = _text(value, label="game_id")
        if _GAME_ID_RE.fullmatch(text) is None:
            raise IndependentTemporalFieldEvidenceError("game_id value is invalid")
        return kind, text
    if kind == "calendar_year":
        if type(value) is not int or value < 1946 or value > 9999:
            raise IndependentTemporalFieldEvidenceError("calendar_year value is invalid")
        return kind, value
    text = _text(value, label=f"{kind} value")
    if len(text) > 256:
        raise IndependentTemporalFieldEvidenceError(f"{kind} value exceeds the bound")
    return kind, text


def _parameter_value(value: object, *, label: str) -> object:
    if value is None or type(value) in {str, int, bool}:
        if type(value) is str and len(value) > _MAX_TEXT:
            raise IndependentTemporalFieldEvidenceError(f"{label} exceeds the string bound")
        return value
    if type(value) is list:
        result = _array(value, label=label, maximum=_MAX_PARAMETERS)
        for item in result:
            if item is not None and type(item) not in {str, int, bool}:
                raise IndependentTemporalFieldEvidenceError(f"{label} contains a non-scalar value")
            if type(item) is str and len(item) > _MAX_TEXT:
                raise IndependentTemporalFieldEvidenceError(f"{label} contains an oversized string")
        return result
    raise IndependentTemporalFieldEvidenceError(f"{label} must be an exact scalar or scalar array")


def _parameters(value: object) -> list[dict[str, object]]:
    raw_items = _array(value, label="parameter_items", maximum=_MAX_PARAMETERS)
    result: list[dict[str, object]] = []
    for raw in raw_items:
        item = _mapping(raw, label="parameter item")
        _exact_keys(
            item,
            expected=frozenset({"name", "value"}),
            label="parameter item",
        )
        name = _safe_id(item["name"], label="parameter name")
        result.append(
            {
                "name": name,
                "value": _parameter_value(item["value"], label=f"parameter {name}"),
            }
        )
    names = tuple(cast("str", item["name"]) for item in result)
    if names != tuple(sorted(set(names))):
        raise IndependentTemporalFieldEvidenceError(
            "parameter names must be canonical sorted and unique"
        )
    return result


_CALL_FIELDS = frozenset(
    {
        "schema_version",
        "kind",
        "authority_generation_sha256",
        "physical_call_id",
        "source_family",
        "endpoint_name",
        "canonical_endpoint_name",
        "physical_endpoint_name",
        "parameter_items",
        "parameters_complete",
        "pagination_kind",
        "pagination_value",
        "dependent_workload_kind",
        "dependent_workload_sha256",
        "dependent_physical_alias",
        "request_scope_sha256",
    }
)


def _call(raw: object, *, authority: str) -> dict[str, object]:
    item = _mapping(raw, label="logical request call")
    _exact_keys(item, expected=_CALL_FIELDS, label="logical request call")
    _schema(item, kind="logical_request_call_v1", label="logical request call")
    if _sha(item["authority_generation_sha256"], label="logical call authority") != authority:
        raise IndependentTemporalFieldEvidenceError("logical call uses mixed authority")
    for name in (
        "source_family",
        "endpoint_name",
        "canonical_endpoint_name",
        "physical_endpoint_name",
    ):
        _safe_id(item[name], label=name)
    parameters = _parameters(item["parameter_items"])
    if item["parameters_complete"] is not True:
        raise IndependentTemporalFieldEvidenceError(
            "logical request parameter set is not explicitly complete"
        )
    pagination_kind = item["pagination_kind"]
    pagination_value = item["pagination_value"]
    if type(pagination_kind) is not str or pagination_kind not in {"none", "page", "cursor"}:
        raise IndependentTemporalFieldEvidenceError("pagination kind is invalid")
    if pagination_kind == "none":
        if pagination_value is not None:
            raise IndependentTemporalFieldEvidenceError(
                "non-paginated call carries a pagination value"
            )
    elif type(pagination_value) not in {str, int}:
        raise IndependentTemporalFieldEvidenceError(
            "paginated call lacks an exact pagination value"
        )
    elif type(pagination_value) is str:
        _text(pagination_value, label="pagination value")
    elif cast("int", pagination_value) < 0:
        raise IndependentTemporalFieldEvidenceError("integer pagination value is negative")
    dependent = (
        item["dependent_workload_kind"],
        item["dependent_workload_sha256"],
        item["dependent_physical_alias"],
    )
    if any(value is None for value in dependent) and any(value is not None for value in dependent):
        raise IndependentTemporalFieldEvidenceError("dependent workload identity is partial")
    if dependent[0] is not None:
        _safe_id(dependent[0], label="dependent workload kind")
        _sha(dependent[1], label="dependent workload SHA-256")
        _safe_id(dependent[2], label="dependent physical alias")
    body = {
        "schema_version": _SCHEMA_VERSION,
        "kind": "logical_request_call_v1",
        "authority_generation_sha256": authority,
        "source_family": item["source_family"],
        "endpoint_name": item["endpoint_name"],
        "canonical_endpoint_name": item["canonical_endpoint_name"],
        "physical_endpoint_name": item["physical_endpoint_name"],
        "parameter_items": parameters,
        "parameters_complete": True,
        "pagination_kind": pagination_kind,
        "pagination_value": pagination_value,
        "dependent_workload_kind": dependent[0],
        "dependent_workload_sha256": dependent[1],
        "dependent_physical_alias": dependent[2],
    }
    scope_sha = _sha256(body)
    if not _exact_typed_equal(item["request_scope_sha256"], scope_sha):
        raise IndependentTemporalFieldEvidenceError(
            "logical call scope digest differs from independently derived scope"
        )
    physical_call_id = f"physical-call-v1:{scope_sha}"
    if not _exact_typed_equal(item["physical_call_id"], physical_call_id):
        raise IndependentTemporalFieldEvidenceError(
            "physical call ID differs from independently derived scope"
        )
    return {**body, "physical_call_id": physical_call_id, "request_scope_sha256": scope_sha}


_ROUTE_FIELDS = frozenset(
    {
        "schema_version",
        "kind",
        "authority_generation_sha256",
        "route_request_member_id",
        "physical_call_id",
        "request_scope_sha256",
        "route_id",
        "endpoint_name",
        "result_name",
        "result_ordinal",
        "nested_path",
    }
)


def _route(raw: object, *, authority: str) -> dict[str, object]:
    item = _mapping(raw, label="route request member")
    _exact_keys(item, expected=_ROUTE_FIELDS, label="route request member")
    _schema(item, kind="route_request_member_v1", label="route request member")
    if _sha(item["authority_generation_sha256"], label="route authority") != authority:
        raise IndependentTemporalFieldEvidenceError("route member uses mixed authority")
    physical_call_id = _safe_id(item["physical_call_id"], label="physical_call_id")
    request_scope_sha256 = _sha(item["request_scope_sha256"], label="request_scope_sha256")
    route_id = _safe_id(item["route_id"], label="route_id")
    endpoint_name = _safe_id(item["endpoint_name"], label="endpoint_name")
    result_name = _text(item["result_name"], label="result_name")
    result_ordinal = _nonnegative_int(item["result_ordinal"], label="result_ordinal")
    path = _nested_path(item["nested_path"])
    body = {
        "schema_version": _SCHEMA_VERSION,
        "kind": "route_request_member_v1",
        "authority_generation_sha256": authority,
        "physical_call_id": physical_call_id,
        "request_scope_sha256": request_scope_sha256,
        "route_id": route_id,
        "endpoint_name": endpoint_name,
        "result_name": result_name,
        "result_ordinal": result_ordinal,
        "nested_path": path,
    }
    member_id = f"route-member-v1:{_sha256(body)}"
    if not _exact_typed_equal(item["route_request_member_id"], member_id):
        raise IndependentTemporalFieldEvidenceError(
            "route member ID differs from independently derived identity"
        )
    return {**body, "route_request_member_id": member_id}


_PARENT_CELL_FIELDS = frozenset(
    {
        "schema_version",
        "kind",
        "authority_generation_sha256",
        "cell_id",
        "physical_call_id",
        "route_request_member_id",
        "route_id",
        "endpoint_name",
        "result_name",
        "result_ordinal",
        "nested_path",
        "provider_field",
        "field_occurrence_ordinal",
        "request_scope_sha256",
        "field_fate_contract_sha256",
        "temporal_contract_sha256",
        "temporal_scope_kind",
        "temporal_scope_value",
        "state",
    }
)


def _nested_path(value: object) -> list[str | int]:
    raw = _array(value, label="nested_path", maximum=_MAX_PATH_SEGMENTS)
    result: list[str | int] = []
    for segment in raw:
        if type(segment) is int:
            result.append(_nonnegative_int(segment, label="nested_path index"))
        else:
            result.append(_text(segment, label="nested_path segment"))
    return result


def _parent_cell(
    raw: object,
    *,
    authority: str,
    field_digest: str,
    temporal_digest: str,
) -> dict[str, object]:
    item = _mapping(raw, label="parent field-period cell")
    _exact_keys(item, expected=_PARENT_CELL_FIELDS, label="parent field-period cell")
    _schema(
        item,
        kind="field_period_denominator_cell_v1",
        label="parent field-period cell",
    )
    if _sha(item["authority_generation_sha256"], label="parent cell authority") != authority:
        raise IndependentTemporalFieldEvidenceError("parent cell uses mixed authority")
    _safe_id(item["cell_id"], label="cell_id")
    for name in (
        "physical_call_id",
        "route_request_member_id",
        "route_id",
        "endpoint_name",
    ):
        _safe_id(item[name], label=name)
    _text(item["result_name"], label="result_name")
    _nonnegative_int(item["result_ordinal"], label="result_ordinal")
    _nested_path(item["nested_path"])
    _text(item["provider_field"], label="provider_field")
    _nonnegative_int(item["field_occurrence_ordinal"], label="field_occurrence_ordinal")
    request_scope_sha256 = _sha(item["request_scope_sha256"], label="request_scope_sha256")
    if _sha(item["field_fate_contract_sha256"], label="field fate authority") != field_digest:
        raise IndependentTemporalFieldEvidenceError("parent cell uses mixed field-fate authority")
    if _sha(item["temporal_contract_sha256"], label="temporal authority") != temporal_digest:
        raise IndependentTemporalFieldEvidenceError("parent cell uses mixed temporal authority")
    scope_kind, scope_value = _period(
        item["temporal_scope_kind"],
        item["temporal_scope_value"],
    )
    if type(item["state"]) is not str or item["state"] != "evidence_insufficient":
        raise IndependentTemporalFieldEvidenceError(
            "parent field-period state is not evidence_insufficient"
        )
    body = {
        "schema_version": _SCHEMA_VERSION,
        "kind": "field_period_denominator_cell_v1",
        "authority_generation_sha256": authority,
        "physical_call_id": item["physical_call_id"],
        "route_request_member_id": item["route_request_member_id"],
        "route_id": item["route_id"],
        "endpoint_name": item["endpoint_name"],
        "result_name": item["result_name"],
        "result_ordinal": item["result_ordinal"],
        "nested_path": _nested_path(item["nested_path"]),
        "provider_field": item["provider_field"],
        "field_occurrence_ordinal": item["field_occurrence_ordinal"],
        "request_scope_sha256": request_scope_sha256,
        "field_fate_contract_sha256": field_digest,
        "temporal_contract_sha256": temporal_digest,
        "temporal_scope_kind": scope_kind,
        "temporal_scope_value": scope_value,
        "state": "evidence_insufficient",
    }
    expected_cell_id = f"field-period-cell-v1:{_sha256(body)}"
    if not _exact_typed_equal(item["cell_id"], expected_cell_id):
        raise IndependentTemporalFieldEvidenceError(
            "parent cell identifier differs from its full identity"
        )
    return {**body, "cell_id": expected_cell_id}


_BLOCKER_FIELDS = frozenset(
    {
        "authority_generation_sha256",
        "blocker_code",
        "subject_id",
        "evidence_sha256",
    }
)


def _blocker(raw: object, *, authority: str) -> dict[str, object]:
    item = _mapping(raw, label="parent blocker")
    _exact_keys(item, expected=_BLOCKER_FIELDS, label="parent blocker")
    if _sha(item["authority_generation_sha256"], label="blocker authority") != authority:
        raise IndependentTemporalFieldEvidenceError("parent blocker uses mixed authority")
    return {
        "authority_generation_sha256": authority,
        "blocker_code": _safe_id(item["blocker_code"], label="blocker_code"),
        "subject_id": _safe_id(item["subject_id"], label="subject_id"),
        "evidence_sha256": _sha(item["evidence_sha256"], label="evidence_sha256"),
    }


_PARENT_FIELDS = frozenset(
    {
        "schema_version",
        "kind",
        "authority_generation_sha256",
        "source_inputs_sha256",
        "field_fate_contract_sha256",
        "temporal_contract_sha256",
        "logical_call_count",
        "route_member_count",
        "field_period_cell_count",
        "blocker_count",
        "logical_call_inventory_sha256",
        "route_member_inventory_sha256",
        "field_period_inventory_sha256",
        "blocker_inventory_sha256",
        "logical_calls",
        "route_members",
        "field_period_cells",
        "blockers",
        "terminal",
        "release_eligible",
    }
)


def _parent_candidate(payload: Mapping[str, object]) -> dict[str, object]:
    item = _mapping(payload, label="parent candidate")
    _exact_keys(item, expected=_PARENT_FIELDS, label="parent candidate")
    _schema(
        item,
        kind="request_universe_candidate_generation_v1",
        label="parent candidate",
    )
    authority = _sha(item["authority_generation_sha256"], label="authority generation")
    source_inputs_sha256 = _sha(item["source_inputs_sha256"], label="source_inputs_sha256")
    field_digest = _sha(
        item["field_fate_contract_sha256"],
        label="field_fate_contract_sha256",
    )
    temporal_digest = _sha(
        item["temporal_contract_sha256"],
        label="temporal_contract_sha256",
    )
    for name in (
        "logical_call_inventory_sha256",
        "route_member_inventory_sha256",
        "field_period_inventory_sha256",
        "blocker_inventory_sha256",
    ):
        _sha(item[name], label=name)
    if item["terminal"] is not False or item["release_eligible"] is not False:
        raise IndependentTemporalFieldEvidenceError("parent candidate falsely attests finality")
    calls = [
        _call(raw, authority=authority)
        for raw in _array(
            item["logical_calls"],
            label="logical_calls",
            maximum=_MAX_OBSERVATIONS,
        )
    ]
    routes = [
        _route(raw, authority=authority)
        for raw in _array(
            item["route_members"],
            label="route_members",
            maximum=_MAX_OBSERVATIONS,
        )
    ]
    if not calls or not routes:
        raise IndependentTemporalFieldEvidenceError(
            "parent candidate calls and routes must be nonempty"
        )
    cells = [
        _parent_cell(
            raw,
            authority=authority,
            field_digest=field_digest,
            temporal_digest=temporal_digest,
        )
        for raw in _array(
            item["field_period_cells"],
            label="field_period_cells",
            maximum=_MAX_CELLS,
        )
    ]
    blockers = [
        _blocker(raw, authority=authority)
        for raw in _array(item["blockers"], label="blockers", maximum=_MAX_OBSERVATIONS)
    ]
    _sorted_unique(calls, identity_name="physical_call_id", label="parent logical calls")
    _sorted_unique(
        routes,
        identity_name="route_request_member_id",
        label="parent route members",
    )
    _sorted_unique(cells, identity_name="cell_id", label="parent cells")
    blocker_digests = tuple(_sha256(blocker) for blocker in blockers)
    if blocker_digests != tuple(sorted(set(blocker_digests))):
        raise IndependentTemporalFieldEvidenceError(
            "parent blockers must use canonical sorted unique order"
        )
    call_by_id = {cast("str", call["physical_call_id"]): call for call in calls}
    route_by_id = {cast("str", route["route_request_member_id"]): route for route in routes}
    for route in routes:
        call = call_by_id.get(cast("str", route["physical_call_id"]))
        if call is None or not _exact_typed_equal(
            (route["request_scope_sha256"], route["endpoint_name"]),
            (call["request_scope_sha256"], call["endpoint_name"]),
        ):
            raise IndependentTemporalFieldEvidenceError(
                "parent route member differs from its exact physical call"
            )
    for cell in cells:
        route = route_by_id.get(cast("str", cell["route_request_member_id"]))
        if route is None or not _exact_typed_equal(
            (
                cell["physical_call_id"],
                cell["request_scope_sha256"],
                cell["route_id"],
                cell["endpoint_name"],
                cell["result_name"],
                cell["result_ordinal"],
                cell["nested_path"],
            ),
            (
                route["physical_call_id"],
                route["request_scope_sha256"],
                route["route_id"],
                route["endpoint_name"],
                route["result_name"],
                route["result_ordinal"],
                route["nested_path"],
            ),
        ):
            raise IndependentTemporalFieldEvidenceError(
                "parent cell differs from its exact route member"
            )
    inventories = (
        ("logical_calls", "logical_call_count", "logical_call_inventory_sha256", calls),
        ("route_members", "route_member_count", "route_member_inventory_sha256", routes),
        (
            "field_period_cells",
            "field_period_cell_count",
            "field_period_inventory_sha256",
            cells,
        ),
        ("blockers", "blocker_count", "blocker_inventory_sha256", blockers),
    )
    for label, count_name, digest_name, inventory in inventories:
        observed_count = _nonnegative_int(item[count_name], label=count_name)
        if observed_count != len(inventory) or not _exact_typed_equal(
            item[digest_name],
            _sha256(inventory),
        ):
            raise IndependentTemporalFieldEvidenceError(
                f"parent {label} count or digest is inconsistent"
            )
    fixed_point = {
        "authority_generation_sha256": authority,
        "blocker_code": "candidate_not_fixed_point",
        "subject_id": "request_universe_candidate_generation_v1",
        "evidence_sha256": source_inputs_sha256,
    }
    if fixed_point not in blockers:
        raise IndependentTemporalFieldEvidenceError(
            "parent candidate lacks its non-fixed-point blocker"
        )
    return {
        "schema_version": _SCHEMA_VERSION,
        "kind": "request_universe_candidate_generation_v1",
        "authority_generation_sha256": authority,
        "source_inputs_sha256": source_inputs_sha256,
        "field_fate_contract_sha256": field_digest,
        "temporal_contract_sha256": temporal_digest,
        "logical_call_count": len(calls),
        "route_member_count": len(routes),
        "field_period_cell_count": len(cells),
        "blocker_count": len(blockers),
        "logical_call_inventory_sha256": _sha256(calls),
        "route_member_inventory_sha256": _sha256(routes),
        "field_period_inventory_sha256": _sha256(cells),
        "blocker_inventory_sha256": _sha256(blockers),
        "logical_calls": calls,
        "route_members": routes,
        "field_period_cells": cells,
        "blockers": blockers,
        "terminal": False,
        "release_eligible": False,
    }


_PARENT_PROOF_FIELDS = frozenset(
    {
        "schema_version",
        "kind",
        "authority_generation_sha256",
        "source_inputs_sha256",
        "candidate_generation_sha256",
        "logical_call_inventory_sha256",
        "route_member_inventory_sha256",
        "field_period_inventory_sha256",
        "blocker_inventory_sha256",
        "logical_call_count",
        "route_member_count",
        "field_period_cell_count",
        "blocker_count",
        "exact_inventory_equal",
        "candidate_only",
        "terminal",
        "release_eligible",
        "verifier_id",
    }
)


def _parent_proof(
    payload: Mapping[str, object],
    *,
    candidate: Mapping[str, object],
) -> dict[str, object]:
    item = _mapping(payload, label="parent proof")
    _exact_keys(item, expected=_PARENT_PROOF_FIELDS, label="parent proof")
    _schema(
        item,
        kind="request_universe_candidate_independent_proof_v1",
        label="parent proof",
    )
    if (
        type(item["verifier_id"]) is not str
        or item["verifier_id"] != "independent_request_universe_candidate_v1"
        or item["exact_inventory_equal"] is not True
        or item["candidate_only"] is not True
        or item["terminal"] is not False
        or item["release_eligible"] is not False
    ):
        raise IndependentTemporalFieldEvidenceError("parent proof falsely attests authority")
    bindings = {
        "authority_generation_sha256": candidate["authority_generation_sha256"],
        "source_inputs_sha256": candidate["source_inputs_sha256"],
        "candidate_generation_sha256": _sha256(candidate),
        "logical_call_inventory_sha256": candidate["logical_call_inventory_sha256"],
        "route_member_inventory_sha256": candidate["route_member_inventory_sha256"],
        "field_period_inventory_sha256": candidate["field_period_inventory_sha256"],
        "blocker_inventory_sha256": candidate["blocker_inventory_sha256"],
        "logical_call_count": candidate["logical_call_count"],
        "route_member_count": candidate["route_member_count"],
        "field_period_cell_count": candidate["field_period_cell_count"],
        "blocker_count": candidate["blocker_count"],
    }
    for name, expected in bindings.items():
        if name.endswith("_count"):
            _nonnegative_int(item[name], label=f"parent proof {name}")
        else:
            _sha(item[name], label=f"parent proof {name}")
        if not _exact_typed_equal(item[name], expected):
            raise IndependentTemporalFieldEvidenceError(
                f"parent proof {name} differs from the exact candidate"
            )
    return {
        "schema_version": _SCHEMA_VERSION,
        "kind": "request_universe_candidate_independent_proof_v1",
        **bindings,
        "exact_inventory_equal": True,
        "candidate_only": True,
        "terminal": False,
        "release_eligible": False,
        "verifier_id": "independent_request_universe_candidate_v1",
    }


_OBSERVATION_FIELDS = frozenset(
    {
        "schema_version",
        "kind",
        "parent_candidate_sha256",
        "authority_generation_sha256",
        "observation_id",
        "cell_id",
        "physical_call_id",
        "route_request_member_id",
        "route_id",
        "endpoint_name",
        "result_name",
        "result_ordinal",
        "nested_path",
        "provider_field",
        "field_occurrence_ordinal",
        "request_scope_sha256",
        "field_fate_contract_sha256",
        "temporal_contract_sha256",
        "temporal_scope_kind",
        "temporal_scope_value",
        "state",
        "raw_authority_bundle_sha256",
        "request_observation_sha256",
        "provider_call_sha256",
        "provider_request_sha256",
        "result_occurrence_sha256",
        "logical_result_receipt_sha256",
        "route_receipt_sha256",
        "typed_value_receipt_sha256",
        "reconstruction_receipt_sha256",
        "proofs_equal",
    }
)


def _observation(raw: object) -> dict[str, object]:
    item = _mapping(raw, label="field observation")
    _exact_keys(item, expected=_OBSERVATION_FIELDS, label="field observation")
    _schema(item, kind="field_observation_binding_v1", label="field observation")
    parent_candidate_sha256 = _sha(
        item["parent_candidate_sha256"],
        label="parent_candidate_sha256",
    )
    authority_generation_sha256 = _sha(
        item["authority_generation_sha256"],
        label="authority_generation_sha256",
    )
    cell_id = _safe_id(item["cell_id"], label="cell_id")
    physical_call_id = _safe_id(item["physical_call_id"], label="physical_call_id")
    route_request_member_id = _safe_id(
        item["route_request_member_id"],
        label="route_request_member_id",
    )
    route_id = _safe_id(item["route_id"], label="route_id")
    endpoint_name = _safe_id(item["endpoint_name"], label="endpoint_name")
    result_name = _text(item["result_name"], label="result_name")
    result_ordinal = _nonnegative_int(item["result_ordinal"], label="result_ordinal")
    nested_path = _nested_path(item["nested_path"])
    provider_field = _text(item["provider_field"], label="provider_field")
    field_occurrence_ordinal = _nonnegative_int(
        item["field_occurrence_ordinal"],
        label="field_occurrence_ordinal",
    )
    digest_names = (
        "request_scope_sha256",
        "field_fate_contract_sha256",
        "temporal_contract_sha256",
        "raw_authority_bundle_sha256",
        "request_observation_sha256",
        "provider_call_sha256",
        "provider_request_sha256",
        "result_occurrence_sha256",
        "logical_result_receipt_sha256",
        "route_receipt_sha256",
        "typed_value_receipt_sha256",
        "reconstruction_receipt_sha256",
    )
    digests = {name: _sha(item[name], label=name) for name in digest_names}
    temporal_scope_kind, temporal_scope_value = _period(
        item["temporal_scope_kind"],
        item["temporal_scope_value"],
    )
    if type(item["state"]) is not str or item["state"] not in _OBSERVATION_STATES:
        raise IndependentTemporalFieldEvidenceError("field observation state is invalid")
    if item["proofs_equal"] is not True:
        raise IndependentTemporalFieldEvidenceError(
            "field observation does not bind equal proof paths"
        )
    identity = {
        "schema_version": _SCHEMA_VERSION,
        "kind": "field_observation_binding_v1",
        "parent_candidate_sha256": parent_candidate_sha256,
        "authority_generation_sha256": authority_generation_sha256,
        "cell_id": cell_id,
        "physical_call_id": physical_call_id,
        "route_request_member_id": route_request_member_id,
        "route_id": route_id,
        "endpoint_name": endpoint_name,
        "result_name": result_name,
        "result_ordinal": result_ordinal,
        "nested_path": nested_path,
        "provider_field": provider_field,
        "field_occurrence_ordinal": field_occurrence_ordinal,
        **digests,
        "temporal_scope_kind": temporal_scope_kind,
        "temporal_scope_value": temporal_scope_value,
        "state": item["state"],
        "proofs_equal": True,
    }
    expected_id = f"field-observation-v1:{_sha256(identity)}"
    if not _exact_typed_equal(item["observation_id"], expected_id):
        raise IndependentTemporalFieldEvidenceError(
            "field observation identifier differs from its receipts"
        )
    return {**identity, "observation_id": expected_id}


def _observation_identity(item: Mapping[str, object]) -> tuple[object, ...]:
    return (
        item["cell_id"],
        item["physical_call_id"],
        item["route_request_member_id"],
        item["route_id"],
        item["endpoint_name"],
        item["result_name"],
        item["result_ordinal"],
        tuple(cast("list[object]", item["nested_path"])),
        item["provider_field"],
        item["field_occurrence_ordinal"],
        item["request_scope_sha256"],
        item["field_fate_contract_sha256"],
        item["temporal_contract_sha256"],
        item["temporal_scope_kind"],
        item["temporal_scope_value"],
    )


def _parent_cell_identity(item: Mapping[str, object]) -> tuple[object, ...]:
    return (
        item["cell_id"],
        item["physical_call_id"],
        item["route_request_member_id"],
        item["route_id"],
        item["endpoint_name"],
        item["result_name"],
        item["result_ordinal"],
        tuple(cast("list[object]", item["nested_path"])),
        item["provider_field"],
        item["field_occurrence_ordinal"],
        item["request_scope_sha256"],
        item["field_fate_contract_sha256"],
        item["temporal_contract_sha256"],
        item["temporal_scope_kind"],
        item["temporal_scope_value"],
    )


def _classification(states: list[str]) -> tuple[str, str]:
    if not states:
        return "evidence_insufficient", "unresolved"
    if len(states) > 1:
        return "evidence_insufficient", "conflict"
    if states[0] not in _OBSERVATION_STATES:
        raise IndependentTemporalFieldEvidenceError("internal observation state is invalid")
    return "evidence_insufficient", "unresolved"


def _evidence_cell(
    parent: Mapping[str, object],
    observations: list[dict[str, object]],
) -> dict[str, object]:
    observation_ids = sorted(cast("str", item["observation_id"]) for item in observations)
    states = sorted({cast("str", item["state"]) for item in observations})
    state, disposition = _classification(states)
    return {
        "schema_version": 1,
        "kind": "temporal_field_evidence_cell_v1",
        "authority_generation_sha256": parent["authority_generation_sha256"],
        "parent_cell_sha256": _sha256(parent),
        "cell_id": parent["cell_id"],
        "physical_call_id": parent["physical_call_id"],
        "route_request_member_id": parent["route_request_member_id"],
        "route_id": parent["route_id"],
        "endpoint_name": parent["endpoint_name"],
        "result_name": parent["result_name"],
        "result_ordinal": parent["result_ordinal"],
        "nested_path": parent["nested_path"],
        "provider_field": parent["provider_field"],
        "field_occurrence_ordinal": parent["field_occurrence_ordinal"],
        "request_scope_sha256": parent["request_scope_sha256"],
        "field_fate_contract_sha256": parent["field_fate_contract_sha256"],
        "temporal_contract_sha256": parent["temporal_contract_sha256"],
        "temporal_scope_kind": parent["temporal_scope_kind"],
        "temporal_scope_value": parent["temporal_scope_value"],
        "parent_state": "evidence_insufficient",
        "state": state,
        "disposition": disposition,
        "observation_ids": observation_ids,
        "observed_states": states,
    }


def _unjoinable(observation: Mapping[str, object], reason: str) -> dict[str, object]:
    if reason not in _UNJOINABLE_REASONS:
        raise IndependentTemporalFieldEvidenceError("internal unjoinable reason is invalid")
    return {
        "schema_version": 1,
        "kind": "unjoinable_field_observation_v1",
        "observation_id": observation["observation_id"],
        "cell_id": observation["cell_id"],
        "reason": reason,
        "observation_sha256": _sha256(observation),
    }


def _expected_candidate(
    *,
    parent: Mapping[str, object],
    proof: Mapping[str, object],
    observations: list[dict[str, object]],
) -> dict[str, object]:
    authority = cast("str", parent["authority_generation_sha256"])
    parent_sha = _sha256(parent)
    parent_cells = cast("list[dict[str, object]]", parent["field_period_cells"])
    parent_by_id = {cast("str", item["cell_id"]): item for item in parent_cells}
    by_cell: dict[str, list[dict[str, object]]] = {cell_id: [] for cell_id in parent_by_id}
    joined: list[dict[str, object]] = []
    unjoinable: list[dict[str, object]] = []
    for observation in observations:
        parent_cell = parent_by_id.get(cast("str", observation["cell_id"]))
        reason: str | None = None
        if observation["parent_candidate_sha256"] != parent_sha:
            reason = "parent_candidate_mismatch"
        elif observation["authority_generation_sha256"] != authority:
            reason = "authority_mismatch"
        elif parent_cell is None:
            reason = "cell_absent"
        elif _observation_identity(observation) != _parent_cell_identity(parent_cell):
            reason = "cell_identity_mismatch"
        if reason is not None:
            unjoinable.append(_unjoinable(observation, reason))
            continue
        joined.append(observation)
        by_cell[cast("str", observation["cell_id"])].append(observation)
    evidence_cells = [
        _evidence_cell(cell, by_cell[cast("str", cell["cell_id"])]) for cell in parent_cells
    ]
    evidenced_ids = [
        cast("str", item["cell_id"])
        for item in evidence_cells
        if item["disposition"] == "evidenced"
    ]
    unresolved_ids = [
        cast("str", item["cell_id"])
        for item in evidence_cells
        if item["disposition"] == "unresolved"
    ]
    conflict_ids = [
        cast("str", item["cell_id"]) for item in evidence_cells if item["disposition"] == "conflict"
    ]
    blockers = cast("list[dict[str, object]]", parent["blockers"])
    joined.sort(key=lambda item: cast("str", item["observation_id"]))
    unjoinable.sort(key=lambda item: cast("str", item["observation_id"]))
    return {
        "schema_version": 1,
        "kind": "temporal_field_evidence_candidate_v1",
        "authority_generation_sha256": authority,
        "parent_candidate_sha256": parent_sha,
        "parent_proof_sha256": _sha256(proof),
        "parent_source_inputs_sha256": parent["source_inputs_sha256"],
        "parent_field_period_inventory_sha256": parent["field_period_inventory_sha256"],
        "parent_blocker_inventory_sha256": parent["blocker_inventory_sha256"],
        "denominator_count": len(parent_cells),
        "denominator_inventory_sha256": parent["field_period_inventory_sha256"],
        "evidence_cell_count": len(evidence_cells),
        "joined_observation_count": len(joined),
        "unjoinable_observation_count": len(unjoinable),
        "parent_blocker_count": len(blockers),
        "evidenced_cell_count": len(evidenced_ids),
        "unresolved_cell_count": len(unresolved_ids),
        "conflict_cell_count": len(conflict_ids),
        "evidence_cell_inventory_sha256": _sha256(evidence_cells),
        "joined_observation_inventory_sha256": _sha256(joined),
        "unjoinable_observation_inventory_sha256": _sha256(unjoinable),
        "parent_blocker_inventory_sha256_copy": _sha256(blockers),
        "evidenced_partition_sha256": _sha256(evidenced_ids),
        "unresolved_partition_sha256": _sha256(unresolved_ids),
        "conflict_partition_sha256": _sha256(conflict_ids),
        "evidence_cells": evidence_cells,
        "joined_observations": joined,
        "unjoinable_observations": unjoinable,
        "parent_blockers": blockers,
        "evidenced_cell_ids": evidenced_ids,
        "unresolved_cell_ids": unresolved_ids,
        "conflict_cell_ids": conflict_ids,
        "denominator_admitted": False,
        "terminal": False,
        "release_eligible": False,
    }


@dataclass(frozen=True, slots=True)
class TemporalFieldEvidenceIndependentProofV1:
    """Independent exact-partition proof for a nonterminal evidence candidate."""

    authority_generation_sha256: str
    parent_candidate_sha256: str
    parent_proof_sha256: str
    evidence_candidate_sha256: str
    denominator_inventory_sha256: str
    evidence_cell_inventory_sha256: str
    joined_observation_inventory_sha256: str
    unjoinable_observation_inventory_sha256: str
    denominator_count: int
    evidenced_cell_count: int
    unresolved_cell_count: int
    conflict_cell_count: int
    unjoinable_observation_count: int
    exact_partition_equal: Literal[True]
    candidate_only: Literal[True]
    denominator_admitted: Literal[False]
    terminal: Literal[False]
    release_eligible: Literal[False]
    verifier_id: Literal["independent_temporal_field_evidence_v1"] = (
        "independent_temporal_field_evidence_v1"
    )

    schema_version: ClassVar[int] = _SCHEMA_VERSION
    kind: ClassVar[str] = "temporal_field_evidence_independent_proof_v1"

    def __post_init__(self) -> None:
        for name in (
            "authority_generation_sha256",
            "parent_candidate_sha256",
            "parent_proof_sha256",
            "evidence_candidate_sha256",
            "denominator_inventory_sha256",
            "evidence_cell_inventory_sha256",
            "joined_observation_inventory_sha256",
            "unjoinable_observation_inventory_sha256",
        ):
            _sha(getattr(self, name), label=name)
        for name in (
            "denominator_count",
            "evidenced_cell_count",
            "unresolved_cell_count",
            "conflict_cell_count",
            "unjoinable_observation_count",
        ):
            _nonnegative_int(getattr(self, name), label=name)
        if (
            self.exact_partition_equal is not True
            or self.candidate_only is not True
            or self.denominator_admitted is not False
            or self.terminal is not False
            or self.release_eligible is not False
            or self.verifier_id != "independent_temporal_field_evidence_v1"
        ):
            raise IndependentTemporalFieldEvidenceError(
                "independent proof cannot admit a denominator or finality"
            )

    def to_dict(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "kind": self.kind,
            "authority_generation_sha256": self.authority_generation_sha256,
            "parent_candidate_sha256": self.parent_candidate_sha256,
            "parent_proof_sha256": self.parent_proof_sha256,
            "evidence_candidate_sha256": self.evidence_candidate_sha256,
            "denominator_inventory_sha256": self.denominator_inventory_sha256,
            "evidence_cell_inventory_sha256": self.evidence_cell_inventory_sha256,
            "joined_observation_inventory_sha256": (self.joined_observation_inventory_sha256),
            "unjoinable_observation_inventory_sha256": (
                self.unjoinable_observation_inventory_sha256
            ),
            "denominator_count": self.denominator_count,
            "evidenced_cell_count": self.evidenced_cell_count,
            "unresolved_cell_count": self.unresolved_cell_count,
            "conflict_cell_count": self.conflict_cell_count,
            "unjoinable_observation_count": self.unjoinable_observation_count,
            "exact_partition_equal": self.exact_partition_equal,
            "candidate_only": self.candidate_only,
            "denominator_admitted": self.denominator_admitted,
            "terminal": self.terminal,
            "release_eligible": self.release_eligible,
            "verifier_id": self.verifier_id,
        }

    @property
    def canonical_bytes(self) -> bytes:
        return _canonical_bytes(self.to_dict())

    @property
    def identity_sha256(self) -> str:
        return hashlib.sha256(self.canonical_bytes).hexdigest()

    @classmethod
    def from_dict(cls, payload: Mapping[str, object]) -> Self:
        expected = frozenset(
            {
                "schema_version",
                "kind",
                "authority_generation_sha256",
                "parent_candidate_sha256",
                "parent_proof_sha256",
                "evidence_candidate_sha256",
                "denominator_inventory_sha256",
                "evidence_cell_inventory_sha256",
                "joined_observation_inventory_sha256",
                "unjoinable_observation_inventory_sha256",
                "denominator_count",
                "evidenced_cell_count",
                "unresolved_cell_count",
                "conflict_cell_count",
                "unjoinable_observation_count",
                "exact_partition_equal",
                "candidate_only",
                "denominator_admitted",
                "terminal",
                "release_eligible",
                "verifier_id",
            }
        )
        item = _mapping(payload, label="independent temporal-field proof")
        _exact_keys(item, expected=expected, label="independent temporal-field proof")
        _schema(item, kind=cls.kind, label="independent temporal-field proof")
        return cls(
            authority_generation_sha256=cast("str", item["authority_generation_sha256"]),
            parent_candidate_sha256=cast("str", item["parent_candidate_sha256"]),
            parent_proof_sha256=cast("str", item["parent_proof_sha256"]),
            evidence_candidate_sha256=cast("str", item["evidence_candidate_sha256"]),
            denominator_inventory_sha256=cast("str", item["denominator_inventory_sha256"]),
            evidence_cell_inventory_sha256=cast("str", item["evidence_cell_inventory_sha256"]),
            joined_observation_inventory_sha256=cast(
                "str", item["joined_observation_inventory_sha256"]
            ),
            unjoinable_observation_inventory_sha256=cast(
                "str", item["unjoinable_observation_inventory_sha256"]
            ),
            denominator_count=cast("int", item["denominator_count"]),
            evidenced_cell_count=cast("int", item["evidenced_cell_count"]),
            unresolved_cell_count=cast("int", item["unresolved_cell_count"]),
            conflict_cell_count=cast("int", item["conflict_cell_count"]),
            unjoinable_observation_count=cast("int", item["unjoinable_observation_count"]),
            exact_partition_equal=cast("Literal[True]", item["exact_partition_equal"]),
            candidate_only=cast("Literal[True]", item["candidate_only"]),
            denominator_admitted=cast("Literal[False]", item["denominator_admitted"]),
            terminal=cast("Literal[False]", item["terminal"]),
            release_eligible=cast("Literal[False]", item["release_eligible"]),
            verifier_id=cast(
                "Literal['independent_temporal_field_evidence_v1']",
                item["verifier_id"],
            ),
        )

    @classmethod
    def from_canonical_bytes(cls, raw: bytes) -> Self:
        result = cls.from_dict(_decode_canonical_mapping(raw, label="independent proof"))
        if result.canonical_bytes != raw:
            raise IndependentTemporalFieldEvidenceError(
                "independent proof differs after strict reconstruction"
            )
        return result


def verify_temporal_field_evidence_candidate_independently(
    *,
    parent_candidate_bytes: bytes,
    parent_proof_bytes: bytes,
    evidence_bytes: tuple[bytes, ...],
    candidate_bytes: bytes,
) -> TemporalFieldEvidenceIndependentProofV1:
    """Re-derive the entire evidence partition from exact canonical bytes."""

    if type(evidence_bytes) is not tuple or len(evidence_bytes) > _MAX_OBSERVATIONS:
        raise IndependentTemporalFieldEvidenceError("evidence_bytes must be an exact bounded tuple")
    parent_payload = _decode_canonical_mapping(
        parent_candidate_bytes,
        label="parent candidate",
    )
    parent = _parent_candidate(parent_payload)
    if _canonical_bytes(parent) != parent_candidate_bytes:
        raise IndependentTemporalFieldEvidenceError(
            "parent candidate differs after strict independent parsing"
        )
    proof_payload = _decode_canonical_mapping(parent_proof_bytes, label="parent proof")
    proof = _parent_proof(proof_payload, candidate=parent)
    if _canonical_bytes(proof) != parent_proof_bytes:
        raise IndependentTemporalFieldEvidenceError(
            "parent proof differs after strict independent parsing"
        )
    observations: list[dict[str, object]] = []
    for ordinal, raw in enumerate(evidence_bytes):
        payload = _decode_canonical_mapping(raw, label=f"field observation {ordinal}")
        observation = _observation(payload)
        if _canonical_bytes(observation) != raw:
            raise IndependentTemporalFieldEvidenceError(
                "field observation differs after strict independent parsing"
            )
        observations.append(observation)
    observations.sort(key=lambda item: cast("str", item["observation_id"]))
    observation_ids = tuple(cast("str", item["observation_id"]) for item in observations)
    if len(observation_ids) != len(set(observation_ids)):
        raise IndependentTemporalFieldEvidenceError(
            "duplicate field observation identities are forbidden"
        )
    expected = _expected_candidate(
        parent=parent,
        proof=proof,
        observations=observations,
    )
    observed = _decode_canonical_mapping(candidate_bytes, label="temporal-field candidate")
    expected_bytes = _canonical_bytes(expected)
    if not _exact_typed_equal(observed, expected) or candidate_bytes != expected_bytes:
        raise IndependentTemporalFieldEvidenceError(
            "temporal-field candidate differs from the independently derived partition"
        )
    return TemporalFieldEvidenceIndependentProofV1(
        authority_generation_sha256=cast("str", expected["authority_generation_sha256"]),
        parent_candidate_sha256=cast("str", expected["parent_candidate_sha256"]),
        parent_proof_sha256=cast("str", expected["parent_proof_sha256"]),
        evidence_candidate_sha256=_sha256_bytes(candidate_bytes),
        denominator_inventory_sha256=cast("str", expected["denominator_inventory_sha256"]),
        evidence_cell_inventory_sha256=cast("str", expected["evidence_cell_inventory_sha256"]),
        joined_observation_inventory_sha256=cast(
            "str", expected["joined_observation_inventory_sha256"]
        ),
        unjoinable_observation_inventory_sha256=cast(
            "str", expected["unjoinable_observation_inventory_sha256"]
        ),
        denominator_count=cast("int", expected["denominator_count"]),
        evidenced_cell_count=cast("int", expected["evidenced_cell_count"]),
        unresolved_cell_count=cast("int", expected["unresolved_cell_count"]),
        conflict_cell_count=cast("int", expected["conflict_cell_count"]),
        unjoinable_observation_count=cast("int", expected["unjoinable_observation_count"]),
        exact_partition_equal=True,
        candidate_only=True,
        denominator_admitted=False,
        terminal=False,
        release_eligible=False,
    )
