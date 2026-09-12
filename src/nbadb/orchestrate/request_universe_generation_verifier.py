"""Independent verifier for nonterminal request-universe candidates.

The implementation deliberately imports neither the primary candidate module
nor any of its helpers.  It re-parses literal source mappings, re-derives every
physical-call, route-member, field-period-cell, blocker, count, and inventory
digest, then requires byte-equivalent semantic payloads.  The resulting proof
attests only a candidate generation; it cannot attest a fixed point, terminal
request universe, extraction completeness, or release eligibility.
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, ClassVar, Literal, Self, cast

if TYPE_CHECKING:
    from collections.abc import Mapping

__all__ = [
    "IndependentRequestUniverseCandidateError",
    "RequestUniverseCandidateIndependentProofV1",
    "RequestUniverseIndependentEmptyDeltaReceiptV1",
    "RequestUniverseIndependentProofV1",
    "verify_request_universe_candidate_independently",
    "verify_request_universe_v1_independently",
]

_SCHEMA_VERSION = 1
_SHA256_RE = re.compile(r"[0-9a-f]{64}")
_SAFE_ID_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.:/#-]{0,511}")
_SEASON_RE = re.compile(r"([0-9]{4})-([0-9]{2})")
_DATE_RE = re.compile(r"([0-9]{4})-([0-9]{2})-([0-9]{2})")
_GAME_ID_RE = re.compile(r"[0-9]{10}")
_CUME_REASON_RE = re.compile(r"[a-z0-9][a-z0-9_]*")
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
_MAX_TEXT = 1_024
_MAX_PARAMETERS = 256
_MAX_PATH_SEGMENTS = 64
_MAX_CALLS = 250_000
_MAX_ROUTE_MEMBERS = 1_000_000
_MAX_FIELD_OCCURRENCES = 2_000_000
_MAX_TEMPORAL_SCOPES = 2_000_000
_MAX_CELLS = 5_000_000
_MAX_CANONICAL_BYTES = 32 * 1024 * 1024
_MAX_CUME_WORKLOAD_BYTES = 16 * 1024
_CUME_PLAYER_ALIASES = ("cume_stats_player", "cume_stats_player_games")
_CUME_TEAM_ALIASES = ("cume_stats_team", "cume_stats_team_games")
_CUME_SEASON_TYPES = frozenset({"Regular Season", "Playoffs", "Pre Season", "PlayIn", "All Star"})
_CUME_WORKLOAD_FIELDS = frozenset(
    {
        "schema_version",
        "kind",
        "entity_kind",
        "entity_id",
        "season",
        "season_type",
        "game_ids",
        "disposition",
        "typed_zero_reason",
        "foundation_receipt_sha256",
        "provider_authority_sha256",
    }
)


class IndependentRequestUniverseCandidateError(ValueError):
    """Raised when independent derivation disagrees or input is malformed."""


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
        raise IndependentRequestUniverseCandidateError(
            "independent verifier input is not canonical JSON data"
        ) from exc


def _sha256(value: object) -> str:
    return hashlib.sha256(_canonical_bytes(value)).hexdigest()


def _decode_canonical_mapping(raw: bytes, *, label: str) -> dict[str, object]:
    if type(raw) is not bytes or not raw or len(raw) > _MAX_CANONICAL_BYTES:
        raise IndependentRequestUniverseCandidateError(f"{label} canonical byte length is invalid")

    def reject_duplicates(pairs: list[tuple[str, object]]) -> dict[str, object]:
        result: dict[str, object] = {}
        for key, value in pairs:
            if key in result:
                raise IndependentRequestUniverseCandidateError(
                    f"{label} canonical JSON contains duplicate keys"
                )
            result[key] = value
        return result

    try:
        decoded = json.loads(
            raw.decode("utf-8", errors="strict"),
            object_pairs_hook=reject_duplicates,
            parse_constant=lambda _value: (_ for _ in ()).throw(
                IndependentRequestUniverseCandidateError(
                    f"{label} canonical JSON contains a non-finite number"
                )
            ),
        )
    except IndependentRequestUniverseCandidateError:
        raise
    except (UnicodeDecodeError, json.JSONDecodeError, RecursionError) as exc:
        raise IndependentRequestUniverseCandidateError(
            f"{label} canonical input is not valid JSON"
        ) from exc
    payload = _mapping(decoded, label=f"{label} canonical root")
    if _canonical_bytes(payload) != raw:
        raise IndependentRequestUniverseCandidateError(f"{label} input is not exact canonical JSON")
    return payload


def _mapping(value: object, *, label: str) -> dict[str, object]:
    if type(value) is not dict or any(type(key) is not str for key in value):
        raise IndependentRequestUniverseCandidateError(
            f"{label} must be an exact string-keyed object"
        )
    return cast("dict[str, object]", value)


def _array(value: object, *, label: str, maximum: int) -> list[object]:
    if type(value) is not list or len(value) > maximum:
        raise IndependentRequestUniverseCandidateError(f"{label} must be an exact bounded array")
    return cast("list[object]", value)


def _exact_keys(
    payload: Mapping[str, object],
    *,
    expected: frozenset[str],
    label: str,
) -> None:
    if frozenset(payload) != expected:
        raise IndependentRequestUniverseCandidateError(f"{label} has missing or unexpected fields")


def _sha(value: object, *, label: str) -> str:
    if type(value) is not str or _SHA256_RE.fullmatch(value) is None:
        raise IndependentRequestUniverseCandidateError(
            f"{label} must be an exact lowercase SHA-256"
        )
    return value


def _safe_id(value: object, *, label: str) -> str:
    if type(value) is not str or _SAFE_ID_RE.fullmatch(value) is None:
        raise IndependentRequestUniverseCandidateError(
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
        raise IndependentRequestUniverseCandidateError(
            f"{label} must be exact bounded non-control text"
        )
    return value


def _nonnegative_int(value: object, *, label: str) -> int:
    if type(value) is not int or value < 0:
        raise IndependentRequestUniverseCandidateError(f"{label} must be a nonnegative integer")
    return value


def _schema(payload: Mapping[str, object], *, kind: str, label: str) -> None:
    if (
        type(payload.get("schema_version")) is not int
        or payload.get("schema_version") != _SCHEMA_VERSION
        or type(payload.get("kind")) is not str
        or payload.get("kind") != kind
    ):
        raise IndependentRequestUniverseCandidateError(f"{label} schema identity is invalid")


def _parameter_value(value: object, *, label: str) -> object:
    if value is None or type(value) in {str, int, bool}:
        if type(value) is str and len(value) > _MAX_TEXT:
            raise IndependentRequestUniverseCandidateError(f"{label} exceeds the string bound")
        return value
    if type(value) is list:
        result = _array(value, label=label, maximum=_MAX_PARAMETERS)
        for item in result:
            if item is not None and type(item) not in {str, int, bool}:
                raise IndependentRequestUniverseCandidateError(
                    f"{label} contains a non-scalar value"
                )
            if type(item) is str and len(item) > _MAX_TEXT:
                raise IndependentRequestUniverseCandidateError(
                    f"{label} contains an oversized string"
                )
        return result
    raise IndependentRequestUniverseCandidateError(
        f"{label} must be an exact scalar or scalar array"
    )


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
        raise IndependentRequestUniverseCandidateError("parameter names must be sorted and unique")
    return result


def _nested_path(value: object) -> list[str | int]:
    raw = _array(value, label="nested_path", maximum=_MAX_PATH_SEGMENTS)
    result: list[str | int] = []
    for segment in raw:
        if type(segment) is int:
            result.append(_nonnegative_int(segment, label="nested_path index"))
        else:
            result.append(_text(segment, label="nested_path segment"))
    return result


def _period(kind: object, value: object) -> tuple[str, str | int]:
    if type(kind) is not str or kind not in _TEMPORAL_KINDS:
        raise IndependentRequestUniverseCandidateError("temporal scope kind is invalid")
    if kind == "season":
        text = _text(value, label="season")
        match = _SEASON_RE.fullmatch(text)
        if match is None or int(match.group(2)) != (int(match.group(1)) + 1) % 100:
            raise IndependentRequestUniverseCandidateError("season value is invalid")
        return kind, text
    if kind == "game_date":
        text = _text(value, label="game_date")
        match = _DATE_RE.fullmatch(text)
        if match is None:
            raise IndependentRequestUniverseCandidateError("game_date value is invalid")
        year, month, day = (int(part) for part in match.groups())
        try:
            __import__("datetime").date(year, month, day)
        except ValueError as exc:
            raise IndependentRequestUniverseCandidateError(
                "game_date value is not a calendar date"
            ) from exc
        return kind, text
    if kind == "game_id":
        text = _text(value, label="game_id")
        if _GAME_ID_RE.fullmatch(text) is None:
            raise IndependentRequestUniverseCandidateError("game_id value is invalid")
        return kind, text
    if kind == "calendar_year":
        if type(value) is not int or value < 1946 or value > 9999:
            raise IndependentRequestUniverseCandidateError("calendar_year value is invalid")
        return kind, value
    text = _text(value, label=f"{kind} value")
    if len(text) > 256:
        raise IndependentRequestUniverseCandidateError(f"{kind} value exceeds the bound")
    return kind, text


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
    if (
        _sha(
            item["authority_generation_sha256"],
            label="logical call authority_generation_sha256",
        )
        != authority
    ):
        raise IndependentRequestUniverseCandidateError(
            "logical call uses a mixed authority generation"
        )
    for name in (
        "source_family",
        "endpoint_name",
        "canonical_endpoint_name",
        "physical_endpoint_name",
    ):
        _safe_id(item[name], label=name)
    parameters = _parameters(item["parameter_items"])
    if item["parameters_complete"] is not True:
        raise IndependentRequestUniverseCandidateError(
            "logical request parameter set is not explicitly complete"
        )
    pagination_kind = item["pagination_kind"]
    pagination_value = item["pagination_value"]
    if pagination_kind not in {"none", "page", "cursor"}:
        raise IndependentRequestUniverseCandidateError("pagination kind is invalid")
    if pagination_kind == "none":
        if pagination_value is not None:
            raise IndependentRequestUniverseCandidateError(
                "non-paginated call carries a pagination value"
            )
    elif type(pagination_value) not in {str, int}:
        raise IndependentRequestUniverseCandidateError(
            "paginated call lacks an exact pagination value"
        )
    elif type(pagination_value) is str:
        _text(pagination_value, label="pagination value")
    elif cast("int", pagination_value) < 0:
        raise IndependentRequestUniverseCandidateError("integer pagination value is negative")
    dependent = (
        item["dependent_workload_kind"],
        item["dependent_workload_sha256"],
        item["dependent_physical_alias"],
    )
    if any(value is None for value in dependent) and any(value is not None for value in dependent):
        raise IndependentRequestUniverseCandidateError("dependent workload identity is partial")
    if dependent[0] is not None:
        _safe_id(dependent[0], label="dependent workload kind")
        _sha(dependent[1], label="dependent workload SHA-256")
        _safe_id(dependent[2], label="dependent physical alias")
    scope_payload = {
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
    scope_sha = _sha256(scope_payload)
    if item["request_scope_sha256"] != scope_sha:
        raise IndependentRequestUniverseCandidateError(
            "logical call scope digest differs from independently derived scope"
        )
    if item["physical_call_id"] != f"physical-call-v1:{scope_sha}":
        raise IndependentRequestUniverseCandidateError(
            "physical call ID differs from independently derived scope"
        )
    return {
        **scope_payload,
        "physical_call_id": item["physical_call_id"],
        "request_scope_sha256": scope_sha,
    }


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
    if (
        _sha(
            item["authority_generation_sha256"],
            label="route member authority_generation_sha256",
        )
        != authority
    ):
        raise IndependentRequestUniverseCandidateError(
            "route member uses a mixed authority generation"
        )
    _safe_id(item["physical_call_id"], label="physical_call_id")
    _sha(item["request_scope_sha256"], label="request_scope_sha256")
    _safe_id(item["route_id"], label="route_id")
    _safe_id(item["endpoint_name"], label="endpoint_name")
    _text(item["result_name"], label="result_name")
    _nonnegative_int(item["result_ordinal"], label="result_ordinal")
    path = _nested_path(item["nested_path"])
    body = {
        "schema_version": _SCHEMA_VERSION,
        "kind": "route_request_member_v1",
        "authority_generation_sha256": authority,
        "physical_call_id": item["physical_call_id"],
        "request_scope_sha256": item["request_scope_sha256"],
        "route_id": item["route_id"],
        "endpoint_name": item["endpoint_name"],
        "result_name": item["result_name"],
        "result_ordinal": item["result_ordinal"],
        "nested_path": path,
    }
    member_id = f"route-member-v1:{_sha256(body)}"
    if item["route_request_member_id"] != member_id:
        raise IndependentRequestUniverseCandidateError(
            "route member ID differs from independently derived identity"
        )
    return {**body, "route_request_member_id": member_id}


_FIELD_FIELDS = frozenset(
    {
        "authority_generation_sha256",
        "occurrence_id",
        "route_id",
        "endpoint_name",
        "result_name",
        "result_ordinal",
        "nested_path",
        "provider_field",
        "field_occurrence_ordinal",
        "field_fate_contract_sha256",
    }
)


def _field(raw: object, *, authority: str, field_digest: str) -> dict[str, object]:
    item = _mapping(raw, label="field occurrence")
    _exact_keys(item, expected=_FIELD_FIELDS, label="field occurrence")
    if (
        _sha(
            item["authority_generation_sha256"],
            label="field occurrence authority_generation_sha256",
        )
        != authority
    ):
        raise IndependentRequestUniverseCandidateError(
            "field occurrence uses a mixed authority generation"
        )
    if (
        _sha(
            item["field_fate_contract_sha256"],
            label="field occurrence field_fate_contract_sha256",
        )
        != field_digest
    ):
        raise IndependentRequestUniverseCandidateError(
            "field occurrence uses a mixed field-fate authority"
        )
    _safe_id(item["occurrence_id"], label="occurrence_id")
    _safe_id(item["route_id"], label="route_id")
    _safe_id(item["endpoint_name"], label="endpoint_name")
    _text(item["result_name"], label="result_name")
    _nonnegative_int(item["result_ordinal"], label="result_ordinal")
    path = _nested_path(item["nested_path"])
    _text(item["provider_field"], label="provider_field")
    _nonnegative_int(
        item["field_occurrence_ordinal"],
        label="field_occurrence_ordinal",
    )
    return {**item, "nested_path": path}


_PERIOD_FIELDS = frozenset(
    {
        "authority_generation_sha256",
        "physical_call_id",
        "route_request_member_id",
        "route_id",
        "endpoint_name",
        "request_scope_sha256",
        "temporal_contract_sha256",
        "temporal_scope_kind",
        "temporal_scope_value",
    }
)


def _temporal_scope(
    raw: object,
    *,
    authority: str,
    temporal_digest: str,
) -> dict[str, object]:
    item = _mapping(raw, label="explicit temporal scope")
    _exact_keys(item, expected=_PERIOD_FIELDS, label="explicit temporal scope")
    if (
        _sha(
            item["authority_generation_sha256"],
            label="temporal scope authority_generation_sha256",
        )
        != authority
    ):
        raise IndependentRequestUniverseCandidateError(
            "temporal scope uses a mixed authority generation"
        )
    if (
        _sha(
            item["temporal_contract_sha256"],
            label="temporal scope temporal_contract_sha256",
        )
        != temporal_digest
    ):
        raise IndependentRequestUniverseCandidateError(
            "temporal scope uses a mixed temporal authority"
        )
    _safe_id(item["physical_call_id"], label="physical_call_id")
    _safe_id(item["route_request_member_id"], label="route_request_member_id")
    _safe_id(item["route_id"], label="route_id")
    _safe_id(item["endpoint_name"], label="endpoint_name")
    _sha(item["request_scope_sha256"], label="request_scope_sha256")
    kind, value = _period(item["temporal_scope_kind"], item["temporal_scope_value"])
    return {**item, "temporal_scope_kind": kind, "temporal_scope_value": value}


_CUME_FIELDS = frozenset(
    {
        "authority_generation_sha256",
        "entity_kind",
        "workload_content_sha256",
        "workload_canonical_json",
        "physical_endpoint_aliases",
    }
)


def _cume_aliases_for_entity(entity_kind: object) -> tuple[str, ...]:
    if type(entity_kind) is not str:
        raise IndependentRequestUniverseCandidateError("cume entity_kind must be player or team")
    if entity_kind == "player":
        return _CUME_PLAYER_ALIASES
    if entity_kind == "team":
        return _CUME_TEAM_ALIASES
    raise IndependentRequestUniverseCandidateError("cume entity_kind must be player or team")


def _cume_workload_binding(
    *,
    entity_kind: object,
    content_sha256: object,
    canonical_json: object,
) -> tuple[str, str, str]:
    _cume_aliases_for_entity(entity_kind)
    digest = _sha(content_sha256, label="workload_content_sha256")
    if type(canonical_json) is not str:
        raise IndependentRequestUniverseCandidateError(
            "cume workload authority must be exact canonical JSON text"
        )
    raw = canonical_json.encode("utf-8")
    if not raw or len(raw) > _MAX_CUME_WORKLOAD_BYTES:
        raise IndependentRequestUniverseCandidateError(
            "cume workload authority has an invalid bounded byte length"
        )
    payload = _decode_canonical_mapping(raw, label="cume workload authority")
    _exact_keys(
        payload,
        expected=_CUME_WORKLOAD_FIELDS,
        label="cume workload authority",
    )
    _schema(payload, kind="nbadb_cume_workload", label="cume workload authority")
    if payload["entity_kind"] != entity_kind:
        raise IndependentRequestUniverseCandidateError(
            "cume workload content cannot be rebound to another entity kind"
        )
    entity_id = payload["entity_id"]
    if type(entity_id) is not int or entity_id <= 0:
        raise IndependentRequestUniverseCandidateError(
            "cume workload entity_id must be a positive integer"
        )
    _period("season", payload["season"])
    if type(payload["season_type"]) is not str or payload["season_type"] not in _CUME_SEASON_TYPES:
        raise IndependentRequestUniverseCandidateError("cume workload season_type is invalid")
    game_ids = _array(
        payload["game_ids"],
        label="cume workload game_ids",
        maximum=_MAX_CUME_WORKLOAD_BYTES,
    )
    if any(
        type(game_id) is not str or _GAME_ID_RE.fullmatch(game_id) is None for game_id in game_ids
    ) or len(game_ids) != len(set(cast("list[str]", game_ids))):
        raise IndependentRequestUniverseCandidateError(
            "cume workload game_ids must be unique exact ten-digit strings"
        )
    disposition = payload["disposition"]
    reason = payload["typed_zero_reason"]
    if disposition == "complete":
        if not game_ids or reason is not None:
            raise IndependentRequestUniverseCandidateError(
                "complete cume workload authority is inconsistent"
            )
    elif disposition == "typed_zero":
        if game_ids or type(reason) is not str or _CUME_REASON_RE.fullmatch(reason) is None:
            raise IndependentRequestUniverseCandidateError(
                "typed-zero cume workload authority is inconsistent"
            )
    else:
        raise IndependentRequestUniverseCandidateError("cume workload disposition is invalid")
    _sha(
        payload["foundation_receipt_sha256"],
        label="cume workload foundation_receipt_sha256",
    )
    _sha(
        payload["provider_authority_sha256"],
        label="cume workload provider_authority_sha256",
    )
    if hashlib.sha256(raw).hexdigest() != digest:
        raise IndependentRequestUniverseCandidateError(
            "cume workload content digest differs from its canonical authority"
        )
    return cast("str", entity_kind), digest, canonical_json


def _cume(raw: object, *, authority: str) -> dict[str, object]:
    item = _mapping(raw, label="unintegrated cume value")
    _exact_keys(item, expected=_CUME_FIELDS, label="unintegrated cume value")
    if (
        _sha(
            item["authority_generation_sha256"],
            label="cume value authority_generation_sha256",
        )
        != authority
    ):
        raise IndependentRequestUniverseCandidateError(
            "cume value uses a mixed authority generation"
        )
    entity_kind, content_sha256, canonical_json = _cume_workload_binding(
        entity_kind=item["entity_kind"],
        content_sha256=item["workload_content_sha256"],
        canonical_json=item["workload_canonical_json"],
    )
    aliases = _array(
        item["physical_endpoint_aliases"],
        label="physical_endpoint_aliases",
        maximum=16,
    )
    if not aliases or any(type(alias) is not str for alias in aliases):
        raise IndependentRequestUniverseCandidateError("physical endpoint aliases are invalid")
    for alias in aliases:
        _safe_id(alias, label="physical endpoint alias")
    if aliases != list(_cume_aliases_for_entity(entity_kind)):
        raise IndependentRequestUniverseCandidateError(
            "cume physical endpoint aliases differ from the exact entity-bound set"
        )
    return {
        "authority_generation_sha256": authority,
        "entity_kind": entity_kind,
        "workload_content_sha256": content_sha256,
        "workload_canonical_json": canonical_json,
        "physical_endpoint_aliases": aliases,
    }


_SOURCE_FIELDS = frozenset(
    {
        "schema_version",
        "kind",
        "authority_generation_sha256",
        "field_fate_contract_sha256",
        "temporal_contract_sha256",
        "logical_calls",
        "route_members",
        "field_occurrences",
        "explicit_temporal_scopes",
        "unintegrated_cume_values",
    }
)


def _source(raw: Mapping[str, object]) -> dict[str, object]:
    item = _mapping(raw, label="candidate source")
    _exact_keys(item, expected=_SOURCE_FIELDS, label="candidate source")
    _schema(
        item,
        kind="request_universe_candidate_source_v1",
        label="candidate source",
    )
    authority = _sha(
        item["authority_generation_sha256"],
        label="authority_generation_sha256",
    )
    field_digest = _sha(
        item["field_fate_contract_sha256"],
        label="field_fate_contract_sha256",
    )
    temporal_digest = _sha(
        item["temporal_contract_sha256"],
        label="temporal_contract_sha256",
    )
    calls = [
        _call(raw_call, authority=authority)
        for raw_call in _array(
            item["logical_calls"],
            label="logical_calls",
            maximum=_MAX_CALLS,
        )
    ]
    if not calls:
        raise IndependentRequestUniverseCandidateError("logical_calls must be nonempty")
    routes = [
        _route(raw_route, authority=authority)
        for raw_route in _array(
            item["route_members"],
            label="route_members",
            maximum=_MAX_ROUTE_MEMBERS,
        )
    ]
    if not routes:
        raise IndependentRequestUniverseCandidateError("route_members must be nonempty")
    fields = [
        _field(raw_field, authority=authority, field_digest=field_digest)
        for raw_field in _array(
            item["field_occurrences"],
            label="field_occurrences",
            maximum=_MAX_FIELD_OCCURRENCES,
        )
    ]
    periods = [
        _temporal_scope(
            raw_period,
            authority=authority,
            temporal_digest=temporal_digest,
        )
        for raw_period in _array(
            item["explicit_temporal_scopes"],
            label="explicit_temporal_scopes",
            maximum=_MAX_TEMPORAL_SCOPES,
        )
    ]
    cume_values = [
        _cume(raw_cume, authority=authority)
        for raw_cume in _array(
            item["unintegrated_cume_values"],
            label="unintegrated_cume_values",
            maximum=_MAX_CALLS,
        )
    ]
    order_specs: tuple[tuple[list[dict[str, object]], str, str], ...] = (
        (calls, "physical_call_id", "logical_calls"),
        (routes, "route_request_member_id", "route_members"),
    )
    for values, identity, label in order_specs:
        ids = [cast("str", value[identity]) for value in values]
        if ids != sorted(set(ids)):
            raise IndependentRequestUniverseCandidateError(f"{label} must be sorted and unique")
    for values, label in (
        (fields, "field_occurrences"),
        (periods, "explicit_temporal_scopes"),
        (cume_values, "unintegrated_cume_values"),
    ):
        ids = [_sha256(value) for value in values]
        if ids != sorted(set(ids)):
            raise IndependentRequestUniverseCandidateError(
                f"{label} must be sorted and unique by exact identity"
            )
    call_by_id = {cast("str", call["physical_call_id"]): call for call in calls}
    route_by_id = {cast("str", route["route_request_member_id"]): route for route in routes}
    for route in routes:
        call = call_by_id.get(cast("str", route["physical_call_id"]))
        if call is None or (
            route["request_scope_sha256"],
            route["endpoint_name"],
        ) != (
            call["request_scope_sha256"],
            call["endpoint_name"],
        ):
            raise IndependentRequestUniverseCandidateError(
                "route member differs from its exact physical call"
            )
    route_shapes = {
        (
            route["route_id"],
            route["endpoint_name"],
            route["result_name"],
            route["result_ordinal"],
            tuple(cast("list[object]", route["nested_path"])),
        )
        for route in routes
    }
    field_shapes = {
        (
            field["route_id"],
            field["endpoint_name"],
            field["result_name"],
            field["result_ordinal"],
            tuple(cast("list[object]", field["nested_path"])),
        )
        for field in fields
    }
    if not field_shapes <= route_shapes:
        raise IndependentRequestUniverseCandidateError(
            "field occurrence lacks an exact route/result/path member"
        )
    for period in periods:
        route = route_by_id.get(cast("str", period["route_request_member_id"]))
        if route is None or (
            period["physical_call_id"],
            period["route_id"],
            period["endpoint_name"],
            period["request_scope_sha256"],
        ) != (
            route["physical_call_id"],
            route["route_id"],
            route["endpoint_name"],
            route["request_scope_sha256"],
        ):
            raise IndependentRequestUniverseCandidateError(
                "explicit temporal scope differs from its route member"
            )
    cume_aliases = {
        alias
        for value in cume_values
        for alias in cast("list[str]", value["physical_endpoint_aliases"])
    }
    if any(
        {
            cast("str", call["endpoint_name"]),
            cast("str", call["canonical_endpoint_name"]),
            cast("str", call["physical_endpoint_name"]),
        }
        & cume_aliases
        for call in calls
    ):
        raise IndependentRequestUniverseCandidateError(
            "unintegrated cume value was promoted into a request unit"
        )
    return {
        "schema_version": _SCHEMA_VERSION,
        "kind": "request_universe_candidate_source_v1",
        "authority_generation_sha256": authority,
        "field_fate_contract_sha256": field_digest,
        "temporal_contract_sha256": temporal_digest,
        "logical_calls": calls,
        "route_members": routes,
        "field_occurrences": fields,
        "explicit_temporal_scopes": periods,
        "unintegrated_cume_values": cume_values,
    }


def _route_shape(route: Mapping[str, object]) -> tuple[object, ...]:
    return (
        route["route_id"],
        route["endpoint_name"],
        route["result_name"],
        route["result_ordinal"],
        tuple(cast("list[object]", route["nested_path"])),
    )


def _field_shape(field: Mapping[str, object]) -> tuple[object, ...]:
    return (
        field["route_id"],
        field["endpoint_name"],
        field["result_name"],
        field["result_ordinal"],
        tuple(cast("list[object]", field["nested_path"])),
    )


def _cell(
    *,
    authority: str,
    route: Mapping[str, object],
    field: Mapping[str, object],
    period: Mapping[str, object],
) -> dict[str, object]:
    body = {
        "schema_version": _SCHEMA_VERSION,
        "kind": "field_period_denominator_cell_v1",
        "authority_generation_sha256": authority,
        "physical_call_id": route["physical_call_id"],
        "route_request_member_id": route["route_request_member_id"],
        "route_id": route["route_id"],
        "endpoint_name": route["endpoint_name"],
        "result_name": route["result_name"],
        "result_ordinal": route["result_ordinal"],
        "nested_path": route["nested_path"],
        "provider_field": field["provider_field"],
        "field_occurrence_ordinal": field["field_occurrence_ordinal"],
        "request_scope_sha256": route["request_scope_sha256"],
        "field_fate_contract_sha256": field["field_fate_contract_sha256"],
        "temporal_contract_sha256": period["temporal_contract_sha256"],
        "temporal_scope_kind": period["temporal_scope_kind"],
        "temporal_scope_value": period["temporal_scope_value"],
        "state": "evidence_insufficient",
    }
    return {**body, "cell_id": f"field-period-cell-v1:{_sha256(body)}"}


def _blocker(
    *,
    authority: str,
    blocker_code: str,
    subject_id: str,
    evidence_sha256: str,
) -> dict[str, object]:
    return {
        "authority_generation_sha256": authority,
        "blocker_code": blocker_code,
        "subject_id": subject_id,
        "evidence_sha256": evidence_sha256,
    }


_OBSERVED_CELL_FIELDS = frozenset(
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


def _observed_cell(
    raw: object,
    *,
    authority: str,
    field_digest: str,
    temporal_digest: str,
) -> dict[str, object]:
    item = _mapping(raw, label="observed field-period cell")
    _exact_keys(
        item,
        expected=_OBSERVED_CELL_FIELDS,
        label="observed field-period cell",
    )
    _schema(
        item,
        kind="field_period_denominator_cell_v1",
        label="observed field-period cell",
    )
    if (
        _sha(
            item["authority_generation_sha256"],
            label="observed cell authority_generation_sha256",
        )
        != authority
    ):
        raise IndependentRequestUniverseCandidateError(
            "observed cell uses a mixed authority generation"
        )
    physical_call_id = _safe_id(
        item["physical_call_id"],
        label="observed cell physical_call_id",
    )
    route_request_member_id = _safe_id(
        item["route_request_member_id"],
        label="observed cell route_request_member_id",
    )
    route_id = _safe_id(item["route_id"], label="observed cell route_id")
    endpoint_name = _safe_id(
        item["endpoint_name"],
        label="observed cell endpoint_name",
    )
    result_name = _text(item["result_name"], label="observed cell result_name")
    result_ordinal = _nonnegative_int(
        item["result_ordinal"],
        label="observed cell result_ordinal",
    )
    nested_path = _nested_path(item["nested_path"])
    provider_field = _text(
        item["provider_field"],
        label="observed cell provider_field",
    )
    field_occurrence_ordinal = _nonnegative_int(
        item["field_occurrence_ordinal"],
        label="observed cell field_occurrence_ordinal",
    )
    request_scope_sha256 = _sha(
        item["request_scope_sha256"],
        label="observed cell request_scope_sha256",
    )
    if (
        _sha(
            item["field_fate_contract_sha256"],
            label="observed cell field_fate_contract_sha256",
        )
        != field_digest
    ):
        raise IndependentRequestUniverseCandidateError(
            "observed cell uses a mixed field-fate authority"
        )
    if (
        _sha(
            item["temporal_contract_sha256"],
            label="observed cell temporal_contract_sha256",
        )
        != temporal_digest
    ):
        raise IndependentRequestUniverseCandidateError(
            "observed cell uses a mixed temporal authority"
        )
    period_kind, period_value = _period(
        item["temporal_scope_kind"],
        item["temporal_scope_value"],
    )
    if type(item["state"]) is not str or item["state"] != "evidence_insufficient":
        raise IndependentRequestUniverseCandidateError(
            "observed candidate cell state must remain evidence_insufficient"
        )
    body = {
        "schema_version": _SCHEMA_VERSION,
        "kind": "field_period_denominator_cell_v1",
        "authority_generation_sha256": authority,
        "physical_call_id": physical_call_id,
        "route_request_member_id": route_request_member_id,
        "route_id": route_id,
        "endpoint_name": endpoint_name,
        "result_name": result_name,
        "result_ordinal": result_ordinal,
        "nested_path": nested_path,
        "provider_field": provider_field,
        "field_occurrence_ordinal": field_occurrence_ordinal,
        "request_scope_sha256": request_scope_sha256,
        "field_fate_contract_sha256": field_digest,
        "temporal_contract_sha256": temporal_digest,
        "temporal_scope_kind": period_kind,
        "temporal_scope_value": period_value,
        "state": "evidence_insufficient",
    }
    cell_id = f"field-period-cell-v1:{_sha256(body)}"
    if _safe_id(item["cell_id"], label="observed cell cell_id") != cell_id:
        raise IndependentRequestUniverseCandidateError(
            "observed cell ID differs from its independently parsed identity"
        )
    return {**body, "cell_id": cell_id}


_OBSERVED_BLOCKER_FIELDS = frozenset(
    {
        "authority_generation_sha256",
        "blocker_code",
        "subject_id",
        "evidence_sha256",
    }
)


def _observed_blocker(raw: object, *, authority: str) -> dict[str, object]:
    item = _mapping(raw, label="observed candidate blocker")
    _exact_keys(
        item,
        expected=_OBSERVED_BLOCKER_FIELDS,
        label="observed candidate blocker",
    )
    if (
        _sha(
            item["authority_generation_sha256"],
            label="observed blocker authority_generation_sha256",
        )
        != authority
    ):
        raise IndependentRequestUniverseCandidateError(
            "observed blocker uses a mixed authority generation"
        )
    return _blocker(
        authority=authority,
        blocker_code=_safe_id(
            item["blocker_code"],
            label="observed blocker blocker_code",
        ),
        subject_id=_safe_id(
            item["subject_id"],
            label="observed blocker subject_id",
        ),
        evidence_sha256=_sha(
            item["evidence_sha256"],
            label="observed blocker evidence_sha256",
        ),
    )


_OBSERVED_CANDIDATE_FIELDS = frozenset(
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


def _observed_candidate(raw: Mapping[str, object]) -> dict[str, object]:
    item = _mapping(raw, label="observed candidate generation")
    _exact_keys(
        item,
        expected=_OBSERVED_CANDIDATE_FIELDS,
        label="observed candidate generation",
    )
    _schema(
        item,
        kind="request_universe_candidate_generation_v1",
        label="observed candidate generation",
    )
    authority = _sha(
        item["authority_generation_sha256"],
        label="observed candidate authority_generation_sha256",
    )
    source_sha256 = _sha(
        item["source_inputs_sha256"],
        label="observed candidate source_inputs_sha256",
    )
    field_digest = _sha(
        item["field_fate_contract_sha256"],
        label="observed candidate field_fate_contract_sha256",
    )
    temporal_digest = _sha(
        item["temporal_contract_sha256"],
        label="observed candidate temporal_contract_sha256",
    )
    calls = [
        _call(raw_call, authority=authority)
        for raw_call in _array(
            item["logical_calls"],
            label="observed candidate logical_calls",
            maximum=_MAX_CALLS,
        )
    ]
    routes = [
        _route(raw_route, authority=authority)
        for raw_route in _array(
            item["route_members"],
            label="observed candidate route_members",
            maximum=_MAX_ROUTE_MEMBERS,
        )
    ]
    cells = [
        _observed_cell(
            raw_cell,
            authority=authority,
            field_digest=field_digest,
            temporal_digest=temporal_digest,
        )
        for raw_cell in _array(
            item["field_period_cells"],
            label="observed candidate field_period_cells",
            maximum=_MAX_CELLS,
        )
    ]
    blockers = [
        _observed_blocker(raw_blocker, authority=authority)
        for raw_blocker in _array(
            item["blockers"],
            label="observed candidate blockers",
            maximum=_MAX_ROUTE_MEMBERS,
        )
    ]
    if not calls or not routes or not blockers:
        raise IndependentRequestUniverseCandidateError(
            "observed candidate requires nonempty call, route, and blocker inventories"
        )
    call_ids = [cast("str", value["physical_call_id"]) for value in calls]
    route_ids = [cast("str", value["route_request_member_id"]) for value in routes]
    cell_ids = [cast("str", value["cell_id"]) for value in cells]
    blocker_ids = [_sha256(value) for value in blockers]
    for identities, label in (
        (call_ids, "logical_calls"),
        (route_ids, "route_members"),
        (cell_ids, "field_period_cells"),
        (blocker_ids, "blockers"),
    ):
        if identities != sorted(set(identities)):
            raise IndependentRequestUniverseCandidateError(
                f"observed candidate {label} must be sorted and unique"
            )
    counts = {
        "logical_call_count": len(calls),
        "route_member_count": len(routes),
        "field_period_cell_count": len(cells),
        "blocker_count": len(blockers),
    }
    for name, expected_count in counts.items():
        if type(item[name]) is not int or item[name] != expected_count:
            raise IndependentRequestUniverseCandidateError(
                f"observed candidate {name} differs from its exact inventory"
            )
    inventories = {
        "logical_call_inventory_sha256": calls,
        "route_member_inventory_sha256": routes,
        "field_period_inventory_sha256": cells,
        "blocker_inventory_sha256": blockers,
    }
    inventory_digests: dict[str, str] = {}
    for name, inventory in inventories.items():
        expected_digest = _sha256(inventory)
        if _sha(item[name], label=f"observed candidate {name}") != expected_digest:
            raise IndependentRequestUniverseCandidateError(
                f"observed candidate {name} differs from its exact inventory"
            )
        inventory_digests[name] = expected_digest
    if item["terminal"] is not False or item["release_eligible"] is not False:
        raise IndependentRequestUniverseCandidateError(
            "observed candidate cannot be terminal or release eligible"
        )
    call_by_id = {cast("str", call["physical_call_id"]): call for call in calls}
    route_by_id = {cast("str", route["route_request_member_id"]): route for route in routes}
    for route in routes:
        call = call_by_id.get(cast("str", route["physical_call_id"]))
        if call is None or (
            route["request_scope_sha256"],
            route["endpoint_name"],
        ) != (
            call["request_scope_sha256"],
            call["endpoint_name"],
        ):
            raise IndependentRequestUniverseCandidateError(
                "observed candidate route differs from its exact physical call"
            )
    for cell in cells:
        route = route_by_id.get(cast("str", cell["route_request_member_id"]))
        if route is None or (
            cell["physical_call_id"],
            cell["route_id"],
            cell["endpoint_name"],
            cell["result_name"],
            cell["result_ordinal"],
            cell["nested_path"],
            cell["request_scope_sha256"],
        ) != (
            route["physical_call_id"],
            route["route_id"],
            route["endpoint_name"],
            route["result_name"],
            route["result_ordinal"],
            route["nested_path"],
            route["request_scope_sha256"],
        ):
            raise IndependentRequestUniverseCandidateError(
                "observed candidate cell differs from its exact route member"
            )
    fixed_point_blocker = _blocker(
        authority=authority,
        blocker_code="candidate_not_fixed_point",
        subject_id="request_universe_candidate_generation_v1",
        evidence_sha256=source_sha256,
    )
    if _sha256(fixed_point_blocker) not in blocker_ids:
        raise IndependentRequestUniverseCandidateError(
            "observed candidate lacks its exact non-fixed-point blocker"
        )
    return {
        "schema_version": _SCHEMA_VERSION,
        "kind": "request_universe_candidate_generation_v1",
        "authority_generation_sha256": authority,
        "source_inputs_sha256": source_sha256,
        "field_fate_contract_sha256": field_digest,
        "temporal_contract_sha256": temporal_digest,
        **counts,
        **inventory_digests,
        "logical_calls": calls,
        "route_members": routes,
        "field_period_cells": cells,
        "blockers": blockers,
        "terminal": False,
        "release_eligible": False,
    }


def _expected_candidate(source: Mapping[str, object]) -> dict[str, object]:
    authority = cast("str", source["authority_generation_sha256"])
    calls = cast("list[dict[str, object]]", source["logical_calls"])
    routes = cast("list[dict[str, object]]", source["route_members"])
    fields = cast("list[dict[str, object]]", source["field_occurrences"])
    periods = cast("list[dict[str, object]]", source["explicit_temporal_scopes"])
    cume_values = cast("list[dict[str, object]]", source["unintegrated_cume_values"])
    fields_by_shape: dict[tuple[object, ...], list[dict[str, object]]] = {}
    for field in fields:
        fields_by_shape.setdefault(_field_shape(field), []).append(field)
    periods_by_member: dict[str, list[dict[str, object]]] = {}
    for period in periods:
        periods_by_member.setdefault(cast("str", period["route_request_member_id"]), []).append(
            period
        )
    cells: list[dict[str, object]] = []
    for route in routes:
        for field in fields_by_shape.get(_route_shape(route), ()):
            for period in periods_by_member.get(cast("str", route["route_request_member_id"]), ()):
                cells.append(
                    _cell(
                        authority=authority,
                        route=route,
                        field=field,
                        period=period,
                    )
                )
                if len(cells) > _MAX_CELLS:
                    raise IndependentRequestUniverseCandidateError(
                        "independent field-period cross product exceeds the bound"
                    )
    cells.sort(key=lambda item: cast("str", item["cell_id"]))
    source_sha = _sha256(source)
    blockers: list[dict[str, object]] = [
        _blocker(
            authority=authority,
            blocker_code="candidate_not_fixed_point",
            subject_id="request_universe_candidate_generation_v1",
            evidence_sha256=source_sha,
        )
    ]
    for route in routes:
        member_id = cast("str", route["route_request_member_id"])
        if not fields_by_shape.get(_route_shape(route)):
            blockers.append(
                _blocker(
                    authority=authority,
                    blocker_code="route_field_denominator_absent",
                    subject_id=member_id,
                    evidence_sha256=cast("str", source["field_fate_contract_sha256"]),
                )
            )
        if not periods_by_member.get(member_id):
            blockers.append(
                _blocker(
                    authority=authority,
                    blocker_code="explicit_temporal_scope_absent",
                    subject_id=member_id,
                    evidence_sha256=cast("str", source["temporal_contract_sha256"]),
                )
            )
    for value in cume_values:
        blockers.append(
            _blocker(
                authority=authority,
                blocker_code="unintegrated_cume_value",
                subject_id=cast("str", value["workload_content_sha256"]),
                evidence_sha256=_sha256(value),
            )
        )
    blockers.sort(key=_sha256)
    return {
        "schema_version": _SCHEMA_VERSION,
        "kind": "request_universe_candidate_generation_v1",
        "authority_generation_sha256": authority,
        "source_inputs_sha256": source_sha,
        "field_fate_contract_sha256": source["field_fate_contract_sha256"],
        "temporal_contract_sha256": source["temporal_contract_sha256"],
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


@dataclass(frozen=True, slots=True)
class RequestUniverseCandidateIndependentProofV1:
    """Independent exact-inventory proof for a candidate-only generation."""

    authority_generation_sha256: str
    source_inputs_sha256: str
    candidate_generation_sha256: str
    logical_call_inventory_sha256: str
    route_member_inventory_sha256: str
    field_period_inventory_sha256: str
    blocker_inventory_sha256: str
    logical_call_count: int
    route_member_count: int
    field_period_cell_count: int
    blocker_count: int
    exact_inventory_equal: Literal[True]
    candidate_only: Literal[True]
    terminal: Literal[False]
    release_eligible: Literal[False]
    verifier_id: Literal["independent_request_universe_candidate_v1"] = (
        "independent_request_universe_candidate_v1"
    )

    schema_version: ClassVar[int] = _SCHEMA_VERSION
    kind: ClassVar[str] = "request_universe_candidate_independent_proof_v1"

    def __post_init__(self) -> None:
        for name in (
            "authority_generation_sha256",
            "source_inputs_sha256",
            "candidate_generation_sha256",
            "logical_call_inventory_sha256",
            "route_member_inventory_sha256",
            "field_period_inventory_sha256",
            "blocker_inventory_sha256",
        ):
            _sha(getattr(self, name), label=name)
        for name in (
            "logical_call_count",
            "route_member_count",
            "field_period_cell_count",
            "blocker_count",
        ):
            _nonnegative_int(getattr(self, name), label=name)
        if (
            self.exact_inventory_equal is not True
            or self.candidate_only is not True
            or self.terminal is not False
            or self.release_eligible is not False
            or self.verifier_id != "independent_request_universe_candidate_v1"
        ):
            raise IndependentRequestUniverseCandidateError(
                "independent proof cannot attest finality or release eligibility"
            )

    def to_dict(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "kind": self.kind,
            "authority_generation_sha256": self.authority_generation_sha256,
            "source_inputs_sha256": self.source_inputs_sha256,
            "candidate_generation_sha256": self.candidate_generation_sha256,
            "logical_call_inventory_sha256": self.logical_call_inventory_sha256,
            "route_member_inventory_sha256": self.route_member_inventory_sha256,
            "field_period_inventory_sha256": self.field_period_inventory_sha256,
            "blocker_inventory_sha256": self.blocker_inventory_sha256,
            "logical_call_count": self.logical_call_count,
            "route_member_count": self.route_member_count,
            "field_period_cell_count": self.field_period_cell_count,
            "blocker_count": self.blocker_count,
            "exact_inventory_equal": self.exact_inventory_equal,
            "candidate_only": self.candidate_only,
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
        item = _mapping(payload, label="independent proof")
        _exact_keys(item, expected=expected, label="independent proof")
        _schema(
            item,
            kind="request_universe_candidate_independent_proof_v1",
            label="independent proof",
        )
        return cls(
            authority_generation_sha256=cast("str", item["authority_generation_sha256"]),
            source_inputs_sha256=cast("str", item["source_inputs_sha256"]),
            candidate_generation_sha256=cast("str", item["candidate_generation_sha256"]),
            logical_call_inventory_sha256=cast("str", item["logical_call_inventory_sha256"]),
            route_member_inventory_sha256=cast("str", item["route_member_inventory_sha256"]),
            field_period_inventory_sha256=cast("str", item["field_period_inventory_sha256"]),
            blocker_inventory_sha256=cast("str", item["blocker_inventory_sha256"]),
            logical_call_count=cast("int", item["logical_call_count"]),
            route_member_count=cast("int", item["route_member_count"]),
            field_period_cell_count=cast("int", item["field_period_cell_count"]),
            blocker_count=cast("int", item["blocker_count"]),
            exact_inventory_equal=cast("Literal[True]", item["exact_inventory_equal"]),
            candidate_only=cast("Literal[True]", item["candidate_only"]),
            terminal=cast("Literal[False]", item["terminal"]),
            release_eligible=cast("Literal[False]", item["release_eligible"]),
            verifier_id=cast(
                "Literal['independent_request_universe_candidate_v1']",
                item["verifier_id"],
            ),
        )

    @classmethod
    def from_canonical_bytes(cls, raw: bytes) -> Self:
        result = cls.from_dict(_decode_canonical_mapping(raw, label="independent proof"))
        if result.canonical_bytes != raw:
            raise IndependentRequestUniverseCandidateError(
                "independent proof differs after strict reconstruction"
            )
        return result


def verify_request_universe_candidate_independently(
    *,
    source_payload: Mapping[str, object],
    candidate_payload: Mapping[str, object],
) -> RequestUniverseCandidateIndependentProofV1:
    """Re-derive and compare a candidate without using its production code."""

    source = _source(source_payload)
    expected = _expected_candidate(source)
    observed = _observed_candidate(candidate_payload)
    expected_bytes = _canonical_bytes(expected)
    observed_bytes = _canonical_bytes(observed)
    if observed_bytes != expected_bytes:
        raise IndependentRequestUniverseCandidateError(
            "candidate generation differs from independently derived exact inventories"
        )
    return RequestUniverseCandidateIndependentProofV1(
        authority_generation_sha256=cast("str", expected["authority_generation_sha256"]),
        source_inputs_sha256=cast("str", expected["source_inputs_sha256"]),
        candidate_generation_sha256=hashlib.sha256(observed_bytes).hexdigest(),
        logical_call_inventory_sha256=cast("str", expected["logical_call_inventory_sha256"]),
        route_member_inventory_sha256=cast("str", expected["route_member_inventory_sha256"]),
        field_period_inventory_sha256=cast("str", expected["field_period_inventory_sha256"]),
        blocker_inventory_sha256=cast("str", expected["blocker_inventory_sha256"]),
        logical_call_count=cast("int", expected["logical_call_count"]),
        route_member_count=cast("int", expected["route_member_count"]),
        field_period_cell_count=cast("int", expected["field_period_cell_count"]),
        blocker_count=cast("int", expected["blocker_count"]),
        exact_inventory_equal=True,
        candidate_only=True,
        terminal=False,
        release_eligible=False,
    )


_FINAL_SCHEMA_VERSION = 1
_FINAL_DISPOSITIONS = frozenset(
    {"captured_nonempty", "captured_present_empty", "upstream_unavailable"}
)
_FINAL_SOURCE_SCALARS = frozenset(
    {
        "authority_generation_sha256",
        "checkpoint_identity_sha256",
        "checkpoint_authority_generation_sha256",
        "request_closure_receipt_sha256",
        "request_closure_authority_generation_sha256",
        "w2_authority_identity_sha256",
        "w2_authority_generation_sha256",
        "temporal_field_denominator_sha256",
        "temporal_field_authority_generation_sha256",
        "committed_observation_generation_sha256",
        "committed_observation_authority_generation_sha256",
        "candidate_source_sha256",
        "candidate_generation_sha256",
        "candidate_independent_proof_sha256",
        "source_admission_sha256",
        "parent_request_universe_sha256",
        "generation_ordinal",
    }
)


def _terminal_evidence(raw: object, *, authority: str) -> dict[str, object]:
    item = _mapping(raw, label="terminal request evidence")
    fields = frozenset(
        {
            "authority_generation_sha256",
            "checkpoint_identity_sha256",
            "request_closure_receipt_sha256",
            "w2_authority_identity_sha256",
            "temporal_field_denominator_sha256",
            "observation_generation_key_sha256",
            "physical_call_id",
            "request_scope_sha256",
            "source_family",
            "endpoint_name",
            "provider_request_sha256",
            "request_observation_sha256",
            "request_call",
            "disposition",
            "captured_row_count",
            "result_receipt_count",
            "staging_receipt_count",
            "result_receipt_inventory_sha256",
            "staging_receipt_inventory_sha256",
            "typed_upstream_unavailable_evidence_sha256",
            "upstream_support_authority_sha256",
            "safe_probe_receipt_sha256",
            "unavailable_reason_code",
            "validity_scope_start",
            "validity_scope_end",
            "independent_verifier_id",
            "independent_verifier_sha256",
            "revalidation_policy",
            "evidence_sha256",
        }
    )
    _exact_keys(
        item,
        expected=frozenset({"schema_version", "kind", *fields}),
        label="terminal request evidence",
    )
    _schema(item, kind="terminal_request_evidence_v1", label="terminal evidence")
    if item["authority_generation_sha256"] != authority:
        raise IndependentRequestUniverseCandidateError("terminal request evidence is foreign")
    for field in (
        "checkpoint_identity_sha256",
        "request_closure_receipt_sha256",
        "w2_authority_identity_sha256",
        "temporal_field_denominator_sha256",
        "observation_generation_key_sha256",
        "request_scope_sha256",
        "provider_request_sha256",
        "request_observation_sha256",
    ):
        _sha(item[field], label=field)
    _safe_id(item["physical_call_id"], label="physical_call_id")
    if item["source_family"] not in {"stats", "live", "static"}:
        raise IndependentRequestUniverseCandidateError(
            "terminal evidence source family is unsupported"
        )
    _safe_id(item["endpoint_name"], label="endpoint_name")
    request_call = _call(item["request_call"], authority=authority)
    if (
        request_call["physical_call_id"] != item["physical_call_id"]
        or request_call["request_scope_sha256"] != item["request_scope_sha256"]
        or request_call["source_family"] != item["source_family"]
        or request_call["endpoint_name"] != item["endpoint_name"]
    ):
        raise IndependentRequestUniverseCandidateError(
            "terminal evidence logical request call is stale or foreign"
        )
    disposition = item["disposition"]
    if type(disposition) is not str or disposition not in _FINAL_DISPOSITIONS:
        raise IndependentRequestUniverseCandidateError(
            "terminal evidence disposition is unsupported"
        )
    capture_fields = (
        item["captured_row_count"],
        item["result_receipt_count"],
        item["staging_receipt_count"],
        item["result_receipt_inventory_sha256"],
        item["staging_receipt_inventory_sha256"],
    )
    unavailable_names = (
        "typed_upstream_unavailable_evidence_sha256",
        "upstream_support_authority_sha256",
        "safe_probe_receipt_sha256",
        "unavailable_reason_code",
        "validity_scope_start",
        "validity_scope_end",
        "independent_verifier_id",
        "independent_verifier_sha256",
        "revalidation_policy",
    )
    unavailable_fields = tuple(item[name] for name in unavailable_names)
    if disposition == "upstream_unavailable":
        if any(value is not None for value in capture_fields) or any(
            value is None for value in unavailable_fields
        ):
            raise IndependentRequestUniverseCandidateError(
                "typed upstream-unavailable evidence fields are invalid"
            )
        for field in (
            "typed_upstream_unavailable_evidence_sha256",
            "upstream_support_authority_sha256",
            "safe_probe_receipt_sha256",
            "independent_verifier_sha256",
        ):
            _sha(item[field], label=field)
        for field in (
            "validity_scope_start",
            "validity_scope_end",
            "independent_verifier_id",
        ):
            _safe_id(item[field], label=field)
        if (
            item["unavailable_reason_code"] != "provider_contract_absent_for_scope"
            or item["revalidation_policy"] != "on_authority_or_scope_change"
        ):
            raise IndependentRequestUniverseCandidateError(
                "upstream-unavailable policy is unsupported"
            )
    else:
        if any(value is not None for value in unavailable_fields):
            raise IndependentRequestUniverseCandidateError(
                "captured evidence carries unavailable support"
            )
        row_count = _nonnegative_int(item["captured_row_count"], label="captured_row_count")
        result_count = _nonnegative_int(item["result_receipt_count"], label="result_receipt_count")
        staging_count = _nonnegative_int(
            item["staging_receipt_count"], label="staging_receipt_count"
        )
        _sha(
            item["result_receipt_inventory_sha256"],
            label="result_receipt_inventory_sha256",
        )
        _sha(
            item["staging_receipt_inventory_sha256"],
            label="staging_receipt_inventory_sha256",
        )
        if (disposition == "captured_nonempty") != (row_count > 0):
            raise IndependentRequestUniverseCandidateError(
                "captured evidence row count contradicts disposition"
            )
        if result_count < 1 or staging_count < 1:
            raise IndependentRequestUniverseCandidateError(
                "captured evidence lacks present result/staging receipts"
            )
    body = {key: value for key, value in item.items() if key != "evidence_sha256"}
    if item["evidence_sha256"] != _sha256(body):
        raise IndependentRequestUniverseCandidateError("terminal evidence digest differs")
    return {**item, "request_call": request_call}


def _final_classification(
    raw: object,
    *,
    authority: str,
    observation_generation: str,
) -> dict[str, object]:
    item = _mapping(raw, label="terminal classification")
    _exact_keys(
        item,
        expected=frozenset(
            {
                "schema_version",
                "kind",
                "authority_generation_sha256",
                "committed_observation_generation_sha256",
                "physical_call_id",
                "request_scope_sha256",
                "disposition",
                "evidence",
            }
        ),
        label="terminal classification",
    )
    _schema(item, kind="terminal_request_classification_v1", label="classification")
    if (
        item["authority_generation_sha256"] != authority
        or item["committed_observation_generation_sha256"] != observation_generation
    ):
        raise IndependentRequestUniverseCandidateError(
            "terminal classification is stale or foreign"
        )
    physical_call_id = _safe_id(item["physical_call_id"], label="physical_call_id")
    request_scope = _sha(item["request_scope_sha256"], label="request_scope_sha256")
    disposition = item["disposition"]
    if type(disposition) is not str or disposition not in _FINAL_DISPOSITIONS:
        raise IndependentRequestUniverseCandidateError(
            "terminal classification disposition is unsupported"
        )
    evidence = _terminal_evidence(item["evidence"], authority=authority)
    if (
        evidence["physical_call_id"] != physical_call_id
        or evidence["request_scope_sha256"] != request_scope
        or evidence["disposition"] != disposition
    ):
        raise IndependentRequestUniverseCandidateError(
            "terminal classification is rebound from typed evidence"
        )
    return {
        **item,
        "physical_call_id": physical_call_id,
        "request_scope_sha256": request_scope,
        "evidence": evidence,
    }


def _final_shard(raw: object, *, authority: str) -> dict[str, object]:
    item = _mapping(raw, label="request-universe shard")
    _exact_keys(
        item,
        expected=frozenset(
            {
                "schema_version",
                "kind",
                "authority_generation_sha256",
                "shard_id",
                "physical_call_ids",
                "request_inventory_sha256",
            }
        ),
        label="request-universe shard",
    )
    _schema(item, kind="request_universe_shard_v1", label="request-universe shard")
    if item["authority_generation_sha256"] != authority:
        raise IndependentRequestUniverseCandidateError("request shard is foreign")
    shard_id = _safe_id(item["shard_id"], label="shard_id")
    ids = [
        _safe_id(value, label="shard physical_call_id")
        for value in _array(
            item["physical_call_ids"], label="physical_call_ids", maximum=_MAX_CALLS
        )
    ]
    if not ids or ids != sorted(set(ids)):
        raise IndependentRequestUniverseCandidateError(
            "request shard IDs are empty, duplicated, or unsorted"
        )
    if item["request_inventory_sha256"] != _sha256(ids):
        raise IndependentRequestUniverseCandidateError("request shard inventory digest differs")
    return {
        **item,
        "shard_id": shard_id,
        "physical_call_ids": ids,
    }


def _committed_observation_generation(
    raw: object,
    *,
    authority: str,
) -> dict[str, object]:
    item = _mapping(raw, label="committed observation generation")
    expected = frozenset(
        {
            "schema_version",
            "kind",
            "authority_generation_sha256",
            "checkpoint_identity_sha256",
            "request_closure_receipt_sha256",
            "w2_authority_identity_sha256",
            "temporal_field_denominator_sha256",
            "parent_observation_generation_sha256",
            "generation_ordinal",
            "generation_key_sha256",
            "closure_fixed_point_provider_request_count",
            "closure_fixed_point_provider_request_inventory_sha256",
            "closure_fixed_point_provider_request_sha256s",
            "terminal_evidence_count",
            "next_generation_call_count",
            "terminal_evidence_inventory_sha256",
            "next_generation_call_inventory_sha256",
            "terminal_evidence",
            "next_generation_calls",
            "generation_sha256",
        }
    )
    _exact_keys(item, expected=expected, label="committed observation generation")
    _schema(
        item,
        kind="committed_observation_generation_v1",
        label="committed observation generation",
    )
    if item["authority_generation_sha256"] != authority:
        raise IndependentRequestUniverseCandidateError(
            "committed observation generation is foreign"
        )
    for field in (
        "checkpoint_identity_sha256",
        "request_closure_receipt_sha256",
        "w2_authority_identity_sha256",
        "temporal_field_denominator_sha256",
    ):
        _sha(item[field], label=field)
    ordinal = item["generation_ordinal"]
    if type(ordinal) is not int or ordinal < 1:
        raise IndependentRequestUniverseCandidateError("observation generation ordinal is invalid")
    parent = item["parent_observation_generation_sha256"]
    if parent is None:
        if ordinal != 1:
            raise IndependentRequestUniverseCandidateError(
                "genesis observation generation ordinal is invalid"
            )
    else:
        _sha(parent, label="parent_observation_generation_sha256")
        if ordinal == 1:
            raise IndependentRequestUniverseCandidateError(
                "non-genesis observation generation ordinal is invalid"
            )
    closure_units = [
        _sha(value, label="closure fixed-point provider request SHA-256")
        for value in _array(
            item["closure_fixed_point_provider_request_sha256s"],
            label="closure_fixed_point_provider_request_sha256s",
            maximum=_MAX_CALLS,
        )
    ]
    if not closure_units or closure_units != sorted(set(closure_units)):
        raise IndependentRequestUniverseCandidateError(
            "closure fixed-point provider request inventory is invalid"
        )
    closure_root = _sha256(closure_units)
    if (
        type(item["closure_fixed_point_provider_request_count"]) is not int
        or item["closure_fixed_point_provider_request_count"] != len(closure_units)
        or item["closure_fixed_point_provider_request_inventory_sha256"] != closure_root
    ):
        raise IndependentRequestUniverseCandidateError(
            "closure fixed-point provider request count or digest differs"
        )
    key_body = {
        field: item[field]
        for field in (
            "authority_generation_sha256",
            "checkpoint_identity_sha256",
            "request_closure_receipt_sha256",
            "w2_authority_identity_sha256",
            "temporal_field_denominator_sha256",
            "parent_observation_generation_sha256",
            "generation_ordinal",
        )
    }
    key_body["closure_fixed_point_provider_request_inventory_sha256"] = closure_root
    generation_key = _sha256(key_body)
    if item["generation_key_sha256"] != generation_key:
        raise IndependentRequestUniverseCandidateError("observation generation key differs")
    evidence = [
        _terminal_evidence(value, authority=authority)
        for value in _array(
            item["terminal_evidence"],
            label="terminal_evidence",
            maximum=_MAX_CALLS,
        )
    ]
    evidence_ids = [value["physical_call_id"] for value in evidence]
    if not evidence or evidence_ids != sorted(set(evidence_ids)):
        raise IndependentRequestUniverseCandidateError(
            "terminal evidence inventory is duplicated or unsorted"
        )
    serialized_calls = [
        _call(value, authority=authority)
        for value in _array(
            item["next_generation_calls"],
            label="next_generation_calls",
            maximum=_MAX_CALLS,
        )
    ]
    calls = [cast("dict[str, object]", value["request_call"]) for value in evidence]
    call_ids = [value["physical_call_id"] for value in calls]
    if not calls or call_ids != sorted(set(call_ids)) or serialized_calls != calls:
        raise IndependentRequestUniverseCandidateError(
            "serialized next-generation calls differ from typed evidence derivation"
        )
    roots = (
        item["checkpoint_identity_sha256"],
        item["request_closure_receipt_sha256"],
        item["w2_authority_identity_sha256"],
        item["temporal_field_denominator_sha256"],
    )
    if any(
        value["observation_generation_key_sha256"] != generation_key
        or (
            value["checkpoint_identity_sha256"],
            value["request_closure_receipt_sha256"],
            value["w2_authority_identity_sha256"],
            value["temporal_field_denominator_sha256"],
        )
        != roots
        for value in evidence
    ):
        raise IndependentRequestUniverseCandidateError(
            "terminal evidence is foreign to its observation generation"
        )
    if sorted({cast("str", value["provider_request_sha256"]) for value in evidence}) != (
        closure_units
    ):
        raise IndependentRequestUniverseCandidateError(
            "terminal evidence differs from the closure fixed-point request inventory"
        )
    if (
        type(item["terminal_evidence_count"]) is not int
        or item["terminal_evidence_count"] != len(evidence)
        or type(item["next_generation_call_count"]) is not int
        or item["next_generation_call_count"] != len(calls)
        or item["terminal_evidence_inventory_sha256"] != _sha256(evidence)
        or item["next_generation_call_inventory_sha256"] != _sha256(calls)
    ):
        raise IndependentRequestUniverseCandidateError(
            "committed observation generation inventory differs"
        )
    normalized = {
        **item,
        "closure_fixed_point_provider_request_sha256s": closure_units,
        "terminal_evidence": evidence,
        "next_generation_calls": calls,
    }
    body = {key: value for key, value in normalized.items() if key != "generation_sha256"}
    if item["generation_sha256"] != _sha256(body):
        raise IndependentRequestUniverseCandidateError(
            "committed observation generation digest differs"
        )
    return normalized


def _finalization_source(raw: Mapping[str, object]) -> dict[str, object]:
    item = _mapping(raw, label="request-universe finalization source")
    _exact_keys(
        item,
        expected=frozenset(
            {
                "schema_version",
                "kind",
                *_FINAL_SOURCE_SCALARS,
                "logical_calls",
                "terminal_classifications",
                "committed_observation_generation",
                "shards",
                "ancestor_request_universe_sha256s",
            }
        ),
        label="request-universe finalization source",
    )
    _schema(
        item,
        kind="request_universe_finalization_source_v1",
        label="request-universe finalization source",
    )
    authority = _sha(item["authority_generation_sha256"], label="authority_generation_sha256")
    for field in _FINAL_SOURCE_SCALARS - {
        "parent_request_universe_sha256",
        "generation_ordinal",
    }:
        _sha(item[field], label=field)
    for field in (
        "checkpoint_authority_generation_sha256",
        "request_closure_authority_generation_sha256",
        "w2_authority_generation_sha256",
        "temporal_field_authority_generation_sha256",
        "committed_observation_authority_generation_sha256",
    ):
        if item[field] != authority:
            raise IndependentRequestUniverseCandidateError(
                "finalization source contains stale authority evidence"
            )
    observation_generation = _committed_observation_generation(
        item["committed_observation_generation"],
        authority=authority,
    )
    if (
        observation_generation["generation_sha256"]
        != item["committed_observation_generation_sha256"]
        or observation_generation["checkpoint_identity_sha256"]
        != item["checkpoint_identity_sha256"]
        or observation_generation["request_closure_receipt_sha256"]
        != item["request_closure_receipt_sha256"]
        or observation_generation["w2_authority_identity_sha256"]
        != item["w2_authority_identity_sha256"]
        or observation_generation["temporal_field_denominator_sha256"]
        != item["temporal_field_denominator_sha256"]
    ):
        raise IndependentRequestUniverseCandidateError(
            "committed observation generation is stale or foreign"
        )
    calls = [
        _call(value, authority=authority)
        for value in _array(item["logical_calls"], label="logical_calls", maximum=_MAX_CALLS)
    ]
    if not calls or [call["physical_call_id"] for call in calls] != sorted(
        {call["physical_call_id"] for call in calls}
    ):
        raise IndependentRequestUniverseCandidateError(
            "final logical request denominator is duplicated or unsorted"
        )
    observation_generation_sha = cast("str", item["committed_observation_generation_sha256"])
    classifications = [
        _final_classification(
            value,
            authority=authority,
            observation_generation=observation_generation_sha,
        )
        for value in _array(
            item["terminal_classifications"],
            label="terminal_classifications",
            maximum=_MAX_CALLS,
        )
    ]
    classification_ids = [value["physical_call_id"] for value in classifications]
    if classification_ids != sorted(set(classification_ids)):
        raise IndependentRequestUniverseCandidateError(
            "terminal classifications are duplicated or unsorted"
        )
    call_by_id = {cast("str", call["physical_call_id"]): call for call in calls}
    if set(classification_ids) != set(call_by_id):
        raise IndependentRequestUniverseCandidateError(
            "terminal classifications differ from the request denominator"
        )
    if any(
        value["request_scope_sha256"]
        != call_by_id[cast("str", value["physical_call_id"])]["request_scope_sha256"]
        for value in classifications
    ):
        raise IndependentRequestUniverseCandidateError(
            "terminal classification request scope differs"
        )
    evidence_by_call = {
        value["physical_call_id"]: value
        for value in cast(
            "list[dict[str, object]]",
            observation_generation["terminal_evidence"],
        )
    }
    if any(
        evidence_by_call.get(value["physical_call_id"]) != value["evidence"]
        for value in classifications
    ):
        raise IndependentRequestUniverseCandidateError(
            "terminal classification differs from committed typed evidence"
        )
    shards = [
        _final_shard(value, authority=authority)
        for value in _array(item["shards"], label="shards", maximum=_MAX_CALLS)
    ]
    if not shards or [shard["shard_id"] for shard in shards] != sorted(
        {shard["shard_id"] for shard in shards}
    ):
        raise IndependentRequestUniverseCandidateError("request shards are duplicated or unsorted")
    partition = [
        physical_call_id
        for shard in shards
        for physical_call_id in cast("list[str]", shard["physical_call_ids"])
    ]
    if len(partition) != len(set(partition)) or set(partition) != set(call_by_id):
        raise IndependentRequestUniverseCandidateError(
            "request shard partition overlaps, omits, or invents calls"
        )
    next_call_ids = {
        value["physical_call_id"]
        for value in cast(
            "list[dict[str, object]]",
            observation_generation["next_generation_calls"],
        )
    }
    if not set(call_by_id) <= next_call_ids:
        raise IndependentRequestUniverseCandidateError(
            "derived next generation omits an admitted call"
        )
    ancestry = [
        _sha(value, label="ancestor_request_universe_sha256")
        for value in _array(
            item["ancestor_request_universe_sha256s"],
            label="ancestor_request_universe_sha256s",
            maximum=_MAX_CALLS,
        )
    ]
    if len(ancestry) != len(set(ancestry)):
        raise IndependentRequestUniverseCandidateError("request-universe ancestry is cyclic")
    parent = item["parent_request_universe_sha256"]
    ordinal = item["generation_ordinal"]
    if type(ordinal) is not int or ordinal < 1:
        raise IndependentRequestUniverseCandidateError("generation ordinal is invalid")
    if parent is None:
        if ancestry or ordinal != 1:
            raise IndependentRequestUniverseCandidateError("genesis ancestry is invalid")
    elif (
        not ancestry
        or _sha(parent, label="parent_request_universe_sha256") != ancestry[-1]
        or ordinal != len(ancestry) + 1
    ):
        raise IndependentRequestUniverseCandidateError(
            "request-universe parent or generation differs from ancestry"
        )
    return {
        **item,
        "logical_calls": calls,
        "terminal_classifications": classifications,
        "committed_observation_generation": observation_generation,
        "shards": shards,
        "ancestor_request_universe_sha256s": ancestry,
    }


def _closure_fixed_point_provider_requests(
    raw: Mapping[str, object],
    *,
    expected_receipt_sha256: object,
) -> list[str]:
    """Independently recover the exact final provider-request fixed point."""

    item = _mapping(raw, label="request-closure runtime receipt")
    _exact_keys(
        item,
        expected=frozenset(
            {
                "schema_version",
                "kind",
                "request_surface_sha256",
                "terminal_policy_sha256",
                "route_manifest_sha256",
                "scope_sha256",
                "unit_inventory_sha256",
                "request_binding_inventory_sha256",
                "terminal_inventory_sha256",
                "staging_receipt_inventory_sha256",
                "persisted_staging_receipt_roots",
                "persisted_staging_receipt_roots_sha256",
                "route_manifest",
                "scope",
                "observations",
                "closure",
            }
        ),
        label="request-closure runtime receipt",
    )
    if item["schema_version"] != 2 or item["kind"] != "nbadb_request_closure_runtime_receipt":
        raise IndependentRequestUniverseCandidateError(
            "request-closure runtime schema identity is invalid"
        )
    try:
        encoded = json.dumps(
            item,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
            allow_nan=False,
        ).encode("utf-8")
    except (TypeError, ValueError, RecursionError) as exc:
        raise IndependentRequestUniverseCandidateError(
            "request-closure runtime receipt is not canonical JSON data"
        ) from exc
    if hashlib.sha256(encoded).hexdigest() != _sha(
        expected_receipt_sha256,
        label="request_closure_receipt_sha256",
    ):
        raise IndependentRequestUniverseCandidateError(
            "request-closure runtime receipt digest differs from finalization source"
        )
    closure = _mapping(item["closure"], label="request closure")
    iterations = _array(
        closure.get("iterations"),
        label="request closure iterations",
        maximum=_MAX_CALLS,
    )
    if len(iterations) < 2:
        raise IndependentRequestUniverseCandidateError(
            "request closure lacks a fixed-point iteration chain"
        )
    previous_output: list[str] = []
    for ordinal, raw_iteration in enumerate(iterations):
        iteration = _mapping(raw_iteration, label="request closure iteration")
        _exact_keys(
            iteration,
            expected=frozenset(
                {
                    "iteration",
                    "request_surface_sha256",
                    "scope_sha256",
                    "input_units",
                    "new_units",
                    "output_units",
                    "evidence",
                }
            ),
            label="request closure iteration",
        )
        if iteration["iteration"] != ordinal:
            raise IndependentRequestUniverseCandidateError(
                "request closure iteration chain is noncontiguous"
            )
        input_units = [
            _sha(value, label="request closure input unit")
            for value in _array(
                iteration["input_units"],
                label="request closure input_units",
                maximum=_MAX_CALLS,
            )
        ]
        new_units = [
            _sha(value, label="request closure new unit")
            for value in _array(
                iteration["new_units"],
                label="request closure new_units",
                maximum=_MAX_CALLS,
            )
        ]
        output_units = [
            _sha(value, label="request closure output unit")
            for value in _array(
                iteration["output_units"],
                label="request closure output_units",
                maximum=_MAX_CALLS,
            )
        ]
        if (
            input_units != previous_output
            or input_units != sorted(set(input_units))
            or new_units != sorted(set(new_units))
            or set(input_units) & set(new_units)
            or output_units != sorted(set((*input_units, *new_units)))
        ):
            raise IndependentRequestUniverseCandidateError(
                "request closure iteration is not an exact set-union chain"
            )
        previous_output = output_units
    final = _mapping(iterations[-1], label="final request closure iteration")
    final_evidence = _array(
        final["evidence"],
        label="final request closure evidence",
        maximum=_MAX_CALLS,
    )
    if final["new_units"] != [] or not any(
        type(value) is dict
        and value.get("evidence_kind") == "fixed_point"
        and value.get("complete") is True
        and value.get("discovered_units") == []
        and value.get("input_units") == previous_output
        for value in final_evidence
    ):
        raise IndependentRequestUniverseCandidateError(
            "request closure lacks exact complete zero-growth evidence"
        )
    unit_root = _sha256(previous_output)
    independent_proof = _mapping(
        closure.get("independent_proof"),
        label="request closure independent proof",
    )
    if (
        item["unit_inventory_sha256"] != unit_root
        or independent_proof.get("unit_inventory_sha256") != unit_root
        or independent_proof.get("verifier_id") == "nbadb_request_surface_primary_v2"
    ):
        raise IndependentRequestUniverseCandidateError(
            "request closure fixed-point inventory lacks independent agreement"
        )
    observed_units = sorted(
        _sha(
            _mapping(value, label="request closure observation").get("provider_request_sha256"),
            label="observation provider_request_sha256",
        )
        for value in _array(
            item["observations"],
            label="request closure observations",
            maximum=_MAX_CALLS,
        )
    )
    if observed_units != previous_output or len(observed_units) != len(set(observed_units)):
        raise IndependentRequestUniverseCandidateError(
            "request closure observations differ from its exact fixed point"
        )
    return previous_output


def _expected_final_universe(source: Mapping[str, object]) -> dict[str, object]:
    calls = cast("list[dict[str, object]]", source["logical_calls"])
    classifications = cast("list[dict[str, object]]", source["terminal_classifications"])
    shards = cast("list[dict[str, object]]", source["shards"])
    logical_inventory = _sha256(calls)
    source_sha = _sha256(source)
    empty_root = _sha256([])
    observation_generation = cast("dict[str, object]", source["committed_observation_generation"])
    next_calls = cast("list[dict[str, object]]", observation_generation["next_generation_calls"])
    admitted_ids = {call["physical_call_id"] for call in calls}
    delta = [call for call in next_calls if call["physical_call_id"] not in admitted_ids]
    if delta:
        raise IndependentRequestUniverseCandidateError(
            "independent compiler derived a nonempty next-generation delta"
        )
    receipt_body: dict[str, object] = {
        "schema_version": _FINAL_SCHEMA_VERSION,
        "kind": "request_universe_empty_delta_receipt_v1",
        "authority_generation_sha256": source["authority_generation_sha256"],
        "finalization_source_sha256": source_sha,
        "committed_observation_generation_sha256": source[
            "committed_observation_generation_sha256"
        ],
        "derivation_input_sha256": observation_generation["generation_sha256"],
        "admitted_call_inventory_sha256": logical_inventory,
        "derived_call_inventory_sha256": observation_generation[
            "next_generation_call_inventory_sha256"
        ],
        "derived_call_count": len(next_calls),
        "logical_call_inventory_sha256": logical_inventory,
        "logical_call_count": len(calls),
        "delta_inventory_sha256": empty_root,
        "delta_count": 0,
        "compiler_id": "primary_request_universe_v1",
    }
    primary_receipt = {**receipt_body, "receipt_sha256": _sha256(receipt_body)}
    return {
        "schema_version": _FINAL_SCHEMA_VERSION,
        "kind": "request_universe_v1",
        **{
            key: source[key]
            for key in (
                "authority_generation_sha256",
                "checkpoint_identity_sha256",
                "request_closure_receipt_sha256",
                "w2_authority_identity_sha256",
                "temporal_field_denominator_sha256",
                "committed_observation_generation_sha256",
                "candidate_source_sha256",
                "candidate_generation_sha256",
                "candidate_independent_proof_sha256",
                "source_admission_sha256",
                "parent_request_universe_sha256",
                "generation_ordinal",
            )
        },
        "finalization_source_sha256": source_sha,
        "logical_call_inventory_sha256": logical_inventory,
        "terminal_classification_inventory_sha256": _sha256(classifications),
        "shard_inventory_sha256": _sha256(shards),
        "logical_call_count": len(calls),
        "terminal_classification_count": len(classifications),
        "shard_count": len(shards),
        "logical_calls": calls,
        "terminal_classifications": classifications,
        "shards": shards,
        "primary_empty_delta_receipt": primary_receipt,
        "exact_request_denominator": True,
        "terminal_classification_complete": True,
        "shard_partition_exact": True,
        "least_fixed_point_proven": True,
        "terminal": True,
        "release_eligible": False,
    }


@dataclass(frozen=True, slots=True)
class RequestUniverseIndependentProofV1:
    authority_generation_sha256: str
    finalization_source_sha256: str
    request_universe_sha256: str
    logical_call_inventory_sha256: str
    terminal_classification_inventory_sha256: str
    shard_inventory_sha256: str
    logical_call_count: int
    exact_inventory_equal: Literal[True]
    shard_partition_exact: Literal[True]
    terminal_classification_complete: Literal[True]
    verifier_id: Literal["independent_request_universe_v1"]
    proof_sha256: str

    schema_version: ClassVar[int] = _FINAL_SCHEMA_VERSION
    kind: ClassVar[str] = "request_universe_independent_proof_v1"

    def __post_init__(self) -> None:
        for field in (
            "authority_generation_sha256",
            "finalization_source_sha256",
            "request_universe_sha256",
            "logical_call_inventory_sha256",
            "terminal_classification_inventory_sha256",
            "shard_inventory_sha256",
        ):
            _sha(getattr(self, field), label=field)
        _nonnegative_int(self.logical_call_count, label="logical_call_count")
        if (
            self.exact_inventory_equal is not True
            or self.shard_partition_exact is not True
            or self.terminal_classification_complete is not True
            or self.verifier_id != "independent_request_universe_v1"
            or self.proof_sha256 != _sha256(self._body())
        ):
            raise IndependentRequestUniverseCandidateError(
                "independent final request-universe proof is invalid"
            )

    def _body(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "kind": self.kind,
            **{
                field: getattr(self, field)
                for field in (
                    "authority_generation_sha256",
                    "finalization_source_sha256",
                    "request_universe_sha256",
                    "logical_call_inventory_sha256",
                    "terminal_classification_inventory_sha256",
                    "shard_inventory_sha256",
                    "logical_call_count",
                    "exact_inventory_equal",
                    "shard_partition_exact",
                    "terminal_classification_complete",
                    "verifier_id",
                )
            },
        }

    def to_dict(self) -> dict[str, object]:
        return {**self._body(), "proof_sha256": self.proof_sha256}

    @property
    def canonical_bytes(self) -> bytes:
        return _canonical_bytes(self.to_dict())

    @classmethod
    def from_dict(cls, payload: Mapping[str, object]) -> Self:
        item = _mapping(payload, label="independent request-universe proof")
        fields = frozenset(
            {
                "authority_generation_sha256",
                "finalization_source_sha256",
                "request_universe_sha256",
                "logical_call_inventory_sha256",
                "terminal_classification_inventory_sha256",
                "shard_inventory_sha256",
                "logical_call_count",
                "exact_inventory_equal",
                "shard_partition_exact",
                "terminal_classification_complete",
                "verifier_id",
                "proof_sha256",
            }
        )
        _exact_keys(
            item,
            expected=frozenset({"schema_version", "kind", *fields}),
            label="independent request-universe proof",
        )
        _schema(item, kind=cls.kind, label="independent request-universe proof")
        return cls(**cast("Any", {field: item[field] for field in fields}))

    @classmethod
    def from_canonical_bytes(cls, raw: bytes) -> Self:
        result = cls.from_dict(_decode_canonical_mapping(raw, label="final proof"))
        if result.canonical_bytes != raw:
            raise IndependentRequestUniverseCandidateError(
                "independent final proof is not canonical"
            )
        return result


@dataclass(frozen=True, slots=True)
class RequestUniverseIndependentEmptyDeltaReceiptV1:
    authority_generation_sha256: str
    finalization_source_sha256: str
    request_universe_sha256: str
    independent_proof_sha256: str
    committed_observation_generation_sha256: str
    derivation_input_sha256: str
    admitted_call_inventory_sha256: str
    derived_call_inventory_sha256: str
    derived_call_count: int
    logical_call_inventory_sha256: str
    logical_call_count: int
    delta_inventory_sha256: str
    delta_count: Literal[0]
    compiler_id: Literal["independent_request_universe_v1"]
    receipt_sha256: str

    schema_version: ClassVar[int] = _FINAL_SCHEMA_VERSION
    kind: ClassVar[str] = "request_universe_independent_empty_delta_receipt_v1"

    def __post_init__(self) -> None:
        for field in (
            "authority_generation_sha256",
            "finalization_source_sha256",
            "request_universe_sha256",
            "independent_proof_sha256",
            "committed_observation_generation_sha256",
            "derivation_input_sha256",
            "admitted_call_inventory_sha256",
            "derived_call_inventory_sha256",
            "logical_call_inventory_sha256",
            "delta_inventory_sha256",
        ):
            _sha(getattr(self, field), label=field)
        _nonnegative_int(self.logical_call_count, label="logical_call_count")
        _nonnegative_int(self.derived_call_count, label="derived_call_count")
        if (
            type(self.delta_count) is not int
            or self.delta_count != 0
            or self.delta_inventory_sha256 != _sha256([])
            or self.compiler_id != "independent_request_universe_v1"
            or self.admitted_call_inventory_sha256 != self.logical_call_inventory_sha256
            or self.receipt_sha256 != _sha256(self._body())
        ):
            raise IndependentRequestUniverseCandidateError(
                "independent empty-delta receipt is invalid"
            )

    def _body(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "kind": self.kind,
            **{
                field: getattr(self, field)
                for field in (
                    "authority_generation_sha256",
                    "finalization_source_sha256",
                    "request_universe_sha256",
                    "independent_proof_sha256",
                    "committed_observation_generation_sha256",
                    "derivation_input_sha256",
                    "admitted_call_inventory_sha256",
                    "derived_call_inventory_sha256",
                    "derived_call_count",
                    "logical_call_inventory_sha256",
                    "logical_call_count",
                    "delta_inventory_sha256",
                    "delta_count",
                    "compiler_id",
                )
            },
        }

    def to_dict(self) -> dict[str, object]:
        return {**self._body(), "receipt_sha256": self.receipt_sha256}

    @property
    def canonical_bytes(self) -> bytes:
        return _canonical_bytes(self.to_dict())

    @classmethod
    def from_dict(cls, payload: Mapping[str, object]) -> Self:
        item = _mapping(payload, label="independent empty-delta receipt")
        fields = frozenset(
            {
                "authority_generation_sha256",
                "finalization_source_sha256",
                "request_universe_sha256",
                "independent_proof_sha256",
                "committed_observation_generation_sha256",
                "derivation_input_sha256",
                "admitted_call_inventory_sha256",
                "derived_call_inventory_sha256",
                "derived_call_count",
                "logical_call_inventory_sha256",
                "logical_call_count",
                "delta_inventory_sha256",
                "delta_count",
                "compiler_id",
                "receipt_sha256",
            }
        )
        _exact_keys(
            item,
            expected=frozenset({"schema_version", "kind", *fields}),
            label="independent empty-delta receipt",
        )
        _schema(item, kind=cls.kind, label="independent empty-delta receipt")
        return cls(**cast("Any", {field: item[field] for field in fields}))

    @classmethod
    def from_canonical_bytes(cls, raw: bytes) -> Self:
        result = cls.from_dict(
            _decode_canonical_mapping(raw, label="independent empty-delta receipt")
        )
        if result.canonical_bytes != raw:
            raise IndependentRequestUniverseCandidateError(
                "independent empty-delta receipt is not canonical"
            )
        return result


def verify_request_universe_v1_independently(
    *,
    finalization_source_payload: Mapping[str, object],
    request_universe_payload: Mapping[str, object],
    request_closure_payload: Mapping[str, object],
) -> tuple[
    RequestUniverseIndependentProofV1,
    RequestUniverseIndependentEmptyDeltaReceiptV1,
]:
    """Independently compile the final universe and prove the same empty delta."""

    source = _finalization_source(finalization_source_payload)
    closure_units = _closure_fixed_point_provider_requests(
        request_closure_payload,
        expected_receipt_sha256=source["request_closure_receipt_sha256"],
    )
    observation_generation = cast("dict[str, object]", source["committed_observation_generation"])
    if observation_generation["closure_fixed_point_provider_request_sha256s"] != closure_units:
        raise IndependentRequestUniverseCandidateError(
            "committed observation generation differs from the typed closure fixed point"
        )
    expected = _expected_final_universe(source)
    observed = _mapping(request_universe_payload, label="request universe")
    if _canonical_bytes(observed) != _canonical_bytes(expected):
        raise IndependentRequestUniverseCandidateError(
            "final request universe disagrees with independent compilation"
        )
    universe_sha = _sha256(observed)
    proof_body: dict[str, object] = {
        "schema_version": _FINAL_SCHEMA_VERSION,
        "kind": RequestUniverseIndependentProofV1.kind,
        "authority_generation_sha256": source["authority_generation_sha256"],
        "finalization_source_sha256": _sha256(source),
        "request_universe_sha256": universe_sha,
        "logical_call_inventory_sha256": expected["logical_call_inventory_sha256"],
        "terminal_classification_inventory_sha256": expected[
            "terminal_classification_inventory_sha256"
        ],
        "shard_inventory_sha256": expected["shard_inventory_sha256"],
        "logical_call_count": expected["logical_call_count"],
        "exact_inventory_equal": True,
        "shard_partition_exact": True,
        "terminal_classification_complete": True,
        "verifier_id": "independent_request_universe_v1",
    }
    proof_values = {
        key: value for key, value in proof_body.items() if key not in {"schema_version", "kind"}
    }
    proof = RequestUniverseIndependentProofV1(
        **cast("Any", proof_values),
        proof_sha256=_sha256(proof_body),
    )
    next_calls = cast("list[dict[str, object]]", observation_generation["next_generation_calls"])
    admitted_ids = {
        call["physical_call_id"]
        for call in cast("list[dict[str, object]]", source["logical_calls"])
    }
    independent_delta = [
        call for call in next_calls if call["physical_call_id"] not in admitted_ids
    ]
    if independent_delta:
        raise IndependentRequestUniverseCandidateError(
            "independent receipt compiler derived a nonempty delta"
        )
    receipt_body: dict[str, object] = {
        "schema_version": _FINAL_SCHEMA_VERSION,
        "kind": RequestUniverseIndependentEmptyDeltaReceiptV1.kind,
        "authority_generation_sha256": source["authority_generation_sha256"],
        "finalization_source_sha256": _sha256(source),
        "request_universe_sha256": universe_sha,
        "independent_proof_sha256": proof.proof_sha256,
        "committed_observation_generation_sha256": source[
            "committed_observation_generation_sha256"
        ],
        "derivation_input_sha256": observation_generation["generation_sha256"],
        "admitted_call_inventory_sha256": expected["logical_call_inventory_sha256"],
        "derived_call_inventory_sha256": observation_generation[
            "next_generation_call_inventory_sha256"
        ],
        "derived_call_count": len(next_calls),
        "logical_call_inventory_sha256": expected["logical_call_inventory_sha256"],
        "logical_call_count": expected["logical_call_count"],
        "delta_inventory_sha256": _sha256([]),
        "delta_count": 0,
        "compiler_id": "independent_request_universe_v1",
    }
    receipt_values = {
        key: value for key, value in receipt_body.items() if key not in {"schema_version", "kind"}
    }
    receipt = RequestUniverseIndependentEmptyDeltaReceiptV1(
        **cast("Any", receipt_values),
        receipt_sha256=_sha256(receipt_body),
    )
    return proof, receipt
