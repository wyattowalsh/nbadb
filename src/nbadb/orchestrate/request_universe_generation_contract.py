"""Nonterminal, literal-input compiler for one request-universe candidate.

This module intentionally does not build ``RequestUniverseV1``.  It conserves
an explicit frozen set of physical calls, route/result members, route-local
field occurrences, and explicitly typed temporal values into a candidate
generation whose field-period cells are all ``evidence_insufficient``.

No registry, provider, filesystem, clock, or environment is consulted.  In
particular, planner floors and declared season capabilities are not temporal
evidence.  Cumulative-stat workload values are not integrated here and are
therefore retained only as blocking evidence, never executable request units.
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass, field
from enum import StrEnum
from typing import TYPE_CHECKING, Any, ClassVar, Literal, Self, cast

if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence

    from nbadb.contracts.field_fate_contract import ProviderFieldFateContract
    from nbadb.contracts.temporal_availability_contract import RouteTemporalScope
    from nbadb.orchestrate.cume_workload_contract import CumeWorkloadValue

__all__ = [
    "REQUEST_UNIVERSE_CANDIDATE_SCHEMA_VERSION",
    "CandidateBlockerV1",
    "CommittedObservationGenerationV1",
    "ExplicitTemporalScopeValueV1",
    "FieldOccurrenceInputV1",
    "FieldPeriodDenominatorCellV1",
    "LogicalRequestCallV1",
    "RequestUniverseCandidateContractError",
    "RequestUniverseCandidateGenerationV1",
    "RequestUniverseCandidateSourceV1",
    "RequestUniverseEmptyDeltaReceiptV1",
    "RequestUniverseFinalizationSourceV1",
    "RequestUniverseShardV1",
    "RequestUniverseV1",
    "RouteRequestMemberV1",
    "TerminalRequestClassificationV1",
    "TerminalRequestDisposition",
    "TerminalRequestEvidenceV1",
    "TemporalScopeKind",
    "UnintegratedCumeValueV1",
    "canonical_request_universe_json_bytes",
    "canonical_request_universe_sha256",
    "compile_request_universe_candidate_generation_v1",
    "compile_request_universe_v1",
]

REQUEST_UNIVERSE_CANDIDATE_SCHEMA_VERSION = 1
REQUEST_UNIVERSE_FINAL_SCHEMA_VERSION = 1

_SHA256_RE = re.compile(r"[0-9a-f]{64}")
_SAFE_ID_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.:/#-]{0,511}")
_SEASON_RE = re.compile(r"([0-9]{4})-([0-9]{2})")
_DATE_RE = re.compile(r"([0-9]{4})-([0-9]{2})-([0-9]{2})")
_GAME_ID_RE = re.compile(r"[0-9]{10}")
_CUME_REASON_RE = re.compile(r"[a-z0-9][a-z0-9_]*")
_MAX_TEXT = 1_024
_MAX_PARAMETERS = 256
_MAX_PATH_SEGMENTS = 64
_MAX_CALLS = 250_000
_MAX_ROUTE_MEMBERS = 1_000_000
_MAX_FIELD_OCCURRENCES = 2_000_000
_MAX_TEMPORAL_SCOPES = 2_000_000
_MAX_CELLS = 5_000_000
_MAX_CANONICAL_BYTES = 256 * 1024 * 1024
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

type ParameterScalar = str | int | bool | None
type FrozenParameterValue = ParameterScalar | tuple[ParameterScalar, ...]
type ParameterItems = tuple[tuple[str, FrozenParameterValue], ...]
type NestedPathSegment = str | int


class RequestUniverseCandidateContractError(ValueError):
    """Raised when a candidate input or generation is lossy or inconsistent."""


class TemporalScopeKind(StrEnum):
    """Closed temporal/value dimensions admitted by this candidate slice."""

    SEASON = "season"
    SEASON_TYPE = "season_type"
    GAME_DATE = "game_date"
    GAME_ID = "game_id"
    CALENDAR_YEAR = "calendar_year"
    COMPETITION = "competition"
    RUNTIME_SCOPE = "runtime_scope"


def canonical_request_universe_json_bytes(payload: object) -> bytes:
    """Return the sole canonical JSON representation for this contract."""

    try:
        return json.dumps(
            payload,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=True,
            allow_nan=False,
        ).encode("utf-8")
    except (TypeError, ValueError, RecursionError) as exc:
        raise RequestUniverseCandidateContractError(
            "request-universe candidate value is not canonical JSON"
        ) from exc


def canonical_request_universe_sha256(payload: object) -> str:
    return hashlib.sha256(canonical_request_universe_json_bytes(payload)).hexdigest()


def _require_sha256(value: object, *, field_name: str) -> str:
    if type(value) is not str or _SHA256_RE.fullmatch(value) is None:
        raise RequestUniverseCandidateContractError(
            f"{field_name} must be an exact lowercase SHA-256"
        )
    return value


def _require_safe_id(value: object, *, field_name: str) -> str:
    if type(value) is not str or _SAFE_ID_RE.fullmatch(value) is None:
        raise RequestUniverseCandidateContractError(
            f"{field_name} must be an exact bounded safe identifier"
        )
    return value


def _require_text(value: object, *, field_name: str) -> str:
    if (
        type(value) is not str
        or not value
        or len(value) > _MAX_TEXT
        or any(ord(character) < 0x20 for character in value)
    ):
        raise RequestUniverseCandidateContractError(
            f"{field_name} must be exact bounded non-control text"
        )
    return value


def _require_nonnegative_int(value: object, *, field_name: str) -> int:
    if type(value) is not int or value < 0:
        raise RequestUniverseCandidateContractError(f"{field_name} must be a nonnegative integer")
    return value


def _require_exact_tuple(value: object, *, field_name: str) -> tuple[Any, ...]:
    if type(value) is not tuple:
        raise RequestUniverseCandidateContractError(f"{field_name} must be an exact tuple")
    return cast("tuple[Any, ...]", value)


def _require_sorted_unique(
    value: object,
    *,
    field_name: str,
    key: Any,
    maximum: int,
    allow_empty: bool = True,
) -> tuple[Any, ...]:
    result = _require_exact_tuple(value, field_name=field_name)
    if (not allow_empty and not result) or len(result) > maximum:
        raise RequestUniverseCandidateContractError(
            f"{field_name} has an invalid bounded cardinality"
        )
    expected = tuple(sorted(result, key=key))
    identities = tuple(key(item) for item in result)
    if result != expected or len(identities) != len(set(identities)):
        raise RequestUniverseCandidateContractError(
            f"{field_name} must use canonical sorted unique order"
        )
    return result


def _require_exact_keys(
    payload: Mapping[str, object],
    *,
    expected: frozenset[str],
    label: str,
) -> None:
    if type(payload) is not dict or frozenset(payload) != expected:
        raise RequestUniverseCandidateContractError(f"{label} has missing or unexpected fields")


def _mapping(value: object, *, field_name: str) -> Mapping[str, object]:
    if type(value) is not dict or any(type(key) is not str for key in value):
        raise RequestUniverseCandidateContractError(
            f"{field_name} must be an exact string-keyed object"
        )
    return cast("Mapping[str, object]", value)


def _list(value: object, *, field_name: str) -> list[object]:
    if type(value) is not list:
        raise RequestUniverseCandidateContractError(f"{field_name} must be an exact array")
    return cast("list[object]", value)


def _freeze_parameter_scalar(value: object, *, field_name: str) -> ParameterScalar:
    if value is None or type(value) in {str, int, bool}:
        if type(value) is str and len(value) > _MAX_TEXT:
            raise RequestUniverseCandidateContractError(
                f"{field_name} string value exceeds the bound"
            )
        return cast("ParameterScalar", value)
    raise RequestUniverseCandidateContractError(
        f"{field_name} must be an exact JSON string, integer, boolean, or null"
    )


def _freeze_parameter_value(value: object, *, field_name: str) -> FrozenParameterValue:
    if type(value) is tuple:
        values = value
        if len(values) > _MAX_PARAMETERS:
            raise RequestUniverseCandidateContractError(f"{field_name} array exceeds the bound")
        return tuple(_freeze_parameter_scalar(item, field_name=field_name) for item in values)
    return _freeze_parameter_scalar(value, field_name=field_name)


def _parameter_items(value: object) -> ParameterItems:
    items = _require_exact_tuple(value, field_name="parameter_items")
    if len(items) > _MAX_PARAMETERS:
        raise RequestUniverseCandidateContractError("parameter_items exceeds the bound")
    normalized: list[tuple[str, FrozenParameterValue]] = []
    for raw in items:
        if type(raw) is not tuple or len(raw) != 2:
            raise RequestUniverseCandidateContractError(
                "parameter_items must contain exact name/value tuples"
            )
        name = _require_safe_id(raw[0], field_name="parameter name")
        normalized.append((name, _freeze_parameter_value(raw[1], field_name=f"parameter {name}")))
    result = tuple(normalized)
    names = tuple(name for name, _value in result)
    if names != tuple(sorted(set(names))):
        raise RequestUniverseCandidateContractError(
            "parameter_items names must be sorted and unique"
        )
    return result


def _parameter_items_from_mapping(value: Mapping[str, object]) -> ParameterItems:
    if type(value) is not dict or len(value) > _MAX_PARAMETERS:
        raise RequestUniverseCandidateContractError(
            "parameters must be an exact bounded dictionary"
        )
    return _parameter_items(
        tuple(
            sorted(
                (
                    _require_safe_id(name, field_name="parameter name"),
                    _freeze_parameter_value(raw, field_name=f"parameter {name}"),
                )
                for name, raw in value.items()
            )
        )
    )


def _parameter_payload(items: ParameterItems) -> list[dict[str, object]]:
    return [
        {
            "name": name,
            "value": list(value) if type(value) is tuple else value,
        }
        for name, value in items
    ]


def _parameter_items_from_payload(value: object) -> ParameterItems:
    raw_items = _list(value, field_name="parameter_items")
    items: list[tuple[str, FrozenParameterValue]] = []
    for raw in raw_items:
        item = _mapping(raw, field_name="parameter item")
        _require_exact_keys(
            item,
            expected=frozenset({"name", "value"}),
            label="parameter item",
        )
        raw_value = item["value"]
        if type(raw_value) is list:
            raw_value = tuple(cast("list[object]", raw_value))
        items.append(
            (
                _require_safe_id(item["name"], field_name="parameter name"),
                _freeze_parameter_value(raw_value, field_name="parameter value"),
            )
        )
    return _parameter_items(tuple(items))


def _nested_path(value: object) -> tuple[NestedPathSegment, ...]:
    segments = _require_exact_tuple(value, field_name="nested_path")
    if len(segments) > _MAX_PATH_SEGMENTS:
        raise RequestUniverseCandidateContractError("nested_path exceeds the bound")
    normalized: list[NestedPathSegment] = []
    for segment in segments:
        if type(segment) is int:
            normalized.append(_require_nonnegative_int(segment, field_name="nested_path index"))
        else:
            normalized.append(_require_text(segment, field_name="nested_path segment"))
    return tuple(normalized)


def _nested_path_from_payload(value: object) -> tuple[NestedPathSegment, ...]:
    return _nested_path(tuple(_list(value, field_name="nested_path")))


def _typed_period_value(kind: TemporalScopeKind, value: object) -> str | int:
    if kind is TemporalScopeKind.SEASON:
        text = _require_text(value, field_name="season value")
        match = _SEASON_RE.fullmatch(text)
        if match is None or int(match.group(2)) != (int(match.group(1)) + 1) % 100:
            raise RequestUniverseCandidateContractError(
                "season value must use exact consecutive YYYY-YY form"
            )
        return text
    if kind is TemporalScopeKind.GAME_DATE:
        text = _require_text(value, field_name="game_date value")
        match = _DATE_RE.fullmatch(text)
        if match is None:
            raise RequestUniverseCandidateContractError(
                "game_date value must use exact YYYY-MM-DD form"
            )
        year, month, day = (int(part) for part in match.groups())
        try:
            __import__("datetime").date(year, month, day)
        except ValueError as exc:
            raise RequestUniverseCandidateContractError(
                "game_date value is not a calendar date"
            ) from exc
        return text
    if kind is TemporalScopeKind.GAME_ID:
        text = _require_text(value, field_name="game_id value")
        if _GAME_ID_RE.fullmatch(text) is None:
            raise RequestUniverseCandidateContractError(
                "game_id value must be an exact ten-digit string"
            )
        return text
    if kind is TemporalScopeKind.CALENDAR_YEAR:
        if type(value) is not int or value < 1946 or value > 9999:
            raise RequestUniverseCandidateContractError(
                "calendar_year value must be an exact bounded integer"
            )
        return value
    text = _require_text(value, field_name=f"{kind.value} value")
    if len(text) > 256:
        raise RequestUniverseCandidateContractError(f"{kind.value} value exceeds the bound")
    return text


def _parse_schema(payload: Mapping[str, object], *, kind: str, label: str) -> None:
    if (
        type(payload.get("schema_version")) is not int
        or payload.get("schema_version") != REQUEST_UNIVERSE_CANDIDATE_SCHEMA_VERSION
        or payload.get("kind") != kind
    ):
        raise RequestUniverseCandidateContractError(f"{label} schema identity is invalid")


def _decode_canonical_mapping(encoded: bytes) -> Mapping[str, object]:
    if type(encoded) is not bytes or not encoded or len(encoded) > _MAX_CANONICAL_BYTES:
        raise RequestUniverseCandidateContractError("candidate canonical byte length is invalid")

    def reject_duplicates(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for key, value in pairs:
            if key in result:
                raise RequestUniverseCandidateContractError(
                    "candidate canonical JSON contains duplicate keys"
                )
            result[key] = value
        return result

    try:
        decoded = json.loads(
            encoded.decode("utf-8", errors="strict"),
            object_pairs_hook=reject_duplicates,
            parse_constant=lambda _value: (_ for _ in ()).throw(
                RequestUniverseCandidateContractError(
                    "candidate canonical JSON contains a non-finite number"
                )
            ),
        )
    except RequestUniverseCandidateContractError:
        raise
    except (UnicodeDecodeError, json.JSONDecodeError, RecursionError) as exc:
        raise RequestUniverseCandidateContractError(
            "candidate canonical input is not valid JSON"
        ) from exc
    payload = _mapping(decoded, field_name="candidate canonical root")
    if canonical_request_universe_json_bytes(payload) != encoded:
        raise RequestUniverseCandidateContractError("candidate input is not exact canonical JSON")
    return payload


def _cume_aliases_for_entity(entity_kind: object) -> tuple[str, ...]:
    if type(entity_kind) is not str:
        raise RequestUniverseCandidateContractError("cume entity_kind must be player or team")
    if entity_kind == "player":
        return _CUME_PLAYER_ALIASES
    if entity_kind == "team":
        return _CUME_TEAM_ALIASES
    raise RequestUniverseCandidateContractError("cume entity_kind must be player or team")


def _validate_cume_workload_binding(
    *,
    entity_kind: object,
    workload_content_sha256: object,
    workload_canonical_json: object,
) -> tuple[Literal["player", "team"], str, str]:
    _cume_aliases_for_entity(entity_kind)
    content_sha256 = _require_sha256(
        workload_content_sha256,
        field_name="workload_content_sha256",
    )
    if type(workload_canonical_json) is not str:
        raise RequestUniverseCandidateContractError(
            "cume workload authority must be exact canonical JSON text"
        )
    encoded = workload_canonical_json.encode("utf-8")
    if not encoded or len(encoded) > _MAX_CUME_WORKLOAD_BYTES:
        raise RequestUniverseCandidateContractError(
            "cume workload authority has an invalid bounded byte length"
        )
    payload = _decode_canonical_mapping(encoded)
    _require_exact_keys(
        payload,
        expected=_CUME_WORKLOAD_FIELDS,
        label="cume workload authority",
    )
    if (
        type(payload["schema_version"]) is not int
        or payload["schema_version"] != 1
        or payload["kind"] != "nbadb_cume_workload"
    ):
        raise RequestUniverseCandidateContractError(
            "cume workload authority schema identity is invalid"
        )
    if payload["entity_kind"] != entity_kind:
        raise RequestUniverseCandidateContractError(
            "cume workload content cannot be rebound to another entity kind"
        )
    entity_id = payload["entity_id"]
    if type(entity_id) is not int or entity_id <= 0:
        raise RequestUniverseCandidateContractError(
            "cume workload entity_id must be a positive integer"
        )
    _typed_period_value(TemporalScopeKind.SEASON, payload["season"])
    if type(payload["season_type"]) is not str or payload["season_type"] not in _CUME_SEASON_TYPES:
        raise RequestUniverseCandidateContractError("cume workload season_type is invalid")
    game_ids = _list(payload["game_ids"], field_name="cume workload game_ids")
    if any(
        type(game_id) is not str or _GAME_ID_RE.fullmatch(game_id) is None for game_id in game_ids
    ) or len(game_ids) != len(set(cast("list[str]", game_ids))):
        raise RequestUniverseCandidateContractError(
            "cume workload game_ids must be unique exact ten-digit strings"
        )
    disposition = payload["disposition"]
    typed_zero_reason = payload["typed_zero_reason"]
    if disposition == "complete":
        if not game_ids or typed_zero_reason is not None:
            raise RequestUniverseCandidateContractError(
                "complete cume workload authority is inconsistent"
            )
    elif disposition == "typed_zero":
        if (
            game_ids
            or type(typed_zero_reason) is not str
            or _CUME_REASON_RE.fullmatch(typed_zero_reason) is None
        ):
            raise RequestUniverseCandidateContractError(
                "typed-zero cume workload authority is inconsistent"
            )
    else:
        raise RequestUniverseCandidateContractError("cume workload disposition is invalid")
    _require_sha256(
        payload["foundation_receipt_sha256"],
        field_name="cume workload foundation_receipt_sha256",
    )
    _require_sha256(
        payload["provider_authority_sha256"],
        field_name="cume workload provider_authority_sha256",
    )
    if hashlib.sha256(encoded).hexdigest() != content_sha256:
        raise RequestUniverseCandidateContractError(
            "cume workload content digest differs from its canonical authority"
        )
    return (
        cast("Literal['player', 'team']", entity_kind),
        content_sha256,
        workload_canonical_json,
    )


@dataclass(frozen=True, slots=True)
class LogicalRequestCallV1:
    """One physical provider call with complete explicit parameter identity."""

    authority_generation_sha256: str
    physical_call_id: str
    source_family: str
    endpoint_name: str
    canonical_endpoint_name: str
    physical_endpoint_name: str
    parameter_items: ParameterItems
    parameters_complete: Literal[True]
    pagination_kind: Literal["none", "page", "cursor"]
    pagination_value: str | int | None
    dependent_workload_kind: str | None
    dependent_workload_sha256: str | None
    dependent_physical_alias: str | None
    request_scope_sha256: str

    schema_version: ClassVar[int] = REQUEST_UNIVERSE_CANDIDATE_SCHEMA_VERSION
    kind: ClassVar[str] = "logical_request_call_v1"

    def __post_init__(self) -> None:
        _require_sha256(
            self.authority_generation_sha256,
            field_name="authority_generation_sha256",
        )
        for field_name in (
            "source_family",
            "endpoint_name",
            "canonical_endpoint_name",
            "physical_endpoint_name",
        ):
            _require_safe_id(getattr(self, field_name), field_name=field_name)
        parameters = _parameter_items(self.parameter_items)
        if self.parameters_complete is not True:
            raise RequestUniverseCandidateContractError(
                "logical request parameters must be explicitly complete"
            )
        if self.pagination_kind not in {"none", "page", "cursor"}:
            raise RequestUniverseCandidateContractError("pagination_kind is invalid")
        if self.pagination_kind == "none":
            if self.pagination_value is not None:
                raise RequestUniverseCandidateContractError(
                    "non-paginated call cannot carry a pagination value"
                )
        elif type(self.pagination_value) not in {str, int}:
            raise RequestUniverseCandidateContractError(
                "paginated call requires an exact string or integer value"
            )
        elif type(self.pagination_value) is str:
            _require_text(self.pagination_value, field_name="pagination_value")
        elif cast("int", self.pagination_value) < 0:
            raise RequestUniverseCandidateContractError(
                "integer pagination_value must be nonnegative"
            )
        dependent_values = (
            self.dependent_workload_kind,
            self.dependent_workload_sha256,
            self.dependent_physical_alias,
        )
        if any(value is None for value in dependent_values) and any(
            value is not None for value in dependent_values
        ):
            raise RequestUniverseCandidateContractError(
                "dependent workload identity must be wholly present or absent"
            )
        if self.dependent_workload_kind is not None:
            _require_safe_id(
                self.dependent_workload_kind,
                field_name="dependent_workload_kind",
            )
            _require_sha256(
                self.dependent_workload_sha256,
                field_name="dependent_workload_sha256",
            )
            _require_safe_id(
                self.dependent_physical_alias,
                field_name="dependent_physical_alias",
            )
        object.__setattr__(self, "parameter_items", parameters)
        expected_scope = canonical_request_universe_sha256(self._scope_payload())
        if self.request_scope_sha256 != expected_scope:
            raise RequestUniverseCandidateContractError(
                "request_scope_sha256 differs from the complete physical call scope"
            )
        expected_id = f"physical-call-v1:{expected_scope}"
        if self.physical_call_id != expected_id:
            raise RequestUniverseCandidateContractError(
                "physical_call_id differs from the complete physical call scope"
            )

    @classmethod
    def from_parameters(
        cls,
        *,
        authority_generation_sha256: str,
        source_family: str,
        endpoint_name: str,
        canonical_endpoint_name: str,
        physical_endpoint_name: str,
        parameters: Mapping[str, object],
        pagination_kind: Literal["none", "page", "cursor"] = "none",
        pagination_value: str | int | None = None,
        dependent_workload_kind: str | None = None,
        dependent_workload_sha256: str | None = None,
        dependent_physical_alias: str | None = None,
    ) -> LogicalRequestCallV1:
        items = _parameter_items_from_mapping(parameters)
        payload = {
            "schema_version": REQUEST_UNIVERSE_CANDIDATE_SCHEMA_VERSION,
            "kind": cls.kind,
            "authority_generation_sha256": authority_generation_sha256,
            "source_family": source_family,
            "endpoint_name": endpoint_name,
            "canonical_endpoint_name": canonical_endpoint_name,
            "physical_endpoint_name": physical_endpoint_name,
            "parameter_items": _parameter_payload(items),
            "parameters_complete": True,
            "pagination_kind": pagination_kind,
            "pagination_value": pagination_value,
            "dependent_workload_kind": dependent_workload_kind,
            "dependent_workload_sha256": dependent_workload_sha256,
            "dependent_physical_alias": dependent_physical_alias,
        }
        scope = canonical_request_universe_sha256(payload)
        return cls(
            authority_generation_sha256=authority_generation_sha256,
            physical_call_id=f"physical-call-v1:{scope}",
            source_family=source_family,
            endpoint_name=endpoint_name,
            canonical_endpoint_name=canonical_endpoint_name,
            physical_endpoint_name=physical_endpoint_name,
            parameter_items=items,
            parameters_complete=True,
            pagination_kind=pagination_kind,
            pagination_value=pagination_value,
            dependent_workload_kind=dependent_workload_kind,
            dependent_workload_sha256=dependent_workload_sha256,
            dependent_physical_alias=dependent_physical_alias,
            request_scope_sha256=scope,
        )

    def _scope_payload(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "kind": self.kind,
            "authority_generation_sha256": self.authority_generation_sha256,
            "source_family": self.source_family,
            "endpoint_name": self.endpoint_name,
            "canonical_endpoint_name": self.canonical_endpoint_name,
            "physical_endpoint_name": self.physical_endpoint_name,
            "parameter_items": _parameter_payload(self.parameter_items),
            "parameters_complete": self.parameters_complete,
            "pagination_kind": self.pagination_kind,
            "pagination_value": self.pagination_value,
            "dependent_workload_kind": self.dependent_workload_kind,
            "dependent_workload_sha256": self.dependent_workload_sha256,
            "dependent_physical_alias": self.dependent_physical_alias,
        }

    def to_dict(self) -> dict[str, object]:
        return {
            **self._scope_payload(),
            "physical_call_id": self.physical_call_id,
            "request_scope_sha256": self.request_scope_sha256,
        }

    @classmethod
    def from_dict(cls, payload: Mapping[str, object]) -> Self:
        _require_exact_keys(
            payload,
            expected=frozenset(
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
            ),
            label="logical request call",
        )
        _parse_schema(payload, kind=cls.kind, label="logical request call")
        pagination_kind = payload["pagination_kind"]
        if pagination_kind not in {"none", "page", "cursor"}:
            raise RequestUniverseCandidateContractError("pagination_kind is invalid")
        for optional in (
            "dependent_workload_kind",
            "dependent_workload_sha256",
            "dependent_physical_alias",
        ):
            if payload[optional] is not None and type(payload[optional]) is not str:
                raise RequestUniverseCandidateContractError(f"{optional} must be a string or null")
        pagination_value = payload["pagination_value"]
        if pagination_value is not None and type(pagination_value) not in {str, int}:
            raise RequestUniverseCandidateContractError(
                "pagination_value must be a string, integer, or null"
            )
        return cls(
            authority_generation_sha256=cast("str", payload["authority_generation_sha256"]),
            physical_call_id=cast("str", payload["physical_call_id"]),
            source_family=cast("str", payload["source_family"]),
            endpoint_name=cast("str", payload["endpoint_name"]),
            canonical_endpoint_name=cast("str", payload["canonical_endpoint_name"]),
            physical_endpoint_name=cast("str", payload["physical_endpoint_name"]),
            parameter_items=_parameter_items_from_payload(payload["parameter_items"]),
            parameters_complete=cast("Literal[True]", payload["parameters_complete"]),
            pagination_kind=cast("Literal['none', 'page', 'cursor']", pagination_kind),
            pagination_value=cast("str | int | None", pagination_value),
            dependent_workload_kind=cast("str | None", payload["dependent_workload_kind"]),
            dependent_workload_sha256=cast("str | None", payload["dependent_workload_sha256"]),
            dependent_physical_alias=cast("str | None", payload["dependent_physical_alias"]),
            request_scope_sha256=cast("str", payload["request_scope_sha256"]),
        )


@dataclass(frozen=True, slots=True)
class RouteRequestMemberV1:
    """One exact physical route/result/nested-path member of a call."""

    authority_generation_sha256: str
    route_request_member_id: str
    physical_call_id: str
    request_scope_sha256: str
    route_id: str
    endpoint_name: str
    result_name: str
    result_ordinal: int
    nested_path: tuple[NestedPathSegment, ...]

    schema_version: ClassVar[int] = REQUEST_UNIVERSE_CANDIDATE_SCHEMA_VERSION
    kind: ClassVar[str] = "route_request_member_v1"

    def __post_init__(self) -> None:
        _require_sha256(
            self.authority_generation_sha256,
            field_name="authority_generation_sha256",
        )
        _require_safe_id(self.physical_call_id, field_name="physical_call_id")
        _require_sha256(self.request_scope_sha256, field_name="request_scope_sha256")
        _require_safe_id(self.route_id, field_name="route_id")
        _require_safe_id(self.endpoint_name, field_name="endpoint_name")
        _require_text(self.result_name, field_name="result_name")
        _require_nonnegative_int(self.result_ordinal, field_name="result_ordinal")
        path = _nested_path(self.nested_path)
        object.__setattr__(self, "nested_path", path)
        expected = f"route-member-v1:{canonical_request_universe_sha256(self._identity_payload())}"
        if self.route_request_member_id != expected:
            raise RequestUniverseCandidateContractError(
                "route_request_member_id differs from its physical route identity"
            )

    @classmethod
    def build(
        cls,
        *,
        call: LogicalRequestCallV1,
        route_id: str,
        result_name: str,
        result_ordinal: int,
        nested_path: tuple[NestedPathSegment, ...] = (),
    ) -> RouteRequestMemberV1:
        payload = {
            "schema_version": REQUEST_UNIVERSE_CANDIDATE_SCHEMA_VERSION,
            "kind": cls.kind,
            "authority_generation_sha256": call.authority_generation_sha256,
            "physical_call_id": call.physical_call_id,
            "request_scope_sha256": call.request_scope_sha256,
            "route_id": route_id,
            "endpoint_name": call.endpoint_name,
            "result_name": result_name,
            "result_ordinal": result_ordinal,
            "nested_path": list(_nested_path(nested_path)),
        }
        member_id = f"route-member-v1:{canonical_request_universe_sha256(payload)}"
        return cls(
            authority_generation_sha256=call.authority_generation_sha256,
            route_request_member_id=member_id,
            physical_call_id=call.physical_call_id,
            request_scope_sha256=call.request_scope_sha256,
            route_id=route_id,
            endpoint_name=call.endpoint_name,
            result_name=result_name,
            result_ordinal=result_ordinal,
            nested_path=nested_path,
        )

    def _identity_payload(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "kind": self.kind,
            "authority_generation_sha256": self.authority_generation_sha256,
            "physical_call_id": self.physical_call_id,
            "request_scope_sha256": self.request_scope_sha256,
            "route_id": self.route_id,
            "endpoint_name": self.endpoint_name,
            "result_name": self.result_name,
            "result_ordinal": self.result_ordinal,
            "nested_path": list(self.nested_path),
        }

    def to_dict(self) -> dict[str, object]:
        return {**self._identity_payload(), "route_request_member_id": self.route_request_member_id}

    @classmethod
    def from_dict(cls, payload: Mapping[str, object]) -> Self:
        _require_exact_keys(
            payload,
            expected=frozenset(
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
            ),
            label="route request member",
        )
        _parse_schema(payload, kind=cls.kind, label="route request member")
        return cls(
            authority_generation_sha256=cast("str", payload["authority_generation_sha256"]),
            route_request_member_id=cast("str", payload["route_request_member_id"]),
            physical_call_id=cast("str", payload["physical_call_id"]),
            request_scope_sha256=cast("str", payload["request_scope_sha256"]),
            route_id=cast("str", payload["route_id"]),
            endpoint_name=cast("str", payload["endpoint_name"]),
            result_name=cast("str", payload["result_name"]),
            result_ordinal=cast("int", payload["result_ordinal"]),
            nested_path=_nested_path_from_payload(payload["nested_path"]),
        )


@dataclass(frozen=True, slots=True)
class FieldOccurrenceInputV1:
    """Minimal frozen projection of one current route-local field fate."""

    authority_generation_sha256: str
    occurrence_id: str
    route_id: str
    endpoint_name: str
    result_name: str
    result_ordinal: int
    nested_path: tuple[NestedPathSegment, ...]
    provider_field: str
    field_occurrence_ordinal: int
    field_fate_contract_sha256: str

    def __post_init__(self) -> None:
        _require_sha256(
            self.authority_generation_sha256,
            field_name="authority_generation_sha256",
        )
        _require_safe_id(self.occurrence_id, field_name="occurrence_id")
        _require_safe_id(self.route_id, field_name="route_id")
        _require_safe_id(self.endpoint_name, field_name="endpoint_name")
        _require_text(self.result_name, field_name="result_name")
        _require_nonnegative_int(self.result_ordinal, field_name="result_ordinal")
        object.__setattr__(self, "nested_path", _nested_path(self.nested_path))
        _require_text(self.provider_field, field_name="provider_field")
        _require_nonnegative_int(
            self.field_occurrence_ordinal,
            field_name="field_occurrence_ordinal",
        )
        _require_sha256(
            self.field_fate_contract_sha256,
            field_name="field_fate_contract_sha256",
        )

    @classmethod
    def from_current_contract(
        cls,
        *,
        authority_generation_sha256: str,
        field_fate_contract_sha256: str,
        field_fate: ProviderFieldFateContract,
    ) -> FieldOccurrenceInputV1:
        """Project only literal occurrence identity from the current field API."""

        provider_field = field_fate.provider_column
        nested_path: tuple[NestedPathSegment, ...] = ()
        if field_fate.provider_field_kind == "nested_projection":
            parts = tuple(provider_field.split("."))
            if len(parts) < 2 or any(not part for part in parts):
                raise RequestUniverseCandidateContractError(
                    "nested projection lacks an explicit provider path"
                )
            nested_path = parts[:-1]
            provider_field = parts[-1]
        return cls(
            authority_generation_sha256=authority_generation_sha256,
            occurrence_id=field_fate.occurrence_id,
            route_id=field_fate.route_id,
            endpoint_name=field_fate.endpoint_name,
            result_name=field_fate.provider_result_set_name,
            result_ordinal=field_fate.provider_result_set_ordinal,
            nested_path=nested_path,
            provider_field=provider_field,
            field_occurrence_ordinal=field_fate.route_field_ordinal,
            field_fate_contract_sha256=field_fate_contract_sha256,
        )

    @property
    def identity_sha256(self) -> str:
        return canonical_request_universe_sha256(self.to_dict())

    def to_dict(self) -> dict[str, object]:
        return {
            "authority_generation_sha256": self.authority_generation_sha256,
            "occurrence_id": self.occurrence_id,
            "route_id": self.route_id,
            "endpoint_name": self.endpoint_name,
            "result_name": self.result_name,
            "result_ordinal": self.result_ordinal,
            "nested_path": list(self.nested_path),
            "provider_field": self.provider_field,
            "field_occurrence_ordinal": self.field_occurrence_ordinal,
            "field_fate_contract_sha256": self.field_fate_contract_sha256,
        }

    @classmethod
    def from_dict(cls, payload: Mapping[str, object]) -> Self:
        _require_exact_keys(
            payload,
            expected=frozenset(
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
            ),
            label="field occurrence input",
        )
        return cls(
            authority_generation_sha256=cast("str", payload["authority_generation_sha256"]),
            occurrence_id=cast("str", payload["occurrence_id"]),
            route_id=cast("str", payload["route_id"]),
            endpoint_name=cast("str", payload["endpoint_name"]),
            result_name=cast("str", payload["result_name"]),
            result_ordinal=cast("int", payload["result_ordinal"]),
            nested_path=_nested_path_from_payload(payload["nested_path"]),
            provider_field=cast("str", payload["provider_field"]),
            field_occurrence_ordinal=cast("int", payload["field_occurrence_ordinal"]),
            field_fate_contract_sha256=cast("str", payload["field_fate_contract_sha256"]),
        )


@dataclass(frozen=True, slots=True)
class ExplicitTemporalScopeValueV1:
    """One caller-supplied typed period; nothing is inferred from planner policy."""

    authority_generation_sha256: str
    physical_call_id: str
    route_request_member_id: str
    route_id: str
    endpoint_name: str
    request_scope_sha256: str
    temporal_contract_sha256: str
    temporal_scope_kind: TemporalScopeKind
    temporal_scope_value: str | int

    def __post_init__(self) -> None:
        _require_sha256(
            self.authority_generation_sha256,
            field_name="authority_generation_sha256",
        )
        _require_safe_id(self.physical_call_id, field_name="physical_call_id")
        _require_safe_id(
            self.route_request_member_id,
            field_name="route_request_member_id",
        )
        _require_safe_id(self.route_id, field_name="route_id")
        _require_safe_id(self.endpoint_name, field_name="endpoint_name")
        _require_sha256(self.request_scope_sha256, field_name="request_scope_sha256")
        _require_sha256(
            self.temporal_contract_sha256,
            field_name="temporal_contract_sha256",
        )
        try:
            kind = TemporalScopeKind(self.temporal_scope_kind)
        except ValueError as exc:
            raise RequestUniverseCandidateContractError("temporal_scope_kind is invalid") from exc
        value = _typed_period_value(kind, self.temporal_scope_value)
        object.__setattr__(self, "temporal_scope_kind", kind)
        object.__setattr__(self, "temporal_scope_value", value)

    @classmethod
    def from_current_contract(
        cls,
        *,
        authority_generation_sha256: str,
        temporal_contract_sha256: str,
        route_member: RouteRequestMemberV1,
        route_scope: RouteTemporalScope,
        temporal_scope_kind: TemporalScopeKind,
        temporal_scope_value: str | int,
    ) -> ExplicitTemporalScopeValueV1:
        """Bind an explicit value to the current route API without inferring one."""

        if (
            route_member.route_id != route_scope.route_id
            or route_member.endpoint_name != route_scope.endpoint_name
            or route_member.result_name != route_scope.provider_result_set_name
            or route_member.result_ordinal != route_scope.provider_result_set_ordinal
        ):
            raise RequestUniverseCandidateContractError(
                "route temporal scope differs from its physical route member"
            )
        return cls(
            authority_generation_sha256=authority_generation_sha256,
            physical_call_id=route_member.physical_call_id,
            route_request_member_id=route_member.route_request_member_id,
            route_id=route_member.route_id,
            endpoint_name=route_member.endpoint_name,
            request_scope_sha256=route_member.request_scope_sha256,
            temporal_contract_sha256=temporal_contract_sha256,
            temporal_scope_kind=temporal_scope_kind,
            temporal_scope_value=temporal_scope_value,
        )

    @property
    def identity_sha256(self) -> str:
        return canonical_request_universe_sha256(self.to_dict())

    def to_dict(self) -> dict[str, object]:
        return {
            "authority_generation_sha256": self.authority_generation_sha256,
            "physical_call_id": self.physical_call_id,
            "route_request_member_id": self.route_request_member_id,
            "route_id": self.route_id,
            "endpoint_name": self.endpoint_name,
            "request_scope_sha256": self.request_scope_sha256,
            "temporal_contract_sha256": self.temporal_contract_sha256,
            "temporal_scope_kind": self.temporal_scope_kind.value,
            "temporal_scope_value": self.temporal_scope_value,
        }

    @classmethod
    def from_dict(cls, payload: Mapping[str, object]) -> Self:
        _require_exact_keys(
            payload,
            expected=frozenset(
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
            ),
            label="explicit temporal scope",
        )
        try:
            scope_kind = TemporalScopeKind(payload["temporal_scope_kind"])
        except (TypeError, ValueError) as exc:
            raise RequestUniverseCandidateContractError("temporal_scope_kind is invalid") from exc
        return cls(
            authority_generation_sha256=cast("str", payload["authority_generation_sha256"]),
            physical_call_id=cast("str", payload["physical_call_id"]),
            route_request_member_id=cast("str", payload["route_request_member_id"]),
            route_id=cast("str", payload["route_id"]),
            endpoint_name=cast("str", payload["endpoint_name"]),
            request_scope_sha256=cast("str", payload["request_scope_sha256"]),
            temporal_contract_sha256=cast("str", payload["temporal_contract_sha256"]),
            temporal_scope_kind=scope_kind,
            temporal_scope_value=cast("str | int", payload["temporal_scope_value"]),
        )


@dataclass(frozen=True, slots=True)
class UnintegratedCumeValueV1:
    """Identity of one cume value intentionally barred from request units."""

    authority_generation_sha256: str
    entity_kind: Literal["player", "team"]
    workload_content_sha256: str
    workload_canonical_json: str
    physical_endpoint_aliases: tuple[str, ...]

    def __post_init__(self) -> None:
        _require_sha256(
            self.authority_generation_sha256,
            field_name="authority_generation_sha256",
        )
        entity_kind, content_sha256, canonical_json = _validate_cume_workload_binding(
            entity_kind=self.entity_kind,
            workload_content_sha256=self.workload_content_sha256,
            workload_canonical_json=self.workload_canonical_json,
        )
        expected_aliases = _cume_aliases_for_entity(entity_kind)
        aliases = _require_sorted_unique(
            self.physical_endpoint_aliases,
            field_name="physical_endpoint_aliases",
            key=lambda item: item,
            maximum=16,
            allow_empty=False,
        )
        for alias in aliases:
            _require_safe_id(alias, field_name="physical_endpoint_alias")
        if aliases != expected_aliases:
            raise RequestUniverseCandidateContractError(
                "cume physical endpoint aliases differ from the exact entity-bound set"
            )
        object.__setattr__(self, "entity_kind", entity_kind)
        object.__setattr__(self, "workload_content_sha256", content_sha256)
        object.__setattr__(self, "workload_canonical_json", canonical_json)
        object.__setattr__(self, "physical_endpoint_aliases", aliases)

    @classmethod
    def from_current_contract(
        cls,
        *,
        authority_generation_sha256: str,
        workload: CumeWorkloadValue,
    ) -> UnintegratedCumeValueV1:
        entity = workload.entity_kind.value
        aliases = _cume_aliases_for_entity(entity)
        return cls(
            authority_generation_sha256=authority_generation_sha256,
            entity_kind=entity,
            workload_content_sha256=workload.content_sha256,
            workload_canonical_json=workload.canonical_bytes.decode("utf-8", errors="strict"),
            physical_endpoint_aliases=aliases,
        )

    @property
    def identity_sha256(self) -> str:
        return canonical_request_universe_sha256(self.to_dict())

    def to_dict(self) -> dict[str, object]:
        return {
            "authority_generation_sha256": self.authority_generation_sha256,
            "entity_kind": self.entity_kind,
            "workload_content_sha256": self.workload_content_sha256,
            "workload_canonical_json": self.workload_canonical_json,
            "physical_endpoint_aliases": list(self.physical_endpoint_aliases),
        }

    @classmethod
    def from_dict(cls, payload: Mapping[str, object]) -> Self:
        _require_exact_keys(
            payload,
            expected=frozenset(
                {
                    "authority_generation_sha256",
                    "entity_kind",
                    "workload_content_sha256",
                    "workload_canonical_json",
                    "physical_endpoint_aliases",
                }
            ),
            label="unintegrated cume value",
        )
        return cls(
            authority_generation_sha256=cast("str", payload["authority_generation_sha256"]),
            entity_kind=cast("Literal['player', 'team']", payload["entity_kind"]),
            workload_content_sha256=cast("str", payload["workload_content_sha256"]),
            workload_canonical_json=cast("str", payload["workload_canonical_json"]),
            physical_endpoint_aliases=tuple(
                cast(
                    "list[str]",
                    _list(
                        payload["physical_endpoint_aliases"],
                        field_name="physical_endpoint_aliases",
                    ),
                )
            ),
        )


@dataclass(frozen=True, slots=True)
class FieldPeriodDenominatorCellV1:
    """One route-local provider-field occurrence at one explicit period."""

    authority_generation_sha256: str
    cell_id: str
    physical_call_id: str
    route_request_member_id: str
    route_id: str
    endpoint_name: str
    result_name: str
    result_ordinal: int
    nested_path: tuple[NestedPathSegment, ...]
    provider_field: str
    field_occurrence_ordinal: int
    request_scope_sha256: str
    field_fate_contract_sha256: str
    temporal_contract_sha256: str
    temporal_scope_kind: TemporalScopeKind
    temporal_scope_value: str | int
    state: Literal["evidence_insufficient"] = "evidence_insufficient"

    schema_version: ClassVar[int] = REQUEST_UNIVERSE_CANDIDATE_SCHEMA_VERSION
    kind: ClassVar[str] = "field_period_denominator_cell_v1"

    def __post_init__(self) -> None:
        _require_sha256(
            self.authority_generation_sha256,
            field_name="authority_generation_sha256",
        )
        _require_safe_id(self.physical_call_id, field_name="physical_call_id")
        _require_safe_id(
            self.route_request_member_id,
            field_name="route_request_member_id",
        )
        _require_safe_id(self.route_id, field_name="route_id")
        _require_safe_id(self.endpoint_name, field_name="endpoint_name")
        _require_text(self.result_name, field_name="result_name")
        _require_nonnegative_int(self.result_ordinal, field_name="result_ordinal")
        object.__setattr__(self, "nested_path", _nested_path(self.nested_path))
        _require_text(self.provider_field, field_name="provider_field")
        _require_nonnegative_int(
            self.field_occurrence_ordinal,
            field_name="field_occurrence_ordinal",
        )
        _require_sha256(self.request_scope_sha256, field_name="request_scope_sha256")
        _require_sha256(
            self.field_fate_contract_sha256,
            field_name="field_fate_contract_sha256",
        )
        _require_sha256(
            self.temporal_contract_sha256,
            field_name="temporal_contract_sha256",
        )
        try:
            scope_kind = TemporalScopeKind(self.temporal_scope_kind)
        except ValueError as exc:
            raise RequestUniverseCandidateContractError("temporal_scope_kind is invalid") from exc
        value = _typed_period_value(scope_kind, self.temporal_scope_value)
        if self.state != "evidence_insufficient":
            raise RequestUniverseCandidateContractError(
                "candidate field-period state must remain evidence_insufficient"
            )
        object.__setattr__(self, "temporal_scope_kind", scope_kind)
        object.__setattr__(self, "temporal_scope_value", value)
        expected = (
            f"field-period-cell-v1:{canonical_request_universe_sha256(self._identity_payload())}"
        )
        if self.cell_id != expected:
            raise RequestUniverseCandidateContractError(
                "cell_id differs from its field-period identity"
            )

    @classmethod
    def build(
        cls,
        *,
        route_member: RouteRequestMemberV1,
        field_occurrence: FieldOccurrenceInputV1,
        temporal_scope: ExplicitTemporalScopeValueV1,
    ) -> FieldPeriodDenominatorCellV1:
        payload = {
            "schema_version": REQUEST_UNIVERSE_CANDIDATE_SCHEMA_VERSION,
            "kind": cls.kind,
            "authority_generation_sha256": route_member.authority_generation_sha256,
            "physical_call_id": route_member.physical_call_id,
            "route_request_member_id": route_member.route_request_member_id,
            "route_id": route_member.route_id,
            "endpoint_name": route_member.endpoint_name,
            "result_name": route_member.result_name,
            "result_ordinal": route_member.result_ordinal,
            "nested_path": list(route_member.nested_path),
            "provider_field": field_occurrence.provider_field,
            "field_occurrence_ordinal": field_occurrence.field_occurrence_ordinal,
            "request_scope_sha256": route_member.request_scope_sha256,
            "field_fate_contract_sha256": field_occurrence.field_fate_contract_sha256,
            "temporal_contract_sha256": temporal_scope.temporal_contract_sha256,
            "temporal_scope_kind": temporal_scope.temporal_scope_kind.value,
            "temporal_scope_value": temporal_scope.temporal_scope_value,
            "state": "evidence_insufficient",
        }
        cell_id = f"field-period-cell-v1:{canonical_request_universe_sha256(payload)}"
        return cls(
            authority_generation_sha256=route_member.authority_generation_sha256,
            cell_id=cell_id,
            physical_call_id=route_member.physical_call_id,
            route_request_member_id=route_member.route_request_member_id,
            route_id=route_member.route_id,
            endpoint_name=route_member.endpoint_name,
            result_name=route_member.result_name,
            result_ordinal=route_member.result_ordinal,
            nested_path=route_member.nested_path,
            provider_field=field_occurrence.provider_field,
            field_occurrence_ordinal=field_occurrence.field_occurrence_ordinal,
            request_scope_sha256=route_member.request_scope_sha256,
            field_fate_contract_sha256=field_occurrence.field_fate_contract_sha256,
            temporal_contract_sha256=temporal_scope.temporal_contract_sha256,
            temporal_scope_kind=temporal_scope.temporal_scope_kind,
            temporal_scope_value=temporal_scope.temporal_scope_value,
        )

    def _identity_payload(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "kind": self.kind,
            "authority_generation_sha256": self.authority_generation_sha256,
            "physical_call_id": self.physical_call_id,
            "route_request_member_id": self.route_request_member_id,
            "route_id": self.route_id,
            "endpoint_name": self.endpoint_name,
            "result_name": self.result_name,
            "result_ordinal": self.result_ordinal,
            "nested_path": list(self.nested_path),
            "provider_field": self.provider_field,
            "field_occurrence_ordinal": self.field_occurrence_ordinal,
            "request_scope_sha256": self.request_scope_sha256,
            "field_fate_contract_sha256": self.field_fate_contract_sha256,
            "temporal_contract_sha256": self.temporal_contract_sha256,
            "temporal_scope_kind": self.temporal_scope_kind.value,
            "temporal_scope_value": self.temporal_scope_value,
            "state": self.state,
        }

    def to_dict(self) -> dict[str, object]:
        return {**self._identity_payload(), "cell_id": self.cell_id}

    @classmethod
    def from_dict(cls, payload: Mapping[str, object]) -> Self:
        expected = frozenset(
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
        _require_exact_keys(payload, expected=expected, label="field-period cell")
        _parse_schema(payload, kind=cls.kind, label="field-period cell")
        try:
            scope_kind = TemporalScopeKind(payload["temporal_scope_kind"])
        except (TypeError, ValueError) as exc:
            raise RequestUniverseCandidateContractError("temporal_scope_kind is invalid") from exc
        return cls(
            authority_generation_sha256=cast("str", payload["authority_generation_sha256"]),
            cell_id=cast("str", payload["cell_id"]),
            physical_call_id=cast("str", payload["physical_call_id"]),
            route_request_member_id=cast("str", payload["route_request_member_id"]),
            route_id=cast("str", payload["route_id"]),
            endpoint_name=cast("str", payload["endpoint_name"]),
            result_name=cast("str", payload["result_name"]),
            result_ordinal=cast("int", payload["result_ordinal"]),
            nested_path=_nested_path_from_payload(payload["nested_path"]),
            provider_field=cast("str", payload["provider_field"]),
            field_occurrence_ordinal=cast("int", payload["field_occurrence_ordinal"]),
            request_scope_sha256=cast("str", payload["request_scope_sha256"]),
            field_fate_contract_sha256=cast("str", payload["field_fate_contract_sha256"]),
            temporal_contract_sha256=cast("str", payload["temporal_contract_sha256"]),
            temporal_scope_kind=scope_kind,
            temporal_scope_value=cast("str | int", payload["temporal_scope_value"]),
            state=cast("Literal['evidence_insufficient']", payload["state"]),
        )


@dataclass(frozen=True, slots=True)
class CandidateBlockerV1:
    """One explicit reason this candidate cannot become a final universe."""

    authority_generation_sha256: str
    blocker_code: str
    subject_id: str
    evidence_sha256: str

    def __post_init__(self) -> None:
        _require_sha256(
            self.authority_generation_sha256,
            field_name="authority_generation_sha256",
        )
        _require_safe_id(self.blocker_code, field_name="blocker_code")
        _require_safe_id(self.subject_id, field_name="subject_id")
        _require_sha256(self.evidence_sha256, field_name="evidence_sha256")

    @property
    def identity_sha256(self) -> str:
        return canonical_request_universe_sha256(self.to_dict())

    def to_dict(self) -> dict[str, object]:
        return {
            "authority_generation_sha256": self.authority_generation_sha256,
            "blocker_code": self.blocker_code,
            "subject_id": self.subject_id,
            "evidence_sha256": self.evidence_sha256,
        }

    @classmethod
    def from_dict(cls, payload: Mapping[str, object]) -> Self:
        _require_exact_keys(
            payload,
            expected=frozenset(
                {
                    "authority_generation_sha256",
                    "blocker_code",
                    "subject_id",
                    "evidence_sha256",
                }
            ),
            label="candidate blocker",
        )
        return cls(
            authority_generation_sha256=cast("str", payload["authority_generation_sha256"]),
            blocker_code=cast("str", payload["blocker_code"]),
            subject_id=cast("str", payload["subject_id"]),
            evidence_sha256=cast("str", payload["evidence_sha256"]),
        )


@dataclass(frozen=True, slots=True)
class RequestUniverseCandidateSourceV1:
    """All frozen literal inputs consumed by both candidate compilers."""

    authority_generation_sha256: str
    field_fate_contract_sha256: str
    temporal_contract_sha256: str
    logical_calls: tuple[LogicalRequestCallV1, ...]
    route_members: tuple[RouteRequestMemberV1, ...]
    field_occurrences: tuple[FieldOccurrenceInputV1, ...]
    explicit_temporal_scopes: tuple[ExplicitTemporalScopeValueV1, ...]
    unintegrated_cume_values: tuple[UnintegratedCumeValueV1, ...] = field(default_factory=tuple)

    schema_version: ClassVar[int] = REQUEST_UNIVERSE_CANDIDATE_SCHEMA_VERSION
    kind: ClassVar[str] = "request_universe_candidate_source_v1"

    def __post_init__(self) -> None:
        authority = _require_sha256(
            self.authority_generation_sha256,
            field_name="authority_generation_sha256",
        )
        field_digest = _require_sha256(
            self.field_fate_contract_sha256,
            field_name="field_fate_contract_sha256",
        )
        temporal_digest = _require_sha256(
            self.temporal_contract_sha256,
            field_name="temporal_contract_sha256",
        )
        calls = _require_sorted_unique(
            self.logical_calls,
            field_name="logical_calls",
            key=lambda item: item.physical_call_id,
            maximum=_MAX_CALLS,
            allow_empty=False,
        )
        routes = _require_sorted_unique(
            self.route_members,
            field_name="route_members",
            key=lambda item: item.route_request_member_id,
            maximum=_MAX_ROUTE_MEMBERS,
            allow_empty=False,
        )
        fields = _require_sorted_unique(
            self.field_occurrences,
            field_name="field_occurrences",
            key=lambda item: item.identity_sha256,
            maximum=_MAX_FIELD_OCCURRENCES,
        )
        periods = _require_sorted_unique(
            self.explicit_temporal_scopes,
            field_name="explicit_temporal_scopes",
            key=lambda item: item.identity_sha256,
            maximum=_MAX_TEMPORAL_SCOPES,
        )
        cume_values = _require_sorted_unique(
            self.unintegrated_cume_values,
            field_name="unintegrated_cume_values",
            key=lambda item: item.identity_sha256,
            maximum=_MAX_CALLS,
        )
        all_items = (*calls, *routes, *fields, *periods, *cume_values)
        if any(item.authority_generation_sha256 != authority for item in all_items):
            raise RequestUniverseCandidateContractError(
                "mixed-authority candidate generations are forbidden"
            )
        if any(item.field_fate_contract_sha256 != field_digest for item in fields):
            raise RequestUniverseCandidateContractError(
                "field occurrence uses a mixed field-fate authority"
            )
        if any(item.temporal_contract_sha256 != temporal_digest for item in periods):
            raise RequestUniverseCandidateContractError(
                "temporal scope uses a mixed temporal authority"
            )
        call_by_id = {item.physical_call_id: item for item in calls}
        route_by_id = {item.route_request_member_id: item for item in routes}
        for route in routes:
            call = call_by_id.get(route.physical_call_id)
            if call is None or (
                route.authority_generation_sha256,
                route.request_scope_sha256,
                route.endpoint_name,
            ) != (
                call.authority_generation_sha256,
                call.request_scope_sha256,
                call.endpoint_name,
            ):
                raise RequestUniverseCandidateContractError(
                    "route member differs from its exact physical call"
                )
        route_shapes = {
            (
                item.route_id,
                item.endpoint_name,
                item.result_name,
                item.result_ordinal,
                item.nested_path,
            )
            for item in routes
        }
        field_shapes = {
            (
                item.route_id,
                item.endpoint_name,
                item.result_name,
                item.result_ordinal,
                item.nested_path,
            )
            for item in fields
        }
        if not field_shapes <= route_shapes:
            raise RequestUniverseCandidateContractError(
                "field occurrence lacks an exact route/result/path member"
            )
        for period in periods:
            route = route_by_id.get(period.route_request_member_id)
            if route is None or (
                period.physical_call_id,
                period.route_id,
                period.endpoint_name,
                period.request_scope_sha256,
            ) != (
                route.physical_call_id,
                route.route_id,
                route.endpoint_name,
                route.request_scope_sha256,
            ):
                raise RequestUniverseCandidateContractError(
                    "explicit temporal scope differs from its route member"
                )
        prohibited_aliases = {
            alias for value in cume_values for alias in value.physical_endpoint_aliases
        }
        if any(
            {
                call.endpoint_name,
                call.canonical_endpoint_name,
                call.physical_endpoint_name,
            }
            & prohibited_aliases
            for call in calls
        ):
            raise RequestUniverseCandidateContractError(
                "unintegrated cume values cannot become request units"
            )
        object.__setattr__(self, "logical_calls", calls)
        object.__setattr__(self, "route_members", routes)
        object.__setattr__(self, "field_occurrences", fields)
        object.__setattr__(self, "explicit_temporal_scopes", periods)
        object.__setattr__(self, "unintegrated_cume_values", cume_values)

    @property
    def source_inputs_sha256(self) -> str:
        return canonical_request_universe_sha256(self.to_dict())

    def to_dict(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "kind": self.kind,
            "authority_generation_sha256": self.authority_generation_sha256,
            "field_fate_contract_sha256": self.field_fate_contract_sha256,
            "temporal_contract_sha256": self.temporal_contract_sha256,
            "logical_calls": [item.to_dict() for item in self.logical_calls],
            "route_members": [item.to_dict() for item in self.route_members],
            "field_occurrences": [item.to_dict() for item in self.field_occurrences],
            "explicit_temporal_scopes": [item.to_dict() for item in self.explicit_temporal_scopes],
            "unintegrated_cume_values": [item.to_dict() for item in self.unintegrated_cume_values],
        }

    @classmethod
    def from_dict(cls, payload: Mapping[str, object]) -> Self:
        _require_exact_keys(
            payload,
            expected=frozenset(
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
            ),
            label="candidate source",
        )
        _parse_schema(payload, kind=cls.kind, label="candidate source")
        return cls(
            authority_generation_sha256=cast("str", payload["authority_generation_sha256"]),
            field_fate_contract_sha256=cast("str", payload["field_fate_contract_sha256"]),
            temporal_contract_sha256=cast("str", payload["temporal_contract_sha256"]),
            logical_calls=tuple(
                LogicalRequestCallV1.from_dict(_mapping(item, field_name="logical call"))
                for item in _list(payload["logical_calls"], field_name="logical_calls")
            ),
            route_members=tuple(
                RouteRequestMemberV1.from_dict(_mapping(item, field_name="route member"))
                for item in _list(payload["route_members"], field_name="route_members")
            ),
            field_occurrences=tuple(
                FieldOccurrenceInputV1.from_dict(_mapping(item, field_name="field occurrence"))
                for item in _list(payload["field_occurrences"], field_name="field_occurrences")
            ),
            explicit_temporal_scopes=tuple(
                ExplicitTemporalScopeValueV1.from_dict(
                    _mapping(item, field_name="explicit temporal scope")
                )
                for item in _list(
                    payload["explicit_temporal_scopes"],
                    field_name="explicit_temporal_scopes",
                )
            ),
            unintegrated_cume_values=tuple(
                UnintegratedCumeValueV1.from_dict(
                    _mapping(item, field_name="unintegrated cume value")
                )
                for item in _list(
                    payload["unintegrated_cume_values"],
                    field_name="unintegrated_cume_values",
                )
            ),
        )


@dataclass(frozen=True, slots=True)
class RequestUniverseCandidateGenerationV1:
    """Nonterminal candidate; never a final request universe or release gate."""

    authority_generation_sha256: str
    source_inputs_sha256: str
    field_fate_contract_sha256: str
    temporal_contract_sha256: str
    logical_calls: tuple[LogicalRequestCallV1, ...]
    route_members: tuple[RouteRequestMemberV1, ...]
    field_period_cells: tuple[FieldPeriodDenominatorCellV1, ...]
    blockers: tuple[CandidateBlockerV1, ...]
    logical_call_inventory_sha256: str
    route_member_inventory_sha256: str
    field_period_inventory_sha256: str
    blocker_inventory_sha256: str
    terminal: Literal[False] = False
    release_eligible: Literal[False] = False

    schema_version: ClassVar[int] = REQUEST_UNIVERSE_CANDIDATE_SCHEMA_VERSION
    kind: ClassVar[str] = "request_universe_candidate_generation_v1"

    def __post_init__(self) -> None:
        authority = _require_sha256(
            self.authority_generation_sha256,
            field_name="authority_generation_sha256",
        )
        _require_sha256(self.source_inputs_sha256, field_name="source_inputs_sha256")
        _require_sha256(
            self.field_fate_contract_sha256,
            field_name="field_fate_contract_sha256",
        )
        _require_sha256(
            self.temporal_contract_sha256,
            field_name="temporal_contract_sha256",
        )
        calls = _require_sorted_unique(
            self.logical_calls,
            field_name="logical_calls",
            key=lambda item: item.physical_call_id,
            maximum=_MAX_CALLS,
            allow_empty=False,
        )
        routes = _require_sorted_unique(
            self.route_members,
            field_name="route_members",
            key=lambda item: item.route_request_member_id,
            maximum=_MAX_ROUTE_MEMBERS,
            allow_empty=False,
        )
        cells = _require_sorted_unique(
            self.field_period_cells,
            field_name="field_period_cells",
            key=lambda item: item.cell_id,
            maximum=_MAX_CELLS,
        )
        blockers = _require_sorted_unique(
            self.blockers,
            field_name="blockers",
            key=lambda item: item.identity_sha256,
            maximum=_MAX_ROUTE_MEMBERS,
            allow_empty=False,
        )
        if any(
            item.authority_generation_sha256 != authority
            for item in (*calls, *routes, *cells, *blockers)
        ):
            raise RequestUniverseCandidateContractError(
                "mixed-authority candidate generations are forbidden"
            )
        if any(
            cell.field_fate_contract_sha256 != self.field_fate_contract_sha256 for cell in cells
        ):
            raise RequestUniverseCandidateContractError(
                "candidate cell uses a mixed field-fate authority"
            )
        if any(cell.temporal_contract_sha256 != self.temporal_contract_sha256 for cell in cells):
            raise RequestUniverseCandidateContractError(
                "candidate cell uses a mixed temporal authority"
            )
        call_by_id = {item.physical_call_id: item for item in calls}
        route_by_id = {item.route_request_member_id: item for item in routes}
        for route in routes:
            call = call_by_id.get(route.physical_call_id)
            if call is None or (
                route.request_scope_sha256,
                route.endpoint_name,
            ) != (
                call.request_scope_sha256,
                call.endpoint_name,
            ):
                raise RequestUniverseCandidateContractError(
                    "candidate route differs from its exact physical call"
                )
        for cell in cells:
            route = route_by_id.get(cell.route_request_member_id)
            if route is None or (
                cell.physical_call_id,
                cell.route_id,
                cell.endpoint_name,
                cell.result_name,
                cell.result_ordinal,
                cell.nested_path,
                cell.request_scope_sha256,
            ) != (
                route.physical_call_id,
                route.route_id,
                route.endpoint_name,
                route.result_name,
                route.result_ordinal,
                route.nested_path,
                route.request_scope_sha256,
            ):
                raise RequestUniverseCandidateContractError(
                    "candidate cell differs from its exact route member"
                )
        fixed_point_blocker = CandidateBlockerV1(
            authority_generation_sha256=authority,
            blocker_code="candidate_not_fixed_point",
            subject_id="request_universe_candidate_generation_v1",
            evidence_sha256=self.source_inputs_sha256,
        )
        if fixed_point_blocker.identity_sha256 not in {
            blocker.identity_sha256 for blocker in blockers
        }:
            raise RequestUniverseCandidateContractError(
                "candidate lacks its exact non-fixed-point blocker"
            )
        expected_digests = {
            "logical_call_inventory_sha256": canonical_request_universe_sha256(
                [item.to_dict() for item in calls]
            ),
            "route_member_inventory_sha256": canonical_request_universe_sha256(
                [item.to_dict() for item in routes]
            ),
            "field_period_inventory_sha256": canonical_request_universe_sha256(
                [item.to_dict() for item in cells]
            ),
            "blocker_inventory_sha256": canonical_request_universe_sha256(
                [item.to_dict() for item in blockers]
            ),
        }
        for field_name, expected in expected_digests.items():
            if getattr(self, field_name) != expected:
                raise RequestUniverseCandidateContractError(
                    f"{field_name} differs from its exact inventory"
                )
        if self.terminal is not False or self.release_eligible is not False:
            raise RequestUniverseCandidateContractError(
                "candidate generation cannot be terminal or release eligible"
            )
        if any(cell.state != "evidence_insufficient" for cell in cells):
            raise RequestUniverseCandidateContractError(
                "candidate cells must remain evidence_insufficient"
            )
        object.__setattr__(self, "logical_calls", calls)
        object.__setattr__(self, "route_members", routes)
        object.__setattr__(self, "field_period_cells", cells)
        object.__setattr__(self, "blockers", blockers)

    @property
    def canonical_bytes(self) -> bytes:
        return canonical_request_universe_json_bytes(self.to_dict())

    @property
    def identity_sha256(self) -> str:
        return hashlib.sha256(self.canonical_bytes).hexdigest()

    def to_dict(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "kind": self.kind,
            "authority_generation_sha256": self.authority_generation_sha256,
            "source_inputs_sha256": self.source_inputs_sha256,
            "field_fate_contract_sha256": self.field_fate_contract_sha256,
            "temporal_contract_sha256": self.temporal_contract_sha256,
            "logical_call_count": len(self.logical_calls),
            "route_member_count": len(self.route_members),
            "field_period_cell_count": len(self.field_period_cells),
            "blocker_count": len(self.blockers),
            "logical_call_inventory_sha256": self.logical_call_inventory_sha256,
            "route_member_inventory_sha256": self.route_member_inventory_sha256,
            "field_period_inventory_sha256": self.field_period_inventory_sha256,
            "blocker_inventory_sha256": self.blocker_inventory_sha256,
            "logical_calls": [item.to_dict() for item in self.logical_calls],
            "route_members": [item.to_dict() for item in self.route_members],
            "field_period_cells": [item.to_dict() for item in self.field_period_cells],
            "blockers": [item.to_dict() for item in self.blockers],
            "terminal": self.terminal,
            "release_eligible": self.release_eligible,
        }

    @classmethod
    def from_dict(cls, payload: Mapping[str, object]) -> Self:
        expected_fields = frozenset(
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
        _require_exact_keys(payload, expected=expected_fields, label="candidate generation")
        _parse_schema(payload, kind=cls.kind, label="candidate generation")
        calls = tuple(
            LogicalRequestCallV1.from_dict(_mapping(item, field_name="logical call"))
            for item in _list(payload["logical_calls"], field_name="logical_calls")
        )
        routes = tuple(
            RouteRequestMemberV1.from_dict(_mapping(item, field_name="route member"))
            for item in _list(payload["route_members"], field_name="route_members")
        )
        cells = tuple(
            FieldPeriodDenominatorCellV1.from_dict(_mapping(item, field_name="field-period cell"))
            for item in _list(payload["field_period_cells"], field_name="field_period_cells")
        )
        blockers = tuple(
            CandidateBlockerV1.from_dict(_mapping(item, field_name="candidate blocker"))
            for item in _list(payload["blockers"], field_name="blockers")
        )
        counts = {
            "logical_call_count": len(calls),
            "route_member_count": len(routes),
            "field_period_cell_count": len(cells),
            "blocker_count": len(blockers),
        }
        if any(
            type(payload[name]) is not int or payload[name] != value
            for name, value in counts.items()
        ):
            raise RequestUniverseCandidateContractError(
                "candidate count differs from its exact inventory"
            )
        return cls(
            authority_generation_sha256=cast("str", payload["authority_generation_sha256"]),
            source_inputs_sha256=cast("str", payload["source_inputs_sha256"]),
            field_fate_contract_sha256=cast("str", payload["field_fate_contract_sha256"]),
            temporal_contract_sha256=cast("str", payload["temporal_contract_sha256"]),
            logical_calls=calls,
            route_members=routes,
            field_period_cells=cells,
            blockers=blockers,
            logical_call_inventory_sha256=cast("str", payload["logical_call_inventory_sha256"]),
            route_member_inventory_sha256=cast("str", payload["route_member_inventory_sha256"]),
            field_period_inventory_sha256=cast("str", payload["field_period_inventory_sha256"]),
            blocker_inventory_sha256=cast("str", payload["blocker_inventory_sha256"]),
            terminal=cast("Literal[False]", payload["terminal"]),
            release_eligible=cast("Literal[False]", payload["release_eligible"]),
        )

    @classmethod
    def from_canonical_bytes(cls, encoded: bytes) -> Self:
        payload = _decode_canonical_mapping(encoded)
        result = cls.from_dict(payload)
        if result.canonical_bytes != encoded:
            raise RequestUniverseCandidateContractError(
                "candidate canonical bytes differ after strict reconstruction"
            )
        return result


def _field_shape(item: FieldOccurrenceInputV1) -> tuple[object, ...]:
    return (
        item.route_id,
        item.endpoint_name,
        item.result_name,
        item.result_ordinal,
        item.nested_path,
    )


def _route_shape(item: RouteRequestMemberV1) -> tuple[object, ...]:
    return (
        item.route_id,
        item.endpoint_name,
        item.result_name,
        item.result_ordinal,
        item.nested_path,
    )


def _compile_blockers(
    source: RequestUniverseCandidateSourceV1,
    *,
    fields_by_shape: Mapping[tuple[object, ...], Sequence[FieldOccurrenceInputV1]],
    periods_by_member: Mapping[str, Sequence[ExplicitTemporalScopeValueV1]],
) -> tuple[CandidateBlockerV1, ...]:
    blockers: list[CandidateBlockerV1] = [
        CandidateBlockerV1(
            authority_generation_sha256=source.authority_generation_sha256,
            blocker_code="candidate_not_fixed_point",
            subject_id="request_universe_candidate_generation_v1",
            evidence_sha256=source.source_inputs_sha256,
        )
    ]
    for route in source.route_members:
        if not fields_by_shape.get(_route_shape(route)):
            blockers.append(
                CandidateBlockerV1(
                    authority_generation_sha256=source.authority_generation_sha256,
                    blocker_code="route_field_denominator_absent",
                    subject_id=route.route_request_member_id,
                    evidence_sha256=source.field_fate_contract_sha256,
                )
            )
        if not periods_by_member.get(route.route_request_member_id):
            blockers.append(
                CandidateBlockerV1(
                    authority_generation_sha256=source.authority_generation_sha256,
                    blocker_code="explicit_temporal_scope_absent",
                    subject_id=route.route_request_member_id,
                    evidence_sha256=source.temporal_contract_sha256,
                )
            )
    for value in source.unintegrated_cume_values:
        blockers.append(
            CandidateBlockerV1(
                authority_generation_sha256=source.authority_generation_sha256,
                blocker_code="unintegrated_cume_value",
                subject_id=value.workload_content_sha256,
                evidence_sha256=value.identity_sha256,
            )
        )
    return tuple(sorted(blockers, key=lambda item: item.identity_sha256))


def compile_request_universe_candidate_generation_v1(
    source: RequestUniverseCandidateSourceV1,
) -> RequestUniverseCandidateGenerationV1:
    """Compile the exact nonterminal cross product of explicit source inputs."""

    if type(source) is not RequestUniverseCandidateSourceV1:
        raise RequestUniverseCandidateContractError(
            "candidate compiler requires an exact frozen source DTO"
        )
    fields_by_shape: dict[tuple[object, ...], list[FieldOccurrenceInputV1]] = {}
    for item in source.field_occurrences:
        fields_by_shape.setdefault(_field_shape(item), []).append(item)
    periods_by_member: dict[str, list[ExplicitTemporalScopeValueV1]] = {}
    for item in source.explicit_temporal_scopes:
        periods_by_member.setdefault(item.route_request_member_id, []).append(item)

    cells: list[FieldPeriodDenominatorCellV1] = []
    for route in source.route_members:
        for field_occurrence in fields_by_shape.get(_route_shape(route), ()):
            for temporal_scope in periods_by_member.get(route.route_request_member_id, ()):
                cells.append(
                    FieldPeriodDenominatorCellV1.build(
                        route_member=route,
                        field_occurrence=field_occurrence,
                        temporal_scope=temporal_scope,
                    )
                )
                if len(cells) > _MAX_CELLS:
                    raise RequestUniverseCandidateContractError(
                        "field-period cell cross product exceeds the bound"
                    )
    canonical_cells = tuple(sorted(cells, key=lambda item: item.cell_id))
    blockers = _compile_blockers(
        source,
        fields_by_shape=fields_by_shape,
        periods_by_member=periods_by_member,
    )
    calls = source.logical_calls
    routes = source.route_members
    return RequestUniverseCandidateGenerationV1(
        authority_generation_sha256=source.authority_generation_sha256,
        source_inputs_sha256=source.source_inputs_sha256,
        field_fate_contract_sha256=source.field_fate_contract_sha256,
        temporal_contract_sha256=source.temporal_contract_sha256,
        logical_calls=calls,
        route_members=routes,
        field_period_cells=canonical_cells,
        blockers=blockers,
        logical_call_inventory_sha256=canonical_request_universe_sha256(
            [item.to_dict() for item in calls]
        ),
        route_member_inventory_sha256=canonical_request_universe_sha256(
            [item.to_dict() for item in routes]
        ),
        field_period_inventory_sha256=canonical_request_universe_sha256(
            [item.to_dict() for item in canonical_cells]
        ),
        blocker_inventory_sha256=canonical_request_universe_sha256(
            [item.to_dict() for item in blockers]
        ),
        terminal=False,
        release_eligible=False,
    )


class TerminalRequestDisposition(StrEnum):
    """Only terminal outcomes admitted into a final request universe."""

    CAPTURED_NONEMPTY = "captured_nonempty"
    CAPTURED_PRESENT_EMPTY = "captured_present_empty"
    UPSTREAM_UNAVAILABLE = "upstream_unavailable"


@dataclass(frozen=True, slots=True)
class TerminalRequestEvidenceV1:
    """Typed, generation-bound evidence for one terminal request outcome."""

    authority_generation_sha256: str
    checkpoint_identity_sha256: str
    request_closure_receipt_sha256: str
    w2_authority_identity_sha256: str
    temporal_field_denominator_sha256: str
    observation_generation_key_sha256: str
    physical_call_id: str
    request_scope_sha256: str
    source_family: str
    endpoint_name: str
    provider_request_sha256: str
    request_observation_sha256: str
    request_call: LogicalRequestCallV1
    disposition: TerminalRequestDisposition
    captured_row_count: int | None = None
    result_receipt_count: int | None = None
    staging_receipt_count: int | None = None
    result_receipt_inventory_sha256: str | None = None
    staging_receipt_inventory_sha256: str | None = None
    typed_upstream_unavailable_evidence_sha256: str | None = None
    upstream_support_authority_sha256: str | None = None
    safe_probe_receipt_sha256: str | None = None
    unavailable_reason_code: str | None = None
    validity_scope_start: str | None = None
    validity_scope_end: str | None = None
    independent_verifier_id: str | None = None
    independent_verifier_sha256: str | None = None
    revalidation_policy: str | None = None
    evidence_sha256: str = ""

    schema_version: ClassVar[int] = REQUEST_UNIVERSE_FINAL_SCHEMA_VERSION
    kind: ClassVar[str] = "terminal_request_evidence_v1"

    def __post_init__(self) -> None:
        for field_name in (
            "authority_generation_sha256",
            "checkpoint_identity_sha256",
            "request_closure_receipt_sha256",
            "w2_authority_identity_sha256",
            "temporal_field_denominator_sha256",
            "observation_generation_key_sha256",
            "request_scope_sha256",
            "provider_request_sha256",
            "request_observation_sha256",
        ):
            _require_sha256(getattr(self, field_name), field_name=field_name)
        _require_safe_id(self.physical_call_id, field_name="physical_call_id")
        if self.source_family not in {"stats", "live", "static"}:
            raise RequestUniverseCandidateContractError(
                "terminal evidence source family is unsupported"
            )
        _require_safe_id(self.endpoint_name, field_name="endpoint_name")
        if type(self.request_call) is not LogicalRequestCallV1:
            raise RequestUniverseCandidateContractError(
                "terminal evidence lacks its exact logical request call"
            )
        if (
            self.request_call.authority_generation_sha256 != self.authority_generation_sha256
            or self.request_call.physical_call_id != self.physical_call_id
            or self.request_call.request_scope_sha256 != self.request_scope_sha256
            or self.request_call.source_family != self.source_family
            or self.request_call.endpoint_name != self.endpoint_name
        ):
            raise RequestUniverseCandidateContractError(
                "terminal evidence logical request call is stale or foreign"
            )
        if type(self.disposition) is not TerminalRequestDisposition:
            raise RequestUniverseCandidateContractError("terminal evidence disposition is foreign")
        capture_fields = (
            self.captured_row_count,
            self.result_receipt_count,
            self.staging_receipt_count,
            self.result_receipt_inventory_sha256,
            self.staging_receipt_inventory_sha256,
        )
        unavailable_fields = (
            self.typed_upstream_unavailable_evidence_sha256,
            self.upstream_support_authority_sha256,
            self.safe_probe_receipt_sha256,
            self.unavailable_reason_code,
            self.validity_scope_start,
            self.validity_scope_end,
            self.independent_verifier_id,
            self.independent_verifier_sha256,
            self.revalidation_policy,
        )
        if self.disposition is TerminalRequestDisposition.UPSTREAM_UNAVAILABLE:
            if any(value is not None for value in capture_fields):
                raise RequestUniverseCandidateContractError(
                    "upstream-unavailable evidence cannot carry capture receipts"
                )
            if any(value is None for value in unavailable_fields):
                raise RequestUniverseCandidateContractError(
                    "upstream-unavailable evidence lacks its exact typed support"
                )
            for field_name in (
                "typed_upstream_unavailable_evidence_sha256",
                "upstream_support_authority_sha256",
                "safe_probe_receipt_sha256",
                "independent_verifier_sha256",
            ):
                _require_sha256(getattr(self, field_name), field_name=field_name)
            for field_name in (
                "validity_scope_start",
                "validity_scope_end",
                "independent_verifier_id",
            ):
                _require_safe_id(cast("str", getattr(self, field_name)), field_name=field_name)
            if self.unavailable_reason_code != "provider_contract_absent_for_scope":
                raise RequestUniverseCandidateContractError(
                    "upstream-unavailable reason is not exact provider-contract evidence"
                )
            if self.revalidation_policy != "on_authority_or_scope_change":
                raise RequestUniverseCandidateContractError(
                    "upstream-unavailable evidence lacks the exact revalidation policy"
                )
        else:
            if any(value is not None for value in unavailable_fields):
                raise RequestUniverseCandidateContractError(
                    "captured evidence cannot carry unavailable support"
                )
            row_count = _require_nonnegative_int(
                self.captured_row_count,
                field_name="captured_row_count",
            )
            result_count = _require_nonnegative_int(
                self.result_receipt_count,
                field_name="result_receipt_count",
            )
            staging_count = _require_nonnegative_int(
                self.staging_receipt_count,
                field_name="staging_receipt_count",
            )
            _require_sha256(
                self.result_receipt_inventory_sha256,
                field_name="result_receipt_inventory_sha256",
            )
            _require_sha256(
                self.staging_receipt_inventory_sha256,
                field_name="staging_receipt_inventory_sha256",
            )
            if (self.disposition is TerminalRequestDisposition.CAPTURED_NONEMPTY) != (
                row_count > 0
            ):
                raise RequestUniverseCandidateContractError(
                    "captured terminal disposition contradicts its exact row count"
                )
            if result_count < 1 or staging_count < 1:
                raise RequestUniverseCandidateContractError(
                    "captured terminal evidence lacks present result/staging receipts"
                )
        expected = canonical_request_universe_sha256(self._body())
        if self.evidence_sha256 and self.evidence_sha256 != expected:
            raise RequestUniverseCandidateContractError("terminal request evidence digest differs")
        object.__setattr__(self, "evidence_sha256", expected)

    def _body(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "kind": self.kind,
            **{
                field_name: (
                    getattr(self, field_name).value
                    if field_name == "disposition"
                    else self.request_call.to_dict()
                    if field_name == "request_call"
                    else getattr(self, field_name)
                )
                for field_name in (
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
                )
            },
        }

    def to_dict(self) -> dict[str, object]:
        return {**self._body(), "evidence_sha256": self.evidence_sha256}

    @classmethod
    def from_dict(cls, payload: Mapping[str, object]) -> Self:
        fields = {
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
        _require_exact_keys(
            payload,
            expected=frozenset({"schema_version", "kind", *fields}),
            label="terminal request evidence",
        )
        _parse_schema(payload, kind=cls.kind, label="terminal request evidence")
        try:
            disposition = TerminalRequestDisposition(payload["disposition"])
        except (TypeError, ValueError) as exc:
            raise RequestUniverseCandidateContractError(
                "terminal request evidence disposition is unsupported"
            ) from exc
        values = {
            field_name: payload[field_name]
            for field_name in fields - {"disposition", "request_call"}
        }
        return cls(
            **cast("Any", values),
            request_call=LogicalRequestCallV1.from_dict(
                _mapping(payload["request_call"], field_name="terminal request call")
            ),
            disposition=disposition,
        )


@dataclass(frozen=True, slots=True)
class TerminalRequestClassificationV1:
    """Exact terminal classification derived from one typed evidence receipt."""

    authority_generation_sha256: str
    committed_observation_generation_sha256: str
    physical_call_id: str
    request_scope_sha256: str
    disposition: TerminalRequestDisposition
    evidence: TerminalRequestEvidenceV1

    schema_version: ClassVar[int] = REQUEST_UNIVERSE_FINAL_SCHEMA_VERSION
    kind: ClassVar[str] = "terminal_request_classification_v1"

    def __post_init__(self) -> None:
        for field_name in (
            "authority_generation_sha256",
            "committed_observation_generation_sha256",
            "request_scope_sha256",
        ):
            _require_sha256(getattr(self, field_name), field_name=field_name)
        _require_safe_id(self.physical_call_id, field_name="physical_call_id")
        if type(self.disposition) is not TerminalRequestDisposition:
            raise RequestUniverseCandidateContractError("terminal request disposition is foreign")
        if type(self.evidence) is not TerminalRequestEvidenceV1:
            raise RequestUniverseCandidateContractError(
                "terminal classification lacks typed evidence"
            )
        if (
            self.authority_generation_sha256 != self.evidence.authority_generation_sha256
            or self.physical_call_id != self.evidence.physical_call_id
            or self.request_scope_sha256 != self.evidence.request_scope_sha256
            or self.disposition is not self.evidence.disposition
        ):
            raise RequestUniverseCandidateContractError(
                "terminal classification is rebound from its typed evidence"
            )

    @property
    def identity_sha256(self) -> str:
        return canonical_request_universe_sha256(self.to_dict())

    def to_dict(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "kind": self.kind,
            "authority_generation_sha256": self.authority_generation_sha256,
            "committed_observation_generation_sha256": (
                self.committed_observation_generation_sha256
            ),
            "physical_call_id": self.physical_call_id,
            "request_scope_sha256": self.request_scope_sha256,
            "disposition": self.disposition.value,
            "evidence": self.evidence.to_dict(),
        }

    @classmethod
    def from_dict(cls, payload: Mapping[str, object]) -> Self:
        _require_exact_keys(
            payload,
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
            label="terminal request classification",
        )
        _parse_schema(payload, kind=cls.kind, label="terminal request classification")
        try:
            disposition = TerminalRequestDisposition(payload["disposition"])
        except (TypeError, ValueError) as exc:
            raise RequestUniverseCandidateContractError(
                "terminal request disposition is unsupported"
            ) from exc
        return cls(
            authority_generation_sha256=cast("str", payload["authority_generation_sha256"]),
            committed_observation_generation_sha256=cast(
                "str", payload["committed_observation_generation_sha256"]
            ),
            physical_call_id=cast("str", payload["physical_call_id"]),
            request_scope_sha256=cast("str", payload["request_scope_sha256"]),
            disposition=disposition,
            evidence=TerminalRequestEvidenceV1.from_dict(
                _mapping(payload["evidence"], field_name="terminal request evidence")
            ),
        )


@dataclass(frozen=True, slots=True)
class CommittedObservationGenerationV1:
    """Typed committed observations plus the next derived complete call set."""

    authority_generation_sha256: str
    checkpoint_identity_sha256: str
    request_closure_receipt_sha256: str
    w2_authority_identity_sha256: str
    temporal_field_denominator_sha256: str
    closure_fixed_point_provider_request_sha256s: tuple[str, ...]
    terminal_evidence: tuple[TerminalRequestEvidenceV1, ...]
    next_generation_calls: tuple[LogicalRequestCallV1, ...] = field(
        init=False,
        default_factory=tuple,
    )
    parent_observation_generation_sha256: str | None = None
    generation_ordinal: int = 1
    generation_key_sha256: str = ""
    closure_fixed_point_provider_request_inventory_sha256: str = ""
    terminal_evidence_inventory_sha256: str = ""
    next_generation_call_inventory_sha256: str = ""
    generation_sha256: str = ""

    schema_version: ClassVar[int] = REQUEST_UNIVERSE_FINAL_SCHEMA_VERSION
    kind: ClassVar[str] = "committed_observation_generation_v1"

    def __post_init__(self) -> None:
        authority = _require_sha256(
            self.authority_generation_sha256,
            field_name="authority_generation_sha256",
        )
        for field_name in (
            "checkpoint_identity_sha256",
            "request_closure_receipt_sha256",
            "w2_authority_identity_sha256",
            "temporal_field_denominator_sha256",
        ):
            _require_sha256(getattr(self, field_name), field_name=field_name)
        closure_units = _require_sorted_unique(
            self.closure_fixed_point_provider_request_sha256s,
            field_name="closure_fixed_point_provider_request_sha256s",
            key=lambda value: value,
            maximum=_MAX_CALLS,
            allow_empty=False,
        )
        for provider_request_sha256 in closure_units:
            _require_sha256(
                provider_request_sha256,
                field_name="closure fixed-point provider request SHA-256",
            )
        closure_root = canonical_request_universe_sha256(list(closure_units))
        if (
            self.closure_fixed_point_provider_request_inventory_sha256
            and self.closure_fixed_point_provider_request_inventory_sha256 != closure_root
        ):
            raise RequestUniverseCandidateContractError(
                "closure fixed-point provider request inventory differs"
            )
        if type(self.generation_ordinal) is not int or self.generation_ordinal < 1:
            raise RequestUniverseCandidateContractError(
                "observation generation ordinal must be positive"
            )
        if self.parent_observation_generation_sha256 is None:
            if self.generation_ordinal != 1:
                raise RequestUniverseCandidateContractError(
                    "genesis observation generation must use ordinal one"
                )
        else:
            _require_sha256(
                self.parent_observation_generation_sha256,
                field_name="parent_observation_generation_sha256",
            )
            if self.generation_ordinal == 1:
                raise RequestUniverseCandidateContractError(
                    "non-genesis observation generation cannot use ordinal one"
                )
        key_body = {
            "authority_generation_sha256": authority,
            "checkpoint_identity_sha256": self.checkpoint_identity_sha256,
            "request_closure_receipt_sha256": self.request_closure_receipt_sha256,
            "w2_authority_identity_sha256": self.w2_authority_identity_sha256,
            "temporal_field_denominator_sha256": (self.temporal_field_denominator_sha256),
            "closure_fixed_point_provider_request_inventory_sha256": closure_root,
            "parent_observation_generation_sha256": (self.parent_observation_generation_sha256),
            "generation_ordinal": self.generation_ordinal,
        }
        generation_key = canonical_request_universe_sha256(key_body)
        if self.generation_key_sha256 and self.generation_key_sha256 != generation_key:
            raise RequestUniverseCandidateContractError(
                "observation generation key differs from its authority inputs"
            )
        evidence = _require_sorted_unique(
            self.terminal_evidence,
            field_name="terminal_evidence",
            key=lambda item: item.physical_call_id,
            maximum=_MAX_CALLS,
            allow_empty=False,
        )
        calls = _require_sorted_unique(
            tuple(item.request_call for item in evidence),
            field_name="next_generation_calls",
            key=lambda item: item.physical_call_id,
            maximum=_MAX_CALLS,
            allow_empty=False,
        )
        roots = (
            self.checkpoint_identity_sha256,
            self.request_closure_receipt_sha256,
            self.w2_authority_identity_sha256,
            self.temporal_field_denominator_sha256,
        )
        if any(
            item.authority_generation_sha256 != authority
            or item.observation_generation_key_sha256 != generation_key
            or (
                item.checkpoint_identity_sha256,
                item.request_closure_receipt_sha256,
                item.w2_authority_identity_sha256,
                item.temporal_field_denominator_sha256,
            )
            != roots
            for item in evidence
        ):
            raise RequestUniverseCandidateContractError(
                "terminal evidence is stale or foreign to its committed generation"
            )
        if any(item.authority_generation_sha256 != authority for item in calls):
            raise RequestUniverseCandidateContractError("next-generation call is foreign")
        if tuple(sorted({item.provider_request_sha256 for item in evidence})) != (closure_units):
            raise RequestUniverseCandidateContractError(
                "terminal evidence differs from the closure fixed-point request inventory"
            )
        evidence_root = canonical_request_universe_sha256([item.to_dict() for item in evidence])
        call_root = canonical_request_universe_sha256([item.to_dict() for item in calls])
        for field_name, supplied, expected in (
            (
                "terminal_evidence_inventory_sha256",
                self.terminal_evidence_inventory_sha256,
                evidence_root,
            ),
            (
                "next_generation_call_inventory_sha256",
                self.next_generation_call_inventory_sha256,
                call_root,
            ),
        ):
            if supplied and supplied != expected:
                raise RequestUniverseCandidateContractError(
                    f"{field_name} differs from its exact inventory"
                )
        object.__setattr__(self, "generation_key_sha256", generation_key)
        object.__setattr__(
            self,
            "closure_fixed_point_provider_request_sha256s",
            closure_units,
        )
        object.__setattr__(
            self,
            "closure_fixed_point_provider_request_inventory_sha256",
            closure_root,
        )
        object.__setattr__(self, "terminal_evidence", evidence)
        object.__setattr__(self, "next_generation_calls", calls)
        object.__setattr__(
            self,
            "terminal_evidence_inventory_sha256",
            evidence_root,
        )
        object.__setattr__(
            self,
            "next_generation_call_inventory_sha256",
            call_root,
        )
        generation_sha = canonical_request_universe_sha256(self._body())
        if self.generation_sha256 and self.generation_sha256 != generation_sha:
            raise RequestUniverseCandidateContractError(
                "committed observation generation digest differs"
            )
        object.__setattr__(self, "generation_sha256", generation_sha)

    def _body(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "kind": self.kind,
            "authority_generation_sha256": self.authority_generation_sha256,
            "checkpoint_identity_sha256": self.checkpoint_identity_sha256,
            "request_closure_receipt_sha256": self.request_closure_receipt_sha256,
            "w2_authority_identity_sha256": self.w2_authority_identity_sha256,
            "temporal_field_denominator_sha256": (self.temporal_field_denominator_sha256),
            "parent_observation_generation_sha256": (self.parent_observation_generation_sha256),
            "generation_ordinal": self.generation_ordinal,
            "generation_key_sha256": self.generation_key_sha256,
            "closure_fixed_point_provider_request_count": len(
                self.closure_fixed_point_provider_request_sha256s
            ),
            "closure_fixed_point_provider_request_inventory_sha256": (
                self.closure_fixed_point_provider_request_inventory_sha256
            ),
            "closure_fixed_point_provider_request_sha256s": list(
                self.closure_fixed_point_provider_request_sha256s
            ),
            "terminal_evidence_count": len(self.terminal_evidence),
            "next_generation_call_count": len(self.next_generation_calls),
            "terminal_evidence_inventory_sha256": (self.terminal_evidence_inventory_sha256),
            "next_generation_call_inventory_sha256": (self.next_generation_call_inventory_sha256),
            "terminal_evidence": [item.to_dict() for item in self.terminal_evidence],
            "next_generation_calls": [item.to_dict() for item in self.next_generation_calls],
        }

    def to_dict(self) -> dict[str, object]:
        return {**self._body(), "generation_sha256": self.generation_sha256}

    @classmethod
    def from_dict(cls, payload: Mapping[str, object]) -> Self:
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
        _require_exact_keys(
            payload,
            expected=expected,
            label="committed observation generation",
        )
        _parse_schema(
            payload,
            kind=cls.kind,
            label="committed observation generation",
        )
        evidence = tuple(
            TerminalRequestEvidenceV1.from_dict(
                _mapping(item, field_name="terminal request evidence")
            )
            for item in _list(
                payload["terminal_evidence"],
                field_name="terminal_evidence",
            )
        )
        calls = tuple(
            LogicalRequestCallV1.from_dict(_mapping(item, field_name="next-generation call"))
            for item in _list(
                payload["next_generation_calls"],
                field_name="next_generation_calls",
            )
        )
        closure_units = tuple(
            cast(
                "list[str]",
                _list(
                    payload["closure_fixed_point_provider_request_sha256s"],
                    field_name="closure_fixed_point_provider_request_sha256s",
                ),
            )
        )
        if (
            type(payload["closure_fixed_point_provider_request_count"]) is not int
            or payload["closure_fixed_point_provider_request_count"] != len(closure_units)
            or type(payload["terminal_evidence_count"]) is not int
            or payload["terminal_evidence_count"] != len(evidence)
            or type(payload["next_generation_call_count"]) is not int
            or payload["next_generation_call_count"] != len(calls)
        ):
            raise RequestUniverseCandidateContractError(
                "committed observation generation count differs"
            )
        result = cls(
            authority_generation_sha256=cast("str", payload["authority_generation_sha256"]),
            checkpoint_identity_sha256=cast("str", payload["checkpoint_identity_sha256"]),
            request_closure_receipt_sha256=cast("str", payload["request_closure_receipt_sha256"]),
            w2_authority_identity_sha256=cast("str", payload["w2_authority_identity_sha256"]),
            temporal_field_denominator_sha256=cast(
                "str", payload["temporal_field_denominator_sha256"]
            ),
            closure_fixed_point_provider_request_sha256s=closure_units,
            terminal_evidence=evidence,
            parent_observation_generation_sha256=cast(
                "str | None", payload["parent_observation_generation_sha256"]
            ),
            generation_ordinal=cast("int", payload["generation_ordinal"]),
            generation_key_sha256=cast("str", payload["generation_key_sha256"]),
            closure_fixed_point_provider_request_inventory_sha256=cast(
                "str",
                payload["closure_fixed_point_provider_request_inventory_sha256"],
            ),
            terminal_evidence_inventory_sha256=cast(
                "str", payload["terminal_evidence_inventory_sha256"]
            ),
            next_generation_call_inventory_sha256=cast(
                "str", payload["next_generation_call_inventory_sha256"]
            ),
            generation_sha256=cast("str", payload["generation_sha256"]),
        )
        if result.next_generation_calls != calls:
            raise RequestUniverseCandidateContractError(
                "serialized next-generation calls differ from typed evidence derivation"
            )
        return result


@dataclass(frozen=True, slots=True)
class RequestUniverseShardV1:
    """Bounded executable partition member over physical request identities."""

    authority_generation_sha256: str
    shard_id: str
    physical_call_ids: tuple[str, ...]
    request_inventory_sha256: str = ""

    schema_version: ClassVar[int] = REQUEST_UNIVERSE_FINAL_SCHEMA_VERSION
    kind: ClassVar[str] = "request_universe_shard_v1"

    def __post_init__(self) -> None:
        _require_sha256(
            self.authority_generation_sha256,
            field_name="authority_generation_sha256",
        )
        _require_safe_id(self.shard_id, field_name="shard_id")
        ids = _require_sorted_unique(
            self.physical_call_ids,
            field_name="physical_call_ids",
            key=lambda value: value,
            maximum=_MAX_CALLS,
            allow_empty=False,
        )
        for physical_call_id in ids:
            _require_safe_id(physical_call_id, field_name="physical_call_id")
        expected = canonical_request_universe_sha256(list(ids))
        if self.request_inventory_sha256 and self.request_inventory_sha256 != expected:
            raise RequestUniverseCandidateContractError("shard request inventory digest differs")
        object.__setattr__(self, "physical_call_ids", ids)
        object.__setattr__(self, "request_inventory_sha256", expected)

    def to_dict(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "kind": self.kind,
            "authority_generation_sha256": self.authority_generation_sha256,
            "shard_id": self.shard_id,
            "physical_call_ids": list(self.physical_call_ids),
            "request_inventory_sha256": self.request_inventory_sha256,
        }

    @classmethod
    def from_dict(cls, payload: Mapping[str, object]) -> Self:
        _require_exact_keys(
            payload,
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
        _parse_schema(payload, kind=cls.kind, label="request-universe shard")
        return cls(
            authority_generation_sha256=cast("str", payload["authority_generation_sha256"]),
            shard_id=cast("str", payload["shard_id"]),
            physical_call_ids=tuple(
                cast(
                    "list[str]",
                    _list(
                        payload["physical_call_ids"],
                        field_name="physical_call_ids",
                    ),
                )
            ),
            request_inventory_sha256=cast("str", payload["request_inventory_sha256"]),
        )


@dataclass(frozen=True, slots=True)
class RequestUniverseFinalizationSourceV1:
    """All local immutable evidence required before final compilation."""

    authority_generation_sha256: str
    checkpoint_identity_sha256: str
    checkpoint_authority_generation_sha256: str
    request_closure_receipt_sha256: str
    request_closure_authority_generation_sha256: str
    w2_authority_identity_sha256: str
    w2_authority_generation_sha256: str
    temporal_field_denominator_sha256: str
    temporal_field_authority_generation_sha256: str
    committed_observation_generation_sha256: str
    committed_observation_authority_generation_sha256: str
    candidate_source_sha256: str
    candidate_generation_sha256: str
    candidate_independent_proof_sha256: str
    source_admission_sha256: str
    committed_observation_generation: CommittedObservationGenerationV1
    logical_calls: tuple[LogicalRequestCallV1, ...]
    terminal_classifications: tuple[TerminalRequestClassificationV1, ...]
    shards: tuple[RequestUniverseShardV1, ...]
    ancestor_request_universe_sha256s: tuple[str, ...] = field(default_factory=tuple)
    parent_request_universe_sha256: str | None = None
    generation_ordinal: int = 1

    schema_version: ClassVar[int] = REQUEST_UNIVERSE_FINAL_SCHEMA_VERSION
    kind: ClassVar[str] = "request_universe_finalization_source_v1"

    def __post_init__(self) -> None:
        authority = _require_sha256(
            self.authority_generation_sha256,
            field_name="authority_generation_sha256",
        )
        for field_name in (
            "checkpoint_identity_sha256",
            "request_closure_receipt_sha256",
            "w2_authority_identity_sha256",
            "temporal_field_denominator_sha256",
            "committed_observation_generation_sha256",
            "candidate_source_sha256",
            "candidate_generation_sha256",
            "candidate_independent_proof_sha256",
            "source_admission_sha256",
        ):
            _require_sha256(getattr(self, field_name), field_name=field_name)
        generation_bindings = (
            self.checkpoint_authority_generation_sha256,
            self.request_closure_authority_generation_sha256,
            self.w2_authority_generation_sha256,
            self.temporal_field_authority_generation_sha256,
            self.committed_observation_authority_generation_sha256,
        )
        if any(
            _require_sha256(value, field_name="bound authority generation") != authority
            for value in generation_bindings
        ):
            raise RequestUniverseCandidateContractError(
                "finalization evidence is stale or foreign to the authority generation"
            )
        if type(self.committed_observation_generation) is not CommittedObservationGenerationV1:
            raise RequestUniverseCandidateContractError(
                "finalization source lacks a typed committed observation generation"
            )
        observation_generation = self.committed_observation_generation
        if (
            observation_generation.generation_sha256 != self.committed_observation_generation_sha256
            or observation_generation.authority_generation_sha256 != authority
            or observation_generation.checkpoint_identity_sha256 != self.checkpoint_identity_sha256
            or observation_generation.request_closure_receipt_sha256
            != self.request_closure_receipt_sha256
            or observation_generation.w2_authority_identity_sha256
            != self.w2_authority_identity_sha256
            or observation_generation.temporal_field_denominator_sha256
            != self.temporal_field_denominator_sha256
        ):
            raise RequestUniverseCandidateContractError(
                "committed observation generation is stale or foreign"
            )
        calls = _require_sorted_unique(
            self.logical_calls,
            field_name="final logical_calls",
            key=lambda item: item.physical_call_id,
            maximum=_MAX_CALLS,
            allow_empty=False,
        )
        classifications = _require_sorted_unique(
            self.terminal_classifications,
            field_name="terminal_classifications",
            key=lambda item: item.physical_call_id,
            maximum=_MAX_CALLS,
            allow_empty=False,
        )
        shards = _require_sorted_unique(
            self.shards,
            field_name="shards",
            key=lambda item: item.shard_id,
            maximum=_MAX_CALLS,
            allow_empty=False,
        )
        if any(item.authority_generation_sha256 != authority for item in calls):
            raise RequestUniverseCandidateContractError("final logical call is foreign")
        if any(
            item.authority_generation_sha256 != authority
            or item.committed_observation_generation_sha256
            != self.committed_observation_generation_sha256
            for item in classifications
        ):
            raise RequestUniverseCandidateContractError(
                "terminal classification is stale or foreign"
            )
        evidence_by_call = {
            item.physical_call_id: item for item in observation_generation.terminal_evidence
        }
        if any(
            evidence_by_call.get(item.physical_call_id) != item.evidence for item in classifications
        ):
            raise RequestUniverseCandidateContractError(
                "terminal classification differs from committed typed evidence"
            )
        if any(item.authority_generation_sha256 != authority for item in shards):
            raise RequestUniverseCandidateContractError("request shard is foreign")
        call_by_id = {item.physical_call_id: item for item in calls}
        classification_ids = {item.physical_call_id for item in classifications}
        if classification_ids != set(call_by_id):
            raise RequestUniverseCandidateContractError(
                "terminal classifications do not equal the logical request denominator"
            )
        for classification in classifications:
            call = call_by_id[classification.physical_call_id]
            if classification.request_scope_sha256 != call.request_scope_sha256:
                raise RequestUniverseCandidateContractError(
                    "terminal classification request scope differs"
                )
        partition = [
            physical_call_id for shard in shards for physical_call_id in shard.physical_call_ids
        ]
        if len(partition) != len(set(partition)):
            raise RequestUniverseCandidateContractError("request shard partition overlaps")
        if set(partition) != set(call_by_id):
            raise RequestUniverseCandidateContractError(
                "request shard partition omits or invents logical requests"
            )
        next_call_ids = {
            item.physical_call_id for item in observation_generation.next_generation_calls
        }
        if not set(call_by_id) <= next_call_ids:
            raise RequestUniverseCandidateContractError(
                "derived next generation omits an admitted logical request"
            )
        ancestry = self.ancestor_request_universe_sha256s
        if type(ancestry) is not tuple or len(ancestry) != len(set(ancestry)):
            raise RequestUniverseCandidateContractError(
                "request-universe ancestry is duplicated or cyclic"
            )
        for item in ancestry:
            _require_sha256(item, field_name="ancestor_request_universe_sha256")
        if self.parent_request_universe_sha256 is None:
            if ancestry or self.generation_ordinal != 1:
                raise RequestUniverseCandidateContractError(
                    "genesis request universe has foreign ancestry"
                )
        else:
            parent = _require_sha256(
                self.parent_request_universe_sha256,
                field_name="parent_request_universe_sha256",
            )
            if not ancestry or ancestry[-1] != parent:
                raise RequestUniverseCandidateContractError(
                    "request-universe parent differs from ancestry"
                )
            if self.generation_ordinal != len(ancestry) + 1:
                raise RequestUniverseCandidateContractError(
                    "request-universe generation ordinal differs from ancestry"
                )
        if type(self.generation_ordinal) is not int or self.generation_ordinal < 1:
            raise RequestUniverseCandidateContractError(
                "generation_ordinal must be a positive integer"
            )
        matchup_endpoints = {
            "player_vs_player",
            "team_vs_player",
            "team_and_players_vs",
            "team_and_players_vs_players",
        }
        if any(
            matchup_endpoints
            & {
                call.endpoint_name,
                call.canonical_endpoint_name,
                call.physical_endpoint_name,
            }
            and call.dependent_workload_sha256 is None
            for call in calls
        ):
            raise RequestUniverseCandidateContractError(
                "matchup request lacks direct dependent-workload evidence"
            )
        object.__setattr__(self, "logical_calls", calls)
        object.__setattr__(self, "terminal_classifications", classifications)
        object.__setattr__(self, "shards", shards)

    @property
    def source_inputs_sha256(self) -> str:
        return canonical_request_universe_sha256(self.to_dict())

    @property
    def derived_delta_physical_call_ids(self) -> tuple[str, ...]:
        admitted = {item.physical_call_id for item in self.logical_calls}
        return tuple(
            item.physical_call_id
            for item in self.committed_observation_generation.next_generation_calls
            if item.physical_call_id not in admitted
        )

    def to_dict(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "kind": self.kind,
            **{
                field_name: getattr(self, field_name)
                for field_name in (
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
                )
            },
            "logical_calls": [item.to_dict() for item in self.logical_calls],
            "terminal_classifications": [item.to_dict() for item in self.terminal_classifications],
            "committed_observation_generation": (self.committed_observation_generation.to_dict()),
            "shards": [item.to_dict() for item in self.shards],
            "ancestor_request_universe_sha256s": list(self.ancestor_request_universe_sha256s),
        }

    @classmethod
    def from_dict(cls, payload: Mapping[str, object]) -> Self:
        scalar_fields = {
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
        _require_exact_keys(
            payload,
            expected=frozenset(
                {
                    "schema_version",
                    "kind",
                    *scalar_fields,
                    "logical_calls",
                    "terminal_classifications",
                    "committed_observation_generation",
                    "shards",
                    "ancestor_request_universe_sha256s",
                }
            ),
            label="request-universe finalization source",
        )
        _parse_schema(payload, kind=cls.kind, label="request-universe finalization source")
        values = {field_name: payload[field_name] for field_name in scalar_fields}
        return cls(
            **cast("Any", values),
            committed_observation_generation=CommittedObservationGenerationV1.from_dict(
                _mapping(
                    payload["committed_observation_generation"],
                    field_name="committed observation generation",
                )
            ),
            logical_calls=tuple(
                LogicalRequestCallV1.from_dict(_mapping(item, field_name="logical call"))
                for item in _list(payload["logical_calls"], field_name="logical_calls")
            ),
            terminal_classifications=tuple(
                TerminalRequestClassificationV1.from_dict(
                    _mapping(item, field_name="terminal classification")
                )
                for item in _list(
                    payload["terminal_classifications"],
                    field_name="terminal_classifications",
                )
            ),
            shards=tuple(
                RequestUniverseShardV1.from_dict(_mapping(item, field_name="shard"))
                for item in _list(payload["shards"], field_name="shards")
            ),
            ancestor_request_universe_sha256s=tuple(
                cast(
                    "list[str]",
                    _list(
                        payload["ancestor_request_universe_sha256s"],
                        field_name="ancestor_request_universe_sha256s",
                    ),
                )
            ),
        )

    @classmethod
    def from_canonical_bytes(cls, raw: bytes) -> Self:
        result = cls.from_dict(_decode_canonical_mapping(raw))
        if canonical_request_universe_json_bytes(result.to_dict()) != raw:
            raise RequestUniverseCandidateContractError(
                "finalization source is not exact canonical JSON"
            )
        return result


@dataclass(frozen=True, slots=True)
class RequestUniverseEmptyDeltaReceiptV1:
    authority_generation_sha256: str
    finalization_source_sha256: str
    committed_observation_generation_sha256: str
    derivation_input_sha256: str
    admitted_call_inventory_sha256: str
    derived_call_inventory_sha256: str
    derived_call_count: int
    logical_call_inventory_sha256: str
    logical_call_count: int
    delta_inventory_sha256: str
    delta_count: Literal[0]
    compiler_id: Literal["primary_request_universe_v1"]
    receipt_sha256: str

    schema_version: ClassVar[int] = REQUEST_UNIVERSE_FINAL_SCHEMA_VERSION
    kind: ClassVar[str] = "request_universe_empty_delta_receipt_v1"

    def __post_init__(self) -> None:
        for field_name in (
            "authority_generation_sha256",
            "finalization_source_sha256",
            "committed_observation_generation_sha256",
            "derivation_input_sha256",
            "admitted_call_inventory_sha256",
            "derived_call_inventory_sha256",
            "logical_call_inventory_sha256",
            "delta_inventory_sha256",
        ):
            _require_sha256(getattr(self, field_name), field_name=field_name)
        _require_nonnegative_int(self.logical_call_count, field_name="logical_call_count")
        _require_nonnegative_int(self.derived_call_count, field_name="derived_call_count")
        if (
            type(self.delta_count) is not int
            or self.delta_count != 0
            or self.delta_inventory_sha256 != canonical_request_universe_sha256([])
            or self.compiler_id != "primary_request_universe_v1"
            or self.admitted_call_inventory_sha256 != self.logical_call_inventory_sha256
        ):
            raise RequestUniverseCandidateContractError(
                "primary fixed-point delta is nonempty or foreign"
            )
        if self.receipt_sha256 != canonical_request_universe_sha256(self._body()):
            raise RequestUniverseCandidateContractError(
                "primary empty-delta receipt digest differs"
            )

    def _body(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "kind": self.kind,
            "authority_generation_sha256": self.authority_generation_sha256,
            "finalization_source_sha256": self.finalization_source_sha256,
            "committed_observation_generation_sha256": (
                self.committed_observation_generation_sha256
            ),
            "derivation_input_sha256": self.derivation_input_sha256,
            "admitted_call_inventory_sha256": self.admitted_call_inventory_sha256,
            "derived_call_inventory_sha256": self.derived_call_inventory_sha256,
            "derived_call_count": self.derived_call_count,
            "logical_call_inventory_sha256": self.logical_call_inventory_sha256,
            "logical_call_count": self.logical_call_count,
            "delta_inventory_sha256": self.delta_inventory_sha256,
            "delta_count": self.delta_count,
            "compiler_id": self.compiler_id,
        }

    def to_dict(self) -> dict[str, object]:
        return {**self._body(), "receipt_sha256": self.receipt_sha256}

    @classmethod
    def build(cls, source: RequestUniverseFinalizationSourceV1) -> Self:
        admitted = {item.physical_call_id for item in source.logical_calls}
        delta = tuple(
            item
            for item in source.committed_observation_generation.next_generation_calls
            if item.physical_call_id not in admitted
        )
        if delta:
            raise RequestUniverseCandidateContractError(
                "primary compiler derived a nonempty next-generation delta"
            )
        admitted_root = canonical_request_universe_sha256(
            [item.to_dict() for item in source.logical_calls]
        )
        derived_root = source.committed_observation_generation.next_generation_call_inventory_sha256
        body = {
            "schema_version": cls.schema_version,
            "kind": cls.kind,
            "authority_generation_sha256": source.authority_generation_sha256,
            "finalization_source_sha256": source.source_inputs_sha256,
            "committed_observation_generation_sha256": (
                source.committed_observation_generation_sha256
            ),
            "derivation_input_sha256": (source.committed_observation_generation.generation_sha256),
            "admitted_call_inventory_sha256": admitted_root,
            "derived_call_inventory_sha256": derived_root,
            "derived_call_count": len(
                source.committed_observation_generation.next_generation_calls
            ),
            "logical_call_inventory_sha256": admitted_root,
            "logical_call_count": len(source.logical_calls),
            "delta_inventory_sha256": canonical_request_universe_sha256([]),
            "delta_count": 0,
            "compiler_id": "primary_request_universe_v1",
        }
        values = {
            key: value for key, value in body.items() if key not in {"schema_version", "kind"}
        }
        return cls(
            **cast("Any", values),
            receipt_sha256=canonical_request_universe_sha256(body),
        )

    @classmethod
    def from_dict(cls, payload: Mapping[str, object]) -> Self:
        expected = frozenset(
            {
                "schema_version",
                "kind",
                "authority_generation_sha256",
                "finalization_source_sha256",
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
        _require_exact_keys(payload, expected=expected, label="primary empty-delta receipt")
        _parse_schema(payload, kind=cls.kind, label="primary empty-delta receipt")
        values = {key: payload[key] for key in expected - {"schema_version", "kind"}}
        return cls(**cast("Any", values))


@dataclass(frozen=True, slots=True)
class RequestUniverseV1:
    """Immutable complete logical denominator, separate from executable shards."""

    authority_generation_sha256: str
    checkpoint_identity_sha256: str
    request_closure_receipt_sha256: str
    w2_authority_identity_sha256: str
    temporal_field_denominator_sha256: str
    committed_observation_generation_sha256: str
    finalization_source_sha256: str
    candidate_source_sha256: str
    candidate_generation_sha256: str
    candidate_independent_proof_sha256: str
    source_admission_sha256: str
    logical_calls: tuple[LogicalRequestCallV1, ...]
    terminal_classifications: tuple[TerminalRequestClassificationV1, ...]
    shards: tuple[RequestUniverseShardV1, ...]
    logical_call_inventory_sha256: str
    terminal_classification_inventory_sha256: str
    shard_inventory_sha256: str
    primary_empty_delta_receipt: RequestUniverseEmptyDeltaReceiptV1
    parent_request_universe_sha256: str | None
    generation_ordinal: int
    exact_request_denominator: Literal[True] = True
    terminal_classification_complete: Literal[True] = True
    shard_partition_exact: Literal[True] = True
    least_fixed_point_proven: Literal[True] = True
    terminal: Literal[True] = True
    release_eligible: Literal[False] = False

    schema_version: ClassVar[int] = REQUEST_UNIVERSE_FINAL_SCHEMA_VERSION
    kind: ClassVar[str] = "request_universe_v1"

    def __post_init__(self) -> None:
        for field_name in (
            "authority_generation_sha256",
            "checkpoint_identity_sha256",
            "request_closure_receipt_sha256",
            "w2_authority_identity_sha256",
            "temporal_field_denominator_sha256",
            "committed_observation_generation_sha256",
            "finalization_source_sha256",
            "candidate_source_sha256",
            "candidate_generation_sha256",
            "candidate_independent_proof_sha256",
            "source_admission_sha256",
            "logical_call_inventory_sha256",
            "terminal_classification_inventory_sha256",
            "shard_inventory_sha256",
        ):
            _require_sha256(getattr(self, field_name), field_name=field_name)
        if self.parent_request_universe_sha256 is not None:
            _require_sha256(
                self.parent_request_universe_sha256,
                field_name="parent_request_universe_sha256",
            )
        calls = _require_sorted_unique(
            self.logical_calls,
            field_name="logical_calls",
            key=lambda item: item.physical_call_id,
            maximum=_MAX_CALLS,
            allow_empty=False,
        )
        classifications = _require_sorted_unique(
            self.terminal_classifications,
            field_name="terminal_classifications",
            key=lambda item: item.physical_call_id,
            maximum=_MAX_CALLS,
            allow_empty=False,
        )
        shards = _require_sorted_unique(
            self.shards,
            field_name="shards",
            key=lambda item: item.shard_id,
            maximum=_MAX_CALLS,
            allow_empty=False,
        )
        expected = {
            "logical_call_inventory_sha256": canonical_request_universe_sha256(
                [item.to_dict() for item in calls]
            ),
            "terminal_classification_inventory_sha256": (
                canonical_request_universe_sha256([item.to_dict() for item in classifications])
            ),
            "shard_inventory_sha256": canonical_request_universe_sha256(
                [item.to_dict() for item in shards]
            ),
        }
        if any(getattr(self, key) != value for key, value in expected.items()):
            raise RequestUniverseCandidateContractError(
                "final request-universe inventory digest differs"
            )
        authority = self.authority_generation_sha256
        observation_generation = self.committed_observation_generation_sha256
        if any(item.authority_generation_sha256 != authority for item in calls):
            raise RequestUniverseCandidateContractError("final logical call is foreign")
        call_by_id = {item.physical_call_id: item for item in calls}
        if any(
            item.authority_generation_sha256 != authority
            or item.committed_observation_generation_sha256 != observation_generation
            or item.request_scope_sha256
            != call_by_id.get(item.physical_call_id, item).request_scope_sha256
            for item in classifications
        ):
            raise RequestUniverseCandidateContractError(
                "final classification is missing, stale, or foreign"
            )
        classification_ids = {item.physical_call_id for item in classifications}
        if classification_ids != set(call_by_id):
            raise RequestUniverseCandidateContractError(
                "final classifications differ from the logical request denominator"
            )
        if any(item.authority_generation_sha256 != authority for item in shards):
            raise RequestUniverseCandidateContractError("final shard is foreign")
        partition = [
            physical_call_id for shard in shards for physical_call_id in shard.physical_call_ids
        ]
        if len(partition) != len(set(partition)) or set(partition) != set(call_by_id):
            raise RequestUniverseCandidateContractError(
                "final shard partition overlaps, omits, or invents logical requests"
            )
        if type(self.primary_empty_delta_receipt) is not RequestUniverseEmptyDeltaReceiptV1:
            raise RequestUniverseCandidateContractError(
                "final universe lacks its primary empty-delta receipt"
            )
        receipt = self.primary_empty_delta_receipt
        if (
            receipt.authority_generation_sha256 != self.authority_generation_sha256
            or receipt.finalization_source_sha256 != self.finalization_source_sha256
            or receipt.committed_observation_generation_sha256
            != self.committed_observation_generation_sha256
            or receipt.logical_call_inventory_sha256 != self.logical_call_inventory_sha256
            or receipt.logical_call_count != len(calls)
        ):
            raise RequestUniverseCandidateContractError("primary empty-delta receipt is foreign")
        if (
            self.exact_request_denominator is not True
            or self.terminal_classification_complete is not True
            or self.shard_partition_exact is not True
            or self.least_fixed_point_proven is not True
            or self.terminal is not True
            or self.release_eligible is not False
        ):
            raise RequestUniverseCandidateContractError(
                "final request universe has invalid terminal flags"
            )
        object.__setattr__(self, "logical_calls", calls)
        object.__setattr__(self, "terminal_classifications", classifications)
        object.__setattr__(self, "shards", shards)

    @property
    def canonical_bytes(self) -> bytes:
        return canonical_request_universe_json_bytes(self.to_dict())

    @property
    def identity_sha256(self) -> str:
        return hashlib.sha256(self.canonical_bytes).hexdigest()

    def to_dict(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "kind": self.kind,
            **{
                field_name: getattr(self, field_name)
                for field_name in (
                    "authority_generation_sha256",
                    "checkpoint_identity_sha256",
                    "request_closure_receipt_sha256",
                    "w2_authority_identity_sha256",
                    "temporal_field_denominator_sha256",
                    "committed_observation_generation_sha256",
                    "finalization_source_sha256",
                    "candidate_source_sha256",
                    "candidate_generation_sha256",
                    "candidate_independent_proof_sha256",
                    "source_admission_sha256",
                    "logical_call_inventory_sha256",
                    "terminal_classification_inventory_sha256",
                    "shard_inventory_sha256",
                    "parent_request_universe_sha256",
                    "generation_ordinal",
                    "exact_request_denominator",
                    "terminal_classification_complete",
                    "shard_partition_exact",
                    "least_fixed_point_proven",
                    "terminal",
                    "release_eligible",
                )
            },
            "logical_call_count": len(self.logical_calls),
            "terminal_classification_count": len(self.terminal_classifications),
            "shard_count": len(self.shards),
            "logical_calls": [item.to_dict() for item in self.logical_calls],
            "terminal_classifications": [item.to_dict() for item in self.terminal_classifications],
            "shards": [item.to_dict() for item in self.shards],
            "primary_empty_delta_receipt": self.primary_empty_delta_receipt.to_dict(),
        }

    @classmethod
    def from_dict(cls, payload: Mapping[str, object]) -> Self:
        inventory_fields = {
            "authority_generation_sha256",
            "checkpoint_identity_sha256",
            "request_closure_receipt_sha256",
            "w2_authority_identity_sha256",
            "temporal_field_denominator_sha256",
            "committed_observation_generation_sha256",
            "finalization_source_sha256",
            "candidate_source_sha256",
            "candidate_generation_sha256",
            "candidate_independent_proof_sha256",
            "source_admission_sha256",
            "logical_call_inventory_sha256",
            "terminal_classification_inventory_sha256",
            "shard_inventory_sha256",
            "parent_request_universe_sha256",
            "generation_ordinal",
            "exact_request_denominator",
            "terminal_classification_complete",
            "shard_partition_exact",
            "least_fixed_point_proven",
            "terminal",
            "release_eligible",
        }
        expected = frozenset(
            {
                "schema_version",
                "kind",
                *inventory_fields,
                "logical_call_count",
                "terminal_classification_count",
                "shard_count",
                "logical_calls",
                "terminal_classifications",
                "shards",
                "primary_empty_delta_receipt",
            }
        )
        _require_exact_keys(payload, expected=expected, label="request universe")
        _parse_schema(payload, kind=cls.kind, label="request universe")
        calls = tuple(
            LogicalRequestCallV1.from_dict(_mapping(item, field_name="logical call"))
            for item in _list(payload["logical_calls"], field_name="logical_calls")
        )
        classifications = tuple(
            TerminalRequestClassificationV1.from_dict(
                _mapping(item, field_name="terminal classification")
            )
            for item in _list(
                payload["terminal_classifications"],
                field_name="terminal_classifications",
            )
        )
        shards = tuple(
            RequestUniverseShardV1.from_dict(_mapping(item, field_name="shard"))
            for item in _list(payload["shards"], field_name="shards")
        )
        counts = {
            "logical_call_count": len(calls),
            "terminal_classification_count": len(classifications),
            "shard_count": len(shards),
        }
        if any(
            type(payload[key]) is not int or payload[key] != value for key, value in counts.items()
        ):
            raise RequestUniverseCandidateContractError(
                "request-universe count differs from its inventory"
            )
        return cls(
            **cast("Any", {key: payload[key] for key in inventory_fields}),
            logical_calls=calls,
            terminal_classifications=classifications,
            shards=shards,
            primary_empty_delta_receipt=RequestUniverseEmptyDeltaReceiptV1.from_dict(
                _mapping(
                    payload["primary_empty_delta_receipt"],
                    field_name="primary empty-delta receipt",
                )
            ),
        )

    @classmethod
    def from_canonical_bytes(cls, raw: bytes) -> Self:
        result = cls.from_dict(_decode_canonical_mapping(raw))
        if result.canonical_bytes != raw:
            raise RequestUniverseCandidateContractError(
                "request universe is not exact canonical JSON"
            )
        return result


def compile_request_universe_v1(
    source: RequestUniverseFinalizationSourceV1,
) -> RequestUniverseV1:
    """Compile a final universe only from already committed local evidence."""

    if type(source) is not RequestUniverseFinalizationSourceV1:
        raise RequestUniverseCandidateContractError(
            "final compiler requires an exact finalization source DTO"
        )
    strict_source = RequestUniverseFinalizationSourceV1.from_canonical_bytes(
        canonical_request_universe_json_bytes(source.to_dict())
    )
    if strict_source != source:
        raise RequestUniverseCandidateContractError(
            "finalization source differs after strict reconstruction"
        )
    receipt = RequestUniverseEmptyDeltaReceiptV1.build(source)
    calls = source.logical_calls
    classifications = source.terminal_classifications
    shards = source.shards
    return RequestUniverseV1(
        authority_generation_sha256=source.authority_generation_sha256,
        checkpoint_identity_sha256=source.checkpoint_identity_sha256,
        request_closure_receipt_sha256=source.request_closure_receipt_sha256,
        w2_authority_identity_sha256=source.w2_authority_identity_sha256,
        temporal_field_denominator_sha256=source.temporal_field_denominator_sha256,
        committed_observation_generation_sha256=(source.committed_observation_generation_sha256),
        finalization_source_sha256=source.source_inputs_sha256,
        candidate_source_sha256=source.candidate_source_sha256,
        candidate_generation_sha256=source.candidate_generation_sha256,
        candidate_independent_proof_sha256=(source.candidate_independent_proof_sha256),
        source_admission_sha256=source.source_admission_sha256,
        logical_calls=calls,
        terminal_classifications=classifications,
        shards=shards,
        logical_call_inventory_sha256=canonical_request_universe_sha256(
            [item.to_dict() for item in calls]
        ),
        terminal_classification_inventory_sha256=canonical_request_universe_sha256(
            [item.to_dict() for item in classifications]
        ),
        shard_inventory_sha256=canonical_request_universe_sha256(
            [item.to_dict() for item in shards]
        ),
        primary_empty_delta_receipt=receipt,
        parent_request_universe_sha256=source.parent_request_universe_sha256,
        generation_ordinal=source.generation_ordinal,
    )
