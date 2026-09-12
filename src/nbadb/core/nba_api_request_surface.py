"""Compact, exact-pin request-surface authority for :mod:`nba_api`.

The checked-in runtime contract owns endpoint declarations.  This module adds
the missing request-domain layer without expanding the historical Cartesian
request universe: every declared parameter receives one deterministic domain
kind, coverage policy, and semantic dependency.  Runtime planners must still
bind those compact domains to a versioned scope and prove a least fixed point.

The generated JSON resource stores every canonical parameter-occurrence tuple,
its typed-domain receipt, and the acyclic constraint graph alongside exact
input/output digests and counts.  Loading it rebuilds the full surface from the
pinned runtime contract and installed static helper modules, so an omitted,
replaced, or newly added parameter or helper fails closed.
"""

from __future__ import annotations

import ast
import hashlib
import importlib
import inspect
import json
import math
import re
import textwrap
from collections import Counter, defaultdict
from collections.abc import Mapping
from dataclasses import dataclass, replace
from dataclasses import field as dataclass_field
from datetime import datetime
from functools import lru_cache
from importlib import resources
from typing import TYPE_CHECKING, Any, Final, Literal, cast
from urllib.parse import quote, urlencode

from nbadb.core.nba_api_competition import (
    CompetitionAuthority,
    NbaApiCompetitionError,
    load_pinned_competition_payload,
    pinned_competition_authority,
)
from nbadb.core.nba_api_runtime_contract import (
    load_pinned_runtime_contract_payload,
    stats_endpoint_url_template,
    stats_parameter_finite_values,
)
from nbadb.core.nba_api_terminal_state import (
    INCOMPLETE_REQUEST_STATES,
    RELEASE_TERMINAL_REQUEST_STATES,
    REQUEST_ACCOUNTING_STATES,
    NbaApiTerminalStateError,
    RequestAccountingState,
    TerminalRequestBinding,
    TypedUpstreamUnavailableEvidence,
    is_release_terminal_request_state,
    load_pinned_terminal_state_payload,
)

if TYPE_CHECKING:
    from collections.abc import Sequence
    from pathlib import Path

REQUEST_SURFACE_SCHEMA_VERSION = 3
REQUEST_SURFACE_RESOURCE = "nba_api_request_surface_v1_11_4.json"
REQUEST_SURFACE_DERIVATION_POLICY_VERSION = 6

SourceFamily = Literal["stats", "live"]
DomainKind = Literal[
    "discovered_identifier",
    "temporal_scope",
    "league_scope",
    "bounded_numeric_scope",
    "nullable_filter_scope",
    "explicit_value_scope",
]
CoveragePolicy = Literal[
    "enumerate_discovered_values",
    "enumerate_scope_values",
    "enumerate_explicit_values",
]
StaticHelperKind = Literal["dataset_projection", "filtered_projection", "finder_alias"]
StaticScopeStatus = Literal["in_scope", "out_of_scope_with_evidence"]
ParameterLocation = Literal["query", "path"]
ParameterValueType = Literal["str", "int", "float", "bool"]
ParameterDefaultAuthority = Literal[
    "provider_literal_or_required_v1",
    "provider_dynamic_default_expression_v1",
]
ParameterConstraintKind = Literal[
    "authorized_by",
    "lower_lte_upper_if_both_present",
]
SemanticRole = Literal[
    "discovery_key",
    "scope_axis",
    "bounded_control",
    "finite_selector",
    "neutral_filter",
    "pagination_cursor",
]
DomainEvidenceKind = Literal[
    "discovered_inventory",
    "scope_inventory",
    "bounded_interval",
    "provider_finite_values",
    "explicit_scope_inventory",
    "neutral_value",
    "pagination_until_terminal",
]
ExpansionEvidenceKind = Literal[
    "seed",
    "scope_expansion",
    "discovered_identifiers",
    "pagination_expansion",
    "fixed_point",
]
type TerminalRequestState = RequestAccountingState
TerminalEvidenceKind = Literal[
    "receipt_bound_provider_response",
    "typed_upstream_unavailable_evidence",
    "implementation_or_modeled_contract_gap",
    "transport_timeout_retry_vpn_or_infrastructure_failure",
    "parser_or_response_contract_failure",
    "budget_cap_policy_or_scheduling_exhaustion",
    "classification_unknown",
]
type EvidenceValue = str | int | float | bool | None

_DOMAIN_KINDS = frozenset(
    {
        "discovered_identifier",
        "temporal_scope",
        "league_scope",
        "bounded_numeric_scope",
        "nullable_filter_scope",
        "explicit_value_scope",
    }
)
_COVERAGE_POLICIES = frozenset(
    {
        "enumerate_discovered_values",
        "enumerate_scope_values",
        "enumerate_explicit_values",
    }
)
_DEPENDENCY_IDS = frozenset(
    {
        "explicit_scope_manifest",
        "game_date_index",
        "game_event_index",
        "league_scope",
        "lineup_group_universe",
        "playoff_series_universe",
        "season_player_universe",
        "season_scope",
        "season_team_universe",
        "season_type_scope",
    }
)
_RELEASE_TERMINAL_REQUEST_STATES: Final = RELEASE_TERMINAL_REQUEST_STATES
_INCOMPLETE_REQUEST_STATES: Final = INCOMPLETE_REQUEST_STATES
_REQUEST_ACCOUNTING_STATES: Final = REQUEST_ACCOUNTING_STATES
_TERMINAL_EVIDENCE_KINDS: Final[dict[TerminalRequestState, TerminalEvidenceKind]] = {
    "success_nonempty": "receipt_bound_provider_response",
    "success_empty": "receipt_bound_provider_response",
    "upstream_unavailable": "typed_upstream_unavailable_evidence",
    "contract_blocked": "implementation_or_modeled_contract_gap",
    "transient_failed": "transport_timeout_retry_vpn_or_infrastructure_failure",
    "response_contract_failed": "parser_or_response_contract_failure",
    "unattempted": "budget_cap_policy_or_scheduling_exhaustion",
    "unclassified": "classification_unknown",
}
_SHA256_RE = re.compile(r"[0-9a-f]{64}")
_SAFE_ID_RE = re.compile(r"[A-Za-z0-9_][A-Za-z0-9_.:-]{0,255}")
_IDENTIFIER_RE = re.compile(
    r"(?:^|_)(?:game|event|player|team|group|series)_id"
    r"(?:s|[1-5]|_list)?(?:_nullable)?$"
)
_PERSON_IDENTIFIER_RE = re.compile(r"^person[12]_id$")
_METRIC_FILTER_RE = re.compile(r"^(?:gt|lt|eq|wrs|btr)_")
_TEMPORAL_RE = re.compile(
    r"(?:^season(?:_|$)|_season(?:_|$)|season_type|season_year|draft_year|rookie_year)"
)

_NUMERIC_TEXT_RE = re.compile(r"[+-]?(?:[0-9]+(?:\.[0-9]*)?|\.[0-9]+)")
_IDENTIFIER_VALUE_RE = re.compile(r"[0-9]+")
_IDENTIFIER_LIST_VALUE_RE = re.compile(r"[0-9]+(?:,[0-9]+)*")
_PATH_TOKEN_RE = re.compile(r"\{(?P<name>[A-Za-z_][A-Za-z0-9_]*)\}")
_SEASON_LABEL_RE = re.compile(r"(?P<start>[0-9]{4})-(?P<end>[0-9]{2})")
_SEASON_ID_RE = re.compile(r"[0-9]{5}")
_YEAR_RE = re.compile(r"[0-9]{4}")
_LEAGUE_ID_RE = re.compile(r"[0-9]{2}")
_DATE_FORMATS = ("%Y-%m-%d", "%m/%d/%Y")

_FINITE_TEMPORAL_PARAMETERS = frozenset(
    {
        "person1_season_type",
        "person2_season_type",
        "season_segment_nullable",
        "season_type",
        "season_type_all_star",
        "season_type_all_star_nullable",
        "season_type_nullable",
        "season_type_playoffs",
    }
)

_BOUNDED_NUMERIC_RANGES: dict[str, tuple[float, float]] = {
    "counter": (0, 2_147_483_647),
    "day_offset": (-36_600, 36_600),
    "end_period": (0, 20),
    "end_period_nullable": (0, 20),
    "end_range": (0, 1_000_000),
    "end_range_nullable": (0, 1_000_000),
    "group_quantity": (1, 5),
    "last_n_games": (0, 2_147_483_647),
    "last_n_games_nullable": (0, 2_147_483_647),
    "min_games_nullable": (0, 5_000),
    "minutes_min": (0, 60),
    "month": (0, 12),
    "month_nullable": (0, 12),
    "number_of_games": (0, 2_147_483_647),
    "overall_pick_nullable": (0, 1_000),
    "period": (0, 20),
    "period_nullable": (0, 20),
    "point_diff": (-200, 200),
    "point_diff_nullable": (-200, 200),
    "range_type": (0, 5),
    "range_type_nullable": (0, 5),
    "round_num_nullable": (0, 100),
    "round_pick_nullable": (0, 1_000),
    "start_period": (0, 20),
    "start_period_nullable": (0, 20),
    "start_range": (0, 1_000_000),
    "start_range_nullable": (0, 1_000_000),
    "topx": (1, 10_000),
    "topx_nullable": (1, 10_000),
}

_BOUNDED_NUMERIC_PARAMETERS = frozenset(
    {
        "counter",
        "day_offset",
        "end_period",
        "end_period_nullable",
        "end_range",
        "end_range_nullable",
        "group_quantity",
        "last_n_games",
        "last_n_games_nullable",
        "min_games_nullable",
        "minutes_min",
        "month",
        "month_nullable",
        "number_of_games",
        "overall_pick_nullable",
        "period",
        "period_nullable",
        "point_diff",
        "point_diff_nullable",
        "range_type",
        "range_type_nullable",
        "round_num_nullable",
        "round_pick_nullable",
        "start_period",
        "start_period_nullable",
        "start_range",
        "start_range_nullable",
        "topx",
        "topx_nullable",
    }
)

# These exact-pin names have neither an identifier/temporal/numeric shape nor a
# provider-declared finite value inventory.  A planner must bind explicit scope
# values; none may silently fall back to an arbitrary default or Cartesian fanout.
_EXPLICIT_VALUE_PARAMETERS = frozenset(
    {
        "active_players",
        "ahead_behind",
        "clutch_time",
        "college",
        "context_measure_detailed",
        "context_measure_simple",
        "defense_category",
        "direction",
        "distance_range",
        "game_scope_detailed",
        "measure_type_detailed",
        "measure_type_detailed_defense",
        "measure_type_simple",
        "pace_adjust",
        "per_mode36",
        "per_mode48",
        "per_mode_detailed",
        "per_mode_simple",
        "per_mode_time",
        "player_or_team",
        "player_or_team_abbreviation",
        "player_scope",
        "plus_minus",
        "pt_measure_type",
        "run_type",
        "rank",
        "scope",
        "section",
        "sorter",
        "stat",
        "stat_category",
        "stat_category_abbreviation",
        "stat_type",
        "todays_opponent",
        "todays_players",
        "is_only_current_season",
    }
)

_PARAMETER_ORDER_CONSTRAINTS = (
    ("date_from_nullable", "date_to_nullable"),
    ("start_period", "end_period"),
    ("start_period_nullable", "end_period_nullable"),
    ("start_range", "end_range"),
    ("start_range_nullable", "end_range_nullable"),
)

_DYNAMIC_DEFAULT_EXPRESSION_TYPES: dict[str, ParameterValueType] = {
    "GameDate.default": "str",
    "Season.default": "str",
    "SeasonAll.default": "str",
    "SeasonAll_Time.default": "str",
    "SeasonID.default": "str",
    "SeasonYear.default": "int",
}
_EXPECTED_DYNAMIC_DEFAULT_EXPRESSION_COUNTS: dict[str, int] = {
    "GameDate.default": 2,
    "Season.default": 77,
    "SeasonAll.default": 1,
    "SeasonAll_Time.default": 1,
    "SeasonID.default": 2,
    "SeasonYear.default": 7,
}
_DYNAMIC_DEFAULT_CLASS_NAMES = frozenset(
    expression.partition(".")[0] for expression in _DYNAMIC_DEFAULT_EXPRESSION_TYPES
)


class NbaApiRequestSurfaceError(ValueError):
    """Fail-closed request-surface or closure-contract violation."""


@lru_cache(maxsize=1)
def _competition_authority_binding() -> tuple[CompetitionAuthority, str]:
    try:
        authority = pinned_competition_authority()
        payload = load_pinned_competition_payload()
    except NbaApiCompetitionError as exc:
        raise NbaApiRequestSurfaceError("pinned competition authority is invalid") from exc
    payload_sha256 = payload.get("payload_sha256")
    if not isinstance(payload_sha256, str) or _SHA256_RE.fullmatch(payload_sha256) is None:
        raise NbaApiRequestSurfaceError("pinned competition authority payload digest is invalid")
    return authority, payload_sha256


@lru_cache(maxsize=1)
def _terminal_policy_binding() -> tuple[str, tuple[tuple[str, str], ...]]:
    try:
        payload = load_pinned_terminal_state_payload()
    except NbaApiTerminalStateError as exc:
        raise NbaApiRequestSurfaceError("pinned terminal-state policy is invalid") from exc
    terminal_policy_sha256 = payload.get("terminal_policy_sha256")
    if (
        not isinstance(terminal_policy_sha256, str)
        or _SHA256_RE.fullmatch(terminal_policy_sha256) is None
    ):
        raise NbaApiRequestSurfaceError("terminal-state policy digest is invalid")
    release_states = payload.get("release_terminal_request_states")
    incomplete_states = payload.get("incomplete_request_states")
    wire_states = payload.get("wire_request_states")
    if (
        not isinstance(release_states, (list, tuple))
        or not isinstance(incomplete_states, (list, tuple))
        or not isinstance(wire_states, (list, tuple))
    ):
        raise NbaApiRequestSurfaceError("terminal-state policy partition is inconsistent")
    if (
        tuple(release_states) != _RELEASE_TERMINAL_REQUEST_STATES
        or tuple(incomplete_states) != _INCOMPLETE_REQUEST_STATES
        or tuple(wire_states) != _REQUEST_ACCOUNTING_STATES
    ):
        raise NbaApiRequestSurfaceError("terminal-state policy partition is inconsistent")
    contracts = payload.get("accounting_state_contracts")
    if not isinstance(contracts, list):
        raise NbaApiRequestSurfaceError("terminal-state policy contracts are absent")
    observed_kinds = tuple(
        (str(contract.get("state")), str(contract.get("evidence_kind")))
        for contract in contracts
        if isinstance(contract, dict)
    )
    expected_kinds = tuple(
        (state, _TERMINAL_EVIDENCE_KINDS[state]) for state in _REQUEST_ACCOUNTING_STATES
    )
    if observed_kinds != expected_kinds:
        raise NbaApiRequestSurfaceError("terminal evidence-kind vocabulary is inconsistent")
    return terminal_policy_sha256, observed_kinds


def _terminal_policy_sha256() -> str:
    return _terminal_policy_binding()[0]


def _reserved_authorities() -> dict[str, str]:
    return {
        "league_finite_values": _competition_authority_binding()[1],
        "release_terminal_state": _terminal_policy_sha256(),
    }


def _canonical_json_bytes(value: object) -> bytes:
    try:
        return json.dumps(
            value,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
            allow_nan=False,
        ).encode("utf-8")
    except (TypeError, ValueError) as exc:
        raise NbaApiRequestSurfaceError("request-surface value is not canonical JSON") from exc


def _sha256(value: object) -> str:
    return hashlib.sha256(_canonical_json_bytes(value)).hexdigest()


def _require_sha256(field: str, value: object) -> str:
    if not isinstance(value, str) or _SHA256_RE.fullmatch(value) is None:
        raise NbaApiRequestSurfaceError(f"{field} must be a canonical SHA-256")
    return value


def _require_safe_id(field: str, value: object) -> str:
    if not isinstance(value, str) or _SAFE_ID_RE.fullmatch(value) is None:
        raise NbaApiRequestSurfaceError(f"{field} must be a safe nonempty identifier")
    return value


def _require_nonnegative_integer(field: str, value: object) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise NbaApiRequestSurfaceError(f"{field} must be a non-negative integer")
    return value


def _canonical_request_value(value: object) -> object:
    if value is None or isinstance(value, str | bool | int):
        return value
    if isinstance(value, float):
        if not math.isfinite(value):
            raise NbaApiRequestSurfaceError("request values must be finite")
        return value
    if isinstance(value, list | tuple):
        return [_canonical_request_value(item) for item in value]
    if isinstance(value, Mapping):
        if any(not isinstance(key, str) or not key for key in value):
            raise NbaApiRequestSurfaceError("request-value object keys must be nonempty strings")
        return {
            key: _canonical_request_value(item)
            for key, item in sorted(value.items(), key=lambda pair: pair[0])
        }
    raise NbaApiRequestSurfaceError("request values must be JSON-compatible")


def _canonical_scalar(value: object, *, field: str) -> EvidenceValue:
    if value is None or type(value) in {str, bool, int}:
        return cast("EvidenceValue", value)
    if type(value) is float and math.isfinite(cast("float", value)):
        return cast("float", value)
    raise NbaApiRequestSurfaceError(f"{field} must be a finite JSON scalar")


def _canonical_scalar_tuple(
    values: object,
    *,
    field: str,
    allow_empty: bool = False,
) -> tuple[EvidenceValue, ...]:
    if type(values) is not tuple:
        raise NbaApiRequestSurfaceError(f"{field} must be an exact tuple")
    result = tuple(_canonical_scalar(value, field=field) for value in values)
    encoded = tuple(_canonical_json_bytes(value) for value in result)
    if (not allow_empty and not result) or encoded != tuple(sorted(set(encoded))):
        raise NbaApiRequestSurfaceError(
            f"{field} must be canonical-byte sorted, unique, and"
            f" {'possibly empty' if allow_empty else 'nonempty'}"
        )
    return result


def _sorted_scalar_values(values: object) -> tuple[EvidenceValue, ...]:
    by_bytes: dict[bytes, EvidenceValue] = {}
    for value in cast("list[object] | tuple[object, ...] | set[object]", values):
        scalar = _canonical_scalar(value, field="evidence value")
        by_bytes[_canonical_json_bytes(scalar)] = scalar
    return tuple(by_bytes[key] for key in sorted(by_bytes))


def _parameter_occurrence_id(
    source_family: SourceFamily,
    endpoint_id: str,
    ordinal: int,
    name: str,
) -> str:
    """Return the canonical identity of one constructor/wire occurrence."""

    return f"parameter:{source_family}:{endpoint_id}:{ordinal:04d}:{name}"


def _constructor_default_expressions(
    module_name: str,
    class_name: str,
    expected_parameters: Sequence[str],
) -> dict[str, str | None]:
    """Return exact constructor-default AST expressions for declared parameters."""

    try:
        module = importlib.import_module(module_name)
        runtime_class = getattr(module, class_name)
        source = textwrap.dedent(inspect.getsource(runtime_class.__init__))
        tree = ast.parse(source)
    except (AttributeError, ImportError, IndentationError, OSError, SyntaxError, TypeError) as exc:
        raise NbaApiRequestSurfaceError(
            "provider constructor source is unavailable for default authority"
        ) from exc
    functions = [
        node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name == "__init__"
    ]
    if len(functions) != 1:
        raise NbaApiRequestSurfaceError(
            "provider constructor source has ambiguous default authority"
        )
    function = functions[0]
    positional = (*function.args.posonlyargs, *function.args.args)
    positional_defaults: dict[str, ast.expr | None] = dict.fromkeys(
        (argument.arg for argument in positional),
        None,
    )
    positional_with_defaults = (
        positional[-len(function.args.defaults) :] if function.args.defaults else ()
    )
    for argument, default in zip(
        positional_with_defaults,
        function.args.defaults,
        strict=True,
    ):
        positional_defaults[argument.arg] = default
    keyword_defaults = {
        argument.arg: default
        for argument, default in zip(
            function.args.kwonlyargs,
            function.args.kw_defaults,
            strict=True,
        )
    }
    defaults = {**positional_defaults, **keyword_defaults}
    if any(name not in defaults for name in expected_parameters):
        raise NbaApiRequestSurfaceError(
            "provider constructor parameters differ from default authority input"
        )
    return {
        name: ast.unparse(default) if (default := defaults[name]) is not None else None
        for name in expected_parameters
    }


def _normalize_parameter_default(
    *,
    source_expression: str | None,
    has_default: bool,
    raw_default: EvidenceValue,
    raw_default_type: str | None = None,
) -> tuple[EvidenceValue, ParameterDefaultAuthority, str | None]:
    """Replace an ambient provider default with its stable source expression."""

    if source_expression in _DYNAMIC_DEFAULT_EXPRESSION_TYPES:
        expected_type = _DYNAMIC_DEFAULT_EXPRESSION_TYPES[source_expression]
        observed_type = raw_default_type or type(raw_default).__name__
        if not has_default or observed_type != expected_type:
            raise NbaApiRequestSurfaceError(
                "dynamic provider default differs from its source expression type"
            )
        return None, "provider_dynamic_default_expression_v1", source_expression
    expression_owner = source_expression.partition(".")[0] if source_expression else None
    if expression_owner in _DYNAMIC_DEFAULT_CLASS_NAMES:
        raise NbaApiRequestSurfaceError(
            "provider dynamic default uses an unsupported source expression"
        )
    return raw_default, "provider_literal_or_required_v1", None


def _parameter_source_signature_payload(
    *,
    occurrence_id: str,
    ordinal: int,
    name: str,
    query_name: str,
    location: ParameterLocation,
    required: bool,
    nullable: bool,
    has_default: bool,
    default: EvidenceValue,
    default_authority: ParameterDefaultAuthority,
    default_expression: str | None,
) -> dict[str, object]:
    return {
        "schema_version": 1,
        "kind": "nba_api_parameter_source_signature",
        "occurrence_id": occurrence_id,
        "ordinal": ordinal,
        "name": name,
        "query_name": query_name,
        "location": location,
        "required": required,
        "nullable": nullable,
        "has_default": has_default,
        "default": default,
        "default_authority": default_authority,
        "default_expression": default_expression,
        "default_value_type": (
            _DYNAMIC_DEFAULT_EXPRESSION_TYPES[default_expression]
            if default_authority == "provider_dynamic_default_expression_v1"
            and default_expression is not None
            else type(default).__name__
            if has_default
            else None
        ),
    }


@dataclass(frozen=True, slots=True)
class ParameterDomainEvidence:
    """Concrete, independently hashable evidence for one parameter domain."""

    evidence_kind: DomainEvidenceKind
    authority: str
    dependencies: tuple[str, ...] = ()
    finite_values: tuple[EvidenceValue, ...] = ()
    minimum: float | int | None = None
    maximum: float | int | None = None
    neutral_value_present: bool = False
    neutral_value: EvidenceValue = None
    terminal_condition: str | None = None

    def __post_init__(self) -> None:
        if self.evidence_kind not in {
            "discovered_inventory",
            "scope_inventory",
            "bounded_interval",
            "provider_finite_values",
            "explicit_scope_inventory",
            "neutral_value",
            "pagination_until_terminal",
        }:
            raise NbaApiRequestSurfaceError("parameter evidence_kind is unsupported")
        _require_safe_id("parameter evidence authority", self.authority)
        if (
            type(self.dependencies) is not tuple
            or self.dependencies != tuple(sorted(set(self.dependencies)))
            or any(item not in _DEPENDENCY_IDS for item in self.dependencies)
        ):
            raise NbaApiRequestSurfaceError(
                "parameter evidence dependencies must be sorted, unique, and known"
            )
        _canonical_scalar_tuple(
            self.finite_values,
            field="parameter evidence finite_values",
            allow_empty=True,
        )
        for label, value in (("minimum", self.minimum), ("maximum", self.maximum)):
            if value is not None and (
                isinstance(value, bool)
                or not isinstance(value, int | float)
                or not math.isfinite(value)
            ):
                raise NbaApiRequestSurfaceError(f"parameter evidence {label} is invalid")
        if self.minimum is not None and self.maximum is not None and self.minimum > self.maximum:
            raise NbaApiRequestSurfaceError("parameter evidence interval is inverted")
        if type(self.neutral_value_present) is not bool:
            raise NbaApiRequestSurfaceError("neutral_value_present must be a boolean")
        _canonical_scalar(self.neutral_value, field="parameter evidence neutral_value")
        if not self.neutral_value_present and self.neutral_value is not None:
            raise NbaApiRequestSurfaceError("absent neutral evidence must use null placeholder")
        if self.terminal_condition is not None and (
            not isinstance(self.terminal_condition, str)
            or _SAFE_ID_RE.fullmatch(self.terminal_condition) is None
        ):
            raise NbaApiRequestSurfaceError("parameter evidence terminal_condition is invalid")

        if self.evidence_kind == "bounded_interval":
            if self.minimum is None or self.maximum is None:
                raise NbaApiRequestSurfaceError("bounded evidence requires both interval endpoints")
        elif self.minimum is not None or self.maximum is not None:
            raise NbaApiRequestSurfaceError("only bounded evidence may declare an interval")
        if self.evidence_kind == "provider_finite_values" and not self.finite_values:
            raise NbaApiRequestSurfaceError("finite provider evidence requires concrete values")
        if self.evidence_kind != "provider_finite_values" and self.finite_values:
            raise NbaApiRequestSurfaceError("only finite provider evidence may declare values")
        if self.evidence_kind == "neutral_value" and not self.neutral_value_present:
            raise NbaApiRequestSurfaceError("neutral-filter evidence requires a concrete value")
        if self.evidence_kind != "neutral_value" and self.neutral_value_present:
            raise NbaApiRequestSurfaceError("only neutral evidence may declare a neutral value")
        if self.evidence_kind == "pagination_until_terminal":
            if self.terminal_condition != "contiguous_from_zero_with_terminal_page":
                raise NbaApiRequestSurfaceError("pagination evidence has no fail-closed stop rule")
        elif self.terminal_condition is not None:
            raise NbaApiRequestSurfaceError(
                "only pagination evidence may declare a terminal condition"
            )

    @property
    def evidence_sha256(self) -> str:
        return _sha256(_domain_evidence_payload(self))


def _typed_parameter_domain_payload(
    *,
    occurrence_id: str,
    source_signature_sha256: str,
    value_types: tuple[ParameterValueType, ...],
    pattern: str | None,
    domain_kind: DomainKind,
    coverage_policy: CoveragePolicy,
    semantic_role: SemanticRole,
    dependencies: tuple[str, ...],
    evidence: tuple[ParameterDomainEvidence, ...],
) -> dict[str, object]:
    return {
        "schema_version": 1,
        "kind": "nba_api_typed_parameter_occurrence_domain",
        "occurrence_id": occurrence_id,
        "source_signature_sha256": source_signature_sha256,
        "value_types": list(value_types),
        "pattern": pattern,
        "domain_kind": domain_kind,
        "coverage_policy": coverage_policy,
        "semantic_role": semantic_role,
        "dependencies": list(dependencies),
        "evidence_sha256": [item.evidence_sha256 for item in evidence],
    }


@dataclass(frozen=True, slots=True)
class ParameterDomainDisposition:
    """One exact endpoint parameter and its mandatory domain evidence."""

    ordinal: int
    occurrence_id: str
    name: str
    query_name: str
    location: ParameterLocation
    required: bool
    nullable: bool
    has_default: bool
    default: str | int | float | bool | None
    default_authority: ParameterDefaultAuthority
    default_expression: str | None
    value_types: tuple[ParameterValueType, ...]
    pattern: str | None
    domain_kind: DomainKind
    coverage_policy: CoveragePolicy
    semantic_role: SemanticRole
    dependencies: tuple[str, ...]
    evidence: tuple[ParameterDomainEvidence, ...]
    source_signature_sha256: str
    typed_domain_sha256: str

    def __post_init__(self) -> None:
        _require_nonnegative_integer("ordinal", self.ordinal)
        _require_safe_id("parameter occurrence_id", self.occurrence_id)
        _require_safe_id("parameter name", self.name)
        _require_safe_id("parameter query_name", self.query_name)
        if self.location not in {"query", "path"}:
            raise NbaApiRequestSurfaceError("parameter location is unsupported")
        for field in ("required", "nullable", "has_default"):
            if type(getattr(self, field)) is not bool:
                raise NbaApiRequestSurfaceError(f"{field} must be a boolean")
        if self.required and self.has_default:
            raise NbaApiRequestSurfaceError("required parameters cannot declare defaults")
        if not self.has_default and self.default is not None:
            raise NbaApiRequestSurfaceError("absent defaults must use a null placeholder")
        if self.default_authority not in {
            "provider_literal_or_required_v1",
            "provider_dynamic_default_expression_v1",
        }:
            raise NbaApiRequestSurfaceError("parameter default authority is unsupported")
        is_dynamic = self.default_authority == "provider_dynamic_default_expression_v1"
        if is_dynamic != (self.default_expression in _DYNAMIC_DEFAULT_EXPRESSION_TYPES):
            raise NbaApiRequestSurfaceError(
                "parameter default authority differs from its source expression"
            )
        if is_dynamic and (not self.has_default or self.default is not None or self.nullable):
            raise NbaApiRequestSurfaceError(
                "dynamic provider default must use a non-nullable authority placeholder"
            )
        if not is_dynamic and self.default_expression is not None:
            raise NbaApiRequestSurfaceError(
                "literal provider default cannot retain a source expression authority"
            )
        _canonical_request_value(self.default)
        if (
            type(self.value_types) is not tuple
            or not self.value_types
            or self.value_types != tuple(sorted(set(self.value_types)))
            or any(item not in {"str", "int", "float", "bool"} for item in self.value_types)
        ):
            raise NbaApiRequestSurfaceError(
                "parameter value_types must be sorted, unique, supported, and nonempty"
            )
        if self.pattern is not None and (not isinstance(self.pattern, str) or not self.pattern):
            raise NbaApiRequestSurfaceError("parameter pattern must be nonempty when present")
        if self.domain_kind not in _DOMAIN_KINDS:
            raise NbaApiRequestSurfaceError("parameter domain_kind is unsupported")
        if self.coverage_policy not in _COVERAGE_POLICIES:
            raise NbaApiRequestSurfaceError("parameter coverage_policy is unsupported")
        if self.semantic_role not in {
            "discovery_key",
            "scope_axis",
            "bounded_control",
            "finite_selector",
            "neutral_filter",
            "pagination_cursor",
        }:
            raise NbaApiRequestSurfaceError("parameter semantic_role is unsupported")
        if (
            type(self.dependencies) is not tuple
            or not self.dependencies
            or self.dependencies != tuple(sorted(set(self.dependencies)))
            or any(item not in _DEPENDENCY_IDS for item in self.dependencies)
        ):
            raise NbaApiRequestSurfaceError(
                "parameter dependencies must be sorted, unique, known, and nonempty"
            )
        if (
            type(self.evidence) is not tuple
            or not self.evidence
            or any(not isinstance(item, ParameterDomainEvidence) for item in self.evidence)
            or tuple(item.evidence_sha256 for item in self.evidence)
            != tuple(sorted({item.evidence_sha256 for item in self.evidence}))
        ):
            raise NbaApiRequestSurfaceError(
                "parameter evidence must be digest-sorted, unique, and nonempty"
            )
        evidence_dependencies = {
            dependency for item in self.evidence for dependency in item.dependencies
        }
        if not set(self.dependencies) <= evidence_dependencies:
            raise NbaApiRequestSurfaceError(
                "parameter dependencies are not bound by concrete evidence"
            )
        if self.semantic_role == "pagination_cursor" and not any(
            item.evidence_kind == "pagination_until_terminal" for item in self.evidence
        ):
            raise NbaApiRequestSurfaceError("pagination cursor lacks terminal-page evidence")
        if self.semantic_role == "neutral_filter" and not any(
            item.evidence_kind == "neutral_value" for item in self.evidence
        ):
            raise NbaApiRequestSurfaceError("neutral filter lacks concrete neutral evidence")
        expected_source_signature = _sha256(
            _parameter_source_signature_payload(
                occurrence_id=self.occurrence_id,
                ordinal=self.ordinal,
                name=self.name,
                query_name=self.query_name,
                location=self.location,
                required=self.required,
                nullable=self.nullable,
                has_default=self.has_default,
                default=self.default,
                default_authority=self.default_authority,
                default_expression=self.default_expression,
            )
        )
        if (
            _require_sha256("parameter source_signature_sha256", self.source_signature_sha256)
            != expected_source_signature
        ):
            raise NbaApiRequestSurfaceError(
                "parameter source signature differs from its exact occurrence"
            )
        expected_typed_domain = _sha256(
            _typed_parameter_domain_payload(
                occurrence_id=self.occurrence_id,
                source_signature_sha256=self.source_signature_sha256,
                value_types=self.value_types,
                pattern=self.pattern,
                domain_kind=self.domain_kind,
                coverage_policy=self.coverage_policy,
                semantic_role=self.semantic_role,
                dependencies=self.dependencies,
                evidence=self.evidence,
            )
        )
        if (
            _require_sha256("parameter typed_domain_sha256", self.typed_domain_sha256)
            != expected_typed_domain
        ):
            raise NbaApiRequestSurfaceError(
                "parameter typed-domain authority differs from its exact occurrence"
            )
        if self.has_default and self.default_authority == "provider_literal_or_required_v1":
            _validate_parameter_value(self, self.default)


def _build_parameter_disposition(
    *,
    source_family: SourceFamily,
    endpoint_id: str,
    ordinal: int,
    name: str,
    query_name: str,
    location: ParameterLocation,
    required: bool,
    nullable: bool,
    has_default: bool,
    default: EvidenceValue,
    default_authority: ParameterDefaultAuthority,
    default_expression: str | None,
    value_types: tuple[ParameterValueType, ...],
    pattern: str | None,
    domain_kind: DomainKind,
    coverage_policy: CoveragePolicy,
    semantic_role: SemanticRole,
    dependencies: tuple[str, ...],
    evidence: tuple[ParameterDomainEvidence, ...],
) -> ParameterDomainDisposition:
    occurrence_id = _parameter_occurrence_id(source_family, endpoint_id, ordinal, name)
    source_signature_sha256 = _sha256(
        _parameter_source_signature_payload(
            occurrence_id=occurrence_id,
            ordinal=ordinal,
            name=name,
            query_name=query_name,
            location=location,
            required=required,
            nullable=nullable,
            has_default=has_default,
            default=default,
            default_authority=default_authority,
            default_expression=default_expression,
        )
    )
    typed_domain_sha256 = _sha256(
        _typed_parameter_domain_payload(
            occurrence_id=occurrence_id,
            source_signature_sha256=source_signature_sha256,
            value_types=value_types,
            pattern=pattern,
            domain_kind=domain_kind,
            coverage_policy=coverage_policy,
            semantic_role=semantic_role,
            dependencies=dependencies,
            evidence=evidence,
        )
    )
    return ParameterDomainDisposition(
        ordinal=ordinal,
        occurrence_id=occurrence_id,
        name=name,
        query_name=query_name,
        location=location,
        required=required,
        nullable=nullable,
        has_default=has_default,
        default=default,
        default_authority=default_authority,
        default_expression=default_expression,
        value_types=value_types,
        pattern=pattern,
        domain_kind=domain_kind,
        coverage_policy=coverage_policy,
        semantic_role=semantic_role,
        dependencies=dependencies,
        evidence=evidence,
        source_signature_sha256=source_signature_sha256,
        typed_domain_sha256=typed_domain_sha256,
    )


@dataclass(frozen=True, slots=True)
class ParameterConstraintEdge:
    """One canonical dependency or cross-parameter constraint edge."""

    source_node: str
    target_node: str
    constraint_kind: ParameterConstraintKind
    authority: str

    def __post_init__(self) -> None:
        _require_safe_id("constraint source_node", self.source_node)
        _require_safe_id("constraint target_node", self.target_node)
        _require_safe_id("constraint authority", self.authority)
        if self.source_node == self.target_node:
            raise NbaApiRequestSurfaceError("parameter constraint cannot be a self-loop")
        if self.constraint_kind not in {
            "authorized_by",
            "lower_lte_upper_if_both_present",
        }:
            raise NbaApiRequestSurfaceError("parameter constraint kind is unsupported")

    @property
    def constraint_sha256(self) -> str:
        return _sha256(_parameter_constraint_payload(self))


def _parameter_constraint_payload(edge: ParameterConstraintEdge) -> dict[str, object]:
    return {
        "source_node": edge.source_node,
        "target_node": edge.target_node,
        "constraint_kind": edge.constraint_kind,
        "authority": edge.authority,
    }


def _constraint_sort_key(edge: ParameterConstraintEdge) -> tuple[str, str, str, str]:
    return (
        edge.source_node,
        edge.target_node,
        edge.constraint_kind,
        edge.authority,
    )


def _parameter_constraint_edges(
    parameters: tuple[ParameterDomainDisposition, ...],
) -> tuple[ParameterConstraintEdge, ...]:
    by_name = {parameter.name: parameter for parameter in parameters}
    edges = [
        ParameterConstraintEdge(
            source_node=f"authority:{dependency}",
            target_node=parameter.occurrence_id,
            constraint_kind="authorized_by",
            authority="typed_parameter_dependency_v1",
        )
        for parameter in parameters
        for dependency in parameter.dependencies
    ]
    edges.extend(
        ParameterConstraintEdge(
            source_node=by_name[lower_name].occurrence_id,
            target_node=by_name[upper_name].occurrence_id,
            constraint_kind="lower_lte_upper_if_both_present",
            authority="ordered_wire_interval_v1",
        )
        for lower_name, upper_name in _PARAMETER_ORDER_CONSTRAINTS
        if lower_name in by_name and upper_name in by_name
    )
    return tuple(sorted(edges, key=_constraint_sort_key))


def _validate_parameter_constraint_graph(
    nodes: tuple[str, ...],
    edges: tuple[ParameterConstraintEdge, ...],
) -> None:
    """Require a canonical acyclic graph over exact parameter occurrences."""

    if nodes != tuple(sorted(set(nodes))) or any(
        _SAFE_ID_RE.fullmatch(node) is None for node in nodes
    ):
        raise NbaApiRequestSurfaceError(
            "parameter constraint graph nodes must be sorted, unique, and safe"
        )
    if (
        type(edges) is not tuple
        or any(not isinstance(edge, ParameterConstraintEdge) for edge in edges)
        or edges != tuple(sorted(set(edges), key=_constraint_sort_key))
    ):
        raise NbaApiRequestSurfaceError(
            "parameter constraint graph edges must be sorted and unique"
        )
    node_set = set(nodes)
    if any(edge.source_node not in node_set or edge.target_node not in node_set for edge in edges):
        raise NbaApiRequestSurfaceError("parameter constraint graph references an unknown node")
    outgoing: dict[str, list[str]] = {node: [] for node in nodes}
    incoming_count = {node: 0 for node in nodes}
    for edge in edges:
        outgoing[edge.source_node].append(edge.target_node)
        incoming_count[edge.target_node] += 1
    ready = sorted(node for node, count in incoming_count.items() if count == 0)
    visited = 0
    while ready:
        node = ready.pop(0)
        visited += 1
        for target in sorted(outgoing[node]):
            incoming_count[target] -= 1
            if incoming_count[target] == 0:
                ready.append(target)
        ready.sort()
    if visited != len(nodes):
        raise NbaApiRequestSurfaceError("parameter constraint graph contains a cycle")


@dataclass(frozen=True, slots=True)
class EndpointRequestSurface:
    """Ordered request contract for one concrete provider endpoint class."""

    source_family: SourceFamily
    endpoint_id: str
    module_name: str
    endpoint_slug: str
    url_template: str
    request_method: str
    parameters: tuple[ParameterDomainDisposition, ...]
    constraint_edges: tuple[ParameterConstraintEdge, ...]

    def __post_init__(self) -> None:
        if self.source_family not in {"stats", "live"}:
            raise NbaApiRequestSurfaceError("endpoint source_family is unsupported")
        _require_safe_id("endpoint_id", self.endpoint_id)
        if not isinstance(self.module_name, str) or not self.module_name:
            raise NbaApiRequestSurfaceError("endpoint module_name must be nonempty")
        _require_safe_id("endpoint_slug", self.endpoint_slug)
        if not isinstance(self.url_template, str) or not self.url_template.startswith("https://"):
            raise NbaApiRequestSurfaceError("endpoint url_template must be an HTTPS URL")
        if self.request_method != "GET":
            raise NbaApiRequestSurfaceError("pinned nba_api endpoints must use GET")
        if type(self.parameters) is not tuple or any(
            not isinstance(parameter, ParameterDomainDisposition) for parameter in self.parameters
        ):
            raise NbaApiRequestSurfaceError("endpoint parameters must be an exact tuple")
        if tuple(parameter.ordinal for parameter in self.parameters) != tuple(
            range(len(self.parameters))
        ):
            raise NbaApiRequestSurfaceError("endpoint parameter ordinals must be contiguous")
        if any(
            parameter.occurrence_id
            != _parameter_occurrence_id(
                self.source_family,
                self.endpoint_id,
                parameter.ordinal,
                parameter.name,
            )
            for parameter in self.parameters
        ):
            raise NbaApiRequestSurfaceError(
                "parameter occurrence identity differs from its exact endpoint tuple"
            )
        names = tuple(parameter.name for parameter in self.parameters)
        query_names = tuple(parameter.query_name for parameter in self.parameters)
        if len(names) != len(set(names)) or len(query_names) != len(set(query_names)):
            raise NbaApiRequestSurfaceError("endpoint parameter names must be unique")
        path_names = {match.group("name") for match in _PATH_TOKEN_RE.finditer(self.url_template)}
        declared_path_names = {
            parameter.name for parameter in self.parameters if parameter.location == "path"
        }
        if path_names != declared_path_names:
            raise NbaApiRequestSurfaceError(
                "endpoint path tokens do not exactly match declared path parameters"
            )
        constraint_nodes = tuple(
            sorted(
                {
                    *(parameter.occurrence_id for parameter in self.parameters),
                    *(
                        f"authority:{dependency}"
                        for parameter in self.parameters
                        for dependency in parameter.dependencies
                    ),
                }
            )
        )
        _validate_parameter_constraint_graph(constraint_nodes, self.constraint_edges)
        expected_edges = _parameter_constraint_edges(self.parameters)
        if self.constraint_edges != expected_edges:
            raise NbaApiRequestSurfaceError(
                "parameter constraint graph differs from exact typed dependencies"
            )

    def parameter(self, name: str) -> ParameterDomainDisposition:
        """Return one exact parameter or fail closed."""

        match = next((parameter for parameter in self.parameters if parameter.name == name), None)
        if match is None:
            raise NbaApiRequestSurfaceError("request references an unknown endpoint parameter")
        return match


@dataclass(frozen=True, slots=True)
class StaticDatasetSurface:
    """Exact embedded static array body owned by the request surface."""

    dataset_id: str
    module_name: str
    source_symbol: str
    row_count: int
    row_width: int
    embedded_body_sha256: str
    runtime_source_rows_sha256: str

    def __post_init__(self) -> None:
        _require_safe_id("static dataset_id", self.dataset_id)
        if not isinstance(self.module_name, str) or not self.module_name:
            raise NbaApiRequestSurfaceError("static dataset module_name must be nonempty")
        _require_safe_id("static dataset source_symbol", self.source_symbol)
        _require_nonnegative_integer("static dataset row_count", self.row_count)
        _require_nonnegative_integer("static dataset row_width", self.row_width)
        _require_sha256("static dataset embedded_body_sha256", self.embedded_body_sha256)
        _require_sha256(
            "static dataset runtime_source_rows_sha256",
            self.runtime_source_rows_sha256,
        )
        if self.row_count == 0 or self.row_width == 0:
            raise NbaApiRequestSurfaceError("static dataset body must be nonempty")
        if self.embedded_body_sha256 != self.runtime_source_rows_sha256:
            raise NbaApiRequestSurfaceError(
                "static embedded body differs from the exact runtime contract"
            )


@dataclass(frozen=True, slots=True)
class StaticHelperSurface:
    """Public static helper classified as a projection, never a new dataset."""

    helper_id: str
    module_name: str
    function_name: str
    dataset_id: str
    helper_kind: StaticHelperKind
    scope_status: StaticScopeStatus
    embedded_body_sha256: str
    parameters: tuple[str, ...]
    required_parameters: tuple[str, ...]

    def __post_init__(self) -> None:
        _require_safe_id("static helper_id", self.helper_id)
        if not isinstance(self.module_name, str) or not self.module_name:
            raise NbaApiRequestSurfaceError("static helper module_name must be nonempty")
        _require_safe_id("static helper function_name", self.function_name)
        _require_safe_id("static helper dataset_id", self.dataset_id)
        if self.helper_kind not in {"dataset_projection", "filtered_projection", "finder_alias"}:
            raise NbaApiRequestSurfaceError("static helper_kind is unsupported")
        if self.scope_status not in {"in_scope", "out_of_scope_with_evidence"}:
            raise NbaApiRequestSurfaceError("static helper scope_status is unsupported")
        _require_sha256("static helper embedded_body_sha256", self.embedded_body_sha256)
        for label, values in (
            ("parameters", self.parameters),
            ("required_parameters", self.required_parameters),
        ):
            if (
                type(values) is not tuple
                or len(values) != len(set(values))
                or any(_SAFE_ID_RE.fullmatch(value) is None for value in values)
            ):
                raise NbaApiRequestSurfaceError(f"static helper {label} is invalid")
        if not set(self.required_parameters) <= set(self.parameters):
            raise NbaApiRequestSurfaceError(
                "static helper required parameters must belong to its signature"
            )


@dataclass(frozen=True, slots=True)
class RequestSurfaceAuthority:
    """Exact full request and public-static-helper surface for the pinned release."""

    runtime_contract_payload_sha256: str
    terminal_policy_sha256: str
    endpoints: tuple[EndpointRequestSurface, ...]
    static_datasets: tuple[StaticDatasetSurface, ...]
    static_helpers: tuple[StaticHelperSurface, ...]
    _surface_sha256: str = dataclass_field(init=False, repr=False, compare=False)

    def __post_init__(self) -> None:
        _require_sha256("runtime_contract_payload_sha256", self.runtime_contract_payload_sha256)
        if self.terminal_policy_sha256 != _terminal_policy_sha256():
            raise NbaApiRequestSurfaceError(
                "request surface references a foreign terminal-state policy"
            )
        if not self.endpoints or not all(
            isinstance(endpoint, EndpointRequestSurface) for endpoint in self.endpoints
        ):
            raise NbaApiRequestSurfaceError("request surface must contain endpoints")
        endpoint_keys = tuple(
            (endpoint.source_family, endpoint.endpoint_id) for endpoint in self.endpoints
        )
        if endpoint_keys != tuple(sorted(set(endpoint_keys))):
            raise NbaApiRequestSurfaceError("request endpoints must be sorted and unique")
        occurrence_ids = tuple(
            parameter.occurrence_id
            for endpoint in self.endpoints
            for parameter in endpoint.parameters
        )
        if len(occurrence_ids) != len(set(occurrence_ids)):
            raise NbaApiRequestSurfaceError(
                "request surface contains duplicate parameter occurrences"
            )
        typed_domain_digests = tuple(
            parameter.typed_domain_sha256
            for endpoint in self.endpoints
            for parameter in endpoint.parameters
        )
        if len(typed_domain_digests) != len(set(typed_domain_digests)):
            raise NbaApiRequestSurfaceError("typed parameter domains are not occurrence-specific")
        if not self.static_helpers or not all(
            isinstance(helper, StaticHelperSurface) for helper in self.static_helpers
        ):
            raise NbaApiRequestSurfaceError("request surface must contain static helpers")
        helper_ids = tuple(helper.helper_id for helper in self.static_helpers)
        if helper_ids != tuple(sorted(set(helper_ids))):
            raise NbaApiRequestSurfaceError("static helpers must be sorted and unique")
        if not self.static_datasets or not all(
            isinstance(dataset, StaticDatasetSurface) for dataset in self.static_datasets
        ):
            raise NbaApiRequestSurfaceError("request surface must contain static datasets")
        dataset_ids = tuple(dataset.dataset_id for dataset in self.static_datasets)
        if dataset_ids != tuple(sorted(set(dataset_ids))):
            raise NbaApiRequestSurfaceError("static datasets must be sorted and unique")
        dataset_digests = {
            dataset.dataset_id: dataset.embedded_body_sha256 for dataset in self.static_datasets
        }
        if set(dataset_digests) != {
            "static_players",
            "static_teams",
            "static_wnba_players",
            "static_wnba_teams",
        }:
            raise NbaApiRequestSurfaceError("static dataset inventory is incomplete")
        if any(
            helper.scope_status != "in_scope"
            or dataset_digests.get(helper.dataset_id) != helper.embedded_body_sha256
            for helper in self.static_helpers
        ):
            raise NbaApiRequestSurfaceError(
                "every NBA and WNBA static helper must bind one in-scope embedded array"
            )
        # The authority is deeply immutable.  Materialize its canonical identity once
        # per instance instead of rebuilding the full nested payload for every route.
        object.__setattr__(self, "_surface_sha256", _sha256(_authority_payload(self)))

    @property
    def surface_sha256(self) -> str:
        return self._surface_sha256

    @property
    def parameter_occurrence_count(self) -> int:
        return sum(len(endpoint.parameters) for endpoint in self.endpoints)

    @property
    def parameter_name_count(self) -> int:
        return len(
            {parameter.name for endpoint in self.endpoints for parameter in endpoint.parameters}
        )

    @property
    def parameter_constraint_edge_count(self) -> int:
        return sum(len(endpoint.constraint_edges) for endpoint in self.endpoints)

    def endpoint(self, source_family: SourceFamily, endpoint_id: str) -> EndpointRequestSurface:
        match = next(
            (
                endpoint
                for endpoint in self.endpoints
                if endpoint.source_family == source_family and endpoint.endpoint_id == endpoint_id
            ),
            None,
        )
        if match is None:
            raise NbaApiRequestSurfaceError("request references an unknown endpoint")
        return match


def _identifier_dependencies(name: str) -> tuple[str, ...]:
    if "event_id" in name:
        return ("game_event_index",)
    if "game_id" in name:
        return ("game_date_index",)
    if "player_id" in name or name.startswith("person"):
        return ("season_player_universe",)
    if "team_id" in name:
        return ("season_team_universe",)
    if "series_id" in name:
        return ("playoff_series_universe",)
    if "group_id" in name:
        return ("lineup_group_universe",)
    raise NbaApiRequestSurfaceError(f"unclassified identifier parameter: {name}")


def _classify_parameter(name: str) -> tuple[DomainKind, CoveragePolicy, tuple[str, ...]]:
    """Classify one exact-pin parameter; unknown future names fail closed."""

    if _IDENTIFIER_RE.search(name) is not None or _PERSON_IDENTIFIER_RE.fullmatch(name):
        return (
            "discovered_identifier",
            "enumerate_discovered_values",
            _identifier_dependencies(name),
        )
    if name == "game_date" or name.startswith("date_"):
        return "temporal_scope", "enumerate_scope_values", ("game_date_index",)
    if name in _EXPLICIT_VALUE_PARAMETERS:
        return (
            "explicit_value_scope",
            "enumerate_explicit_values",
            ("explicit_scope_manifest",),
        )
    if _TEMPORAL_RE.search(name) is not None:
        dependency = "season_type_scope" if "season_type" in name else "season_scope"
        return "temporal_scope", "enumerate_scope_values", (dependency,)
    if "league_id" in name:
        return "league_scope", "enumerate_scope_values", ("league_scope",)
    if _METRIC_FILTER_RE.match(name) is not None:
        return (
            "nullable_filter_scope",
            "enumerate_explicit_values",
            ("explicit_scope_manifest",),
        )
    if name in _BOUNDED_NUMERIC_PARAMETERS:
        return (
            "bounded_numeric_scope",
            "enumerate_explicit_values",
            ("explicit_scope_manifest",),
        )
    if name.endswith("_nullable"):
        return (
            "nullable_filter_scope",
            "enumerate_explicit_values",
            ("explicit_scope_manifest",),
        )
    raise NbaApiRequestSurfaceError(f"unclassified request parameter: {name}")


def _provider_parameter_class_name(name: str) -> str:
    """Return the provider class identity recorded as non-executable evidence."""

    return "".join(part[:1].upper() + part[1:] for part in name.split("_") if part)


def _provider_finite_values(name: str) -> tuple[EvidenceValue, ...]:
    values: list[EvidenceValue] = []
    for value in stats_parameter_finite_values(name):
        if value is None or type(value) in {str, bool, int, float}:
            values.append(_canonical_scalar(value, field="provider finite value"))
    return _sorted_scalar_values(values)


def _parameter_value_types(
    name: str,
    *,
    default: object,
    pattern: str | None,
) -> tuple[ParameterValueType, ...]:
    if pattern is not None or name in {
        "game_id",
        "game_ids",
        "player_id_list",
        "vs_player_id_list",
    }:
        return ("str",)
    if name == "is_only_current_season":
        return ("int",)
    if _METRIC_FILTER_RE.match(name) is not None or name in _BOUNDED_NUMERIC_PARAMETERS:
        return ("float", "int", "str")
    if _IDENTIFIER_RE.search(name) is not None or _PERSON_IDENTIFIER_RE.fullmatch(name):
        return ("int", "str")
    if default is not None:
        value_type = type(default).__name__
        if value_type in {"str", "int", "float", "bool"}:
            return (cast("ParameterValueType", value_type),)
    return ("str",)


def _semantic_role_and_evidence(
    name: str,
    *,
    default: EvidenceValue,
    nullable: bool,
    dependencies: tuple[str, ...],
    domain_kind: DomainKind,
) -> tuple[SemanticRole, tuple[ParameterDomainEvidence, ...]]:
    evidence: list[ParameterDomainEvidence] = []
    finite_values = _provider_finite_values(name)
    if domain_kind == "discovered_identifier":
        role: SemanticRole = "discovery_key"
        evidence.append(
            ParameterDomainEvidence(
                evidence_kind="discovered_inventory",
                authority="typed_discovery_inventory_v1",
                dependencies=dependencies,
            )
        )
    elif name == "counter":
        role = "pagination_cursor"
        lower, upper = _BOUNDED_NUMERIC_RANGES[name]
        evidence.extend(
            (
                ParameterDomainEvidence(
                    evidence_kind="bounded_interval",
                    authority="nba_api_wire_numeric_bounds_v1",
                    dependencies=dependencies,
                    minimum=lower,
                    maximum=upper,
                ),
                ParameterDomainEvidence(
                    evidence_kind="pagination_until_terminal",
                    authority="contiguous_page_receipt_v1",
                    dependencies=dependencies,
                    terminal_condition="contiguous_from_zero_with_terminal_page",
                ),
            )
        )
    elif domain_kind == "bounded_numeric_scope":
        role = "bounded_control"
        bounds = _BOUNDED_NUMERIC_RANGES.get(name)
        if bounds is None:
            raise NbaApiRequestSurfaceError(f"bounded parameter lacks exact bounds: {name}")
        evidence.append(
            ParameterDomainEvidence(
                evidence_kind="bounded_interval",
                authority="nba_api_wire_numeric_bounds_v1",
                dependencies=dependencies,
                minimum=bounds[0],
                maximum=bounds[1],
            )
        )
    elif domain_kind == "nullable_filter_scope":
        role = "neutral_filter"
        evidence.append(
            ParameterDomainEvidence(
                evidence_kind="neutral_value",
                authority="exact_constructor_default_v1",
                dependencies=dependencies,
                neutral_value_present=True,
                neutral_value=default,
            )
        )
        if finite_values:
            evidence.append(
                ParameterDomainEvidence(
                    evidence_kind="provider_finite_values",
                    authority=_provider_parameter_class_name(name),
                    dependencies=dependencies,
                    finite_values=finite_values,
                )
            )
    elif domain_kind in {"temporal_scope", "league_scope"}:
        role = "scope_axis"
        evidence.append(
            ParameterDomainEvidence(
                evidence_kind="scope_inventory",
                authority="typed_scope_manifest_v1",
                dependencies=dependencies,
            )
        )
        if domain_kind == "league_scope":
            competition_authority, competition_payload_sha256 = _competition_authority_binding()
            evidence.append(
                ParameterDomainEvidence(
                    evidence_kind="provider_finite_values",
                    authority=(f"nba_api_competition_v1_11_4_{competition_payload_sha256}"),
                    dependencies=dependencies,
                    finite_values=cast(
                        "tuple[EvidenceValue, ...]",
                        competition_authority.league_ids,
                    ),
                )
            )
        # Season/year helper classes expose a moving convenience inventory, not
        # the historical domain.  Treat only the exact enum-like temporal
        # selectors as finite; historical seasons remain scope-authorized.
        if (
            domain_kind == "temporal_scope"
            and name in _FINITE_TEMPORAL_PARAMETERS
            and finite_values
        ):
            evidence.append(
                ParameterDomainEvidence(
                    evidence_kind="provider_finite_values",
                    authority=_provider_parameter_class_name(name),
                    dependencies=dependencies,
                    finite_values=finite_values,
                )
            )
    else:
        role = "finite_selector"
        if finite_values:
            evidence.append(
                ParameterDomainEvidence(
                    evidence_kind="provider_finite_values",
                    authority=_provider_parameter_class_name(name),
                    dependencies=dependencies,
                    finite_values=finite_values,
                )
            )
        else:
            evidence.append(
                ParameterDomainEvidence(
                    evidence_kind="explicit_scope_inventory",
                    authority="typed_explicit_scope_manifest_v1",
                    dependencies=dependencies,
                )
            )
    if nullable and not any(item.evidence_kind == "neutral_value" for item in evidence):
        evidence.append(
            ParameterDomainEvidence(
                evidence_kind="neutral_value",
                authority="exact_constructor_default_v1",
                dependencies=dependencies,
                neutral_value_present=True,
                neutral_value=default,
            )
        )
    return role, tuple(sorted(evidence, key=lambda item: item.evidence_sha256))


def _value_type_name(value: object) -> ParameterValueType | None:
    if type(value) is str:
        return "str"
    if type(value) is int:
        return "int"
    if type(value) is float:
        return "float"
    if type(value) is bool:
        return "bool"
    return None


def _parameter_evidence(
    parameter: ParameterDomainDisposition,
    kind: DomainEvidenceKind,
) -> ParameterDomainEvidence | None:
    return next((item for item in parameter.evidence if item.evidence_kind == kind), None)


def _numeric_value(parameter: ParameterDomainDisposition, value: object) -> float:
    if isinstance(value, bool):
        raise NbaApiRequestSurfaceError("boolean is not a numeric request value")
    if isinstance(value, int | float) or (
        isinstance(value, str) and _NUMERIC_TEXT_RE.fullmatch(value)
    ):
        numeric = float(value)
    else:
        raise NbaApiRequestSurfaceError(f"parameter {parameter.name} requires a numeric wire value")
    if not math.isfinite(numeric):
        raise NbaApiRequestSurfaceError("numeric request values must be finite")
    return numeric


def _canonical_scalar_equal(left: EvidenceValue, right: EvidenceValue) -> bool:
    """Compare JSON scalars without Python's ``True == 1`` coercion."""

    return _canonical_json_bytes(left) == _canonical_json_bytes(right)


def _validate_calendar_date(parameter_name: str, value: EvidenceValue) -> None:
    if (
        not isinstance(value, str)
        or re.fullmatch(
            r"(?:[0-9]{4}-[0-9]{2}-[0-9]{2}|[0-9]{2}/[0-9]{2}/[0-9]{4})",
            value,
        )
        is None
    ):
        raise NbaApiRequestSurfaceError(
            f"parameter {parameter_name} is outside its exact calendar-date domain"
        )
    for date_format in _DATE_FORMATS:
        try:
            datetime.strptime(value, date_format)
        except ValueError:
            continue
        return
    raise NbaApiRequestSurfaceError(
        f"parameter {parameter_name} is outside its exact calendar-date domain"
    )


def _validate_scope_axis_value(
    parameter: ParameterDomainDisposition,
    value: EvidenceValue,
) -> None:
    """Reject malformed values before a scope receipt can authorize them.

    Scope manifests decide *which* historical values are in a run.  This
    validator independently proves that those values belong to the pinned wire
    grammar, while deliberately avoiding a moving current-season allowlist.
    """

    name = parameter.name
    if parameter.domain_kind == "league_scope":
        if not isinstance(value, str) or _LEAGUE_ID_RE.fullmatch(value) is None:
            raise NbaApiRequestSurfaceError(
                f"parameter {name} is outside its exact league-id domain"
            )
        return
    if parameter.domain_kind != "temporal_scope" or name in _FINITE_TEMPORAL_PARAMETERS:
        return
    if name in {"game_date", "date_from_nullable", "date_to_nullable"}:
        _validate_calendar_date(name, value)
        return
    if name in {
        "draft_year_nullable",
        "rookie_year_nullable",
        "season_year_nullable",
    }:
        if not isinstance(value, str) or _YEAR_RE.fullmatch(value) is None:
            raise NbaApiRequestSurfaceError(
                f"parameter {name} is outside its exact four-digit-year domain"
            )
        return
    if name in {"season_year", "person1_season_year", "person2_season_year"}:
        if isinstance(value, bool) or not isinstance(value, int) or not 1000 <= value <= 9999:
            raise NbaApiRequestSurfaceError(
                f"parameter {name} is outside its exact four-digit-year domain"
            )
        return
    if name in {"season_id", "season_id_nullable"}:
        if not isinstance(value, str) or _SEASON_ID_RE.fullmatch(value) is None:
            raise NbaApiRequestSurfaceError(
                f"parameter {name} is outside its exact season-id domain"
            )
        return
    if name in {"season", "season_nullable", "season_all", "season_all_time"}:
        special_value = (name == "season_all" and value == "ALL") or (
            name == "season_all_time" and value == "ALLTIME"
        )
        if special_value:
            return
        if not isinstance(value, str):
            raise NbaApiRequestSurfaceError(
                f"parameter {name} is outside its exact season-label domain"
            )
        match = _SEASON_LABEL_RE.fullmatch(value)
        if match is None:
            raise NbaApiRequestSurfaceError(
                f"parameter {name} is outside its exact season-label domain"
            )
        if (int(match.group("start")) + 1) % 100 != int(match.group("end")):
            raise NbaApiRequestSurfaceError(
                f"parameter {name} is outside its exact consecutive-season domain"
            )
        return
    raise NbaApiRequestSurfaceError(f"parameter {name} has no pinned temporal wire grammar")


def _validate_parameter_value(
    parameter: ParameterDomainDisposition,
    value: object,
) -> EvidenceValue:
    if value is None:
        if not parameter.nullable:
            raise NbaApiRequestSurfaceError(f"parameter {parameter.name} does not permit null")
        return None
    value_type = _value_type_name(value)
    if value_type is None or value_type not in parameter.value_types:
        raise NbaApiRequestSurfaceError(f"parameter {parameter.name} has an invalid concrete type")
    scalar = _canonical_scalar(value, field=f"parameter {parameter.name}")
    if parameter.required and scalar == "":
        raise NbaApiRequestSurfaceError(
            f"required parameter {parameter.name} cannot be an empty string"
        )
    if parameter.pattern is not None and (
        not isinstance(scalar, str)
        or re.fullmatch(parameter.pattern, scalar, flags=re.ASCII) is None
    ):
        raise NbaApiRequestSurfaceError(
            f"parameter {parameter.name} does not match its exact pattern"
        )
    neutral = _parameter_evidence(parameter, "neutral_value")
    is_neutral = neutral is not None and _canonical_scalar_equal(
        scalar,
        neutral.neutral_value,
    )
    if not is_neutral:
        _validate_scope_axis_value(parameter, scalar)
    if parameter.semantic_role == "discovery_key" and not is_neutral:
        if isinstance(scalar, int):
            if scalar < 0:
                raise NbaApiRequestSurfaceError("identifier request values cannot be negative")
        elif isinstance(scalar, str):
            value_pattern = (
                _IDENTIFIER_LIST_VALUE_RE
                if parameter.name in {"game_ids", "player_id_list", "vs_player_id_list"}
                else _IDENTIFIER_VALUE_RE
            )
            if value_pattern.fullmatch(scalar) is None:
                raise NbaApiRequestSurfaceError(
                    f"parameter {parameter.name} has an invalid identifier value"
                )
    bounded = _parameter_evidence(parameter, "bounded_interval")
    if bounded is not None and not is_neutral:
        numeric = _numeric_value(parameter, scalar)
        assert bounded.minimum is not None and bounded.maximum is not None
        if numeric < bounded.minimum or numeric > bounded.maximum:
            raise NbaApiRequestSurfaceError(
                f"parameter {parameter.name} is outside its exact bounded domain"
            )
    finite = _parameter_evidence(parameter, "provider_finite_values")
    if (
        finite is not None
        and not any(
            _canonical_scalar_equal(scalar, candidate) for candidate in finite.finite_values
        )
        and not is_neutral
    ):
        raise NbaApiRequestSurfaceError(
            f"parameter {parameter.name} is outside its provider finite domain"
        )
    return scalar


def _ordered_constraint_value(
    parameter: ParameterDomainDisposition,
    value: EvidenceValue,
) -> float:
    if parameter.name in {"date_from_nullable", "date_to_nullable"}:
        if not isinstance(value, str):
            raise NbaApiRequestSurfaceError("ordered date constraint received a non-string value")
        for date_format in _DATE_FORMATS:
            try:
                return float(datetime.strptime(value, date_format).toordinal())
            except ValueError:
                continue
        raise NbaApiRequestSurfaceError("ordered date constraint received an invalid date")
    return _numeric_value(parameter, value)


def _validate_materialized_parameter_constraints(
    endpoint: EndpointRequestSurface,
    values: Mapping[str, EvidenceValue],
) -> None:
    by_occurrence = {parameter.occurrence_id: parameter for parameter in endpoint.parameters}
    for edge in endpoint.constraint_edges:
        if edge.constraint_kind != "lower_lte_upper_if_both_present":
            continue
        lower_parameter = by_occurrence[edge.source_node]
        upper_parameter = by_occurrence[edge.target_node]
        lower = values[lower_parameter.name]
        upper = values[upper_parameter.name]
        if lower is None or upper is None:
            continue
        lower_neutral = _parameter_evidence(lower_parameter, "neutral_value")
        upper_neutral = _parameter_evidence(upper_parameter, "neutral_value")
        if (
            lower_neutral is not None
            and _canonical_scalar_equal(lower, lower_neutral.neutral_value)
        ) or (
            upper_neutral is not None
            and _canonical_scalar_equal(upper, upper_neutral.neutral_value)
        ):
            continue
        if _ordered_constraint_value(lower_parameter, lower) > _ordered_constraint_value(
            upper_parameter, upper
        ):
            raise NbaApiRequestSurfaceError(
                "materialized parameters violate their ordered cross-parameter constraint"
            )


def _stats_endpoint_surfaces(runtime: Mapping[str, object]) -> list[EndpointRequestSurface]:
    contracts = runtime.get("contracts")
    if not isinstance(contracts, dict) or not contracts:
        raise NbaApiRequestSurfaceError("runtime stats contracts are absent")
    surfaces: list[EndpointRequestSurface] = []
    for endpoint_id, raw_contract in sorted(contracts.items()):
        if not isinstance(endpoint_id, str) or not isinstance(raw_contract, dict):
            raise NbaApiRequestSurfaceError("runtime stats contract is invalid")
        contract = cast("dict[str, Any]", raw_contract)
        names = contract.get("parameters")
        required = contract.get("required_parameters")
        nullable = contract.get("nullable_parameters")
        defaults = contract.get("parameter_defaults")
        query_names = contract.get("parameter_query_names")
        patterns = contract.get("parameter_patterns") or {}
        if not all(
            isinstance(value, list) for value in (names, required, nullable, defaults, query_names)
        ):
            raise NbaApiRequestSurfaceError("runtime stats parameter contract is invalid")
        if not isinstance(patterns, dict):
            raise NbaApiRequestSurfaceError("runtime stats parameter patterns are invalid")
        name_values = cast("list[object]", names)
        required_set = set(cast("list[object]", required))
        nullable_set = set(cast("list[object]", nullable))
        default_map: dict[
            str,
            tuple[
                EvidenceValue,
                ParameterValueType,
                ParameterDefaultAuthority,
                str | None,
            ],
        ] = {}
        for item in cast("list[object]", defaults):
            if not isinstance(item, dict):
                raise NbaApiRequestSurfaceError("runtime stats parameter default is invalid")
            default_item = cast("dict[str, object]", item)
            declared_authority = default_item.get("default_authority")
            expected_fields = (
                {"name", "value_type", "default_authority", "default_expression"}
                if declared_authority == "provider_dynamic_default_expression_v1"
                else {
                    "name",
                    "value",
                    "value_type",
                    "default_authority",
                    "default_expression",
                }
            )
            if set(default_item) != expected_fields:
                raise NbaApiRequestSurfaceError("runtime stats parameter default is invalid")
            default_name = default_item["name"]
            if not isinstance(default_name, str) or default_name in default_map:
                raise NbaApiRequestSurfaceError("runtime stats parameter defaults are invalid")
            default_value = default_item.get("value")
            default_value_type = default_item["value_type"]
            default_authority = default_item["default_authority"]
            default_expression = default_item["default_expression"]
            if default_value_type not in {"str", "int", "float", "bool", "NoneType"}:
                raise NbaApiRequestSurfaceError("runtime stats default type evidence is invalid")
            if default_authority == "provider_dynamic_default_expression_v1":
                if (
                    default_value is not None
                    or not isinstance(default_expression, str)
                    or _DYNAMIC_DEFAULT_EXPRESSION_TYPES.get(default_expression)
                    != default_value_type
                ):
                    raise NbaApiRequestSurfaceError(
                        "runtime stats dynamic default authority is invalid"
                    )
            elif default_authority == "provider_literal_or_required_v1":
                if (
                    not isinstance(default_expression, str)
                    or default_expression in _DYNAMIC_DEFAULT_EXPRESSION_TYPES
                    or default_expression.partition(".")[0] in _DYNAMIC_DEFAULT_CLASS_NAMES
                    or type(default_value).__name__ != default_value_type
                ):
                    raise NbaApiRequestSurfaceError(
                        "runtime stats literal default authority is invalid"
                    )
            else:
                raise NbaApiRequestSurfaceError(
                    "runtime stats parameter default authority is invalid"
                )
            default_map[default_name] = (
                cast("EvidenceValue", default_value),
                cast("ParameterValueType", default_value_type),
                cast("ParameterDefaultAuthority", default_authority),
                cast("str | None", default_expression),
            )
        query_map: dict[str, str] = {}
        for item in cast("list[object]", query_names):
            if not isinstance(item, dict) or set(item) != {"name", "query_name"}:
                raise NbaApiRequestSurfaceError("runtime stats query-name contract is invalid")
            query_item = cast("dict[str, object]", item)
            parameter_name = query_item["name"]
            query_name = query_item["query_name"]
            if (
                not isinstance(parameter_name, str)
                or not isinstance(query_name, str)
                or parameter_name in query_map
            ):
                raise NbaApiRequestSurfaceError("runtime stats query names are invalid")
            query_map[parameter_name] = query_name
        if (
            any(not isinstance(name, str) for name in name_values)
            or set(name_values) != set(query_map)
            or not required_set <= set(name_values)
            or not nullable_set <= set(name_values)
            or not set(default_map) <= set(name_values)
            or not set(patterns) <= set(name_values)
        ):
            raise NbaApiRequestSurfaceError("runtime stats parameter inventory is inconsistent")
        module_name = contract.get("module_name")
        class_name = contract.get("runtime_class_name")
        if not isinstance(module_name, str) or not isinstance(class_name, str):
            raise NbaApiRequestSurfaceError("runtime stats class identity is invalid")
        default_expressions = _constructor_default_expressions(
            module_name,
            class_name,
            cast("list[str]", name_values),
        )
        parameters: list[ParameterDomainDisposition] = []
        for ordinal, raw_name in enumerate(name_values):
            name = cast("str", raw_name)
            domain_kind, coverage_policy, dependencies = _classify_parameter(name)
            pattern = patterns.get(name)
            if pattern is not None and not isinstance(pattern, str):
                raise NbaApiRequestSurfaceError("runtime stats parameter pattern is invalid")
            has_default = name in default_map
            default_contract = default_map.get(name)
            raw_default = default_contract[0] if default_contract is not None else None
            raw_default_type = default_contract[1] if default_contract is not None else None
            value_types = _parameter_value_types(name, default=raw_default, pattern=pattern)
            default, default_authority, default_expression = _normalize_parameter_default(
                source_expression=default_expressions[name],
                has_default=has_default,
                raw_default=raw_default,
                raw_default_type=raw_default_type,
            )
            if default_contract is not None and (
                default_authority != default_contract[2]
                or (
                    default_authority == "provider_dynamic_default_expression_v1"
                    and default_expression != default_contract[3]
                )
                or default_expressions[name] != default_contract[3]
            ):
                raise NbaApiRequestSurfaceError(
                    "runtime stats default authority differs from provider source"
                )
            semantic_role, evidence = _semantic_role_and_evidence(
                name,
                default=default,
                nullable=name in nullable_set,
                dependencies=dependencies,
                domain_kind=domain_kind,
            )
            disposition = _build_parameter_disposition(
                source_family="stats",
                endpoint_id=endpoint_id,
                ordinal=ordinal,
                name=name,
                query_name=query_map[name],
                location="query",
                required=name in required_set,
                nullable=name in nullable_set,
                has_default=has_default,
                default=default,
                default_authority=default_authority,
                default_expression=default_expression,
                value_types=value_types,
                pattern=pattern,
                domain_kind=domain_kind,
                coverage_policy=coverage_policy,
                semantic_role=semantic_role,
                dependencies=dependencies,
                evidence=evidence,
            )
            if has_default and default_authority == "provider_literal_or_required_v1":
                _validate_parameter_value(disposition, default)
            parameters.append(disposition)
        endpoint_slug = contract.get("endpoint_slug")
        request_method = contract.get("request_method")
        if not all(
            isinstance(value, str) for value in (module_name, endpoint_slug, request_method)
        ):
            raise NbaApiRequestSurfaceError("runtime stats endpoint identity is invalid")
        url_template = stats_endpoint_url_template(cast("str", endpoint_slug))
        surfaces.append(
            EndpointRequestSurface(
                source_family="stats",
                endpoint_id=endpoint_id,
                module_name=cast("str", module_name),
                endpoint_slug=cast("str", endpoint_slug),
                url_template=url_template,
                request_method=cast("str", request_method),
                parameters=tuple(parameters),
                constraint_edges=_parameter_constraint_edges(tuple(parameters)),
            )
        )
    return surfaces


def _live_endpoint_surfaces(runtime: Mapping[str, object]) -> list[EndpointRequestSurface]:
    contracts = runtime.get("live_contracts")
    if not isinstance(contracts, dict) or not contracts:
        raise NbaApiRequestSurfaceError("runtime live contracts are absent")
    surfaces: list[EndpointRequestSurface] = []
    for endpoint_id, raw_contract in sorted(contracts.items()):
        if not isinstance(endpoint_id, str) or not isinstance(raw_contract, dict):
            raise NbaApiRequestSurfaceError("runtime live contract is invalid")
        contract = cast("dict[str, Any]", raw_contract)
        raw_parameters = contract.get("parameters")
        if not isinstance(raw_parameters, list):
            raise NbaApiRequestSurfaceError("runtime live parameters are invalid")
        module_name = contract.get("runtime_module")
        class_name = contract.get("endpoint_id")
        raw_names = [
            parameter.get("name") if isinstance(parameter, dict) else None
            for parameter in raw_parameters
        ]
        if (
            not isinstance(module_name, str)
            or not isinstance(class_name, str)
            or any(not isinstance(name, str) for name in raw_names)
        ):
            raise NbaApiRequestSurfaceError("runtime live class identity is invalid")
        default_expressions = _constructor_default_expressions(
            module_name,
            class_name,
            cast("list[str]", raw_names),
        )
        parameters: list[ParameterDomainDisposition] = []
        for raw_parameter in raw_parameters:
            if not isinstance(raw_parameter, dict):
                raise NbaApiRequestSurfaceError("runtime live parameter is invalid")
            parameter = cast("dict[str, Any]", raw_parameter)
            name = parameter.get("name")
            query_name = parameter.get("query_name")
            ordinal = parameter.get("ordinal")
            required = parameter.get("required")
            nullable = parameter.get("nullable")
            has_default = parameter.get("has_default")
            location = parameter.get("location")
            pattern = parameter.get("pattern")
            if (
                not isinstance(name, str)
                or not isinstance(query_name, str)
                or isinstance(ordinal, bool)
                or not isinstance(ordinal, int)
                or type(required) is not bool
                or type(nullable) is not bool
                or type(has_default) is not bool
                or location not in {"query", "path"}
                or (pattern is not None and not isinstance(pattern, str))
            ):
                raise NbaApiRequestSurfaceError("runtime live parameter fields are invalid")
            domain_kind, coverage_policy, dependencies = _classify_parameter(name)
            raw_default = cast("EvidenceValue", parameter.get("default"))
            value_types = _parameter_value_types(name, default=raw_default, pattern=pattern)
            default, default_authority, default_expression = _normalize_parameter_default(
                source_expression=default_expressions[name],
                has_default=has_default,
                raw_default=raw_default,
            )
            semantic_role, evidence = _semantic_role_and_evidence(
                name,
                default=default,
                nullable=nullable,
                dependencies=dependencies,
                domain_kind=domain_kind,
            )
            disposition = _build_parameter_disposition(
                source_family="live",
                endpoint_id=endpoint_id,
                ordinal=ordinal,
                name=name,
                query_name=query_name,
                location=cast("ParameterLocation", location),
                required=required,
                nullable=nullable,
                has_default=has_default,
                default=default,
                default_authority=default_authority,
                default_expression=default_expression,
                value_types=value_types,
                pattern=pattern,
                domain_kind=domain_kind,
                coverage_policy=coverage_policy,
                semantic_role=semantic_role,
                dependencies=dependencies,
                evidence=evidence,
            )
            if has_default and default_authority == "provider_literal_or_required_v1":
                _validate_parameter_value(disposition, default)
            parameters.append(disposition)
        endpoint_slug = contract.get("endpoint_slug")
        full_url_template = contract.get("full_url_template")
        request_method = contract.get("request_method")
        if not all(
            isinstance(value, str)
            for value in (module_name, endpoint_slug, full_url_template, request_method)
        ):
            raise NbaApiRequestSurfaceError("runtime live endpoint identity is invalid")
        surfaces.append(
            EndpointRequestSurface(
                source_family="live",
                endpoint_id=endpoint_id,
                module_name=cast("str", module_name),
                endpoint_slug=cast("str", endpoint_slug),
                url_template=cast("str", full_url_template),
                request_method=cast("str", request_method),
                parameters=tuple(parameters),
                constraint_edges=_parameter_constraint_edges(tuple(parameters)),
            )
        )
    return surfaces


def _static_surfaces(
    runtime: Mapping[str, object],
) -> tuple[list[StaticDatasetSurface], list[StaticHelperSurface]]:
    raw_contracts = runtime.get("static_contracts")
    if not isinstance(raw_contracts, dict) or set(raw_contracts) != {
        "static_players",
        "static_teams",
        "static_wnba_players",
        "static_wnba_teams",
    }:
        raise NbaApiRequestSurfaceError("runtime static dataset inventory is invalid")
    contracts = cast("dict[str, object]", raw_contracts)
    datasets: list[StaticDatasetSurface] = []
    helpers: list[StaticHelperSurface] = []
    dataset_digests: dict[str, str] = {}
    for short_name in ("players", "teams"):
        module_name = f"nba_api.stats.static.{short_name}"
        try:
            module = importlib.import_module(module_name)
        except Exception as exc:
            raise NbaApiRequestSurfaceError("static helper module import failed") from exc
        public_functions = [
            (name, function)
            for name, function in inspect.getmembers(module, inspect.isfunction)
            if function.__module__ == module_name and not name.startswith("_")
        ]
        if not public_functions:
            raise NbaApiRequestSurfaceError("static helper module has no public functions")
        for is_wnba in (False, True):
            dataset_id = f"static_{'wnba_' if is_wnba else ''}{short_name}"
            contract = contracts[dataset_id]
            if not isinstance(contract, dict):
                raise NbaApiRequestSurfaceError("static dataset contract is invalid")
            source_symbol = contract.get("source_symbol")
            runtime_digest = contract.get("source_rows_sha256")
            runtime_row_count = contract.get("row_count")
            if (
                not isinstance(source_symbol, str)
                or not isinstance(runtime_digest, str)
                or isinstance(runtime_row_count, bool)
                or not isinstance(runtime_row_count, int)
            ):
                raise NbaApiRequestSurfaceError("static dataset contract body evidence is invalid")
            raw_rows = getattr(module, source_symbol, None)
            if not isinstance(raw_rows, list) or not raw_rows:
                raise NbaApiRequestSurfaceError("static embedded dataset body is unavailable")
            if any(not isinstance(row, list | tuple) or not row for row in raw_rows):
                raise NbaApiRequestSurfaceError("static embedded dataset rows are invalid")
            row_widths = {len(row) for row in raw_rows}
            if len(row_widths) != 1:
                raise NbaApiRequestSurfaceError("static embedded dataset rows are ragged")
            body_digest = _sha256(raw_rows)
            if len(raw_rows) != runtime_row_count or body_digest != runtime_digest:
                raise NbaApiRequestSurfaceError(
                    "static embedded dataset body differs from runtime contract evidence"
                )
            dataset_digests[dataset_id] = body_digest
            datasets.append(
                StaticDatasetSurface(
                    dataset_id=dataset_id,
                    module_name=module_name,
                    source_symbol=source_symbol,
                    row_count=len(raw_rows),
                    row_width=next(iter(row_widths)),
                    embedded_body_sha256=body_digest,
                    runtime_source_rows_sha256=runtime_digest,
                )
            )
        for function_name, function in public_functions:
            is_wnba = "wnba" in function_name
            dataset_id = f"static_{'wnba_' if is_wnba else ''}{short_name}"
            contract = contracts[dataset_id]
            if not isinstance(contract, dict):
                raise NbaApiRequestSurfaceError("static helper dataset contract is invalid")
            # Request-surface capture owns every exact embedded array.  Output-model
            # disposition is a separate concern and cannot exclude the WNBA bodies.
            scope_status: StaticScopeStatus = "in_scope"
            full_getter = f"get_{'wnba_' if is_wnba else ''}{short_name}"
            if function_name == full_getter:
                helper_kind: StaticHelperKind = "dataset_projection"
            elif function_name.startswith("get_"):
                helper_kind = "filtered_projection"
            elif function_name.startswith("find_"):
                helper_kind = "finder_alias"
            else:
                raise NbaApiRequestSurfaceError("static public function is unclassified")
            try:
                signature = inspect.signature(function)
            except (TypeError, ValueError) as exc:
                raise NbaApiRequestSurfaceError("static helper signature is unavailable") from exc
            parameters = tuple(signature.parameters)
            required_parameters = tuple(
                parameter.name
                for parameter in signature.parameters.values()
                if parameter.default is inspect.Parameter.empty
            )
            helpers.append(
                StaticHelperSurface(
                    helper_id=f"{short_name}.{function_name}",
                    module_name=module_name,
                    function_name=function_name,
                    dataset_id=dataset_id,
                    helper_kind=helper_kind,
                    scope_status=scope_status,
                    embedded_body_sha256=dataset_digests[dataset_id],
                    parameters=parameters,
                    required_parameters=required_parameters,
                )
            )
    return datasets, helpers


def _validate_dynamic_default_inventory(
    endpoints: Sequence[EndpointRequestSurface],
) -> None:
    observed = Counter(
        parameter.default_expression
        for endpoint in endpoints
        for parameter in endpoint.parameters
        if parameter.default_authority == "provider_dynamic_default_expression_v1"
    )
    if dict(sorted(observed.items())) != _EXPECTED_DYNAMIC_DEFAULT_EXPRESSION_COUNTS:
        raise NbaApiRequestSurfaceError(
            "provider dynamic-default expression inventory differs from the exact pin"
        )


def _domain_evidence_payload(evidence: ParameterDomainEvidence) -> dict[str, object]:
    return {
        "evidence_kind": evidence.evidence_kind,
        "authority": evidence.authority,
        "dependencies": list(evidence.dependencies),
        "finite_values": list(evidence.finite_values),
        "minimum": evidence.minimum,
        "maximum": evidence.maximum,
        "neutral_value_present": evidence.neutral_value_present,
        "neutral_value": evidence.neutral_value,
        "terminal_condition": evidence.terminal_condition,
    }


def _parameter_payload(parameter: ParameterDomainDisposition) -> dict[str, object]:
    return {
        "ordinal": parameter.ordinal,
        "occurrence_id": parameter.occurrence_id,
        "name": parameter.name,
        "query_name": parameter.query_name,
        "location": parameter.location,
        "required": parameter.required,
        "nullable": parameter.nullable,
        "has_default": parameter.has_default,
        "default": parameter.default,
        "default_authority": parameter.default_authority,
        "default_expression": parameter.default_expression,
        "value_types": list(parameter.value_types),
        "pattern": parameter.pattern,
        "domain_kind": parameter.domain_kind,
        "coverage_policy": parameter.coverage_policy,
        "semantic_role": parameter.semantic_role,
        "dependencies": list(parameter.dependencies),
        "evidence": [
            {
                **_domain_evidence_payload(item),
                "evidence_sha256": item.evidence_sha256,
            }
            for item in parameter.evidence
        ],
        "source_signature_sha256": parameter.source_signature_sha256,
        "typed_domain_sha256": parameter.typed_domain_sha256,
    }


def _canonical_parameter_occurrences(
    authority: RequestSurfaceAuthority,
) -> list[dict[str, object]]:
    return [
        {
            "source_family": endpoint.source_family,
            "endpoint_id": endpoint.endpoint_id,
            **_parameter_payload(parameter),
        }
        for endpoint in authority.endpoints
        for parameter in endpoint.parameters
    ]


def _parameter_constraint_graph_payload(
    authority: RequestSurfaceAuthority,
) -> dict[str, object]:
    edges = tuple(
        sorted(
            (edge for endpoint in authority.endpoints for edge in endpoint.constraint_edges),
            key=_constraint_sort_key,
        )
    )
    nodes = tuple(
        sorted(
            {
                *(
                    parameter.occurrence_id
                    for endpoint in authority.endpoints
                    for parameter in endpoint.parameters
                ),
                *(edge.source_node for edge in edges),
                *(edge.target_node for edge in edges),
            }
        )
    )
    _validate_parameter_constraint_graph(nodes, edges)
    edge_payloads = [
        {
            **_parameter_constraint_payload(edge),
            "constraint_sha256": edge.constraint_sha256,
        }
        for edge in edges
    ]
    body: dict[str, object] = {
        "schema_version": 1,
        "kind": "nba_api_parameter_constraint_graph",
        "nodes": list(nodes),
        "nodes_sha256": _sha256(list(nodes)),
        "edges": edge_payloads,
        "edges_sha256": _sha256(edge_payloads),
    }
    body["graph_sha256"] = _sha256(body)
    return body


def _authority_payload(authority: RequestSurfaceAuthority) -> dict[str, object]:
    return {
        "runtime_contract_payload_sha256": authority.runtime_contract_payload_sha256,
        "terminal_policy_sha256": authority.terminal_policy_sha256,
        "endpoints": [
            {
                "source_family": endpoint.source_family,
                "endpoint_id": endpoint.endpoint_id,
                "module_name": endpoint.module_name,
                "endpoint_slug": endpoint.endpoint_slug,
                "url_template": endpoint.url_template,
                "request_method": endpoint.request_method,
                "parameters": [_parameter_payload(parameter) for parameter in endpoint.parameters],
                "constraint_edges": [
                    {
                        **_parameter_constraint_payload(edge),
                        "constraint_sha256": edge.constraint_sha256,
                    }
                    for edge in endpoint.constraint_edges
                ],
            }
            for endpoint in authority.endpoints
        ],
        "static_datasets": [
            {
                "dataset_id": dataset.dataset_id,
                "module_name": dataset.module_name,
                "source_symbol": dataset.source_symbol,
                "row_count": dataset.row_count,
                "row_width": dataset.row_width,
                "embedded_body_sha256": dataset.embedded_body_sha256,
                "runtime_source_rows_sha256": dataset.runtime_source_rows_sha256,
            }
            for dataset in authority.static_datasets
        ],
        "static_helpers": [
            {
                "helper_id": helper.helper_id,
                "module_name": helper.module_name,
                "function_name": helper.function_name,
                "dataset_id": helper.dataset_id,
                "helper_kind": helper.helper_kind,
                "scope_status": helper.scope_status,
                "embedded_body_sha256": helper.embedded_body_sha256,
                "parameters": list(helper.parameters),
                "required_parameters": list(helper.required_parameters),
            }
            for helper in authority.static_helpers
        ],
    }


def _derivation_policy_payload() -> dict[str, object]:
    return {
        "version": REQUEST_SURFACE_DERIVATION_POLICY_VERSION,
        "bounded_numeric_ranges": {
            name: [minimum, maximum]
            for name, (minimum, maximum) in sorted(_BOUNDED_NUMERIC_RANGES.items())
        },
        "bounded_numeric_parameters": sorted(_BOUNDED_NUMERIC_PARAMETERS),
        "explicit_value_parameters": sorted(_EXPLICIT_VALUE_PARAMETERS),
        "dependency_ids": sorted(_DEPENDENCY_IDS),
        "domain_kinds": sorted(_DOMAIN_KINDS),
        "coverage_policies": sorted(_COVERAGE_POLICIES),
        "parameter_occurrence_identity": "source_family_endpoint_ordinal_name_v1",
        "typed_domain_authority": "source_signature_plus_domain_evidence_v1",
        "default_authorities": [
            "provider_dynamic_default_expression_v1",
            "provider_literal_or_required_v1",
        ],
        "dynamic_default_expression_counts": dict(
            sorted(_EXPECTED_DYNAMIC_DEFAULT_EXPRESSION_COUNTS.items())
        ),
        "dynamic_default_omission_policy": "explicit_scope_value_required_v1",
        "constraint_kinds": [
            "authorized_by",
            "lower_lte_upper_if_both_present",
        ],
        "parameter_order_constraints": [list(item) for item in _PARAMETER_ORDER_CONSTRAINTS],
        "constraint_graph_rule": "canonical_acyclic_exact_dependency_graph_v1",
        "terminal_policy_sha256": _terminal_policy_sha256(),
        "release_terminal_request_states": list(_RELEASE_TERMINAL_REQUEST_STATES),
        "incomplete_request_states": list(_INCOMPLETE_REQUEST_STATES),
        "terminal_evidence_kinds": dict(_terminal_policy_binding()[1]),
        "terminal_state_partition": "terminal_policy_authoritative_v1",
        "reserved_authorities": _reserved_authorities(),
        "request_serialization": {
            "query": "ordered_urlencode_quote_plus_omit_null_v1",
            "path": "utf8_percent_encode_no_safe_chars_v1",
        },
        "scope_axis_wire_grammars": {
            "calendar_date": ["YYYY-MM-DD", "MM/DD/YYYY"],
            "league_id": "exactly_two_ascii_digits",
            "season_id": "exactly_five_ascii_digits",
            "season_label": "consecutive_YYYY-YY",
            "year": "exactly_four_ascii_digits",
            "finite_temporal_parameters": sorted(_FINITE_TEMPORAL_PARAMETERS),
        },
        "pagination_rule": "contiguous_from_zero_with_exactly_one_terminal_max_page_v1",
        "static_scope": "all_nba_and_wnba_embedded_arrays_v1",
    }


@lru_cache(maxsize=1)
def _derivation_policy_sha256() -> str:
    return _sha256(_derivation_policy_payload())


def _request_surface_manifest(authority: RequestSurfaceAuthority) -> dict[str, object]:
    return {
        "terminal_policy_sha256": authority.terminal_policy_sha256,
        "endpoint_contracts": [
            {
                "source_family": endpoint.source_family,
                "endpoint_id": endpoint.endpoint_id,
                "module_name": endpoint.module_name,
                "endpoint_slug": endpoint.endpoint_slug,
                "url_template": endpoint.url_template,
                "request_method": endpoint.request_method,
                "parameter_count": len(endpoint.parameters),
                "parameters_sha256": _sha256(
                    [_parameter_payload(parameter) for parameter in endpoint.parameters]
                ),
                "constraint_edge_count": len(endpoint.constraint_edges),
                "constraint_edges_sha256": _sha256(
                    [_parameter_constraint_payload(edge) for edge in endpoint.constraint_edges]
                ),
            }
            for endpoint in authority.endpoints
        ],
        "static_datasets": [
            {
                "dataset_id": dataset.dataset_id,
                "module_name": dataset.module_name,
                "source_symbol": dataset.source_symbol,
                "row_count": dataset.row_count,
                "row_width": dataset.row_width,
                "embedded_body_sha256": dataset.embedded_body_sha256,
            }
            for dataset in authority.static_datasets
        ],
        "static_helpers": [
            {
                "helper_id": helper.helper_id,
                "dataset_id": helper.dataset_id,
                "helper_kind": helper.helper_kind,
                "scope_status": helper.scope_status,
                "embedded_body_sha256": helper.embedded_body_sha256,
                "parameters": list(helper.parameters),
                "required_parameters": list(helper.required_parameters),
            }
            for helper in authority.static_helpers
        ],
    }


@lru_cache(maxsize=1)
def build_request_surface_authority() -> RequestSurfaceAuthority:
    """Rebuild the full no-network request surface from exact pinned inputs."""

    runtime = load_pinned_runtime_contract_payload()
    runtime_digest = runtime.get("payload_sha256")
    if not isinstance(runtime_digest, str):
        raise NbaApiRequestSurfaceError("runtime contract payload digest is absent")
    endpoints = _stats_endpoint_surfaces(runtime)
    endpoints.extend(_live_endpoint_surfaces(runtime))
    _validate_dynamic_default_inventory(endpoints)
    static_datasets, static_helpers = _static_surfaces(runtime)
    return RequestSurfaceAuthority(
        runtime_contract_payload_sha256=runtime_digest,
        terminal_policy_sha256=_terminal_policy_sha256(),
        endpoints=tuple(sorted(endpoints, key=lambda item: (item.source_family, item.endpoint_id))),
        static_datasets=tuple(sorted(static_datasets, key=lambda item: item.dataset_id)),
        static_helpers=tuple(sorted(static_helpers, key=lambda item: item.helper_id)),
    )


def _request_surface_summary(authority: RequestSurfaceAuthority) -> dict[str, object]:
    occurrences = _canonical_parameter_occurrences(authority)
    constraint_graph = _parameter_constraint_graph_payload(authority)
    domain_counts = {
        kind: sum(
            parameter.domain_kind == kind
            for endpoint in authority.endpoints
            for parameter in endpoint.parameters
        )
        for kind in sorted(_DOMAIN_KINDS)
    }
    names = sorted(
        {parameter.name for endpoint in authority.endpoints for parameter in endpoint.parameters}
    )
    semantic_role_counts = {
        role: sum(
            parameter.semantic_role == role
            for endpoint in authority.endpoints
            for parameter in endpoint.parameters
        )
        for role in (
            "bounded_control",
            "discovery_key",
            "finite_selector",
            "neutral_filter",
            "pagination_cursor",
            "scope_axis",
        )
    }
    evidence_kind_counts = {
        kind: sum(
            item.evidence_kind == kind
            for endpoint in authority.endpoints
            for parameter in endpoint.parameters
            for item in parameter.evidence
        )
        for kind in (
            "bounded_interval",
            "discovered_inventory",
            "explicit_scope_inventory",
            "neutral_value",
            "pagination_until_terminal",
            "provider_finite_values",
            "scope_inventory",
        )
    }
    return {
        "stats_endpoint_count": sum(
            endpoint.source_family == "stats" for endpoint in authority.endpoints
        ),
        "live_endpoint_count": sum(
            endpoint.source_family == "live" for endpoint in authority.endpoints
        ),
        "parameter_occurrence_count": authority.parameter_occurrence_count,
        "typed_parameter_domain_count": authority.parameter_occurrence_count,
        "source_signature_count": authority.parameter_occurrence_count,
        "parameter_name_count": authority.parameter_name_count,
        "parameter_name_inventory_sha256": _sha256(names),
        "parameter_occurrence_inventory_sha256": _sha256(occurrences),
        "typed_domain_inventory_sha256": _sha256(
            [
                parameter.typed_domain_sha256
                for endpoint in authority.endpoints
                for parameter in endpoint.parameters
            ]
        ),
        "source_signature_inventory_sha256": _sha256(
            [
                parameter.source_signature_sha256
                for endpoint in authority.endpoints
                for parameter in endpoint.parameters
            ]
        ),
        "parameter_constraint_node_count": len(cast("list[object]", constraint_graph["nodes"])),
        "parameter_constraint_edge_count": authority.parameter_constraint_edge_count,
        "parameter_constraint_graph_sha256": constraint_graph["graph_sha256"],
        "domain_kind_counts": domain_counts,
        "semantic_role_counts": semantic_role_counts,
        "evidence_kind_counts": evidence_kind_counts,
        "static_dataset_count": len(authority.static_datasets),
        "static_embedded_row_count": sum(
            dataset.row_count for dataset in authority.static_datasets
        ),
        "static_dataset_inventory_sha256": _sha256(
            [
                {
                    "dataset_id": dataset.dataset_id,
                    "row_count": dataset.row_count,
                    "row_width": dataset.row_width,
                    "embedded_body_sha256": dataset.embedded_body_sha256,
                }
                for dataset in authority.static_datasets
            ]
        ),
        "static_helper_count": len(authority.static_helpers),
        "in_scope_static_helper_count": sum(
            helper.scope_status == "in_scope" for helper in authority.static_helpers
        ),
        "out_of_scope_static_helper_count": sum(
            helper.scope_status == "out_of_scope_with_evidence"
            for helper in authority.static_helpers
        ),
        "static_helper_inventory_sha256": _sha256(
            [
                {
                    "helper_id": helper.helper_id,
                    "dataset_id": helper.dataset_id,
                    "kind": helper.helper_kind,
                    "scope": helper.scope_status,
                    "parameters": list(helper.parameters),
                }
                for helper in authority.static_helpers
            ]
        ),
    }


def build_pinned_request_surface_payload() -> dict[str, object]:
    """Build the checked-in occurrence and constraint authority receipt."""

    authority = build_request_surface_authority()
    manifest = _request_surface_manifest(authority)
    parameter_occurrences = _canonical_parameter_occurrences(authority)
    constraint_graph = _parameter_constraint_graph_payload(authority)
    payload: dict[str, object] = {
        "schema_version": REQUEST_SURFACE_SCHEMA_VERSION,
        "kind": "nbadb_pinned_nba_api_request_surface",
        "derivation_policy_version": REQUEST_SURFACE_DERIVATION_POLICY_VERSION,
        "derivation_policy_sha256": _derivation_policy_sha256(),
        "runtime_contract_payload_sha256": authority.runtime_contract_payload_sha256,
        "terminal_policy_sha256": authority.terminal_policy_sha256,
        "domain_kinds": sorted(_DOMAIN_KINDS),
        "dependency_ids": sorted(_DEPENDENCY_IDS),
        "release_terminal_request_states": list(_RELEASE_TERMINAL_REQUEST_STATES),
        "incomplete_request_states": list(_INCOMPLETE_REQUEST_STATES),
        "terminal_evidence_kinds": dict(_terminal_policy_binding()[1]),
        "reserved_authorities": _reserved_authorities(),
        "summary": _request_surface_summary(authority),
        "parameter_occurrences": parameter_occurrences,
        "parameter_occurrences_sha256": _sha256(parameter_occurrences),
        "parameter_constraint_graph": constraint_graph,
        "manifest": manifest,
        "manifest_sha256": _sha256(manifest),
        "surface_sha256": authority.surface_sha256,
        "independent_proof": {
            "required": True,
            "schema_version": 1,
            "kind": "independent_package_rebuilder_receipt",
            "claim_status": "not_supplied_by_this_artifact",
        },
    }
    payload["payload_sha256"] = _sha256(payload)
    return payload


def write_pinned_request_surface(path: Path, *, check: bool = False) -> bool:
    """Write or check the canonical compact request-surface resource."""

    encoded = _canonical_json_bytes(build_pinned_request_surface_payload()) + b"\n"
    if path.is_file() and path.read_bytes() == encoded:
        return True
    if check:
        raise NbaApiRequestSurfaceError("pinned nba_api request surface has generated drift")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(encoded)
    return False


def _reject_duplicate_object(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise NbaApiRequestSurfaceError(
                f"request-surface resource contains duplicate object key: {key}"
            )
        result[key] = value
    return result


def _reject_nonfinite_constant(value: str) -> object:
    raise NbaApiRequestSurfaceError(
        f"request-surface resource contains non-finite JSON constant: {value}"
    )


def _validate_checked_parameter_authority(payload: Mapping[str, object]) -> None:
    occurrences = payload.get("parameter_occurrences")
    occurrence_digest = payload.get("parameter_occurrences_sha256")
    if not isinstance(occurrences, list) or not occurrences:
        raise NbaApiRequestSurfaceError("checked parameter authority has no occurrence inventory")
    if _require_sha256("parameter_occurrences_sha256", occurrence_digest) != _sha256(occurrences):
        raise NbaApiRequestSurfaceError("checked parameter occurrence inventory digest is invalid")
    occurrence_ids: list[str] = []
    for raw_occurrence in occurrences:
        if not isinstance(raw_occurrence, dict):
            raise NbaApiRequestSurfaceError("checked parameter occurrence is not an object")
        occurrence = cast("dict[str, object]", raw_occurrence)
        occurrence_id = occurrence.get("occurrence_id")
        if not isinstance(occurrence_id, str):
            raise NbaApiRequestSurfaceError("checked parameter occurrence identity is invalid")
        _require_safe_id("checked parameter occurrence_id", occurrence_id)
        _require_sha256(
            "checked parameter source_signature_sha256",
            occurrence.get("source_signature_sha256"),
        )
        _require_sha256(
            "checked parameter typed_domain_sha256",
            occurrence.get("typed_domain_sha256"),
        )
        evidence = occurrence.get("evidence")
        if not isinstance(evidence, list) or not evidence:
            raise NbaApiRequestSurfaceError(
                "checked parameter occurrence lacks typed domain evidence"
            )
        occurrence_ids.append(occurrence_id)
    if len(occurrence_ids) != len(set(occurrence_ids)):
        raise NbaApiRequestSurfaceError("checked parameter occurrence identities are not unique")

    raw_graph = payload.get("parameter_constraint_graph")
    if not isinstance(raw_graph, dict) or set(raw_graph) != {
        "schema_version",
        "kind",
        "nodes",
        "nodes_sha256",
        "edges",
        "edges_sha256",
        "graph_sha256",
    }:
        raise NbaApiRequestSurfaceError("checked parameter constraint graph is invalid")
    graph = cast("dict[str, object]", raw_graph)
    graph_body = dict(graph)
    graph_digest = graph_body.pop("graph_sha256")
    if _require_sha256("constraint graph_sha256", graph_digest) != _sha256(graph_body):
        raise NbaApiRequestSurfaceError("checked parameter constraint graph digest is invalid")
    raw_nodes = graph.get("nodes")
    raw_edges = graph.get("edges")
    if not isinstance(raw_nodes, list) or not all(isinstance(node, str) for node in raw_nodes):
        raise NbaApiRequestSurfaceError("checked parameter constraint nodes are invalid")
    nodes = tuple(cast("list[str]", raw_nodes))
    if _require_sha256("constraint nodes_sha256", graph.get("nodes_sha256")) != _sha256(
        list(nodes)
    ):
        raise NbaApiRequestSurfaceError("checked parameter constraint node digest is invalid")
    if not isinstance(raw_edges, list):
        raise NbaApiRequestSurfaceError("checked parameter constraint edges are invalid")
    edges: list[ParameterConstraintEdge] = []
    for raw_edge in raw_edges:
        if not isinstance(raw_edge, dict) or set(raw_edge) != {
            "source_node",
            "target_node",
            "constraint_kind",
            "authority",
            "constraint_sha256",
        }:
            raise NbaApiRequestSurfaceError("checked parameter constraint edge is invalid")
        edge_payload = dict(raw_edge)
        constraint_digest = edge_payload.pop("constraint_sha256")
        if _require_sha256("constraint_sha256", constraint_digest) != _sha256(edge_payload):
            raise NbaApiRequestSurfaceError("checked parameter constraint edge digest is invalid")
        try:
            edge = ParameterConstraintEdge(
                source_node=cast("str", edge_payload["source_node"]),
                target_node=cast("str", edge_payload["target_node"]),
                constraint_kind=cast(
                    "ParameterConstraintKind",
                    edge_payload["constraint_kind"],
                ),
                authority=cast("str", edge_payload["authority"]),
            )
        except (KeyError, TypeError) as exc:
            raise NbaApiRequestSurfaceError(
                "checked parameter constraint edge fields are invalid"
            ) from exc
        edges.append(edge)
    edge_payloads = [
        {
            **_parameter_constraint_payload(edge),
            "constraint_sha256": edge.constraint_sha256,
        }
        for edge in edges
    ]
    if _require_sha256("constraint edges_sha256", graph.get("edges_sha256")) != _sha256(
        edge_payloads
    ):
        raise NbaApiRequestSurfaceError("checked parameter constraint edge digest is invalid")
    _validate_parameter_constraint_graph(nodes, tuple(edges))
    if not set(occurrence_ids) <= set(nodes):
        raise NbaApiRequestSurfaceError("checked constraint graph omits parameter occurrences")
    if payload.get("reserved_authorities") != _reserved_authorities():
        raise NbaApiRequestSurfaceError("checked reserved authority disposition is invalid")


def load_pinned_request_surface_payload(path: Path | None = None) -> dict[str, object]:
    """Load and independently reproduce the compact request-surface receipt."""

    if path is None:
        raw = resources.files("nbadb.contracts").joinpath(REQUEST_SURFACE_RESOURCE).read_bytes()
    else:
        try:
            raw = path.read_bytes()
        except (AttributeError, OSError) as exc:
            raise NbaApiRequestSurfaceError("request-surface resource cannot be read") from exc
    try:
        text = raw.decode("utf-8", errors="strict")
        payload = json.loads(
            text,
            object_pairs_hook=_reject_duplicate_object,
            parse_constant=_reject_nonfinite_constant,
        )
    except NbaApiRequestSurfaceError:
        raise
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise NbaApiRequestSurfaceError("request-surface resource cannot be decoded") from exc
    if not isinstance(payload, dict):
        raise NbaApiRequestSurfaceError("request-surface resource must be an object")
    if raw != _canonical_json_bytes(payload) + b"\n":
        raise NbaApiRequestSurfaceError("request-surface resource bytes are not canonical JSON")
    expected_fields = {
        "schema_version",
        "kind",
        "derivation_policy_version",
        "derivation_policy_sha256",
        "runtime_contract_payload_sha256",
        "terminal_policy_sha256",
        "domain_kinds",
        "dependency_ids",
        "release_terminal_request_states",
        "incomplete_request_states",
        "terminal_evidence_kinds",
        "reserved_authorities",
        "summary",
        "parameter_occurrences",
        "parameter_occurrences_sha256",
        "parameter_constraint_graph",
        "manifest",
        "manifest_sha256",
        "surface_sha256",
        "independent_proof",
        "payload_sha256",
    }
    if set(payload) != expected_fields:
        raise NbaApiRequestSurfaceError("request-surface resource fields do not match schema")
    body = dict(payload)
    digest = body.pop("payload_sha256")
    if _require_sha256("payload_sha256", digest) != _sha256(body):
        raise NbaApiRequestSurfaceError("request-surface resource digest is invalid")
    _validate_checked_parameter_authority(payload)
    expected = build_pinned_request_surface_payload()
    if payload != expected:
        raise NbaApiRequestSurfaceError(
            "request-surface resource differs from the exact pinned package surface"
        )
    return cast("dict[str, object]", payload)


@lru_cache(maxsize=1)
def pinned_request_surface_authority() -> RequestSurfaceAuthority:
    """Return the reproduced authority after its checked receipt validates."""

    load_pinned_request_surface_payload()
    return build_request_surface_authority()


def _materialize_request_components(
    endpoint: EndpointRequestSurface,
    parameters: Mapping[str, object],
    *,
    request_surface_sha256: str,
    runtime_contract_payload_sha256: str,
) -> tuple[tuple[tuple[str, EvidenceValue], ...], str, str, str, str]:
    if not isinstance(parameters, Mapping) or any(not isinstance(name, str) for name in parameters):
        raise NbaApiRequestSurfaceError("request parameters must be a string-keyed mapping")
    supplied = dict(parameters)
    expected_names = {parameter.name for parameter in endpoint.parameters}
    if set(supplied) - expected_names:
        raise NbaApiRequestSurfaceError("request contains unknown endpoint parameters")

    materialized: list[tuple[str, EvidenceValue]] = []
    query_pairs: list[tuple[str, str]] = []
    path_values: dict[str, str] = {}
    for parameter in endpoint.parameters:
        if parameter.name in supplied:
            raw_value = supplied[parameter.name]
        elif parameter.default_authority == "provider_dynamic_default_expression_v1":
            raise NbaApiRequestSurfaceError(
                "request omitted a dynamic provider default; explicit scope value is required"
            )
        elif parameter.has_default:
            raw_value = parameter.default
        else:
            raise NbaApiRequestSurfaceError("request omitted a required endpoint parameter")
        value = _validate_parameter_value(parameter, raw_value)
        materialized.append((parameter.name, value))
        if parameter.location == "path":
            if value is None:
                raise NbaApiRequestSurfaceError("path parameters cannot serialize null")
            path_values[parameter.name] = quote(str(value), safe="", encoding="utf-8")
        elif value is not None:
            query_pairs.append((parameter.query_name, str(value)))

    _validate_materialized_parameter_constraints(endpoint, dict(materialized))

    full_url = endpoint.url_template
    for name, value in sorted(path_values.items()):
        full_url = full_url.replace(f"{{{name}}}", value)
    if _PATH_TOKEN_RE.search(full_url) is not None:
        raise NbaApiRequestSurfaceError("request path contains an unmaterialized token")
    query_string = urlencode(query_pairs, doseq=False)
    if query_string:
        full_url = f"{full_url}?{query_string}"
    path_start = full_url.find("/", len("https://"))
    if path_start < 0:
        raise NbaApiRequestSurfaceError("materialized provider URL has no absolute path")
    url_path = full_url[path_start:].split("?", 1)[0]
    wire_authority = {
        "request_surface_sha256": request_surface_sha256,
        "derivation_policy_sha256": _derivation_policy_sha256(),
        "runtime_contract_payload_sha256": runtime_contract_payload_sha256,
        "source_family": endpoint.source_family,
        "endpoint_id": endpoint.endpoint_id,
        "request_method": endpoint.request_method,
        "url_path": url_path,
        "query_string": query_string,
    }
    return (
        tuple(materialized),
        url_path,
        query_string,
        full_url,
        _sha256(wire_authority),
    )


@dataclass(frozen=True, slots=True)
class CanonicalProviderRequest:
    """Exact materialized NBA provider request plus its authority-bound key."""

    request_surface_sha256: str
    runtime_contract_payload_sha256: str
    source_family: SourceFamily
    endpoint_id: str
    request_method: str
    url_path: str
    query_string: str
    full_url: str
    materialized_parameters: tuple[tuple[str, EvidenceValue], ...]
    provider_request_sha256: str

    def __post_init__(self) -> None:
        _require_sha256("request_surface_sha256", self.request_surface_sha256)
        _require_sha256(
            "runtime_contract_payload_sha256",
            self.runtime_contract_payload_sha256,
        )
        if self.source_family not in {"stats", "live"}:
            raise NbaApiRequestSurfaceError("canonical request source_family is invalid")
        _require_safe_id("canonical request endpoint_id", self.endpoint_id)
        if self.request_method != "GET":
            raise NbaApiRequestSurfaceError("canonical request method is invalid")
        if not self.url_path.startswith("/") or not self.full_url.startswith("https://"):
            raise NbaApiRequestSurfaceError("canonical request URL is invalid")
        if type(self.materialized_parameters) is not tuple or any(
            type(item) is not tuple or len(item) != 2 or not isinstance(item[0], str)
            for item in self.materialized_parameters
        ):
            raise NbaApiRequestSurfaceError("canonical request materialized parameters are invalid")
        _require_sha256("provider_request_sha256", self.provider_request_sha256)
        authority = pinned_request_surface_authority()
        if self.request_surface_sha256 != authority.surface_sha256:
            raise NbaApiRequestSurfaceError("canonical request references a foreign surface")
        if self.runtime_contract_payload_sha256 != authority.runtime_contract_payload_sha256:
            raise NbaApiRequestSurfaceError("canonical request references a foreign runtime")
        endpoint = authority.endpoint(self.source_family, self.endpoint_id)
        parameter_names = tuple(name for name, _ in self.materialized_parameters)
        if parameter_names != tuple(parameter.name for parameter in endpoint.parameters):
            raise NbaApiRequestSurfaceError(
                "canonical request parameter inventory differs from pinned endpoint"
            )
        expected = _materialize_request_components(
            endpoint,
            dict(self.materialized_parameters),
            request_surface_sha256=authority.surface_sha256,
            runtime_contract_payload_sha256=authority.runtime_contract_payload_sha256,
        )
        observed = (
            self.materialized_parameters,
            self.url_path,
            self.query_string,
            self.full_url,
            self.provider_request_sha256,
        )
        if self.request_method != endpoint.request_method or observed != expected:
            raise NbaApiRequestSurfaceError("canonical request differs from pinned materialization")


def materialize_provider_request(
    endpoint: EndpointRequestSurface,
    parameters: Mapping[str, object],
    *,
    request_surface_sha256: str,
    runtime_contract_payload_sha256: str,
) -> CanonicalProviderRequest:
    """Validate and serialize one request against the reproduced pinned authority."""

    authority = pinned_request_surface_authority()
    if request_surface_sha256 != authority.surface_sha256:
        raise NbaApiRequestSurfaceError("request references a foreign surface authority")
    if runtime_contract_payload_sha256 != authority.runtime_contract_payload_sha256:
        raise NbaApiRequestSurfaceError("request references a foreign runtime authority")
    canonical_endpoint = authority.endpoint(endpoint.source_family, endpoint.endpoint_id)
    if endpoint != canonical_endpoint:
        raise NbaApiRequestSurfaceError("request endpoint differs from pinned authority")
    materialized, url_path, query_string, full_url, request_sha256 = (
        _materialize_request_components(
            endpoint,
            parameters,
            request_surface_sha256=authority.surface_sha256,
            runtime_contract_payload_sha256=authority.runtime_contract_payload_sha256,
        )
    )
    return CanonicalProviderRequest(
        request_surface_sha256=authority.surface_sha256,
        runtime_contract_payload_sha256=authority.runtime_contract_payload_sha256,
        source_family=endpoint.source_family,
        endpoint_id=endpoint.endpoint_id,
        request_method=endpoint.request_method,
        url_path=url_path,
        query_string=query_string,
        full_url=full_url,
        materialized_parameters=materialized,
        provider_request_sha256=request_sha256,
    )


def canonical_provider_request_key(
    endpoint: EndpointRequestSurface,
    parameters: Mapping[str, object],
    *,
    request_surface_sha256: str,
    runtime_contract_payload_sha256: str,
) -> str:
    """Hash one fully materialized provider request for proof-gated single-flight."""

    return materialize_provider_request(
        endpoint,
        parameters,
        request_surface_sha256=request_surface_sha256,
        runtime_contract_payload_sha256=runtime_contract_payload_sha256,
    ).provider_request_sha256


@dataclass(frozen=True, slots=True)
class RequestRouteBinding:
    """One exact provider request key and all concrete routes it materializes."""

    provider_request_sha256: str
    route_ids: tuple[str, ...]

    def __post_init__(self) -> None:
        _require_sha256("provider_request_sha256", self.provider_request_sha256)
        if (
            type(self.route_ids) is not tuple
            or not self.route_ids
            or self.route_ids != tuple(sorted(set(self.route_ids)))
            or any(_SAFE_ID_RE.fullmatch(route_id) is None for route_id in self.route_ids)
        ):
            raise NbaApiRequestSurfaceError("route_ids must be sorted, unique, and nonempty")


@dataclass(frozen=True, slots=True)
class RouteRequestSpec:
    """One authoritative concrete route and its exact provider parameters."""

    route_id: str
    source_family: SourceFamily
    endpoint_id: str
    parameters: tuple[tuple[str, EvidenceValue], ...]
    pagination_series_id: str | None = None
    pagination_ordinal: int | None = None
    pagination_terminal: bool = False

    def __post_init__(self) -> None:
        _require_safe_id("route_id", self.route_id)
        if self.source_family not in {"stats", "live"}:
            raise NbaApiRequestSurfaceError("route source_family is unsupported")
        _require_safe_id("route endpoint_id", self.endpoint_id)
        if type(self.parameters) is not tuple:
            raise NbaApiRequestSurfaceError("route parameters must be an exact tuple")
        names: list[str] = []
        for item in self.parameters:
            if type(item) is not tuple or len(item) != 2:
                raise NbaApiRequestSurfaceError("route parameter entry is invalid")
            name, value = item
            _require_safe_id("route parameter name", name)
            _canonical_scalar(value, field="route parameter value")
            names.append(name)
        if tuple(names) != tuple(sorted(set(names))):
            raise NbaApiRequestSurfaceError("route parameters must be name-sorted and unique")
        if type(self.pagination_terminal) is not bool:
            raise NbaApiRequestSurfaceError("pagination_terminal must be a boolean")
        if self.pagination_series_id is None:
            if self.pagination_ordinal is not None or self.pagination_terminal:
                raise NbaApiRequestSurfaceError("non-pagination route has pagination metadata")
        else:
            _require_safe_id("pagination_series_id", self.pagination_series_id)
            if self.pagination_ordinal is None:
                raise NbaApiRequestSurfaceError("pagination route has no ordinal")
            _require_nonnegative_integer("pagination_ordinal", self.pagination_ordinal)

    @property
    def parameter_mapping(self) -> dict[str, EvidenceValue]:
        return dict(self.parameters)


@dataclass(frozen=True, slots=True)
class AuthoritativeRouteManifest:
    """Registry-bound, concrete route manifest used for conservation proofs."""

    request_surface_sha256: str
    runtime_contract_payload_sha256: str
    derivation_policy_sha256: str
    registry_manifest_sha256: str
    routes: tuple[RouteRequestSpec, ...]

    def __post_init__(self) -> None:
        for field in (
            "request_surface_sha256",
            "runtime_contract_payload_sha256",
            "derivation_policy_sha256",
            "registry_manifest_sha256",
        ):
            _require_sha256(field, getattr(self, field))
        if (
            type(self.routes) is not tuple
            or not self.routes
            or any(not isinstance(route, RouteRequestSpec) for route in self.routes)
            or tuple(route.route_id for route in self.routes)
            != tuple(sorted({route.route_id for route in self.routes}))
        ):
            raise NbaApiRequestSurfaceError(
                "route manifest routes must be route-id sorted, unique, and nonempty"
            )
        if self.registry_manifest_sha256 != _sha256(
            [_route_spec_payload(route) for route in self.routes]
        ):
            raise NbaApiRequestSurfaceError(
                "registry manifest digest differs from its concrete route inventory"
            )
        series: dict[str, list[RouteRequestSpec]] = defaultdict(list)
        for route in self.routes:
            if route.pagination_series_id is not None:
                series[route.pagination_series_id].append(route)
        for series_id, pages in series.items():
            ordinals = sorted(cast("int", page.pagination_ordinal) for page in pages)
            if ordinals != list(range(len(ordinals))) or len(ordinals) != len(set(ordinals)):
                raise NbaApiRequestSurfaceError(
                    f"pagination series {series_id} is truncated or has duplicate pages"
                )
            terminals = [
                cast("int", page.pagination_ordinal) for page in pages if page.pagination_terminal
            ]
            if terminals != [ordinals[-1]]:
                raise NbaApiRequestSurfaceError(
                    f"pagination series {series_id} lacks one exact terminal max page"
                )

    @property
    def manifest_sha256(self) -> str:
        return _sha256(_route_manifest_payload(self))


def _route_spec_payload(route: RouteRequestSpec) -> dict[str, object]:
    return {
        "route_id": route.route_id,
        "source_family": route.source_family,
        "endpoint_id": route.endpoint_id,
        "parameters": [[name, value] for name, value in route.parameters],
        "pagination_series_id": route.pagination_series_id,
        "pagination_ordinal": route.pagination_ordinal,
        "pagination_terminal": route.pagination_terminal,
    }


def _route_manifest_payload(manifest: AuthoritativeRouteManifest) -> dict[str, object]:
    return {
        "request_surface_sha256": manifest.request_surface_sha256,
        "runtime_contract_payload_sha256": manifest.runtime_contract_payload_sha256,
        "derivation_policy_sha256": manifest.derivation_policy_sha256,
        "registry_manifest_sha256": manifest.registry_manifest_sha256,
        "routes": [_route_spec_payload(route) for route in manifest.routes],
    }


def require_route_conservation(
    manifest: AuthoritativeRouteManifest,
    bindings: Sequence[RequestRouteBinding],
) -> None:
    """Recompute every route binding from the exact pinned provider authority."""

    authority = pinned_request_surface_authority()
    if (
        manifest.request_surface_sha256 != authority.surface_sha256
        or manifest.runtime_contract_payload_sha256 != authority.runtime_contract_payload_sha256
        or manifest.derivation_policy_sha256 != _derivation_policy_sha256()
    ):
        raise NbaApiRequestSurfaceError("route manifest references a foreign authority")
    expected_by_request: dict[str, list[str]] = defaultdict(list)
    for route in manifest.routes:
        endpoint = authority.endpoint(route.source_family, route.endpoint_id)
        pagination_parameters = tuple(
            parameter
            for parameter in endpoint.parameters
            if parameter.semantic_role == "pagination_cursor"
        )
        requires_pagination = bool(pagination_parameters)
        if requires_pagination != (route.pagination_series_id is not None):
            raise NbaApiRequestSurfaceError(
                "route pagination metadata disagrees with endpoint authority"
            )
        materialized = materialize_provider_request(
            endpoint,
            route.parameter_mapping,
            request_surface_sha256=manifest.request_surface_sha256,
            runtime_contract_payload_sha256=manifest.runtime_contract_payload_sha256,
        )
        if requires_pagination:
            if len(pagination_parameters) != 1:
                raise NbaApiRequestSurfaceError(
                    "pagination route does not have one exact cursor authority"
                )
            cursor_value = dict(materialized.materialized_parameters)[pagination_parameters[0].name]
            if (
                route.pagination_ordinal is None
                or _numeric_value(pagination_parameters[0], cursor_value)
                != route.pagination_ordinal
            ):
                raise NbaApiRequestSurfaceError(
                    "pagination route ordinal differs from its serialized cursor"
                )
        expected_by_request[materialized.provider_request_sha256].append(route.route_id)
    expected_bindings = tuple(
        RequestRouteBinding(
            provider_request_sha256=request_key,
            route_ids=tuple(sorted(route_ids)),
        )
        for request_key, route_ids in sorted(expected_by_request.items())
    )
    if type(bindings) is not tuple or any(
        not isinstance(binding, RequestRouteBinding) for binding in bindings
    ):
        raise NbaApiRequestSurfaceError("route bindings must be an exact tuple")
    if tuple(bindings) != expected_bindings:
        raise NbaApiRequestSurfaceError(
            "materialized route bindings are not independently conserved"
        )
    observed = {route_id for binding in bindings for route_id in binding.route_ids}
    if observed != {route.route_id for route in manifest.routes}:
        raise NbaApiRequestSurfaceError("materialized route inventory is not conserved")


def _canonical_sha256_tuple(
    values: object,
    *,
    field: str,
    allow_empty: bool = False,
) -> tuple[str, ...]:
    if type(values) is not tuple:
        raise NbaApiRequestSurfaceError(f"{field} must be an exact tuple")
    result = values
    if any(not isinstance(value, str) or _SHA256_RE.fullmatch(value) is None for value in result):
        raise NbaApiRequestSurfaceError(f"{field} contains a noncanonical SHA-256")
    canonical = cast("tuple[str, ...]", result)
    if (not allow_empty and not canonical) or canonical != tuple(sorted(set(canonical))):
        raise NbaApiRequestSurfaceError(
            f"{field} must be sorted, unique, and {'possibly empty' if allow_empty else 'nonempty'}"
        )
    return canonical


@dataclass(frozen=True, slots=True)
class RequestScopeDimension:
    """Actual finite scope values and the authority that supplied them."""

    dependency_id: str
    source_kind: str
    source_authority_sha256: str
    values: tuple[EvidenceValue, ...]
    endpoint_id: str | None = None
    parameter_name: str | None = None

    def __post_init__(self) -> None:
        if self.dependency_id not in _DEPENDENCY_IDS:
            raise NbaApiRequestSurfaceError("scope dimension dependency_id is unknown")
        _require_safe_id("scope dimension source_kind", self.source_kind)
        _require_sha256("scope dimension source_authority_sha256", self.source_authority_sha256)
        _canonical_scalar_tuple(self.values, field="scope dimension values")
        if self.endpoint_id is not None:
            _require_safe_id("scope dimension endpoint_id", self.endpoint_id)
        if self.parameter_name is not None:
            _require_safe_id("scope dimension parameter_name", self.parameter_name)
        if (self.endpoint_id is None) != (self.parameter_name is None):
            raise NbaApiRequestSurfaceError(
                "parameter-specific scope must bind endpoint and parameter together"
            )

    @property
    def dimension_sha256(self) -> str:
        return _sha256(
            {
                "dependency_id": self.dependency_id,
                "source_kind": self.source_kind,
                "source_authority_sha256": self.source_authority_sha256,
                "values": list(self.values),
                "endpoint_id": self.endpoint_id,
                "parameter_name": self.parameter_name,
            }
        )


@dataclass(frozen=True, slots=True)
class RequestScopeManifest:
    """Versioned finite scope with explicit seed routes and typed dimensions."""

    request_surface_sha256: str
    scope_id: str
    seed_route_ids: tuple[str, ...]
    dimensions: tuple[RequestScopeDimension, ...]

    def __post_init__(self) -> None:
        _require_sha256("scope request_surface_sha256", self.request_surface_sha256)
        _require_safe_id("scope_id", self.scope_id)
        if (
            type(self.seed_route_ids) is not tuple
            or not self.seed_route_ids
            or self.seed_route_ids != tuple(sorted(set(self.seed_route_ids)))
            or any(_SAFE_ID_RE.fullmatch(item) is None for item in self.seed_route_ids)
        ):
            raise NbaApiRequestSurfaceError(
                "scope seed_route_ids must be sorted, unique, and nonempty"
            )
        if (
            type(self.dimensions) is not tuple
            or not self.dimensions
            or any(not isinstance(item, RequestScopeDimension) for item in self.dimensions)
            or tuple(item.dimension_sha256 for item in self.dimensions)
            != tuple(sorted({item.dimension_sha256 for item in self.dimensions}))
        ):
            raise NbaApiRequestSurfaceError(
                "scope dimensions must be digest-sorted, unique, and nonempty"
            )

    @property
    def scope_sha256(self) -> str:
        return _sha256(
            {
                "request_surface_sha256": self.request_surface_sha256,
                "scope_id": self.scope_id,
                "seed_route_ids": list(self.seed_route_ids),
                "dimensions": [
                    {
                        "dependency_id": item.dependency_id,
                        "source_kind": item.source_kind,
                        "source_authority_sha256": item.source_authority_sha256,
                        "values": list(item.values),
                        "endpoint_id": item.endpoint_id,
                        "parameter_name": item.parameter_name,
                    }
                    for item in self.dimensions
                ],
            }
        )

    def authorizes_filter(
        self,
        endpoint_id: str,
        parameter_name: str,
        value: EvidenceValue,
    ) -> bool:
        return any(
            dimension.dependency_id == "explicit_scope_manifest"
            and dimension.endpoint_id == endpoint_id
            and dimension.parameter_name == parameter_name
            and any(_canonical_scalar_equal(value, candidate) for candidate in dimension.values)
            for dimension in self.dimensions
        )

    def authorizes_parameter(
        self,
        endpoint_id: str,
        parameter_name: str,
        dependencies: tuple[str, ...],
        value: EvidenceValue,
    ) -> bool:
        return any(
            dimension.dependency_id in dependencies
            and (
                dimension.endpoint_id is None
                or (
                    dimension.endpoint_id == endpoint_id
                    and dimension.parameter_name == parameter_name
                )
            )
            and any(_canonical_scalar_equal(value, candidate) for candidate in dimension.values)
            for dimension in self.dimensions
        )


@dataclass(frozen=True, slots=True)
class RequestExpansionEvidence:
    """Typed evidence whose concrete discoveries exactly explain one delta."""

    evidence_id: str
    evidence_kind: ExpansionEvidenceKind
    request_surface_sha256: str
    scope_sha256: str
    input_units: tuple[str, ...]
    discovered_units: tuple[str, ...]
    source_values: tuple[EvidenceValue, ...]
    complete: bool
    pagination_ordinals: tuple[int, ...] = ()
    pagination_terminal_ordinal: int | None = None

    def __post_init__(self) -> None:
        _require_safe_id("expansion evidence_id", self.evidence_id)
        if self.evidence_kind not in {
            "seed",
            "scope_expansion",
            "discovered_identifiers",
            "pagination_expansion",
            "fixed_point",
        }:
            raise NbaApiRequestSurfaceError("expansion evidence_kind is unsupported")
        _require_sha256("expansion request_surface_sha256", self.request_surface_sha256)
        _require_sha256("expansion scope_sha256", self.scope_sha256)
        _canonical_sha256_tuple(
            self.input_units,
            field="expansion input_units",
            allow_empty=True,
        )
        _canonical_sha256_tuple(
            self.discovered_units,
            field="expansion discovered_units",
            allow_empty=True,
        )
        _canonical_scalar_tuple(
            self.source_values,
            field="expansion source_values",
            allow_empty=self.evidence_kind == "fixed_point",
        )
        if type(self.complete) is not bool:
            raise NbaApiRequestSurfaceError("expansion complete must be a boolean")
        if self.evidence_kind == "fixed_point":
            if self.discovered_units or not self.complete:
                raise NbaApiRequestSurfaceError(
                    "fixed-point evidence must be complete with zero discoveries"
                )
        elif not self.discovered_units:
            raise NbaApiRequestSurfaceError(
                "non-fixed expansion evidence must explain concrete discoveries"
            )
        if self.evidence_kind == "pagination_expansion":
            if (
                type(self.pagination_ordinals) is not tuple
                or not self.pagination_ordinals
                or any(
                    isinstance(item, bool) or not isinstance(item, int) or item < 0
                    for item in self.pagination_ordinals
                )
                or self.pagination_ordinals != tuple(range(len(self.pagination_ordinals)))
                or self.pagination_terminal_ordinal != self.pagination_ordinals[-1]
                or not self.complete
            ):
                raise NbaApiRequestSurfaceError(
                    "pagination evidence is truncated or lacks its terminal page"
                )
        elif self.pagination_ordinals or self.pagination_terminal_ordinal is not None:
            raise NbaApiRequestSurfaceError("non-pagination evidence carries pagination metadata")

    @property
    def evidence_sha256(self) -> str:
        return _sha256(
            {
                "evidence_id": self.evidence_id,
                "evidence_kind": self.evidence_kind,
                "request_surface_sha256": self.request_surface_sha256,
                "scope_sha256": self.scope_sha256,
                "input_units": list(self.input_units),
                "discovered_units": list(self.discovered_units),
                "source_values": list(self.source_values),
                "complete": self.complete,
                "pagination_ordinals": list(self.pagination_ordinals),
                "pagination_terminal_ordinal": self.pagination_terminal_ordinal,
            }
        )


@dataclass(frozen=True, slots=True)
class RequestClosureIteration:
    """One recomputable set-union step in a request least fixed point."""

    iteration: int
    request_surface_sha256: str
    scope_sha256: str
    input_units: tuple[str, ...]
    new_units: tuple[str, ...]
    output_units: tuple[str, ...]
    evidence: tuple[RequestExpansionEvidence, ...]

    def __post_init__(self) -> None:
        _require_nonnegative_integer("iteration", self.iteration)
        _require_sha256("iteration request_surface_sha256", self.request_surface_sha256)
        _require_sha256("iteration scope_sha256", self.scope_sha256)
        for field in ("input_units", "new_units", "output_units"):
            _canonical_sha256_tuple(
                getattr(self, field),
                field=f"iteration {field}",
                allow_empty=field != "output_units",
            )
        if set(self.input_units) & set(self.new_units):
            raise NbaApiRequestSurfaceError(
                "request closure additions are not disjoint from prior units"
            )
        if set(self.output_units) != set(self.input_units) | set(self.new_units):
            raise NbaApiRequestSurfaceError(
                "request closure output is not the exact input-plus-delta union"
            )
        if (
            type(self.evidence) is not tuple
            or not self.evidence
            or any(not isinstance(item, RequestExpansionEvidence) for item in self.evidence)
            or tuple(item.evidence_sha256 for item in self.evidence)
            != tuple(sorted({item.evidence_sha256 for item in self.evidence}))
        ):
            raise NbaApiRequestSurfaceError(
                "iteration evidence must be digest-sorted, unique, and nonempty"
            )
        discovered: list[str] = []
        for item in self.evidence:
            if (
                item.request_surface_sha256 != self.request_surface_sha256
                or item.scope_sha256 != self.scope_sha256
                or item.input_units != self.input_units
            ):
                raise NbaApiRequestSurfaceError(
                    "iteration evidence is unrelated to its scope or input set"
                )
            discovered.extend(item.discovered_units)
        if len(discovered) != len(set(discovered)) or set(discovered) != set(self.new_units):
            raise NbaApiRequestSurfaceError(
                "iteration evidence does not exactly and uniquely explain its delta"
            )
        if not self.new_units and not any(
            item.evidence_kind == "fixed_point" and item.complete for item in self.evidence
        ):
            raise NbaApiRequestSurfaceError(
                "zero-growth iteration lacks complete fixed-point evidence"
            )

    @property
    def input_unit_count(self) -> int:
        return len(self.input_units)

    @property
    def input_units_sha256(self) -> str:
        return _sha256(list(self.input_units))

    @property
    def new_unit_count(self) -> int:
        return len(self.new_units)

    @property
    def output_unit_count(self) -> int:
        return len(self.output_units)

    @property
    def output_units_sha256(self) -> str:
        return _sha256(list(self.output_units))


@dataclass(frozen=True, slots=True)
class RequestTerminalEvidence:
    """One actual request-unit outcome with typed, non-digest-only evidence."""

    request_binding: TerminalRequestBinding
    state: TerminalRequestState
    evidence_kind: TerminalEvidenceKind
    evidence_values: tuple[tuple[str, EvidenceValue], ...]
    upstream_unavailable_evidence: TypedUpstreamUnavailableEvidence | None = None

    def __post_init__(self) -> None:
        if type(self.request_binding) is not TerminalRequestBinding:
            raise NbaApiRequestSurfaceError("terminal request binding is invalid")
        if self.state not in _REQUEST_ACCOUNTING_STATES:
            raise NbaApiRequestSurfaceError("terminal evidence state is unsupported")
        if self.evidence_kind != _TERMINAL_EVIDENCE_KINDS[self.state]:
            raise NbaApiRequestSurfaceError("terminal state and typed evidence kind disagree")
        _terminal_policy_binding()
        if type(self.evidence_values) is not tuple:
            raise NbaApiRequestSurfaceError("terminal evidence_values must be an exact tuple")
        names: list[str] = []
        for item in self.evidence_values:
            if type(item) is not tuple or len(item) != 2:
                raise NbaApiRequestSurfaceError("terminal evidence value entry is invalid")
            name, value = item
            _require_safe_id("terminal evidence value name", name)
            _canonical_scalar(value, field="terminal evidence value")
            names.append(name)
        if tuple(names) != tuple(sorted(set(names))):
            raise NbaApiRequestSurfaceError(
                "terminal evidence values must be name-sorted and unique"
            )
        values = dict(self.evidence_values)
        pagination_fields = {
            "pagination_ordinal",
            "pagination_terminal",
            "pagination_termination_reason",
        }
        required_fields: dict[TerminalRequestState, set[str]] = {
            "success_nonempty": {
                "decoded_results_receipt_sha256",
                "http_status",
                "persistence_receipt_sha256",
                "response_body_sha256",
                "result_occurrence",
                "row_count",
            },
            "success_empty": {
                "decoded_results_receipt_sha256",
                "http_status",
                "persistence_receipt_sha256",
                "response_body_sha256",
                "result_occurrence",
                "row_count",
            },
            "upstream_unavailable": set(),
            "contract_blocked": {"contract_evidence_sha256", "reason_code"},
            "transient_failed": {"attempt_count", "failure_class"},
            "response_contract_failed": {"failure_class", "response_body_sha256"},
            "unattempted": {"reason_code"},
            "unclassified": {"classification_input_sha256"},
        }
        if set(values) - pagination_fields != required_fields[self.state]:
            raise NbaApiRequestSurfaceError(
                "terminal evidence fields do not match the accounting-state contract"
            )
        if self.state == "upstream_unavailable":
            typed = self.upstream_unavailable_evidence
            if (
                type(typed) is not TypedUpstreamUnavailableEvidence
                or typed.request_binding != self.request_binding
                or typed.state != self.state
            ):
                raise NbaApiRequestSurfaceError(
                    "upstream unavailable state lacks exact typed request-bound evidence"
                )
        elif self.upstream_unavailable_evidence is not None:
            raise NbaApiRequestSurfaceError(
                "typed upstream-unavailable evidence is valid only for that state"
            )
        if self.state in {"success_nonempty", "success_empty"}:
            status = values.get("http_status")
            row_count = values.get("row_count")
            expected_occurrence = (
                "present_nonempty" if self.state == "success_nonempty" else "present_empty"
            )
            if (
                status != 200
                or isinstance(row_count, bool)
                or not isinstance(row_count, int)
                or row_count < 0
                or values.get("result_occurrence") != expected_occurrence
                or any(
                    not isinstance(values.get(field), str)
                    or _SHA256_RE.fullmatch(cast("str", values.get(field))) is None
                    for field in (
                        "decoded_results_receipt_sha256",
                        "persistence_receipt_sha256",
                        "response_body_sha256",
                    )
                )
                or (self.state == "success_nonempty" and row_count == 0)
                or (self.state == "success_empty" and row_count != 0)
            ):
                raise NbaApiRequestSurfaceError(
                    "provider response evidence is incomplete or contradicts its state"
                )
        elif self.state == "upstream_unavailable":
            if set(values) - pagination_fields:
                raise NbaApiRequestSurfaceError(
                    "typed upstream-unavailable evidence cannot contain scalar evidence"
                )
        elif self.state == "contract_blocked":
            reason = values.get("reason_code")
            receipt_digest = values.get("contract_evidence_sha256")
            if (
                not isinstance(reason, str)
                or _SAFE_ID_RE.fullmatch(reason) is None
                or not isinstance(receipt_digest, str)
                or _SHA256_RE.fullmatch(receipt_digest) is None
            ):
                raise NbaApiRequestSurfaceError(
                    "classified terminal evidence lacks its exact typed receipt"
                )
        elif self.state in {"transient_failed", "response_contract_failed"}:
            failure_class = values.get("failure_class")
            if not isinstance(failure_class, str) or _SAFE_ID_RE.fullmatch(failure_class) is None:
                raise NbaApiRequestSurfaceError("failure evidence lacks a safe failure class")
            if self.state == "transient_failed":
                attempt_count = values.get("attempt_count")
                if (
                    isinstance(attempt_count, bool)
                    or not isinstance(attempt_count, int)
                    or attempt_count <= 0
                ):
                    raise NbaApiRequestSurfaceError(
                        "transient evidence lacks a positive attempt count"
                    )
            else:
                response_digest = values.get("response_body_sha256")
                if (
                    not isinstance(response_digest, str)
                    or _SHA256_RE.fullmatch(response_digest) is None
                ):
                    raise NbaApiRequestSurfaceError(
                        "response-contract evidence lacks the observed body digest"
                    )
        elif self.state == "unattempted":
            reason = values.get("reason_code")
            if not isinstance(reason, str) or _SAFE_ID_RE.fullmatch(reason) is None:
                raise NbaApiRequestSurfaceError("unattempted evidence lacks a reason code")
        else:
            classification_digest = values.get("classification_input_sha256")
            if (
                not isinstance(classification_digest, str)
                or _SHA256_RE.fullmatch(classification_digest) is None
            ):
                raise NbaApiRequestSurfaceError(
                    "unclassified evidence lacks its classification input digest"
                )

    @property
    def provider_request_sha256(self) -> str:
        return self.request_binding.provider_request_sha256

    def to_dict(self) -> dict[str, object]:
        return {
            "request_binding": self.request_binding.to_dict(),
            "state": self.state,
            "evidence_kind": self.evidence_kind,
            "evidence_values": [list(item) for item in self.evidence_values],
            "upstream_unavailable_evidence": (
                None
                if self.upstream_unavailable_evidence is None
                else self.upstream_unavailable_evidence.to_dict()
            ),
        }

    @property
    def evidence_sha256(self) -> str:
        return _sha256(self.to_dict())


@dataclass(frozen=True, slots=True)
class IndependentClosureProof:
    """Receipt produced by an implementation distinct from this primary builder."""

    verifier_id: str
    request_surface_sha256: str
    scope_sha256: str
    route_manifest_sha256: str
    unit_inventory_sha256: str
    terminal_inventory_sha256: str

    def __post_init__(self) -> None:
        _require_safe_id("independent verifier_id", self.verifier_id)
        if self.verifier_id == "nbadb_request_surface_primary_v2":
            raise NbaApiRequestSurfaceError("independent verifier cannot be the primary builder")
        for field in (
            "request_surface_sha256",
            "scope_sha256",
            "route_manifest_sha256",
            "unit_inventory_sha256",
            "terminal_inventory_sha256",
        ):
            _require_sha256(field, getattr(self, field))


@dataclass(frozen=True, slots=True)
class RequestClosureReceipt:
    """Actual-set conservation proof for one finite, registry-bound scope."""

    request_surface_sha256: str
    scope: RequestScopeManifest
    route_manifest: AuthoritativeRouteManifest
    bindings: tuple[RequestRouteBinding, ...]
    iterations: tuple[RequestClosureIteration, ...]
    terminal_evidence: tuple[RequestTerminalEvidence, ...]
    independent_proof: IndependentClosureProof | None = None

    def __post_init__(self) -> None:
        authority = pinned_request_surface_authority()
        if (
            self.request_surface_sha256 != authority.surface_sha256
            or self.scope.request_surface_sha256 != authority.surface_sha256
            or self.route_manifest.request_surface_sha256 != authority.surface_sha256
        ):
            raise NbaApiRequestSurfaceError("closure references a foreign surface authority")
        require_route_conservation(self.route_manifest, self.bindings)
        route_ids = {route.route_id for route in self.route_manifest.routes}
        if not set(self.scope.seed_route_ids) <= route_ids:
            raise NbaApiRequestSurfaceError("closure seed routes are absent from route manifest")
        if (
            type(self.iterations) is not tuple
            or len(self.iterations) < 2
            or any(not isinstance(item, RequestClosureIteration) for item in self.iterations)
            or tuple(item.iteration for item in self.iterations)
            != tuple(range(len(self.iterations)))
        ):
            raise NbaApiRequestSurfaceError(
                "closure iterations must be a contiguous tuple with a fixed-point step"
            )
        if self.iterations[0].input_units:
            raise NbaApiRequestSurfaceError("closure must begin from an empty unit set")
        for item in self.iterations:
            if (
                item.request_surface_sha256 != authority.surface_sha256
                or item.scope_sha256 != self.scope.scope_sha256
            ):
                raise NbaApiRequestSurfaceError(
                    "closure iteration is unrelated to its surface or scope"
                )
        for previous, current in zip(self.iterations, self.iterations[1:], strict=False):
            if current.input_units != previous.output_units:
                raise NbaApiRequestSurfaceError("request closure iteration chain is discontinuous")
        expected_units = tuple(sorted(binding.provider_request_sha256 for binding in self.bindings))
        if self.iterations[-1].output_units != expected_units:
            raise NbaApiRequestSurfaceError(
                "closure fixed point differs from independently recomputed route units"
            )
        if self.iterations[-1].new_units:
            raise NbaApiRequestSurfaceError("closure has not reached a zero-growth fixed point")

        seed_route_ids = set(self.scope.seed_route_ids)
        seed_units = tuple(
            sorted(
                binding.provider_request_sha256
                for binding in self.bindings
                if seed_route_ids & set(binding.route_ids)
            )
        )
        seed_evidence_units = tuple(
            sorted(
                unit
                for item in self.iterations[0].evidence
                if item.evidence_kind == "seed"
                for unit in item.discovered_units
            )
        )
        if seed_evidence_units != seed_units:
            raise NbaApiRequestSurfaceError(
                "closure seed evidence differs from scope-bound seed routes"
            )

        dependency_ids = {dimension.dependency_id for dimension in self.scope.dimensions}
        for route in self.route_manifest.routes:
            endpoint = authority.endpoint(route.source_family, route.endpoint_id)
            materialized = materialize_provider_request(
                endpoint,
                route.parameter_mapping,
                request_surface_sha256=authority.surface_sha256,
                runtime_contract_payload_sha256=authority.runtime_contract_payload_sha256,
            )
            materialized_map = dict(materialized.materialized_parameters)
            for parameter in endpoint.parameters:
                if not set(parameter.dependencies) <= dependency_ids:
                    raise NbaApiRequestSurfaceError("closure scope omits a parameter dependency")
                neutral = _parameter_evidence(parameter, "neutral_value")
                value = materialized_map[parameter.name]
                is_neutral = neutral is not None and value == neutral.neutral_value
                if not is_neutral and not self.scope.authorizes_parameter(
                    endpoint.endpoint_id,
                    parameter.name,
                    parameter.dependencies,
                    value,
                ):
                    raise NbaApiRequestSurfaceError(
                        "materialized request value is absent from its typed scope evidence"
                    )
                if parameter.semantic_role != "neutral_filter":
                    continue
                assert neutral is not None
                if not is_neutral and not self.scope.authorizes_filter(
                    endpoint.endpoint_id,
                    parameter.name,
                    value,
                ):
                    raise NbaApiRequestSurfaceError(
                        "non-neutral filter lacks parameter-specific scope evidence"
                    )

        if (
            type(self.terminal_evidence) is not tuple
            or any(not isinstance(item, RequestTerminalEvidence) for item in self.terminal_evidence)
            or tuple(item.provider_request_sha256 for item in self.terminal_evidence)
            != expected_units
        ):
            raise NbaApiRequestSurfaceError(
                "terminal evidence must account for each request unit exactly once"
            )
        route_by_id = {route.route_id: route for route in self.route_manifest.routes}
        binding_by_request = {binding.provider_request_sha256: binding for binding in self.bindings}
        for item in self.terminal_evidence:
            request_binding = item.request_binding
            route_binding = binding_by_request[item.provider_request_sha256]
            if (
                request_binding.request_surface_sha256 != authority.surface_sha256
                or request_binding.runtime_contract_payload_sha256
                != authority.runtime_contract_payload_sha256
                or request_binding.route_manifest_sha256 != self.route_manifest.manifest_sha256
                or request_binding.scope_sha256 != self.scope.scope_sha256
                or request_binding.route_ids != route_binding.route_ids
            ):
                raise NbaApiRequestSurfaceError(
                    "terminal request binding rebinds its closure authority or route unit"
                )
            endpoint_keys = {
                (route_by_id[route_id].source_family, route_by_id[route_id].endpoint_id)
                for route_id in request_binding.route_ids
            }
            if endpoint_keys != {(request_binding.source_family, request_binding.endpoint_id)}:
                raise NbaApiRequestSurfaceError(
                    "terminal request binding rebinds its endpoint routes"
                )
        request_by_route = {
            route_id: binding.provider_request_sha256
            for binding in self.bindings
            for route_id in binding.route_ids
        }
        terminal_by_request = {
            item.provider_request_sha256: item for item in self.terminal_evidence
        }
        for route in self.route_manifest.routes:
            if route.pagination_series_id is None:
                continue
            terminal_item = terminal_by_request[request_by_route[route.route_id]]
            values = dict(terminal_item.evidence_values)
            if (
                values.get("pagination_ordinal") != route.pagination_ordinal
                or values.get("pagination_terminal") is not route.pagination_terminal
            ):
                raise NbaApiRequestSurfaceError(
                    "pagination outcome evidence disagrees with its route page"
                )
            termination_reason = values.get("pagination_termination_reason")
            if route.pagination_terminal:
                if termination_reason not in {
                    "declared_total",
                    "empty_page",
                    "short_page",
                }:
                    raise NbaApiRequestSurfaceError(
                        "terminal pagination page lacks a concrete stop reason"
                    )
            elif termination_reason is not None:
                raise NbaApiRequestSurfaceError(
                    "nonterminal pagination page declares a stop reason"
                )
        if self.independent_proof is not None:
            terminal_digest = self.terminal_inventory_sha256
            unit_digest = _sha256(list(expected_units))
            if (
                self.independent_proof.request_surface_sha256 != authority.surface_sha256
                or self.independent_proof.scope_sha256 != self.scope.scope_sha256
                or self.independent_proof.route_manifest_sha256
                != self.route_manifest.manifest_sha256
                or self.independent_proof.unit_inventory_sha256 != unit_digest
                or self.independent_proof.terminal_inventory_sha256 != terminal_digest
            ):
                raise NbaApiRequestSurfaceError(
                    "independent closure proof is unrelated to the recomputed inventories"
                )

    @property
    def scope_sha256(self) -> str:
        return self.scope.scope_sha256

    @property
    def unit_inventory(self) -> tuple[str, ...]:
        """Return the exact canonical provider-request fixed point."""

        return tuple(binding.provider_request_sha256 for binding in self.bindings)

    @property
    def unit_inventory_sha256(self) -> str:
        """Compatibility digest used by the independent v1 verifier receipt."""

        return _sha256(list(self.unit_inventory))

    @property
    def iteration_inventory_sha256(self) -> str:
        """Bind every actual iteration set and evidence receipt to its authority."""

        return _sha256(
            {
                "request_surface_sha256": self.request_surface_sha256,
                "runtime_contract_payload_sha256": (
                    self.route_manifest.runtime_contract_payload_sha256
                ),
                "derivation_policy_sha256": self.route_manifest.derivation_policy_sha256,
                "scope_sha256": self.scope_sha256,
                "route_manifest_sha256": self.route_manifest.manifest_sha256,
                "iterations": [
                    {
                        "iteration": item.iteration,
                        "input_units": list(item.input_units),
                        "new_units": list(item.new_units),
                        "output_units": list(item.output_units),
                        "evidence_sha256s": [
                            evidence.evidence_sha256 for evidence in item.evidence
                        ],
                    }
                    for item in self.iterations
                ],
            }
        )

    @property
    def request_binding_inventory_sha256(self) -> str:
        """Bind every full terminal request authority in provider-unit order."""

        return _sha256([item.request_binding.to_dict() for item in self.terminal_evidence])

    @property
    def terminal_inventory_sha256(self) -> str:
        return _sha256(
            [
                {
                    "provider_request_sha256": item.provider_request_sha256,
                    "state": item.state,
                    "evidence_sha256": item.evidence_sha256,
                }
                for item in self.terminal_evidence
            ]
        )

    @property
    def primary_receipt_sha256(self) -> str:
        """Digest the proof-free closure over concrete inventories and authorities."""

        return _sha256(
            {
                "schema_version": 2,
                "request_surface_sha256": self.request_surface_sha256,
                "runtime_contract_payload_sha256": (
                    self.route_manifest.runtime_contract_payload_sha256
                ),
                "terminal_policy_sha256": _terminal_policy_sha256(),
                "derivation_policy_sha256": self.route_manifest.derivation_policy_sha256,
                "scope_sha256": self.scope_sha256,
                "route_manifest_sha256": self.route_manifest.manifest_sha256,
                "bindings": [
                    {
                        "provider_request_sha256": binding.provider_request_sha256,
                        "route_ids": list(binding.route_ids),
                    }
                    for binding in self.bindings
                ],
                "unit_inventory": list(self.unit_inventory),
                "unit_inventory_sha256": self.unit_inventory_sha256,
                "request_binding_inventory": [
                    item.request_binding.to_dict() for item in self.terminal_evidence
                ],
                "request_binding_inventory_sha256": self.request_binding_inventory_sha256,
                "iteration_inventory_sha256": self.iteration_inventory_sha256,
                "terminal_inventory": [
                    {**item.to_dict(), "evidence_sha256": item.evidence_sha256}
                    for item in self.terminal_evidence
                ],
                "terminal_inventory_sha256": self.terminal_inventory_sha256,
                "unavailable_evidence_sha256": self.unavailable_evidence_sha256,
                "blocked_evidence_sha256": self.blocked_evidence_sha256,
            }
        )

    @property
    def receipt_sha256(self) -> str:
        """Digest the complete closure, including independent-verifier authority."""

        proof = self.independent_proof
        return _sha256(
            {
                "primary_receipt_sha256": self.primary_receipt_sha256,
                "independent_proof": (
                    None
                    if proof is None
                    else {
                        "verifier_id": proof.verifier_id,
                        "request_surface_sha256": proof.request_surface_sha256,
                        "scope_sha256": proof.scope_sha256,
                        "route_manifest_sha256": proof.route_manifest_sha256,
                        "unit_inventory_sha256": proof.unit_inventory_sha256,
                        "terminal_inventory_sha256": proof.terminal_inventory_sha256,
                    }
                ),
            }
        )

    @property
    def unavailable_evidence_sha256(self) -> str:
        return _sha256(
            [
                item.upstream_unavailable_evidence.unavailable_evidence_sha256
                for item in self.terminal_evidence
                if item.upstream_unavailable_evidence is not None
            ]
        )

    @property
    def blocked_evidence_sha256(self) -> str:
        return _sha256(
            [
                item.evidence_sha256
                for item in self.terminal_evidence
                if item.state == "contract_blocked"
            ]
        )

    def _state_count(self, state: str) -> int:
        return sum(item.state == state for item in self.terminal_evidence)

    @property
    def success_nonempty(self) -> int:
        return self._state_count("success_nonempty")

    @property
    def success_empty(self) -> int:
        return self._state_count("success_empty")

    @property
    def upstream_unavailable(self) -> int:
        return self._state_count("upstream_unavailable")

    @property
    def contract_blocked(self) -> int:
        return self._state_count("contract_blocked")

    @property
    def transient_failed(self) -> int:
        return self._state_count("transient_failed")

    @property
    def response_contract_failed(self) -> int:
        return self._state_count("response_contract_failed")

    @property
    def unattempted(self) -> int:
        return self._state_count("unattempted")

    @property
    def unclassified(self) -> int:
        return self._state_count("unclassified")

    @property
    def fixed_point(self) -> bool:
        final = self.iterations[-1]
        return (
            not final.new_units
            and final.input_units == final.output_units
            and any(
                item.evidence_kind == "fixed_point" and item.complete for item in final.evidence
            )
        )

    @property
    def green(self) -> bool:
        structurally_green = (
            self.fixed_point
            and self.independent_proof is not None
            and all(
                evidence.complete
                for iteration in self.iterations
                for evidence in iteration.evidence
            )
            and all(
                is_release_terminal_request_state(item.state) for item in self.terminal_evidence
            )
            and all(self._state_count(field) == 0 for field in _INCOMPLETE_REQUEST_STATES)
        )
        if not structurally_green:
            return False
        assert self.independent_proof is not None
        # A matching digest object is not independent evidence by itself.  Re-run
        # the separate AST/source verifier over a proof-free receipt before this
        # convenience property may report green.
        from nbadb.core.nba_api_request_surface_verifier import (
            verify_request_closure_independently,
        )

        try:
            verified = verify_request_closure_independently(
                replace(self, independent_proof=None),
                verifier_id=self.independent_proof.verifier_id,
            )
        except NbaApiRequestSurfaceError:
            return False
        return verified == self.independent_proof

    def require_green(self) -> None:
        if self.independent_proof is None:
            raise NbaApiRequestSurfaceError("request closure lacks the required independent proof")
        if not self.green:
            raise NbaApiRequestSurfaceError("request closure is not terminally green")
