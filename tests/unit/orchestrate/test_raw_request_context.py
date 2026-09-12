from __future__ import annotations

from datetime import date
from typing import TYPE_CHECKING

import pytest
from nba_api.stats.library.http import NBAStatsHTTP

from nbadb.contracts.staging_route_contract import staging_route_contract_bundle
from nbadb.extract.raw_request_capture import RawRequestCaptureContextV2
from nbadb.extract.registry import EndpointRegistry
from nbadb.extract.stats.player_info import CommonAllPlayersExtractor
from nbadb.orchestrate.planning import ExtractionPlanItem
from nbadb.orchestrate.raw_request_context import (
    RawRequestContextCompilationError,
    RawRequestExecutionIdentityV1,
    build_ordinary_stats_raw_request_context_factory,
    compile_ordinary_stats_raw_request_context,
)
from nbadb.orchestrate.request_closure_production import (
    ReceiptOnlyCaptureFactory,
    build_ordinary_request_closure_authority,
)
from nbadb.orchestrate.staging_map import get_by_endpoint

if TYPE_CHECKING:
    from nbadb.orchestrate.extractor_runner import RequestClosureExecutionAuthority

_SUPPORT_DATE = date(2026, 8, 27)
_PARAMS: dict[str, object] = {
    "is_only_current_season": 0,
    "league_id": "00",
    "season": "2025-26",
}


@pytest.fixture
def authority(monkeypatch: pytest.MonkeyPatch) -> RequestClosureExecutionAuthority:
    def _unexpected_network(*_args: object, **_kwargs: object) -> None:
        raise AssertionError("raw-request context fixture attempted network I/O")

    monkeypatch.setattr(NBAStatsHTTP, "send_api_request", _unexpected_network)
    entries = get_by_endpoint("common_all_players")
    assert entries
    registry = EndpointRegistry()
    registry.register(CommonAllPlayersExtractor)
    build = build_ordinary_request_closure_authority(
        [
            ExtractionPlanItem(
                label="raw context fixture",
                pattern=entries[0].param_pattern,
                entries=entries,
                params=[dict(_PARAMS)],
                priority=0,
            )
        ],
        registry=registry,
        run_mode="init",
        support_date=_SUPPORT_DATE,
        discovery_seed_requested=False,
        recurring_live_requested=False,
    )
    assert build.scope_gaps == ()
    assert build.authority is not None
    return build.authority


def _execution(
    *,
    source_sha: str = "1" * 40,
    run_id: int = 101,
    lane_id: str = "lane-001",
) -> RawRequestExecutionIdentityV1:
    return RawRequestExecutionIdentityV1(
        source_sha=source_sha,
        run_id=run_id,
        run_attempt=1,
        chain_id="chain-001",
        lane_id=lane_id,
    )


def test_compiler_joins_request_competition_scope_and_endpoint_authority(
    authority: RequestClosureExecutionAuthority,
) -> None:
    context = compile_ordinary_stats_raw_request_context(
        authority,
        _execution(),
        "common_all_players",
        dict(_PARAMS),
    )

    assert type(context) is RawRequestCaptureContextV2
    assert context.source_sha == "1" * 40
    assert context.run_id == 101
    assert context.run_attempt == 1
    assert context.chain_id == "chain-001"
    assert context.lane_id == "lane-001"
    assert len(context.provider_calls) == 1
    call = context.provider_calls[0]
    logical_call = authority.logical_calls[0]
    competition = authority.competition_authorities[0]
    route = staging_route_contract_bundle().by_route_id[
        "common_all_players:stg_common_all_players:0"
    ]
    assert call.request_ordinal == 0
    assert call.provider_call_role == "primary"
    assert call.provider_call_ordinal == 0
    assert call.source_family == "stats"
    assert call.endpoint_id == competition.request_binding.endpoint_id
    assert call.provider_request_sha256 == logical_call.provider_request_sha256
    assert call.endpoint_contract_sha256 == route.endpoint_contract_sha256
    assert call.competition_id == "00"
    assert call.competition_identity_sha256 == competition.qualified_request.source_request_sha256
    assert call.scope_sha256 == authority.scope.scope_sha256
    assert call.pagination_sha256 is None
    assert call.page_ordinal is None


def test_semantic_request_is_execution_stable_but_invocation_is_not(
    authority: RequestClosureExecutionAuthority,
) -> None:
    first = compile_ordinary_stats_raw_request_context(
        authority,
        _execution(),
        "common_all_players",
        dict(_PARAMS),
    ).provider_calls[0]
    second = compile_ordinary_stats_raw_request_context(
        authority,
        _execution(source_sha="2" * 40, run_id=202, lane_id="lane-002"),
        "common_all_players",
        dict(_PARAMS),
    ).provider_calls[0]

    assert first.semantic_request_sha256 == second.semantic_request_sha256
    assert first.logical_invocation_sha256 != second.logical_invocation_sha256


def test_factory_is_deterministic_for_one_bound_execution(
    authority: RequestClosureExecutionAuthority,
) -> None:
    factory = build_ordinary_stats_raw_request_context_factory(authority, _execution())

    first = factory("common_all_players", dict(_PARAMS))
    second = factory("common_all_players", dict(_PARAMS))

    assert first == second


def test_receipt_only_factory_projects_exact_public_execution_identity() -> None:
    execution = _execution()
    factory = ReceiptOnlyCaptureFactory(execution_identity=execution)

    context = factory.contract_for("common_all_players", dict(_PARAMS)).context

    assert context.workflow_run_id == execution.run_id
    assert context.workflow_run_attempt == execution.run_attempt
    assert context.chain_id == execution.chain_id
    assert context.lane_id == execution.lane_id
    assert context.semantic_source_sha == execution.source_sha


def test_receipt_only_factory_rejects_foreign_execution_identity() -> None:
    with pytest.raises(TypeError, match="execution identity must be exact"):
        ReceiptOnlyCaptureFactory(execution_identity=object())  # type: ignore[arg-type]


@pytest.mark.parametrize(
    ("endpoint_name", "params"),
    [
        ("static_players", {}),
        ("common_all_players", {**_PARAMS, "season": "2024-25"}),
        ("common_all_players", {**_PARAMS, "unknown": "value"}),
    ],
)
def test_compiler_rejects_uncovered_or_mutated_logical_calls(
    authority: RequestClosureExecutionAuthority,
    endpoint_name: str,
    params: dict[str, object],
) -> None:
    with pytest.raises(
        RawRequestContextCompilationError,
        match="no unique logical-call authority",
    ):
        compile_ordinary_stats_raw_request_context(
            authority,
            _execution(),
            endpoint_name,
            params,
        )


@pytest.mark.parametrize(
    "kwargs",
    [
        {"source_sha": "not-a-sha"},
        {"run_id": True},
        {"run_id": 0},
        {"lane_id": "vpn-lane"},
        {"lane_id": "host:runner"},
    ],
)
def test_execution_identity_rejects_malformed_or_forbidden_values(
    kwargs: dict[str, object],
) -> None:
    values: dict[str, object] = {
        "source_sha": "1" * 40,
        "run_id": 101,
        "run_attempt": 1,
        "chain_id": "chain-001",
        "lane_id": "lane-001",
    }
    values.update(kwargs)
    with pytest.raises(RawRequestContextCompilationError):
        RawRequestExecutionIdentityV1(**values)  # type: ignore[arg-type]


def test_compiler_requires_exact_execution_contract(
    authority: RequestClosureExecutionAuthority,
) -> None:
    with pytest.raises(
        RawRequestContextCompilationError,
        match="exact execution identity",
    ):
        compile_ordinary_stats_raw_request_context(
            authority,
            object(),  # type: ignore[arg-type]
            "common_all_players",
            dict(_PARAMS),
        )
