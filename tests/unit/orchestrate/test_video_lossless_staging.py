from __future__ import annotations

import json
from dataclasses import replace
from datetime import date
from types import SimpleNamespace
from typing import TYPE_CHECKING
from unittest.mock import MagicMock

import polars as pl
import pytest
from nba_api.stats.endpoints import VideoDetails, VideoDetailsAsset, VideoEvents
from nba_api.stats.endpoints.videoeventsasset import VideoEventsAsset

from nbadb.contracts.field_fate_structure import compile_field_fate_structure
from nbadb.contracts.staging_route_contract import admit_conditional_lossless_route
from nbadb.core.config import NbaDbSettings
from nbadb.core.db import DBManager
from nbadb.core.errors import ParserInputCaptureIntegrityError, ResponseContractError
from nbadb.core.nba_api_competition_identity import (
    CompetitionQualifiedRequest,
    NbaApiCompetitionIdentityError,
    bind_explicit_competition_request,
    build_competition_terminal_request_binding,
    compile_competition_identity_requirements,
)
from nbadb.core.nba_api_provenance import expected_nba_api_provider_authority
from nbadb.core.nba_api_request_surface import (
    CanonicalProviderRequest,
    RequestScopeDimension,
    RequestScopeManifest,
    materialize_provider_request,
    pinned_request_surface_authority,
)
from nbadb.core.nba_api_runtime_contract import (
    endpoint_contract_sha256,
    pinned_endpoint_contract,
)
from nbadb.extract.bronze import (
    BronzeCaptureStore,
    BronzeLimits,
    LogicalCallReceiptBinding,
    ParserInputContext,
    canonical_parameters_sha256,
)
from nbadb.extract.nba_api_adapter import (
    LOSSLESS_FALLBACK_SCHEMA,
    LOSSLESS_FALLBACK_STAGING_KEY,
    NbaApiCaptureContract,
    NbaDbStatsHTTP,
)
from nbadb.extract.registry import EndpointRegistry
from nbadb.extract.stats.misc import (
    VideoDetailsAssetExtractor,
    VideoDetailsExtractor,
    VideoEventsAssetExtractor,
    VideoEventsExtractor,
)
from nbadb.extract.stats_lossless import (
    build_unknown_stats_lossless_fallback,
    validate_unknown_stats_lossless_frame,
)
from nbadb.orchestrate.body_blob_store import BodyBlobStore
from nbadb.orchestrate.declared_bodyless_packet_store import (
    DeclaredBodylessPacketStore,
)
from nbadb.orchestrate.extractor_runner import (
    ExtractorRunner,
    RequestClosureCompetitionAuthority,
    RequestClosureExecutionAuthority,
    RequestClosureLogicalCallBinding,
    RequestClosureStagingRouteAlias,
    _ExtractionTaskResult,
)
from nbadb.orchestrate.orchestrator import Orchestrator
from nbadb.orchestrate.planning import ExtractionPlanItem
from nbadb.orchestrate.raw_request_context import RawRequestExecutionIdentityV1
from nbadb.orchestrate.raw_request_store import compile_raw_request_manifest_authority
from nbadb.orchestrate.request_closure_production import (
    ProductionRequestClosureBuild,
    _probe_provider_call,
)
from nbadb.orchestrate.request_closure_runtime import (
    RouteRequestSpecInput,
    build_authoritative_route_manifest,
)
from nbadb.orchestrate.staging_map import StagingEntry
from nbadb.orchestrate.w2_source_call_preparation import (
    W2SourceCallPreparationRuntime,
)
from tests.unit.orchestrate._raw_request_test_support import raw_request_assurance_authority
from tests.unit.orchestrate.test_extractor_runner_lossless import _journal, _settings

if TYPE_CHECKING:
    from collections.abc import Callable
    from pathlib import Path


class _FakeResponse:
    def __init__(self, parser_input: str) -> None:
        self._parser_input = parser_input
        self._status_code = 200

    def get_response(self) -> str:
        return self._parser_input

    def get_dict(self) -> object:
        return json.loads(self._parser_input)


def _install_payload(monkeypatch: pytest.MonkeyPatch, payload: object) -> None:
    parser_input = json.dumps(
        payload,
        ensure_ascii=False,
        separators=(",", ":"),
        allow_nan=False,
    )
    monkeypatch.setattr(
        NbaDbStatsHTTP,
        "send_api_request",
        lambda _self, **_kwargs: _FakeResponse(parser_input),
    )


def _capture_contract(
    tmp_path: Path,
    attempt_id: str,
    endpoint_cls: type = VideoDetails,
) -> NbaApiCaptureContract:
    contract = pinned_endpoint_contract(endpoint_cls)
    return NbaApiCaptureContract(
        sink=BronzeCaptureStore(
            tmp_path / "private" / attempt_id,
            public_roots=(tmp_path / "public",),
            limits=BronzeLimits(
                max_response_bytes=1_000_000,
                max_generation_stored_bytes=4_000_000,
                minimum_free_bytes=1,
            ),
        ),
        context=ParserInputContext(
            attempt_id=attempt_id,
            workflow_run_id=101,
            workflow_run_attempt=1,
            chain_id="chain",
            lane_id="lane",
            semantic_source_sha="1" * 40,
        ),
        provider_authority_sha256=expected_nba_api_provider_authority()["authority_sha256"],
        endpoint_contract_sha256=endpoint_contract_sha256(contract),
    )


async def _captured_observation(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    payload: object,
):
    _install_payload(monkeypatch, payload)
    extractor = VideoDetailsExtractor()
    extractor.set_capture_contract(_capture_contract(tmp_path, "direct-video"))
    await extractor.extract(
        player_id=2,
        team_id=1,
        season="2024-25",
        season_type="Regular Season",
        context_measure="PTS",
    )
    return extractor.unknown_response_snapshot()[0]


@pytest.mark.asyncio
async def test_unknown_video_projection_preserves_duplicate_names_and_zero_width_rows(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    observation = await _captured_observation(
        monkeypatch,
        tmp_path,
        {
            "resultSets": [
                {"name": "Observed", "headers": [], "rowSet": [[]]},
                {
                    "name": "Observed",
                    "headers": ["VALUE", "VALUE"],
                    "rowSet": [[1, None]],
                    "extra": {"nested": [True]},
                },
            ]
        },
    )

    fallback = build_unknown_stats_lossless_fallback(observation)

    assert fallback is not None
    assert fallback.result_route_index == 0
    assert fallback.frame.columns == list(LOSSLESS_FALLBACK_SCHEMA)
    result_rows = fallback.frame.filter(pl.col("record_kind") == "result_set")
    assert result_rows.select(
        "result_set_name", "result_set_occurrence", "provider_index"
    ).rows() == [("Observed", 0, 0), ("Observed", 1, 1)]
    zero_width = fallback.frame.filter(
        (pl.col("record_kind") == "row") & (pl.col("provider_index") == 0)
    )
    assert zero_width.select("row_ordinal", "value_kind", "canonical_json").rows() == [
        (0, "array", "[]")
    ]
    assert fallback.frame.filter(
        (pl.col("record_kind") == "cell") & (pl.col("provider_index") == 0)
    ).is_empty()
    assert fallback.frame.filter(
        (pl.col("record_kind") == "header") & (pl.col("provider_index") == 1)
    )["header_name"].to_list() == ["VALUE", "VALUE"]
    assert "value_0" not in fallback.frame.columns
    assert (
        fallback.frame.filter(
            (pl.col("record_kind") == "json_node") & (pl.col("object_key") == "nested")
        ).height
        == 1
    )
    validate_unknown_stats_lossless_frame(
        fallback.frame,
        expected_response_receipt_sha256=observation.response_receipt_sha256,
    )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "payload",
    [{}, {"resultSets": []}],
    ids=["missing-envelope", "present-empty-envelope"],
)
async def test_no_observed_video_drift_does_not_materialize_conditional_table(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    payload: object,
) -> None:
    observation = await _captured_observation(monkeypatch, tmp_path, payload)

    assert build_unknown_stats_lossless_fallback(observation) is None
    assert (
        build_unknown_stats_lossless_fallback(replace(observation, response_receipt_sha256=None))
        is None
    )


@pytest.mark.asyncio
async def test_unknown_video_projection_rejects_request_body_and_node_rebinding(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    observation = await _captured_observation(
        monkeypatch,
        tmp_path,
        {"asset": {"url": "https://example.invalid/private", "metadata": {}}},
    )

    with pytest.raises(ResponseContractError, match="request parameters was rebound"):
        build_unknown_stats_lossless_fallback(
            observation,
            expected_parameters_sha256="0" * 64,
        )
    with pytest.raises(ResponseContractError, match="parser input was rebound"):
        build_unknown_stats_lossless_fallback(
            observation,
            expected_parser_input_sha256="1" * 64,
        )
    with pytest.raises(ResponseContractError, match="response receipt was rebound"):
        build_unknown_stats_lossless_fallback(
            observation,
            expected_response_receipt_sha256="2" * 64,
        )
    fallback = build_unknown_stats_lossless_fallback(observation)
    assert fallback is not None
    assert "url" not in fallback.frame.columns
    assert "asset" not in fallback.frame.columns
    assert (
        fallback.frame.filter(
            (pl.col("record_kind") == "json_node") & (pl.col("object_key") == "url")
        ).height
        == 1
    )

    rows = fallback.frame.to_dicts()
    node_index = next(
        index
        for index, row in enumerate(rows)
        if row["record_kind"] == "json_node" and row["node_ordinal"] == 1
    )
    rows[node_index]["json_path"] = '$["rebound"]'
    rebound = pl.DataFrame(rows, schema=LOSSLESS_FALLBACK_SCHEMA, orient="row")
    with pytest.raises(ResponseContractError, match="JSON path was rebound"):
        validate_unknown_stats_lossless_frame(rebound)

    rows = fallback.frame.to_dicts()
    leaf_index = next(
        index
        for index, row in enumerate(rows)
        if row["record_kind"] == "json_node" and row["object_key"] == "url"
    )
    rows[leaf_index]["value_kind"] = "integer"
    malformed_value = pl.DataFrame(rows, schema=LOSSLESS_FALLBACK_SCHEMA, orient="row")
    with pytest.raises(ResponseContractError, match="node value kind drifted"):
        validate_unknown_stats_lossless_frame(malformed_value)


def _capture_factory(tmp_path: Path) -> Callable[[str, dict[str, object]], NbaApiCaptureContract]:
    counter = 0
    provider_by_endpoint = {
        "video_details": VideoDetails,
        "video_details_asset": VideoDetailsAsset,
        "video_events": VideoEvents,
        "video_events_asset": VideoEventsAsset,
    }

    def factory(endpoint_name: str, _params: dict[str, object]) -> NbaApiCaptureContract:
        nonlocal counter
        counter += 1
        return _capture_contract(
            tmp_path,
            f"runner-video-{counter}",
            provider_by_endpoint[endpoint_name],
        )

    return factory


def _runner(
    tmp_path: Path,
    admissions: list[tuple[str, ...]],
    extractor_cls: type = VideoDetailsExtractor,
) -> ExtractorRunner:
    registry = MagicMock()
    registry.get.return_value = extractor_cls

    def admit_conditional(
        endpoint_name: str,
        _params: dict[str, object],
        static_route_ids: tuple[str, ...],
        conditional_route_ids: tuple[str, ...],
    ) -> None:
        admission = admit_conditional_lossless_route(
            endpoint_name=endpoint_name,
            static_route_ids=static_route_ids,
            conditional_route_ids=conditional_route_ids,
            provider_authority_sha256=expected_nba_api_provider_authority()["authority_sha256"],
        )
        admissions.append((admission.route_id, *admission.static_route_ids))

    return ExtractorRunner(
        registry,
        _settings(),
        _journal(),
        capture_contract_factory=_capture_factory(tmp_path),
        conditional_route_admission=admit_conditional,
    )


_ENTRY = StagingEntry(
    "video_details",
    "stg_video_details",
    "player_team_season",
)
_PARAMS = {
    "player_id": 2,
    "team_id": 1,
    "season": "2024-25",
    "season_type": "Regular Season",
    "context_measure": "PTS",
}
_EXPLICIT_VIDEO_COMPETITIONS = ("00", "01", "10", "15", "20")


def _qualified_video_competition_requests(
    endpoint_name: str,
    endpoint_id: str,
    provider_request: CanonicalProviderRequest,
) -> tuple[tuple[str, CompetitionQualifiedRequest], ...]:
    matching_requirements = tuple(
        requirement
        for requirement in compile_competition_identity_requirements()
        if requirement.source_family == "stats"
        and requirement.provider_endpoint_id == endpoint_id
        and requirement.repo_endpoint_name == endpoint_name
        and requirement.role_binding.binding_strategy == "explicit_applicability_cell"
    )
    assert tuple(requirement.league_id for requirement in matching_requirements) == (
        _EXPLICIT_VIDEO_COMPETITIONS
    )
    qualified_requests: list[tuple[str, CompetitionQualifiedRequest]] = []
    for requirement in matching_requirements:
        try:
            qualified_requests.append(
                (
                    requirement.league_id,
                    bind_explicit_competition_request(requirement, provider_request),
                )
            )
        except NbaApiCompetitionIdentityError:
            continue
    return tuple(qualified_requests)


@pytest.mark.parametrize(
    ("endpoint_name", "endpoint_id", "extractor_cls"),
    (
        ("video_details", "VideoDetails", VideoDetailsExtractor),
        ("video_details_asset", "VideoDetailsAsset", VideoDetailsAssetExtractor),
    ),
    ids=("details", "details-asset"),
)
@pytest.mark.parametrize("league_id", _EXPLICIT_VIDEO_COMPETITIONS)
def test_every_admitted_video_competition_materializes_exact_constructor_and_wire_scope(
    endpoint_name: str,
    endpoint_id: str,
    extractor_cls: type[VideoDetailsExtractor | VideoDetailsAssetExtractor],
    league_id: str,
) -> None:
    registry = EndpointRegistry()
    registry.register(extractor_cls)
    params = {**_PARAMS, "league_id": league_id}
    endpoint_cls, constructor_params, runtime_params = _probe_provider_call(
        registry,
        endpoint_name=endpoint_name,
        params=params,
        use_multi=False,
    )
    assert endpoint_cls.__name__ == endpoint_id
    assert constructor_params["league_id_nullable"] == league_id
    assert runtime_params["LeagueID"] == league_id

    surface = pinned_request_surface_authority()
    provider_request = materialize_provider_request(
        surface.endpoint("stats", endpoint_id),
        constructor_params,
        request_surface_sha256=surface.surface_sha256,
        runtime_contract_payload_sha256=surface.runtime_contract_payload_sha256,
    )
    ((qualified_league_id, _qualified_request),) = _qualified_video_competition_requests(
        endpoint_name,
        endpoint_id,
        provider_request,
    )
    assert qualified_league_id == league_id


@pytest.mark.parametrize(
    ("endpoint_name", "endpoint_id", "extractor_cls"),
    (
        ("video_details", "VideoDetails", VideoDetailsExtractor),
        ("video_details_asset", "VideoDetailsAsset", VideoDetailsAssetExtractor),
    ),
    ids=("details", "details-asset"),
)
def test_omitted_video_competition_uses_only_exact_provider_default(
    endpoint_name: str,
    endpoint_id: str,
    extractor_cls: type[VideoDetailsExtractor | VideoDetailsAssetExtractor],
) -> None:
    registry = EndpointRegistry()
    registry.register(extractor_cls)
    endpoint_cls, constructor_params, runtime_params = _probe_provider_call(
        registry,
        endpoint_name=endpoint_name,
        params=dict(_PARAMS),
        use_multi=False,
    )
    assert endpoint_cls.__name__ == endpoint_id
    assert "league_id_nullable" not in constructor_params
    assert runtime_params["LeagueID"] == "00"

    surface = pinned_request_surface_authority()
    provider_request = materialize_provider_request(
        surface.endpoint("stats", endpoint_id),
        constructor_params,
        request_surface_sha256=surface.surface_sha256,
        runtime_contract_payload_sha256=surface.runtime_contract_payload_sha256,
    )
    ((qualified_league_id, _qualified_request),) = _qualified_video_competition_requests(
        endpoint_name,
        endpoint_id,
        provider_request,
    )
    assert qualified_league_id == "00"


def _video_request_closure_build() -> tuple[
    list[ExtractionPlanItem],
    ProductionRequestClosureBuild,
]:
    registry = EndpointRegistry()
    registry.register(VideoDetailsExtractor)
    plan = [
        ExtractionPlanItem(
            label="video unknown-response raw persistence",
            pattern=_ENTRY.param_pattern,
            entries=[_ENTRY],
            params=[dict(_PARAMS)],
            priority=0,
        )
    ]
    endpoint_cls, constructor_params, _runtime_params = _probe_provider_call(
        registry,
        endpoint_name=_ENTRY.endpoint_name,
        params=dict(_PARAMS),
        use_multi=False,
    )
    assert endpoint_cls is VideoDetails
    surface = pinned_request_surface_authority()
    provider_request = materialize_provider_request(
        surface.endpoint("stats", "VideoDetails"),
        constructor_params,
        request_surface_sha256=surface.surface_sha256,
        runtime_contract_payload_sha256=surface.runtime_contract_payload_sha256,
    )
    qualified_requests = _qualified_video_competition_requests(
        _ENTRY.endpoint_name,
        "VideoDetails",
        provider_request,
    )
    assert len(qualified_requests) == 1

    physical_route_id = f"{_ENTRY.endpoint_name}:{_ENTRY.staging_key}:0"
    manifest_route_id = f"{physical_route_id}:request:{provider_request.provider_request_sha256}"
    manifest = build_authoritative_route_manifest(
        (
            RouteRequestSpecInput(
                route_id=manifest_route_id,
                source_family="stats",
                endpoint_id="VideoDetails",
                parameters=tuple(sorted(provider_request.materialized_parameters)),
            ),
        )
    )
    dimension = RequestScopeDimension(
        dependency_id="season_scope",
        source_kind="video_lossless_test_authority",
        source_authority_sha256=provider_request.provider_request_sha256,
        values=(_PARAMS["season"],),
        endpoint_id="VideoDetails",
        parameter_name="season",
    )
    scope = RequestScopeManifest(
        request_surface_sha256=surface.surface_sha256,
        scope_id="video_lossless_test_scope",
        seed_route_ids=(manifest_route_id,),
        dimensions=(dimension,),
    )
    qualified_league_id, qualified_request = qualified_requests[0]
    assert qualified_league_id == "00"
    authority = RequestClosureExecutionAuthority(
        route_manifest=manifest,
        scope=scope,
        staging_route_aliases=(
            RequestClosureStagingRouteAlias(manifest_route_id, physical_route_id),
        ),
        logical_calls=(
            RequestClosureLogicalCallBinding(
                endpoint_name=_ENTRY.endpoint_name,
                logical_parameters_sha256=canonical_parameters_sha256(_PARAMS),
                provider_request_sha256=provider_request.provider_request_sha256,
                route_ids=(manifest_route_id,),
                provider_parameters_sha256=canonical_parameters_sha256(
                    dict(provider_request.materialized_parameters)
                ),
            ),
        ),
        competition_authorities=(
            RequestClosureCompetitionAuthority(
                qualified_request=qualified_request,
                request_binding=build_competition_terminal_request_binding(
                    qualified_request,
                    route_manifest_sha256=manifest.manifest_sha256,
                    scope_sha256=scope.scope_sha256,
                    route_ids=(manifest_route_id,),
                ),
            ),
        ),
    )
    build = ProductionRequestClosureBuild(authority, (), date(2026, 8, 27), ())
    return plan, build


@pytest.mark.asyncio
async def test_runner_materializes_only_observed_video_drift_under_conditional_route(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    _install_payload(
        monkeypatch,
        {"playlist": [{"gameId": "0022400001", "eventId": 37}]},
    )
    admissions: list[tuple[str, ...]] = []

    result = await _runner(tmp_path, admissions)._extract_single_result(_ENTRY, _PARAMS)

    assert isinstance(result, _ExtractionTaskResult)
    conditional_route = f"video_details:{LOSSLESS_FALLBACK_STAGING_KEY}:0"
    assert set(result.frames) == {"stg_video_details", LOSSLESS_FALLBACK_STAGING_KEY}
    assert result.frames["stg_video_details"].is_empty()
    assert (
        result.frames[LOSSLESS_FALLBACK_STAGING_KEY]
        .filter(pl.col("record_kind") == "json_node")
        .height
        > 0
    )
    assert admissions == [(conditional_route, "video_details:stg_video_details:0")]
    assert result.pending_success is not None
    assert result.pending_success.receipt_binding is not None
    assert result.pending_success.receipt_binding.result_route_ids == tuple(
        sorted(("video_details:stg_video_details:0", conditional_route))
    )


@pytest.mark.parametrize(
    ("endpoint_name", "staging_key", "extractor_cls"),
    [
        ("video_events", "stg_video_events", VideoEventsExtractor),
        (
            "video_events_asset",
            "stg_video_events_asset",
            VideoEventsAssetExtractor,
        ),
    ],
    ids=("events", "events-asset"),
)
@pytest.mark.asyncio
async def test_runner_duplicates_receipt_verified_video_event_drift_to_exact_canonical_route(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    endpoint_name: str,
    staging_key: str,
    extractor_cls: type,
) -> None:
    _install_payload(
        monkeypatch,
        {"playlist": [{"gameId": "0022400001", "eventId": 37, "url": None}]},
    )
    admissions: list[tuple[str, ...]] = []
    entry = StagingEntry(endpoint_name, staging_key, "game")
    params = {"game_id": "0022400001", "game_event_id": 37}

    result = await _runner(
        tmp_path,
        admissions,
        extractor_cls,
    )._extract_single_result(entry, params)

    assert isinstance(result, _ExtractionTaskResult)
    static_route = f"{endpoint_name}:{staging_key}:0"
    conditional_route = f"{endpoint_name}:{LOSSLESS_FALLBACK_STAGING_KEY}:0"
    assert set(result.frames) == {staging_key, LOSSLESS_FALLBACK_STAGING_KEY}
    assert result.frames[staging_key].equals(result.frames[LOSSLESS_FALLBACK_STAGING_KEY])
    assert result.frames[staging_key].filter(pl.col("record_kind") == "json_node").height > 0
    assert (
        result.frames[staging_key].get_column("response_receipt_sha256").drop_nulls().n_unique()
        == 1
    )
    assert admissions == [(conditional_route, static_route)]
    assert result.pending_success is not None
    assert result.pending_success.receipt_binding is not None
    assert result.pending_success.receipt_binding.result_route_ids == tuple(
        sorted((static_route, conditional_route))
    )
    assert result.result_route_ids_by_staging_key == tuple(
        sorted(
            (
                (staging_key, static_route),
                (LOSSLESS_FALLBACK_STAGING_KEY, conditional_route),
            )
        )
    )


def test_video_event_canonical_projection_rejects_unreceipted_and_rebound_fallbacks() -> None:
    endpoint_name = "video_events"
    staging_key = "stg_video_events"
    static_route = f"{endpoint_name}:{staging_key}:0"
    conditional_route = f"{endpoint_name}:{LOSSLESS_FALLBACK_STAGING_KEY}:0"
    frame = pl.DataFrame()
    fallback = MagicMock()
    fallback.response_receipt_sha256 = None

    with pytest.raises(ParserInputCaptureIntegrityError, match="exact receipt and route"):
        ExtractorRunner._canonical_video_lossless_projection(
            endpoint_name,
            static_route_ids=(static_route,),
            fallbacks=(fallback,),
            fallback_projection=(frame, conditional_route),
            pending_success=None,
        )

    fallback.response_receipt_sha256 = "8" * 64
    rebound = LogicalCallReceiptBinding(
        logical_call_receipt_sha256="7" * 64,
        endpoint_name=endpoint_name,
        logical_parameters_sha256=canonical_parameters_sha256({}),
        provider_authority_sha256=expected_nba_api_provider_authority()["authority_sha256"],
        result_route_ids=(static_route,),
    )
    with pytest.raises(ParserInputCaptureIntegrityError, match="exact receipt and route"):
        ExtractorRunner._canonical_video_lossless_projection(
            endpoint_name,
            static_route_ids=(static_route,),
            fallbacks=(fallback,),
            fallback_projection=(frame, conditional_route),
            pending_success=SimpleNamespace(receipt_binding=rebound),
        )


@pytest.mark.asyncio
async def test_runner_keeps_no_drift_video_response_conditional_table_absent(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    _install_payload(monkeypatch, {"resultSets": []})
    admissions: list[tuple[str, ...]] = []

    result = await _runner(tmp_path, admissions)._extract_single_result(_ENTRY, _PARAMS)

    assert isinstance(result, dict)
    assert set(result) == {"stg_video_details"}
    assert admissions == []
    assert result["stg_video_details"].is_empty()


@pytest.mark.asyncio
async def test_unknown_video_persists_raw_authority_and_conditional_nodes_without_result_identity(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    _install_payload(
        monkeypatch,
        {"asset": {"url": "https://example.invalid/opaque", "metadata": {}}},
    )
    plan, closure_build = _video_request_closure_build()
    assert closure_build.authority is not None
    execution = RawRequestExecutionIdentityV1(
        source_sha="1" * 40,
        run_id=101,
        run_attempt=1,
        chain_id="chain",
        lane_id="lane",
    )
    assurance = raw_request_assurance_authority(source_sha=execution.source_sha)
    manifest = compile_raw_request_manifest_authority(
        execution,
        closure_build.authority,
        assurance_authority=assurance,
    )
    data_dir = tmp_path / "data"
    settings = NbaDbSettings(
        data_dir=data_dir,
        sqlite_path=data_dir / "nba.sqlite",
        duckdb_path=data_dir / "nba.duckdb",
    )
    body_root = tmp_path / "w2-body"
    bodyless_root = tmp_path / "w2-bodyless"
    for root in (body_root, bodyless_root):
        root.mkdir(mode=0o700, exist_ok=True)
        root.chmod(0o700)
    w2_identity = {
        "source_sha": execution.source_sha,
        "run_id": execution.run_id,
        "run_attempt": execution.run_attempt,
        "chain_id": execution.chain_id,
        "lane_id": execution.lane_id,
    }
    orchestrator = Orchestrator(
        settings=settings,
        raw_request_execution_identity=execution,
        raw_request_assurance_authority=assurance,
        raw_request_manifest_authority=manifest,
        w2_preparation_runtime=W2SourceCallPreparationRuntime(
            body_blob_store=BodyBlobStore(body_root, **w2_identity),
            declared_bodyless_packet_store=DeclaredBodylessPacketStore(
                bodyless_root, **w2_identity
            ),
            field_fate=compile_field_fate_structure(),
        ),
    )
    admissions: list[tuple[str, ...]] = []
    runner = _runner(tmp_path, admissions)
    db = DBManager(settings.sqlite_path, settings.duckdb_path)
    db.init()
    inventory_path = data_dir / "request-closure-observation-inventory.json"
    try:
        with pytest.raises(
            ParserInputCaptureIntegrityError,
            match="request closure remains incomplete after committed staging",
        ):
            await orchestrator._extract_all_patterns(
                runner,
                plan=plan,
                seasons=[],
                game_ids=[],
                player_ids=[],
                team_ids=[],
                current_team_ids=[],
                game_dates=[],
                player_team_season_params=[],
                game_log_df=pl.DataFrame(),
                include_static=False,
                run_mode="init",
                journal=runner._journal,
                persist_results=lambda frames, **metadata: orchestrator._persist_staging_to_duckdb(
                    db,
                    frames,
                    **metadata,
                ),
                retain_in_memory=False,
                request_closure_build=closure_build,
                request_closure_inventory_path=inventory_path,
            )
        # Chunk durability must survive the fail-closed closure result.  The
        # production pipeline materializes staging only after extraction has
        # cleared its assurance gates, so exercise that separate projection
        # explicitly without weakening the incomplete-request outcome.
        assert (
            orchestrator._staging_store_for(db).materialize((LOSSLESS_FALLBACK_STAGING_KEY,)) == 1
        )
        persisted = db.duckdb.execute(
            f"""
            SELECT count(*),
                   count(*) FILTER (WHERE record_kind = 'json_node'),
                   count(*) FILTER (WHERE result_set_name IS NOT NULL),
                   count(*) FILTER (WHERE canonical_index IS NOT NULL),
                   count(*) FILTER (WHERE object_key = 'url')
            FROM {LOSSLESS_FALLBACK_STAGING_KEY}
            """
        ).fetchone()
        columns = tuple(
            row[0]
            for row in db.duckdb.execute(f"DESCRIBE {LOSSLESS_FALLBACK_STAGING_KEY}").fetchall()
        )
    finally:
        runner.shutdown()
        db.close()

    assert persisted is not None
    assert persisted[0] == persisted[1] + 1
    assert persisted[1] > 0
    assert persisted[2:] == (0, 0, 1)
    assert "url" not in columns
    assert "asset" not in columns
    (pending,) = runner.request_closure_pending_snapshot()
    assert pending.result_contract == "lossless_drift"
    assert pending.bronze_result_sets == ()
    assert pending.response_receipt_sha256
    assert pending.response_body_sha256
    assert pending.endpoint_contract_sha256
    raw_snapshot = runner.raw_request_capture_snapshot()
    assert raw_snapshot is not None
    assert len(raw_snapshot.pending_successes) == 1
    assert len(orchestrator.raw_request_persistence_receipts) == 1
    inventory = orchestrator.request_closure_inventory
    assert inventory is not None
    assert len(inventory.incomplete) == 1
    assert inventory.incomplete[0].reason_code == ("lossless_stats_many_result_to_one_unproven")
