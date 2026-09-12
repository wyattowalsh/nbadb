"""Pure construction and admission of daily/monthly planning requests.

This module derives the complete planning-root inventory only from caller-owned
timestamps and the current staging-route/support contracts.  It deliberately
does not consult a provider, extractor registry, database, journal, capture
generation, or wall clock.
"""

from __future__ import annotations

import re
from datetime import datetime
from typing import TYPE_CHECKING

from nbadb.contracts.staging_route_contract import (
    StagingRouteContract,
    staging_route_contract_bundle,
)
from nbadb.core.types import classify_season_type_availability
from nbadb.orchestrate.extraction_contract import matching_support_rules
from nbadb.orchestrate.successor_planning_contract import (
    SuccessorPlanningContractError,
    SuccessorPlanningRequest,
)
from nbadb.orchestrate.successor_update_contract import (
    CallMutability,
    RequestedRouteScope,
    SuccessorUpdateMode,
    canonical_json_bytes,
)

if TYPE_CHECKING:
    from collections.abc import Mapping

__all__ = [
    "SuccessorPlanningRequestBuilderError",
    "build_successor_planning_request",
    "derive_successor_season",
    "validate_successor_planning_request",
]

_UTC_INSTANT_RE = re.compile(r"[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}Z")
_EXPECTED_PATTERNS = {
    "league_game_log": "season",
    "player_game_logs": "season",
    "common_all_players": "static",
    "common_team_years": "static",
    "live_score_board": "live",
}
_SUPPORTED_ROUTE_STATUSES = frozenset(
    {
        "bound_provider_packet",
        "classified_provider_packet_absent",
        "classified_provider_columns_absent",
    }
)


class SuccessorPlanningRequestBuilderError(SuccessorPlanningContractError):
    """Raised when current route/support authority cannot derive one exact request."""


def _parse_utc_instant(value: object, *, field_name: str) -> datetime:
    if not isinstance(value, str) or _UTC_INSTANT_RE.fullmatch(value) is None:
        raise SuccessorPlanningRequestBuilderError(
            f"{field_name} must use canonical UTC form YYYY-MM-DDTHH:MM:SSZ"
        )
    try:
        parsed = datetime.strptime(value, "%Y-%m-%dT%H:%M:%SZ")
    except ValueError as exc:
        raise SuccessorPlanningRequestBuilderError(
            f"{field_name} must use canonical UTC form YYYY-MM-DDTHH:MM:SSZ"
        ) from exc
    if parsed.strftime("%Y-%m-%dT%H:%M:%SZ") != value:
        raise SuccessorPlanningRequestBuilderError(
            f"{field_name} must use canonical UTC form YYYY-MM-DDTHH:MM:SSZ"
        )
    return parsed


def _season_string(start_year: int) -> str:
    if start_year < 1 or start_year >= 9999:
        raise SuccessorPlanningRequestBuilderError(
            "as_of_utc cannot be represented as an NBA season"
        )
    return f"{start_year:04d}-{(start_year + 1) % 100:02d}"


def derive_successor_season(as_of_utc: str) -> str:
    """Derive the NBA season from one fixed UTC instant using an October 1 boundary."""

    as_of = _parse_utc_instant(as_of_utc, field_name="as_of_utc")
    start_year = as_of.year if (as_of.month, as_of.day) >= (10, 1) else as_of.year - 1
    return _season_string(start_year)


def _routes_for_endpoint(endpoint_name: str) -> tuple[StagingRouteContract, ...]:
    expected_pattern = _EXPECTED_PATTERNS[endpoint_name]
    routes = tuple(
        sorted(
            (
                route
                for route in staging_route_contract_bundle().routes
                if route.endpoint_name == endpoint_name
            ),
            key=lambda route: route.ordinal,
        )
    )
    if not routes:
        raise SuccessorPlanningRequestBuilderError(
            f"required planning endpoint {endpoint_name!r} has no current result route"
        )
    route_ids = tuple(route.route_id for route in routes)
    if len(route_ids) != len(set(route_ids)):
        raise SuccessorPlanningRequestBuilderError(
            f"required planning endpoint {endpoint_name!r} has duplicate result routes"
        )
    for route in routes:
        if route.param_pattern != expected_pattern:
            raise SuccessorPlanningRequestBuilderError(
                f"required planning endpoint {endpoint_name!r} changed parameter pattern"
            )
        if route.classified_status not in _SUPPORTED_ROUTE_STATUSES:
            raise SuccessorPlanningRequestBuilderError(
                f"required planning endpoint {endpoint_name!r} has unknown support classification"
            )
    return routes


def _require_unblocked_scope(
    *,
    endpoint_name: str,
    routes: tuple[StagingRouteContract, ...],
    season_start_year: int | None,
) -> None:
    patterns = tuple(sorted({route.param_pattern for route in routes}))
    matches = matching_support_rules(
        endpoint_name=endpoint_name,
        patterns=patterns,
        season_start=season_start_year,
        season_end=season_start_year,
    )
    blocked = tuple(rule for rule in matches if rule.classification == "contract_blocked")
    if blocked:
        raise SuccessorPlanningRequestBuilderError(
            f"required planning scope for {endpoint_name!r} is contract_blocked"
        )


def _season_types_for_endpoint(
    *,
    endpoint_name: str,
    routes: tuple[StagingRouteContract, ...],
    season_start_year: int,
) -> tuple[str, ...]:
    capabilities = {route.season_type_capability for route in routes}
    inventories = {route.supported_season_types for route in routes}
    if capabilities != {"supported"} or len(inventories) != 1:
        raise SuccessorPlanningRequestBuilderError(
            f"required planning endpoint {endpoint_name!r} lacks one exact season-type contract"
        )
    declared = next(iter(inventories))
    if not declared:
        raise SuccessorPlanningRequestBuilderError(
            f"required planning endpoint {endpoint_name!r} has no supported season types"
        )
    supported = tuple(
        season_type
        for season_type in declared
        if classify_season_type_availability(season_start_year, season_type) == "supported"
    )
    if not supported:
        raise SuccessorPlanningRequestBuilderError(
            f"required planning endpoint {endpoint_name!r} has no available season types"
        )
    return supported


def _route_scopes(
    *,
    endpoint_name: str,
    parameters: Mapping[str, object],
    season_start_year: int | None,
) -> tuple[RequestedRouteScope, ...]:
    routes = _routes_for_endpoint(endpoint_name)
    _require_unblocked_scope(
        endpoint_name=endpoint_name,
        routes=routes,
        season_start_year=season_start_year,
    )
    return tuple(
        RequestedRouteScope.from_parameters(
            endpoint_name=endpoint_name,
            route_id=route.route_id,
            route_contract_sha256=route.contract_sha256,
            parameters=parameters,
            mutability=CallMutability.MUTABLE,
        )
        for route in routes
    )


def _seasonal_log_scopes(
    *,
    endpoint_name: str,
    seasons: tuple[str, ...],
) -> tuple[RequestedRouteScope, ...]:
    routes = _routes_for_endpoint(endpoint_name)
    scopes: list[RequestedRouteScope] = []
    for season in seasons:
        season_start_year = int(season[:4])
        _require_unblocked_scope(
            endpoint_name=endpoint_name,
            routes=routes,
            season_start_year=season_start_year,
        )
        for season_type in _season_types_for_endpoint(
            endpoint_name=endpoint_name,
            routes=routes,
            season_start_year=season_start_year,
        ):
            parameters = {"season": season, "season_type": season_type}
            scopes.extend(
                RequestedRouteScope.from_parameters(
                    endpoint_name=endpoint_name,
                    route_id=route.route_id,
                    route_contract_sha256=route.contract_sha256,
                    parameters=parameters,
                    mutability=CallMutability.MUTABLE,
                )
                for route in routes
            )
    return tuple(scopes)


def _derived_scopes(
    *,
    mode: SuccessorUpdateMode,
    as_of_utc: str,
) -> tuple[RequestedRouteScope, ...]:
    current_season = derive_successor_season(as_of_utc)
    current_start_year = int(current_season[:4])
    if mode is SuccessorUpdateMode.DAILY:
        seasons = (current_season,)
        current_only = 1
    elif mode is SuccessorUpdateMode.MONTHLY:
        seasons = tuple(
            _season_string(year) for year in range(current_start_year - 2, current_start_year + 1)
        )
        current_only = 0
    else:
        raise SuccessorPlanningRequestBuilderError("mode must be a SuccessorUpdateMode")

    scopes: list[RequestedRouteScope] = []
    for endpoint_name in ("league_game_log", "player_game_logs"):
        scopes.extend(_seasonal_log_scopes(endpoint_name=endpoint_name, seasons=seasons))
    for season in seasons if mode is SuccessorUpdateMode.MONTHLY else (current_season,):
        scopes.extend(
            _route_scopes(
                endpoint_name="common_all_players",
                parameters={
                    "season": season,
                    "is_only_current_season": current_only,
                },
                season_start_year=int(season[:4]),
            )
        )
    scopes.extend(
        _route_scopes(
            endpoint_name="common_team_years",
            parameters={},
            season_start_year=None,
        )
    )
    scopes.extend(
        _route_scopes(
            endpoint_name="live_score_board",
            parameters={},
            season_start_year=None,
        )
    )
    return tuple(scopes)


def build_successor_planning_request(
    *,
    baseline_identity_sha256: str,
    mode: SuccessorUpdateMode,
    source_sha: str,
    cutoff_utc: str,
    as_of_utc: str,
    workflow_run_id: int,
    workflow_run_attempt: int,
) -> SuccessorPlanningRequest:
    """Build the only current route-complete request for the supplied fixed inputs."""

    _parse_utc_instant(cutoff_utc, field_name="cutoff_utc")
    _parse_utc_instant(as_of_utc, field_name="as_of_utc")
    return SuccessorPlanningRequest(
        baseline_identity_sha256=baseline_identity_sha256,
        mode=mode,
        source_sha=source_sha,
        cutoff_utc=cutoff_utc,
        as_of_utc=as_of_utc,
        workflow_run_id=workflow_run_id,
        workflow_run_attempt=workflow_run_attempt,
        requested_planning_scopes=_derived_scopes(mode=mode, as_of_utc=as_of_utc),
    )


def validate_successor_planning_request(
    request: SuccessorPlanningRequest,
) -> SuccessorPlanningRequest:
    """Re-derive and require byte-exact equality with current route/support authority."""

    if not isinstance(request, SuccessorPlanningRequest):
        raise SuccessorPlanningRequestBuilderError("request must be a SuccessorPlanningRequest")
    expected = build_successor_planning_request(
        baseline_identity_sha256=request.baseline_identity_sha256,
        mode=request.mode,
        source_sha=request.source_sha,
        cutoff_utc=request.cutoff_utc,
        as_of_utc=request.as_of_utc,
        workflow_run_id=request.workflow_run_id,
        workflow_run_attempt=request.workflow_run_attempt,
    )
    if canonical_json_bytes(request.to_dict()) != canonical_json_bytes(expected.to_dict()):
        raise SuccessorPlanningRequestBuilderError(
            "successor planning request differs from the exact derived inventory"
        )
    return request
