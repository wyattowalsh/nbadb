from __future__ import annotations

import json
from dataclasses import replace
from datetime import date, timedelta
from functools import lru_cache
from types import SimpleNamespace
from typing import TYPE_CHECKING, cast
from unittest.mock import MagicMock, patch

import duckdb
import polars as pl
import pytest
from nba_api.stats.library.http import NBAStatsHTTP

from nbadb.contracts.field_fate_structure import compile_field_fate_structure
from nbadb.contracts.raw_request_authority import (
    ParserInputObjectV2,
    RequestAttemptIdentityV2,
    RequestObservationV2,
)
from nbadb.contracts.staging_route_contract import staging_route_contract_bundle
from nbadb.core.errors import ParserInputCaptureIntegrityError
from nbadb.core.nba_api_competition_identity import (
    compile_competition_identity_requirements,
)
from nbadb.core.nba_api_request_surface import pinned_request_surface_authority
from nbadb.core.nba_api_runtime_contract import pinned_static_contracts
from nbadb.extract.bronze import (
    LogicalCallReceiptBinding,
    canonical_parameters_sha256,
)
from nbadb.extract.nba_api_adapter import (
    rederive_raw_authority_stats_rows,
    rows_to_polars,
)
from nbadb.extract.raw_request_capture import (
    PendingRawRequestSuccessV2,
    PendingResultOccurrenceV2,
    RawRequestCaptureSnapshotV2,
)
from nbadb.extract.registry import EndpointRegistry
from nbadb.extract.static.players import (
    StaticPlayersExtractor,
    StaticWnbaPlayersExtractor,
)
from nbadb.extract.static.teams import StaticTeamsExtractor, StaticWnbaTeamsExtractor
from nbadb.extract.stats.player_info import CommonAllPlayersExtractor
from nbadb.orchestrate.body_blob_store import BodyBlobStore
from nbadb.orchestrate.declared_bodyless_packet_store import DeclaredBodylessPacketStore
from nbadb.orchestrate.extractor_runner import ExtractorRunner, PendingRequestObservation
from nbadb.orchestrate.orchestrator import Orchestrator
from nbadb.orchestrate.planning import ExtractionPlanItem
from nbadb.orchestrate.raw_request_context import (
    RawRequestExecutionIdentityV1,
    compile_ordinary_stats_raw_request_context,
)
from nbadb.orchestrate.raw_request_store import (
    RAW_REQUEST_AUTHORITY_BUNDLE_JOURNAL,
    RAW_REQUEST_AUTHORITY_MANIFEST_JOURNAL,
    RAW_REQUEST_AUTHORITY_TABLES,
    RawRequestAuthorityStore,
    RawRequestManifestAuthorityV2,
    compile_raw_request_manifest_authority,
)
from nbadb.orchestrate.request_closure_production import (
    ProductionRequestClosureBuild,
    ReceiptOnlyCaptureFactory,
    build_ordinary_request_closure_authority,
)
from nbadb.orchestrate.staging_map import get_by_endpoint
from nbadb.orchestrate.w2_source_call_preparation import W2SourceCallPreparationRuntime
from nbadb.schemas.raw.player import RawCommonAllPlayersSchema
from tests.unit.contracts.test_raw_request_finalization import _STARTED_AT
from tests.unit.orchestrate._raw_request_test_support import (
    raw_request_assurance_authority,
)

if TYPE_CHECKING:
    from pathlib import Path

    from nbadb.core.config import NbaDbSettings
    from nbadb.core.db import DBManager
    from nbadb.orchestrate.extractor_runner import RequestClosureExecutionAuthority

_PARAMS: dict[str, object] = {
    "is_only_current_season": 0,
    "league_id": "00",
    "season": "2025-26",
}
_STATIC_EXTRACTORS = (
    StaticPlayersExtractor,
    StaticTeamsExtractor,
    StaticWnbaPlayersExtractor,
    StaticWnbaTeamsExtractor,
)
_STATIC_ENDPOINTS = tuple(sorted(item.endpoint_name for item in _STATIC_EXTRACTORS))


def _static_plan() -> list[ExtractionPlanItem]:
    plan: list[ExtractionPlanItem] = []
    for endpoint_name in _STATIC_ENDPOINTS:
        entries = get_by_endpoint(endpoint_name)
        assert entries
        plan.append(
            ExtractionPlanItem(
                label=f"raw static integration: {endpoint_name}",
                pattern=entries[0].param_pattern,
                entries=entries,
                params=[{}],
                priority=0,
            )
        )
    return plan


def _static_closure_build() -> tuple[
    list[ExtractionPlanItem],
    ProductionRequestClosureBuild,
]:
    registry = EndpointRegistry()
    for extractor in _STATIC_EXTRACTORS:
        registry.register(extractor)
    plan = _static_plan()
    build = build_ordinary_request_closure_authority(
        plan,
        registry=registry,
        run_mode="init",
        support_date=date(2026, 8, 27),
        discovery_seed_requested=False,
        recurring_live_requested=False,
    )
    assert build.authority is None
    assert build.scope_gaps == ()
    assert tuple(item.endpoint_name for item in build.static_authorities) == (_STATIC_ENDPOINTS)
    return plan, build


def _runner_settings() -> MagicMock:
    settings = MagicMock()
    settings.semaphore_tiers = {"default": 4, "static": 4}
    settings.endpoint_semaphore_limits = {}
    settings.pbp_chunk_size = 50
    settings.default_chunk_size = 50
    settings.thread_pool_size = 4
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


@pytest.mark.asyncio
async def test_cold_cache_all_four_static_routes_reach_terminal_raw_manifest(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    def _unexpected_network(*_args: object, **_kwargs: object) -> None:
        raise AssertionError("static raw-request integration attempted network I/O")

    monkeypatch.setattr(NBAStatsHTTP, "send_api_request", _unexpected_network)
    staging_route_contract_bundle.cache_clear()
    pinned_static_contracts.cache_clear()
    pinned_request_surface_authority.cache_clear()
    compile_competition_identity_requirements.cache_clear()

    plan, build = _static_closure_build()
    execution = _execution(lane_id="lane-static-all")
    assurance_authority = raw_request_assurance_authority(source_sha=execution.source_sha)
    manifest_authority = compile_raw_request_manifest_authority(
        execution,
        None,
        static_authorities=build.static_authorities,
        assurance_authority=assurance_authority,
    )
    registry = EndpointRegistry()
    for extractor in _STATIC_EXTRACTORS:
        registry.register(extractor)
    settings = _runner_settings()
    journal = MagicMock()
    journal.was_extracted_batch.return_value = set()
    orchestrator = Orchestrator(
        settings=settings,
        raw_request_execution_identity=execution,
        raw_request_assurance_authority=assurance_authority,
        raw_request_manifest_authority=manifest_authority,
        w2_preparation_runtime=_w2_runtime(tmp_path, execution),
    )
    orchestrator._enable_ordinary_request_closure_capture()
    receipt_factory = orchestrator._receipt_only_capture_factory
    assert receipt_factory is not None
    runner = ExtractorRunner(
        registry,
        settings,
        journal,
        capture_contract_factory=receipt_factory.contract_for,
    )
    connection = duckdb.connect(":memory:")
    try:
        outcome = await orchestrator._extract_all_patterns(
            runner,
            plan=plan,
            seasons=[],
            game_ids=[],
            player_ids=[],
            team_ids=[],
            game_dates=[],
            game_log_df=pl.DataFrame(),
            run_mode="init",
            journal=journal,
            persist_results=lambda frames, **metadata: orchestrator._persist_staging_to_duckdb(
                _db(connection),
                frames,
                **metadata,
            ),
            retain_in_memory=False,
            request_closure_build=build,
        )
    finally:
        runner.shutdown()

    try:
        assert outcome.pattern_failures == outcome.failed_calls == 0
        assert receipt_factory.sink.outstanding_parser_input_bytes == 0
        assert len(orchestrator.raw_request_persistence_receipts) == 4
        manifest = orchestrator.raw_request_authority_manifest
        assert manifest is not None
        assert {item.endpoint_name for item in manifest.expected_calls} == set(_STATIC_ENDPOINTS)
        assert {item.source_family for item in manifest.expected_calls} == {"static"}
        assert manifest.unresolved_request_sha256s == ()
        assert manifest.completed_request_count == 4
        assert manifest.coverage_complete is True
        assert manifest.terminal_sealed is True
        assert manifest.is_complete is True
        assert journal.record_success.call_count == 4
        assert {
            call.kwargs["receipt_binding"].endpoint_name
            for call in journal.record_success.call_args_list
        } == set(_STATIC_ENDPOINTS)
        assert [_count(connection, table) for table in RAW_REQUEST_AUTHORITY_TABLES] == [
            0,
            4,
            4,
            4,
        ]
        assert _count(connection, RAW_REQUEST_AUTHORITY_BUNDLE_JOURNAL) == 4
        assert _count(connection, RAW_REQUEST_AUTHORITY_MANIFEST_JOURNAL) == 5
    finally:
        connection.close()


@pytest.mark.asyncio
@pytest.mark.parametrize("authority_mode", ["missing", "foreign"])
async def test_static_authority_inventory_fails_before_provider_execution(
    authority_mode: str,
) -> None:
    plan, complete = _static_closure_build()
    if authority_mode == "missing":
        active_plan = plan
        static_authorities = complete.static_authorities[:-1]
    else:
        active_plan = plan[:-1]
        static_authorities = complete.static_authorities
    build = ProductionRequestClosureBuild(
        None,
        (),
        complete.support_date,
        static_authorities,
    )
    execution = _execution(lane_id=f"lane-static-{authority_mode}")
    assurance_authority = raw_request_assurance_authority(source_sha=execution.source_sha)
    manifest_authority = compile_raw_request_manifest_authority(
        execution,
        None,
        static_authorities=static_authorities,
        assurance_authority=assurance_authority,
    )
    registry = EndpointRegistry()
    for extractor in _STATIC_EXTRACTORS:
        registry.register(extractor)
    settings = _runner_settings()
    journal = MagicMock()
    journal.was_extracted_batch.return_value = set()
    runner = ExtractorRunner(
        registry,
        settings,
        journal,
        capture_contract_factory=ReceiptOnlyCaptureFactory(
            execution_identity=execution
        ).contract_for,
    )
    orchestrator = Orchestrator(
        settings=settings,
        raw_request_execution_identity=execution,
        raw_request_assurance_authority=assurance_authority,
        raw_request_manifest_authority=manifest_authority,
    )
    connection = duckdb.connect(":memory:")
    try:
        with pytest.raises(ParserInputCaptureIntegrityError):
            await orchestrator._extract_all_patterns(
                runner,
                plan=active_plan,
                seasons=[],
                game_ids=[],
                player_ids=[],
                team_ids=[],
                game_dates=[],
                game_log_df=pl.DataFrame(),
                run_mode="init",
                journal=journal,
                persist_results=lambda frames, **metadata: orchestrator._persist_staging_to_duckdb(
                    _db(connection),
                    frames,
                    **metadata,
                ),
                retain_in_memory=False,
                request_closure_build=build,
            )

        journal.record_start.assert_not_called()
        assert connection.execute("SHOW TABLES").fetchall() == []
    finally:
        runner.shutdown()
        connection.close()


def _execution(*, lane_id: str = "lane") -> RawRequestExecutionIdentityV1:
    return RawRequestExecutionIdentityV1(
        source_sha="1" * 40,
        run_id=101,
        run_attempt=1,
        chain_id="chain",
        lane_id=lane_id,
    )


@lru_cache(maxsize=1)
def _request_closure() -> RequestClosureExecutionAuthority:
    entries = get_by_endpoint("common_all_players")
    assert entries
    registry = EndpointRegistry()
    registry.register(CommonAllPlayersExtractor)
    build = build_ordinary_request_closure_authority(
        [
            ExtractionPlanItem(
                label="raw manifest runtime fixture",
                pattern=entries[0].param_pattern,
                entries=entries,
                params=[dict(_PARAMS)],
                priority=0,
            )
        ],
        registry=registry,
        run_mode="init",
        support_date=date(2026, 8, 27),
        discovery_seed_requested=False,
        recurring_live_requested=False,
    )
    assert build.scope_gaps == ()
    assert build.authority is not None
    return build.authority


def _manifest_authority(
    *,
    execution: RawRequestExecutionIdentityV1 | None = None,
    closure: RequestClosureExecutionAuthority | None = None,
) -> RawRequestManifestAuthorityV2:
    resolved_execution = execution or _execution()
    return compile_raw_request_manifest_authority(
        resolved_execution,
        closure or _request_closure(),
        assurance_authority=raw_request_assurance_authority(
            source_sha=resolved_execution.source_sha
        ),
    )


def _orchestrator(
    *,
    lane_id: str = "lane",
    manifest_authority: RawRequestManifestAuthorityV2 | None = None,
    w2_root: Path | None = None,
) -> Orchestrator:
    execution = _execution(lane_id=lane_id)
    return Orchestrator(
        settings=cast("NbaDbSettings", object()),
        raw_request_execution_identity=execution,
        raw_request_assurance_authority=raw_request_assurance_authority(
            source_sha=execution.source_sha
        ),
        raw_request_manifest_authority=manifest_authority,
        w2_preparation_runtime=(_w2_runtime(w2_root, execution) if w2_root is not None else None),
    )


def _w2_runtime(
    root: Path,
    execution: RawRequestExecutionIdentityV1,
) -> W2SourceCallPreparationRuntime:
    body_root = root / "body"
    bodyless_root = root / "bodyless"
    body_root.mkdir(mode=0o700, exist_ok=True)
    bodyless_root.mkdir(mode=0o700, exist_ok=True)
    body_root.chmod(0o700)
    bodyless_root.chmod(0o700)
    identity = {
        "source_sha": execution.source_sha,
        "run_id": execution.run_id,
        "run_attempt": execution.run_attempt,
        "chain_id": execution.chain_id,
        "lane_id": execution.lane_id,
    }
    return W2SourceCallPreparationRuntime(
        body_blob_store=BodyBlobStore(body_root, **identity),
        declared_bodyless_packet_store=DeclaredBodylessPacketStore(
            bodyless_root,
            **identity,
        ),
        field_fate=compile_field_fate_structure(),
    )


def _db(connection: duckdb.DuckDBPyConnection) -> DBManager:
    return cast("DBManager", SimpleNamespace(duckdb=connection))


def _stats_success_source() -> tuple[
    dict[str, pl.DataFrame],
    dict[str, object],
    RawRequestCaptureSnapshotV2,
    LogicalCallReceiptBinding,
]:
    closure = _request_closure()
    execution = _execution()
    context = compile_ordinary_stats_raw_request_context(
        closure,
        execution,
        "common_all_players",
        dict(_PARAMS),
    )
    call = context.provider_calls[0]
    route = staging_route_contract_bundle().by_route_id[
        "common_all_players:stg_common_all_players:0"
    ]
    attempt = RequestAttemptIdentityV2.build(
        semantic_request_sha256=call.semantic_request_sha256,
        logical_invocation_sha256=call.logical_invocation_sha256,
        provider_call_role=call.provider_call_role,
        provider_call_ordinal=call.provider_call_ordinal,
        retry_ordinal=0,
        request_ordinal=call.request_ordinal,
        source_family="stats",
        endpoint_id=call.endpoint_id,
        parameters=_PARAMS,
        provider_authority_sha256=context.provider_authority_sha256,
        endpoint_contract_sha256=call.endpoint_contract_sha256,
        competition_id=call.competition_id,
        competition_identity_sha256=call.competition_identity_sha256,
        scope_sha256=call.scope_sha256,
        pagination_sha256=call.pagination_sha256,
        page_ordinal=call.page_ordinal,
        source_sha=execution.source_sha,
        run_id=execution.run_id,
        run_attempt=execution.run_attempt,
        chain_id=execution.chain_id,
        lane_id=execution.lane_id,
    )
    binding = LogicalCallReceiptBinding(
        logical_call_receipt_sha256="5" * 64,
        endpoint_name=route.endpoint_name,
        logical_parameters_sha256=canonical_parameters_sha256(_PARAMS),
        provider_authority_sha256=context.provider_authority_sha256,
        result_route_ids=(route.route_id,),
    )
    parser_input = json.dumps(
        {
            "resultSets": [
                {
                    "name": route.provider_result_set_name,
                    "headers": list(route.provider_columns),
                    "rowSet": [
                        [
                            {
                                "PERSON_ID": 1,
                                "ROSTERSTATUS": 1,
                                "TEAM_ID": 1_610_612_737,
                            }.get(header, f"value-{index}")
                            for index, header in enumerate(route.provider_columns)
                        ]
                    ],
                }
            ]
        },
        separators=(",", ":"),
    )
    body = ParserInputObjectV2.from_parser_input(parser_input)
    derivations = rederive_raw_authority_stats_rows(
        endpoint_id=call.endpoint_id,
        parser_input=parser_input.encode(),
        provider_authority_sha256=context.provider_authority_sha256,
        endpoint_contract_sha256_value=call.endpoint_contract_sha256,
    )
    assert len(derivations) == 1
    result = derivations[0].result_set
    logical_call = closure.logical_calls[0]
    pending_closure = PendingRequestObservation(
        request_surface_sha256=closure.route_manifest.request_surface_sha256,
        route_manifest_sha256=closure.route_manifest.manifest_sha256,
        scope_sha256=closure.scope.scope_sha256,
        provider_request_sha256=logical_call.provider_request_sha256,
        source_family="stats",
        endpoint_id=call.endpoint_id,
        route_ids=logical_call.route_ids,
        attempt_count=1,
        retry_ordinal=0,
        request_ordinal=0,
        http_status=200,
        response_body_sha256=body.response_sha256,
        response_body_bytes=body.uncompressed_bytes,
        parser_input_sha256=body.response_sha256,
        response_receipt_sha256="9" * 64,
        logical_call_receipt_sha256=binding.logical_call_receipt_sha256,
        logical_parameters_sha256=binding.logical_parameters_sha256,
        provider_parameters_sha256=cast("str", logical_call.provider_parameters_sha256),
        provider_authority_sha256=binding.provider_authority_sha256,
        endpoint_contract_sha256=route.endpoint_contract_sha256,
        result_contract="pinned_exact",
        bronze_result_sets=(result,),
    )
    snapshot = RawRequestCaptureSnapshotV2(
        objects=(body,),
        observations=(),
        pending_successes=(
            PendingRawRequestSuccessV2(
                private_receipt_sha256="6" * 64,
                attempt=attempt,
                transport={
                    "transport_kind": "stats_http",
                    "status_code": 200,
                    "effective_status_code": 200,
                },
                started_at=_STARTED_AT,
                finished_at=_STARTED_AT + timedelta(seconds=1),
                elapsed_ns=1_000_000_000,
                outcome="success_nonempty",
                body_disposition="public_parser_input",
                body_object=body,
                results=(
                    PendingResultOccurrenceV2(
                        result_set=result,
                        duplicate_name_ordinal=0,
                        ordered_headers=route.provider_columns,
                    ),
                ),
                logical_receipt_sha256=binding.logical_call_receipt_sha256,
                aggregate_route_ids=binding.result_route_ids,
            ),
        ),
        issues=(),
    )
    values = tuple(
        tuple(json.loads(cell.canonical_json) for cell in row) for row in derivations[0].rows
    )
    frame = rows_to_polars(derivations[0].ordered_headers, values).rename(
        {item.provider_column: item.canonical_column for item in route.column_mappings}
    )
    frame = RawCommonAllPlayersSchema.validate(frame)
    assert isinstance(frame, pl.DataFrame)
    frame = frame.with_columns(
        pl.lit(_PARAMS["season"]).alias("season_year"),
        pl.lit(_PARAMS["league_id"]).alias("league_id"),
    )
    frames = {route.staging_key: frame}
    source = {
        "frames": frames,
        "source_endpoint_name": route.endpoint_name,
        "source_params_json": json.dumps(
            _PARAMS,
            sort_keys=True,
        ),
        "expected_staging_keys": (route.staging_key,),
        "receipt_binding": binding,
        "raw_request_capture_snapshot": snapshot,
        "pending_request_observations": (pending_closure,),
        "result_route_ids_by_staging_key": ((route.staging_key, route.route_id),),
    }
    return frames, source, snapshot, binding


def _failed_snapshot() -> RawRequestCaptureSnapshotV2:
    _frames, _source, success_snapshot, _binding = _stats_success_source()
    pending = success_snapshot.pending_successes[0]
    observation = RequestObservationV2.build(
        attempt=pending.attempt,
        transport={"transport_kind": "stats_http"},
        started_at=_STARTED_AT,
        finished_at=_STARTED_AT + timedelta(milliseconds=1),
        elapsed_ns=1_000_000,
        lifecycle="incomplete",
        outcome="transport_failure_no_response",
        failure_class="transport_transient",
        root_exception_class="ConnectionError",
        body_disposition="no_response",
        body_object_sha256=None,
        bodyless_evidence_sha256="7" * 64,
        result_occurrence_sha256s=(),
        route_landing_sha256s=(),
        capture_response_receipt_sha256=None,
        logical_receipt_sha256=None,
    )
    return RawRequestCaptureSnapshotV2(
        objects=(),
        observations=(observation,),
        pending_successes=(),
        issues=(),
    )


def _count(connection: duckdb.DuckDBPyConnection, table: str) -> int:
    return cast("int", connection.execute(f'SELECT count(*) FROM "{table}"').fetchone()[0])


def test_success_commits_staging_then_raw_authority_and_replays_idempotently(
    tmp_path: Path,
) -> None:
    connection = duckdb.connect(":memory:")
    orchestrator = _orchestrator(w2_root=tmp_path)
    frames, source, _snapshot, _binding = _stats_success_source()
    try:
        admissions = []
        for _attempt in range(2):
            admissions.append(
                orchestrator._persist_staging_to_duckdb(
                    _db(connection),
                    frames,
                    run_mode="init",
                    lane_id="lane",
                    pattern="season",
                    chunk_index=0,
                    chunk_params=[{"season": "2024-25"}],
                    entries=[],
                    source_results=[source],
                    request_closure_authority=_request_closure(),
                    materialize=False,
                )
            )

        assert len(admissions[0]) == len(admissions[1]) == 1
        assert admissions[0][0].identity_payload() == admissions[1][0].identity_payload()
        assert admissions[0][0].admission_sha256 == admissions[1][0].admission_sha256
        assert [_count(connection, table) for table in RAW_REQUEST_AUTHORITY_TABLES] == [
            1,
            1,
            1,
            1,
        ]
        assert _count(connection, RAW_REQUEST_AUTHORITY_BUNDLE_JOURNAL) == 1
        assert _count(connection, RAW_REQUEST_AUTHORITY_MANIFEST_JOURNAL) == 1
        assert len(orchestrator.raw_request_persistence_receipts) == 1
        assert orchestrator.raw_request_persistence_receipts[0].replayed is False
        assert orchestrator.raw_request_authority_manifest is not None
        assert orchestrator.raw_request_authority_manifest.generation == 0
        assert orchestrator.raw_request_authority_manifest.delta_receipt_sha256s == (
            orchestrator.raw_request_persistence_receipts[0].receipt_sha256,
        )
    finally:
        connection.close()


def test_success_requires_explicit_w2_runtime_before_any_staging_write() -> None:
    connection = duckdb.connect(":memory:")
    orchestrator = _orchestrator()
    frames, source, _snapshot, _binding = _stats_success_source()
    try:
        with pytest.raises(
            ParserInputCaptureIntegrityError,
            match="requires an explicit W2 preparation runtime",
        ):
            orchestrator._persist_staging_to_duckdb(
                _db(connection),
                frames,
                source_results=[source],
                request_closure_authority=_request_closure(),
                materialize=False,
            )

        assert connection.execute("SHOW TABLES").fetchall() == []
        assert orchestrator.raw_request_persistence_receipts == ()
        assert orchestrator.raw_request_authority_manifest is None
    finally:
        connection.close()


def test_failure_only_snapshot_persists_without_staging_or_success_materialization() -> None:
    connection = duckdb.connect(":memory:")
    orchestrator = _orchestrator()
    try:
        orchestrator._persist_staging_to_duckdb(
            _db(connection),
            {},
            run_mode="init",
            lane_id="lane",
            pattern="season",
            failure_raw_request_capture_snapshots=(_failed_snapshot(),),
            request_closure_authority=_request_closure(),
            materialize=False,
        )

        tables = {str(row[0]) for row in connection.execute("SHOW TABLES").fetchall()}
        assert "_staging_chunk_journal" not in tables
        assert [_count(connection, table) for table in RAW_REQUEST_AUTHORITY_TABLES] == [
            0,
            1,
            0,
            0,
        ]
        assert _count(connection, RAW_REQUEST_AUTHORITY_BUNDLE_JOURNAL) == 1
        assert _count(connection, RAW_REQUEST_AUTHORITY_MANIFEST_JOURNAL) == 1
        assert len(orchestrator.raw_request_persistence_receipts) == 1
    finally:
        connection.close()


def test_raw_store_failure_stops_postcommit_callback_after_staging_commit(
    tmp_path: Path,
) -> None:
    connection = duckdb.connect(":memory:")
    orchestrator = _orchestrator(w2_root=tmp_path)
    frames, source, _snapshot, _binding = _stats_success_source()
    try:
        with (
            patch.object(
                RawRequestAuthorityStore,
                "persist_bundle",
                side_effect=RuntimeError("test-only raw store failure"),
            ),
            pytest.raises(RuntimeError, match="raw store failure"),
        ):
            orchestrator._persist_staging_to_duckdb(
                _db(connection),
                frames,
                run_mode="init",
                lane_id="lane",
                pattern="season",
                chunk_index=0,
                chunk_params=[{"season": "2024-25"}],
                entries=[],
                source_results=[source],
                request_closure_authority=_request_closure(),
                materialize=False,
            )

        tables = {str(row[0]) for row in connection.execute("SHOW TABLES").fetchall()}
        assert "_staging_chunk_journal" in tables
        assert not (set(RAW_REQUEST_AUTHORITY_TABLES) & tables)
        assert orchestrator.raw_request_persistence_receipts == ()
    finally:
        connection.close()


def test_foreign_execution_snapshot_fails_before_any_staging_write(tmp_path: Path) -> None:
    connection = duckdb.connect(":memory:")
    orchestrator = _orchestrator(w2_root=tmp_path)
    frames, source, snapshot, _binding = _stats_success_source()
    pending = snapshot.pending_successes[0]
    source["raw_request_capture_snapshot"] = replace(
        snapshot,
        pending_successes=(
            replace(
                pending,
                attempt=pending.attempt.model_copy(update={"lane_id": "foreign-lane"}),
            ),
        ),
    )
    try:
        with pytest.raises(
            ParserInputCaptureIntegrityError,
            match="differs from execution authority",
        ):
            orchestrator._persist_staging_to_duckdb(
                _db(connection),
                frames,
                source_results=[source],
                request_closure_authority=_request_closure(),
                materialize=False,
            )

        assert connection.execute("SHOW TABLES").fetchall() == []
    finally:
        connection.close()


@pytest.mark.parametrize(
    ("execution", "assurance_authority", "manifest_authority", "message"),
    (
        (
            _execution(),
            None,
            None,
            "requires a verified assurance authority",
        ),
        (
            None,
            raw_request_assurance_authority(),
            None,
            "cannot admit authorities without an execution identity",
        ),
        (
            None,
            None,
            _manifest_authority(),
            "cannot admit authorities without an execution identity",
        ),
    ),
)
def test_constructor_rejects_partial_raw_capture_authority(
    execution: RawRequestExecutionIdentityV1 | None,
    assurance_authority: object | None,
    manifest_authority: RawRequestManifestAuthorityV2 | None,
    message: str,
) -> None:
    with pytest.raises(
        ParserInputCaptureIntegrityError,
        match=message,
    ):
        Orchestrator(
            settings=cast("NbaDbSettings", object()),
            raw_request_execution_identity=execution,
            raw_request_assurance_authority=assurance_authority,  # type: ignore[arg-type]
            raw_request_manifest_authority=manifest_authority,
        )


def test_constructor_rejects_manifest_from_foreign_execution() -> None:
    execution = _execution()
    assurance_authority = raw_request_assurance_authority(source_sha=execution.source_sha)
    foreign = replace(_manifest_authority(execution=execution), run_id=execution.run_id + 1)

    with pytest.raises(
        ParserInputCaptureIntegrityError,
        match="differs from execution identity",
    ):
        Orchestrator(
            settings=cast("NbaDbSettings", object()),
            raw_request_execution_identity=execution,
            raw_request_assurance_authority=assurance_authority,
            raw_request_manifest_authority=foreign,
        )


@pytest.mark.parametrize(
    "field_name",
    ("field_authority_sha256", "model_authority_sha256"),
)
def test_manifest_authority_rejects_incomplete_field_or_model_digest(
    field_name: str,
) -> None:
    values = _manifest_authority().to_dict()
    values.pop("schema_version")
    values.pop("kind")
    values[field_name] = "not-a-digest"

    with pytest.raises(
        ValueError,
        match=field_name,
    ):
        RawRequestManifestAuthorityV2(**values)  # type: ignore[arg-type]


@pytest.mark.parametrize(
    "field_name",
    (
        "route_authority_sha256",
        "request_closure_authority_sha256",
    ),
)
def test_foreign_closure_authority_fails_before_any_staging_write(
    field_name: str,
) -> None:
    connection = duckdb.connect(":memory:")
    foreign = replace(_manifest_authority(), **{field_name: "9" * 64})
    orchestrator = _orchestrator(manifest_authority=foreign)
    frames, source, _snapshot, _binding = _stats_success_source()
    try:
        with pytest.raises(
            ParserInputCaptureIntegrityError,
            match="differs from request closure",
        ):
            orchestrator._persist_staging_to_duckdb(
                _db(connection),
                frames,
                source_results=[source],
                request_closure_authority=_request_closure(),
                materialize=False,
            )

        assert connection.execute("SHOW TABLES").fetchall() == []
    finally:
        connection.close()


def test_manifest_authority_rejects_scope_outside_exact_request_denominator() -> None:
    with pytest.raises(
        ValueError,
        match="scope_sha256 does not bind the exact per-request scope denominator",
    ):
        replace(_manifest_authority(), scope_sha256="9" * 64)


def test_manifest_failure_stops_callback_after_raw_commit_before_success(
    tmp_path: Path,
) -> None:
    connection = duckdb.connect(":memory:")
    orchestrator = _orchestrator(w2_root=tmp_path)
    frames, source, _snapshot, _binding = _stats_success_source()
    try:
        with (
            patch.object(
                RawRequestAuthorityStore,
                "advance_manifest",
                side_effect=RuntimeError("test-only manifest failure"),
            ),
            pytest.raises(RuntimeError, match="manifest failure"),
        ):
            orchestrator._persist_staging_to_duckdb(
                _db(connection),
                frames,
                source_results=[source],
                request_closure_authority=_request_closure(),
                materialize=False,
            )

        tables = {str(row[0]) for row in connection.execute("SHOW TABLES").fetchall()}
        assert "_staging_chunk_journal" in tables
        assert set(RAW_REQUEST_AUTHORITY_TABLES) <= tables
        assert RAW_REQUEST_AUTHORITY_BUNDLE_JOURNAL in tables
        assert RAW_REQUEST_AUTHORITY_MANIFEST_JOURNAL not in tables
        assert orchestrator.raw_request_persistence_receipts == ()
        assert orchestrator.raw_request_authority_manifest is None
    finally:
        connection.close()
