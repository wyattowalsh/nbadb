from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace
from typing import TYPE_CHECKING, cast
from unittest.mock import MagicMock

import duckdb
import polars as pl
import pytest
from nba_api.live.nba.endpoints import BoxScore, Odds, PlayByPlay, ScoreBoard

from nbadb.contracts.staging_route_contract import (
    ConditionalLiveStagingRouteAdmission,
    admit_conditional_live_lossless_route,
    admit_known_conditional_staging_route,
    staging_route_contract_bundle,
)
from nbadb.core.config import NbaDbSettings
from nbadb.core.errors import ParserInputCaptureIntegrityError
from nbadb.core.nba_api_provenance import expected_nba_api_provider_authority
from nbadb.core.nba_api_runtime_contract import (
    owned_contract_sha256,
    pinned_live_endpoint_contract,
)
from nbadb.extract.bronze import (
    BronzeCaptureStore,
    BronzeLimits,
    ParserInputContext,
    canonical_parameters_sha256,
)
from nbadb.extract.live.endpoints import LivePlayByPlayExtractor
from nbadb.extract.live_lossless import (
    LIVE_LOSSLESS_SCHEMA,
    LIVE_LOSSLESS_STAGING_KEY,
    validate_live_lossless_frame,
)
from nbadb.extract.nba_api_adapter import NbaApiCaptureContract, NbaDbLiveHTTP
from nbadb.load.sqlite import SQLiteLoader
from nbadb.orchestrate.extractor_runner import ExtractorRunner, _ExtractionTaskResult
from nbadb.orchestrate.live_snapshot import LiveSnapshotWarehouse
from nbadb.orchestrate.staging_batches import (
    CANONICAL_FRAME_FORMAT,
    FRAME_CONTENT_HASH_CONTRACT,
    FRAME_SCHEMA_HASH_CONTRACT,
    SourceScopeReplacementAttestation,
    StagingBatchStore,
    StagingChunkMetadata,
    StagingFrameBatch,
)
from nbadb.orchestrate.staging_map import (
    LOSSLESS_FALLBACK_STAGING_KEY,
    StagingEntry,
)
from nbadb.orchestrate.successor_execution_restore import (
    logical_bindings_from_replacement_attestations,
    successor_receipts_from_replacement_attestations,
)
from nbadb.orchestrate.successor_planning_runtime import (
    ExactPlanningRuntimeError,
    ExtractorPlanningExactCallRuntime,
)
from nbadb.schemas.registry import get_input_schema
from tests.unit.extract.test_live_lossless_nodes import (
    _complete_endpoint_payload,
    _live_response,
)
from tests.unit.orchestrate.test_live_snapshot import _ExactLiveAuthorityHarness
from tests.unit.orchestrate.test_orchestrator import (
    _successor_candidate,
    _successor_plan_for_scopes,
    _successor_replacement_attestations,
)

if TYPE_CHECKING:
    from collections.abc import Callable
    from pathlib import Path

    from nbadb.orchestrate.successor_planning_runtime import PlanningExactCallRuntimeRequest


_STATIC_ROUTE = "live_play_by_play:stg_live_play_by_play:0"
_SNAPSHOT_AT = datetime(2026, 4, 17, 12, 0, tzinfo=UTC)
_GAME_ID = "0022400001"


def _settings() -> MagicMock:
    settings = MagicMock()
    settings.semaphore_tiers = {"live": 5, "default": 5}
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
    return settings


def _journal() -> MagicMock:
    journal = MagicMock()
    journal.was_extracted.return_value = False
    journal.was_extracted_batch.return_value = set()
    journal.get_failed.return_value = []
    return journal


def _recurring_settings(tmp_path: Path) -> NbaDbSettings:
    return NbaDbSettings(
        data_dir=tmp_path / "data",
        log_dir=tmp_path / "logs",
        formats=["duckdb"],
        sqlite_path=tmp_path / "data" / "live.sqlite",
        duckdb_path=tmp_path / "data" / "live.duckdb",
    )


def _capture_factory(
    tmp_path: Path,
    endpoint_cls: type,
) -> Callable[[str, dict[str, object]], NbaApiCaptureContract]:
    contract = pinned_live_endpoint_contract(endpoint_cls)
    counter = 0

    def factory(_endpoint_name: str, _params: dict[str, object]) -> NbaApiCaptureContract:
        nonlocal counter
        counter += 1
        store = BronzeCaptureStore(
            tmp_path / "private" / "bronze",
            public_roots=(tmp_path / "public",),
            limits=BronzeLimits(
                max_response_bytes=2_000_000,
                max_generation_stored_bytes=8_000_000,
                minimum_free_bytes=1,
            ),
        )
        return NbaApiCaptureContract(
            sink=store,
            context=ParserInputContext(attempt_id=f"live-integration-{counter}"),
            provider_authority_sha256=expected_nba_api_provider_authority()["authority_sha256"],
            endpoint_contract_sha256=owned_contract_sha256(contract),
        )

    return factory


def _patch_live_response(
    monkeypatch: pytest.MonkeyPatch,
    endpoint_cls: type,
    events: list[str] | None = None,
) -> None:
    payload = _complete_endpoint_payload(pinned_live_endpoint_contract(endpoint_cls))

    def send_response(_self: object, **_kwargs: object):
        if events is not None:
            events.append("provider")
        return _live_response(payload)

    monkeypatch.setattr(NbaDbLiveHTTP, "send_api_request", send_response)


def _live_route(endpoint_name: str, endpoint_cls: type) -> str:
    return (
        f"{endpoint_name}:{LIVE_LOSSLESS_STAGING_KEY}:"
        f"{len(pinned_live_endpoint_contract(endpoint_cls).result_sets)}"
    )


@pytest.mark.parametrize(
    ("endpoint_name", "endpoint_cls"),
    [
        ("live_score_board", ScoreBoard),
        ("live_odds", Odds),
        ("live_play_by_play", PlayByPlay),
        ("live_box_score", BoxScore),
    ],
)
def test_live_conditional_authority_is_derived_from_each_pinned_contract(
    endpoint_name: str,
    endpoint_cls: type,
) -> None:
    bundle = staging_route_contract_bundle()
    static_routes = tuple(
        route.route_id for route in bundle.routes if route.endpoint_name == endpoint_name
    )

    admission = admit_conditional_live_lossless_route(
        endpoint_name=endpoint_name,
        static_route_ids=static_routes,
        conditional_route_ids=(_live_route(endpoint_name, endpoint_cls),),
        provider_authority_sha256=bundle.provider_authority_sha256,
    )

    assert admission.provider_endpoint_id == endpoint_cls.__name__
    assert admission.expected_result_set_count == len(
        pinned_live_endpoint_contract(endpoint_cls).result_sets
    )
    assert admission.storage_columns == tuple(LIVE_LOSSLESS_SCHEMA)


@pytest.mark.parametrize(
    "conditional_route",
    [
        f"live_play_by_play:{LIVE_LOSSLESS_STAGING_KEY}:3",
        f"live_play_by_play:{LOSSLESS_FALLBACK_STAGING_KEY}:4",
        "live_play_by_play:stg_unknown_lossless_nodes:4",
    ],
)
def test_live_authority_rejects_wrong_index_and_route_family(
    conditional_route: str,
) -> None:
    bundle = staging_route_contract_bundle()

    with pytest.raises(ValueError):
        admit_conditional_live_lossless_route(
            endpoint_name="live_play_by_play",
            static_route_ids=(_STATIC_ROUTE,),
            conditional_route_ids=(conditional_route,),
            provider_authority_sha256=bundle.provider_authority_sha256,
        )


@pytest.mark.asyncio
async def test_runner_binds_wide_and_live_nodes_to_one_logical_receipt(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    events: list[str] = []
    _patch_live_response(monkeypatch, PlayByPlay, events)
    registry = MagicMock()
    registry.get.return_value = LivePlayByPlayExtractor
    provider_authority = staging_route_contract_bundle().provider_authority_sha256

    def admit_conditional(
        endpoint_name: str,
        _params: dict[str, object],
        static_route_ids: tuple[str, ...],
        conditional_route_ids: tuple[str, ...],
    ) -> None:
        events.append("conditional")
        admission = admit_known_conditional_staging_route(
            endpoint_name=endpoint_name,
            static_route_ids=static_route_ids,
            conditional_route_ids=conditional_route_ids,
            provider_authority_sha256=provider_authority,
        )
        assert isinstance(admission, ConditionalLiveStagingRouteAdmission)

    runner = ExtractorRunner(
        registry,
        _settings(),
        _journal(),
        capture_contract_factory=_capture_factory(tmp_path, PlayByPlay),
        call_admission=lambda *_args: events.append("static"),
        conditional_route_admission=admit_conditional,
    )
    entry = StagingEntry(
        "live_play_by_play",
        "stg_live_play_by_play",
        "game",
    )

    result = await runner._extract_single_result(
        entry,
        {"game_id": _GAME_ID},
        snapshot_at=_SNAPSHOT_AT,
    )

    assert isinstance(result, _ExtractionTaskResult)
    assert events == ["static", "provider", "conditional"]
    assert set(result.frames) == {"stg_live_play_by_play", LIVE_LOSSLESS_STAGING_KEY}
    assert result.pending_success is not None
    binding = result.pending_success.receipt_binding
    assert binding is not None
    live_route = _live_route("live_play_by_play", PlayByPlay)
    assert binding.result_route_ids == tuple(sorted((_STATIC_ROUTE, live_route)))
    assert result.result_route_ids_by_staging_key == tuple(
        sorted(
            (
                ("stg_live_play_by_play", _STATIC_ROUTE),
                (LIVE_LOSSLESS_STAGING_KEY, live_route),
            )
        )
    )
    live_frame = result.frames[LIVE_LOSSLESS_STAGING_KEY]
    receipts = live_frame["response_receipt_sha256"].unique().to_list()
    assert len(receipts) == 1 and isinstance(receipts[0], str)
    validate_live_lossless_frame(
        live_frame,
        expected_response_receipt_sha256=receipts[0],
        expected_result_set_count=len(pinned_live_endpoint_contract(PlayByPlay).result_sets),
        expected_snapshot_at=_SNAPSHOT_AT,
        expected_endpoint_id="PlayByPlay",
        expected_endpoint_slug="playbyplay",
    )
    schema = get_input_schema(LIVE_LOSSLESS_STAGING_KEY)
    assert schema is not None
    normalized = schema.validate(live_frame)
    assert dict(normalized.schema) == LIVE_LOSSLESS_SCHEMA


@pytest.mark.asyncio
async def test_uncaptured_runner_keeps_wide_output_without_public_unbound_nodes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_live_response(monkeypatch, PlayByPlay)
    registry = MagicMock()
    registry.get.return_value = LivePlayByPlayExtractor
    runner = ExtractorRunner(registry, _settings(), _journal())
    entry = StagingEntry("live_play_by_play", "stg_live_play_by_play", "game")

    result = await runner._extract_single_result(
        entry,
        {"game_id": _GAME_ID},
        snapshot_at=_SNAPSHOT_AT,
    )

    assert isinstance(result, dict)
    assert set(result) == {"stg_live_play_by_play"}


def _captured_scoreboard_source(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
):
    _patch_live_response(monkeypatch, ScoreBoard)
    authority = _ExactLiveAuthorityHarness()
    warehouse = LiveSnapshotWarehouse(
        settings=_recurring_settings(tmp_path),
        public_recurring=True,
        raw_request_capture_context_factory=authority.context_for,
        live_plan_authority_binding_factory=authority.plan_for,
    )
    extraction = warehouse.extract_source_calls(
        game_ids=[],
        snapshot_at=_SNAPSHOT_AT,
    )
    assert len(extraction.source_calls) == 1
    return extraction.source_calls[0]


def test_production_live_snapshot_retains_nodes_when_scoreboard_has_no_active_games(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    source = _captured_scoreboard_source(monkeypatch, tmp_path)

    assert source.expected_staging_keys == (
        "stg_live_score_board",
        LIVE_LOSSLESS_STAGING_KEY,
    )
    assert set(source.frames) == set(source.expected_staging_keys)
    assert source.receipt_binding is not None
    assert source.receipt_binding.result_route_ids == tuple(
        sorted(
            (
                "live_score_board:stg_live_score_board:0",
                _live_route("live_score_board", ScoreBoard),
            )
        )
    )
    assert not source.frames[LIVE_LOSSLESS_STAGING_KEY].is_empty()


def test_production_live_snapshot_binds_each_live_endpoint_to_its_distinct_node_route(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    endpoint_contracts = (
        ("live_score_board", ScoreBoard),
        ("live_odds", Odds),
        ("live_play_by_play", PlayByPlay),
        ("live_box_score", BoxScore),
    )
    responses = iter(
        _live_response(_complete_endpoint_payload(pinned_live_endpoint_contract(endpoint_cls)))
        for _endpoint_name, endpoint_cls in endpoint_contracts
    )
    monkeypatch.setattr(
        NbaDbLiveHTTP,
        "send_api_request",
        lambda _self, **_kwargs: next(responses),
    )
    authority = _ExactLiveAuthorityHarness()
    warehouse = LiveSnapshotWarehouse(
        settings=_recurring_settings(tmp_path),
        public_recurring=True,
        raw_request_capture_context_factory=authority.context_for,
        live_plan_authority_binding_factory=authority.plan_for,
    )

    extraction = warehouse.extract_source_calls(
        game_ids=[_GAME_ID],
        snapshot_at=_SNAPSHOT_AT,
    )

    assert tuple(call.endpoint_name for call in extraction.source_calls) == tuple(
        endpoint_name for endpoint_name, _endpoint_cls in endpoint_contracts
    )
    for source_call, (endpoint_name, endpoint_cls) in zip(
        extraction.source_calls,
        endpoint_contracts,
        strict=True,
    ):
        assert source_call.receipt_binding is not None
        assert LIVE_LOSSLESS_STAGING_KEY in source_call.frames
        live_route = _live_route(endpoint_name, endpoint_cls)
        assert live_route in source_call.receipt_binding.result_route_ids
        assert source_call.result_route_ids_by_staging_key == tuple(
            sorted(source_call.result_route_ids_by_staging_key)
        )
        live_frame = source_call.frames[LIVE_LOSSLESS_STAGING_KEY]
        (receipt,) = live_frame["response_receipt_sha256"].unique().to_list()
        validate_live_lossless_frame(
            live_frame,
            expected_response_receipt_sha256=receipt,
            expected_result_set_count=len(pinned_live_endpoint_contract(endpoint_cls).result_sets),
            expected_snapshot_at=_SNAPSHOT_AT,
            expected_endpoint_id=endpoint_cls.__name__,
            expected_endpoint_slug=pinned_live_endpoint_contract(endpoint_cls).endpoint_slug,
        )


def test_live_lossless_frame_is_sqlite_exportable(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    import sqlite3

    source = _captured_scoreboard_source(monkeypatch, tmp_path)
    frame = source.frames[LIVE_LOSSLESS_STAGING_KEY]
    sqlite_path = tmp_path / "nba.sqlite"

    SQLiteLoader(sqlite_path).load(LIVE_LOSSLESS_STAGING_KEY, frame)

    connection = sqlite3.connect(sqlite_path)
    try:
        row_count = connection.execute(
            f'SELECT COUNT(*) FROM "{LIVE_LOSSLESS_STAGING_KEY}"'
        ).fetchone()
        columns = tuple(
            str(row[1])
            for row in connection.execute(
                f'PRAGMA table_info("{LIVE_LOSSLESS_STAGING_KEY}")'
            ).fetchall()
        )
    finally:
        connection.close()
    assert row_count == (frame.height,)
    assert columns == tuple(LIVE_LOSSLESS_SCHEMA)


@pytest.mark.parametrize(
    ("tamper", "error"),
    [
        ("snapshot", "snapshot"),
        ("request", "request scope"),
    ],
)
def test_staging_batch_rejects_tampered_live_tree_before_any_wide_write(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    tamper: str,
    error: str,
) -> None:
    source = _captured_scoreboard_source(monkeypatch, tmp_path)
    assert source.receipt_binding is not None
    frames = source.frames
    replacement = (
        pl.lit(None, dtype=pl.Datetime("us", "UTC")).alias("snapshot_at")
        if tamper == "snapshot"
        else pl.lit('{"GameID":"0022400001"}').alias("request_parameters_json")
    )
    frames[LIVE_LOSSLESS_STAGING_KEY] = frames[LIVE_LOSSLESS_STAGING_KEY].with_columns(replacement)
    connection = duckdb.connect(":memory:")
    store = StagingBatchStore(connection)
    batch = StagingFrameBatch(
        frames=frames,
        metadata=StagingChunkMetadata(
            run_mode="successor",
            lane_id="live-lossless",
            pattern="live",
            chunk_index=0,
            params_digest="0" * 64,
            entries_digest="1" * 64,
            source_endpoint_name=source.endpoint_name,
            source_params_digest=source.receipt_binding.logical_parameters_sha256,
        ),
        expected_staging_keys=source.expected_staging_keys,
        receipt_binding=source.receipt_binding,
        result_route_ids_by_staging_key=source.result_route_ids_by_staging_key,
    )

    with pytest.raises(ParserInputCaptureIntegrityError, match=error):
        store.persist_frame_batches([batch], materialize=True)

    tables = {
        str(row[0])
        for row in connection.execute(
            "select table_name from information_schema.tables where table_schema = 'main'"
        ).fetchall()
    }
    assert "_staging_chunks__stg_live_score_board" not in tables
    assert f"_staging_chunks__{LIVE_LOSSLESS_STAGING_KEY}" not in tables
    assert connection.execute("select count(*) from _staging_chunk_journal").fetchone() == (0,)
    connection.close()


def test_planning_validator_accepts_receipt_bound_live_nodes_and_rejects_tampering(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    source_call = _captured_scoreboard_source(monkeypatch, tmp_path)
    assert source_call.receipt_binding is not None
    dispatch = SimpleNamespace(
        endpoint_name="live_score_board",
        staging_route_ids=("live_score_board:stg_live_score_board:0",),
        parameters_sha256=canonical_parameters_sha256({}),
    )
    request = cast(
        "PlanningExactCallRuntimeRequest",
        SimpleNamespace(
            dispatch=dispatch,
            provider_authority_sha256=staging_route_contract_bundle().provider_authority_sha256,
            as_of_utc=_SNAPSHOT_AT.isoformat(timespec="seconds").replace("+00:00", "Z"),
        ),
    )
    source = [
        {
            "frames": source_call.frames,
            "source_endpoint_name": source_call.endpoint_name,
            "source_params_json": source_call.parameters_json,
            "expected_staging_keys": source_call.expected_staging_keys,
            "receipt_binding": source_call.receipt_binding,
            "result_route_ids_by_staging_key": tuple(
                sorted(source_call.result_route_ids_by_staging_key)
            ),
            "raw_request_capture_snapshot": source_call.raw_request_capture_snapshot,
            "recorded_static_attempts": (),
            "plan_live_snapshot_at": _SNAPSHOT_AT,
        }
    ]

    validated = ExtractorPlanningExactCallRuntime._validated_source_result(
        request,
        source,
    )
    assert set(validated.frames) == {"stg_live_score_board", LIVE_LOSSLESS_STAGING_KEY}

    bad_frames = dict(source_call.frames)
    bad_frames[LIVE_LOSSLESS_STAGING_KEY] = bad_frames[LIVE_LOSSLESS_STAGING_KEY].with_columns(
        pl.lit("0" * 64).alias("endpoint_contract_sha256")
    )
    bad_source = [dict(source[0], frames=bad_frames)]
    with pytest.raises(ExactPlanningRuntimeError, match="typed authority"):
        ExtractorPlanningExactCallRuntime._validated_source_result(request, bad_source)

    for expression in (
        pl.lit('{"GameID":"0022400001"}').alias("request_parameters_json"),
        pl.lit(
            datetime(2026, 4, 17, 12, 0, 1, tzinfo=UTC),
            dtype=pl.Datetime("us", "UTC"),
        ).alias("snapshot_at"),
    ):
        bad_frames = dict(source_call.frames)
        bad_frames[LIVE_LOSSLESS_STAGING_KEY] = bad_frames[LIVE_LOSSLESS_STAGING_KEY].with_columns(
            expression
        )
        bad_source = [dict(source[0], frames=bad_frames)]
        with pytest.raises(ExactPlanningRuntimeError, match="request scope|snapshot"):
            ExtractorPlanningExactCallRuntime._validated_source_result(request, bad_source)


def test_same_generation_restore_keeps_live_conditional_route_outside_delta_receipts() -> None:
    bundle = staging_route_contract_bundle()
    route = bundle.by_route_id["live_score_board:stg_live_score_board:0"]
    transaction = _successor_candidate(
        route_id=route.route_id,
        route_contract_sha256=route.contract_sha256,
        parameters={},
        provider_authority_sha256=bundle.provider_authority_sha256,
    )
    plan = _successor_plan_for_scopes(transaction.intent.requested_scopes)
    dispatch = plan.dispatches[0]
    (static_attestation,) = _successor_replacement_attestations(
        transaction,
        dispatch,
        logical_root="a" * 64,
    )
    live_attestation = SourceScopeReplacementAttestation(
        successor_generation_sha256=transaction.generation_identity_sha256,
        source_scope_sha256=dispatch.parameters_sha256,
        staging_key=LIVE_LOSSLESS_STAGING_KEY,
        prior_persisted_content_sha256=None,
        persisted_content_sha256="b" * 64,
        persisted_schema_sha256="c" * 64,
        persisted_row_count=10,
        logical_call_receipt_sha256=static_attestation.logical_call_receipt_sha256,
        provider_authority_sha256=bundle.provider_authority_sha256,
        logical_parameters_sha256=dispatch.parameters_sha256,
        result_route_id=_live_route("live_score_board", ScoreBoard),
        canonical_frame_format=CANONICAL_FRAME_FORMAT,
        frame_content_hash_contract=FRAME_CONTENT_HASH_CONTRACT,
        frame_schema_hash_contract=FRAME_SCHEMA_HASH_CONTRACT,
    )
    attestations = (static_attestation, live_attestation)

    receipts = successor_receipts_from_replacement_attestations(
        transaction=transaction,
        execution_plan=plan,
        attestations=attestations,
    )
    bindings = logical_bindings_from_replacement_attestations(attestations)

    assert len(receipts) == 1
    assert len(bindings) == 1
    assert bindings[0].result_route_ids == tuple(
        sorted((route.route_id, live_attestation.result_route_id))
    )
