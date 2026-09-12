from __future__ import annotations

from dataclasses import replace
from types import SimpleNamespace
from typing import Any

import pytest

import nbadb.orchestrate.seasons as seasons_module
import nbadb.orchestrate.successor_planning_request_builder as builder_module
from nbadb.contracts.staging_route_contract import staging_route_contract_bundle
from nbadb.core.types import SeasonType
from nbadb.orchestrate.successor_planning_contract import (
    SuccessorPlanningContractError,
    SuccessorPlanningRequest,
)
from nbadb.orchestrate.successor_planning_request_builder import (
    SuccessorPlanningRequestBuilderError,
    build_successor_planning_request,
    derive_successor_season,
    validate_successor_planning_request,
)
from nbadb.orchestrate.successor_update_contract import (
    CallMutability,
    RequestedRouteScope,
    SuccessorUpdateMode,
)

_BASELINE_SHA = "a" * 64
_SOURCE_SHA = "b" * 40
_CUTOFF = "2026-08-12T00:00:00Z"
_AS_OF = "2026-08-13T00:00:00Z"


def _request(
    mode: SuccessorUpdateMode = SuccessorUpdateMode.DAILY,
    *,
    as_of_utc: str = _AS_OF,
) -> SuccessorPlanningRequest:
    return build_successor_planning_request(
        baseline_identity_sha256=_BASELINE_SHA,
        mode=mode,
        source_sha=_SOURCE_SHA,
        cutoff_utc=_CUTOFF,
        as_of_utc=as_of_utc,
        workflow_run_id=731,
        workflow_run_attempt=4,
    )


def _by_endpoint(
    request: SuccessorPlanningRequest,
) -> dict[str, tuple[RequestedRouteScope, ...]]:
    return {
        endpoint: tuple(
            scope for scope in request.requested_planning_scopes if scope.endpoint_name == endpoint
        )
        for endpoint in {scope.endpoint_name for scope in request.requested_planning_scopes}
    }


def _rebuilt(
    request: SuccessorPlanningRequest,
    scopes: tuple[RequestedRouteScope, ...],
) -> SuccessorPlanningRequest:
    return SuccessorPlanningRequest(
        baseline_identity_sha256=request.baseline_identity_sha256,
        mode=request.mode,
        source_sha=request.source_sha,
        cutoff_utc=request.cutoff_utc,
        as_of_utc=request.as_of_utc,
        workflow_run_id=request.workflow_run_id,
        workflow_run_attempt=request.workflow_run_attempt,
        requested_planning_scopes=scopes,
    )


def test_october_first_is_the_fixed_utc_season_boundary() -> None:
    assert derive_successor_season("2026-09-30T23:59:59Z") == "2025-26"
    assert derive_successor_season("2026-10-01T00:00:00Z") == "2026-27"

    before = _request(as_of_utc="2026-09-30T23:59:59Z")
    after = _request(as_of_utc="2026-10-01T00:00:00Z")
    assert {
        scope.parameters["season"]
        for scope in before.requested_planning_scopes
        if "season" in scope.parameters
    } == {"2025-26"}
    assert {
        scope.parameters["season"]
        for scope in after.requested_planning_scopes
        if "season" in scope.parameters
    } == {"2026-27"}


def test_daily_request_is_the_exact_13_scope_current_inventory() -> None:
    request = _request()
    scopes = _by_endpoint(request)

    assert len(request.requested_planning_scopes) == 13
    assert {endpoint: len(values) for endpoint, values in scopes.items()} == {
        "league_game_log": 5,
        "player_game_logs": 5,
        "common_all_players": 1,
        "common_team_years": 1,
        "live_score_board": 1,
    }
    assert {scope.route_id for scope in scopes["league_game_log"]} == {
        "league_game_log:stg_league_game_log:0"
    }
    assert {scope.route_id for scope in scopes["player_game_logs"]} == {
        "player_game_logs:stg_player_game_logs:0"
    }
    assert {scope.route_id for scope in scopes["common_all_players"]} == {
        "common_all_players:stg_common_all_players:0"
    }
    assert {scope.route_id for scope in scopes["common_team_years"]} == {
        "common_team_years:stg_team_years:0"
    }
    assert {scope.route_id for scope in scopes["live_score_board"]} == {
        "live_score_board:stg_live_score_board:0"
    }
    assert not any(
        scope.endpoint_name == "scoreboard_v3" for scope in request.requested_planning_scopes
    )
    assert all(
        scope.mutability is CallMutability.MUTABLE for scope in request.requested_planning_scopes
    )


def test_daily_parameters_preserve_all_five_current_season_types() -> None:
    scopes = _by_endpoint(_request())
    expected_types = {season_type.value for season_type in SeasonType}

    for endpoint in ("league_game_log", "player_game_logs"):
        assert {scope.parameters["season_type"] for scope in scopes[endpoint]} == expected_types
        assert {tuple(sorted(scope.parameters)) for scope in scopes[endpoint]} == {
            ("season", "season_type")
        }
        assert {scope.parameters["season"] for scope in scopes[endpoint]} == {"2025-26"}
    assert tuple(scope.parameters for scope in scopes["common_all_players"]) == (
        {"is_only_current_season": 1, "season": "2025-26"},
    )
    assert scopes["common_team_years"][0].parameters == {}
    assert scopes["live_score_board"][0].parameters == {}


def test_monthly_request_is_exact_35_scope_three_season_inventory() -> None:
    request = _request(SuccessorUpdateMode.MONTHLY)
    scopes = _by_endpoint(request)

    assert len(request.requested_planning_scopes) == 35
    assert {endpoint: len(values) for endpoint, values in scopes.items()} == {
        "league_game_log": 15,
        "player_game_logs": 15,
        "common_all_players": 3,
        "common_team_years": 1,
        "live_score_board": 1,
    }
    expected_seasons = {"2023-24", "2024-25", "2025-26"}
    expected_types = {season_type.value for season_type in SeasonType}
    for endpoint in ("league_game_log", "player_game_logs"):
        assert {
            (scope.parameters["season"], scope.parameters["season_type"])
            for scope in scopes[endpoint]
        } == {
            (season, season_type) for season in expected_seasons for season_type in expected_types
        }
    assert {tuple(sorted(scope.parameters.items())) for scope in scopes["common_all_players"]} == {
        (("is_only_current_season", 0), ("season", season)) for season in expected_seasons
    }
    assert scopes["common_team_years"][0].parameters == {}
    assert scopes["live_score_board"][0].parameters == {}


def test_every_logical_root_fans_out_to_every_current_result_route(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    original = staging_route_contract_bundle()
    league_route = next(
        route for route in original.routes if route.endpoint_name == "league_game_log"
    )
    added_route = replace(
        league_route,
        route_id="league_game_log:stg_league_game_log_copy:0",
        ordinal=len(original.routes) + 1,
        staging_key="stg_league_game_log_copy",
    )
    monkeypatch.setattr(
        builder_module,
        "staging_route_contract_bundle",
        lambda: SimpleNamespace(routes=(*original.routes, added_route)),
    )

    scopes = _by_endpoint(_request())
    assert len(scopes["league_game_log"]) == 10
    assert {scope.route_id for scope in scopes["league_game_log"]} == {
        league_route.route_id,
        added_route.route_id,
    }
    assert len(_request().requested_planning_scopes) == 18


def test_fixed_inputs_do_not_consult_wall_clock_season_helpers(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    expected = _request().to_dict()

    def fail(*_args: object, **_kwargs: object) -> Any:
        raise AssertionError("wall-clock season helper was consulted")

    monkeypatch.setattr(seasons_module, "current_season", fail)
    monkeypatch.setattr(seasons_module, "recent_seasons", fail)
    assert _request().to_dict() == expected


def test_validator_rejects_current_route_or_provider_contract_drift(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    request = _request()
    original = staging_route_contract_bundle()
    changed_routes = tuple(
        replace(route, provider_authority_sha256="0" * 64)
        if route.endpoint_name == "league_game_log"
        else route
        for route in original.routes
    )
    monkeypatch.setattr(
        builder_module,
        "staging_route_contract_bundle",
        lambda: SimpleNamespace(routes=changed_routes),
    )

    with pytest.raises(SuccessorPlanningRequestBuilderError, match="exact derived inventory"):
        validate_successor_planning_request(request)


def test_validator_rejects_parameter_and_season_drift() -> None:
    request = _request()
    target = next(
        scope
        for scope in request.requested_planning_scopes
        if scope.endpoint_name == "common_all_players"
    )
    changed = RequestedRouteScope.from_parameters(
        endpoint_name=target.endpoint_name,
        route_id=target.route_id,
        route_contract_sha256=target.route_contract_sha256,
        parameters={"season": "2024-25", "is_only_current_season": 0},
        mutability=target.mutability,
    )
    forged = _rebuilt(
        request,
        tuple(changed if scope is target else scope for scope in request.requested_planning_scopes),
    )

    with pytest.raises(SuccessorPlanningRequestBuilderError, match="exact derived inventory"):
        validate_successor_planning_request(forged)


def test_validator_rejects_scoreboard_v3_as_the_live_root() -> None:
    request = _request()
    bundle = staging_route_contract_bundle()
    scoreboard = next(route for route in bundle.routes if route.endpoint_name == "scoreboard_v3")
    wrong_live = RequestedRouteScope.from_parameters(
        endpoint_name=scoreboard.endpoint_name,
        route_id=scoreboard.route_id,
        route_contract_sha256=scoreboard.contract_sha256,
        parameters={},
        mutability=CallMutability.MUTABLE,
    )
    forged = _rebuilt(
        request,
        tuple(
            wrong_live if scope.endpoint_name == "live_score_board" else scope
            for scope in request.requested_planning_scopes
        ),
    )

    with pytest.raises(SuccessorPlanningRequestBuilderError, match="exact derived inventory"):
        validate_successor_planning_request(forged)


def test_validator_rejects_missing_and_extra_scopes() -> None:
    request = _request()
    with pytest.raises(SuccessorPlanningRequestBuilderError, match="exact derived inventory"):
        validate_successor_planning_request(
            _rebuilt(request, request.requested_planning_scopes[:-1])
        )

    team_scope = next(
        scope
        for scope in request.requested_planning_scopes
        if scope.endpoint_name == "common_team_years"
    )
    extra = RequestedRouteScope.from_parameters(
        endpoint_name=team_scope.endpoint_name,
        route_id=team_scope.route_id,
        route_contract_sha256=team_scope.route_contract_sha256,
        parameters={"unexpected": 1},
        mutability=team_scope.mutability,
    )
    with pytest.raises(SuccessorPlanningRequestBuilderError, match="exact derived inventory"):
        validate_successor_planning_request(
            _rebuilt(request, (*request.requested_planning_scopes, extra))
        )


def test_scope_input_order_is_canonicalized_before_exact_validation() -> None:
    request = _request()
    reordered = _rebuilt(request, tuple(reversed(request.requested_planning_scopes)))

    assert reordered.to_dict() == request.to_dict()
    assert validate_successor_planning_request(reordered) is reordered


def test_contract_blocked_support_classification_fails_instead_of_dropping(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    blocked = SimpleNamespace(classification="contract_blocked")
    monkeypatch.setattr(builder_module, "matching_support_rules", lambda **_kwargs: (blocked,))

    with pytest.raises(SuccessorPlanningRequestBuilderError, match="contract_blocked"):
        _request()


@pytest.mark.parametrize(
    "value",
    [
        "2026-10-01T00:00:00+00:00",
        "2026-10-01T00:00:00.000000Z",
        "2026-02-30T00:00:00Z",
        "2026-1-01T00:00:00Z",
    ],
)
def test_noncanonical_or_invalid_as_of_timestamp_is_rejected(value: str) -> None:
    with pytest.raises(SuccessorPlanningRequestBuilderError, match="canonical UTC"):
        derive_successor_season(value)


@pytest.mark.parametrize("field", ["workflow_run_id", "workflow_run_attempt"])
def test_boolean_workflow_identity_is_rejected_by_request_contract(field: str) -> None:
    kwargs: dict[str, object] = {
        "baseline_identity_sha256": _BASELINE_SHA,
        "mode": SuccessorUpdateMode.DAILY,
        "source_sha": _SOURCE_SHA,
        "cutoff_utc": _CUTOFF,
        "as_of_utc": _AS_OF,
        "workflow_run_id": 731,
        "workflow_run_attempt": 4,
    }
    kwargs[field] = True

    with pytest.raises(SuccessorPlanningContractError, match="positive integer"):
        build_successor_planning_request(**kwargs)  # type: ignore[arg-type]
