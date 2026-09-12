from __future__ import annotations

import copy
import hashlib
import inspect
import json
from dataclasses import dataclass, replace
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import polars as pl
import pyarrow as pa
import pyarrow.ipc as pa_ipc
import pytest

import nbadb.contracts.field_fate_structure as field_fate_module
import nbadb.contracts.raw_request_authority as raw_authority_module
import nbadb.contracts.typed_field_value_receipt as receipt_module
from nbadb.contracts.canonical_arrow_value import (
    CanonicalArrowValueError,
    ValueBudgetLimits,
    canonical_arrow_array_scalar,
    canonical_arrow_scalar,
    compare_canonical_arrow_values,
)
from nbadb.contracts.field_fate_structure import (
    ConditionalRouteOccurrenceAuthorityV1,
    FieldFateStructureError,
    FieldFateStructureV1,
    compile_field_fate_structure,
    derive_conditional_route_occurrence_authority,
)
from nbadb.contracts.raw_request_authority import (
    ObservationRouteLandingV2,
    ParserInputObjectV2,
    RawRequestAuthorityBundleV2,
    RequestAttemptIdentityV2,
    RequestObservationV2,
    ResultOccurrenceV2,
)
from nbadb.contracts.raw_request_finalization import finalize_raw_request_capture
from nbadb.contracts.raw_request_reconstruction import LiveSnapshotPlanAuthorityV2
from nbadb.contracts.staging_route_contract import staging_route_contract_bundle
from nbadb.contracts.typed_field_value_receipt import (
    OccurrenceLandingAuthorityV2,
    RouteFieldLandingReceiptV2,
    TypedFieldValueReceiptError,
    canonical_json_bytes,
    canonical_sha256,
    validate_route_field_landing_receipt_replay,
)
from nbadb.core.nba_api_runtime_contract import pinned_live_contracts
from nbadb.extract.bronze import LogicalCallReceiptBinding
from nbadb.extract.live_lossless import build_live_lossless_landing
from nbadb.extract.nba_api_adapter import (
    fetch_static_packet,
    rederive_raw_authority_result_sets,
    rederive_raw_authority_route_frames,
    rederive_raw_authority_stats_fallback,
    rederive_raw_authority_stats_wide_rows,
    validate_lossless_fallback_frame,
)
from nbadb.extract.raw_request_capture import (
    PendingRawRequestSuccessV2,
    PendingResultOccurrenceV2,
    RawRequestCaptureSnapshotV2,
)
from nbadb.orchestrate.staging_batches import (
    CANONICAL_FRAME_FORMAT,
    FRAME_CONTENT_HASH_CONTRACT,
    FRAME_SCHEMA_HASH_CONTRACT,
    CommittedStagingChunkReceiptV2,
    CommittedStagingFrameReadbackV2,
    frame_content_hash,
    frame_schema_hash,
)
from tests.unit.contracts.test_field_fate_structure import (
    _body_node_conditional_authority,
    _rebuild_result_occurrence,
    _selected_stats_conditional_authority,
    _selected_unknown_stats_conditional_authority,
)
from tests.unit.contracts.test_independent_stats_value_decoder import (
    _legacy_payload,
    _schedule_payload,
    _scoreboard_payload,
    _traditional_payload,
)
from tests.unit.contracts.test_raw_request_authority import _video_bundle
from tests.unit.contracts.test_raw_request_finalization import _case
from tests.unit.extract.test_live_lossless_nodes import _complete_endpoint_payload

_ROUTE_ID = "common_team_years:stg_team_years:0"
_STARTED = datetime(2026, 8, 27, 12, 0, tzinfo=UTC)
_RAW_HEADERS = ["LEAGUE_ID", "TEAM_ID", "MIN_YEAR", "MAX_YEAR", "ABBREVIATION"]
_RAW_ROWS: list[list[object]] = [
    ["00", 1, "1946", "2026", "AAA"],
    ["00", 2, "1949", "2026", "BBB"],
]


def _sha(label: str) -> str:
    return hashlib.sha256(label.encode("utf-8")).hexdigest()


def _normalized_output_sha256(headers: list[str], rows: list[list[object]]) -> str:
    encoded = json.dumps(
        {"headers": headers, "rows": rows},
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


@pytest.fixture(scope="module")
def field_fate() -> FieldFateStructureV1:
    return compile_field_fate_structure()


_CONDITIONAL_CASE_CACHE: dict[
    tuple[str, str],
    tuple[str, pl.DataFrame, ConditionalRouteOccurrenceAuthorityV1],
] = {}


def _cached_conditional_case(
    field_fate: FieldFateStructureV1,
    shape: str,
) -> tuple[str, pl.DataFrame, ConditionalRouteOccurrenceAuthorityV1]:
    key = (field_fate.identity_sha256, shape)
    cached = _CONDITIONAL_CASE_CACHE.get(key)
    if cached is not None:
        return cached
    factories = {
        "selected_result_bound": _selected_stats_conditional_authority,
        "body_node_bound": _body_node_conditional_authority,
        "hybrid_result_body_bound": _selected_unknown_stats_conditional_authority,
        "live_lossless_bound": _typed_live_conditional_authority,
    }
    built = factories[shape](field_fate)
    _CONDITIONAL_CASE_CACHE[key] = built
    return built


def _cached_selected_stats_conditional_authority(
    field_fate: FieldFateStructureV1,
) -> tuple[str, pl.DataFrame, ConditionalRouteOccurrenceAuthorityV1]:
    return _cached_conditional_case(field_fate, "selected_result_bound")


def _cached_body_node_conditional_authority(
    field_fate: FieldFateStructureV1,
) -> tuple[str, pl.DataFrame, ConditionalRouteOccurrenceAuthorityV1]:
    return _cached_conditional_case(field_fate, "body_node_bound")


def _cached_live_conditional_authority(
    field_fate: FieldFateStructureV1,
) -> tuple[str, pl.DataFrame, ConditionalRouteOccurrenceAuthorityV1]:
    return _cached_conditional_case(field_fate, "live_lossless_bound")


def _cached_hybrid_stats_conditional_authority(
    field_fate: FieldFateStructureV1,
) -> tuple[str, pl.DataFrame, ConditionalRouteOccurrenceAuthorityV1]:
    return _cached_conditional_case(field_fate, "hybrid_result_body_bound")


@dataclass(frozen=True, slots=True)
class _Fixture:
    frame: pl.DataFrame
    readback: CommittedStagingFrameReadbackV2
    bundle: RawRequestAuthorityBundleV2


def _committed_receipt_from_landing(
    landing: ObservationRouteLandingV2,
) -> CommittedStagingChunkReceiptV2:
    return CommittedStagingChunkReceiptV2(
        chunk_id=landing.chunk_id,
        staging_key=landing.staging_key,
        canonical_frame_format=landing.canonical_frame_format,
        frame_content_hash_contract=landing.frame_content_hash_contract,
        frame_schema_hash_contract=landing.frame_schema_hash_contract,
        content_hash=landing.content_hash,
        persisted_row_count=landing.persisted_row_count,
        persisted_content_sha256=landing.persisted_content_sha256,
        persisted_schema_sha256=landing.persisted_schema_sha256,
        logical_call_receipt_sha256=landing.logical_call_receipt_sha256,
        provider_authority_sha256=landing.provider_authority_sha256,
        logical_parameters_sha256=landing.logical_parameters_sha256,
        result_route_id=landing.result_route_id,
    )


def _occurrence(
    attempt: RequestAttemptIdentityV2,
    *,
    receipt_root_sha256: str,
    occurrence_ordinal: int,
    headers: list[str],
    rows: list[list[object]],
) -> ResultOccurrenceV2:
    row_count = len(rows)
    parser_input = json.dumps(
        {
            "resultSets": [
                {
                    "name": "TeamYears",
                    "headers": headers,
                    "rowSet": rows,
                }
            ]
        },
        separators=(",", ":"),
    ).encode("utf-8")
    derivations = rederive_raw_authority_result_sets(
        source_family="stats",
        endpoint_id=attempt.endpoint_id,
        parser_input=parser_input,
        provider_authority_sha256=attempt.provider_authority_sha256,
        endpoint_contract_sha256_value=attempt.endpoint_contract_sha256,
    )
    assert len(derivations) == 1
    derivation = derivations[0]
    result = derivation.result_set
    return ResultOccurrenceV2.build(
        observation_sha256=attempt.observation_sha256,
        occurrence_ordinal=occurrence_ordinal,
        result_name="TeamYears",
        duplicate_name_ordinal=0,
        provider_result_ordinal=0,
        canonical_result_ordinal=0,
        json_path=None,
        container_kind="nba_api_result_set",
        presence="present" if rows else "present_empty",
        ordered_headers=headers,
        row_count=row_count,
        cell_count=row_count * len(headers),
        node_count=0,
        container_count=result.container_count,
        missing_count=result.missing_count,
        null_count=result.null_count,
        parent_state_sha256=result.parent_occurrence_states_sha256,
        output_sha256=result.normalized_output_sha256,
        canonical_route_ids=[_ROUTE_ID],
        committed_staging_receipts=[{"route_id": _ROUTE_ID, "receipt_sha256": receipt_root_sha256}],
        landing_disposition="wide_only",
    )


def _fixture(
    *,
    headers: list[str] | None = None,
    raw_rows: list[list[object]] | None = None,
    foreign_occurrence_root: bool = False,
    include_zero_row_occurrence: bool = False,
) -> _Fixture:
    route = staging_route_contract_bundle().by_route_id[_ROUTE_ID]
    frame = pl.DataFrame(
        {
            "league_id": pl.Series(["00", "00"], dtype=pl.String),
            "team_id": pl.Series([1, 2], dtype=pl.Int64),
            "min_year": pl.Series(["1946", "1949"], dtype=pl.String),
            "max_year": pl.Series(["2026", "2026"], dtype=pl.String),
            "abbreviation": pl.Series(["AAA", "BBB"], dtype=pl.String),
        }
    )

    def attempt(call_ordinal: int) -> RequestAttemptIdentityV2:
        return RequestAttemptIdentityV2.build(
            semantic_request_sha256=_sha(f"semantic-{call_ordinal}"),
            logical_invocation_sha256=_sha("invocation"),
            provider_call_role="primary",
            provider_call_ordinal=call_ordinal,
            retry_ordinal=0,
            request_ordinal=call_ordinal,
            source_family="stats",
            endpoint_id=route.provider_endpoint_id,
            parameters={"league_id": "00"},
            provider_authority_sha256=route.provider_authority_sha256,
            endpoint_contract_sha256=route.endpoint_contract_sha256,
            competition_id="nba",
            competition_identity_sha256=_sha("competition"),
            scope_sha256=_sha("scope"),
            pagination_sha256=None,
            page_ordinal=None,
            source_sha="1" * 40,
            run_id=101,
            run_attempt=1,
            chain_id="chain",
            lane_id="lane",
        )

    logical_receipt = _sha("logical-receipt")
    first_attempt = attempt(0)
    content_sha256 = frame_content_hash(frame)
    committed = CommittedStagingChunkReceiptV2(
        chunk_id="chunk-team-years",
        staging_key=route.staging_key,
        canonical_frame_format=CANONICAL_FRAME_FORMAT,
        frame_content_hash_contract=FRAME_CONTENT_HASH_CONTRACT,
        frame_schema_hash_contract=FRAME_SCHEMA_HASH_CONTRACT,
        content_hash=content_sha256,
        persisted_row_count=frame.height,
        persisted_content_sha256=content_sha256,
        persisted_schema_sha256=frame_schema_hash(frame),
        logical_call_receipt_sha256=logical_receipt,
        provider_authority_sha256=first_attempt.provider_authority_sha256,
        logical_parameters_sha256=first_attempt.safe_parameters_sha256,
        result_route_id=_ROUTE_ID,
    )
    exact_headers = headers or list(_RAW_HEADERS)
    occurrence_root = (
        _sha("foreign-root") if foreign_occurrence_root else committed.receipt_root_sha256
    )
    first_rows = _RAW_ROWS if raw_rows is None else raw_rows
    occurrence_rows = [first_rows, []] if include_zero_row_occurrence else [first_rows]
    objects: list[ParserInputObjectV2] = []
    observations: list[RequestObservationV2] = []
    occurrences: list[ResultOccurrenceV2] = []
    landings: list[ObservationRouteLandingV2] = []
    for call_ordinal, raw_rows in enumerate(occurrence_rows):
        current_attempt = attempt(call_ordinal)
        body = ParserInputObjectV2.from_parser_input(
            json.dumps(
                {
                    "resultSets": [
                        {
                            "name": "TeamYears",
                            "headers": exact_headers,
                            "rowSet": raw_rows,
                        }
                    ]
                },
                separators=(",", ":"),
            )
        )
        occurrence = _occurrence(
            current_attempt,
            receipt_root_sha256=occurrence_root,
            occurrence_ordinal=0,
            headers=exact_headers,
            rows=raw_rows,
        )
        objects.append(body)
        occurrences.append(occurrence)
        landing = ObservationRouteLandingV2.build(
            observation_sha256=current_attempt.observation_sha256,
            logical_receipt_sha256=logical_receipt,
            route_ordinal=0,
            route_authority_kind="staging_route_contract_v1",
            route_authority_sha256=route.contract_sha256,
            landing_semantic="occurrence_bound",
            conditional_lossless=False,
            alias_target_route_id=None,
            live_snapshot_at=None,
            source_occurrence_sha256s=(occurrence.occurrence_sha256,),
            committed_receipt=committed,
        )
        landings.append(landing)
        observations.append(
            RequestObservationV2.build(
                attempt=current_attempt,
                transport={
                    "transport_kind": "stats_http",
                    "status_code": 200,
                    "effective_status_code": 200,
                },
                started_at=_STARTED,
                finished_at=_STARTED + timedelta(microseconds=1),
                elapsed_ns=1_000,
                lifecycle="selected_terminal",
                outcome="success_nonempty" if raw_rows else "success_empty",
                failure_class=None,
                root_exception_class=None,
                body_disposition="public_parser_input",
                body_object_sha256=body.object_sha256,
                bodyless_evidence_sha256=None,
                result_occurrence_sha256s=[occurrence.occurrence_sha256],
                route_landing_sha256s=[landing.landing_sha256],
                capture_response_receipt_sha256=_sha(f"capture-{call_ordinal}"),
                logical_receipt_sha256=logical_receipt,
            )
        )
    bundle = RawRequestAuthorityBundleV2.build(
        objects=objects,
        observations=observations,
        occurrences=occurrences,
        landings=landings,
    )
    return _Fixture(
        frame=frame,
        readback=CommittedStagingFrameReadbackV2.build(
            committed_receipt=committed,
            frame=frame,
        ),
        bundle=bundle,
    )


def _custom_stats_value_authority(
    endpoint_id: str,
    payload: dict[str, object],
) -> tuple[
    RequestObservationV2,
    tuple[ResultOccurrenceV2, ...],
    bytes,
]:
    route_bundle = staging_route_contract_bundle()
    endpoint_routes = tuple(
        route for route in route_bundle.routes if route.provider_endpoint_id == endpoint_id
    )
    assert endpoint_routes
    route_by_result_name = {route.provider_result_set_name: route for route in endpoint_routes}
    first_route = endpoint_routes[0]
    parameters_by_endpoint: dict[str, dict[str, object]] = {
        "BoxScoreTraditionalV3": {"game_id": "0022400001"},
        "ScheduleLeagueV2": {"season": "2025-26"},
        "ScoreboardV3": {"game_date": "2026-01-01"},
    }
    attempt = RequestAttemptIdentityV2.build(
        semantic_request_sha256=_sha(f"{endpoint_id}-semantic"),
        logical_invocation_sha256=_sha(f"{endpoint_id}-invocation"),
        provider_call_role="primary",
        provider_call_ordinal=0,
        retry_ordinal=0,
        request_ordinal=0,
        source_family="stats",
        endpoint_id=endpoint_id,
        parameters=parameters_by_endpoint[endpoint_id],
        provider_authority_sha256=route_bundle.provider_authority_sha256,
        endpoint_contract_sha256=first_route.endpoint_contract_sha256,
        competition_id="nba",
        competition_identity_sha256=_sha(f"{endpoint_id}-competition"),
        scope_sha256=_sha(f"{endpoint_id}-scope"),
        pagination_sha256=None,
        page_ordinal=None,
        source_sha="1" * 40,
        run_id=101,
        run_attempt=1,
        chain_id="chain",
        lane_id="lane",
    )
    parser_input = json.dumps(payload, separators=(",", ":"))
    body = ParserInputObjectV2.from_parser_input(parser_input)
    derivations = rederive_raw_authority_result_sets(
        source_family="stats",
        endpoint_id=endpoint_id,
        parser_input=parser_input.encode("utf-8"),
        provider_authority_sha256=route_bundle.provider_authority_sha256,
        endpoint_contract_sha256_value=first_route.endpoint_contract_sha256,
    )
    occurrence_values: list[ResultOccurrenceV2] = []
    for ordinal, derivation in enumerate(derivations):
        result = derivation.result_set
        assert result.canonical_index is not None
        route = route_by_result_name[result.name]
        presence = "present" if result.row_count else "present_empty"
        occurrence_values.append(
            ResultOccurrenceV2.build(
                observation_sha256=attempt.observation_sha256,
                occurrence_ordinal=ordinal,
                result_name=result.name,
                duplicate_name_ordinal=derivation.duplicate_name_ordinal,
                provider_result_ordinal=result.provider_index,
                canonical_result_ordinal=result.canonical_index,
                json_path=result.json_path,
                container_kind=result.container_kind,
                presence=presence,
                ordered_headers=derivation.ordered_headers,
                row_count=result.row_count,
                cell_count=result.row_count * len(derivation.ordered_headers),
                node_count=(
                    0 if result.container_kind == "nba_api_result_set" else result.row_count
                ),
                container_count=result.container_count + result.null_count,
                missing_count=result.missing_count,
                null_count=result.null_count,
                parent_state_sha256=result.parent_occurrence_states_sha256,
                output_sha256=result.normalized_output_sha256,
                canonical_route_ids=(route.route_id,),
                committed_staging_receipts=(
                    {"route_id": route.route_id, "receipt_sha256": _sha(route.route_id)},
                ),
                landing_disposition="wide_only",
            )
        )
    observation = RequestObservationV2.build(
        attempt=attempt,
        transport={
            "transport_kind": "stats_http",
            "status_code": 200,
            "effective_status_code": 200,
        },
        started_at=_STARTED,
        finished_at=_STARTED + timedelta(microseconds=1),
        elapsed_ns=1_000,
        lifecycle="selected_terminal",
        outcome=(
            "success_nonempty"
            if any(item.row_count for item in occurrence_values)
            else "success_empty"
        ),
        failure_class=None,
        root_exception_class=None,
        body_disposition="public_parser_input",
        body_object_sha256=body.object_sha256,
        bodyless_evidence_sha256=None,
        result_occurrence_sha256s=tuple(item.occurrence_sha256 for item in occurrence_values),
        route_landing_sha256s=(_sha(f"{endpoint_id}-landing"),),
        capture_response_receipt_sha256=_sha(f"{endpoint_id}-capture"),
        logical_receipt_sha256=_sha(f"{endpoint_id}-logical"),
    )
    return observation, tuple(occurrence_values), parser_input.encode("utf-8")


def _selected_stats_authority_from_payload(
    field_fate: FieldFateStructureV1,
    payload: dict[str, object],
) -> tuple[pl.DataFrame, ConditionalRouteOccurrenceAuthorityV1]:
    snapshot, binding, receipts = _case("stats", fallback=True)
    pending = snapshot.pending_successes[0]
    route = next(
        item
        for item in staging_route_contract_bundle().routes
        if item.endpoint_name == "league_game_log"
    )
    fallback_receipt = next(
        item for item in receipts if "stg_nba_api_lossless_result_cells" in item.result_route_id
    )
    parser_input = json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    )
    body = ParserInputObjectV2.from_parser_input(parser_input)
    derivations = rederive_raw_authority_result_sets(
        source_family="stats",
        endpoint_id=pending.attempt.endpoint_id,
        parser_input=parser_input.encode("utf-8"),
        provider_authority_sha256=pending.attempt.provider_authority_sha256,
        endpoint_contract_sha256_value=pending.attempt.endpoint_contract_sha256,
    )
    template = pending.results[0]
    pending_results = tuple(
        replace(
            template,
            result_set=derivation.result_set,
            duplicate_name_ordinal=derivation.duplicate_name_ordinal,
            ordered_headers=derivation.ordered_headers,
        )
        for derivation in derivations
    )
    snapshot = replace(
        snapshot,
        objects=(body,),
        pending_successes=(
            replace(
                pending,
                body_object=body,
                results=pending_results,
                outcome=(
                    "success_nonempty"
                    if any(item.result_set.row_count for item in pending_results)
                    else "success_empty"
                ),
            ),
        ),
    )
    frame = (
        rederive_raw_authority_stats_fallback(
            endpoint_id=pending.attempt.endpoint_id,
            parser_input=parser_input.encode("utf-8"),
            provider_authority_sha256=pending.attempt.provider_authority_sha256,
            endpoint_contract_sha256_value=pending.attempt.endpoint_contract_sha256,
        )
        .bind_response_receipt(pending.private_receipt_sha256)
        .frame
    )
    validate_lossless_fallback_frame(
        frame,
        expected_response_receipt_sha256=pending.private_receipt_sha256,
    )
    content_sha256 = frame_content_hash(frame)
    fallback_receipt = replace(
        fallback_receipt,
        content_hash=content_sha256,
        persisted_row_count=frame.height,
        persisted_content_sha256=content_sha256,
        persisted_schema_sha256=frame_schema_hash(frame),
    )
    safe_wide_results = rederive_raw_authority_stats_wide_rows(
        endpoint_id=pending.attempt.endpoint_id,
        parser_input=parser_input.encode("utf-8"),
        provider_authority_sha256=pending.attempt.provider_authority_sha256,
        endpoint_contract_sha256_value=pending.attempt.endpoint_contract_sha256,
    )
    wide_candidates = tuple(
        item
        for item in safe_wide_results
        if item.result_set.name == route.provider_result_set_name
        and item.result_set.canonical_index == route.canonical_result_set_ordinal
        and item.ordered_headers == route.provider_columns
    )
    assert len(wide_candidates) in {0, 1}
    wide_frame = (
        raw_authority_module._rebuild_stats_wide_frame(
            route=route,
            result_rows=wide_candidates[0],
            safe_parameters_json=pending.attempt.safe_parameters_json,
        )
        if wide_candidates
        else pl.DataFrame()
    )
    committed = tuple(
        replace(
            item,
            content_hash=frame_content_hash(
                frame if item.result_route_id == fallback_receipt.result_route_id else wide_frame
            ),
            persisted_row_count=(
                frame.height
                if item.result_route_id == fallback_receipt.result_route_id
                else wide_frame.height
            ),
            persisted_content_sha256=frame_content_hash(
                frame if item.result_route_id == fallback_receipt.result_route_id else wide_frame
            ),
            persisted_schema_sha256=frame_schema_hash(
                frame if item.result_route_id == fallback_receipt.result_route_id else wide_frame
            ),
        )
        for item in receipts
    )
    fallback_receipt = next(
        item for item in committed if item.result_route_id == fallback_receipt.result_route_id
    )
    raw_bundle = finalize_raw_request_capture(snapshot, binding, committed)
    readback = CommittedStagingFrameReadbackV2.build(
        committed_receipt=fallback_receipt,
        frame=frame,
    )
    return frame, derive_conditional_route_occurrence_authority(
        structure=field_fate,
        route_id=fallback_receipt.result_route_id,
        raw_bundle=raw_bundle,
        readback=readback,
    )


def _selected_scoreboard_missing_authority(
    field_fate: FieldFateStructureV1,
) -> tuple[pl.DataFrame, ConditionalRouteOccurrenceAuthorityV1]:
    route_bundle = staging_route_contract_bundle()
    routes = tuple(item for item in route_bundle.routes if item.endpoint_name == "scoreboard_v2")
    assert routes
    first_route = routes[0]
    payload = _legacy_payload("ScoreboardV2")
    result_sets = payload["resultSets"]
    assert isinstance(result_sets, list)
    payload["resultSets"] = [item for item in result_sets if item["name"] != "WinProbability"]
    parser_input = json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    )
    body = ParserInputObjectV2.from_parser_input(parser_input)
    attempt = RequestAttemptIdentityV2.build(
        semantic_request_sha256=_sha("scoreboard-missing-semantic"),
        logical_invocation_sha256=_sha("scoreboard-missing-invocation"),
        provider_call_role="primary",
        provider_call_ordinal=0,
        retry_ordinal=0,
        request_ordinal=0,
        source_family="stats",
        endpoint_id=first_route.provider_endpoint_id,
        parameters={"game_date": "2026-08-26"},
        provider_authority_sha256=route_bundle.provider_authority_sha256,
        endpoint_contract_sha256=first_route.endpoint_contract_sha256,
        competition_id="nba",
        competition_identity_sha256=_sha("scoreboard-missing-competition"),
        scope_sha256=_sha("scoreboard-missing-scope"),
        pagination_sha256=None,
        page_ordinal=None,
        source_sha="1" * 40,
        run_id=101,
        run_attempt=1,
        chain_id="chain",
        lane_id="lane",
    )
    derivations = rederive_raw_authority_result_sets(
        source_family="stats",
        endpoint_id=attempt.endpoint_id,
        parser_input=parser_input.encode("utf-8"),
        provider_authority_sha256=attempt.provider_authority_sha256,
        endpoint_contract_sha256_value=attempt.endpoint_contract_sha256,
    )
    assert any(
        item.result_set.name == "WinProbability"
        and item.result_set.provider_index is None
        and item.result_set.missing_count == 1
        for item in derivations
    )
    result_count = 1 + max(
        item.provider_result_set_ordinal
        for item in routes
        if item.provider_result_set_ordinal is not None
    )
    fallback_staging_key = "stg_nba_api_lossless_result_cells"
    fallback_route_id = f"scoreboard_v2:{fallback_staging_key}:{result_count}"
    route_ids = tuple(sorted((*(item.route_id for item in routes), fallback_route_id)))
    logical_receipt_sha256 = _sha("scoreboard-missing-logical-receipt")
    binding = LogicalCallReceiptBinding(
        logical_call_receipt_sha256=logical_receipt_sha256,
        endpoint_name="scoreboard_v2",
        logical_parameters_sha256=attempt.safe_parameters_sha256,
        provider_authority_sha256=attempt.provider_authority_sha256,
        result_route_ids=route_ids,
    )
    private_receipt_sha256 = _sha("scoreboard-missing-capture-response")
    pending = PendingRawRequestSuccessV2(
        private_receipt_sha256=private_receipt_sha256,
        attempt=attempt,
        transport={
            "transport_kind": "stats_http",
            "status_code": 200,
            "effective_status_code": 200,
        },
        started_at=_STARTED,
        finished_at=_STARTED + timedelta(microseconds=1),
        elapsed_ns=1_000,
        outcome="success_nonempty",
        body_disposition="public_parser_input",
        body_object=body,
        results=tuple(
            PendingResultOccurrenceV2(
                result_set=item.result_set,
                duplicate_name_ordinal=item.duplicate_name_ordinal,
                ordered_headers=item.ordered_headers,
            )
            for item in derivations
        ),
        logical_receipt_sha256=logical_receipt_sha256,
        aggregate_route_ids=route_ids,
    )
    frame = (
        rederive_raw_authority_stats_fallback(
            endpoint_id=attempt.endpoint_id,
            parser_input=parser_input.encode("utf-8"),
            provider_authority_sha256=attempt.provider_authority_sha256,
            endpoint_contract_sha256_value=attempt.endpoint_contract_sha256,
        )
        .bind_response_receipt(private_receipt_sha256)
        .frame
    )
    validate_lossless_fallback_frame(
        frame,
        expected_response_receipt_sha256=private_receipt_sha256,
    )
    logical_parameters_sha256 = binding.logical_parameters_sha256

    def receipt(
        *,
        route_id: str,
        staging_key: str,
        row_count: int,
        content_hash: str,
        schema_hash: str,
    ) -> CommittedStagingChunkReceiptV2:
        return CommittedStagingChunkReceiptV2(
            chunk_id=f"chunk:{_sha(route_id)[:16]}",
            staging_key=staging_key,
            canonical_frame_format=CANONICAL_FRAME_FORMAT,
            frame_content_hash_contract=FRAME_CONTENT_HASH_CONTRACT,
            frame_schema_hash_contract=FRAME_SCHEMA_HASH_CONTRACT,
            content_hash=content_hash,
            persisted_row_count=row_count,
            persisted_content_sha256=content_hash,
            persisted_schema_sha256=schema_hash,
            logical_call_receipt_sha256=logical_receipt_sha256,
            provider_authority_sha256=attempt.provider_authority_sha256,
            logical_parameters_sha256=logical_parameters_sha256,
            result_route_id=route_id,
        )

    safe_wide_results = rederive_raw_authority_stats_wide_rows(
        endpoint_id=attempt.endpoint_id,
        parser_input=parser_input.encode("utf-8"),
        provider_authority_sha256=attempt.provider_authority_sha256,
        endpoint_contract_sha256_value=attempt.endpoint_contract_sha256,
    )
    wide_frames_by_route: dict[str, pl.DataFrame] = {}
    for route in routes:
        wide_candidates = tuple(
            item
            for item in safe_wide_results
            if item.result_set.name == route.provider_result_set_name
            and item.result_set.canonical_index == route.canonical_result_set_ordinal
            and item.ordered_headers == route.provider_columns
        )
        assert len(wide_candidates) in {0, 1}
        wide_frames_by_route[route.route_id] = (
            raw_authority_module._rebuild_stats_wide_frame(
                route=route,
                result_rows=wide_candidates[0],
                safe_parameters_json=attempt.safe_parameters_json,
            )
            if wide_candidates
            else pl.DataFrame()
        )
    committed = tuple(
        sorted(
            (
                *(
                    receipt(
                        route_id=route.route_id,
                        staging_key=route.staging_key,
                        row_count=wide_frames_by_route[route.route_id].height,
                        content_hash=frame_content_hash(wide_frames_by_route[route.route_id]),
                        schema_hash=frame_schema_hash(wide_frames_by_route[route.route_id]),
                    )
                    for route in routes
                ),
                receipt(
                    route_id=fallback_route_id,
                    staging_key=fallback_staging_key,
                    row_count=frame.height,
                    content_hash=frame_content_hash(frame),
                    schema_hash=frame_schema_hash(frame),
                ),
            ),
            key=lambda item: item.result_route_id,
        )
    )
    snapshot = RawRequestCaptureSnapshotV2(
        objects=(body,),
        observations=(),
        pending_successes=(pending,),
        issues=(),
    )
    raw_bundle = finalize_raw_request_capture(snapshot, binding, committed)
    fallback_receipt = next(item for item in committed if item.result_route_id == fallback_route_id)
    readback = CommittedStagingFrameReadbackV2.build(
        committed_receipt=fallback_receipt,
        frame=frame,
    )
    return frame, derive_conditional_route_occurrence_authority(
        structure=field_fate,
        route_id=fallback_route_id,
        raw_bundle=raw_bundle,
        readback=readback,
    )


def _live_conditional_authority_from_payload(
    field_fate: FieldFateStructureV1,
    payload: dict[str, object],
) -> tuple[pl.DataFrame, ConditionalRouteOccurrenceAuthorityV1]:
    snapshot, binding, receipts = _case("live")
    route_bundle = staging_route_contract_bundle()
    route = next(item for item in route_bundle.routes if item.endpoint_name == "live_score_board")
    contract = pinned_live_contracts()[route.provider_endpoint_id]
    parser_input = json.dumps(payload, separators=(",", ":"))
    body = ParserInputObjectV2.from_parser_input(parser_input)
    pending = snapshot.pending_successes[0]
    derivations = rederive_raw_authority_result_sets(
        source_family="live",
        endpoint_id=pending.attempt.endpoint_id,
        parser_input=parser_input.encode("utf-8"),
        provider_authority_sha256=pending.attempt.provider_authority_sha256,
        endpoint_contract_sha256_value=pending.attempt.endpoint_contract_sha256,
    )
    pending = replace(
        pending,
        body_object=body,
        results=tuple(
            replace(
                pending_result,
                result_set=derivation.result_set,
                duplicate_name_ordinal=derivation.duplicate_name_ordinal,
                ordered_headers=derivation.ordered_headers,
            )
            for pending_result, derivation in zip(
                pending.results,
                derivations,
                strict=True,
            )
        ),
    )
    snapshot = replace(snapshot, objects=(body,), pending_successes=(pending,))
    landing = (
        build_live_lossless_landing(
            payload,
            contract=contract,
            endpoint_slug=route.provider_endpoint_slug,
            request_parameters={},
            provider_authority_sha256=route_bundle.provider_authority_sha256,
            endpoint_contract_sha256=route.endpoint_contract_sha256,
            result_set_receipts=tuple(item.result_set for item in pending.results),
            anomaly_codes=("additive_field",),
        )
        .bind_response_receipt(pending.private_receipt_sha256)
        .bind_snapshot(_STARTED)
    )
    frame = landing.frame
    route_frames = rederive_raw_authority_route_frames(
        source_family="live",
        endpoint_name=binding.endpoint_name,
        endpoint_id=pending.attempt.endpoint_id,
        selected_route_ids=binding.result_route_ids,
        parser_input=parser_input.encode("utf-8"),
        safe_parameters_json=pending.attempt.safe_parameters_json,
        provider_authority_sha256=pending.attempt.provider_authority_sha256,
        endpoint_contract_sha256_value=pending.attempt.endpoint_contract_sha256,
        capture_response_receipt_sha256=pending.private_receipt_sha256,
        live_snapshot_at=_STARTED,
    )
    frame_by_route = {item.route_id: item for item in route_frames}
    conditional_route_id = next(
        item.result_route_id
        for item in receipts
        if "stg_nba_api_live_lossless_nodes" in item.result_route_id
    )
    frame = frame_by_route[conditional_route_id].frame
    committed = tuple(
        replace(
            item,
            content_hash=frame_by_route[item.result_route_id].frame_content_sha256,
            persisted_row_count=frame_by_route[item.result_route_id].row_count,
            persisted_content_sha256=frame_by_route[item.result_route_id].frame_content_sha256,
            persisted_schema_sha256=frame_by_route[item.result_route_id].frame_schema_sha256,
        )
        for item in receipts
    )
    conditional_receipt = next(
        item for item in committed if "stg_nba_api_live_lossless_nodes" in item.result_route_id
    )
    fixed_route_ids = tuple(
        item.route_id
        for item in sorted(
            (item for item in route_bundle.routes if item.endpoint_name == binding.endpoint_name),
            key=lambda item: item.ordinal,
        )
    )
    conditional_route_ids = tuple(
        route_id for route_id in binding.result_route_ids if route_id not in fixed_route_ids
    )
    live_plan = LiveSnapshotPlanAuthorityV2.build(
        sealed_plan_bytes=b'{"kind":"typed-field-live-plan-fixture-v2"}',
        attempt=pending.attempt,
        route_ids=(*fixed_route_ids, *conditional_route_ids),
        live_snapshot_at=_STARTED,
    )
    raw_bundle = finalize_raw_request_capture(
        snapshot,
        binding,
        committed,
        live_plan_authority=live_plan,
        expected_live_plan_authority_sha256=live_plan.authority_sha256,
    )
    readback = CommittedStagingFrameReadbackV2.build(
        committed_receipt=conditional_receipt,
        frame=frame,
    )
    return frame, derive_conditional_route_occurrence_authority(
        structure=field_fate,
        route_id=conditional_receipt.result_route_id,
        raw_bundle=raw_bundle,
        readback=readback,
    )


def _typed_live_conditional_authority(
    field_fate: FieldFateStructureV1,
) -> tuple[str, pl.DataFrame, ConditionalRouteOccurrenceAuthorityV1]:
    route_bundle = staging_route_contract_bundle()
    route = next(item for item in route_bundle.routes if item.endpoint_name == "live_score_board")
    contract = pinned_live_contracts()[route.provider_endpoint_id]
    frame, authority = _live_conditional_authority_from_payload(
        field_fate,
        _complete_endpoint_payload(contract),
    )
    return authority.route_id, frame, authority


def _live_missing_child_authority(
    field_fate: FieldFateStructureV1,
) -> tuple[pl.DataFrame, ConditionalRouteOccurrenceAuthorityV1]:
    route_bundle = staging_route_contract_bundle()
    route = next(item for item in route_bundle.routes if item.endpoint_name == "live_score_board")
    contract = pinned_live_contracts()[route.provider_endpoint_id]
    payload = _complete_endpoint_payload(contract)
    scoreboard = payload["scoreboard"]
    assert isinstance(scoreboard, dict)
    games = scoreboard["games"]
    assert isinstance(games, list) and games and isinstance(games[0], dict)
    games[0].pop("gameLeaders")
    return _live_conditional_authority_from_payload(field_fate, payload)


def _live_mixed_absent_authority(
    field_fate: FieldFateStructureV1,
) -> tuple[pl.DataFrame, ConditionalRouteOccurrenceAuthorityV1]:
    route_bundle = staging_route_contract_bundle()
    route = next(item for item in route_bundle.routes if item.endpoint_name == "live_score_board")
    contract = pinned_live_contracts()[route.provider_endpoint_id]
    payload = _complete_endpoint_payload(contract)
    scoreboard = payload["scoreboard"]
    assert isinstance(scoreboard, dict)
    games = scoreboard["games"]
    assert isinstance(games, list) and games and isinstance(games[0], dict)
    missing_game = copy.deepcopy(games[0])
    null_game = copy.deepcopy(games[0])
    missing_game.pop("gameLeaders")
    null_game["gameLeaders"] = None
    scoreboard["games"] = [missing_game, null_game]
    return _live_conditional_authority_from_payload(field_fate, payload)


def _live_decoder_authority(
    authority: ConditionalRouteOccurrenceAuthorityV1,
    result_name: str,
) -> tuple[RequestObservationV2, ResultOccurrenceV2, bytes]:
    selected = authority.raw_bundle.selected_terminal_occurrences_for_route(
        authority.route_id,
        authority.readback.committed_receipt.receipt_root_sha256,
    )
    observation, occurrence = next(item for item in selected if item[1].result_name == result_name)
    body = next(
        item
        for item in authority.raw_bundle.objects
        if item.object_sha256 == observation.body_object_sha256
    )
    return (
        observation,
        occurrence,
        receipt_module.decode_parser_input_object(body),
    )


def _live_plan_bindings(
    bundle: RawRequestAuthorityBundleV2,
) -> tuple[tuple[LiveSnapshotPlanAuthorityV2, str], ...]:
    bindings: list[tuple[LiveSnapshotPlanAuthorityV2, str]] = []
    for observation in bundle.observations:
        if (
            observation.lifecycle != "selected_terminal"
            or observation.attempt.source_family != "live"
        ):
            continue
        landings = tuple(
            item
            for item in bundle.landings
            if item.observation_sha256 == observation.attempt.observation_sha256
        )
        snapshots = {item.live_snapshot_at for item in landings}
        assert len(snapshots) == 1 and None not in snapshots
        plan = LiveSnapshotPlanAuthorityV2.build(
            sealed_plan_bytes=(
                b'{"kind":"typed-field-live-plan-fixture-v2","observation":"'
                + observation.attempt.observation_sha256.encode("ascii")
                + b'"}'
            ),
            attempt=observation.attempt,
            route_ids=tuple(item.route_id for item in landings),
            live_snapshot_at=next(iter(snapshots)),  # type: ignore[arg-type]
        )
        bindings.append((plan, plan.authority_sha256))
    return tuple(bindings)


def _build(
    field_fate: FieldFateStructureV1,
    fixture: _Fixture,
    *,
    limits: ValueBudgetLimits | None = None,
) -> RouteFieldLandingReceiptV2:
    return RouteFieldLandingReceiptV2.build_from_authorities(
        readback=fixture.readback,
        raw_bundle=fixture.bundle,
        field_fate=field_fate,
        live_plan_bindings=_live_plan_bindings(fixture.bundle),
        _value_limits=limits,
    )


@pytest.fixture(scope="module")
def receipt_payload(field_fate: FieldFateStructureV1) -> dict[str, object]:
    return _build(field_fate, _fixture()).to_dict()


def _reseal_route_payload(payload: dict[str, object]) -> None:
    identity = {
        key: value
        for key, value in payload.items()
        if key
        not in {
            "field_authorities",
            "occurrence_authorities",
            "selected_occurrence_authorities",
            "value_receipts",
            "conditional_row_receipts",
            "landing_receipt_sha256",
        }
    }
    payload["landing_receipt_sha256"] = canonical_sha256(identity)


def _reseal_conditional_row_payload(payload: dict[str, object]) -> None:
    authority = payload["row_authority"]
    cells = payload["cells"]
    assert isinstance(authority, dict)
    assert isinstance(cells, list)
    authority["authority_sha256"] = canonical_sha256(
        {key: value for key, value in authority.items() if key != "authority_sha256"}
    )
    payload["row_authority_sha256"] = authority["authority_sha256"]
    for cell in cells:
        assert isinstance(cell, dict)
        cell["row_authority_sha256"] = authority["authority_sha256"]
        cell["cell_receipt_sha256"] = canonical_sha256(
            {key: value for key, value in cell.items() if key != "cell_receipt_sha256"}
        )
    payload["cells_sha256"] = canonical_sha256(cells)
    payload["value_receipt_sha256"] = canonical_sha256(
        {
            key: value
            for key, value in payload.items()
            if key not in {"row_authority", "cells", "value_receipt_sha256"}
        }
    )


def _reseal_ordinary_value_payload(payload: dict[str, object]) -> None:
    cells = payload["cells"]
    assert isinstance(cells, list)
    for cell in cells:
        assert isinstance(cell, dict)
        cell["cell_receipt_sha256"] = canonical_sha256(
            {key: value for key, value in cell.items() if key != "cell_receipt_sha256"}
        )
    payload["cells_sha256"] = canonical_sha256(cells)
    payload["value_receipt_sha256"] = canonical_sha256(
        {
            key: value
            for key, value in payload.items()
            if key not in {"occurrence_authority", "cells", "value_receipt_sha256"}
        }
    )


def _reseal_conditional_route_payload(payload: dict[str, object]) -> None:
    rows = payload["conditional_row_receipts"]
    assert isinstance(rows, list)
    payload["conditional_rows_sha256"] = canonical_sha256(rows)
    _reseal_route_payload(payload)


def _reseal_selected_occurrence_payload(payload: dict[str, object]) -> None:
    summaries = payload["selected_occurrence_authorities"]
    assert isinstance(summaries, list)
    for summary in summaries:
        assert isinstance(summary, dict)
        summary["authority_sha256"] = canonical_sha256(
            {key: value for key, value in summary.items() if key != "authority_sha256"}
        )
    payload["selected_occurrences_sha256"] = canonical_sha256(summaries)
    _reseal_route_payload(payload)


def test_build_parse_and_strict_production_replay_are_exact(
    field_fate: FieldFateStructureV1,
) -> None:
    fixture = _fixture()
    receipt = _build(field_fate, fixture)

    assert receipt.schema_version == 2
    assert receipt.row_count == 2
    assert receipt.field_count == 5
    assert receipt.cell_count == 10
    assert receipt.source_family == "stats"
    assert receipt.decoder_kind == "stats_result_set_rows_v1"
    assert tuple(item.storage_ordinal for item in receipt.field_authorities) == tuple(range(5))
    assert tuple(item.source_header_ordinals for item in receipt.field_authorities) == (
        (0,),
        (1,),
        (2,),
        (3,),
        (4,),
    )
    encoded = receipt.to_canonical_bytes()
    assert RouteFieldLandingReceiptV2.from_canonical_bytes(encoded) == receipt
    assert (
        validate_route_field_landing_receipt_replay(
            encoded,
            readback=fixture.readback,
            raw_bundle=fixture.bundle,
            field_fate=field_fate,
        )
        == receipt
    )


def test_source_occurrence_summary_rederives_opaque_raw_identity(
    receipt_payload: dict[str, object],
) -> None:
    payload = copy.deepcopy(receipt_payload)
    summaries = payload["selected_occurrence_authorities"]
    assert isinstance(summaries, list) and len(summaries) == 1
    summary = summaries[0]
    assert isinstance(summary, dict)
    summary["node_count"] = 1
    _reseal_selected_occurrence_payload(payload)

    with pytest.raises(
        TypedFieldValueReceiptError,
        match="source occurrence identity differs from its inspectable payload",
    ):
        RouteFieldLandingReceiptV2.from_canonical_bytes(canonical_json_bytes(payload))


def test_ordinary_cell_cannot_strip_its_exact_source_after_recursive_reseal(
    receipt_payload: dict[str, object],
) -> None:
    payload = copy.deepcopy(receipt_payload)
    values = payload["value_receipts"]
    assert isinstance(values, list) and values
    value = values[0]
    assert isinstance(value, dict)
    cells = value["cells"]
    assert isinstance(cells, list) and cells
    cell = cells[0]
    assert isinstance(cell, dict)
    bindings = cell["source_occurrence_sha256s"]
    assert isinstance(bindings, list) and bindings
    cell["source_occurrence_sha256s"] = []
    cell["value_authority"] = "storage_readback_only"
    source_count = payload["source_verified_cell_count"]
    readback_count = payload["storage_readback_only_cell_count"]
    assert isinstance(source_count, int) and isinstance(readback_count, int)
    payload["source_verified_cell_count"] = source_count - 1
    payload["storage_readback_only_cell_count"] = readback_count + 1
    _reseal_ordinary_value_payload(value)
    payload["values_sha256"] = canonical_sha256(values)
    _reseal_route_payload(payload)

    with pytest.raises(
        TypedFieldValueReceiptError,
        match="ordinary cell source authority differs from its field",
    ):
        RouteFieldLandingReceiptV2.from_canonical_bytes(canonical_json_bytes(payload))


def test_raw_parser_values_are_compared_to_committed_arrow_values(
    field_fate: FieldFateStructureV1,
) -> None:
    hostile_rows = [
        ["00", 1, "1946", "2026", "AAA"],
        ["00", 999, "1949", "2026", "BBB"],
    ]
    with pytest.raises(ValueError, match="fixed route landing receipt differs"):
        _fixture(raw_rows=hostile_rows)


@pytest.mark.parametrize(
    "changes",
    (
        {"presence": "present_empty", "row_count": 0, "cell_count": 0},
        {"ordered_headers": [*_RAW_HEADERS, "EXTRA"], "cell_count": 12},
        {"node_count": 1},
        {"container_count": 2},
        {"missing_count": 1},
        {"null_count": 1},
        {"parent_state_sha256": _sha("hostile-parent-state")},
        {"output_sha256": _sha("hostile-output")},
    ),
)
def test_rebuilt_raw_occurrence_summary_fields_must_match_parser_body(
    changes: dict[str, object],
) -> None:
    fixture = _fixture()
    observation = fixture.bundle.observations[0]
    original = fixture.bundle.occurrences[0]
    values: dict[str, object] = {
        "observation_sha256": original.observation_sha256,
        "occurrence_ordinal": original.occurrence_ordinal,
        "result_name": original.result_name,
        "duplicate_name_ordinal": original.duplicate_name_ordinal,
        "provider_result_ordinal": original.provider_result_ordinal,
        "canonical_result_ordinal": original.canonical_result_ordinal,
        "json_path": original.json_path,
        "container_kind": original.container_kind,
        "presence": original.presence,
        "ordered_headers": list(original.ordered_headers()),
        "row_count": original.row_count,
        "cell_count": original.cell_count,
        "node_count": original.node_count,
        "container_count": original.container_count,
        "missing_count": original.missing_count,
        "null_count": original.null_count,
        "parent_state_sha256": original.parent_state_sha256,
        "output_sha256": original.output_sha256,
        "canonical_route_ids": original.canonical_route_ids(),
        "committed_staging_receipts": tuple(
            {
                "route_id": route_id,
                "receipt_sha256": receipt_sha256,
            }
            for route_id, receipt_sha256 in original.committed_staging_receipts_by_route().items()
        ),
        "landing_disposition": original.landing_disposition,
    }
    values.update(changes)
    hostile = ResultOccurrenceV2.build(**values)  # type: ignore[arg-type]
    body = fixture.bundle.objects[0]

    with pytest.raises(
        TypedFieldValueReceiptError,
        match="raw provider result derivation differs from occurrence authority",
    ):
        receipt_module._assert_rederived_occurrence(
            observation=observation,
            occurrence=hostile,
            parser_input=receipt_module.decode_parser_input_object(body),
        )


@pytest.mark.parametrize(
    ("endpoint_id", "payload"),
    (
        ("BoxScoreTraditionalV3", _traditional_payload()),
        ("ScheduleLeagueV2", _schedule_payload("ScheduleLeagueV2")),
        ("ScoreboardV3", _scoreboard_payload()),
    ),
)
def test_ordinary_custom_nested_stats_values_use_the_independent_decoder(
    endpoint_id: str,
    payload: dict[str, object],
) -> None:
    observation, occurrences, parser_input = _custom_stats_value_authority(endpoint_id, payload)

    decoded_rows = tuple(
        receipt_module._stats_rows_from_independent_decoder(
            observation=observation,
            occurrence=occurrence,
            parser_input=parser_input,
        )
        for occurrence in occurrences
    )

    assert len(decoded_rows) == len(occurrences)
    assert all(
        decoded.ordered_headers == occurrence.ordered_headers()
        and len(decoded.values) == occurrence.row_count
        for decoded, occurrence in zip(decoded_rows, occurrences, strict=True)
    )
    assert any(decoded.values for decoded in decoded_rows)


def test_ordinary_reordered_multi_result_uses_canonical_source_ordinal(
    field_fate: FieldFateStructureV1,
) -> None:
    routes = tuple(
        route
        for route in staging_route_contract_bundle().routes
        if route.provider_endpoint_id == "BoxScoreAdvancedV2"
    )
    route_by_name = {route.provider_result_set_name: route for route in routes}
    player_route = route_by_name["PlayerStats"]
    team_route = route_by_name["TeamStats"]
    player_row = [f"player-{ordinal}" for ordinal in range(len(player_route.provider_columns))]
    team_row = [f"team-{ordinal}" for ordinal in range(len(team_route.provider_columns))]
    parser_payload = {
        "resultSets": [
            {
                "name": "TeamStats",
                "headers": list(team_route.provider_columns),
                "rowSet": [team_row],
            },
            {
                "name": "PlayerStats",
                "headers": list(player_route.provider_columns),
                "rowSet": [player_row],
            },
        ]
    }
    parser_input = json.dumps(parser_payload, separators=(",", ":"))
    frame = pl.DataFrame(
        {
            storage: [value]
            for storage, value in zip(
                team_route.storage_columns,
                team_row,
                strict=True,
            )
        }
    )
    attempt = RequestAttemptIdentityV2.build(
        semantic_request_sha256=_sha("advanced-semantic"),
        logical_invocation_sha256=_sha("advanced-invocation"),
        provider_call_role="primary",
        provider_call_ordinal=0,
        retry_ordinal=0,
        request_ordinal=0,
        source_family="stats",
        endpoint_id="BoxScoreAdvancedV2",
        parameters={"game_id": "0022400001"},
        provider_authority_sha256=team_route.provider_authority_sha256,
        endpoint_contract_sha256=team_route.endpoint_contract_sha256,
        competition_id="nba",
        competition_identity_sha256=_sha("advanced-competition"),
        scope_sha256=_sha("advanced-scope"),
        pagination_sha256=None,
        page_ordinal=None,
        source_sha="1" * 40,
        run_id=101,
        run_attempt=1,
        chain_id="chain",
        lane_id="lane",
    )
    logical_receipt = _sha("advanced-logical")
    content_sha256 = frame_content_hash(frame)
    committed = CommittedStagingChunkReceiptV2(
        chunk_id="chunk-advanced-team",
        staging_key=team_route.staging_key,
        canonical_frame_format=CANONICAL_FRAME_FORMAT,
        frame_content_hash_contract=FRAME_CONTENT_HASH_CONTRACT,
        frame_schema_hash_contract=FRAME_SCHEMA_HASH_CONTRACT,
        content_hash=content_sha256,
        persisted_row_count=frame.height,
        persisted_content_sha256=content_sha256,
        persisted_schema_sha256=frame_schema_hash(frame),
        logical_call_receipt_sha256=logical_receipt,
        provider_authority_sha256=attempt.provider_authority_sha256,
        logical_parameters_sha256=attempt.safe_parameters_sha256,
        result_route_id=team_route.route_id,
    )
    player_frame = pl.DataFrame(
        {
            storage: [value]
            for storage, value in zip(
                player_route.storage_columns,
                player_row,
                strict=True,
            )
        }
    )
    player_content_sha256 = frame_content_hash(player_frame)
    player_committed = CommittedStagingChunkReceiptV2(
        chunk_id="chunk-advanced-player",
        staging_key=player_route.staging_key,
        canonical_frame_format=CANONICAL_FRAME_FORMAT,
        frame_content_hash_contract=FRAME_CONTENT_HASH_CONTRACT,
        frame_schema_hash_contract=FRAME_SCHEMA_HASH_CONTRACT,
        content_hash=player_content_sha256,
        persisted_row_count=player_frame.height,
        persisted_content_sha256=player_content_sha256,
        persisted_schema_sha256=frame_schema_hash(player_frame),
        logical_call_receipt_sha256=logical_receipt,
        provider_authority_sha256=attempt.provider_authority_sha256,
        logical_parameters_sha256=attempt.safe_parameters_sha256,
        result_route_id=player_route.route_id,
    )
    derivations = rederive_raw_authority_result_sets(
        source_family="stats",
        endpoint_id=attempt.endpoint_id,
        parser_input=parser_input.encode("utf-8"),
        provider_authority_sha256=attempt.provider_authority_sha256,
        endpoint_contract_sha256_value=attempt.endpoint_contract_sha256,
    )
    occurrences: list[ResultOccurrenceV2] = []
    for occurrence_ordinal, derivation in enumerate(derivations):
        result = derivation.result_set
        route = route_by_name[result.name]
        receipt_sha256 = (
            committed.receipt_root_sha256
            if route.route_id == team_route.route_id
            else player_committed.receipt_root_sha256
        )
        occurrences.append(
            ResultOccurrenceV2.build(
                observation_sha256=attempt.observation_sha256,
                occurrence_ordinal=occurrence_ordinal,
                result_name=result.name,
                duplicate_name_ordinal=derivation.duplicate_name_ordinal,
                provider_result_ordinal=result.provider_index,
                canonical_result_ordinal=result.canonical_index,
                json_path=None,
                container_kind="nba_api_result_set",
                presence="present",
                ordered_headers=derivation.ordered_headers,
                row_count=result.row_count,
                cell_count=result.row_count * len(derivation.ordered_headers),
                node_count=0,
                container_count=result.container_count,
                missing_count=result.missing_count,
                null_count=result.null_count,
                parent_state_sha256=result.parent_occurrence_states_sha256,
                output_sha256=result.normalized_output_sha256,
                canonical_route_ids=(route.route_id,),
                committed_staging_receipts=(
                    {"route_id": route.route_id, "receipt_sha256": receipt_sha256},
                ),
                landing_disposition="wide_only",
            )
        )
    body = ParserInputObjectV2.from_parser_input(parser_input)
    occurrence_by_route = {
        occurrence.canonical_route_ids()[0]: occurrence for occurrence in occurrences
    }
    committed_by_route = {
        team_route.route_id: committed,
        player_route.route_id: player_committed,
    }
    landings = tuple(
        ObservationRouteLandingV2.build(
            observation_sha256=attempt.observation_sha256,
            logical_receipt_sha256=logical_receipt,
            route_ordinal=route_ordinal,
            route_authority_kind="staging_route_contract_v1",
            route_authority_sha256=route.contract_sha256,
            landing_semantic="occurrence_bound",
            conditional_lossless=False,
            alias_target_route_id=None,
            live_snapshot_at=None,
            source_occurrence_sha256s=(occurrence_by_route[route.route_id].occurrence_sha256,),
            committed_receipt=committed_by_route[route.route_id],
        )
        for route_ordinal, route in enumerate(sorted(routes, key=lambda item: item.ordinal))
    )
    observation = RequestObservationV2.build(
        attempt=attempt,
        transport={
            "transport_kind": "stats_http",
            "status_code": 200,
            "effective_status_code": 200,
        },
        started_at=_STARTED,
        finished_at=_STARTED + timedelta(microseconds=1),
        elapsed_ns=1_000,
        lifecycle="selected_terminal",
        outcome="success_nonempty",
        failure_class=None,
        root_exception_class=None,
        body_disposition="public_parser_input",
        body_object_sha256=body.object_sha256,
        bodyless_evidence_sha256=None,
        result_occurrence_sha256s=tuple(occurrence.occurrence_sha256 for occurrence in occurrences),
        route_landing_sha256s=tuple(landing.landing_sha256 for landing in landings),
        capture_response_receipt_sha256=_sha("advanced-capture"),
        logical_receipt_sha256=logical_receipt,
    )
    bundle = RawRequestAuthorityBundleV2.build(
        objects=(body,),
        observations=(observation,),
        occurrences=tuple(occurrences),
        landings=landings,
    )
    receipt = RouteFieldLandingReceiptV2.build_from_authorities(
        readback=CommittedStagingFrameReadbackV2.build(
            committed_receipt=committed,
            frame=frame,
        ),
        raw_bundle=bundle,
        field_fate=field_fate,
    )

    assert receipt.route_id == team_route.route_id
    assert receipt.selected_occurrence_count == 1
    summary = receipt.selected_occurrence_authorities[0]
    assert summary.provider_result_ordinal == 0
    assert summary.canonical_result_ordinal == 1
    assert all(
        cell.value_authority == "source_verified"
        for values in receipt.value_receipts
        for cell in values.cells
    )
    arrow_table = frame.to_arrow()
    assert all(
        compare_canonical_arrow_values(
            cell.canonical_value,
            canonical_arrow_scalar(
                team_row[ordinal],
                arrow_table.column(ordinal).type,
            ),
        )
        for ordinal, cell in enumerate(receipt.value_receipts[0].cells)
    )


def test_caller_projected_storage_rows_are_not_an_authority(
    field_fate: FieldFateStructureV1,
) -> None:
    assert field_fate is not None
    parameters = inspect.signature(RouteFieldLandingReceiptV2.build_from_authorities).parameters
    assert "decoded_occurrence_rows" not in parameters


def test_static_values_are_reconstructed_by_the_independent_decoder(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    snapshot, binding, receipts = _case("static")
    pending = snapshot.pending_successes[0]
    derivations = rederive_raw_authority_result_sets(
        source_family="static",
        endpoint_id=pending.attempt.endpoint_id,
        parser_input=None,
        provider_authority_sha256=pending.attempt.provider_authority_sha256,
        endpoint_contract_sha256_value=pending.attempt.endpoint_contract_sha256,
    )
    pending = replace(
        pending,
        results=tuple(
            PendingResultOccurrenceV2(
                result_set=item.result_set,
                duplicate_name_ordinal=item.duplicate_name_ordinal,
                ordered_headers=item.ordered_headers,
            )
            for item in derivations
        ),
    )
    snapshot = replace(snapshot, pending_successes=(pending,))
    committed = replace(
        receipts[0],
        persisted_row_count=derivations[0].result_set.row_count,
    )
    bundle = finalize_raw_request_capture(snapshot, binding, (committed,))
    observation = bundle.observations[0]
    occurrence = bundle.occurrences[0]
    packet = fetch_static_packet(observation.attempt.endpoint_id)
    expected_rows = tuple(tuple(row) for row in packet.frame.rows())

    calls = 0
    exact_decoder = receipt_module.decode_static_value_response

    def decode(*args: object, **kwargs: object):
        nonlocal calls
        calls += 1
        return exact_decoder(*args, **kwargs)  # type: ignore[arg-type]

    monkeypatch.setattr(receipt_module, "decode_static_value_response", decode)
    decoded = receipt_module._decoded_provider_rows(
        bundle=bundle,
        observation=observation,
        occurrence=occurrence,
    )
    assert calls == 1
    assert decoded.ordered_headers == occurrence.ordered_headers()
    assert decoded.values == expected_rows
    assert len(decoded.records) == occurrence.row_count

    mutated_packet = replace(
        packet,
        frame=packet.frame.with_columns(
            pl.when(pl.int_range(pl.len()) == 0)
            .then(pl.lit("__forged_static_value__"))
            .otherwise(pl.col("full_name"))
            .alias("full_name")
        ),
    )
    monkeypatch.setattr(receipt_module, "fetch_static_packet", lambda _dataset_id: mutated_packet)
    with pytest.raises(
        TypedFieldValueReceiptError,
        match="independently decoded|differ from raw authority",
    ):
        receipt_module._decoded_provider_rows(
            bundle=bundle,
            observation=observation,
            occurrence=occurrence,
        )


@pytest.mark.parametrize(
    ("factory", "expected_shape"),
    (
        (_cached_selected_stats_conditional_authority, "selected_result_bound"),
        (_cached_body_node_conditional_authority, "body_node_bound"),
        (_cached_hybrid_stats_conditional_authority, "hybrid_result_body_bound"),
        (_cached_live_conditional_authority, "live_lossless_bound"),
    ),
)
def test_conditional_shapes_have_exact_row_partitions_and_round_trip(
    field_fate: FieldFateStructureV1,
    factory: object,
    expected_shape: str,
) -> None:
    route_id, frame, authority = factory(field_fate)  # type: ignore[operator]
    assert authority.route_id == route_id
    assert authority.source_shape == expected_shape
    receipt = RouteFieldLandingReceiptV2.build_from_authorities(
        readback=authority.readback,
        raw_bundle=authority.raw_bundle,
        field_fate=field_fate,
        conditional_authority=authority,
        live_plan_bindings=_live_plan_bindings(authority.raw_bundle),
    )

    assert receipt.source_shape == expected_shape
    assert receipt.conditional_authority_sha256 == authority.authority_sha256
    assert receipt.occurrence_partition_count == 0
    assert receipt.occurrence_authorities == ()
    assert receipt.value_receipts == ()
    assert len(receipt.conditional_row_receipts) == frame.height
    assert tuple(
        item.row_authority.row_order_ordinal for item in receipt.conditional_row_receipts
    ) == tuple(range(frame.height))
    assert all(len(item.cells) == frame.width for item in receipt.conditional_row_receipts)
    encoded = receipt.to_canonical_bytes()
    assert RouteFieldLandingReceiptV2.from_canonical_bytes(encoded) == receipt
    assert (
        validate_route_field_landing_receipt_replay(
            encoded,
            readback=authority.readback,
            raw_bundle=authority.raw_bundle,
            field_fate=field_fate,
            conditional_authority=authority,
            live_plan_bindings=_live_plan_bindings(authority.raw_bundle),
        )
        == receipt
    )


def test_hybrid_unknown_stats_partition_binds_result_and_body_sources_exactly(
    field_fate: FieldFateStructureV1,
) -> None:
    _route_id, frame, authority = _cached_hybrid_stats_conditional_authority(field_fate)
    receipt = RouteFieldLandingReceiptV2.build_from_authorities(
        readback=authority.readback,
        raw_bundle=authority.raw_bundle,
        field_fate=field_fate,
        conditional_authority=authority,
    )
    selected_rows = tuple(
        row
        for row in receipt.conditional_row_receipts
        if row.row_authority.source_occurrence_sha256 is not None
    )
    body_rows = tuple(
        row
        for row in receipt.conditional_row_receipts
        if row.row_authority.source_occurrence_sha256 is None
    )

    assert receipt.source_shape == "hybrid_result_body_bound"
    assert len(selected_rows) == 6
    assert len(body_rows) == frame.height - len(selected_rows) == 19
    assert {row.row_authority.record_kind for row in selected_rows} == {
        "result_set",
        "header",
        "row",
        "cell",
    }
    assert {row.row_authority.record_kind for row in body_rows} == {
        "response",
        "json_node",
    }
    assert all(row.row_authority.body_object_sha256 is None for row in selected_rows)
    assert all(row.row_authority.body_object_sha256 is not None for row in body_rows)
    assert all(
        row.row_authority.observed_expected_result_set_count == 0
        and row.row_authority.observed_provider_result_set_count == 2
        and row.row_authority.observed_reason_codes == ("unknown_dynamic_response",)
        for row in selected_rows
    )
    assert all(
        row.row_authority.observed_response_sha256 is None
        and row.row_authority.observed_reason_codes == ()
        for row in body_rows
    )
    assert receipt.source_verified_cell_count > 0
    assert receipt.storage_readback_only_cell_count > 0

    hostile = receipt.to_dict()
    rows = hostile["conditional_row_receipts"]
    assert isinstance(rows, list)
    selected = next(
        row
        for row in rows
        if isinstance(row, dict)
        and isinstance(row.get("row_authority"), dict)
        and row["row_authority"]["source_occurrence_sha256"] is not None
    )
    selected_authority = selected["row_authority"]
    assert isinstance(selected_authority, dict)
    selected_authority["observed_expected_result_set_count"] = 1
    _reseal_conditional_row_payload(selected)
    _reseal_conditional_route_payload(hostile)
    with pytest.raises(TypedFieldValueReceiptError, match="observed response"):
        RouteFieldLandingReceiptV2.from_canonical_bytes(canonical_json_bytes(hostile))

    hostile = receipt.to_dict()
    rows = hostile["conditional_row_receipts"]
    assert isinstance(rows, list)
    body = next(
        row
        for row in rows
        if isinstance(row, dict)
        and isinstance(row.get("row_authority"), dict)
        and row["row_authority"]["source_occurrence_sha256"] is None
    )
    body_authority = body["row_authority"]
    assert isinstance(body_authority, dict)
    body_authority["source_occurrence_sha256"] = selected_authority["source_occurrence_sha256"]
    body_authority["body_object_sha256"] = None
    body_authority["source_presence"] = "present"
    body_authority["source_row_count"] = 1
    body_authority["source_parent_state_sha256"] = _sha("hostile-hybrid-parent")
    _reseal_conditional_row_payload(body)
    _reseal_conditional_route_payload(hostile)
    with pytest.raises(TypedFieldValueReceiptError, match="observed_response_sha256"):
        RouteFieldLandingReceiptV2.from_canonical_bytes(canonical_json_bytes(hostile))


def test_selected_result_partition_carries_every_record_kind_and_zero_values(
    field_fate: FieldFateStructureV1,
) -> None:
    _route_id, _frame, authority = _cached_selected_stats_conditional_authority(field_fate)
    receipt = RouteFieldLandingReceiptV2.build_from_authorities(
        readback=authority.readback,
        raw_bundle=authority.raw_bundle,
        field_fate=field_fate,
        conditional_authority=authority,
    )
    rows = tuple(item.row_authority for item in receipt.conditional_row_receipts)

    assert {item.record_kind for item in rows} == {"result_set", "header", "row", "cell"}
    assert all(item.source_occurrence_sha256 is not None for item in rows)
    assert all(item.body_object_sha256 is None for item in rows)
    assert all(item.source_row_count == 2 for item in rows)
    assert all(item.source_presence == "present" for item in rows)
    assert any(
        cell.canonical_value.tag == "null"
        for row in receipt.conditional_row_receipts
        for cell in row.cells
    )


@pytest.mark.parametrize(
    ("drift_kind", "reason_code", "record_kind"),
    (
        ("unsupported_header", "unsupported_header_shape", "result_set"),
        ("mixed_header_values", "unsupported_header_shape", "header"),
        ("additive_header", "additive_header", "header"),
        ("removed_header", "removed_header", "header"),
        ("reordered_header", "reordered_header", "header"),
        ("duplicate_header", "duplicate_header", "header"),
        ("unsupported_rows", "unsupported_row_container", "result_set"),
        ("non_sequence_row", "non_sequence_row", "row"),
        ("nested_value", "unrepresentable_typed_frame", "cell"),
        ("additive_result", "additive_result_set", "result_set"),
        ("duplicate_result", "duplicate_result_set_name", "result_set"),
        ("missing_result", "missing_result_set", "missing_expected"),
    ),
)
def test_selected_result_round_trips_every_observed_fallback_shape(
    field_fate: FieldFateStructureV1,
    drift_kind: str,
    reason_code: str,
    record_kind: str,
) -> None:
    route = next(
        item
        for item in staging_route_contract_bundle().routes
        if item.endpoint_name == "league_game_log"
    )
    headers = list(route.provider_columns)
    row: list[object] = [None] * len(headers)
    if drift_kind == "nested_value":
        row[0] = [1, "x"]
    elif drift_kind == "additive_header":
        headers.append("UPSTREAM_ADDITIVE")
        row.append("exact")
    elif drift_kind == "removed_header":
        headers.pop(1)
        row.pop(1)
    elif drift_kind == "reordered_header":
        headers[0], headers[1] = headers[1], headers[0]
        row[0], row[1] = row[1], row[0]
    elif drift_kind == "duplicate_header":
        headers[1] = headers[0]
    if drift_kind != "missing_result":
        result: dict[str, object] = {
            "name": route.provider_result_set_name,
            "headers": (
                {"unsupported": True}
                if drift_kind == "unsupported_header"
                else ["A", 7, "B"]
                if drift_kind == "mixed_header_values"
                else headers
            ),
            "rowSet": (
                {"unsupported": True}
                if drift_kind == "unsupported_rows"
                else [{"unsupported": True}]
                if drift_kind == "non_sequence_row"
                else [row]
            ),
        }
        result_sets: list[dict[str, object]] = [result]
        payload: dict[str, object] = {"resultSets": result_sets}
        if drift_kind == "additive_result":
            result_sets.append(
                {
                    "name": "UpstreamAdditive",
                    "headers": ["UPSTREAM_KEY", "UPSTREAM_VALUE"],
                    "rowSet": [[1, {"nested": [True, None, "exact"]}]],
                }
            )
        elif drift_kind == "duplicate_result":
            duplicate = copy.deepcopy(result)
            duplicate["rowSet"] = [["duplicate", *row[1:]]]
            result_sets.append(duplicate)
        frame, authority = _selected_stats_authority_from_payload(field_fate, payload)
    else:
        frame, authority = _selected_scoreboard_missing_authority(field_fate)
    receipt = RouteFieldLandingReceiptV2.build_from_authorities(
        readback=authority.readback,
        raw_bundle=authority.raw_bundle,
        field_fate=field_fate,
        conditional_authority=authority,
    )

    assert receipt.source_shape == "selected_result_bound"
    assert receipt.selected_occurrence_count == len(authority.result_occurrence_sha256s)
    assert record_kind in {
        row_receipt.row_authority.record_kind for row_receipt in receipt.conditional_row_receipts
    }
    response_identities = {
        (
            row_receipt.row_authority.observed_response_sha256,
            row_receipt.row_authority.observed_results_sha256,
            row_receipt.row_authority.observed_provider_result_set_count,
            row_receipt.row_authority.observed_expected_result_set_count,
            row_receipt.row_authority.observed_reason_codes,
        )
        for row_receipt in receipt.conditional_row_receipts
    }
    assert len(response_identities) == 1
    assert reason_code in next(iter(response_identities))[4]
    assert receipt.source_verified_cell_count > 0
    assert receipt.storage_readback_only_cell_count > 0
    assert len(receipt.conditional_row_receipts) == frame.height
    assert RouteFieldLandingReceiptV2.from_canonical_bytes(receipt.to_canonical_bytes()) == receipt
    assert (
        validate_route_field_landing_receipt_replay(
            receipt.to_canonical_bytes(),
            readback=authority.readback,
            raw_bundle=authority.raw_bundle,
            field_fate=field_fate,
            conditional_authority=authority,
        )
        == receipt
    )
    if drift_kind != "missing_result":
        assert any(
            summary.canonical_result_ordinal is None
            for summary in receipt.selected_occurrence_authorities
        )
    else:
        missing_summaries = tuple(
            summary
            for summary in receipt.selected_occurrence_authorities
            if summary.presence == "missing"
        )
        assert len(missing_summaries) == 1
        assert missing_summaries[0].result_name == "WinProbability"
        assert missing_summaries[0].provider_result_ordinal is None
        assert missing_summaries[0].canonical_result_ordinal is None
        assert missing_summaries[0].ordered_headers == ()
        assert any(
            summary.presence == "present" for summary in receipt.selected_occurrence_authorities
        )


def test_selected_missing_result_rejects_wrong_declared_index_and_raw_promotion(
    field_fate: FieldFateStructureV1,
) -> None:
    frame, authority = _selected_scoreboard_missing_authority(field_fate)
    selected = authority.raw_bundle.selected_terminal_occurrences_for_route(
        authority.route_id,
        authority.readback.committed_receipt.receipt_root_sha256,
    )
    missing_row_ordinal, missing_row = next(
        (ordinal, row)
        for ordinal, row in enumerate(frame.to_dicts())
        if row["record_kind"] == "missing_expected"
    )
    assert missing_row["result_set_name"] == "WinProbability"
    declared_indexes = field_fate_module._declared_stats_result_indexes("ScoreboardV2")

    wrong_index = dict(missing_row)
    wrong_index["canonical_index"] = 8
    with pytest.raises(
        FieldFateStructureError,
        match="ambiguous or missing result occurrence authority",
    ):
        field_fate_module._selected_stats_binding_for_row(
            route_id=authority.route_id,
            staging_row_ordinal=missing_row_ordinal,
            row=wrong_index,
            selected=selected,
            declared_result_indexes=declared_indexes,
        )

    observation, missing_occurrence = next(
        item for item in selected if item[1].presence == "missing"
    )
    promoted = _rebuild_result_occurrence(
        missing_occurrence,
        canonical_result_ordinal=9,
    )
    promoted_selected = tuple(
        (observation, promoted) if item[1] == missing_occurrence else item for item in selected
    )
    with pytest.raises(
        FieldFateStructureError,
        match="ambiguous or missing result occurrence authority",
    ):
        field_fate_module._selected_stats_binding_for_row(
            route_id=authority.route_id,
            staging_row_ordinal=missing_row_ordinal,
            row=missing_row,
            selected=promoted_selected,
            declared_result_indexes=declared_indexes,
        )


def test_body_node_partition_carries_exact_parent_path_and_edge_ordinals(
    field_fate: FieldFateStructureV1,
) -> None:
    _route_id, _frame, authority = _cached_body_node_conditional_authority(field_fate)
    receipt = RouteFieldLandingReceiptV2.build_from_authorities(
        readback=authority.readback,
        raw_bundle=authority.raw_bundle,
        field_fate=field_fate,
        conditional_authority=authority,
    )
    rows = tuple(item.row_authority for item in receipt.conditional_row_receipts)
    root = next(item for item in rows if item.json_path == "$")
    nested = next(item for item in rows if item.object_key == "nested")
    array_item = next(item for item in rows if item.array_ordinal == 0)

    assert root.node_ordinal == 0
    assert root.parent_node_ordinal is None
    assert root.parent_json_path is None
    assert nested.parent_node_ordinal is not None
    assert nested.parent_json_path == '$["unexpected"]'
    assert nested.object_key_ordinal == 0
    assert array_item.parent_node_ordinal is not None
    assert array_item.parent_json_path == '$["unexpected"]["nested"]'
    assert array_item.value_kind == "integer"
    assert all(item.source_occurrence_sha256 is None for item in rows)
    assert all(item.body_object_sha256 is not None for item in rows)


def test_live_partition_carries_declarations_nulls_and_present_containers(
    field_fate: FieldFateStructureV1,
) -> None:
    _route_id, _frame, authority = _cached_live_conditional_authority(field_fate)
    receipt = RouteFieldLandingReceiptV2.build_from_authorities(
        readback=authority.readback,
        raw_bundle=authority.raw_bundle,
        field_fate=field_fate,
        conditional_authority=authority,
        live_plan_bindings=_live_plan_bindings(authority.raw_bundle),
    )
    rows = tuple(item.row_authority for item in receipt.conditional_row_receipts)

    declarations = tuple(item for item in rows if item.record_kind == "result_set_declaration")
    nulls = tuple(item for item in rows if item.presence_kind == "null")
    present_containers = tuple(
        item
        for item in rows
        if item.presence_kind == "present" and item.value_kind in {"object", "array"}
    )
    assert declarations
    assert tuple(item.result_set_ordinal for item in declarations) == tuple(
        range(len(declarations))
    )
    assert nulls
    assert all(item.value_kind == "null" for item in nulls)
    assert present_containers
    assert all(item.body_object_sha256 is not None for item in rows)


def test_ordinary_live_value_decoder_projects_nested_result_through_array(
    field_fate: FieldFateStructureV1,
) -> None:
    _route_id, _frame, authority = _cached_live_conditional_authority(field_fate)
    observation, occurrence, parser_input = _live_decoder_authority(
        authority,
        "scoreboard_games_hometeam",
    )

    decoded = receipt_module._decoded_provider_rows(
        bundle=authority.raw_bundle,
        observation=observation,
        occurrence=occurrence,
    )

    assert decoded.ordered_headers == occurrence.ordered_headers()
    assert len(decoded.values) == occurrence.row_count == 1
    assert len(decoded.records) == 1
    record = decoded.records[0]
    assert isinstance(record, dict)
    assert record["teamId"] == 1
    assert record["periods"] == [{"period": 1, "periodType": "fixture", "score": 1}]
    assert parser_input


def test_ordinary_live_value_decoder_preserves_optional_missing_fields(
    field_fate: FieldFateStructureV1,
) -> None:
    route = next(
        item
        for item in staging_route_contract_bundle().routes
        if item.endpoint_name == "live_score_board"
    )
    payload = _complete_endpoint_payload(pinned_live_contracts()[route.provider_endpoint_id])
    scoreboard = payload["scoreboard"]
    assert isinstance(scoreboard, dict)
    scoreboard.pop("leagueName")
    _frame, authority = _live_conditional_authority_from_payload(field_fate, payload)
    observation, occurrence, _parser_input = _live_decoder_authority(
        authority,
        "scoreboard",
    )

    decoded = receipt_module._decoded_provider_rows(
        bundle=authority.raw_bundle,
        observation=observation,
        occurrence=occurrence,
    )

    league_name_ordinal = decoded.ordered_headers.index("leagueName")
    assert decoded.values[0][league_name_ordinal] is None
    record = decoded.records[0]
    assert isinstance(record, dict)
    assert "leagueName" not in record
    assert len(decoded.values[0]) == occurrence.header_count


def test_ordinary_live_value_decoder_rejects_resealed_occurrence_mismatches(
    field_fate: FieldFateStructureV1,
) -> None:
    _route_id, _frame, authority = _cached_live_conditional_authority(field_fate)
    observation, occurrence, parser_input = _live_decoder_authority(
        authority,
        "scoreboard_games_hometeam",
    )
    headers = list(occurrence.ordered_headers())
    mutations: tuple[dict[str, object], ...] = (
        {"provider_result_ordinal": 0},
        {"duplicate_name_ordinal": 1},
        {"canonical_result_ordinal": occurrence.canonical_result_ordinal + 1},
        {"json_path": '$["scoreboard"]["games"]["foreignTeam"]'},
        {"ordered_headers": ["foreignField", *headers[1:]]},
        {"output_sha256": _sha("foreign-live-output")},
        {
            "presence": "null",
            "ordered_headers": [],
            "row_count": 0,
            "cell_count": 0,
            "node_count": 1,
            "container_count": 1,
            "missing_count": 0,
            "null_count": 1,
        },
    )

    for mutation in mutations:
        hostile = _rebuild_result_occurrence(occurrence, **mutation)
        with pytest.raises(
            TypedFieldValueReceiptError,
            match=(
                "raw live occurrence has no unique independent result summary"
                "|independent live result summary differs from raw occurrence authority"
            ),
        ):
            receipt_module._live_rows_from_independent_decoder(
                observation=observation,
                occurrence=hostile,
                parser_input=parser_input,
            )


def test_ordinary_live_value_decoder_rejects_valid_foreign_response(
    field_fate: FieldFateStructureV1,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _route_id, _frame, authority = _cached_live_conditional_authority(field_fate)
    observation, occurrence, parser_input = _live_decoder_authority(
        authority,
        "scoreboard_games_hometeam",
    )
    route = next(
        item
        for item in staging_route_contract_bundle().routes
        if item.endpoint_name == "live_score_board"
    )
    foreign_payload = _complete_endpoint_payload(
        pinned_live_contracts()[route.provider_endpoint_id]
    )
    foreign_scoreboard = foreign_payload["scoreboard"]
    assert isinstance(foreign_scoreboard, dict)
    foreign_scoreboard["leagueName"] = "foreign"
    foreign_parser_input = json.dumps(
        foreign_payload,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    ).encode("utf-8")
    foreign_response = receipt_module.decode_live_value_response(
        foreign_parser_input,
        endpoint_id=observation.attempt.endpoint_id,
        endpoint_contract_sha256=observation.attempt.endpoint_contract_sha256,
    )
    monkeypatch.setattr(
        receipt_module,
        "decode_live_value_response",
        lambda *_args, **_kwargs: foreign_response,
    )

    with pytest.raises(
        TypedFieldValueReceiptError,
        match="independent live response is rebound to foreign parser authority",
    ):
        receipt_module._live_rows_from_independent_decoder(
            observation=observation,
            occurrence=occurrence,
            parser_input=parser_input,
        )


def test_live_nested_missing_result_set_field_uses_child_occurrence_context(
    field_fate: FieldFateStructureV1,
) -> None:
    frame, authority = _live_missing_child_authority(field_fate)
    receipt = RouteFieldLandingReceiptV2.build_from_authorities(
        readback=authority.readback,
        raw_bundle=authority.raw_bundle,
        field_fate=field_fate,
        conditional_authority=authority,
        live_plan_bindings=_live_plan_bindings(authority.raw_bundle),
    )
    missing = next(
        item.row_authority
        for item in receipt.conditional_row_receipts
        if item.row_authority.json_path == '$["scoreboard"]["games"][0]["gameLeaders"]'
    )

    assert missing.record_kind == "json_node"
    assert missing.result_set_name == "scoreboard_games_gameleaders"
    assert missing.result_set_ordinal == 7
    assert missing.result_set_occurrence == 0
    assert missing.provider_row_ordinal is None
    assert missing.presence_kind == "missing"
    assert missing.value_kind == "missing"
    committed_missing = next(
        row
        for row in frame.to_dicts()
        if row["json_path"] == '$["scoreboard"]["games"][0]["gameLeaders"]'
    )
    assert committed_missing["container_kind"] == "nba_api_live_json_object"
    assert len(receipt.conditional_row_receipts) == frame.height
    encoded = receipt.to_canonical_bytes()
    assert RouteFieldLandingReceiptV2.from_canonical_bytes(encoded) == receipt
    assert (
        validate_route_field_landing_receipt_replay(
            encoded,
            readback=authority.readback,
            raw_bundle=authority.raw_bundle,
            field_fate=field_fate,
            conditional_authority=authority,
            live_plan_bindings=_live_plan_bindings(authority.raw_bundle),
        )
        == receipt
    )


def test_live_mixed_absent_occurrence_is_exact_and_rejects_resealed_tampering(
    field_fate: FieldFateStructureV1,
) -> None:
    frame, authority = _live_mixed_absent_authority(field_fate)
    receipt = RouteFieldLandingReceiptV2.build_from_authorities(
        readback=authority.readback,
        raw_bundle=authority.raw_bundle,
        field_fate=field_fate,
        conditional_authority=authority,
        live_plan_bindings=_live_plan_bindings(authority.raw_bundle),
    )
    summary = next(
        item
        for item in receipt.selected_occurrence_authorities
        if item.result_name == "scoreboard_games_gameleaders"
    )

    assert summary.presence == "mixed_absent"
    assert summary.ordered_headers == ()
    assert summary.header_count == 0
    assert summary.row_count == 0
    assert summary.cell_count == 0
    assert summary.missing_count > 0
    assert summary.null_count > 0
    assert summary.node_count == summary.null_count
    assert summary.container_count == summary.null_count
    assert len(receipt.conditional_row_receipts) == frame.height
    encoded = receipt.to_canonical_bytes()
    assert RouteFieldLandingReceiptV2.from_canonical_bytes(encoded) == receipt
    assert (
        validate_route_field_landing_receipt_replay(
            encoded,
            readback=authority.readback,
            raw_bundle=authority.raw_bundle,
            field_fate=field_fate,
            conditional_authority=authority,
            live_plan_bindings=_live_plan_bindings(authority.raw_bundle),
        )
        == receipt
    )

    selected = authority.raw_bundle.selected_terminal_occurrences_for_route(
        authority.route_id,
        authority.readback.committed_receipt.receipt_root_sha256,
    )
    observation, occurrence = next(
        item for item in selected if item[1].occurrence_sha256 == summary.occurrence_sha256
    )
    body = next(
        item
        for item in authority.raw_bundle.objects
        if item.object_sha256 == observation.body_object_sha256
    )
    hostile_occurrence = _rebuild_result_occurrence(occurrence, presence="present")
    with pytest.raises(
        TypedFieldValueReceiptError,
        match="raw provider result derivation differs from occurrence authority",
    ):
        receipt_module._assert_rederived_occurrence(
            observation=observation,
            occurrence=hostile_occurrence,
            parser_input=receipt_module.decode_parser_input_object(body),
        )

    hostile_payload = receipt.to_dict()
    hostile_summaries = hostile_payload["selected_occurrence_authorities"]
    assert isinstance(hostile_summaries, list)
    hostile_summary = next(
        item
        for item in hostile_summaries
        if isinstance(item, dict) and item["occurrence_sha256"] == summary.occurrence_sha256
    )
    assert isinstance(hostile_summary, dict)
    hostile_summary["presence"] = "missing"
    _reseal_selected_occurrence_payload(hostile_payload)
    with pytest.raises(
        TypedFieldValueReceiptError,
        match="missing source occurrence is invalid",
    ):
        RouteFieldLandingReceiptV2.from_canonical_bytes(canonical_json_bytes(hostile_payload))


def test_conditional_row_occurrence_discriminator_rejects_resealed_partial_states(
    field_fate: FieldFateStructureV1,
) -> None:
    authorities = {
        "selected": _cached_selected_stats_conditional_authority(field_fate)[2],
        "body": _cached_body_node_conditional_authority(field_fate)[2],
        "live": _cached_live_conditional_authority(field_fate)[2],
    }
    payloads = {
        name: RouteFieldLandingReceiptV2.build_from_authorities(
            readback=authority.readback,
            raw_bundle=authority.raw_bundle,
            field_fate=field_fate,
            conditional_authority=authority,
            live_plan_bindings=_live_plan_bindings(authority.raw_bundle),
        ).to_dict()
        for name, authority in authorities.items()
    }

    def reject(
        payload: dict[str, object],
        *,
        row_predicate: object,
        field_name: str,
        value: object,
    ) -> None:
        hostile = copy.deepcopy(payload)
        rows = hostile["conditional_row_receipts"]
        assert isinstance(rows, list)
        row = next(
            item
            for item in rows
            if isinstance(item, dict)
            and isinstance(item.get("row_authority"), dict)
            and row_predicate(item["row_authority"])  # type: ignore[operator]
        )
        authority = row["row_authority"]
        assert isinstance(authority, dict)
        authority[field_name] = value
        _reseal_conditional_row_payload(row)
        _reseal_conditional_route_payload(hostile)
        with pytest.raises(
            TypedFieldValueReceiptError,
            match="occurrence|presence|partial",
        ):
            RouteFieldLandingReceiptV2.from_canonical_bytes(canonical_json_bytes(hostile))

    reject(
        payloads["selected"],
        row_predicate=lambda _row: True,
        field_name="source_presence",
        value=None,
    )
    reject(
        payloads["selected"],
        row_predicate=lambda _row: True,
        field_name="source_presence",
        value="forged",
    )
    reject(
        payloads["body"],
        row_predicate=lambda _row: True,
        field_name="source_occurrence_sha256",
        value=_sha("invented-body-occurrence"),
    )
    reject(
        payloads["live"],
        row_predicate=lambda row: row["source_occurrence_sha256"] is not None,
        field_name="source_row_count",
        value=None,
    )


@pytest.mark.parametrize("mutation", ("strip", "attach", "swap"))
def test_conditional_cell_source_authority_is_an_exact_field_intersection(
    field_fate: FieldFateStructureV1,
    mutation: str,
) -> None:
    authority = _cached_body_node_conditional_authority(field_fate)[2]
    payload = RouteFieldLandingReceiptV2.build_from_authorities(
        readback=authority.readback,
        raw_bundle=authority.raw_bundle,
        field_fate=field_fate,
        conditional_authority=authority,
    ).to_dict()
    rows = payload["conditional_row_receipts"]
    assert isinstance(rows, list)
    selected_row: dict[str, object] | None = None
    source_cell: dict[str, object] | None = None
    storage_cell: dict[str, object] | None = None
    for candidate in rows:
        assert isinstance(candidate, dict)
        cells = candidate["cells"]
        assert isinstance(cells, list)
        verified = next(
            (
                cell
                for cell in cells
                if isinstance(cell, dict) and cell["value_authority"] == "source_verified"
            ),
            None,
        )
        readback_only = next(
            (
                cell
                for cell in cells
                if isinstance(cell, dict) and cell["value_authority"] == "storage_readback_only"
            ),
            None,
        )
        if verified is not None and readback_only is not None:
            selected_row = candidate
            source_cell = verified
            storage_cell = readback_only
            break
    assert selected_row is not None
    assert source_cell is not None
    assert storage_cell is not None
    source_bindings = source_cell["source_binding_sha256s"]
    assert isinstance(source_bindings, list) and source_bindings

    if mutation in {"strip", "swap"}:
        source_cell["source_binding_sha256s"] = []
        source_cell["value_authority"] = "storage_readback_only"
    if mutation in {"attach", "swap"}:
        storage_cell["source_binding_sha256s"] = list(source_bindings)
        storage_cell["value_authority"] = "source_verified"
    source_count = payload["source_verified_cell_count"]
    readback_count = payload["storage_readback_only_cell_count"]
    assert isinstance(source_count, int) and isinstance(readback_count, int)
    if mutation == "strip":
        payload["source_verified_cell_count"] = source_count - 1
        payload["storage_readback_only_cell_count"] = readback_count + 1
    elif mutation == "attach":
        payload["source_verified_cell_count"] = source_count + 1
        payload["storage_readback_only_cell_count"] = readback_count - 1

    _reseal_conditional_row_payload(selected_row)
    _reseal_conditional_route_payload(payload)
    with pytest.raises(
        TypedFieldValueReceiptError,
        match="conditional cell source authority differs from its field",
    ):
        RouteFieldLandingReceiptV2.from_canonical_bytes(canonical_json_bytes(payload))


@pytest.mark.parametrize("mutation", ("drop", "duplicate", "reorder"))
def test_conditional_row_partition_rejects_dropped_duplicated_or_reordered_rows(
    field_fate: FieldFateStructureV1,
    mutation: str,
) -> None:
    _route_id, _frame, authority = _cached_body_node_conditional_authority(field_fate)
    payload = RouteFieldLandingReceiptV2.build_from_authorities(
        readback=authority.readback,
        raw_bundle=authority.raw_bundle,
        field_fate=field_fate,
        conditional_authority=authority,
    ).to_dict()
    rows = payload["conditional_row_receipts"]
    assert isinstance(rows, list)
    if mutation == "drop":
        rows.pop()
    elif mutation == "duplicate":
        rows[-1] = copy.deepcopy(rows[0])
    else:
        rows[0], rows[1] = rows[1], rows[0]
    _reseal_conditional_route_payload(payload)

    with pytest.raises(
        TypedFieldValueReceiptError,
        match="denominator|reordered|foreign",
    ):
        RouteFieldLandingReceiptV2.from_canonical_bytes(canonical_json_bytes(payload))


def test_selected_binding_rebind_with_fully_recomputed_wire_receipts_is_rejected(
    field_fate: FieldFateStructureV1,
) -> None:
    _route_id, _frame, authority = _cached_selected_stats_conditional_authority(field_fate)
    receipt = RouteFieldLandingReceiptV2.build_from_authorities(
        readback=authority.readback,
        raw_bundle=authority.raw_bundle,
        field_fate=field_fate,
        conditional_authority=authority,
    )
    payload = receipt.to_dict()
    rows = payload["conditional_row_receipts"]
    assert isinstance(rows, list)
    row = rows[0]
    assert isinstance(row, dict)
    row_authority = row["row_authority"]
    cells = row["cells"]
    assert isinstance(row_authority, dict)
    assert isinstance(cells, list)
    original_bindings = row_authority["source_binding_sha256s"]
    assert isinstance(original_bindings, list) and len(original_bindings) == 1
    foreign = _sha("foreign-conditional-binding")
    row_authority["source_binding_sha256s"] = [foreign]
    for cell in cells:
        assert isinstance(cell, dict)
        bindings = cell["source_binding_sha256s"]
        assert isinstance(bindings, list)
        cell["source_binding_sha256s"] = [
            foreign if item == original_bindings[0] else item for item in bindings
        ]
    _reseal_conditional_row_payload(row)
    _reseal_conditional_route_payload(payload)
    encoded = canonical_json_bytes(payload)
    with pytest.raises(
        TypedFieldValueReceiptError,
        match="source authority differs from its field|rebound",
    ):
        RouteFieldLandingReceiptV2.from_canonical_bytes(encoded)


def test_body_node_selector_rebind_with_fully_recomputed_wire_receipts_is_rejected(
    field_fate: FieldFateStructureV1,
) -> None:
    _route_id, _frame, authority = _cached_body_node_conditional_authority(field_fate)
    payload = RouteFieldLandingReceiptV2.build_from_authorities(
        readback=authority.readback,
        raw_bundle=authority.raw_bundle,
        field_fate=field_fate,
        conditional_authority=authority,
    ).to_dict()
    rows = payload["conditional_row_receipts"]
    assert isinstance(rows, list)
    row = next(
        item
        for item in rows
        if isinstance(item, dict)
        and isinstance(item.get("row_authority"), dict)
        and item["row_authority"]["array_ordinal"] == 0
    )
    row_authority = row["row_authority"]
    assert isinstance(row_authority, dict)
    row_authority["parent_json_path"] = '$["rebound"]'
    _reseal_conditional_row_payload(row)
    _reseal_conditional_route_payload(payload)
    encoded = canonical_json_bytes(payload)
    assert RouteFieldLandingReceiptV2.from_canonical_bytes(encoded)

    with pytest.raises(TypedFieldValueReceiptError, match="strict production authority replay"):
        validate_route_field_landing_receipt_replay(
            encoded,
            readback=authority.readback,
            raw_bundle=authority.raw_bundle,
            field_fate=field_fate,
            conditional_authority=authority,
        )


def test_live_presence_rebind_with_fully_recomputed_wire_receipts_is_rejected(
    field_fate: FieldFateStructureV1,
) -> None:
    _route_id, _frame, authority = _cached_live_conditional_authority(field_fate)
    payload = RouteFieldLandingReceiptV2.build_from_authorities(
        readback=authority.readback,
        raw_bundle=authority.raw_bundle,
        field_fate=field_fate,
        conditional_authority=authority,
        live_plan_bindings=_live_plan_bindings(authority.raw_bundle),
    ).to_dict()
    rows = payload["conditional_row_receipts"]
    assert isinstance(rows, list)
    row = next(
        item
        for item in rows
        if isinstance(item, dict)
        and isinstance(item.get("row_authority"), dict)
        and item["row_authority"]["presence_kind"] == "null"
    )
    row_authority = row["row_authority"]
    assert isinstance(row_authority, dict)
    row_authority["presence_kind"] = "missing"
    _reseal_conditional_row_payload(row)
    _reseal_conditional_route_payload(payload)
    encoded = canonical_json_bytes(payload)
    assert RouteFieldLandingReceiptV2.from_canonical_bytes(encoded)

    with pytest.raises(TypedFieldValueReceiptError, match="strict production authority replay"):
        validate_route_field_landing_receipt_replay(
            encoded,
            readback=authority.readback,
            raw_bundle=authority.raw_bundle,
            field_fate=field_fate,
            conditional_authority=authority,
            live_plan_bindings=_live_plan_bindings(authority.raw_bundle),
        )


def test_body_source_and_committed_frame_rebindings_fail_after_exact_resealing(
    field_fate: FieldFateStructureV1,
) -> None:
    _route_id, frame, authority = _cached_body_node_conditional_authority(field_fate)
    original = authority.raw_bundle.observations[0]
    foreign_body = ParserInputObjectV2.from_parser_input('{"unexpected":{"nested":[2]}}')
    rebound_observation = RequestObservationV2.build(
        attempt=original.attempt,
        transport=original.transport,
        started_at=original.started_at,
        finished_at=original.finished_at,
        elapsed_ns=original.elapsed_ns,
        lifecycle=original.lifecycle,
        outcome=original.outcome,
        failure_class=original.failure_class,
        root_exception_class=original.root_exception_class,
        body_disposition=original.body_disposition,
        body_object_sha256=foreign_body.object_sha256,
        bodyless_evidence_sha256=original.bodyless_evidence_sha256,
        result_occurrence_sha256s=(),
        route_landing_sha256s=tuple(
            item.landing_sha256
            for item in authority.raw_bundle.landings
            if item.observation_sha256 == original.attempt.observation_sha256
        ),
        capture_response_receipt_sha256=original.capture_response_receipt_sha256,
        logical_receipt_sha256=original.logical_receipt_sha256,
    )
    with pytest.raises(ValueError, match="exact.*reconstruction|body-node"):
        RawRequestAuthorityBundleV2.build(
            objects=(foreign_body,),
            observations=(rebound_observation,),
            occurrences=(),
            landings=authority.raw_bundle.landings,
        )

    rebound_frame = frame.with_columns(
        pl.when(pl.int_range(pl.len()) == 0)
        .then(pl.lit("rebound_record"))
        .otherwise(pl.col("record_kind"))
        .alias("record_kind")
    )
    content_sha256 = frame_content_hash(rebound_frame)
    committed = replace(
        authority.readback.committed_receipt,
        content_hash=content_sha256,
        persisted_row_count=rebound_frame.height,
        persisted_content_sha256=content_sha256,
        persisted_schema_sha256=frame_schema_hash(rebound_frame),
    )
    rebound_readback = CommittedStagingFrameReadbackV2.build(
        committed_receipt=committed,
        frame=rebound_frame,
    )
    with pytest.raises(
        TypedFieldValueReceiptError,
        match="response-level route landing differs from committed readback",
    ):
        RouteFieldLandingReceiptV2.build_from_authorities(
            readback=rebound_readback,
            raw_bundle=authority.raw_bundle,
            field_fate=field_fate,
            conditional_authority=authority,
        )


def test_dictionary_context_is_part_of_exact_value_equality() -> None:
    first = pa.DictionaryArray.from_arrays(
        pa.array([0, 1], type=pa.int8()),
        pa.array(["same", "other"]),
    )
    second = pa.DictionaryArray.from_arrays(
        pa.array([0, 1], type=pa.int8()),
        pa.array(["same", "different"]),
    )
    committed = canonical_arrow_array_scalar(first, 0)
    decoder = canonical_arrow_scalar("same", first.type, dictionary_context=first)
    foreign_context = canonical_arrow_scalar("same", second.type, dictionary_context=second)

    assert compare_canonical_arrow_values(committed, decoder)
    assert not compare_canonical_arrow_values(committed, foreign_context)
    with pytest.raises(CanonicalArrowValueError, match="absent"):
        canonical_arrow_scalar("missing", first.type, dictionary_context=first)


def test_decimal_committed_ipc_and_value_are_exact_fixed_points() -> None:
    frame = pl.DataFrame(
        {
            "amount": pl.Series(
                [Decimal("1.20"), Decimal("-0.00"), Decimal("99999999.99")],
                dtype=pl.Decimal(10, 2),
            )
        }
    )
    content_sha256 = frame_content_hash(frame)
    committed = CommittedStagingChunkReceiptV2(
        chunk_id="chunk-decimal",
        staging_key="stg_decimal",
        canonical_frame_format=CANONICAL_FRAME_FORMAT,
        frame_content_hash_contract=FRAME_CONTENT_HASH_CONTRACT,
        frame_schema_hash_contract=FRAME_SCHEMA_HASH_CONTRACT,
        content_hash=content_sha256,
        persisted_row_count=frame.height,
        persisted_content_sha256=content_sha256,
        persisted_schema_sha256=frame_schema_hash(frame),
        logical_call_receipt_sha256=_sha("decimal-logical"),
        provider_authority_sha256=_sha("decimal-provider"),
        logical_parameters_sha256=_sha("decimal-parameters"),
        result_route_id="stats:stg_decimal:0",
    )
    readback = CommittedStagingFrameReadbackV2.build(
        committed_receipt=committed,
        frame=frame,
    )
    round_trip = pl.read_ipc_stream(readback.canonical_frame_bytes)
    rebuilt = CommittedStagingFrameReadbackV2.build(
        committed_receipt=committed,
        frame=round_trip,
    )
    assert rebuilt.canonical_frame_bytes == readback.canonical_frame_bytes

    with pa_ipc.open_stream(pa.BufferReader(readback.canonical_frame_bytes)) as reader:
        column = reader.read_all().column(0)
    for index, value in enumerate((Decimal("1.20"), Decimal("-0.00"), Decimal("99999999.99"))):
        assert compare_canonical_arrow_values(
            canonical_arrow_array_scalar(column, index),
            canonical_arrow_scalar(value, column.type),
        )


def test_source_family_and_decoder_cannot_be_relabelled_after_reseal(
    field_fate: FieldFateStructureV1,
) -> None:
    occurrence = _build(field_fate, _fixture()).occurrence_authorities[0]
    payload = occurrence.to_dict()
    payload["source_family"] = "live"
    identity = {key: value for key, value in payload.items() if key != "authority_sha256"}
    payload["authority_sha256"] = canonical_sha256(identity)

    with pytest.raises(TypedFieldValueReceiptError, match="relabels"):
        OccurrenceLandingAuthorityV2.from_canonical_bytes(canonical_json_bytes(payload))


def test_duplicate_header_name_at_wrong_ordinal_is_not_collapsed() -> None:
    with pytest.raises(ValueError, match="ordinary result occurrence differs"):
        _fixture(headers=["id", "last_name", "first_name", "full_name", "id"])


def test_foreign_route_receipt_root_and_incomplete_denominator_fail_closed(
    field_fate: FieldFateStructureV1,
) -> None:
    with pytest.raises(ValueError, match="source occurrence receipt root differs"):
        _fixture(foreign_occurrence_root=True)

    with pytest.raises(ValueError, match="landing row count differs from sources"):
        _fixture(include_zero_row_occurrence=True)

    receipt = _build(field_fate, _fixture())
    assert receipt.occurrence_partition_count == 1
    assert receipt.selected_occurrence_count == 1


def test_parser_body_cannot_hide_a_provider_result_from_the_denominator() -> None:
    fixture = _fixture()
    original = fixture.bundle.observations[0]
    occurrence = fixture.bundle.occurrences[0]
    body = ParserInputObjectV2.from_parser_input(
        json.dumps(
            {
                "resultSets": [
                    {"name": "TeamYears", "headers": _RAW_HEADERS, "rowSet": _RAW_ROWS},
                    {"name": "TeamYears", "headers": _RAW_HEADERS, "rowSet": []},
                ]
            },
            separators=(",", ":"),
        )
    )
    observation = RequestObservationV2.build(
        attempt=original.attempt,
        transport={
            "transport_kind": "stats_http",
            "status_code": 200,
            "effective_status_code": 200,
        },
        started_at=_STARTED,
        finished_at=_STARTED + timedelta(microseconds=1),
        elapsed_ns=1_000,
        lifecycle="selected_terminal",
        outcome="success_nonempty",
        failure_class=None,
        root_exception_class=None,
        body_disposition="public_parser_input",
        body_object_sha256=body.object_sha256,
        bodyless_evidence_sha256=None,
        result_occurrence_sha256s=[occurrence.occurrence_sha256],
        route_landing_sha256s=[fixture.bundle.landings[0].landing_sha256],
        capture_response_receipt_sha256=_sha("capture-hidden-result"),
        logical_receipt_sha256=original.logical_receipt_sha256,
    )
    with pytest.raises(ValueError, match="inventory cardinality|exact rederivation"):
        RawRequestAuthorityBundleV2.build(
            objects=[body],
            observations=[observation],
            occurrences=[occurrence],
            landings=fixture.bundle.landings,
        )


def test_response_fixed_zero_route_round_trips_without_fabricated_rows(
    field_fate: FieldFateStructureV1,
) -> None:
    bundle, observation, occurrences, landings = _video_bundle("VideoDetails", {})
    assert observation.route_landing_count == 1
    assert occurrences == ()
    assert len(landings) == 1
    landing = landings[0]
    assert landing.landing_semantic == "response_fixed_zero"
    readback = CommittedStagingFrameReadbackV2.build(
        committed_receipt=_committed_receipt_from_landing(landing),
        frame=pl.DataFrame(),
    )

    receipt = RouteFieldLandingReceiptV2.build_from_authorities(
        readback=readback,
        raw_bundle=bundle,
        field_fate=field_fate,
    )
    assert receipt.source_shape == "response_fixed_zero"
    assert receipt.decoder_kind == "response_fixed_zero_v2"
    assert receipt.row_count == 0
    assert receipt.field_count == 0
    assert receipt.occurrence_partition_count == 0
    assert receipt.selected_occurrence_count == 0
    assert receipt.row_slice_receipt_sha256s == ()
    assert RouteFieldLandingReceiptV2.from_canonical_bytes(receipt.to_canonical_bytes()) == receipt
    assert (
        validate_route_field_landing_receipt_replay(
            receipt.to_canonical_bytes(),
            readback=readback,
            raw_bundle=bundle,
            field_fate=field_fate,
        )
        == receipt
    )


def test_self_resealed_landing_inventory_mutations_fail_before_typed_promotion(
    field_fate: FieldFateStructureV1,
) -> None:
    bundle, _observation, _occurrences, landings = _video_bundle(
        "VideoDetails",
        {"future": {"x": 1}},
    )
    fixed, conditional = landings
    readback = CommittedStagingFrameReadbackV2.build(
        committed_receipt=_committed_receipt_from_landing(fixed),
        frame=pl.DataFrame(),
    )
    relabelled = conditional.model_copy(
        update={
            "route_id": "foreign_route:stg_nba_api_lossless_result_cells:1",
            "result_route_id": "foreign_route:stg_nba_api_lossless_result_cells:1",
        }
    )
    variants = (
        (fixed,),
        (*landings, conditional),
        tuple(reversed(landings)),
        (fixed, relabelled),
    )
    for hostile_landings in variants:
        hostile = bundle.model_copy(deep=True)
        object.__setattr__(hostile, "landings", hostile_landings)
        object.__setattr__(
            hostile,
            "bundle_sha256",
            raw_authority_module._sha256_json(
                raw_authority_module._bundle_identity_payload(
                    objects=hostile.objects,
                    observations=hostile.observations,
                    occurrences=hostile.occurrences,
                    landings=hostile_landings,
                )
            ),
        )
        with pytest.raises(TypedFieldValueReceiptError, match="source authority is invalid"):
            RouteFieldLandingReceiptV2.build_from_authorities(
                readback=readback,
                raw_bundle=hostile,
                field_fate=field_fate,
            )


def test_live_route_requires_exact_external_plan_digest_and_timestamp(
    field_fate: FieldFateStructureV1,
) -> None:
    _route_id, _frame, authority = _cached_live_conditional_authority(field_fate)
    plan_bindings = _live_plan_bindings(authority.raw_bundle)
    assert len(plan_bindings) == 1
    plan, _expected_sha256 = plan_bindings[0]
    kwargs = {
        "readback": authority.readback,
        "raw_bundle": authority.raw_bundle,
        "field_fate": field_fate,
        "conditional_authority": authority,
    }

    with pytest.raises(TypedFieldValueReceiptError, match="lacks its independent sealed-plan"):
        RouteFieldLandingReceiptV2.build_from_authorities(**kwargs)
    with pytest.raises(TypedFieldValueReceiptError, match="independent expected authority"):
        RouteFieldLandingReceiptV2.build_from_authorities(
            **kwargs,
            live_plan_bindings=((plan, _sha("foreign-live-plan-authority")),),
        )

    observation = authority.raw_bundle.observations[0]
    foreign_timestamp_plan = LiveSnapshotPlanAuthorityV2.build(
        sealed_plan_bytes=b'{"kind":"foreign-live-plan-timestamp-v2"}',
        attempt=observation.attempt,
        route_ids=plan.route_ids,
        live_snapshot_at=plan.live_snapshot_at + timedelta(microseconds=1),
    )
    with pytest.raises(TypedFieldValueReceiptError, match="cannot be independently reconstructed"):
        RouteFieldLandingReceiptV2.build_from_authorities(
            **kwargs,
            live_plan_bindings=((foreign_timestamp_plan, foreign_timestamp_plan.authority_sha256),),
        )


def test_v1_foreign_contract_and_noncanonical_inputs_require_restart(
    field_fate: FieldFateStructureV1,
) -> None:
    receipt = _build(field_fate, _fixture())
    v1 = receipt.to_dict()
    v1["schema_version"] = 1
    _reseal_route_payload(v1)
    with pytest.raises(TypedFieldValueReceiptError, match="fresh full restart"):
        RouteFieldLandingReceiptV2.from_canonical_bytes(canonical_json_bytes(v1))

    foreign_frame_contract = receipt.to_dict()
    foreign_frame_contract["canonical_frame_format"] = "foreign_ipc"
    _reseal_route_payload(foreign_frame_contract)
    with pytest.raises(TypedFieldValueReceiptError, match="fresh full restart"):
        RouteFieldLandingReceiptV2.from_canonical_bytes(
            canonical_json_bytes(foreign_frame_contract)
        )

    encoded = receipt.to_canonical_bytes()
    with pytest.raises(TypedFieldValueReceiptError, match="byte-canonical"):
        RouteFieldLandingReceiptV2.from_canonical_bytes(encoded + b"\n")
    with pytest.raises(TypedFieldValueReceiptError, match="duplicate"):
        RouteFieldLandingReceiptV2.from_canonical_bytes(
            encoded.replace(
                b'{"canonical_frame_format":',
                b'{"kind":"x","kind":"y","canonical_frame_format":',
                1,
            )
        )


def test_self_resealed_foreign_raw_bundle_root_fails_structural_summary_binding(
    field_fate: FieldFateStructureV1,
) -> None:
    fixture = _fixture()
    payload = _build(field_fate, fixture).to_dict()
    payload["raw_bundle_sha256"] = _sha("foreign-bundle")
    _reseal_route_payload(payload)
    encoded = canonical_json_bytes(payload)
    with pytest.raises(TypedFieldValueReceiptError, match="summary is foreign"):
        RouteFieldLandingReceiptV2.from_canonical_bytes(encoded)


def test_foreign_canonical_value_and_declared_product_fail_before_acceptance(
    field_fate: FieldFateStructureV1,
) -> None:
    payload = _build(field_fate, _fixture()).to_dict()
    foreign_value = copy.deepcopy(payload)
    value_receipts = foreign_value["value_receipts"]
    assert isinstance(value_receipts, list)
    cells = value_receipts[0]["cells"]
    assert isinstance(cells, list)
    cells[0]["canonical_value"]["schema_version"] = 2
    with pytest.raises(TypedFieldValueReceiptError, match="fresh full restart"):
        RouteFieldLandingReceiptV2.from_canonical_bytes(canonical_json_bytes(foreign_value))

    false_denominator = copy.deepcopy(payload)
    false_denominator["row_count"] = 1_000_000
    false_denominator["field_count"] = 4_096
    false_denominator["cell_count"] = 4_096_000_000
    with pytest.raises(TypedFieldValueReceiptError, match="bounded exact integer"):
        RouteFieldLandingReceiptV2.from_canonical_bytes(canonical_json_bytes(false_denominator))


def test_route_value_budget_is_cumulative_and_atomic(
    field_fate: FieldFateStructureV1,
) -> None:
    fixture = _fixture()
    tiny_limits = ValueBudgetLimits(
        max_nodes=3,
        max_depth=64,
        max_utf8_bytes=8,
        max_binary_bytes=8,
        max_container_items=3,
        max_canonical_bytes=1_024,
    )
    with pytest.raises(TypedFieldValueReceiptError, match="violates its type"):
        _build(field_fate, fixture, limits=tiny_limits)

    receipt = _build(field_fate, fixture)
    assert receipt.value_node_count == sum(
        cell.canonical_value.node_count
        for value_receipt in receipt.value_receipts
        for cell in value_receipt.cells
    )
    assert receipt.value_canonical_bytes < 256 * 1024 * 1024


def test_parser_preallocation_gate_rejects_depth_before_json_decode() -> None:
    hostile = b"[" * 65 + b"0" + b"]" * 65
    with pytest.raises(TypedFieldValueReceiptError, match="depth bound"):
        RouteFieldLandingReceiptV2.from_canonical_bytes(hostile)


@pytest.mark.parametrize(
    "path",
    [
        ("row_count",),
        ("occurrence_partition_count",),
        ("selected_occurrence_count",),
        ("field_count",),
        ("cell_count",),
        ("source_verified_cell_count",),
        ("storage_readback_only_cell_count",),
        ("value_node_count",),
        ("value_max_depth",),
        ("value_utf8_bytes",),
        ("value_binary_bytes",),
        ("value_container_items",),
        ("value_canonical_bytes",),
        ("field_authorities", 0, "storage_ordinal"),
        ("field_authorities", 0, "source_header_ordinals", 0),
        ("occurrence_authorities", 0, "occurrence_order_ordinal"),
        ("occurrence_authorities", 0, "provider_result_ordinal"),
        ("occurrence_authorities", 0, "duplicate_name_ordinal"),
        ("occurrence_authorities", 0, "start_row_ordinal"),
        ("occurrence_authorities", 0, "row_count"),
        ("value_receipts", 0, "row_count"),
        ("value_receipts", 0, "field_count"),
        ("value_receipts", 0, "cell_count"),
        ("value_receipts", 0, "value_node_count"),
        ("value_receipts", 0, "value_max_depth"),
        ("value_receipts", 0, "value_utf8_bytes"),
        ("value_receipts", 0, "value_binary_bytes"),
        ("value_receipts", 0, "value_container_items"),
        ("value_receipts", 0, "value_canonical_bytes"),
        ("value_receipts", 0, "cells", 0, "occurrence_order_ordinal"),
        ("value_receipts", 0, "cells", 0, "row_ordinal"),
        ("value_receipts", 0, "cells", 0, "absolute_row_ordinal"),
        ("value_receipts", 0, "cells", 0, "storage_ordinal"),
    ],
)
def test_hostile_booleans_fail_at_parser_construction(
    receipt_payload: dict[str, object],
    path: tuple[str | int, ...],
) -> None:
    root = copy.deepcopy(receipt_payload)
    payload: object = root
    for segment in path[:-1]:
        if isinstance(segment, str):
            assert isinstance(payload, dict)
            payload = payload[segment]
        else:
            assert isinstance(payload, list)
            payload = payload[segment]
    leaf = path[-1]
    if isinstance(leaf, str):
        assert isinstance(payload, dict)
        payload[leaf] = True
    else:
        assert isinstance(payload, list)
        payload[leaf] = True
    with pytest.raises(TypedFieldValueReceiptError, match="integer|ordinal"):
        RouteFieldLandingReceiptV2.from_canonical_bytes(canonical_json_bytes(root))
