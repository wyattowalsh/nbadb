"""Path-free production evidence for the pinned NBA API request closure.

The core request-surface module owns request materialization and fixed-point
semantics.  This module is the deliberately small adapter between that model
and future extraction/persistence wiring: it binds each terminal request to the
exact response body, decoded result sets, and persisted staging receipt roots.

No filesystem or network operation is performed here.  In particular, static
``nba_api`` datasets are not represented as fabricated HTTP requests; this
contract accepts only the pinned ``stats`` and ``live`` request families.
"""

from __future__ import annotations

import hashlib
import json
import math
import re
from collections import defaultdict
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field, replace
from typing import Any, ClassVar, Self, cast

from nbadb.core.nba_api_request_surface import (
    AuthoritativeRouteManifest,
    IndependentClosureProof,
    NbaApiRequestSurfaceError,
    RequestClosureIteration,
    RequestClosureReceipt,
    RequestExpansionEvidence,
    RequestRouteBinding,
    RequestScopeDimension,
    RequestScopeManifest,
    RequestTerminalEvidence,
    RouteRequestSpec,
    build_pinned_request_surface_payload,
    materialize_provider_request,
    pinned_request_surface_authority,
    require_route_conservation,
)
from nbadb.core.nba_api_request_surface_verifier import (
    verify_request_closure_independently,
)
from nbadb.core.nba_api_runtime_contract import (
    pinned_live_contracts,
    pinned_runtime_contracts,
)
from nbadb.core.nba_api_terminal_state import (
    INCOMPLETE_REQUEST_STATES,
    RELEASE_TERMINAL_REQUEST_STATES,
    REQUEST_ACCOUNTING_STATES,
    RESULT_OCCURRENCE_STATES,
    NbaApiTerminalStateError,
    TerminalRequestBinding,
    TypedUpstreamUnavailableEvidence,
    UpstreamUnavailableSupportAuthority,
    build_terminal_request_binding,
    build_typed_upstream_unavailable_evidence,
)

__all__ = [
    "REQUEST_CLOSURE_RUNTIME_SCHEMA_VERSION",
    "PersistedStagingReceipt",
    "RequestClosureAdapterInput",
    "RequestClosureRuntimeError",
    "RequestClosureRuntimeReceipt",
    "RequestObservation",
    "ResultSetReceipt",
    "RouteRequestSpecInput",
    "build_authoritative_route_manifest",
    "build_request_closure_runtime_receipt",
]

REQUEST_CLOSURE_RUNTIME_SCHEMA_VERSION = 2
_KIND = "nbadb_request_closure_runtime_receipt"
_SHA256_RE = re.compile(r"[0-9a-f]{64}")
_SAFE_ID_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.:-]{0,255}")
_STATES = frozenset(REQUEST_ACCOUNTING_STATES)
_RELEASE_TERMINAL_STATES = frozenset(RELEASE_TERMINAL_REQUEST_STATES)
_INCOMPLETE_STATES = frozenset(INCOMPLETE_REQUEST_STATES)
_RESULT_OCCURRENCE_STATES = frozenset(RESULT_OCCURRENCE_STATES)
_PRESENT_RESULT_OCCURRENCE_STATES = frozenset({"present_nonempty", "present_empty"})
_TERMINAL_EVIDENCE_KINDS = {
    "success_nonempty": "receipt_bound_provider_response",
    "success_empty": "receipt_bound_provider_response",
    "upstream_unavailable": "typed_upstream_unavailable_evidence",
    "contract_blocked": "implementation_or_modeled_contract_gap",
    "transient_failed": "transport_timeout_retry_vpn_or_infrastructure_failure",
    "response_contract_failed": "parser_or_response_contract_failure",
    "unattempted": "budget_cap_policy_or_scheduling_exhaustion",
    "unclassified": "classification_unknown",
}

type Scalar = str | int | float | bool | None


class RequestClosureRuntimeError(NbaApiRequestSurfaceError):
    """Fail-closed runtime receipt or canonical-codec violation."""


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
        raise RequestClosureRuntimeError("request closure is not canonical JSON") from exc


def _sha256(value: object) -> str:
    return hashlib.sha256(_canonical_json_bytes(value)).hexdigest()


def _require_sha256(value: object, *, field: str) -> str:
    if not isinstance(value, str) or _SHA256_RE.fullmatch(value) is None:
        raise RequestClosureRuntimeError(f"{field} must be a canonical SHA-256")
    return value


def _require_safe_id(value: object, *, field: str) -> str:
    if not isinstance(value, str) or _SAFE_ID_RE.fullmatch(value) is None:
        raise RequestClosureRuntimeError(f"{field} must be a safe nonempty identifier")
    return value


def _require_nonnegative_int(value: object, *, field: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise RequestClosureRuntimeError(f"{field} must be a nonnegative integer")
    return value


def _require_positive_int(value: object, *, field: str) -> int:
    result = _require_nonnegative_int(value, field=field)
    if result == 0:
        raise RequestClosureRuntimeError(f"{field} must be positive")
    return result


def _require_scalar(value: object, *, field: str) -> Scalar:
    if value is None or type(value) in {str, int, bool}:
        return cast("Scalar", value)
    if type(value) is float and math.isfinite(cast("float", value)):
        return cast("float", value)
    raise RequestClosureRuntimeError(f"{field} must be a finite JSON scalar")


def _require_exact_tuple(
    values: object,
    *,
    field: str,
    allow_empty: bool,
    key: Any,
) -> tuple[Any, ...]:
    if type(values) is not tuple:
        raise RequestClosureRuntimeError(f"{field} must be an exact tuple")
    result = cast("tuple[Any, ...]", values)
    if not allow_empty and not result:
        raise RequestClosureRuntimeError(f"{field} must be nonempty")
    canonical = tuple(sorted(result, key=key))
    if result != canonical or len(result) != len(set(result)):
        raise RequestClosureRuntimeError(f"{field} must be sorted and unique")
    return result


def _require_exact_keys(
    payload: Mapping[str, object],
    expected: set[str],
    *,
    label: str,
) -> None:
    if type(payload) is not dict or set(payload) != expected:
        raise RequestClosureRuntimeError(f"{label} has missing or unexpected fields")


def _mapping(value: object, *, field: str) -> Mapping[str, object]:
    if type(value) is not dict or any(not isinstance(key, str) for key in value):
        raise RequestClosureRuntimeError(f"{field} must be an exact string-keyed object")
    return cast("Mapping[str, object]", value)


def _list(value: object, *, field: str) -> list[object]:
    if type(value) is not list:
        raise RequestClosureRuntimeError(f"{field} must be an exact array")
    return cast("list[object]", value)


def _optional_string(value: object, *, field: str) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str):
        raise RequestClosureRuntimeError(f"{field} must be a string or null")
    return value


def _scalar_pairs(value: object, *, field: str) -> tuple[tuple[str, Scalar], ...]:
    items = _list(value, field=field)
    result: list[tuple[str, Scalar]] = []
    for item in items:
        if type(item) is not list or len(item) != 2:
            raise RequestClosureRuntimeError(f"{field} contains an invalid pair")
        name = _require_safe_id(item[0], field=f"{field} name")
        result.append((name, _require_scalar(item[1], field=f"{field} value")))
    names = tuple(name for name, _ in result)
    if names != tuple(sorted(set(names))):
        raise RequestClosureRuntimeError(f"{field} names must be sorted and unique")
    return tuple(result)


_TERMINAL_REQUEST_BINDING_FIELDS = {
    "competition_authority_sha256",
    "competition_requirement_sha256",
    "competition_scope_sha256",
    "endpoint_id",
    "provider_authority_sha256",
    "provider_request_sha256",
    "request_binding_sha256",
    "request_surface_sha256",
    "role_binding_sha256",
    "route_ids",
    "route_manifest_sha256",
    "runtime_contract_payload_sha256",
    "scope_sha256",
    "source_evidence_sha256",
    "source_family",
    "source_request_sha256",
}
_UPSTREAM_UNAVAILABLE_SUPPORT_FIELDS = {
    "authority_kind",
    "authority_version",
    "competition_scope_sha256",
    "endpoint_id",
    "independent_verifier_id",
    "independent_verifier_sha256",
    "provider_authority_sha256",
    "provider_request_sha256",
    "reason_code",
    "request_surface_sha256",
    "scope_sha256",
    "source_family",
    "source_request_sha256",
    "status",
    "support_authority_sha256",
    "support_binding_sha256",
    "support_cell_id",
    "support_cell_sha256",
}
_TYPED_UPSTREAM_UNAVAILABLE_FIELDS = {
    "request_binding",
    "state",
    "support_authority",
    "unavailable_evidence_sha256",
}


def _terminal_request_binding_payload(
    binding: TerminalRequestBinding,
) -> dict[str, object]:
    if type(binding) is not TerminalRequestBinding:
        raise RequestClosureRuntimeError(
            "request observation requires a concrete terminal request binding"
        )
    return binding.to_dict()


def _terminal_request_binding_from_payload(value: object) -> TerminalRequestBinding:
    if type(value) is not dict:
        raise RequestClosureRuntimeError("terminal request binding must be an exact object")
    payload = cast("dict[str, object]", value)
    _require_exact_keys(
        payload,
        _TERMINAL_REQUEST_BINDING_FIELDS,
        label="terminal request binding",
    )
    route_ids_value = payload["route_ids"]
    if type(route_ids_value) is not list:
        raise RequestClosureRuntimeError("terminal request route IDs must be an array")
    try:
        binding = build_terminal_request_binding(
            request_surface_sha256=cast("str", payload["request_surface_sha256"]),
            runtime_contract_payload_sha256=cast("str", payload["runtime_contract_payload_sha256"]),
            provider_authority_sha256=cast("str", payload["provider_authority_sha256"]),
            route_manifest_sha256=cast("str", payload["route_manifest_sha256"]),
            scope_sha256=cast("str", payload["scope_sha256"]),
            provider_request_sha256=cast("str", payload["provider_request_sha256"]),
            source_request_sha256=cast("str", payload["source_request_sha256"]),
            competition_authority_sha256=cast("str", payload["competition_authority_sha256"]),
            competition_scope_sha256=cast("str", payload["competition_scope_sha256"]),
            competition_requirement_sha256=cast("str", payload["competition_requirement_sha256"]),
            role_binding_sha256=cast("str", payload["role_binding_sha256"]),
            source_evidence_sha256=cast("str", payload["source_evidence_sha256"]),
            source_family=cast("str", payload["source_family"]),
            endpoint_id=cast("str", payload["endpoint_id"]),
            route_ids=tuple(cast("list[str]", route_ids_value)),
        )
    except (NbaApiTerminalStateError, TypeError) as exc:
        raise RequestClosureRuntimeError("terminal request binding is invalid") from exc
    if binding.to_dict() != payload:
        raise RequestClosureRuntimeError(
            "terminal request binding differs after exact reproduction"
        )
    return binding


def _reproduce_terminal_request_binding(
    binding: TerminalRequestBinding,
) -> TerminalRequestBinding:
    return _terminal_request_binding_from_payload(_terminal_request_binding_payload(binding))


def _upstream_unavailable_support_from_payload(
    value: object,
) -> UpstreamUnavailableSupportAuthority:
    if type(value) is not dict:
        raise RequestClosureRuntimeError(
            "upstream-unavailable support authority must be an exact object"
        )
    payload = cast("dict[str, object]", value)
    _require_exact_keys(
        payload,
        _UPSTREAM_UNAVAILABLE_SUPPORT_FIELDS,
        label="upstream-unavailable support authority",
    )
    try:
        authority = UpstreamUnavailableSupportAuthority(
            authority_kind=cast("str", payload["authority_kind"]),
            authority_version=cast("int", payload["authority_version"]),
            support_authority_sha256=cast("str", payload["support_authority_sha256"]),
            support_cell_id=cast("str", payload["support_cell_id"]),
            support_cell_sha256=cast("str", payload["support_cell_sha256"]),
            provider_authority_sha256=cast("str", payload["provider_authority_sha256"]),
            request_surface_sha256=cast("str", payload["request_surface_sha256"]),
            source_family=cast("str", payload["source_family"]),
            endpoint_id=cast("str", payload["endpoint_id"]),
            scope_sha256=cast("str", payload["scope_sha256"]),
            competition_scope_sha256=cast("str", payload["competition_scope_sha256"]),
            source_request_sha256=cast("str", payload["source_request_sha256"]),
            provider_request_sha256=cast("str", payload["provider_request_sha256"]),
            status=cast("str", payload["status"]),
            reason_code=cast("str", payload["reason_code"]),
            independent_verifier_id=cast("str", payload["independent_verifier_id"]),
            independent_verifier_sha256=cast("str", payload["independent_verifier_sha256"]),
            support_binding_sha256=cast("str", payload["support_binding_sha256"]),
        )
    except (NbaApiTerminalStateError, TypeError) as exc:
        raise RequestClosureRuntimeError(
            "upstream-unavailable support authority is invalid"
        ) from exc
    if authority.to_dict() != payload:
        raise RequestClosureRuntimeError(
            "upstream-unavailable support differs after exact reproduction"
        )
    return authority


def _typed_upstream_unavailable_payload(
    evidence: TypedUpstreamUnavailableEvidence,
) -> dict[str, object]:
    if type(evidence) is not TypedUpstreamUnavailableEvidence:
        raise RequestClosureRuntimeError(
            "upstream-unavailable state requires concrete typed evidence"
        )
    return evidence.to_dict()


def _typed_upstream_unavailable_from_payload(
    value: object,
) -> TypedUpstreamUnavailableEvidence:
    if type(value) is not dict:
        raise RequestClosureRuntimeError(
            "typed upstream-unavailable evidence must be an exact object"
        )
    payload = cast("dict[str, object]", value)
    _require_exact_keys(
        payload,
        _TYPED_UPSTREAM_UNAVAILABLE_FIELDS,
        label="typed upstream-unavailable evidence",
    )
    if payload["state"] != "upstream_unavailable":
        raise RequestClosureRuntimeError("typed upstream-unavailable evidence has a foreign state")
    request_binding = _terminal_request_binding_from_payload(payload["request_binding"])
    support_authority = _upstream_unavailable_support_from_payload(payload["support_authority"])
    try:
        evidence = build_typed_upstream_unavailable_evidence(
            request_binding,
            support_authority,
        )
    except (NbaApiTerminalStateError, TypeError) as exc:
        raise RequestClosureRuntimeError(
            "typed upstream-unavailable evidence is rebound or invalid"
        ) from exc
    if evidence.to_dict() != payload:
        raise RequestClosureRuntimeError(
            "typed upstream-unavailable evidence differs after exact reproduction"
        )
    return evidence


def _reproduce_typed_upstream_unavailable_evidence(
    evidence: TypedUpstreamUnavailableEvidence,
) -> TypedUpstreamUnavailableEvidence:
    return _typed_upstream_unavailable_from_payload(_typed_upstream_unavailable_payload(evidence))


@dataclass(frozen=True, slots=True)
class RouteRequestSpecInput:
    """Strict adapter input for one concrete runtime route/request pair."""

    route_id: str
    source_family: str
    endpoint_id: str
    parameters: tuple[tuple[str, Scalar], ...]
    pagination_series_id: str | None = None
    pagination_ordinal: int | None = None
    pagination_terminal: bool = False

    def __post_init__(self) -> None:
        # The core value object is the authority for parameter and pagination
        # semantics.  Constructing it here also rejects a synthetic static HTTP
        # family before any route manifest can be produced.
        self.to_route_spec()

    def to_route_spec(self) -> RouteRequestSpec:
        return RouteRequestSpec(
            route_id=self.route_id,
            source_family=cast("Any", self.source_family),
            endpoint_id=self.endpoint_id,
            parameters=cast("Any", self.parameters),
            pagination_series_id=self.pagination_series_id,
            pagination_ordinal=self.pagination_ordinal,
            pagination_terminal=self.pagination_terminal,
        )

    @classmethod
    def from_dict(cls, payload: Mapping[str, object]) -> Self:
        _require_exact_keys(
            payload,
            {
                "endpoint_id",
                "pagination_ordinal",
                "pagination_series_id",
                "pagination_terminal",
                "parameters",
                "route_id",
                "source_family",
            },
            label="route request input",
        )
        pagination_ordinal = payload["pagination_ordinal"]
        if pagination_ordinal is not None:
            pagination_ordinal = _require_nonnegative_int(
                pagination_ordinal,
                field="pagination_ordinal",
            )
        if type(payload["pagination_terminal"]) is not bool:
            raise RequestClosureRuntimeError("pagination_terminal must be a boolean")
        return cls(
            route_id=_require_safe_id(payload["route_id"], field="route_id"),
            source_family=cast("str", payload["source_family"]),
            endpoint_id=_require_safe_id(payload["endpoint_id"], field="endpoint_id"),
            parameters=_scalar_pairs(payload["parameters"], field="route parameters"),
            pagination_series_id=_optional_string(
                payload["pagination_series_id"],
                field="pagination_series_id",
            ),
            pagination_ordinal=pagination_ordinal,
            pagination_terminal=payload["pagination_terminal"],
        )

    def to_dict(self) -> dict[str, object]:
        return _route_payload(self.to_route_spec())


def _route_payload(route: RouteRequestSpec) -> dict[str, object]:
    return {
        "route_id": route.route_id,
        "source_family": route.source_family,
        "endpoint_id": route.endpoint_id,
        "parameters": [[name, value] for name, value in route.parameters],
        "pagination_series_id": route.pagination_series_id,
        "pagination_ordinal": route.pagination_ordinal,
        "pagination_terminal": route.pagination_terminal,
    }


def build_authoritative_route_manifest(
    routes: Sequence[RouteRequestSpecInput],
    *,
    request_surface_sha256: str | None = None,
    runtime_contract_payload_sha256: str | None = None,
) -> AuthoritativeRouteManifest:
    """Adapt exact route inputs into a manifest bound to the installed pin."""

    authority = pinned_request_surface_authority()
    surface_sha256 = request_surface_sha256 or authority.surface_sha256
    runtime_sha256 = runtime_contract_payload_sha256 or authority.runtime_contract_payload_sha256
    if (
        surface_sha256 != authority.surface_sha256
        or runtime_sha256 != authority.runtime_contract_payload_sha256
    ):
        raise RequestClosureRuntimeError("route adapter references a foreign authority")
    if isinstance(routes, str | bytes) or not isinstance(routes, Sequence):
        raise RequestClosureRuntimeError("route adapter inputs must be a sequence")
    route_inputs = tuple(routes)
    if not route_inputs or any(
        not isinstance(item, RouteRequestSpecInput) for item in route_inputs
    ):
        raise RequestClosureRuntimeError("route adapter inputs are empty or invalid")
    specs = tuple(item.to_route_spec() for item in route_inputs)
    if tuple(route.route_id for route in specs) != tuple(
        sorted({route.route_id for route in specs})
    ):
        raise RequestClosureRuntimeError("route adapter inputs must be route-id sorted and unique")
    pinned_payload = build_pinned_request_surface_payload()
    derivation_sha256 = _require_sha256(
        pinned_payload.get("derivation_policy_sha256"),
        field="derivation_policy_sha256",
    )
    manifest = AuthoritativeRouteManifest(
        request_surface_sha256=surface_sha256,
        runtime_contract_payload_sha256=runtime_sha256,
        derivation_policy_sha256=derivation_sha256,
        registry_manifest_sha256=_sha256([_route_payload(route) for route in specs]),
        routes=specs,
    )
    bindings = _materialized_bindings(manifest)
    require_route_conservation(manifest, bindings)
    return manifest


@dataclass(frozen=True, slots=True)
class ResultSetReceipt:
    """Receipt for one expected provider result-set occurrence."""

    ordinal: int
    result_set_name: str
    occurrence_state: str
    row_count: int | None
    ordered_columns_sha256: str | None
    result_set_payload_sha256: str | None

    def __post_init__(self) -> None:
        _require_nonnegative_int(self.ordinal, field="result-set ordinal")
        _require_safe_id(self.result_set_name, field="result-set name")
        if (
            not isinstance(self.occurrence_state, str)
            or self.occurrence_state not in _RESULT_OCCURRENCE_STATES
        ):
            raise RequestClosureRuntimeError("result-set occurrence state is unsupported")
        content = (
            self.row_count,
            self.ordered_columns_sha256,
            self.result_set_payload_sha256,
        )
        if self.occurrence_state == "absent_optional":
            if any(value is not None for value in content):
                raise RequestClosureRuntimeError(
                    "absent optional result cannot claim decoded content"
                )
            return
        if any(value is None for value in content):
            raise RequestClosureRuntimeError(
                "present result requires row, column, and payload receipts"
            )
        row_count = _require_nonnegative_int(
            self.row_count,
            field="result-set row_count",
        )
        _require_sha256(self.ordered_columns_sha256, field="ordered columns SHA-256")
        _require_sha256(
            self.result_set_payload_sha256,
            field="result-set payload SHA-256",
        )
        if (self.occurrence_state == "present_nonempty") != (row_count > 0):
            raise RequestClosureRuntimeError(
                "result-set occurrence state contradicts its row count"
            )

    @property
    def receipt_sha256(self) -> str:
        return _sha256(self.to_dict())

    def to_dict(self) -> dict[str, object]:
        return {
            "ordinal": self.ordinal,
            "result_set_name": self.result_set_name,
            "occurrence_state": self.occurrence_state,
            "row_count": self.row_count,
            "ordered_columns_sha256": self.ordered_columns_sha256,
            "result_set_payload_sha256": self.result_set_payload_sha256,
        }

    @classmethod
    def from_dict(cls, payload: Mapping[str, object]) -> Self:
        _require_exact_keys(
            payload,
            {
                "occurrence_state",
                "ordinal",
                "ordered_columns_sha256",
                "result_set_name",
                "result_set_payload_sha256",
                "row_count",
            },
            label="result-set receipt",
        )
        return cls(
            ordinal=_require_nonnegative_int(payload["ordinal"], field="result-set ordinal"),
            result_set_name=_require_safe_id(
                payload["result_set_name"],
                field="result-set name",
            ),
            occurrence_state=cast("str", payload["occurrence_state"]),
            row_count=(
                None
                if payload["row_count"] is None
                else _require_nonnegative_int(
                    payload["row_count"],
                    field="result-set row count",
                )
            ),
            ordered_columns_sha256=(
                None
                if payload["ordered_columns_sha256"] is None
                else _require_sha256(
                    payload["ordered_columns_sha256"],
                    field="ordered columns SHA-256",
                )
            ),
            result_set_payload_sha256=(
                None
                if payload["result_set_payload_sha256"] is None
                else _require_sha256(
                    payload["result_set_payload_sha256"],
                    field="result-set payload SHA-256",
                )
            ),
        )


@dataclass(frozen=True, slots=True)
class PersistedStagingReceipt:
    """Transaction-rooted staging receipt for one decoded result set."""

    result_set_ordinal: int
    result_set_name: str
    staging_key: str
    row_count: int
    result_set_payload_sha256: str
    staging_receipt_root_sha256: str

    def __post_init__(self) -> None:
        _require_nonnegative_int(self.result_set_ordinal, field="staging result-set ordinal")
        _require_safe_id(self.result_set_name, field="staging result-set name")
        _require_safe_id(self.staging_key, field="staging key")
        _require_nonnegative_int(self.row_count, field="staging row count")
        _require_sha256(
            self.result_set_payload_sha256,
            field="staging result-set payload SHA-256",
        )
        _require_sha256(
            self.staging_receipt_root_sha256,
            field="staging receipt root SHA-256",
        )

    @property
    def receipt_sha256(self) -> str:
        return _sha256(self.to_dict())

    def to_dict(self) -> dict[str, object]:
        return {
            "result_set_ordinal": self.result_set_ordinal,
            "result_set_name": self.result_set_name,
            "staging_key": self.staging_key,
            "row_count": self.row_count,
            "result_set_payload_sha256": self.result_set_payload_sha256,
            "staging_receipt_root_sha256": self.staging_receipt_root_sha256,
        }

    @classmethod
    def from_dict(cls, payload: Mapping[str, object]) -> Self:
        _require_exact_keys(
            payload,
            {
                "result_set_name",
                "result_set_ordinal",
                "result_set_payload_sha256",
                "row_count",
                "staging_key",
                "staging_receipt_root_sha256",
            },
            label="persisted staging receipt",
        )
        return cls(
            result_set_ordinal=_require_nonnegative_int(
                payload["result_set_ordinal"],
                field="staging result-set ordinal",
            ),
            result_set_name=_require_safe_id(
                payload["result_set_name"],
                field="staging result-set name",
            ),
            staging_key=_require_safe_id(payload["staging_key"], field="staging key"),
            row_count=_require_nonnegative_int(payload["row_count"], field="staging row count"),
            result_set_payload_sha256=_require_sha256(
                payload["result_set_payload_sha256"],
                field="staging result-set payload SHA-256",
            ),
            staging_receipt_root_sha256=_require_sha256(
                payload["staging_receipt_root_sha256"],
                field="staging receipt root SHA-256",
            ),
        )


@dataclass(frozen=True, slots=True)
class RequestObservation:
    """Compact terminal observation for one exact provider request unit."""

    request_surface_sha256: str
    route_manifest_sha256: str
    scope_sha256: str
    provider_request_sha256: str
    source_family: str
    endpoint_id: str
    route_ids: tuple[str, ...]
    request_binding: TerminalRequestBinding
    state: str
    attempt_count: int
    http_status: int | None = None
    response_body_sha256: str | None = None
    response_body_bytes: int | None = None
    parser_input_sha256: str | None = None
    pagination_termination_reason: str | None = None
    result_sets: tuple[ResultSetReceipt, ...] = ()
    staging_receipts: tuple[PersistedStagingReceipt, ...] = ()
    upstream_unavailable_evidence: TypedUpstreamUnavailableEvidence | None = None
    reason_code: str | None = None
    contract_evidence_sha256: str | None = None
    failure_class: str | None = None
    classification_input_sha256: str | None = None

    _OPTIONAL_OUTCOME_FIELDS: ClassVar[tuple[str, ...]] = (
        "reason_code",
        "contract_evidence_sha256",
        "failure_class",
        "classification_input_sha256",
    )

    def __post_init__(self) -> None:
        for label, value in (
            ("request surface SHA-256", self.request_surface_sha256),
            ("route manifest SHA-256", self.route_manifest_sha256),
            ("scope SHA-256", self.scope_sha256),
            ("provider request SHA-256", self.provider_request_sha256),
        ):
            _require_sha256(value, field=label)
        if not isinstance(self.source_family, str) or self.source_family not in {"stats", "live"}:
            raise RequestClosureRuntimeError(
                "request observation source family must be stats or live"
            )
        _require_safe_id(self.endpoint_id, field="observation endpoint")
        _require_exact_tuple(
            self.route_ids,
            field="observation route IDs",
            allow_empty=False,
            key=lambda value: value,
        )
        for route_id in self.route_ids:
            _require_safe_id(route_id, field="observation route ID")
        request_binding = _reproduce_terminal_request_binding(self.request_binding)
        if (
            request_binding.request_surface_sha256 != self.request_surface_sha256
            or request_binding.route_manifest_sha256 != self.route_manifest_sha256
            or request_binding.scope_sha256 != self.scope_sha256
            or request_binding.provider_request_sha256 != self.provider_request_sha256
            or request_binding.source_family != self.source_family
            or request_binding.endpoint_id != self.endpoint_id
            or request_binding.route_ids != self.route_ids
        ):
            raise RequestClosureRuntimeError(
                "terminal request binding is rebound to a foreign observation"
            )
        if not isinstance(self.state, str) or self.state not in _STATES:
            raise RequestClosureRuntimeError("request observation state is unsupported")
        _require_nonnegative_int(self.attempt_count, field="attempt count")
        if self.http_status is not None:
            status = _require_nonnegative_int(self.http_status, field="HTTP status")
            if status > 999:
                raise RequestClosureRuntimeError("HTTP status is out of range")
        body_fields = (
            self.response_body_sha256,
            self.response_body_bytes,
            self.parser_input_sha256,
        )
        if any(value is not None for value in body_fields):
            if any(value is None for value in body_fields):
                raise RequestClosureRuntimeError(
                    "response body digest, byte count, and parser digest are indivisible"
                )
            _require_sha256(self.response_body_sha256, field="response body SHA-256")
            _require_positive_int(self.response_body_bytes, field="response body bytes")
            _require_sha256(self.parser_input_sha256, field="parser input SHA-256")
        if self.pagination_termination_reason is not None and (
            self.pagination_termination_reason not in {"declared_total", "empty_page", "short_page"}
        ):
            raise RequestClosureRuntimeError("pagination termination reason is unsupported")
        self._validate_result_receipts()
        self._validate_state()

    def _validate_result_receipts(self) -> None:
        if type(self.result_sets) is not tuple or any(
            type(item) is not ResultSetReceipt for item in self.result_sets
        ):
            raise RequestClosureRuntimeError("result-set receipts must be an exact tuple")
        if type(self.staging_receipts) is not tuple or any(
            type(item) is not PersistedStagingReceipt for item in self.staging_receipts
        ):
            raise RequestClosureRuntimeError("staging receipts must be an exact tuple")
        if self.result_sets:
            ordinals = tuple(item.ordinal for item in self.result_sets)
            if ordinals != tuple(range(len(ordinals))):
                raise RequestClosureRuntimeError(
                    "result-set receipts must have contiguous provider ordinals"
                )
        staging_keys = tuple(item.staging_key for item in self.staging_receipts)
        expected_staging = tuple(
            sorted(
                self.staging_receipts,
                key=lambda item: (
                    item.result_set_ordinal,
                    item.staging_key,
                    item.staging_receipt_root_sha256,
                ),
            )
        )
        if self.staging_receipts != expected_staging or len(staging_keys) != len(set(staging_keys)):
            raise RequestClosureRuntimeError("staging receipts must be sorted with unique keys")
        results = {(item.ordinal, item.result_set_name): item for item in self.result_sets}
        present_results = {
            key: result
            for key, result in results.items()
            if result.occurrence_state in _PRESENT_RESULT_OCCURRENCE_STATES
        }
        staged_occurrences: list[tuple[int, str]] = []
        for receipt in self.staging_receipts:
            occurrence = (receipt.result_set_ordinal, receipt.result_set_name)
            result = present_results.get(occurrence)
            if (
                result is None
                or receipt.row_count != result.row_count
                or receipt.result_set_payload_sha256 != result.result_set_payload_sha256
            ):
                raise RequestClosureRuntimeError(
                    "staging receipt does not conserve its decoded result set"
                )
            staged_occurrences.append(occurrence)
        if len(staged_occurrences) != len(set(staged_occurrences)) or set(
            staged_occurrences
        ) != set(present_results):
            raise RequestClosureRuntimeError(
                "persistence must cover each present result occurrence exactly once"
            )

    def _validate_state(self) -> None:
        present_optional = {
            field for field in self._OPTIONAL_OUTCOME_FIELDS if getattr(self, field) is not None
        }
        typed_unavailable = self.upstream_unavailable_evidence
        if typed_unavailable is not None:
            typed_unavailable = _reproduce_typed_upstream_unavailable_evidence(typed_unavailable)
            if typed_unavailable.request_binding != self.request_binding:
                raise RequestClosureRuntimeError(
                    "upstream-unavailable evidence is rebound to a foreign request"
                )
        if (self.state == "upstream_unavailable") != (typed_unavailable is not None):
            raise RequestClosureRuntimeError(
                "typed upstream-unavailable evidence is required only for its exact state"
            )
        if self.state in {"success_nonempty", "success_empty"}:
            present_results = tuple(
                result
                for result in self.result_sets
                if result.occurrence_state in _PRESENT_RESULT_OCCURRENCE_STATES
            )
            if (
                self.attempt_count <= 0
                or self.http_status != 200
                or self.response_body_sha256 is None
                or not self.result_sets
                or not present_results
                or present_optional
            ):
                raise RequestClosureRuntimeError(
                    "successful request lacks its exact body/result-set/staging receipts"
                )
            row_count = sum(cast("int", item.row_count) for item in present_results)
            if (self.state == "success_nonempty") != (row_count > 0):
                raise RequestClosureRuntimeError(
                    "successful request state contradicts its result-set row count"
                )
            return
        if self.result_sets or self.staging_receipts:
            raise RequestClosureRuntimeError(
                "non-success outcome cannot claim persisted result-set receipts"
            )
        expected_optional = {
            "upstream_unavailable": set(),
            "contract_blocked": {"reason_code", "contract_evidence_sha256"},
            "transient_failed": {"failure_class"},
            "response_contract_failed": {"failure_class"},
            "unattempted": {"reason_code"},
            "unclassified": {"classification_input_sha256"},
        }[self.state]
        if present_optional != expected_optional:
            raise RequestClosureRuntimeError(
                "request outcome fields do not exactly match its terminal state"
            )
        if self.reason_code is not None:
            _require_safe_id(self.reason_code, field="reason code")
        if self.failure_class is not None:
            _require_safe_id(self.failure_class, field="failure class")
        for outcome_field in (
            "contract_evidence_sha256",
            "classification_input_sha256",
        ):
            value = getattr(self, outcome_field)
            if value is not None:
                _require_sha256(value, field=outcome_field)
        if self.state in {"transient_failed", "response_contract_failed"}:
            _require_positive_int(self.attempt_count, field="failed request attempt count")
        if self.state == "response_contract_failed" and self.response_body_sha256 is None:
            raise RequestClosureRuntimeError(
                "response-contract failure lacks its exact response body receipt"
            )
        non_request_classification = self.state in {
            "upstream_unavailable",
            "contract_blocked",
            "unattempted",
        }
        if non_request_classification and any(
            value is not None
            for value in (
                self.http_status,
                self.response_body_sha256,
                self.response_body_bytes,
                self.parser_input_sha256,
            )
        ):
            raise RequestClosureRuntimeError(
                "non-request classification cannot claim an observed response body"
            )
        if non_request_classification and self.attempt_count != 0:
            raise RequestClosureRuntimeError("non-request classification must have zero attempts")

    @property
    def result_set_inventory_sha256(self) -> str:
        return _sha256([item.to_dict() for item in self.result_sets])

    @property
    def staging_receipt_inventory_sha256(self) -> str:
        return _sha256([item.to_dict() for item in self.staging_receipts])

    @property
    def staging_receipt_roots_sha256(self) -> str:
        return _sha256(sorted({item.staging_receipt_root_sha256 for item in self.staging_receipts}))

    @property
    def total_result_rows(self) -> int:
        return sum(
            cast("int", item.row_count)
            for item in self.result_sets
            if item.occurrence_state in _PRESENT_RESULT_OCCURRENCE_STATES
        )

    def to_terminal_evidence(
        self,
        *,
        pagination: tuple[int, bool, str | None] | None,
    ) -> RequestTerminalEvidence:
        values: dict[str, Scalar]
        evidence_kind = _TERMINAL_EVIDENCE_KINDS[self.state]
        if self.state in {"success_nonempty", "success_empty"}:
            values = {
                "decoded_results_receipt_sha256": self.result_set_inventory_sha256,
                "http_status": cast("int", self.http_status),
                "persistence_receipt_sha256": self.staging_receipt_inventory_sha256,
                "response_body_sha256": cast("str", self.response_body_sha256),
                "result_occurrence": (
                    "present_nonempty" if self.state == "success_nonempty" else "present_empty"
                ),
                "row_count": self.total_result_rows,
            }
        elif self.state == "upstream_unavailable":
            values = {}
        elif self.state == "contract_blocked":
            values = {
                "contract_evidence_sha256": cast("str", self.contract_evidence_sha256),
                "reason_code": cast("str", self.reason_code),
            }
        elif self.state == "transient_failed":
            values = {
                "attempt_count": self.attempt_count,
                "failure_class": cast("str", self.failure_class),
            }
        elif self.state == "response_contract_failed":
            values = {
                "failure_class": cast("str", self.failure_class),
                "response_body_sha256": cast("str", self.response_body_sha256),
            }
        elif self.state == "unattempted":
            values = {"reason_code": cast("str", self.reason_code)}
        else:
            values = {"classification_input_sha256": cast("str", self.classification_input_sha256)}
        if pagination is not None:
            ordinal, terminal, reason = pagination
            values["pagination_ordinal"] = ordinal
            values["pagination_terminal"] = terminal
            if reason is not None:
                values["pagination_termination_reason"] = reason
        return RequestTerminalEvidence(
            request_binding=self.request_binding,
            state=cast("Any", self.state),
            evidence_kind=cast("Any", evidence_kind),
            evidence_values=tuple(sorted(values.items())),
            upstream_unavailable_evidence=self.upstream_unavailable_evidence,
        )

    def to_dict(self) -> dict[str, object]:
        return {
            "request_surface_sha256": self.request_surface_sha256,
            "route_manifest_sha256": self.route_manifest_sha256,
            "scope_sha256": self.scope_sha256,
            "provider_request_sha256": self.provider_request_sha256,
            "source_family": self.source_family,
            "endpoint_id": self.endpoint_id,
            "route_ids": list(self.route_ids),
            "request_binding": _terminal_request_binding_payload(self.request_binding),
            "state": self.state,
            "attempt_count": self.attempt_count,
            "http_status": self.http_status,
            "response_body_sha256": self.response_body_sha256,
            "response_body_bytes": self.response_body_bytes,
            "parser_input_sha256": self.parser_input_sha256,
            "pagination_termination_reason": self.pagination_termination_reason,
            "result_sets": [item.to_dict() for item in self.result_sets],
            "staging_receipts": [item.to_dict() for item in self.staging_receipts],
            "upstream_unavailable_evidence": (
                None
                if self.upstream_unavailable_evidence is None
                else _typed_upstream_unavailable_payload(self.upstream_unavailable_evidence)
            ),
            "reason_code": self.reason_code,
            "contract_evidence_sha256": self.contract_evidence_sha256,
            "failure_class": self.failure_class,
            "classification_input_sha256": self.classification_input_sha256,
        }

    @classmethod
    def from_dict(cls, payload: Mapping[str, object]) -> Self:
        _require_exact_keys(
            payload,
            {
                "attempt_count",
                "classification_input_sha256",
                "contract_evidence_sha256",
                "endpoint_id",
                "failure_class",
                "http_status",
                "parser_input_sha256",
                "pagination_termination_reason",
                "provider_request_sha256",
                "reason_code",
                "request_binding",
                "request_surface_sha256",
                "response_body_bytes",
                "response_body_sha256",
                "result_sets",
                "route_ids",
                "route_manifest_sha256",
                "scope_sha256",
                "source_family",
                "staging_receipts",
                "state",
                "upstream_unavailable_evidence",
            },
            label="request observation",
        )
        route_ids = tuple(
            _require_safe_id(item, field="observation route ID")
            for item in _list(payload["route_ids"], field="observation route IDs")
        )
        result_sets = tuple(
            ResultSetReceipt.from_dict(_mapping(item, field="result-set receipt"))
            for item in _list(payload["result_sets"], field="result-set receipts")
        )
        staging_receipts = tuple(
            PersistedStagingReceipt.from_dict(_mapping(item, field="persisted staging receipt"))
            for item in _list(payload["staging_receipts"], field="staging receipts")
        )
        http_status = payload["http_status"]
        if http_status is not None:
            http_status = _require_nonnegative_int(http_status, field="HTTP status")
        response_body_bytes = payload["response_body_bytes"]
        if response_body_bytes is not None:
            response_body_bytes = _require_positive_int(
                response_body_bytes,
                field="response body bytes",
            )
        return cls(
            request_surface_sha256=_require_sha256(
                payload["request_surface_sha256"],
                field="request surface SHA-256",
            ),
            route_manifest_sha256=_require_sha256(
                payload["route_manifest_sha256"],
                field="route manifest SHA-256",
            ),
            scope_sha256=_require_sha256(payload["scope_sha256"], field="scope SHA-256"),
            provider_request_sha256=_require_sha256(
                payload["provider_request_sha256"],
                field="provider request SHA-256",
            ),
            source_family=cast("str", payload["source_family"]),
            endpoint_id=_require_safe_id(payload["endpoint_id"], field="endpoint ID"),
            route_ids=route_ids,
            request_binding=_terminal_request_binding_from_payload(payload["request_binding"]),
            state=cast("str", payload["state"]),
            attempt_count=_require_nonnegative_int(
                payload["attempt_count"],
                field="attempt count",
            ),
            http_status=http_status,
            response_body_sha256=_optional_string(
                payload["response_body_sha256"],
                field="response body SHA-256",
            ),
            response_body_bytes=response_body_bytes,
            parser_input_sha256=_optional_string(
                payload["parser_input_sha256"],
                field="parser input SHA-256",
            ),
            pagination_termination_reason=_optional_string(
                payload["pagination_termination_reason"],
                field="pagination termination reason",
            ),
            result_sets=result_sets,
            staging_receipts=staging_receipts,
            upstream_unavailable_evidence=(
                None
                if payload["upstream_unavailable_evidence"] is None
                else _typed_upstream_unavailable_from_payload(
                    payload["upstream_unavailable_evidence"]
                )
            ),
            reason_code=_optional_string(payload["reason_code"], field="reason code"),
            contract_evidence_sha256=_optional_string(
                payload["contract_evidence_sha256"],
                field="contract evidence SHA-256",
            ),
            failure_class=_optional_string(payload["failure_class"], field="failure class"),
            classification_input_sha256=_optional_string(
                payload["classification_input_sha256"],
                field="classification input SHA-256",
            ),
        )


@dataclass(frozen=True, slots=True)
class RequestClosureAdapterInput:
    """Path-free input bundle consumed by the deterministic closure builder."""

    route_manifest: AuthoritativeRouteManifest
    scope: RequestScopeManifest
    observations: tuple[RequestObservation, ...]

    def __post_init__(self) -> None:
        if not isinstance(self.route_manifest, AuthoritativeRouteManifest):
            raise RequestClosureRuntimeError("adapter route manifest is invalid")
        if not isinstance(self.scope, RequestScopeManifest):
            raise RequestClosureRuntimeError("adapter scope is invalid")
        if type(self.observations) is not tuple or any(
            not isinstance(item, RequestObservation) for item in self.observations
        ):
            raise RequestClosureRuntimeError("adapter observations must be an exact tuple")
        keys = tuple(item.provider_request_sha256 for item in self.observations)
        if not keys or keys != tuple(sorted(set(keys))):
            raise RequestClosureRuntimeError(
                "adapter observations must be request-key sorted, unique, and nonempty"
            )


@dataclass(frozen=True, slots=True)
class RequestClosureRuntimeReceipt:
    """Canonical runtime receipt with mandatory independent verification."""

    route_manifest: AuthoritativeRouteManifest
    scope: RequestScopeManifest
    observations: tuple[RequestObservation, ...]
    closure: RequestClosureReceipt = field(init=False)

    def __post_init__(self) -> None:
        adapter = RequestClosureAdapterInput(
            route_manifest=self.route_manifest,
            scope=self.scope,
            observations=self.observations,
        )
        primary = _build_primary_closure(adapter)
        proof = verify_request_closure_independently(primary)
        object.__setattr__(self, "closure", replace(primary, independent_proof=proof))

    @property
    def request_surface_sha256(self) -> str:
        return self.closure.request_surface_sha256

    @property
    def terminal_policy_sha256(self) -> str:
        return pinned_request_surface_authority().terminal_policy_sha256

    @property
    def unit_inventory_sha256(self) -> str:
        return cast("IndependentClosureProof", self.closure.independent_proof).unit_inventory_sha256

    @property
    def terminal_inventory_sha256(self) -> str:
        return self.closure.terminal_inventory_sha256

    @property
    def request_binding_inventory_sha256(self) -> str:
        return self.closure.request_binding_inventory_sha256

    @property
    def staging_receipt_inventory_sha256(self) -> str:
        return _sha256(
            [
                receipt.to_dict()
                for observation in self.observations
                for receipt in observation.staging_receipts
            ]
        )

    @property
    def persisted_staging_receipt_roots(self) -> tuple[str, ...]:
        return tuple(
            sorted(
                {
                    receipt.staging_receipt_root_sha256
                    for observation in self.observations
                    for receipt in observation.staging_receipts
                }
            )
        )

    @property
    def persisted_staging_receipt_roots_sha256(self) -> str:
        return _sha256(list(self.persisted_staging_receipt_roots))

    @property
    def green(self) -> bool:
        return (
            self.closure.green
            and bool(self.observations)
            and all(
                (
                    observation.state in _RELEASE_TERMINAL_STATES
                    and observation.state not in _INCOMPLETE_STATES
                )
                for observation in self.observations
            )
        )

    @property
    def canonical_bytes(self) -> bytes:
        return _canonical_json_bytes(self.to_dict())

    @property
    def artifact_sha256(self) -> str:
        return hashlib.sha256(self.canonical_bytes).hexdigest()

    def to_dict(self) -> dict[str, object]:
        return {
            "schema_version": REQUEST_CLOSURE_RUNTIME_SCHEMA_VERSION,
            "kind": _KIND,
            "request_surface_sha256": self.request_surface_sha256,
            "terminal_policy_sha256": self.terminal_policy_sha256,
            "route_manifest_sha256": self.route_manifest.manifest_sha256,
            "scope_sha256": self.scope.scope_sha256,
            "unit_inventory_sha256": self.unit_inventory_sha256,
            "request_binding_inventory_sha256": (self.request_binding_inventory_sha256),
            "terminal_inventory_sha256": self.terminal_inventory_sha256,
            "staging_receipt_inventory_sha256": self.staging_receipt_inventory_sha256,
            "persisted_staging_receipt_roots": list(self.persisted_staging_receipt_roots),
            "persisted_staging_receipt_roots_sha256": (self.persisted_staging_receipt_roots_sha256),
            "route_manifest": _route_manifest_payload(self.route_manifest),
            "scope": _scope_payload(self.scope),
            "observations": [item.to_dict() for item in self.observations],
            "closure": _closure_payload(self.closure),
        }

    @classmethod
    def from_dict(cls, payload: Mapping[str, object]) -> Self:
        _require_exact_keys(
            payload,
            {
                "closure",
                "kind",
                "observations",
                "persisted_staging_receipt_roots",
                "persisted_staging_receipt_roots_sha256",
                "request_surface_sha256",
                "request_binding_inventory_sha256",
                "route_manifest",
                "route_manifest_sha256",
                "schema_version",
                "scope",
                "scope_sha256",
                "staging_receipt_inventory_sha256",
                "terminal_policy_sha256",
                "terminal_inventory_sha256",
                "unit_inventory_sha256",
            },
            label="request closure runtime receipt",
        )
        if payload["schema_version"] != REQUEST_CLOSURE_RUNTIME_SCHEMA_VERSION:
            raise RequestClosureRuntimeError("request closure runtime schema is unsupported")
        if payload["kind"] != _KIND:
            raise RequestClosureRuntimeError("request closure runtime kind is invalid")
        if (
            _require_sha256(
                payload["terminal_policy_sha256"],
                field="terminal policy SHA-256",
            )
            != pinned_request_surface_authority().terminal_policy_sha256
        ):
            raise RequestClosureRuntimeError(
                "request closure runtime references a foreign terminal policy"
            )
        manifest = _route_manifest_from_payload(
            _mapping(payload["route_manifest"], field="route manifest")
        )
        scope = _scope_from_payload(_mapping(payload["scope"], field="request scope"))
        observations = tuple(
            RequestObservation.from_dict(_mapping(item, field="request observation"))
            for item in _list(payload["observations"], field="request observations")
        )
        result = build_request_closure_runtime_receipt(
            RequestClosureAdapterInput(
                route_manifest=manifest,
                scope=scope,
                observations=observations,
            )
        )
        # The closure body and every redundant compact digest are authority
        # fields, not hints.  Exact reproduction rejects any nested tampering.
        if result.to_dict() != dict(payload):
            raise RequestClosureRuntimeError(
                "request closure runtime payload differs from reproduced evidence"
            )
        return cast("Self", result)

    @classmethod
    def from_canonical_bytes(cls, encoded: bytes) -> Self:
        if not isinstance(encoded, bytes):
            raise RequestClosureRuntimeError("request closure encoding must be bytes")

        def reject_duplicate_pairs(pairs: list[tuple[str, object]]) -> dict[str, object]:
            result: dict[str, object] = {}
            for key, value in pairs:
                if key in result:
                    raise RequestClosureRuntimeError(
                        f"request closure contains duplicate key {key!r}"
                    )
                result[key] = value
            return result

        def reject_constant(value: str) -> object:
            raise RequestClosureRuntimeError(
                f"request closure contains non-finite JSON value {value}"
            )

        try:
            decoded = json.loads(
                encoded.decode("utf-8", errors="strict"),
                object_pairs_hook=reject_duplicate_pairs,
                parse_constant=reject_constant,
            )
        except RequestClosureRuntimeError:
            raise
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise RequestClosureRuntimeError("request closure is not strict UTF-8 JSON") from exc
        if not isinstance(decoded, dict) or _canonical_json_bytes(decoded) != encoded:
            raise RequestClosureRuntimeError("request closure bytes are not canonical")
        result = cls.from_dict(cast("Mapping[str, object]", decoded))
        if result.canonical_bytes != encoded:
            raise RequestClosureRuntimeError(
                "request closure canonical bytes differ after validation"
            )
        return result


def build_request_closure_runtime_receipt(
    adapter: RequestClosureAdapterInput,
) -> RequestClosureRuntimeReceipt:
    """Build and independently verify a deterministic runtime closure receipt."""

    if not isinstance(adapter, RequestClosureAdapterInput):
        raise RequestClosureRuntimeError("request closure adapter input is invalid")
    return RequestClosureRuntimeReceipt(
        route_manifest=adapter.route_manifest,
        scope=adapter.scope,
        observations=adapter.observations,
    )


def _materialized_bindings(
    manifest: AuthoritativeRouteManifest,
) -> tuple[RequestRouteBinding, ...]:
    authority = pinned_request_surface_authority()
    by_request: dict[str, list[str]] = defaultdict(list)
    for route in manifest.routes:
        endpoint = authority.endpoint(route.source_family, route.endpoint_id)
        request = materialize_provider_request(
            endpoint,
            route.parameter_mapping,
            request_surface_sha256=manifest.request_surface_sha256,
            runtime_contract_payload_sha256=manifest.runtime_contract_payload_sha256,
        )
        by_request[request.provider_request_sha256].append(route.route_id)
    return tuple(
        RequestRouteBinding(request_key, tuple(sorted(route_ids)))
        for request_key, route_ids in sorted(by_request.items())
    )


def _pagination_for_binding(
    manifest: AuthoritativeRouteManifest,
    route_ids: tuple[str, ...],
    observation: RequestObservation,
) -> tuple[int, bool, str | None] | None:
    by_id = {route.route_id: route for route in manifest.routes}
    routes = tuple(by_id[route_id] for route_id in route_ids)
    pagination = {(route.pagination_ordinal, route.pagination_terminal) for route in routes}
    if pagination == {(None, False)}:
        if observation.pagination_termination_reason is not None:
            raise RequestClosureRuntimeError("non-pagination request declares a termination reason")
        return None
    if len(pagination) != 1:
        raise RequestClosureRuntimeError("aliased routes disagree on pagination outcome authority")
    ordinal, terminal = next(iter(pagination))
    if ordinal is None:
        raise RequestClosureRuntimeError("pagination route lacks an ordinal")
    reason = observation.pagination_termination_reason
    if terminal and reason not in {"declared_total", "empty_page", "short_page"}:
        raise RequestClosureRuntimeError(
            "terminal pagination request lacks an observed stop reason"
        )
    if not terminal and reason is not None:
        raise RequestClosureRuntimeError("nonterminal pagination request declares a stop reason")
    return ordinal, terminal, reason


def _live_result_occurrence_is_optional(
    *,
    endpoint_id: str,
    ordinal: int,
    result_set_name: str,
) -> bool:
    contract = pinned_live_contracts().get(endpoint_id)
    if contract is None:
        return False
    by_name = {item.name: item for item in contract.result_sets}
    result_set = by_name.get(result_set_name)
    if result_set is None or result_set.ordinal != ordinal:
        return False
    if result_set.parent_result_set_name is None:
        return False
    parent = by_name.get(result_set.parent_result_set_name)
    if parent is None:
        return False
    parent_fields = tuple(
        field
        for field in parent.fields
        if field.nested_result_set_name == result_set_name
        and (result_set.parent_field_name is None or field.name == result_set.parent_field_name)
    )
    return bool(parent_fields) and all(field.key_presence != "required" for field in parent_fields)


def _validate_observation_authority(
    observation: RequestObservation,
    *,
    manifest: AuthoritativeRouteManifest,
    scope: RequestScopeManifest,
    binding: RequestRouteBinding,
) -> None:
    if (
        observation.request_surface_sha256 != manifest.request_surface_sha256
        or observation.route_manifest_sha256 != manifest.manifest_sha256
        or observation.scope_sha256 != scope.scope_sha256
        or observation.provider_request_sha256 != binding.provider_request_sha256
        or observation.route_ids != binding.route_ids
        or observation.request_binding.runtime_contract_payload_sha256
        != manifest.runtime_contract_payload_sha256
    ):
        raise RequestClosureRuntimeError(
            "request observation references foreign route/scope/unit authority"
        )
    routes = {
        route.route_id: route for route in manifest.routes if route.route_id in binding.route_ids
    }
    if len(routes) != len(binding.route_ids):
        raise RequestClosureRuntimeError("request observation references a missing route")
    families = {route.source_family for route in routes.values()}
    endpoints = {route.endpoint_id for route in routes.values()}
    if families != {observation.source_family} or endpoints != {observation.endpoint_id}:
        raise RequestClosureRuntimeError(
            "request observation endpoint differs from materialized route authority"
        )
    if observation.state in {"success_nonempty", "success_empty"}:
        if observation.source_family == "stats":
            contract = pinned_runtime_contracts().get(observation.endpoint_id)
            expected = (
                ()
                if contract is None
                else tuple(
                    (item.result_set_index, item.result_set_name, False)
                    for item in contract.result_sets
                )
            )
        else:
            live_contract = pinned_live_contracts().get(observation.endpoint_id)
            expected = (
                ()
                if live_contract is None
                else tuple(
                    (
                        item.ordinal,
                        item.name,
                        _live_result_occurrence_is_optional(
                            endpoint_id=observation.endpoint_id,
                            ordinal=item.ordinal,
                            result_set_name=item.name,
                        ),
                    )
                    for item in live_contract.result_sets
                )
            )
        observed = tuple((item.ordinal, item.result_set_name) for item in observation.result_sets)
        expected_identity = tuple((ordinal, name) for ordinal, name, _ in expected)
        if not expected or observed != expected_identity:
            raise RequestClosureRuntimeError(
                "successful observation omits or invents a pinned result set"
            )
        for result, (_, _, optional) in zip(
            observation.result_sets,
            expected,
            strict=True,
        ):
            if result.occurrence_state == "absent_optional" and not optional:
                raise RequestClosureRuntimeError(
                    "absent result occurrence is not optional in the pinned contract"
                )


def _build_primary_closure(adapter: RequestClosureAdapterInput) -> RequestClosureReceipt:
    manifest = adapter.route_manifest
    scope = adapter.scope
    authority = pinned_request_surface_authority()
    if (
        manifest.request_surface_sha256 != authority.surface_sha256
        or scope.request_surface_sha256 != authority.surface_sha256
    ):
        raise RequestClosureRuntimeError("closure adapter references a foreign authority")
    bindings = _materialized_bindings(manifest)
    require_route_conservation(manifest, bindings)
    expected_units = tuple(binding.provider_request_sha256 for binding in bindings)
    observed_units = tuple(item.provider_request_sha256 for item in adapter.observations)
    if observed_units != expected_units:
        raise RequestClosureRuntimeError(
            "request observations do not exactly and uniquely conserve request units"
        )
    observations = {item.provider_request_sha256: item for item in adapter.observations}
    terminals: list[RequestTerminalEvidence] = []
    for binding in bindings:
        observation = observations[binding.provider_request_sha256]
        _validate_observation_authority(
            observation,
            manifest=manifest,
            scope=scope,
            binding=binding,
        )
        terminals.append(
            observation.to_terminal_evidence(
                pagination=_pagination_for_binding(
                    manifest,
                    binding.route_ids,
                    observation,
                )
            )
        )

    seed_ids = set(scope.seed_route_ids)
    seed_units = tuple(
        sorted(
            binding.provider_request_sha256
            for binding in bindings
            if seed_ids & set(binding.route_ids)
        )
    )
    if not seed_units:
        raise RequestClosureRuntimeError("scope seed routes materialize no request units")
    iterations: list[RequestClosureIteration] = []
    seed_evidence = RequestExpansionEvidence(
        evidence_id="seed_routes",
        evidence_kind="seed",
        request_surface_sha256=authority.surface_sha256,
        scope_sha256=scope.scope_sha256,
        input_units=(),
        discovered_units=seed_units,
        source_values=tuple(sorted(scope.seed_route_ids)),
        complete=True,
    )
    iterations.append(
        RequestClosureIteration(
            iteration=0,
            request_surface_sha256=authority.surface_sha256,
            scope_sha256=scope.scope_sha256,
            input_units=(),
            new_units=seed_units,
            output_units=seed_units,
            evidence=(seed_evidence,),
        )
    )
    remaining = tuple(sorted(set(expected_units) - set(seed_units)))
    current = seed_units
    if remaining:
        expanded = tuple(sorted((*current, *remaining)))
        expansion = RequestExpansionEvidence(
            evidence_id="scope_routes",
            evidence_kind="scope_expansion",
            request_surface_sha256=authority.surface_sha256,
            scope_sha256=scope.scope_sha256,
            input_units=current,
            discovered_units=remaining,
            source_values=remaining,
            complete=True,
        )
        iterations.append(
            RequestClosureIteration(
                iteration=len(iterations),
                request_surface_sha256=authority.surface_sha256,
                scope_sha256=scope.scope_sha256,
                input_units=current,
                new_units=remaining,
                output_units=expanded,
                evidence=(expansion,),
            )
        )
        current = expanded
    fixed = RequestExpansionEvidence(
        evidence_id="fixed_point",
        evidence_kind="fixed_point",
        request_surface_sha256=authority.surface_sha256,
        scope_sha256=scope.scope_sha256,
        input_units=current,
        discovered_units=(),
        source_values=(),
        complete=True,
    )
    iterations.append(
        RequestClosureIteration(
            iteration=len(iterations),
            request_surface_sha256=authority.surface_sha256,
            scope_sha256=scope.scope_sha256,
            input_units=current,
            new_units=(),
            output_units=current,
            evidence=(fixed,),
        )
    )
    return RequestClosureReceipt(
        request_surface_sha256=authority.surface_sha256,
        scope=scope,
        route_manifest=manifest,
        bindings=bindings,
        iterations=tuple(iterations),
        terminal_evidence=tuple(terminals),
    )


def _route_manifest_payload(manifest: AuthoritativeRouteManifest) -> dict[str, object]:
    return {
        "request_surface_sha256": manifest.request_surface_sha256,
        "runtime_contract_payload_sha256": manifest.runtime_contract_payload_sha256,
        "derivation_policy_sha256": manifest.derivation_policy_sha256,
        "registry_manifest_sha256": manifest.registry_manifest_sha256,
        "routes": [_route_payload(route) for route in manifest.routes],
    }


def _route_manifest_from_payload(
    payload: Mapping[str, object],
) -> AuthoritativeRouteManifest:
    _require_exact_keys(
        payload,
        {
            "derivation_policy_sha256",
            "registry_manifest_sha256",
            "request_surface_sha256",
            "routes",
            "runtime_contract_payload_sha256",
        },
        label="route manifest",
    )
    routes = tuple(
        RouteRequestSpecInput.from_dict(_mapping(item, field="route request input"))
        for item in _list(payload["routes"], field="route manifest routes")
    )
    manifest = build_authoritative_route_manifest(
        routes,
        request_surface_sha256=_require_sha256(
            payload["request_surface_sha256"],
            field="request surface SHA-256",
        ),
        runtime_contract_payload_sha256=_require_sha256(
            payload["runtime_contract_payload_sha256"],
            field="runtime contract payload SHA-256",
        ),
    )
    if _route_manifest_payload(manifest) != dict(payload):
        raise RequestClosureRuntimeError("route manifest differs from reproduced authority")
    return manifest


def _dimension_payload(dimension: RequestScopeDimension) -> dict[str, object]:
    return {
        "dependency_id": dimension.dependency_id,
        "source_kind": dimension.source_kind,
        "source_authority_sha256": dimension.source_authority_sha256,
        "values": list(dimension.values),
        "endpoint_id": dimension.endpoint_id,
        "parameter_name": dimension.parameter_name,
    }


def _scope_payload(scope: RequestScopeManifest) -> dict[str, object]:
    return {
        "request_surface_sha256": scope.request_surface_sha256,
        "scope_id": scope.scope_id,
        "seed_route_ids": list(scope.seed_route_ids),
        "dimensions": [_dimension_payload(item) for item in scope.dimensions],
    }


def _scope_from_payload(payload: Mapping[str, object]) -> RequestScopeManifest:
    _require_exact_keys(
        payload,
        {"dimensions", "request_surface_sha256", "scope_id", "seed_route_ids"},
        label="request scope",
    )
    dimensions: list[RequestScopeDimension] = []
    for raw_dimension in _list(payload["dimensions"], field="scope dimensions"):
        dimension = _mapping(raw_dimension, field="scope dimension")
        _require_exact_keys(
            dimension,
            {
                "dependency_id",
                "endpoint_id",
                "parameter_name",
                "source_authority_sha256",
                "source_kind",
                "values",
            },
            label="scope dimension",
        )
        dimensions.append(
            RequestScopeDimension(
                dependency_id=cast("str", dimension["dependency_id"]),
                source_kind=cast("str", dimension["source_kind"]),
                source_authority_sha256=_require_sha256(
                    dimension["source_authority_sha256"],
                    field="scope source authority SHA-256",
                ),
                values=tuple(
                    _require_scalar(item, field="scope value")
                    for item in _list(dimension["values"], field="scope values")
                ),
                endpoint_id=_optional_string(
                    dimension["endpoint_id"],
                    field="scope endpoint ID",
                ),
                parameter_name=_optional_string(
                    dimension["parameter_name"],
                    field="scope parameter name",
                ),
            )
        )
    scope = RequestScopeManifest(
        request_surface_sha256=_require_sha256(
            payload["request_surface_sha256"],
            field="scope request surface SHA-256",
        ),
        scope_id=_require_safe_id(payload["scope_id"], field="scope ID"),
        seed_route_ids=tuple(
            _require_safe_id(item, field="scope seed route ID")
            for item in _list(payload["seed_route_ids"], field="scope seed route IDs")
        ),
        dimensions=tuple(dimensions),
    )
    if _scope_payload(scope) != dict(payload):
        raise RequestClosureRuntimeError("request scope differs after validation")
    return scope


def _expansion_payload(evidence: RequestExpansionEvidence) -> dict[str, object]:
    return {
        "evidence_id": evidence.evidence_id,
        "evidence_kind": evidence.evidence_kind,
        "request_surface_sha256": evidence.request_surface_sha256,
        "scope_sha256": evidence.scope_sha256,
        "input_units": list(evidence.input_units),
        "discovered_units": list(evidence.discovered_units),
        "source_values": list(evidence.source_values),
        "complete": evidence.complete,
        "pagination_ordinals": list(evidence.pagination_ordinals),
        "pagination_terminal_ordinal": evidence.pagination_terminal_ordinal,
    }


def _iteration_payload(iteration: RequestClosureIteration) -> dict[str, object]:
    return {
        "iteration": iteration.iteration,
        "request_surface_sha256": iteration.request_surface_sha256,
        "scope_sha256": iteration.scope_sha256,
        "input_units": list(iteration.input_units),
        "new_units": list(iteration.new_units),
        "output_units": list(iteration.output_units),
        "evidence": [_expansion_payload(item) for item in iteration.evidence],
    }


def _terminal_payload(evidence: RequestTerminalEvidence) -> dict[str, object]:
    return evidence.to_dict()


def _proof_payload(proof: IndependentClosureProof) -> dict[str, object]:
    return {
        "verifier_id": proof.verifier_id,
        "request_surface_sha256": proof.request_surface_sha256,
        "scope_sha256": proof.scope_sha256,
        "route_manifest_sha256": proof.route_manifest_sha256,
        "unit_inventory_sha256": proof.unit_inventory_sha256,
        "terminal_inventory_sha256": proof.terminal_inventory_sha256,
    }


def _closure_payload(closure: RequestClosureReceipt) -> dict[str, object]:
    if closure.independent_proof is None:
        raise RequestClosureRuntimeError("runtime closure lacks an independent proof")
    return {
        "request_surface_sha256": closure.request_surface_sha256,
        "terminal_policy_sha256": pinned_request_surface_authority().terminal_policy_sha256,
        "scope_sha256": closure.scope.scope_sha256,
        "route_manifest_sha256": closure.route_manifest.manifest_sha256,
        "bindings": [
            {
                "provider_request_sha256": item.provider_request_sha256,
                "route_ids": list(item.route_ids),
            }
            for item in closure.bindings
        ],
        "iterations": [_iteration_payload(item) for item in closure.iterations],
        "request_binding_inventory": [
            item.request_binding.to_dict() for item in closure.terminal_evidence
        ],
        "request_binding_inventory_sha256": (closure.request_binding_inventory_sha256),
        "terminal_evidence": [_terminal_payload(item) for item in closure.terminal_evidence],
        "independent_proof": _proof_payload(closure.independent_proof),
    }
