from __future__ import annotations

import json
from datetime import date
from unittest.mock import MagicMock

import pytest
from nba_api.stats.library.http import NBAStatsHTTP, NBAStatsResponse

from nbadb.core.errors import ExtractionError, ParserInputCaptureIntegrityError
from nbadb.core.nba_api_request_surface import (
    materialize_provider_request,
    pinned_request_surface_authority,
)
from nbadb.core.nba_api_runtime_contract import pinned_runtime_contracts
from nbadb.extract.bronze import (
    PARSER_INPUT_REPRESENTATION,
    LogicalCallReceiptBinding,
    ParserInputContext,
    canonical_parameters_sha256,
)
from nbadb.extract.nba_api_adapter import NbaDbStatsHTTP
from nbadb.extract.registry import EndpointRegistry
from nbadb.extract.static.players import StaticPlayersExtractor
from nbadb.extract.stats.league_stats import LeagueDashTeamStatsExtractor
from nbadb.extract.stats.legacy_versions import BoxScoreTraditionalV2Extractor
from nbadb.extract.stats.player_info import CommonAllPlayersExtractor
from nbadb.orchestrate.extractor_runner import ExtractorRunner
from nbadb.orchestrate.orchestrator import Orchestrator
from nbadb.orchestrate.planning import ExtractionPlanItem
from nbadb.orchestrate.request_closure_production import (
    ReceiptOnlyCaptureFactory,
    ReceiptOnlyParserInputSink,
    build_ordinary_request_closure_authority,
)
from nbadb.orchestrate.staging_map import get_by_endpoint

_SUPPORT_DATE = date(2026, 8, 19)
_COMMON_ALL_PLAYERS_SCOPE: dict[str, object] = {
    "is_only_current_season": 0,
    "league_id": "00",
    "season": "2025-26",
}


def _plan(endpoint_name: str) -> list[ExtractionPlanItem]:
    entries = get_by_endpoint(endpoint_name)
    assert entries
    params = dict(_COMMON_ALL_PLAYERS_SCOPE) if endpoint_name == "common_all_players" else {}
    return [
        ExtractionPlanItem(
            label=f"request closure: {endpoint_name}",
            pattern=entries[0].param_pattern,
            entries=entries,
            params=[params],
            priority=0,
        )
    ]


def test_builder_probes_real_wrapper_without_network_and_binds_explicit_scope(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def _unexpected_network(*_args: object, **_kwargs: object) -> None:
        raise AssertionError("request-closure planning attempted network I/O")

    monkeypatch.setattr(NBAStatsHTTP, "send_api_request", _unexpected_network)
    registry = EndpointRegistry()
    registry.register(CommonAllPlayersExtractor)

    build = build_ordinary_request_closure_authority(
        _plan("common_all_players"),
        registry=registry,
        run_mode="init",
        support_date=_SUPPORT_DATE,
        discovery_seed_requested=False,
        recurring_live_requested=False,
    )

    assert build.scope_gaps == ()
    assert build.authority is not None
    authority = build.authority
    assert len(authority.route_manifest.routes) == 1
    assert len(authority.logical_calls) == 1
    assert len(authority.competition_authorities) == 1
    logical_call = authority.logical_calls[0]
    assert logical_call.endpoint_name == "common_all_players"
    assert logical_call.logical_parameters_sha256 == canonical_parameters_sha256(
        _COMMON_ALL_PLAYERS_SCOPE
    )
    assert logical_call.provider_parameters_sha256 == canonical_parameters_sha256(
        _COMMON_ALL_PLAYERS_SCOPE
    )
    physical_route = "common_all_players:stg_common_all_players:0"
    resolved = authority.resolve_call(
        "common_all_players",
        dict(_COMMON_ALL_PLAYERS_SCOPE),
        (physical_route,),
    )
    assert resolved.provider_request_sha256 == logical_call.provider_request_sha256
    assert (
        authority.request_binding_for(logical_call.provider_request_sha256)
        == authority.competition_authorities[0].request_binding
    )
    assert (
        authority.competition_authorities[0].request_binding.source_request_sha256
        == authority.competition_authorities[0].qualified_request.source_request_sha256
    )
    assert resolved.staging_route_aliases == ((logical_call.route_ids[0], physical_route),)
    assert (
        authority.resolve_call_if_covered(
            "static_players",
            {},
            ("static_players:stg_static_players:0",),
        )
        is None
    )
    with pytest.raises(
        ParserInputCaptureIntegrityError,
        match="staging-route aliases differ",
    ):
        authority.resolve_call_if_covered(
            "common_all_players",
            dict(_COMMON_ALL_PLAYERS_SCOPE),
            (physical_route, "static_players:stg_static_players:0"),
        )

    dimensions = {
        (dimension.dependency_id, dimension.parameter_name): dimension.values
        for dimension in authority.scope.dimensions
    }
    assert dimensions[("league_scope", "league_id")] == ("00",)
    assert dimensions[("season_scope", "season")] == ("2025-26",)
    assert dimensions[("explicit_scope_manifest", "is_only_current_season")] == (0,)


def test_builder_seals_distinct_logical_and_provider_semantic_parameter_hashes() -> None:
    logical_parameters = {
        "season": "2024-25",
        "season_type": "Regular Season",
    }
    provider_parameters = {
        "season": "2024-25",
        "season_type_all_star": "Regular Season",
    }
    endpoint_name = "league_dash_team_stats"
    entries = get_by_endpoint(endpoint_name)
    assert entries
    registry = EndpointRegistry()
    registry.register(LeagueDashTeamStatsExtractor)
    build = build_ordinary_request_closure_authority(
        [
            ExtractionPlanItem(
                label=f"request closure alias: {endpoint_name}",
                pattern=entries[0].param_pattern,
                entries=entries,
                params=[logical_parameters],
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
    assert len(build.authority.logical_calls) == 1
    logical_call = build.authority.logical_calls[0]
    surface = pinned_request_surface_authority()
    provider_request = materialize_provider_request(
        surface.endpoint("stats", "LeagueDashTeamStats"),
        provider_parameters,
        request_surface_sha256=surface.surface_sha256,
        runtime_contract_payload_sha256=surface.runtime_contract_payload_sha256,
    )
    assert logical_call.logical_parameters_sha256 == canonical_parameters_sha256(logical_parameters)
    assert logical_call.provider_parameters_sha256 == canonical_parameters_sha256(
        dict(provider_request.materialized_parameters)
    )
    assert logical_call.logical_parameters_sha256 != logical_call.provider_parameters_sha256


def test_builder_keeps_static_scope_explicitly_incomplete() -> None:
    build = build_ordinary_request_closure_authority(
        _plan("static_players"),
        registry=EndpointRegistry(),
        run_mode="init",
        support_date=_SUPPORT_DATE,
        discovery_seed_requested=False,
        recurring_live_requested=False,
    )

    assert build.authority is None
    assert len(build.scope_gaps) == 1
    gap = build.scope_gaps[0]
    assert gap.reason_code == "static_receipt_not_bound"
    assert gap.endpoint_names == ("static_players",)
    assert gap.logical_call_count == 1


def test_builder_does_not_synthesize_receipt_bound_dynamic_competition_root() -> None:
    endpoint_name = "box_score_traditional_v2"
    entries = get_by_endpoint(endpoint_name)
    assert entries
    registry = EndpointRegistry()
    registry.register(BoxScoreTraditionalV2Extractor)
    build = build_ordinary_request_closure_authority(
        [
            ExtractionPlanItem(
                label="dynamic competition root",
                pattern=entries[0].param_pattern,
                entries=entries,
                params=[{"game_id": "0022400001"}],
                priority=0,
            )
        ],
        registry=registry,
        run_mode="init",
        support_date=_SUPPORT_DATE,
        discovery_seed_requested=False,
        recurring_live_requested=False,
    )

    assert build.authority is None
    assert len(build.scope_gaps) == 1
    gap = build.scope_gaps[0]
    assert gap.reason_code == "provider_boundary_unproven"
    assert gap.endpoint_names == (endpoint_name,)
    assert gap.logical_call_count == 1


def test_post_commit_join_skips_only_receipts_disjoint_from_assured_routes() -> None:
    registry = EndpointRegistry()
    registry.register(CommonAllPlayersExtractor)
    build = build_ordinary_request_closure_authority(
        _plan("common_all_players"),
        registry=registry,
        run_mode="init",
        support_date=_SUPPORT_DATE,
        discovery_seed_requested=False,
        recurring_live_requested=False,
    )
    assert build.authority is not None
    orchestrator = object.__new__(Orchestrator)
    gap_binding = LogicalCallReceiptBinding(
        logical_call_receipt_sha256="1" * 64,
        endpoint_name="static_players",
        logical_parameters_sha256="2" * 64,
        provider_authority_sha256="3" * 64,
        result_route_ids=("static_players:stg_static_players:0",),
    )
    store = MagicMock()
    orchestrator._record_committed_request_closure(
        store,
        [
            {
                "receipt_binding": gap_binding,
                "pending_request_observations": (),
            }
        ],
        build.authority,
    )
    store.committed_logical_call_receipts.assert_not_called()

    assured_binding = LogicalCallReceiptBinding(
        logical_call_receipt_sha256="4" * 64,
        endpoint_name="common_all_players",
        logical_parameters_sha256="5" * 64,
        provider_authority_sha256="6" * 64,
        result_route_ids=("common_all_players:stg_common_all_players:0",),
    )
    with pytest.raises(
        ParserInputCaptureIntegrityError,
        match="omitted its pending request observation",
    ):
        orchestrator._record_committed_request_closure(
            store,
            [
                {
                    "receipt_binding": assured_binding,
                    "pending_request_observations": (),
                }
            ],
            build.authority,
        )


@pytest.mark.asyncio
async def test_mixed_stats_and_static_authorities_discard_parser_bytes_after_persistence(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    contract = pinned_runtime_contracts()["CommonAllPlayers"]
    payload = {
        "resultSets": [
            {
                "name": "CommonAllPlayers",
                "headers": list(contract.result_sets[0].expected_columns),
                "rowSet": [],
            }
        ]
    }

    def _response(*_args: object, **_kwargs: object) -> NBAStatsResponse:
        return NBAStatsResponse(json.dumps(payload), 200, "fixture://common-all-players")

    monkeypatch.setattr(NbaDbStatsHTTP, "send_api_request", _response)
    registry = EndpointRegistry()
    registry.register(CommonAllPlayersExtractor)
    registry.register(StaticPlayersExtractor)
    stats_entries = get_by_endpoint("common_all_players")
    static_entries = get_by_endpoint("static_players")
    plan = [
        ExtractionPlanItem(
            label="proved stats request closure",
            pattern=stats_entries[0].param_pattern,
            entries=stats_entries,
            params=[dict(_COMMON_ALL_PLAYERS_SCOPE)],
            priority=0,
        ),
        ExtractionPlanItem(
            label="fixed-root static request closure",
            pattern=static_entries[0].param_pattern,
            entries=static_entries,
            params=[{}],
            priority=0,
        ),
    ]
    build = build_ordinary_request_closure_authority(
        plan,
        registry=registry,
        run_mode="init",
        support_date=_SUPPORT_DATE,
        discovery_seed_requested=False,
        recurring_live_requested=False,
    )
    assert build.authority is not None
    assert build.scope_gaps == ()
    assert tuple(item.endpoint_name for item in build.static_authorities) == ("static_players",)

    settings = MagicMock()
    settings.semaphore_tiers = {"default": 2, "player_info": 2, "static": 2}
    settings.endpoint_semaphore_limits = {}
    settings.pbp_chunk_size = 50
    settings.default_chunk_size = 50
    settings.thread_pool_size = 2
    settings.adaptive_rate_min = 1.0
    settings.adaptive_rate_recovery = 50
    settings.endpoint_rate_limits = {}
    settings.endpoint_request_timeouts = {}
    settings.endpoint_chunk_size_limits = {}
    settings.endpoint_retry_budgets = {}
    settings.zero_progress_abort_endpoints = set()
    settings.response_contract_circuit_thresholds = {}
    settings.extract_max_retries = 0
    settings.extract_retry_base_delay = 0.0
    settings.circuit_breaker_threshold = 5
    settings.circuit_breaker_max_wait = 600.0
    settings.latency_window_size = 10
    journal = MagicMock()
    journal.was_extracted_batch.return_value = set()
    receipt_factory = ReceiptOnlyCaptureFactory()
    runner = ExtractorRunner(
        registry,
        settings,
        journal,
        capture_contract_factory=receipt_factory.contract_for,
    )
    persistence_calls = 0

    def _persist(_frames: object, *, source_results: object) -> None:
        nonlocal persistence_calls
        persistence_calls += 1
        assert source_results
        assert receipt_factory.sink.outstanding_parser_input_bytes > 0

    try:
        result = await runner.run_pattern_result(
            stats_entries[0].param_pattern,
            [dict(_COMMON_ALL_PLAYERS_SCOPE)],
            stats_entries,
            persist_chunk_results=_persist,
            retain_frames=False,
            request_closure_authority=build.authority,
            support_date=_SUPPORT_DATE,
        )
    finally:
        runner.shutdown()

    assert result.is_complete
    assert result.success_count == 1
    assert len(result.pending_request_observations) == 1
    assert persistence_calls == 1
    assert receipt_factory.sink.outstanding_parser_input_bytes == 0


def test_receipt_only_sink_preserves_adversarial_bytes_until_shared_receipts_discard() -> None:
    sink = ReceiptOnlyParserInputSink(max_response_bytes=256, max_outstanding_bytes=256)
    payload = '{"label":"München 🏀","large":9223372036854775808,"null":null}'
    captured = sink.store_parser_input(
        payload,
        representation=PARSER_INPUT_REPRESENTATION,
    )
    parameters = {
        "label": "München 🏀",
        "large": 2**63,
        "nullable": None,
    }
    provider_authority = "a" * 64
    receipt_digests: list[str] = []
    for attempt_id in ("receipt-only-one", "receipt-only-two"):
        context = ParserInputContext(attempt_id=attempt_id)
        receipt_digest = sink.record_response_attempt(
            context=context,
            transport_kind="http_response",
            source_family="stats",
            endpoint_id="CommonAllPlayers",
            endpoint_slug="commonallplayers",
            parameters=parameters,
            provider_authority_sha256=provider_authority,
            contract_sha256="b" * 64,
            status_code=200,
            captured=captured,
            outcome="success_empty",
            failure_class=None,
            root_exception_class=None,
            result_sets=(),
        )
        sink.record_logical_call(
            context=context,
            logical_endpoint_id="common_all_players",
            logical_parameters=parameters,
            provider_authority_sha256=provider_authority,
            response_receipt_sha256s=(receipt_digest,),
            successful_response_ordinals=(0,),
            result_route_ids=("common_all_players:stg_common_all_players:0",),
        )
        receipt_digests.append(receipt_digest)

    assert sink.outstanding_parser_input_bytes == len(payload.encode("utf-8"))
    assert sink.replay_parser_input(receipt_digests[0]) == payload.encode("utf-8")
    sink.discard_parser_inputs((receipt_digests[0],))
    assert sink.outstanding_parser_input_bytes == len(payload.encode("utf-8"))
    assert sink.replay_parser_input(receipt_digests[1]) == payload.encode("utf-8")
    with pytest.raises(ExtractionError, match="no retained parser input"):
        sink.replay_parser_input(receipt_digests[0])

    sink.discard_parser_inputs((receipt_digests[1],))
    assert sink.outstanding_parser_input_bytes == 0
    with pytest.raises(ExtractionError, match="no retained parser input"):
        sink.replay_parser_input(receipt_digests[1])

    bounded = ReceiptOnlyParserInputSink(max_response_bytes=8, max_outstanding_bytes=8)
    with pytest.raises(ParserInputCaptureIntegrityError, match="per-response bound"):
        bounded.store_parser_input(
            "Unicode 🏀",
            representation=PARSER_INPUT_REPRESENTATION,
        )
