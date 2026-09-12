from __future__ import annotations

import asyncio
import hashlib
import json
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from typing import TYPE_CHECKING, cast

import duckdb
import polars as pl
import pytest

from nbadb.contracts.raw_request_authority import RequestAttemptIdentityV2
from nbadb.contracts.raw_transport_contract import StatsHttpTransportV1
from nbadb.contracts.staging_route_contract import (
    admit_conditional_lossless_route,
    staging_route_contract_bundle,
)
from nbadb.extract.bronze import LogicalCallReceiptBinding, canonical_parameters_sha256
from nbadb.extract.nba_api_adapter import LOSSLESS_FALLBACK_SCHEMA
from nbadb.extract.raw_request_capture import (
    PendingRawRequestSuccessV2,
    RawRequestCaptureSnapshotV2,
)
from nbadb.orchestrate.extractor_runner import PatternExtractionResult
from nbadb.orchestrate.orchestrator import ExtractionPlanItem, Orchestrator
from nbadb.orchestrate.staging_batches import (
    CANONICAL_FRAME_FORMAT,
    FRAME_CONTENT_HASH_CONTRACT,
    FRAME_SCHEMA_HASH_CONTRACT,
    SourceScopeReplacementAttestation,
)
from nbadb.orchestrate.staging_map import LOSSLESS_FALLBACK_STAGING_KEY
from nbadb.orchestrate.successor_execution_restore import (
    logical_bindings_from_replacement_attestations,
    successor_receipts_from_replacement_attestations,
)
from nbadb.orchestrate.successor_planning_runtime import (
    ExactPlanningRuntimeError,
    ExtractorPlanningExactCallRuntime,
)
from nbadb.orchestrate.successor_update_contract import SuccessorUpdateContractError
from nbadb.schemas.registry import get_input_schema
from tests.unit.orchestrate.test_orchestrator import (
    _build_orchestrator_with_mocks,
    _mock_capture_session,
    _mock_settings,
    _successor_candidate,
    _successor_plan_for_scopes,
    _successor_registry_kwargs,
    _successor_replacement_attestations,
)

if TYPE_CHECKING:
    from collections.abc import Mapping
    from typing import Any

    from nbadb.core.db import DBManager
    from nbadb.orchestrate.extractor_runner import ExtractorRunner
    from nbadb.orchestrate.successor_planning_runtime import PlanningExactCallRuntimeRequest

_ENDPOINT = "league_game_log"
_STATIC_ROUTE = "league_game_log:stg_league_game_log:0"
_FALLBACK_ROUTE = f"{_ENDPOINT}:{LOSSLESS_FALLBACK_STAGING_KEY}:1"
_RECEIPT = "9" * 64
_SOURCE_SHA = "a" * 40
_LOGICAL_PARAMETERS = {"season": "2025-26", "season_type": "Regular Season"}
_PROVIDER_PARAMETERS = {
    "season": "2025-26",
    "season_type_all_star": "Regular Season",
}
_VIDEO_LOGICAL_PARAMETERS = {"game_id": "0022400001", "game_event_id": 1}
_VIDEO_PROVIDER_PARAMETERS = dict(_VIDEO_LOGICAL_PARAMETERS)
_STARTED_AT = datetime(2026, 8, 27, 12, 0, tzinfo=UTC)


def _sha(label: str) -> str:
    return hashlib.sha256(label.encode()).hexdigest()


def _raw_snapshot(
    *,
    binding: LogicalCallReceiptBinding,
    route_id: str,
    provider_parameters: Mapping[str, object],
) -> RawRequestCaptureSnapshotV2:
    route = staging_route_contract_bundle().by_route_id[route_id]
    attempt = RequestAttemptIdentityV2.build(
        semantic_request_sha256=_sha(f"semantic:{route_id}"),
        logical_invocation_sha256=_sha(f"logical:{route_id}"),
        provider_call_role="primary",
        provider_call_ordinal=0,
        retry_ordinal=0,
        request_ordinal=0,
        source_family="stats",
        endpoint_id=route.provider_endpoint_id,
        parameters=provider_parameters,
        provider_authority_sha256=binding.provider_authority_sha256,
        endpoint_contract_sha256=route.endpoint_contract_sha256,
        competition_id=None,
        competition_identity_sha256=None,
        scope_sha256=binding.logical_parameters_sha256,
        pagination_sha256=None,
        page_ordinal=None,
        source_sha=_SOURCE_SHA,
        run_id=7001,
        run_attempt=1,
        chain_id="planning-chain",
        lane_id="planning-lane",
    )
    pending = PendingRawRequestSuccessV2(
        private_receipt_sha256=_RECEIPT,
        attempt=attempt,
        transport=StatsHttpTransportV1(
            transport_kind="stats_http",
            status_code=200,
            effective_status_code=200,
        ),
        started_at=_STARTED_AT,
        finished_at=_STARTED_AT + timedelta(seconds=1),
        elapsed_ns=1_000_000_000,
        outcome="success_nonempty",
        body_disposition="declared_bodyless",
        body_object=None,
        results=(),
        logical_receipt_sha256=binding.logical_call_receipt_sha256,
        aggregate_route_ids=binding.result_route_ids,
    )
    return RawRequestCaptureSnapshotV2(
        objects=(),
        observations=(),
        pending_successes=(pending,),
        issues=(),
    )


def _static_empty_frame() -> pl.DataFrame:
    route = staging_route_contract_bundle().by_route_id[_STATIC_ROUTE]
    schema = get_input_schema(route.resolved_schema_table)
    assert schema is not None
    schema_object = schema.to_schema()
    return pl.DataFrame(
        schema={name: column.dtype.type for name, column in schema_object.columns.items()}
    )


def _fallback_frame(
    *,
    receipt: str | None = _RECEIPT,
    endpoint_slug: str = "leaguegamelog",
) -> pl.DataFrame:
    return pl.DataFrame(
        [
            {
                "response_receipt_sha256": receipt,
                "endpoint_slug": endpoint_slug,
                "record_kind": "missing_expected",
                "result_set_name": "LeagueGameLog",
                "result_set_occurrence": 0,
                "provider_index": None,
                "canonical_index": 0,
                "header_name": None,
                "header_ordinal": None,
                "row_ordinal": None,
                "value_kind": None,
                "canonical_json": None,
                "anomaly_codes_json": '["missing_result_set"]',
            }
        ],
        schema=LOSSLESS_FALLBACK_SCHEMA,
    )


def _planning_source(
    *,
    fallback: pl.DataFrame | None,
) -> tuple[PlanningExactCallRuntimeRequest, list[dict[str, object]]]:
    bundle = staging_route_contract_bundle()
    provider_authority = bundle.provider_authority_sha256
    dispatch = SimpleNamespace(
        endpoint_name=_ENDPOINT,
        staging_route_ids=(_STATIC_ROUTE,),
        parameters_sha256=canonical_parameters_sha256(_LOGICAL_PARAMETERS),
    )
    request = SimpleNamespace(
        dispatch=dispatch,
        provider_authority_sha256=provider_authority,
    )
    frames = {
        "stg_league_game_log": (pl.DataFrame() if fallback is not None else _static_empty_frame())
    }
    route_mapping = [("stg_league_game_log", _STATIC_ROUTE)]
    expected_keys = ["stg_league_game_log"]
    result_route_ids = [_STATIC_ROUTE]
    if fallback is not None:
        frames[LOSSLESS_FALLBACK_STAGING_KEY] = fallback
        route_mapping.append((LOSSLESS_FALLBACK_STAGING_KEY, _FALLBACK_ROUTE))
        expected_keys.append(LOSSLESS_FALLBACK_STAGING_KEY)
        result_route_ids.append(_FALLBACK_ROUTE)
    binding = LogicalCallReceiptBinding(
        logical_call_receipt_sha256="5" * 64,
        endpoint_name=_ENDPOINT,
        logical_parameters_sha256=dispatch.parameters_sha256,
        provider_authority_sha256=provider_authority,
        result_route_ids=tuple(sorted(result_route_ids)),
    )
    source = {
        "frames": frames,
        "source_endpoint_name": _ENDPOINT,
        "source_params_json": json.dumps(
            _LOGICAL_PARAMETERS, sort_keys=True, separators=(",", ":")
        ),
        "expected_staging_keys": tuple(expected_keys),
        "receipt_binding": binding,
        "result_route_ids_by_staging_key": tuple(sorted(route_mapping)),
        "raw_request_capture_snapshot": _raw_snapshot(
            binding=binding,
            route_id=_STATIC_ROUTE,
            provider_parameters=_PROVIDER_PARAMETERS,
        ),
        "recorded_static_attempts": (),
    }
    return cast("PlanningExactCallRuntimeRequest", request), [source]


def _video_event_planning_source() -> tuple[
    PlanningExactCallRuntimeRequest, list[dict[str, object]]
]:
    endpoint_name = "video_events"
    staging_key = "stg_video_events"
    static_route = f"{endpoint_name}:{staging_key}:0"
    fallback_route = f"{endpoint_name}:{LOSSLESS_FALLBACK_STAGING_KEY}:0"
    bundle = staging_route_contract_bundle()
    fallback = _fallback_frame(endpoint_slug="videoevents")
    dispatch = SimpleNamespace(
        endpoint_name=endpoint_name,
        staging_route_ids=(static_route,),
        parameters_sha256=canonical_parameters_sha256(_VIDEO_LOGICAL_PARAMETERS),
    )
    request = SimpleNamespace(
        dispatch=dispatch,
        provider_authority_sha256=bundle.provider_authority_sha256,
    )
    binding = LogicalCallReceiptBinding(
        logical_call_receipt_sha256="5" * 64,
        endpoint_name=endpoint_name,
        logical_parameters_sha256=dispatch.parameters_sha256,
        provider_authority_sha256=bundle.provider_authority_sha256,
        result_route_ids=tuple(sorted((static_route, fallback_route))),
    )
    source = {
        "frames": {
            staging_key: fallback.clone(),
            LOSSLESS_FALLBACK_STAGING_KEY: fallback,
        },
        "source_endpoint_name": endpoint_name,
        "source_params_json": json.dumps(
            _VIDEO_LOGICAL_PARAMETERS, sort_keys=True, separators=(",", ":")
        ),
        "expected_staging_keys": (staging_key, LOSSLESS_FALLBACK_STAGING_KEY),
        "receipt_binding": binding,
        "result_route_ids_by_staging_key": tuple(
            sorted(
                (
                    (staging_key, static_route),
                    (LOSSLESS_FALLBACK_STAGING_KEY, fallback_route),
                )
            )
        ),
        "raw_request_capture_snapshot": _raw_snapshot(
            binding=binding,
            route_id=static_route,
            provider_parameters=_VIDEO_PROVIDER_PARAMETERS,
        ),
        "recorded_static_attempts": (),
    }
    return cast("PlanningExactCallRuntimeRequest", request), [source]


def _transaction_plan_dispatch():
    bundle = staging_route_contract_bundle()
    parameters = {"season": "2025-26", "season_type": "Regular Season"}
    transaction = _successor_candidate(
        route_id=_STATIC_ROUTE,
        route_contract_sha256=bundle.by_route_id[_STATIC_ROUTE].contract_sha256,
        parameters=parameters,
        provider_authority_sha256=bundle.provider_authority_sha256,
    )
    plan = _successor_plan_for_scopes(transaction.intent.requested_scopes)
    return transaction, plan, plan.dispatches[0]


def test_conditional_authority_admits_only_exact_post_response_route() -> None:
    bundle = staging_route_contract_bundle()

    admission = admit_conditional_lossless_route(
        endpoint_name=_ENDPOINT,
        static_route_ids=(_STATIC_ROUTE,),
        conditional_route_ids=(_FALLBACK_ROUTE,),
        provider_authority_sha256=bundle.provider_authority_sha256,
    )

    assert admission.route_id == _FALLBACK_ROUTE
    assert admission.result_set_index == 1
    assert admission.provider_endpoint_slug == "leaguegamelog"
    assert admission.static_route_ids == (_STATIC_ROUTE,)
    assert admission.storage_columns == tuple(LOSSLESS_FALLBACK_SCHEMA)
    assert len(staging_route_contract_bundle().routes) == 438


@pytest.mark.parametrize(
    ("endpoint_name", "static_routes", "conditional_routes", "provider_authority"),
    [
        (_ENDPOINT, (_STATIC_ROUTE,), (f"{_ENDPOINT}:stg_not_lossless:1",), None),
        (_ENDPOINT, (_STATIC_ROUTE,), ("scoreboard:stg_nba_api_lossless_result_cells:1",), None),
        (_ENDPOINT, (_STATIC_ROUTE,), (f"{_ENDPOINT}:{LOSSLESS_FALLBACK_STAGING_KEY}:0",), None),
        (_ENDPOINT, (_STATIC_ROUTE,), (_STATIC_ROUTE,), None),
        (_ENDPOINT, ("scoreboard:stg_scoreboard:0",), (_FALLBACK_ROUTE,), None),
        (_ENDPOINT, (_STATIC_ROUTE,), (_FALLBACK_ROUTE,), "0" * 64),
    ],
    ids=[
        "wrong-route",
        "wrong-endpoint",
        "wrong-result-index",
        "static-masquerade",
        "foreign-static-route",
        "wrong-provider-receipt",
    ],
)
def test_conditional_authority_rejects_route_and_receipt_masquerades(
    endpoint_name: str,
    static_routes: tuple[str, ...],
    conditional_routes: tuple[str, ...],
    provider_authority: str | None,
) -> None:
    bundle = staging_route_contract_bundle()

    with pytest.raises(ValueError):
        admit_conditional_lossless_route(
            endpoint_name=endpoint_name,
            static_route_ids=static_routes,
            conditional_route_ids=conditional_routes,
            provider_authority_sha256=provider_authority or bundle.provider_authority_sha256,
        )


def test_planning_validator_accepts_static_only_and_fallback_only_frames() -> None:
    static_request, static_source = _planning_source(fallback=None)
    static_result = ExtractorPlanningExactCallRuntime._validated_source_result(
        static_request, static_source
    )
    assert static_result.frames["stg_league_game_log"].shape == (0, 32)

    fallback_request, fallback_source = _planning_source(fallback=_fallback_frame())
    fallback_result = ExtractorPlanningExactCallRuntime._validated_source_result(
        fallback_request, fallback_source
    )
    assert fallback_result.frames["stg_league_game_log"].shape == (0, 32)
    assert fallback_result.frames[LOSSLESS_FALLBACK_STAGING_KEY].shape == (
        1,
        len(LOSSLESS_FALLBACK_SCHEMA),
    )


def test_planning_validator_preserves_video_event_canonical_and_global_lossless_routes() -> None:
    request, source = _video_event_planning_source()

    result = ExtractorPlanningExactCallRuntime._validated_source_result(request, source)

    assert set(result.frames) == {"stg_video_events", LOSSLESS_FALLBACK_STAGING_KEY}
    assert result.frames["stg_video_events"].equals(result.frames[LOSSLESS_FALLBACK_STAGING_KEY])
    assert result.frames["stg_video_events"].columns == list(LOSSLESS_FALLBACK_SCHEMA)


@pytest.mark.parametrize(
    "fallback",
    [
        _fallback_frame(receipt=None),
        _fallback_frame(endpoint_slug="scoreboardv3"),
    ],
    ids=["missing-response-receipt", "wrong-provider-endpoint"],
)
def test_planning_validator_rejects_unbound_or_foreign_fallback(
    fallback: pl.DataFrame,
) -> None:
    request, source = _planning_source(fallback=fallback)

    with pytest.raises(ExactPlanningRuntimeError, match="fallback frame differs"):
        ExtractorPlanningExactCallRuntime._validated_source_result(request, source)


@pytest.mark.parametrize("wide_row_count", [0, 7], ids=["fallback-only", "wide-and-fallback"])
def test_same_generation_resume_keeps_conditional_binding_without_widening_intent(
    wide_row_count: int,
) -> None:
    transaction, plan, dispatch = _transaction_plan_dispatch()
    logical_root = "6" * 64
    (static_attestation,) = _successor_replacement_attestations(
        transaction,
        dispatch,
        logical_root=logical_root,
    )
    static_attestation = replace(static_attestation, persisted_row_count=wide_row_count)
    fallback_attestation = SourceScopeReplacementAttestation(
        successor_generation_sha256=transaction.generation_identity_sha256,
        source_scope_sha256=dispatch.parameters_sha256,
        staging_key=LOSSLESS_FALLBACK_STAGING_KEY,
        prior_persisted_content_sha256="7" * 64,
        persisted_content_sha256="8" * 64,
        persisted_schema_sha256="9" * 64,
        persisted_row_count=1,
        logical_call_receipt_sha256=logical_root,
        provider_authority_sha256=transaction.baseline.provider_authority_sha256,
        logical_parameters_sha256=dispatch.parameters_sha256,
        result_route_id=_FALLBACK_ROUTE,
        canonical_frame_format=CANONICAL_FRAME_FORMAT,
        frame_content_hash_contract=FRAME_CONTENT_HASH_CONTRACT,
        frame_schema_hash_contract=FRAME_SCHEMA_HASH_CONTRACT,
    )
    attestations = (static_attestation, fallback_attestation)

    receipts = successor_receipts_from_replacement_attestations(
        transaction=transaction,
        execution_plan=plan,
        attestations=attestations,
    )
    bindings = logical_bindings_from_replacement_attestations(attestations)

    assert len(receipts) == 1
    assert receipts[0].persisted_row_count == wide_row_count
    assert bindings[0].result_route_ids == tuple(sorted((_STATIC_ROUTE, _FALLBACK_ROUTE)))


def test_orchestrator_conditional_hook_rechecks_static_intent() -> None:
    transaction, _plan, dispatch = _transaction_plan_dispatch()
    successor_kwargs = cast("dict[str, Any]", _successor_registry_kwargs(transaction))
    orchestrator = Orchestrator(
        settings=_mock_settings(),
        capture_session=_mock_capture_session(),
        successor_transaction=transaction,
        **successor_kwargs,
    )

    orchestrator._admit_successor_conditional_result_routes(
        _ENDPOINT,
        dispatch.parameters,
        dispatch.staging_route_ids,
        (_FALLBACK_ROUTE,),
    )
    with pytest.raises(SuccessorUpdateContractError):
        orchestrator._admit_successor_conditional_result_routes(
            _ENDPOINT,
            {**dispatch.parameters, "season": "2024-25"},
            dispatch.staging_route_ids,
            (_FALLBACK_ROUTE,),
        )


@pytest.mark.parametrize("supports_retain_frames", [True, False])
def test_extraction_forwards_retention_only_when_runner_supports_it(
    supports_retain_frames: bool,
) -> None:
    orchestrator, _database, _journal = _build_orchestrator_with_mocks()
    entry = SimpleNamespace(
        endpoint_name="ep1",
        staging_key="stg_ep1",
        result_set_index=0,
        param_pattern="season",
    )
    observed: list[bool] = []

    if supports_retain_frames:

        async def run_pattern_result(
            _pattern,
            _params,
            _entries,
            *,
            on_progress=None,
            retain_frames: bool = True,
        ):
            del on_progress
            observed.append(retain_frames)
            return PatternExtractionResult(eligible_calls=1, success_count=1, frames={})

    else:

        async def run_pattern_result(  # type: ignore[misc]
            _pattern,
            _params,
            _entries,
            *,
            on_progress=None,
        ):
            del on_progress
            observed.append(True)
            return PatternExtractionResult(eligible_calls=1, success_count=1, frames={})

    runner = SimpleNamespace(run_pattern_result=run_pattern_result)
    outcome = asyncio.run(
        orchestrator._extract_all_patterns(
            cast("ExtractorRunner", runner),
            plan=[
                ExtractionPlanItem(
                    label="season",
                    pattern="season",
                    entries=[cast("Any", entry)],
                    params=[{"season": "2024-25"}],
                    priority=1,
                )
            ],
            seasons=[],
            game_ids=[],
            player_ids=[],
            team_ids=[],
            current_team_ids=[],
            game_dates=[],
            player_team_season_params=[],
            game_log_df=pl.DataFrame(),
            retain_in_memory=False,
        )
    )

    assert outcome.pattern_failures == 0
    assert observed == ([False] if supports_retain_frames else [True])


def test_staging_store_is_reused_only_for_its_exact_connection() -> None:
    orchestrator, _database, _journal = _build_orchestrator_with_mocks()
    first_connection = duckdb.connect(":memory:")
    second_connection = duckdb.connect(":memory:")
    first_db = SimpleNamespace(duckdb=first_connection)
    second_db = SimpleNamespace(duckdb=second_connection)
    try:
        first_store = orchestrator._staging_store_for(cast("DBManager", first_db))

        assert orchestrator._staging_store_for(cast("DBManager", first_db)) is first_store
        assert orchestrator._staging_store_for(cast("DBManager", second_db)) is not first_store
    finally:
        first_connection.close()
        second_connection.close()


@pytest.mark.parametrize("fallback_present", [False, True])
def test_successor_export_keys_include_fallback_only_when_materialized(
    fallback_present: bool,
) -> None:
    connection = duckdb.connect(":memory:")
    database = SimpleNamespace(duckdb=connection)
    try:
        connection.execute("CREATE TABLE stg_league_game_log (value INTEGER)")
        if fallback_present:
            connection.execute(f"CREATE TABLE {LOSSLESS_FALLBACK_STAGING_KEY} (value INTEGER)")

        keys = Orchestrator._successor_publication_staging_keys(
            cast("DBManager", database),
            ("stg_league_game_log",),
        )

        expected = {"stg_league_game_log"}
        if fallback_present:
            expected.add(LOSSLESS_FALLBACK_STAGING_KEY)
        assert set(keys) == expected
    finally:
        connection.close()
