from __future__ import annotations

import json
from dataclasses import replace
from typing import TYPE_CHECKING, Any
from unittest.mock import MagicMock

import polars as pl
import pytest
import requests
from nba_api.stats.endpoints import CommonAllPlayers
from nba_api.stats.library.http import NBAStatsResponse

from nbadb.core.config import NbaDbSettings
from nbadb.core.db import DBManager
from nbadb.core.errors import ParserInputCaptureIntegrityError
from nbadb.core.nba_api_competition_identity import (
    bind_explicit_competition_request,
    build_competition_terminal_request_binding,
    compile_competition_identity_requirements,
)
from nbadb.core.nba_api_provenance import expected_nba_api_provider_authority
from nbadb.core.nba_api_request_surface import (
    RequestScopeDimension,
    RequestScopeManifest,
    materialize_provider_request,
    pinned_request_surface_authority,
)
from nbadb.core.nba_api_runtime_contract import pinned_runtime_contracts
from nbadb.extract.base import BaseExtractor
from nbadb.extract.bronze import BronzeCaptureStore, BronzeLimits, ParserInputContext
from nbadb.extract.nba_api_adapter import NbaApiCaptureContract, NbaDbStatsHTTP
from nbadb.orchestrate.extractor_runner import (
    ExtractorRunner,
    PendingRequestObservation,
    RequestClosureCompetitionAuthority,
    RequestClosureExecutionAuthority,
    RequestClosureStagingRouteAlias,
)
from nbadb.orchestrate.orchestrator import Orchestrator
from nbadb.orchestrate.planning import ExtractionPlanItem
from nbadb.orchestrate.request_closure_runtime import (
    PersistedStagingReceipt,
    RouteRequestSpecInput,
    build_authoritative_route_manifest,
)
from nbadb.orchestrate.staging_map import StagingEntry

if TYPE_CHECKING:
    from collections.abc import Iterator
    from pathlib import Path

_SOURCE_SHA256 = "a" * 64
_STAGING_ROOT_SHA256 = "b" * 64
_ENDPOINT_NAME = "closure_stats_test"
_STAGING_KEY = "stg_closure_stats_test"
_BASE_ROUTE = f"{_ENDPOINT_NAME}:{_STAGING_KEY}:0"
_FALLBACK_ROUTE = f"{_ENDPOINT_NAME}:stg_nba_api_lossless_result_cells:1"


class _StatsExtractor(BaseExtractor):
    endpoint_name = _ENDPOINT_NAME
    category = "default"

    async def extract(self, **params: Any) -> pl.DataFrame:
        return self._from_nba_api(CommonAllPlayers, **params)


def _settings(**overrides: object) -> MagicMock:
    settings = MagicMock()
    settings.semaphore_tiers = {"default": 5}
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
    for key, value in overrides.items():
        setattr(settings, key, value)
    return settings


def _journal() -> MagicMock:
    journal = MagicMock()
    journal.was_extracted.return_value = False
    journal.was_extracted_batch.return_value = set()
    journal.get_failed.return_value = []
    return journal


def _registry() -> MagicMock:
    registry = MagicMock()
    registry.get.return_value = _StatsExtractor
    return registry


def _provider_params() -> dict[str, object]:
    authority = pinned_request_surface_authority()
    endpoint = authority.endpoint("stats", "CommonAllPlayers")
    request = materialize_provider_request(
        endpoint,
        {
            "is_only_current_season": 0,
            "league_id": "00",
            "season": "2025-26",
        },
        request_surface_sha256=authority.surface_sha256,
        runtime_contract_payload_sha256=authority.runtime_contract_payload_sha256,
    )
    return dict(request.materialized_parameters)


def _competition_authority(
    params: dict[str, object],
    *,
    manifest_sha256: str,
    scope_sha256: str,
    route_ids: tuple[str, ...],
) -> RequestClosureCompetitionAuthority:
    surface = pinned_request_surface_authority()
    provider_request = materialize_provider_request(
        surface.endpoint("stats", "CommonAllPlayers"),
        params,
        request_surface_sha256=surface.surface_sha256,
        runtime_contract_payload_sha256=surface.runtime_contract_payload_sha256,
    )
    requirement = next(
        item
        for item in compile_competition_identity_requirements()
        if item.repo_endpoint_name == "common_all_players"
        and item.provider_endpoint_id == "CommonAllPlayers"
        and item.league_id == params["league_id"]
        and item.role_binding.binding_strategy == "explicit_applicability_cell"
    )
    qualified = bind_explicit_competition_request(requirement, provider_request)
    return RequestClosureCompetitionAuthority(
        qualified_request=qualified,
        request_binding=build_competition_terminal_request_binding(
            qualified,
            route_manifest_sha256=manifest_sha256,
            scope_sha256=scope_sha256,
            route_ids=route_ids,
        ),
    )


def _execution_authority(
    params: dict[str, object],
    *,
    include_fallback: bool = False,
) -> RequestClosureExecutionAuthority:
    route_ids = (_BASE_ROUTE, _FALLBACK_ROUTE) if include_fallback else (_BASE_ROUTE,)
    manifest = build_authoritative_route_manifest(
        tuple(
            RouteRequestSpecInput(
                route_id=route_id,
                source_family="stats",
                endpoint_id="CommonAllPlayers",
                parameters=tuple(sorted(params.items())),
            )
            for route_id in sorted(route_ids)
        )
    )
    surface = pinned_request_surface_authority()
    dimension = RequestScopeDimension(
        dependency_id="explicit_scope_manifest",
        source_kind="runner_integration_test",
        source_authority_sha256=_SOURCE_SHA256,
        values=(params["season"],),
        endpoint_id="CommonAllPlayers",
        parameter_name="season",
    )
    scope = RequestScopeManifest(
        request_surface_sha256=surface.surface_sha256,
        scope_id="runner_integration_test",
        seed_route_ids=(_BASE_ROUTE,),
        dimensions=(dimension,),
    )
    return RequestClosureExecutionAuthority(
        manifest,
        scope,
        competition_authorities=(
            _competition_authority(
                params,
                manifest_sha256=manifest.manifest_sha256,
                scope_sha256=scope.scope_sha256,
                route_ids=tuple(route.route_id for route in manifest.routes),
            ),
        ),
    )


def _multi_execution_authority(
    param_sets: list[dict[str, object]],
) -> RequestClosureExecutionAuthority:
    route_inputs: list[RouteRequestSpecInput] = []
    aliases: list[RequestClosureStagingRouteAlias] = []
    for ordinal, params in enumerate(param_sets):
        manifest_route_id = f"{_BASE_ROUTE}:scope:{ordinal}"
        route_inputs.append(
            RouteRequestSpecInput(
                route_id=manifest_route_id,
                source_family="stats",
                endpoint_id="CommonAllPlayers",
                parameters=tuple(sorted(params.items())),
            )
        )
        aliases.append(RequestClosureStagingRouteAlias(manifest_route_id, _BASE_ROUTE))
    manifest = build_authoritative_route_manifest(
        tuple(sorted(route_inputs, key=lambda x: x.route_id))
    )
    surface = pinned_request_surface_authority()
    dimensions = (
        RequestScopeDimension(
            dependency_id="explicit_scope_manifest",
            source_kind="runner_multi_call_test",
            source_authority_sha256=_SOURCE_SHA256,
            values=(base_value,),
            endpoint_id="CommonAllPlayers",
            parameter_name="is_only_current_season",
        )
        for base_value in {params["is_only_current_season"] for params in param_sets}
    )
    dimension_items = [*dimensions]
    dimension_items.extend(
        (
            RequestScopeDimension(
                dependency_id="league_scope",
                source_kind="runner_multi_call_test",
                source_authority_sha256=_SOURCE_SHA256,
                values=tuple(sorted({params["league_id"] for params in param_sets})),
            ),
            RequestScopeDimension(
                dependency_id="season_scope",
                source_kind="runner_multi_call_test",
                source_authority_sha256=_SOURCE_SHA256,
                values=tuple(sorted({params["season"] for params in param_sets})),
            ),
        )
    )
    scope = RequestScopeManifest(
        request_surface_sha256=surface.surface_sha256,
        scope_id="runner_multi_call_test",
        seed_route_ids=(manifest.routes[0].route_id,),
        dimensions=tuple(sorted(dimension_items, key=lambda item: item.dimension_sha256)),
    )
    return RequestClosureExecutionAuthority(
        manifest,
        scope,
        tuple(sorted(aliases)),
        competition_authorities=tuple(
            sorted(
                (
                    _competition_authority(
                        params,
                        manifest_sha256=manifest.manifest_sha256,
                        scope_sha256=scope.scope_sha256,
                        route_ids=(f"{_BASE_ROUTE}:scope:{ordinal}",),
                    )
                    for ordinal, params in enumerate(param_sets)
                ),
                key=lambda item: item.request_binding.provider_request_sha256,
            )
        ),
    )


@pytest.fixture
def capture_store(tmp_path: Path) -> Iterator[BronzeCaptureStore]:
    with BronzeCaptureStore(
        tmp_path / "private" / "bronze",
        public_roots=(tmp_path / "public",),
        limits=BronzeLimits(
            max_response_bytes=1_000_000,
            max_generation_stored_bytes=4_000_000,
            minimum_free_bytes=1,
        ),
    ) as store:
        yield store


def _capture_factory(store: BronzeCaptureStore):
    calls = 0

    def factory(_endpoint: str, _params: dict[str, object]) -> NbaApiCaptureContract:
        nonlocal calls
        calls += 1
        return NbaApiCaptureContract(
            sink=store,
            context=ParserInputContext(attempt_id=f"closure-runner-{calls}"),
            provider_authority_sha256=(expected_nba_api_provider_authority()["authority_sha256"]),
            endpoint_contract_sha256="0" * 64,
        )

    return factory


def _payload(*, rows: list[list[object]], additive: bool = False) -> dict[str, object]:
    contract = pinned_runtime_contracts()["CommonAllPlayers"]
    headers = list(contract.result_sets[0].expected_columns)
    result_sets: list[dict[str, object]] = [
        {"name": "CommonAllPlayers", "headers": headers, "rowSet": rows}
    ]
    if additive:
        result_sets.append({"name": "AdditiveProviderSet", "headers": ["EXTRA"], "rowSet": [[7]]})
    return {"resultSets": result_sets}


def _row() -> list[object]:
    width = len(pinned_runtime_contracts()["CommonAllPlayers"].result_sets[0].expected_columns)
    return [1, *(f"value-{index}" for index in range(1, width))]


def _install_responses(
    monkeypatch: pytest.MonkeyPatch,
    outcomes: list[dict[str, object] | BaseException],
) -> list[str]:
    events: list[str] = []

    def send(_self: object, **_kwargs: object) -> NBAStatsResponse:
        events.append("provider")
        outcome = outcomes.pop(0)
        if isinstance(outcome, BaseException):
            raise outcome
        return NBAStatsResponse(json.dumps(outcome), 200, "fixture://stats")

    monkeypatch.setattr(NbaDbStatsHTTP, "send_api_request", send)
    return events


def _runner(
    store: BronzeCaptureStore,
    *,
    retries: int = 0,
    sealed_admission: bool = True,
) -> tuple[ExtractorRunner, MagicMock]:
    journal = _journal()
    runner = ExtractorRunner(
        _registry(),
        _settings(extract_max_retries=retries),
        journal,
        capture_contract_factory=_capture_factory(store),
        call_admission=(lambda *_args: None) if sealed_admission else None,
        conditional_route_admission=(lambda *_args: None) if sealed_admission else None,
    )
    return runner, journal


def _staging_receipt(pending: PendingRequestObservation) -> PersistedStagingReceipt:
    result = pending.bronze_result_sets[0]
    return PersistedStagingReceipt(
        result_set_ordinal=0,
        result_set_name="CommonAllPlayers",
        staging_key=_STAGING_KEY,
        row_count=result.row_count,
        result_set_payload_sha256=result.normalized_output_sha256,
        staging_receipt_root_sha256=_STAGING_ROOT_SHA256,
    )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "rows,expected_state", [([_row()], "success_nonempty"), ([], "success_empty")]
)
async def test_stats_success_exposes_pending_evidence_then_binds_after_commit(
    monkeypatch: pytest.MonkeyPatch,
    capture_store: BronzeCaptureStore,
    rows: list[list[object]],
    expected_state: str,
) -> None:
    _install_responses(monkeypatch, [_payload(rows=rows)])
    params = _provider_params()
    authority = _execution_authority(params)
    runner, journal = _runner(capture_store)
    persisted_sources: list[dict[str, object]] = []

    def persist(
        _frames: dict[str, pl.DataFrame],
        *,
        source_results: list[dict[str, object]],
    ) -> None:
        persisted_sources.extend(source_results)

    result = await runner.run_pattern_result(
        "season",
        [params],
        [StagingEntry(_ENDPOINT_NAME, _STAGING_KEY, "season")],
        persist_chunk_results=persist,
        required_route_ids=(_BASE_ROUTE,),
        retain_frames=False,
        request_closure_authority=authority,
    )

    assert result.frames == {}
    assert len(result.pending_request_observations) == 1
    pending = result.pending_request_observations[0]
    assert pending.state == expected_state
    assert pending.result_contract == "pinned_exact"
    assert persisted_sources[0]["pending_request_observations"] == (pending,)
    assert runner.request_closure_pending_snapshot() == (pending,)
    assert PendingRequestObservation.from_canonical_bytes(pending.canonical_bytes) == pending
    observation = pending.bind_committed_staging_receipts(
        authority,
        (_staging_receipt(pending),),
    )
    assert observation.state == expected_state
    assert observation.staging_receipts[0].staging_receipt_root_sha256 == (_STAGING_ROOT_SHA256)
    journal.record_success.assert_called_once()


@pytest.mark.asyncio
async def test_additive_stats_fallback_stays_lossless_pending_evidence(
    monkeypatch: pytest.MonkeyPatch,
    capture_store: BronzeCaptureStore,
) -> None:
    _install_responses(monkeypatch, [_payload(rows=[_row()], additive=True)])
    params = _provider_params()
    authority = _execution_authority(params, include_fallback=True)
    runner, _journal_mock = _runner(capture_store)

    result = await runner.run_pattern_result(
        "season",
        [params],
        [StagingEntry(_ENDPOINT_NAME, _STAGING_KEY, "season")],
        persist_chunk_results=lambda *_args, **_kwargs: None,
        required_route_ids=(_BASE_ROUTE,),
        request_closure_authority=authority,
    )

    pending = result.pending_request_observations[0]
    assert pending.result_contract == "lossless_drift"
    assert [
        (item.name, item.provider_index, item.canonical_index)
        for item in pending.bronze_result_sets
    ] == [
        ("CommonAllPlayers", 0, None),
        ("AdditiveProviderSet", 1, None),
    ]
    with pytest.raises(ParserInputCaptureIntegrityError, match="many-to-one"):
        pending.bind_committed_staging_receipts(authority, (_staging_receipt(pending),))


@pytest.mark.asyncio
async def test_success_uses_only_the_terminal_retry_receipt(
    monkeypatch: pytest.MonkeyPatch,
    capture_store: BronzeCaptureStore,
) -> None:
    _install_responses(
        monkeypatch,
        [requests.Timeout("first attempt"), _payload(rows=[_row()])],
    )
    params = _provider_params()
    authority = _execution_authority(params)
    runner, _journal_mock = _runner(capture_store, retries=1)

    result = await runner.run_pattern_result(
        "season",
        [params],
        [StagingEntry(_ENDPOINT_NAME, _STAGING_KEY, "season")],
        persist_chunk_results=lambda *_args, **_kwargs: None,
        required_route_ids=(_BASE_ROUTE,),
        request_closure_authority=authority,
    )

    pending = result.pending_request_observations[0]
    assert (pending.attempt_count, pending.retry_ordinal, pending.request_ordinal) == (2, 1, 0)
    assert capture_store.load_recorded_attempt(pending.response_receipt_sha256).outcome == (
        "success_nonempty"
    )


@pytest.mark.asyncio
async def test_one_authority_covers_multiple_concurrent_parameter_calls(
    monkeypatch: pytest.MonkeyPatch,
    capture_store: BronzeCaptureStore,
) -> None:
    events = _install_responses(
        monkeypatch,
        [_payload(rows=[_row()]), _payload(rows=[_row()])],
    )
    base_params = _provider_params()
    param_sets = [
        {**base_params, "season": "1946-47"},
        {**base_params, "season": "1947-48"},
    ]
    authority = _multi_execution_authority(param_sets)
    runner, journal = _runner(capture_store, sealed_admission=False)
    persisted_sources: list[dict[str, object]] = []

    result = await runner.run_pattern_result(
        "season",
        param_sets,
        [StagingEntry(_ENDPOINT_NAME, _STAGING_KEY, "season")],
        persist_chunk_results=lambda _frames, *, source_results: persisted_sources.extend(
            source_results
        ),
        retain_frames=False,
        request_closure_authority=authority,
    )

    assert result.is_complete
    assert result.success_count == 2
    assert len(events) == 2
    assert len(persisted_sources) == 2
    assert len(result.pending_request_observations) == 2
    assert len({item.provider_request_sha256 for item in result.pending_request_observations}) == 2
    assert {item.route_ids[0] for item in result.pending_request_observations} == {
        route.route_id for route in authority.route_manifest.routes
    }
    assert journal.record_success.call_count == 2


@pytest.mark.asyncio
async def test_orchestrator_persists_green_multi_call_inventory_after_commit(
    monkeypatch: pytest.MonkeyPatch,
    capture_store: BronzeCaptureStore,
    tmp_path: Path,
) -> None:
    _install_responses(
        monkeypatch,
        [_payload(rows=[_row()]), _payload(rows=[])],
    )
    base_params = _provider_params()
    param_sets = [
        {**base_params, "season": "1946-47"},
        {**base_params, "season": "1947-48"},
    ]
    authority = _multi_execution_authority(param_sets)
    runner, journal = _runner(capture_store, sealed_admission=False)
    data_dir = tmp_path / "data"
    settings = NbaDbSettings(
        data_dir=data_dir,
        sqlite_path=data_dir / "nba.sqlite",
        duckdb_path=data_dir / "nba.duckdb",
    )
    orchestrator = Orchestrator(settings=settings)
    db = DBManager(settings.sqlite_path, settings.duckdb_path)
    db.init()
    inventory_path = data_dir / "request-closure-observation-inventory.json"
    entry = StagingEntry(_ENDPOINT_NAME, _STAGING_KEY, "season")
    try:
        outcome = await orchestrator._extract_all_patterns(
            runner,
            plan=[
                ExtractionPlanItem(
                    label="request closure fixture",
                    pattern="season",
                    entries=[entry],
                    params=param_sets,
                    priority=1,
                )
            ],
            seasons=[],
            game_ids=[],
            player_ids=[],
            team_ids=[],
            game_dates=[],
            game_log_df=pl.DataFrame(),
            include_static=False,
            run_mode="init",
            journal=journal,
            persist_results=lambda frames, **metadata: orchestrator._persist_staging_to_duckdb(
                db,
                frames,
                **metadata,
            ),
            retain_in_memory=False,
            request_closure_authority=authority,
            request_closure_inventory_path=inventory_path,
        )
    finally:
        runner.shutdown()
        db.close()

    assert outcome.pattern_failures == 0
    inventory = orchestrator.request_closure_inventory
    assert inventory is not None
    assert inventory.green
    assert inventory.runtime_receipt is not None
    assert len(inventory.observations) == 2
    assert {item.state for item in inventory.observations} == {
        "success_empty",
        "success_nonempty",
    }
    assert inventory_path.read_bytes() == inventory.canonical_bytes


@pytest.mark.asyncio
async def test_orchestrator_persists_typed_incomplete_lossless_join(
    monkeypatch: pytest.MonkeyPatch,
    capture_store: BronzeCaptureStore,
    tmp_path: Path,
) -> None:
    _install_responses(monkeypatch, [_payload(rows=[_row()], additive=True)])
    params = _provider_params()
    authority = _execution_authority(params, include_fallback=True)
    runner, journal = _runner(capture_store, sealed_admission=False)
    data_dir = tmp_path / "data"
    settings = NbaDbSettings(
        data_dir=data_dir,
        sqlite_path=data_dir / "nba.sqlite",
        duckdb_path=data_dir / "nba.duckdb",
    )
    orchestrator = Orchestrator(settings=settings)
    db = DBManager(settings.sqlite_path, settings.duckdb_path)
    db.init()
    inventory_path = data_dir / "request-closure-observation-inventory.json"
    entry = StagingEntry(_ENDPOINT_NAME, _STAGING_KEY, "season")
    try:
        with pytest.raises(ParserInputCaptureIntegrityError, match="incomplete after committed"):
            await orchestrator._extract_all_patterns(
                runner,
                plan=[
                    ExtractionPlanItem(
                        label="request closure drift fixture",
                        pattern="season",
                        entries=[entry],
                        params=[params],
                        priority=1,
                    )
                ],
                seasons=[],
                game_ids=[],
                player_ids=[],
                team_ids=[],
                game_dates=[],
                game_log_df=pl.DataFrame(),
                include_static=False,
                run_mode="init",
                journal=journal,
                persist_results=lambda frames, **metadata: orchestrator._persist_staging_to_duckdb(
                    db, frames, **metadata
                ),
                retain_in_memory=False,
                request_closure_authority=authority,
                request_closure_inventory_path=inventory_path,
            )
    finally:
        runner.shutdown()
        db.close()

    inventory = orchestrator.request_closure_inventory
    assert inventory is not None
    assert not inventory.green
    assert inventory.runtime_receipt is None
    assert len(inventory.incomplete) == 1
    assert inventory.incomplete[0].reason_code == ("lossless_stats_many_result_to_one_unproven")
    assert inventory_path.read_bytes() == inventory.canonical_bytes


@pytest.mark.asyncio
async def test_persistence_failure_publishes_no_pending_observation(
    monkeypatch: pytest.MonkeyPatch,
    capture_store: BronzeCaptureStore,
) -> None:
    _install_responses(monkeypatch, [_payload(rows=[_row()])])
    params = _provider_params()
    runner, journal = _runner(capture_store)

    def fail_persistence(*_args: object, **_kwargs: object) -> None:
        raise RuntimeError("commit failed")

    with pytest.raises(RuntimeError, match="commit failed"):
        await runner.run_pattern_result(
            "season",
            [params],
            [StagingEntry(_ENDPOINT_NAME, _STAGING_KEY, "season")],
            persist_chunk_results=fail_persistence,
            required_route_ids=(_BASE_ROUTE,),
            request_closure_authority=_execution_authority(params),
        )

    assert runner.request_closure_pending_snapshot() == ()
    journal.record_success.assert_not_called()


@pytest.mark.asyncio
async def test_failed_call_exposes_no_success_observation(
    monkeypatch: pytest.MonkeyPatch,
    capture_store: BronzeCaptureStore,
) -> None:
    _install_responses(monkeypatch, [requests.Timeout("provider unavailable")])
    params = _provider_params()
    runner, _journal_mock = _runner(capture_store)

    result = await runner.run_pattern_result(
        "season",
        [params],
        [StagingEntry(_ENDPOINT_NAME, _STAGING_KEY, "season")],
        persist_chunk_results=lambda *_args, **_kwargs: None,
        required_route_ids=(_BASE_ROUTE,),
        request_closure_authority=_execution_authority(params),
    )

    assert result.failure_count == 1
    assert result.pending_request_observations == ()
    assert runner.request_closure_pending_snapshot() == ()


@pytest.mark.asyncio
async def test_foreign_routes_and_parameters_fail_before_provider_access(
    monkeypatch: pytest.MonkeyPatch,
    capture_store: BronzeCaptureStore,
) -> None:
    events = _install_responses(monkeypatch, [_payload(rows=[_row()])])
    params = _provider_params()
    authority = _execution_authority(params)
    runner, _journal_mock = _runner(capture_store)
    changed = {**params, "season": "1946-47"}

    with pytest.raises(ParserInputCaptureIntegrityError, match="parameters differ"):
        await runner.run_pattern_result(
            "season",
            [changed],
            [StagingEntry(_ENDPOINT_NAME, _STAGING_KEY, "season")],
            required_route_ids=(_BASE_ROUTE,),
            request_closure_authority=authority,
        )
    assert events == []

    with pytest.raises(ParserInputCaptureIntegrityError, match="sealed-plan routes"):
        await runner.run_pattern_result(
            "season",
            [params],
            [StagingEntry(_ENDPOINT_NAME, _STAGING_KEY, "season")],
            required_route_ids=(f"{_ENDPOINT_NAME}:foreign:0",),
            request_closure_authority=authority,
        )
    assert events == []


def test_foreign_scope_authority_is_rejected() -> None:
    params = _provider_params()
    authority = _execution_authority(params)
    foreign_scope = replace(authority.scope, request_surface_sha256="f" * 64)

    with pytest.raises(ParserInputCaptureIntegrityError, match="foreign pin"):
        RequestClosureExecutionAuthority(authority.route_manifest, foreign_scope)


def test_execution_authority_rejects_missing_competition_bindings() -> None:
    authority = _execution_authority(_provider_params())

    with pytest.raises(
        ParserInputCaptureIntegrityError,
        match="competition authorities do not bijectively cover provider units",
    ):
        RequestClosureExecutionAuthority(
            route_manifest=authority.route_manifest,
            scope=authority.scope,
            staging_route_aliases=authority.staging_route_aliases,
            logical_calls=authority.logical_calls,
        )
