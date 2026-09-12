from __future__ import annotations

import hashlib
import json
from copy import deepcopy
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from typing import Literal, cast

import polars as pl
import pytest

from nbadb.contracts.logical_provider_parameter_binding import (
    LogicalProviderParameterBindingV1,
    compile_logical_provider_parameter_binding,
)
from nbadb.contracts.raw_request_authority import (
    ParserInputObjectV2,
    RawRequestAuthorityBundleV2,
    RawRequestAuthorityError,
    RequestAttemptIdentityV2,
    RequestObservationV2,
    canonical_semantic_parameters,
    decode_parser_input_object,
    validate_logical_provider_parameter_join,
    validate_raw_request_authority_bundle,
)
from nbadb.contracts.raw_request_finalization import (
    RawRequestFinalizationError,
    materialize_raw_request_failure_snapshot,
    materialize_raw_request_incomplete_success_snapshot,
)
from nbadb.contracts.raw_request_finalization import (
    finalize_raw_request_capture as _finalize_raw_request_capture,
)
from nbadb.contracts.raw_request_reconstruction import (
    LiveSnapshotPlanAuthorityV2,
    reconstruct_raw_request_authority,
)
from nbadb.contracts.staging_route_contract import (
    StagingRouteContract,
    staging_route_contract_bundle,
)
from nbadb.core.nba_api_runtime_contract import (
    pinned_live_contracts,
    pinned_runtime_contracts,
)
from nbadb.extract.bronze import (
    LogicalCallReceiptBinding,
    ResultSetReceipt,
    canonical_parameters_sha256,
    parent_occurrence_states_digest,
)
from nbadb.extract.live_lossless import LIVE_LOSSLESS_STAGING_KEY
from nbadb.extract.nba_api_adapter import (
    RawAuthorityStatsResultRows,
    rederive_raw_authority_result_sets,
    rederive_raw_authority_route_frames,
    rederive_raw_authority_stats_fallback,
    rederive_raw_authority_stats_rows,
    rederive_raw_authority_stats_wide_rows,
    rederive_raw_authority_unknown_stats_response,
    rows_to_polars,
)
from nbadb.extract.raw_request_capture import (
    PendingRawRequestSuccessV2,
    PendingResultOccurrenceV2,
    RawProviderCallContextV2,
    RawRequestCaptureContextV2,
    RawRequestCaptureIssueV2,
    RawRequestCaptureSnapshotV2,
)
from nbadb.extract.stats_lossless import build_unknown_stats_lossless_fallback
from nbadb.orchestrate.staging_batches import (
    CANONICAL_FRAME_FORMAT,
    FRAME_CONTENT_HASH_CONTRACT,
    FRAME_SCHEMA_HASH_CONTRACT,
    CommittedStagingChunkReceiptV2,
    frame_content_hash,
    frame_schema_hash,
)
from nbadb.orchestrate.staging_map import LOSSLESS_FALLBACK_STAGING_KEY
from nbadb.schemas.registry import get_input_schema
from tests.unit.extract.test_live_lossless_nodes import _complete_endpoint_payload

_SOURCE_SHA = "1" * 40
_SEMANTIC_REQUEST = "2" * 64
_LOGICAL_INVOCATION = "3" * 64
_SCOPE = "4" * 64
_LOGICAL_RECEIPT = "5" * 64
_STARTED_AT = datetime(2026, 8, 27, 12, 0, tzinfo=UTC)


class _SplitAuthorityDatetime(datetime):
    """Seal one instant while attempting to supply another during execution."""

    def isoformat(self, *args: object, **kwargs: object) -> str:
        return "2099-01-01T00:00:00.000000+00:00"

    def astimezone(self, tz: object = None) -> datetime:
        return _STARTED_AT


def _sha(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


def finalize_raw_request_capture(
    snapshot: RawRequestCaptureSnapshotV2,
    binding: LogicalCallReceiptBinding,
    committed_receipts: tuple[CommittedStagingChunkReceiptV2, ...],
) -> RawRequestAuthorityBundleV2:
    source_families = {
        item.attempt.source_family for item in (*snapshot.observations, *snapshot.pending_successes)
    }
    live_plan_authority = None
    expected_live_plan_authority_sha256 = None
    if source_families == {"live"}:
        live_plan_authority = _live_plan_authority(snapshot, binding)
        expected_live_plan_authority_sha256 = live_plan_authority.authority_sha256
    return _finalize_raw_request_capture(
        snapshot,
        binding,
        committed_receipts,
        live_plan_authority=live_plan_authority,
        expected_live_plan_authority_sha256=expected_live_plan_authority_sha256,
    )


def _live_plan_authority(
    snapshot: RawRequestCaptureSnapshotV2,
    binding: LogicalCallReceiptBinding,
    *,
    snapshot_at: datetime = _STARTED_AT,
    sealed_plan_bytes: bytes = b'{"kind":"test_live_sealed_plan_v2"}',
) -> LiveSnapshotPlanAuthorityV2:
    assert snapshot.pending_successes
    fixed_routes = tuple(
        route.route_id
        for route in sorted(
            (
                route
                for route in staging_route_contract_bundle().routes
                if route.endpoint_name == binding.endpoint_name
            ),
            key=lambda route: route.ordinal,
        )
    )
    conditional_routes = tuple(
        route_id for route_id in binding.result_route_ids if route_id not in fixed_routes
    )
    return LiveSnapshotPlanAuthorityV2.build(
        sealed_plan_bytes=sealed_plan_bytes,
        attempt=snapshot.pending_successes[0].attempt,
        route_ids=(*fixed_routes, *conditional_routes),
        live_snapshot_at=snapshot_at,
    )


def _route(endpoint_name: str) -> StagingRouteContract:
    matches = tuple(
        route
        for route in staging_route_contract_bundle().routes
        if route.endpoint_name == endpoint_name
    )
    assert matches
    return matches[0]


def _attempt(
    route: StagingRouteContract,
    *,
    parameters: dict[str, object],
    retry_ordinal: int = 0,
    request_ordinal: int = 0,
    provider_call_ordinal: int = 0,
    lane_id: str = "lane",
) -> RequestAttemptIdentityV2:
    bundle = staging_route_contract_bundle()
    return RequestAttemptIdentityV2.build(
        semantic_request_sha256=_SEMANTIC_REQUEST,
        logical_invocation_sha256=_LOGICAL_INVOCATION,
        provider_call_role="primary",
        provider_call_ordinal=provider_call_ordinal,
        retry_ordinal=retry_ordinal,
        request_ordinal=request_ordinal,
        source_family=route.source_family,
        endpoint_id=route.provider_endpoint_id,
        parameters=parameters,
        provider_authority_sha256=bundle.provider_authority_sha256,
        endpoint_contract_sha256=route.endpoint_contract_sha256,
        competition_id=None,
        competition_identity_sha256=None,
        scope_sha256=_SCOPE,
        pagination_sha256=None,
        page_ordinal=None,
        source_sha=_SOURCE_SHA,
        run_id=101,
        run_attempt=1,
        chain_id="chain",
        lane_id=lane_id,
    )


def _result_receipt(
    route: StagingRouteContract,
    *,
    canonical_index: int | None,
    row_count: int = 1,
) -> ResultSetReceipt:
    headers = route.provider_columns
    container_kind = {
        "stats": "nba_api_result_set",
        "static": "nba_api_static_records",
    }.get(route.source_family)
    json_path = None
    if route.source_family == "live":
        live_result = pinned_live_contracts()[route.provider_endpoint_id].result_sets[
            cast("int", route.provider_result_set_ordinal)
        ]
        container_kind = live_result.container_kind
        json_path = live_result.json_path
    provider_index = 0 if route.source_family != "live" else None
    if route.source_family == "stats":
        provider_index = route.provider_result_set_ordinal
    return ResultSetReceipt(
        name=cast("str", route.provider_result_set_name),
        provider_index=provider_index,
        canonical_index=canonical_index,
        headers_sha256=_sha(json.dumps(list(headers), separators=(",", ":"))),
        row_count=row_count,
        json_path=json_path,
        container_kind=cast("str", container_kind),
        container_count=1,
        missing_count=0,
        null_count=0,
        parent_observation_count=1,
        parent_occurrence_states_sha256=parent_occurrence_states_digest(("present",)),
        observed_field_orders_sha256=_sha("observed-fields"),
        normalized_output_sha256=_sha(f"normalized:{route.route_id}:{row_count}"),
    )


def _committed_receipt(
    binding: LogicalCallReceiptBinding,
    *,
    route_id: str,
    staging_key: str,
    row_count: int,
) -> CommittedStagingChunkReceiptV2:
    return CommittedStagingChunkReceiptV2(
        chunk_id=f"chunk:{_sha(route_id)[:16]}",
        staging_key=staging_key,
        canonical_frame_format=CANONICAL_FRAME_FORMAT,
        frame_content_hash_contract=FRAME_CONTENT_HASH_CONTRACT,
        frame_schema_hash_contract=FRAME_SCHEMA_HASH_CONTRACT,
        content_hash=_sha(f"content:{route_id}"),
        persisted_row_count=row_count,
        persisted_content_sha256=_sha(f"persisted:{route_id}"),
        persisted_schema_sha256=_sha(f"schema:{route_id}"),
        logical_call_receipt_sha256=binding.logical_call_receipt_sha256,
        provider_authority_sha256=binding.provider_authority_sha256,
        logical_parameters_sha256=binding.logical_parameters_sha256,
        result_route_id=route_id,
    )


def _committed_frame_receipt(
    binding: LogicalCallReceiptBinding,
    *,
    route_id: str,
    staging_key: str,
    frame: pl.DataFrame,
) -> CommittedStagingChunkReceiptV2:
    assert isinstance(frame, pl.DataFrame)
    content_sha256 = frame_content_hash(frame)
    return CommittedStagingChunkReceiptV2(
        chunk_id=f"chunk:{_sha(route_id)[:16]}",
        staging_key=staging_key,
        canonical_frame_format=CANONICAL_FRAME_FORMAT,
        frame_content_hash_contract=FRAME_CONTENT_HASH_CONTRACT,
        frame_schema_hash_contract=FRAME_SCHEMA_HASH_CONTRACT,
        content_hash=content_sha256,
        persisted_row_count=frame.height,
        persisted_content_sha256=content_sha256,
        persisted_schema_sha256=frame_schema_hash(frame),
        logical_call_receipt_sha256=binding.logical_call_receipt_sha256,
        provider_authority_sha256=binding.provider_authority_sha256,
        logical_parameters_sha256=binding.logical_parameters_sha256,
        result_route_id=route_id,
    )


def _stats_frame(
    route: StagingRouteContract,
    result_rows: RawAuthorityStatsResultRows,
    *,
    safe_parameters_json: str,
) -> pl.DataFrame:
    ordered_headers = result_rows.ordered_headers
    rows = result_rows.rows
    values = tuple(tuple(json.loads(cell.canonical_json) for cell in row) for row in rows)
    frame = rows_to_polars(ordered_headers, values)
    canonical_columns = tuple(item.canonical_column for item in route.column_mappings)
    frame = frame.rename(dict(zip(ordered_headers, canonical_columns, strict=True)))
    schema_cls = get_input_schema(route.staging_key)
    assert schema_cls is not None
    schema = schema_cls.to_schema()
    assert tuple(schema.columns) == route.storage_columns
    frame = frame.select(
        [
            (
                pl.col(column)
                if column in frame.columns
                else pl.lit(None).cast(schema.columns[column].dtype.type)
            ).alias(column)
            for column in route.storage_columns
        ]
    )
    frame = schema_cls.validate(frame)
    assert isinstance(frame, pl.DataFrame)
    parameters = cast("dict[str, object]", json.loads(safe_parameters_json))

    def first(*keys: str) -> object | None:
        return next(
            (
                parameters[key]
                for key in keys
                if parameters.get(key) is not None and parameters.get(key) != ""
            ),
            None,
        )

    additions: list[pl.Expr] = []
    for column_name, value in (
        ("season_year", first("season", "season_nullable", "season_year")),
        (
            "season_type",
            first(
                "season_type_all_star",
                "season_type_playoffs",
                "season_type",
                "season_type_nullable",
                "season_type_all_star_nullable",
            ),
        ),
        ("league_id", first("league_id", "league_id_nullable")),
    ):
        if value is not None and column_name not in frame.columns:
            additions.append(pl.lit(value).alias(column_name))
    return frame.with_columns(additions) if additions else frame


def _pending_success(
    route: StagingRouteContract,
    *,
    binding: LogicalCallReceiptBinding,
    parameters: dict[str, object],
    result: ResultSetReceipt,
    retry_ordinal: int = 0,
    private_receipt: str = "6" * 64,
) -> tuple[PendingRawRequestSuccessV2, ParserInputObjectV2 | None]:
    attempt = _attempt(route, parameters=parameters, retry_ordinal=retry_ordinal)
    body = (
        None
        if route.source_family == "static"
        else ParserInputObjectV2.from_parser_input('{"fixture":true}')
    )
    outcome: Literal[
        "success_nonempty",
        "success_empty",
        "static_snapshot_success",
    ] = (
        "static_snapshot_success"
        if route.source_family == "static"
        else "success_nonempty"
        if result.row_count
        else "success_empty"
    )
    return (
        PendingRawRequestSuccessV2(
            private_receipt_sha256=private_receipt,
            attempt=attempt,
            transport=(
                {"transport_kind": "static_snapshot"}
                if route.source_family == "static"
                else {
                    "transport_kind": f"{route.source_family}_http",
                    "status_code": 200,
                    "effective_status_code": 200,
                }
            ),
            started_at=_STARTED_AT,
            finished_at=_STARTED_AT + timedelta(seconds=1),
            elapsed_ns=1_000_000_000,
            outcome=outcome,
            body_disposition=(
                "declared_bodyless" if route.source_family == "static" else "public_parser_input"
            ),
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
        body,
    )


def _case(
    family: Literal["live", "stats", "static"],
    *,
    fallback: bool = False,
    retry_ordinal: int = 0,
) -> tuple[
    RawRequestCaptureSnapshotV2,
    LogicalCallReceiptBinding,
    tuple[CommittedStagingChunkReceiptV2, ...],
]:
    endpoint_name = {
        "live": "live_score_board",
        "stats": "league_game_log",
        "static": "static_players",
    }[family]
    endpoint_routes = tuple(
        sorted(
            (
                route
                for route in staging_route_contract_bundle().routes
                if route.endpoint_name == endpoint_name
            ),
            key=lambda item: item.ordinal,
        )
    )
    assert endpoint_routes
    route = endpoint_routes[0]
    provider_parameters: dict[str, object] = (
        {
            "season": "2024-25",
            "season_type_all_star": "Regular Season",
        }
        if family == "stats"
        else {}
    )
    conditional_route: str | None = None
    if family == "live":
        result_count = len(pinned_live_contracts()[route.provider_endpoint_id].result_sets)
        conditional_route = f"{endpoint_name}:{LIVE_LOSSLESS_STAGING_KEY}:{result_count}"
    elif fallback:
        result_count = len(pinned_runtime_contracts()[route.provider_endpoint_id].result_sets)
        conditional_route = f"{endpoint_name}:{LOSSLESS_FALLBACK_STAGING_KEY}:{result_count}"

    route_ids = tuple(
        sorted(
            (
                *(item.route_id for item in endpoint_routes),
                *((conditional_route,) if conditional_route else ()),
            )
        )
    )
    attempt = _attempt(route, parameters=provider_parameters, retry_ordinal=retry_ordinal)
    binding = LogicalCallReceiptBinding(
        logical_call_receipt_sha256=_LOGICAL_RECEIPT,
        endpoint_name=endpoint_name,
        logical_parameters_sha256=attempt.safe_parameters_sha256,
        provider_authority_sha256=staging_route_contract_bundle().provider_authority_sha256,
        result_route_ids=route_ids,
    )

    parser_input: bytes | None
    if family == "stats":
        contract = pinned_runtime_contracts()[route.provider_endpoint_id]
        required_values: dict[str, object] = {
            "SEASON_ID": "22024",
            "TEAM_ID": 1_610_612_747,
            "TEAM_ABBREVIATION": "LAL",
            "TEAM_NAME": "Los Angeles Lakers",
            "GAME_ID": "0022400001",
            "GAME_DATE": "2024-10-22",
            "MATCHUP": "LAL vs. MIN",
            "WL": "W",
        }
        provider_sets = [
            {
                "name": item.result_set_name,
                "headers": list(item.expected_columns),
                "rowSet": [[required_values.get(header) for header in item.expected_columns]],
            }
            for item in contract.result_sets
        ]
        if fallback:
            provider_sets.append({"name": "Extra", "headers": ["EXTRA"], "rowSet": [[9]]})
        parser_input = json.dumps(
            {"resultSets": provider_sets},
            separators=(",", ":"),
        ).encode()
    elif family == "live":
        parser_input = json.dumps(
            _complete_endpoint_payload(pinned_live_contracts()[route.provider_endpoint_id]),
            separators=(",", ":"),
        ).encode()
    else:
        parser_input = None

    result_derivations = rederive_raw_authority_result_sets(
        source_family=family,
        endpoint_id=route.provider_endpoint_id,
        parser_input=parser_input,
        provider_authority_sha256=binding.provider_authority_sha256,
        endpoint_contract_sha256_value=route.endpoint_contract_sha256,
    )
    body = (
        None
        if parser_input is None
        else ParserInputObjectV2.from_parser_input(parser_input.decode("utf-8"))
    )
    pending = PendingRawRequestSuccessV2(
        private_receipt_sha256="6" * 64,
        attempt=attempt,
        transport=(
            {"transport_kind": "static_snapshot"}
            if family == "static"
            else {
                "transport_kind": f"{family}_http",
                "status_code": 200,
                "effective_status_code": 200,
            }
        ),
        started_at=_STARTED_AT,
        finished_at=_STARTED_AT + timedelta(seconds=1),
        elapsed_ns=1_000_000_000,
        outcome=(
            "static_snapshot_success"
            if family == "static"
            else "success_nonempty"
            if any(item.result_set.row_count for item in result_derivations)
            else "success_empty"
        ),
        body_disposition="declared_bodyless" if family == "static" else "public_parser_input",
        body_object=body,
        results=tuple(
            PendingResultOccurrenceV2(
                result_set=item.result_set,
                duplicate_name_ordinal=item.duplicate_name_ordinal,
                ordered_headers=item.ordered_headers,
            )
            for item in result_derivations
        ),
        logical_receipt_sha256=binding.logical_call_receipt_sha256,
        aggregate_route_ids=binding.result_route_ids,
    )

    receipts: list[CommittedStagingChunkReceiptV2] = []
    if family in {"static", "live"}:
        frame_derivations = rederive_raw_authority_route_frames(
            source_family=family,
            endpoint_name=endpoint_name,
            endpoint_id=route.provider_endpoint_id,
            selected_route_ids=route_ids,
            parser_input=parser_input,
            safe_parameters_json=attempt.safe_parameters_json,
            provider_authority_sha256=binding.provider_authority_sha256,
            endpoint_contract_sha256_value=route.endpoint_contract_sha256,
            capture_response_receipt_sha256=pending.private_receipt_sha256,
            live_snapshot_at=_STARTED_AT if family == "live" else None,
        )
        receipts.extend(
            _committed_frame_receipt(
                binding,
                route_id=item.route_id,
                staging_key=item.staging_key,
                frame=item.frame,
            )
            for item in frame_derivations
        )
    else:
        safe_rows = (
            rederive_raw_authority_stats_wide_rows(
                endpoint_id=route.provider_endpoint_id,
                parser_input=cast("bytes", parser_input),
                provider_authority_sha256=binding.provider_authority_sha256,
                endpoint_contract_sha256_value=route.endpoint_contract_sha256,
            )
            if fallback
            else rederive_raw_authority_stats_rows(
                endpoint_id=route.provider_endpoint_id,
                parser_input=cast("bytes", parser_input),
                provider_authority_sha256=binding.provider_authority_sha256,
                endpoint_contract_sha256_value=route.endpoint_contract_sha256,
            )
        )
        for fixed_route in endpoint_routes:
            candidates = tuple(
                item
                for item in safe_rows
                if item.result_set.canonical_index == fixed_route.canonical_result_set_ordinal
                and item.ordered_headers == fixed_route.provider_columns
            )
            assert len(candidates) <= 1
            frame = (
                pl.DataFrame()
                if not candidates
                else _stats_frame(
                    fixed_route,
                    candidates[0],
                    safe_parameters_json=attempt.safe_parameters_json,
                )
            )
            receipts.append(
                _committed_frame_receipt(
                    binding,
                    route_id=fixed_route.route_id,
                    staging_key=fixed_route.staging_key,
                    frame=frame,
                )
            )
        if conditional_route is not None:
            fallback_frame = (
                rederive_raw_authority_stats_fallback(
                    endpoint_id=route.provider_endpoint_id,
                    parser_input=cast("bytes", parser_input),
                    provider_authority_sha256=binding.provider_authority_sha256,
                    endpoint_contract_sha256_value=route.endpoint_contract_sha256,
                )
                .bind_response_receipt(pending.private_receipt_sha256)
                .frame
            )
            receipts.append(
                _committed_frame_receipt(
                    binding,
                    route_id=conditional_route,
                    staging_key=LOSSLESS_FALLBACK_STAGING_KEY,
                    frame=fallback_frame,
                )
            )
    return (
        RawRequestCaptureSnapshotV2(
            objects=() if body is None else (body,),
            observations=(),
            pending_successes=(pending,),
            issues=(),
        ),
        binding,
        tuple(sorted(receipts, key=lambda item: item.result_route_id)),
    )


def _aliased_stats_case() -> tuple[
    RawRequestCaptureSnapshotV2,
    LogicalCallReceiptBinding,
    tuple[CommittedStagingChunkReceiptV2, ...],
    LogicalProviderParameterBindingV1,
]:
    snapshot, provider_binding, provider_receipts = _case("stats")
    attempt = snapshot.pending_successes[0].attempt
    logical_parameters = {
        "season": "2024-25",
        "season_type": "Regular Season",
    }
    logical_binding = replace(
        provider_binding,
        logical_parameters_sha256=canonical_parameters_sha256(logical_parameters),
    )
    logical_receipts = tuple(
        replace(
            receipt,
            logical_parameters_sha256=logical_binding.logical_parameters_sha256,
        )
        for receipt in provider_receipts
    )
    call = RawProviderCallContextV2(
        request_ordinal=attempt.request_ordinal,
        semantic_request_sha256=attempt.semantic_request_sha256,
        logical_invocation_sha256=attempt.logical_invocation_sha256,
        provider_call_role=attempt.provider_call_role,
        provider_call_ordinal=attempt.provider_call_ordinal,
        source_family=attempt.source_family,
        endpoint_id=attempt.endpoint_id,
        provider_request_sha256=attempt.provider_request_sha256,
        endpoint_contract_sha256=attempt.endpoint_contract_sha256,
        competition_id=attempt.competition_id,
        competition_identity_sha256=attempt.competition_identity_sha256,
        scope_sha256=attempt.scope_sha256,
        pagination_sha256=attempt.pagination_sha256,
        page_ordinal=attempt.page_ordinal,
    )
    context = RawRequestCaptureContextV2(
        provider_authority_sha256=attempt.provider_authority_sha256,
        source_sha=attempt.source_sha,
        run_id=attempt.run_id,
        run_attempt=attempt.run_attempt,
        chain_id=attempt.chain_id,
        lane_id=attempt.lane_id,
        provider_calls=(call,),
    )
    parameter_binding = compile_logical_provider_parameter_binding(
        raw_request_context=context,
        logical_endpoint_name=logical_binding.endpoint_name,
        logical_parameters=logical_parameters,
        result_route_ids=logical_binding.result_route_ids,
        provider_semantic_parameters=(json.loads(attempt.safe_parameters_json),),
    )
    assert logical_binding.logical_parameters_sha256 != attempt.safe_parameters_sha256
    return snapshot, logical_binding, logical_receipts, parameter_binding


def _aliased_stats_bundle() -> RawRequestAuthorityBundleV2:
    snapshot, binding, receipts, parameter_binding = _aliased_stats_case()
    return _finalize_raw_request_capture(
        snapshot,
        binding,
        receipts,
        logical_provider_parameter_binding=parameter_binding,
        expected_logical_provider_parameter_binding_sha256=(parameter_binding.binding_sha256),
    )


def _replace_live_payload(
    snapshot: RawRequestCaptureSnapshotV2,
    binding: LogicalCallReceiptBinding,
    payload: dict[str, object],
) -> tuple[RawRequestCaptureSnapshotV2, tuple[CommittedStagingChunkReceiptV2, ...]]:
    pending = snapshot.pending_successes[0]
    parser_input = json.dumps(payload, separators=(",", ":")).encode()
    body = ParserInputObjectV2.from_parser_input(parser_input.decode("utf-8"))
    derivations = rederive_raw_authority_result_sets(
        source_family="live",
        endpoint_id=pending.attempt.endpoint_id,
        parser_input=parser_input,
        provider_authority_sha256=pending.attempt.provider_authority_sha256,
        endpoint_contract_sha256_value=pending.attempt.endpoint_contract_sha256,
    )
    pending = replace(
        pending,
        body_object=body,
        outcome=(
            "success_nonempty"
            if any(item.result_set.row_count for item in derivations)
            else "success_empty"
        ),
        results=tuple(
            PendingResultOccurrenceV2(
                result_set=item.result_set,
                duplicate_name_ordinal=item.duplicate_name_ordinal,
                ordered_headers=item.ordered_headers,
            )
            for item in derivations
        ),
    )
    frame_derivations = rederive_raw_authority_route_frames(
        source_family="live",
        endpoint_name=binding.endpoint_name,
        endpoint_id=pending.attempt.endpoint_id,
        selected_route_ids=binding.result_route_ids,
        parser_input=parser_input,
        safe_parameters_json=pending.attempt.safe_parameters_json,
        provider_authority_sha256=pending.attempt.provider_authority_sha256,
        endpoint_contract_sha256_value=pending.attempt.endpoint_contract_sha256,
        capture_response_receipt_sha256=pending.private_receipt_sha256,
        live_snapshot_at=_STARTED_AT,
    )
    receipts = tuple(
        sorted(
            (
                _committed_frame_receipt(
                    binding,
                    route_id=item.route_id,
                    staging_key=item.staging_key,
                    frame=item.frame,
                )
                for item in frame_derivations
            ),
            key=lambda item: item.result_route_id,
        )
    )
    return (
        replace(snapshot, objects=(body,), pending_successes=(pending,)),
        receipts,
    )


def _replace_stats_payload(
    snapshot: RawRequestCaptureSnapshotV2,
    binding: LogicalCallReceiptBinding,
    payload: dict[str, object],
) -> tuple[RawRequestCaptureSnapshotV2, tuple[CommittedStagingChunkReceiptV2, ...]]:
    pending = snapshot.pending_successes[0]
    parser_input = json.dumps(payload, separators=(",", ":")).encode()
    body = ParserInputObjectV2.from_parser_input(parser_input.decode("utf-8"))
    derivations = rederive_raw_authority_result_sets(
        source_family="stats",
        endpoint_id=pending.attempt.endpoint_id,
        parser_input=parser_input,
        provider_authority_sha256=pending.attempt.provider_authority_sha256,
        endpoint_contract_sha256_value=pending.attempt.endpoint_contract_sha256,
    )
    pending = replace(
        pending,
        body_object=body,
        outcome=(
            "success_nonempty"
            if any(item.result_set.row_count for item in derivations)
            else "success_empty"
        ),
        results=tuple(
            PendingResultOccurrenceV2(
                result_set=item.result_set,
                duplicate_name_ordinal=item.duplicate_name_ordinal,
                ordered_headers=item.ordered_headers,
            )
            for item in derivations
        ),
    )
    fixed_routes = tuple(
        sorted(
            (
                route
                for route in staging_route_contract_bundle().routes
                if route.route_id in binding.result_route_ids
            ),
            key=lambda item: item.ordinal,
        )
    )
    conditional_route_ids = tuple(
        route_id
        for route_id in binding.result_route_ids
        if route_id not in {route.route_id for route in fixed_routes}
    )
    fallback = bool(conditional_route_ids)
    safe_rows = (
        rederive_raw_authority_stats_wide_rows(
            endpoint_id=pending.attempt.endpoint_id,
            parser_input=parser_input,
            provider_authority_sha256=pending.attempt.provider_authority_sha256,
            endpoint_contract_sha256_value=pending.attempt.endpoint_contract_sha256,
        )
        if fallback
        else rederive_raw_authority_stats_rows(
            endpoint_id=pending.attempt.endpoint_id,
            parser_input=parser_input,
            provider_authority_sha256=pending.attempt.provider_authority_sha256,
            endpoint_contract_sha256_value=pending.attempt.endpoint_contract_sha256,
        )
    )
    receipts: list[CommittedStagingChunkReceiptV2] = []
    for route in fixed_routes:
        candidates = tuple(
            item
            for item in safe_rows
            if item.result_set.canonical_index == route.canonical_result_set_ordinal
            and item.ordered_headers == route.provider_columns
        )
        assert len(candidates) <= 1
        frame = (
            pl.DataFrame()
            if not candidates
            else _stats_frame(
                route,
                candidates[0],
                safe_parameters_json=pending.attempt.safe_parameters_json,
            )
        )
        receipts.append(
            _committed_frame_receipt(
                binding,
                route_id=route.route_id,
                staging_key=route.staging_key,
                frame=frame,
            )
        )
    if conditional_route_ids:
        assert len(conditional_route_ids) == 1
        fallback_frame = (
            rederive_raw_authority_stats_fallback(
                endpoint_id=pending.attempt.endpoint_id,
                parser_input=parser_input,
                provider_authority_sha256=pending.attempt.provider_authority_sha256,
                endpoint_contract_sha256_value=pending.attempt.endpoint_contract_sha256,
            )
            .bind_response_receipt(pending.private_receipt_sha256)
            .frame
        )
        receipts.append(
            _committed_frame_receipt(
                binding,
                route_id=conditional_route_ids[0],
                staging_key=LOSSLESS_FALLBACK_STAGING_KEY,
                frame=fallback_frame,
            )
        )
    return (
        replace(snapshot, objects=(body,), pending_successes=(pending,)),
        tuple(sorted(receipts, key=lambda item: item.result_route_id)),
    )


def _stats_fallback_case(
    endpoint_name: str,
    payload: dict[str, object],
) -> tuple[
    RawRequestCaptureSnapshotV2,
    LogicalCallReceiptBinding,
    tuple[CommittedStagingChunkReceiptV2, ...],
]:
    routes = tuple(
        route
        for route in staging_route_contract_bundle().routes
        if route.endpoint_name == endpoint_name
    )
    assert routes and all(route.source_family == "stats" for route in routes)
    provider_endpoint_id = routes[0].provider_endpoint_id
    contract = pinned_runtime_contracts()[provider_endpoint_id]
    conditional_route = (
        f"{endpoint_name}:{LOSSLESS_FALLBACK_STAGING_KEY}:{len(contract.result_sets)}"
    )
    route_ids = tuple(sorted((*[route.route_id for route in routes], conditional_route)))
    attempt = _attempt(routes[0], parameters={})
    binding = LogicalCallReceiptBinding(
        logical_call_receipt_sha256=_LOGICAL_RECEIPT,
        endpoint_name=endpoint_name,
        logical_parameters_sha256=attempt.safe_parameters_sha256,
        provider_authority_sha256=staging_route_contract_bundle().provider_authority_sha256,
        result_route_ids=route_ids,
    )
    parser_input = json.dumps(payload, separators=(",", ":"))
    body = ParserInputObjectV2.from_parser_input(parser_input)
    derivations = rederive_raw_authority_result_sets(
        source_family="stats",
        endpoint_id=provider_endpoint_id,
        parser_input=parser_input.encode(),
        provider_authority_sha256=binding.provider_authority_sha256,
        endpoint_contract_sha256_value=routes[0].endpoint_contract_sha256,
    )
    pending = PendingRawRequestSuccessV2(
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
        results=tuple(
            PendingResultOccurrenceV2(
                result_set=item.result_set,
                duplicate_name_ordinal=item.duplicate_name_ordinal,
                ordered_headers=item.ordered_headers,
            )
            for item in derivations
        ),
        logical_receipt_sha256=binding.logical_call_receipt_sha256,
        aggregate_route_ids=binding.result_route_ids,
    )
    snapshot = RawRequestCaptureSnapshotV2(
        objects=(body,),
        observations=(),
        pending_successes=(pending,),
        issues=(),
    )
    rebuilt_snapshot, receipts = _replace_stats_payload(snapshot, binding, payload)
    return rebuilt_snapshot, binding, receipts


def _unknown_stats_case(
    endpoint_name: str,
    payload: dict[str, object],
    *,
    include_results: bool = True,
) -> tuple[
    RawRequestCaptureSnapshotV2,
    LogicalCallReceiptBinding,
    tuple[CommittedStagingChunkReceiptV2, ...],
]:
    route = _route(endpoint_name)
    parameters = (
        {"game_id": "0022400001", "game_event_id": 7}
        if route.provider_endpoint_id in {"VideoEvents", "VideoEventsAsset"}
        else {"team_id": 1, "player_id": 2, "season": "2024-25"}
    )
    attempt = _attempt(route, parameters=parameters)
    parser_input = json.dumps(payload, separators=(",", ":"))
    body = ParserInputObjectV2.from_parser_input(parser_input)
    unknown = rederive_raw_authority_unknown_stats_response(
        endpoint_id=route.provider_endpoint_id,
        parser_input=parser_input.encode(),
        safe_parameters_json=attempt.safe_parameters_json,
        provider_authority_sha256=attempt.provider_authority_sha256,
        endpoint_contract_sha256_value=attempt.endpoint_contract_sha256,
    )
    duplicate_names: dict[str, int] = {}
    results: list[PendingResultOccurrenceV2] = []
    for item in unknown.occurrences:
        duplicate_ordinal = duplicate_names.get(item.name, 0)
        duplicate_names[item.name] = duplicate_ordinal + 1
        results.append(
            PendingResultOccurrenceV2(
                result_set=item.receipt,
                duplicate_name_ordinal=duplicate_ordinal,
                ordered_headers=item.headers,
            )
        )
    if include_results:
        assert results
    else:
        assert not results
    private_receipt_sha256 = "6" * 64
    fallback = build_unknown_stats_lossless_fallback(
        unknown.bind_response_receipt(private_receipt_sha256)
    )
    conditional_route = f"{endpoint_name}:{LOSSLESS_FALLBACK_STAGING_KEY}:0"
    route_ids = [route.route_id]
    if fallback is not None:
        route_ids.append(conditional_route)
    binding = LogicalCallReceiptBinding(
        logical_call_receipt_sha256=_LOGICAL_RECEIPT,
        endpoint_name=endpoint_name,
        logical_parameters_sha256=attempt.safe_parameters_sha256,
        provider_authority_sha256=attempt.provider_authority_sha256,
        result_route_ids=tuple(sorted(route_ids)),
    )
    pending = PendingRawRequestSuccessV2(
        private_receipt_sha256=private_receipt_sha256,
        attempt=attempt,
        transport={
            "transport_kind": "stats_http",
            "status_code": 200,
            "effective_status_code": 200,
        },
        started_at=_STARTED_AT,
        finished_at=_STARTED_AT + timedelta(seconds=1),
        elapsed_ns=1_000_000_000,
        outcome=unknown.outcome,
        body_disposition="public_parser_input",
        body_object=body,
        results=tuple(results),
        logical_receipt_sha256=binding.logical_call_receipt_sha256,
        aggregate_route_ids=binding.result_route_ids,
    )
    receipts = [
        _committed_frame_receipt(
            binding,
            route_id=route.route_id,
            staging_key=route.staging_key,
            frame=(
                fallback.frame
                if route.provider_endpoint_id in {"VideoEvents", "VideoEventsAsset"}
                and fallback is not None
                else pl.DataFrame()
            ),
        )
    ]
    if fallback is not None:
        receipts.append(
            _committed_frame_receipt(
                binding,
                route_id=conditional_route,
                staging_key=LOSSLESS_FALLBACK_STAGING_KEY,
                frame=fallback.frame,
            )
        )
    issue = (
        ()
        if include_results
        else (
            RawRequestCaptureIssueV2(
                code="success_result_authority_pending",
                retry_ordinal=pending.attempt.retry_ordinal,
                request_ordinal=pending.attempt.request_ordinal,
                root_exception_class=None,
            ),
        )
    )
    return (
        RawRequestCaptureSnapshotV2(
            objects=(body,),
            observations=(),
            pending_successes=(pending,),
            issues=issue,
        ),
        binding,
        tuple(sorted(receipts, key=lambda item: item.result_route_id)),
    )


@pytest.mark.parametrize(
    ("family", "fallback", "expected_landing"),
    [
        ("live", False, "wide_plus_lossless"),
        ("stats", False, "wide_only"),
        ("stats", True, "wide_plus_lossless"),
        ("static", False, "wide_only"),
    ],
)
def test_finalizes_supported_route_families(
    family: Literal["live", "stats", "static"],
    fallback: bool,
    expected_landing: str,
) -> None:
    snapshot, binding, receipts = _case(family, fallback=fallback)

    bundle = finalize_raw_request_capture(snapshot, binding, receipts)

    assert len(bundle.observations) == 1
    assert len(bundle.occurrences) == len(snapshot.pending_successes[0].results)
    assert bundle.observations[0].lifecycle == "selected_terminal"
    assert (
        bundle.observations[0].capture_response_receipt_sha256
        == snapshot.pending_successes[0].private_receipt_sha256
    )
    assert bundle.observations[0].logical_receipt_sha256 == _LOGICAL_RECEIPT
    assert expected_landing in {item.landing_disposition for item in bundle.occurrences}
    assert {
        route_id
        for item in bundle.occurrences
        for route_id in json.loads(item.canonical_route_ids_json)
    } == set(binding.result_route_ids)
    assert {
        item["receipt_sha256"]
        for occurrence in bundle.occurrences
        for item in json.loads(occurrence.committed_staging_receipts_json)
    } == {item.receipt_root_sha256 for item in receipts}
    assert tuple(item.route_id for item in bundle.landings) == tuple(
        [
            route.route_id
            for route in sorted(
                (
                    route
                    for route in staging_route_contract_bundle().routes
                    if route.endpoint_name == binding.endpoint_name
                ),
                key=lambda item: item.ordinal,
            )
        ]
        + [
            route_id
            for route_id in binding.result_route_ids
            if route_id
            not in {
                route.route_id
                for route in staging_route_contract_bundle().routes
                if route.endpoint_name == binding.endpoint_name
            }
        ]
    )
    assert {item.receipt_root_sha256 for item in bundle.landings} == {
        item.receipt_root_sha256 for item in receipts
    }
    assert all(
        item.live_snapshot_at == (_STARTED_AT if family == "live" else None)
        for item in bundle.landings
    )
    bundle.require_complete_terminal_selection()


def test_live_plan_authority_is_required_and_receipt_bound() -> None:
    snapshot, binding, receipts = _case("live")
    authority = _live_plan_authority(snapshot, binding)

    with pytest.raises(RawRequestFinalizationError, match="sealed-plan authority"):
        _finalize_raw_request_capture(snapshot, binding, receipts)
    with pytest.raises(RawRequestFinalizationError, match="bare live plan timestamp"):
        _finalize_raw_request_capture(
            snapshot,
            binding,
            receipts,
            plan_live_snapshot_at=_STARTED_AT,
        )
    with pytest.raises(RawRequestFinalizationError, match="independent sealed-plan"):
        _finalize_raw_request_capture(
            snapshot,
            binding,
            receipts,
            live_plan_authority=authority,
        )
    with pytest.raises(RawRequestFinalizationError, match="independent receipt"):
        _finalize_raw_request_capture(
            snapshot,
            binding,
            receipts,
            live_plan_authority=authority,
            expected_live_plan_authority_sha256="f" * 64,
        )
    with pytest.raises(RawRequestFinalizationError, match="route-frame rederivation"):
        wrong_time = _live_plan_authority(
            snapshot,
            binding,
            snapshot_at=_STARTED_AT + timedelta(microseconds=1),
        )
        _finalize_raw_request_capture(
            snapshot,
            binding,
            receipts,
            live_plan_authority=wrong_time,
            expected_live_plan_authority_sha256=wrong_time.authority_sha256,
        )
    with pytest.raises(RawRequestFinalizationError, match="independent receipt"):
        resealed = _live_plan_authority(
            snapshot,
            binding,
            sealed_plan_bytes=b'{"kind":"foreign_live_sealed_plan_v2"}',
        )
        _finalize_raw_request_capture(
            snapshot,
            binding,
            receipts,
            live_plan_authority=resealed,
            expected_live_plan_authority_sha256=authority.authority_sha256,
        )
    foreign_attempt = _attempt(
        _route("live_score_board"),
        parameters={},
        lane_id="foreign-lane",
    )
    foreign_snapshot = replace(
        snapshot,
        pending_successes=(replace(snapshot.pending_successes[0], attempt=foreign_attempt),),
    )
    foreign_authority = _live_plan_authority(foreign_snapshot, binding)
    with pytest.raises(RawRequestFinalizationError, match="crosses its exact request"):
        _finalize_raw_request_capture(
            snapshot,
            binding,
            receipts,
            live_plan_authority=foreign_authority,
            expected_live_plan_authority_sha256=foreign_authority.authority_sha256,
        )
    missing_route_authority = LiveSnapshotPlanAuthorityV2.build(
        sealed_plan_bytes=b'{"kind":"missing_route_live_sealed_plan_v2"}',
        attempt=snapshot.pending_successes[0].attempt,
        route_ids=authority.route_ids[:-1],
        live_snapshot_at=_STARTED_AT,
    )
    with pytest.raises(RawRequestFinalizationError, match="route inventory"):
        _finalize_raw_request_capture(
            snapshot,
            binding,
            receipts,
            live_plan_authority=missing_route_authority,
            expected_live_plan_authority_sha256=(missing_route_authority.authority_sha256),
        )
    split_timestamp = _SplitAuthorityDatetime(
        2099,
        1,
        1,
        tzinfo=UTC,
    )
    split_authority = _live_plan_authority(
        snapshot,
        binding,
        snapshot_at=split_timestamp,
    )
    with pytest.raises(RawRequestFinalizationError, match="exact built-in UTC datetime"):
        _finalize_raw_request_capture(
            snapshot,
            binding,
            receipts,
            live_plan_authority=split_authority,
            expected_live_plan_authority_sha256=split_authority.authority_sha256,
        )

    bundle = _finalize_raw_request_capture(
        snapshot,
        binding,
        receipts,
        live_plan_authority=authority,
        expected_live_plan_authority_sha256=authority.authority_sha256,
    )
    assert {item.live_snapshot_at for item in bundle.landings} == {_STARTED_AT}


def test_non_live_closure_rejects_live_plan_inputs() -> None:
    snapshot, binding, receipts = _case("static")

    with pytest.raises(RawRequestFinalizationError, match="bare live plan timestamp"):
        _finalize_raw_request_capture(
            snapshot,
            binding,
            receipts,
            plan_live_snapshot_at=_STARTED_AT,
        )
    live_snapshot, live_binding, _live_receipts = _case("live")
    live_authority = _live_plan_authority(live_snapshot, live_binding)
    with pytest.raises(RawRequestFinalizationError, match="non-live request closure"):
        _finalize_raw_request_capture(
            snapshot,
            binding,
            receipts,
            live_plan_authority=live_authority,
            expected_live_plan_authority_sha256=live_authority.authority_sha256,
        )


def _franchise_history_fallback_payload(variant: str) -> dict[str, object]:
    contract = pinned_runtime_contracts()["FranchiseHistory"]
    required_values: dict[str, object] = {
        "LEAGUE_ID": "00",
        "TEAM_ID": 1_610_612_747,
    }
    result_sets: list[dict[str, object]] = [
        {
            "name": item.result_set_name,
            "headers": list(item.expected_columns),
            "rowSet": [[required_values.get(header) for header in item.expected_columns]],
        }
        for item in contract.result_sets
    ]
    if variant == "header_drift":
        headers = result_sets[0]["headers"]
        rows = result_sets[0]["rowSet"]
        assert isinstance(headers, list) and isinstance(rows, list)
        headers.append("ADDITIVE")
        rows[0].append(None)
    elif variant == "missing_result":
        result_sets.pop()
    elif variant == "heterogeneous":
        headers = result_sets[0]["headers"]
        assert isinstance(headers, list)
        first = [None for _header in headers]
        second = [None for _header in headers]
        first[0] = 1
        second[0] = "one"
        result_sets[0]["rowSet"] = [first, second]
    elif variant == "duplicate_name":
        result_sets.insert(1, deepcopy(result_sets[0]))
    elif variant == "additive_result":
        result_sets.append({"name": "Additive", "headers": ["EXTRA"], "rowSet": [[9]]})
    else:
        raise AssertionError(f"unknown stats fallback variant: {variant}")
    return {"resultSets": result_sets}


@pytest.mark.parametrize(
    ("variant", "wide_admitted"),
    [
        ("header_drift", False),
        ("missing_result", False),
        ("heterogeneous", False),
        ("duplicate_name", False),
        ("additive_result", True),
    ],
)
def test_stats_fallback_wide_membership_is_response_wide_and_body_rederived(
    variant: str,
    wide_admitted: bool,
) -> None:
    snapshot, binding, receipts = _stats_fallback_case(
        "franchise_history",
        _franchise_history_fallback_payload(variant),
    )

    bundle = finalize_raw_request_capture(snapshot, binding, receipts)

    wide_route_ids = {
        route_id
        for route_id in binding.result_route_ids
        if LOSSLESS_FALLBACK_STAGING_KEY not in route_id
    }
    conditional_route_id = next(
        route_id
        for route_id in binding.result_route_ids
        if LOSSLESS_FALLBACK_STAGING_KEY in route_id
    )
    for occurrence in bundle.occurrences:
        route_ids = set(json.loads(occurrence.canonical_route_ids_json))
        if route_ids & wide_route_ids:
            assert occurrence.landing_disposition == (
                "wide_plus_lossless" if wide_admitted else "lossless_only"
            )
        else:
            assert route_ids == {conditional_route_id}
            assert occurrence.landing_disposition == "lossless_only"
    assert all(
        (receipt.persisted_row_count > 0) == wide_admitted
        for receipt in receipts
        if receipt.result_route_id in wide_route_ids
    )

    if variant == "missing_result":
        missing = next(item for item in bundle.occurrences if item.presence == "missing")
        assert missing.provider_result_ordinal is None
        assert missing.canonical_result_ordinal is None
        assert set(json.loads(missing.canonical_route_ids_json)) & wide_route_ids
    if variant == "duplicate_name":
        repeated = [
            item
            for item in bundle.occurrences
            if item.result_name == bundle.occurrences[0].result_name
        ]
        assert [item.duplicate_name_ordinal for item in repeated] == [0, 1]
        assert set(json.loads(repeated[0].canonical_route_ids_json)) & wide_route_ids
        assert set(json.loads(repeated[1].canonical_route_ids_json)) == {conditional_route_id}

    if not wide_admitted:
        wide_receipt = next(
            receipt for receipt in receipts if receipt.result_route_id in wide_route_ids
        )
        forged_receipts = tuple(
            replace(receipt, persisted_row_count=1)
            if receipt.result_route_id == wide_receipt.result_route_id
            else receipt
            for receipt in receipts
        )
        with pytest.raises(RawRequestFinalizationError, match="wide staging"):
            finalize_raw_request_capture(snapshot, binding, forged_receipts)


@pytest.mark.parametrize(
    "endpoint_name",
    [
        "video_details",
        "video_details_asset",
        "video_events",
        "video_events_asset",
    ],
)
def test_unknown_video_legacy_results_use_exact_response_level_route_policy(
    endpoint_name: str,
) -> None:
    snapshot, binding, receipts = _unknown_stats_case(
        endpoint_name,
        {
            "resultSets": [
                {"name": "Observed", "headers": [], "rowSet": [[]]},
                {"name": "Observed", "headers": ["A"], "rowSet": [[1]]},
            ]
        },
    )

    bundle = finalize_raw_request_capture(snapshot, binding, receipts)

    conditional_route = next(
        route_id
        for route_id in binding.result_route_ids
        if LOSSLESS_FALLBACK_STAGING_KEY in route_id
    )
    assert [item.duplicate_name_ordinal for item in bundle.occurrences] == [0, 1]
    assert [item.provider_result_ordinal for item in bundle.occurrences] == [0, 1]
    assert all(
        json.loads(item.canonical_route_ids_json) == [conditional_route]
        and item.landing_disposition == "lossless_only"
        for item in bundle.occurrences
    )
    fixed_receipt = next(item for item in receipts if item.result_route_id != conditional_route)
    conditional_receipt = next(
        item for item in receipts if item.result_route_id == conditional_route
    )
    if endpoint_name in {"video_details", "video_details_asset"}:
        assert fixed_receipt.persisted_row_count == 0
    else:
        assert fixed_receipt.persisted_row_count == conditional_receipt.persisted_row_count
        assert fixed_receipt.content_hash == conditional_receipt.content_hash
        assert fixed_receipt.persisted_schema_sha256 == (
            conditional_receipt.persisted_schema_sha256
        )
    bundle.require_complete_terminal_selection()


@pytest.mark.parametrize("endpoint_name", ["video_details", "video_events"])
def test_unknown_video_zero_occurrence_success_retains_every_route_landing(
    endpoint_name: str,
) -> None:
    snapshot, binding, receipts = _unknown_stats_case(
        endpoint_name,
        {"asset": {"metadata": {}, "url": "https://example.invalid/opaque"}},
        include_results=False,
    )

    bundle = finalize_raw_request_capture(replace(snapshot, issues=()), binding, receipts)

    assert bundle.occurrences == ()
    assert {item.route_id for item in bundle.landings} == {
        item.result_route_id for item in receipts
    }
    assert all(item.source_occurrence_count == 0 for item in bundle.landings)
    assert bundle.landings[0].landing_semantic == (
        "response_fixed_zero" if endpoint_name == "video_details" else "response_canonical_alias"
    )
    assert bundle.landings[1].landing_semantic == "conditional_lossless"
    bundle.require_complete_terminal_selection()


@pytest.mark.parametrize(
    "endpoint_name",
    [
        "video_details",
        "video_details_asset",
        "video_events",
        "video_events_asset",
    ],
)
def test_unknown_video_zero_occurrence_no_drift_retains_fixed_zero_landing(
    endpoint_name: str,
) -> None:
    snapshot, binding, receipts = _unknown_stats_case(
        endpoint_name,
        {},
        include_results=False,
    )

    bundle = finalize_raw_request_capture(replace(snapshot, issues=()), binding, receipts)

    assert bundle.occurrences == ()
    assert len(bundle.landings) == 1
    assert bundle.landings[0].route_id == receipts[0].result_route_id
    assert bundle.landings[0].landing_semantic == "response_fixed_zero"
    assert bundle.landings[0].source_occurrence_count == 0
    assert bundle.landings[0].persisted_row_count == 0
    bundle.require_complete_terminal_selection()


@pytest.mark.parametrize(
    ("endpoint_name", "mutation"),
    [
        ("video_details", "fixed_positive"),
        ("video_details", "fixed_content"),
        ("video_details", "fixed_schema"),
        ("video_events", "fixed_zero"),
        ("video_events", "fixed_content"),
        ("video_events", "conditional_content"),
    ],
)
def test_unknown_video_route_policy_rejects_forged_receipts(
    endpoint_name: str,
    mutation: str,
) -> None:
    snapshot, binding, receipts = _unknown_stats_case(
        endpoint_name,
        {"resultSets": [{"name": "Observed", "headers": ["A"], "rowSet": [[1]]}]},
    )
    conditional_route = next(
        route_id
        for route_id in binding.result_route_ids
        if LOSSLESS_FALLBACK_STAGING_KEY in route_id
    )
    fixed_route = next(
        route_id for route_id in binding.result_route_ids if route_id != conditional_route
    )
    forged = []
    for receipt in receipts:
        if mutation == "fixed_positive" and receipt.result_route_id == fixed_route:
            receipt = replace(receipt, persisted_row_count=1)
        elif mutation == "fixed_zero" and receipt.result_route_id == fixed_route:
            receipt = replace(receipt, persisted_row_count=0)
        elif mutation == "fixed_content" and receipt.result_route_id == fixed_route:
            receipt = replace(
                receipt,
                content_hash="a" * 64,
                persisted_content_sha256="a" * 64,
            )
        elif mutation == "fixed_schema" and receipt.result_route_id == fixed_route:
            receipt = replace(receipt, persisted_schema_sha256="c" * 64)
        elif mutation == "conditional_content" and receipt.result_route_id == conditional_route:
            receipt = replace(
                receipt,
                content_hash="b" * 64,
                persisted_content_sha256="b" * 64,
            )
        forged.append(receipt)

    with pytest.raises(RawRequestFinalizationError):
        finalize_raw_request_capture(snapshot, binding, tuple(forged))


def test_preserves_incomplete_retry_before_unique_terminal_selection() -> None:
    snapshot, binding, receipts = _case("live", retry_ordinal=1)
    route = _route("live_score_board")
    failed_attempt = _attempt(route, parameters={}, retry_ordinal=0)
    failed = RequestObservationV2.build(
        attempt=failed_attempt,
        transport={"transport_kind": "live_http"},
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
    snapshot = replace(snapshot, observations=(failed,))

    bundle = finalize_raw_request_capture(snapshot, binding, receipts)

    assert [item.attempt.retry_ordinal for item in bundle.observations] == [0, 1]
    assert [item.lifecycle for item in bundle.observations] == ["incomplete", "selected_terminal"]


def test_capture_issue_blocks_finalization() -> None:
    snapshot, binding, receipts = _case("live")
    snapshot = replace(
        snapshot,
        issues=(
            RawRequestCaptureIssueV2(
                code="capture_unavailable",
                retry_ordinal=0,
                request_ordinal=0,
                root_exception_class="ValueError",
            ),
        ),
    )

    with pytest.raises(RawRequestFinalizationError, match="unresolved capture issues"):
        finalize_raw_request_capture(snapshot, binding, receipts)


@pytest.mark.parametrize("mutation", ["missing", "duplicate", "foreign"])
def test_missing_duplicate_or_foreign_committed_receipt_blocks(mutation: str) -> None:
    snapshot, binding, receipts = _case("live")
    if mutation == "missing":
        receipts = receipts[:-1]
    elif mutation == "duplicate":
        receipts = (*receipts, receipts[0])
    else:
        receipts = (
            replace(receipts[0], result_route_id="foreign:stg_foreign:0"),
            *receipts[1:],
        )

    with pytest.raises(RawRequestFinalizationError, match="receipt"):
        finalize_raw_request_capture(snapshot, binding, receipts)


def test_receipt_parameter_or_wide_row_mutation_blocks() -> None:
    snapshot, binding, receipts = _case("stats")

    with pytest.raises(RawRequestFinalizationError, match="crosses logical"):
        finalize_raw_request_capture(
            snapshot,
            binding,
            (replace(receipts[0], logical_parameters_sha256="8" * 64),),
        )
    with pytest.raises(RawRequestFinalizationError, match="row count"):
        finalize_raw_request_capture(
            snapshot,
            binding,
            (replace(receipts[0], persisted_row_count=2),),
        )


@pytest.mark.parametrize("mutation", ["content", "schema"])
def test_stats_fixed_route_hash_reseal_cannot_fabricate_a_landing(mutation: str) -> None:
    snapshot, binding, receipts = _case("stats")
    receipt = receipts[0]
    forged = (
        replace(
            receipt,
            content_hash="a" * 64,
            persisted_content_sha256="a" * 64,
        )
        if mutation == "content"
        else replace(receipt, persisted_schema_sha256="b" * 64)
    )

    with pytest.raises(RawRequestFinalizationError, match="not closed"):
        finalize_raw_request_capture(snapshot, binding, (forged,))


def test_cross_context_attempt_and_orphan_object_block() -> None:
    snapshot, binding, receipts = _case("live")
    route = _route("live_score_board")
    foreign_attempt = _attempt(route, parameters={}, retry_ordinal=1, lane_id="foreign")
    foreign = RequestObservationV2.build(
        attempt=foreign_attempt,
        transport={"transport_kind": "live_http"},
        started_at=_STARTED_AT,
        finished_at=_STARTED_AT + timedelta(milliseconds=1),
        elapsed_ns=1_000_000,
        lifecycle="incomplete",
        outcome="transport_failure_no_response",
        failure_class="transport_transient",
        root_exception_class="ConnectionError",
        body_disposition="no_response",
        body_object_sha256=None,
        bodyless_evidence_sha256="9" * 64,
        result_occurrence_sha256s=(),
        route_landing_sha256s=(),
        capture_response_receipt_sha256=None,
        logical_receipt_sha256=None,
    )
    with pytest.raises(RawRequestFinalizationError, match="cross logical execution contexts"):
        finalize_raw_request_capture(
            replace(snapshot, observations=(foreign,)),
            binding,
            receipts,
        )

    orphan = ParserInputObjectV2.from_parser_input('{"orphan":true}')
    with pytest.raises(RawRequestFinalizationError, match="orphan"):
        finalize_raw_request_capture(
            replace(snapshot, objects=(*snapshot.objects, orphan)),
            binding,
            receipts,
        )


def test_duplicate_result_identity_is_ambiguous_for_one_wide_route() -> None:
    snapshot, binding, receipts = _case("live")
    pending = snapshot.pending_successes[0]
    duplicate = replace(pending.results[0], duplicate_name_ordinal=1)
    pending = replace(pending, results=(*pending.results, duplicate))

    with pytest.raises(RawRequestFinalizationError, match="exact pinned endpoint"):
        finalize_raw_request_capture(
            replace(snapshot, pending_successes=(pending,)),
            binding,
            receipts,
        )


def test_live_result_path_mutation_cannot_reuse_a_pinned_result_identity() -> None:
    snapshot, binding, receipts = _case("live")
    pending = snapshot.pending_successes[0]
    first = pending.results[0]
    mutated = replace(
        first,
        result_set=replace(first.result_set, json_path="$.foreign"),
    )

    with pytest.raises(RawRequestFinalizationError, match="exact pinned endpoint"):
        finalize_raw_request_capture(
            replace(
                snapshot,
                pending_successes=(replace(pending, results=(mutated, *pending.results[1:])),),
            ),
            binding,
            receipts,
        )


def test_exact_empty_array_presence_and_wide_row_count_are_derived() -> None:
    snapshot, binding, _receipts = _case("live")
    contract = pinned_live_contracts()[snapshot.pending_successes[0].attempt.endpoint_id]
    payload = _complete_endpoint_payload(contract)
    scoreboard = cast("dict[str, object]", payload["scoreboard"])
    scoreboard["games"] = []
    snapshot, receipts = _replace_live_payload(snapshot, binding, payload)

    bundle = finalize_raw_request_capture(snapshot, binding, receipts)

    occurrence = next(item for item in bundle.occurrences if item.result_name == "scoreboard_games")
    assert occurrence.presence == "empty_array"
    assert occurrence.row_count == occurrence.cell_count == 0
    assert occurrence.node_count == 1
    assert occurrence.container_count == 1


def test_exact_empty_stats_result_presence_is_derived() -> None:
    snapshot, binding, _receipts = _case("stats")
    pending = snapshot.pending_successes[0]
    payload = json.loads(
        decode_parser_input_object(cast("ParserInputObjectV2", pending.body_object))
    )
    result_sets = cast("list[dict[str, object]]", payload["resultSets"])
    for result_set in result_sets:
        result_set["rowSet"] = []
    snapshot, receipts = _replace_stats_payload(snapshot, binding, payload)
    selected = snapshot.pending_successes[0].results[0]

    bundle = finalize_raw_request_capture(snapshot, binding, receipts)

    assert bundle.occurrences[0].presence == "present_empty"
    assert json.loads(bundle.occurrences[0].ordered_headers_json) == list(selected.ordered_headers)
    assert bundle.occurrences[0].row_count == bundle.occurrences[0].cell_count == 0


def test_zero_parent_live_child_derives_exact_not_observed_presence() -> None:
    snapshot, binding, _receipts = _case("live")
    contract = pinned_live_contracts()[snapshot.pending_successes[0].attempt.endpoint_id]
    payload = _complete_endpoint_payload(contract)
    scoreboard = cast("dict[str, object]", payload["scoreboard"])
    scoreboard["games"] = []
    snapshot, receipts = _replace_live_payload(snapshot, binding, payload)

    bundle = finalize_raw_request_capture(snapshot, binding, receipts)

    occurrence = next(
        item for item in bundle.occurrences if item.result_name == "scoreboard_games_hometeam"
    )
    assert occurrence.presence == "not_observed_parent_empty"
    assert occurrence.parent_state_sha256 == parent_occurrence_states_digest(())
    expected = next(
        item
        for item in snapshot.pending_successes[0].results
        if item.result_set.name == occurrence.result_name
    )
    assert json.loads(occurrence.ordered_headers_json) == list(expected.ordered_headers)
    assert (
        occurrence.row_count
        == occurrence.cell_count
        == occurrence.node_count
        == occurrence.container_count
        == occurrence.missing_count
        == occurrence.null_count
        == 0
    )
    bundle.require_complete_terminal_selection()


def test_zero_parent_live_root_cannot_claim_child_not_observed_state() -> None:
    snapshot, binding, receipts = _case("live")
    pending = snapshot.pending_successes[0]
    selected = pending.results[0]
    zero_parent_root = replace(
        selected,
        result_set=replace(
            selected.result_set,
            row_count=0,
            container_count=0,
            parent_observation_count=0,
            parent_occurrence_states_sha256=parent_occurrence_states_digest(()),
            normalized_output_sha256=_sha("zero-parent-live-root"),
        ),
    )

    with pytest.raises(RawRequestFinalizationError, match="exact pinned endpoint"):
        finalize_raw_request_capture(
            replace(
                snapshot,
                pending_successes=(
                    replace(
                        pending,
                        results=(zero_parent_root, *pending.results[1:]),
                    ),
                ),
            ),
            binding,
            receipts,
        )


def test_missing_live_child_preserves_existing_missing_semantics() -> None:
    snapshot, binding, _receipts = _case("live")
    contract = pinned_live_contracts()[snapshot.pending_successes[0].attempt.endpoint_id]
    payload = _complete_endpoint_payload(contract)
    scoreboard = cast("dict[str, object]", payload["scoreboard"])
    games = cast("list[dict[str, object]]", scoreboard["games"])
    games[0].pop("pbOdds")
    snapshot, receipts = _replace_live_payload(snapshot, binding, payload)

    bundle = finalize_raw_request_capture(snapshot, binding, receipts)

    occurrence = next(
        item for item in bundle.occurrences if item.result_name == "scoreboard_games_pbodds"
    )
    assert occurrence.presence == "missing"
    assert occurrence.missing_count == 1
    assert occurrence.container_count == occurrence.null_count == 0


def _mixed_live_parent_bundle(
    parent_states: tuple[Literal["missing", "null"], Literal["missing", "null"]],
) -> tuple[RawRequestAuthorityBundleV2, ParserInputObjectV2]:
    assert set(parent_states) == {"missing", "null"}
    snapshot, binding, receipts = _case("live")
    pending = snapshot.pending_successes[0]
    contract = pinned_live_contracts()[pending.attempt.endpoint_id]
    payload = _complete_endpoint_payload(contract)
    scoreboard = payload["scoreboard"]
    assert isinstance(scoreboard, dict)
    original_games = scoreboard["games"]
    assert isinstance(original_games, list) and len(original_games) == 1
    games = [deepcopy(original_games[0]), deepcopy(original_games[0])]
    for game, state in zip(games, parent_states, strict=True):
        assert isinstance(game, dict)
        if state == "missing":
            game.pop("pbOdds")
        else:
            game["pbOdds"] = None
    scoreboard["games"] = games
    snapshot, receipts = _replace_live_payload(snapshot, binding, payload)
    body = snapshot.objects[0]
    bundle = finalize_raw_request_capture(snapshot, binding, receipts)
    return bundle, body


def test_mixed_missing_and_null_live_parents_roundtrip_with_ordered_authority() -> None:
    missing_null_bundle, missing_null_body = _mixed_live_parent_bundle(("missing", "null"))
    null_missing_bundle, _null_missing_body = _mixed_live_parent_bundle(("null", "missing"))
    missing_null = next(
        item
        for item in missing_null_bundle.occurrences
        if item.result_name == "scoreboard_games_pbodds"
    )
    null_missing = next(
        item
        for item in null_missing_bundle.occurrences
        if item.result_name == "scoreboard_games_pbodds"
    )
    assert missing_null.presence == null_missing.presence == "mixed_absent"
    assert (
        missing_null.row_count
        == missing_null.cell_count
        == 0
        == null_missing.row_count
        == null_missing.cell_count
    )
    assert missing_null.node_count == missing_null.container_count == 1
    assert missing_null.missing_count == missing_null.null_count == 1
    assert missing_null.parent_state_sha256 == parent_occurrence_states_digest(("missing", "null"))
    assert null_missing.parent_state_sha256 == parent_occurrence_states_digest(("null", "missing"))
    assert missing_null.parent_state_sha256 != null_missing.parent_state_sha256
    assert missing_null.output_sha256 == null_missing.output_sha256
    assert missing_null.occurrence_sha256 != null_missing.occurrence_sha256

    observation = missing_null_bundle.observations[-1]
    live_snapshot_at = missing_null_bundle.landings[0].live_snapshot_at
    assert live_snapshot_at is not None
    plan = LiveSnapshotPlanAuthorityV2.build(
        sealed_plan_bytes=b'{"kind":"finalization-roundtrip-plan","version":2}',
        attempt=observation.attempt,
        route_ids=tuple(item.route_id for item in missing_null_bundle.landings),
        live_snapshot_at=live_snapshot_at,
    )
    reconstruction = reconstruct_raw_request_authority(
        missing_null_body,
        observation,
        missing_null_bundle.occurrences,
        missing_null_bundle.landings,
        live_plan_authority=plan,
        expected_live_plan_authority_sha256=plan.authority_sha256,
    )
    packet = next(
        item
        for item in reconstruction.result_packets
        if item.result_name == "scoreboard_games_pbodds"
    )
    assert packet.presence == "mixed_absent"
    assert packet.parent_state_sha256 == missing_null.parent_state_sha256
    assert packet.missing_count == packet.null_count == packet.container_count == 1


def test_two_pending_successes_cannot_terminalize_one_provider_call() -> None:
    snapshot, binding, receipts = _case("live")
    route = _route("live_score_board")
    second = replace(
        snapshot.pending_successes[0],
        attempt=_attempt(route, parameters={}, retry_ordinal=1),
        private_receipt_sha256="a" * 64,
    )

    with pytest.raises(RawRequestFinalizationError, match="more than one pending"):
        finalize_raw_request_capture(
            replace(
                snapshot,
                pending_successes=(*snapshot.pending_successes, second),
            ),
            binding,
            receipts,
        )


def test_typed_conditional_identity_and_stats_fallback_presence_are_required() -> None:
    snapshot, binding, receipts = _case("live")
    conditional = next(
        route_id for route_id in binding.result_route_ids if LIVE_LOSSLESS_STAGING_KEY in route_id
    )
    endpoint_name, staging_key, raw_index = conditional.rsplit(":", 2)
    forged = f"{endpoint_name}:{staging_key}:{int(raw_index) + 1}"
    forged_routes = tuple(
        sorted(
            forged if route_id == conditional else route_id for route_id in binding.result_route_ids
        )
    )
    forged_binding = replace(binding, result_route_ids=forged_routes)
    forged_pending = replace(
        snapshot.pending_successes[0],
        aggregate_route_ids=forged_routes,
    )
    forged_receipts = tuple(
        replace(receipt, result_route_id=forged)
        if receipt.result_route_id == conditional
        else receipt
        for receipt in receipts
    )
    with pytest.raises(RawRequestFinalizationError, match="typed endpoint authority"):
        finalize_raw_request_capture(
            replace(snapshot, pending_successes=(forged_pending,)),
            forged_binding,
            forged_receipts,
        )

    stats_snapshot, stats_binding, stats_receipts = _case("stats", fallback=True)
    wide_route = next(
        route_id
        for route_id in stats_binding.result_route_ids
        if LOSSLESS_FALLBACK_STAGING_KEY not in route_id
    )
    wide_binding = replace(stats_binding, result_route_ids=(wide_route,))
    wide_pending = replace(
        stats_snapshot.pending_successes[0],
        aggregate_route_ids=(wide_route,),
    )
    wide_receipts = tuple(
        receipt for receipt in stats_receipts if receipt.result_route_id == wide_route
    )
    with pytest.raises(RawRequestFinalizationError, match="fallback route disagree"):
        finalize_raw_request_capture(
            replace(stats_snapshot, pending_successes=(wide_pending,)),
            wide_binding,
            wide_receipts,
        )


def test_live_logical_parameter_mutation_blocks_even_with_matching_receipts() -> None:
    snapshot, binding, receipts = _case("live")
    mutated_binding = replace(
        binding,
        logical_parameters_sha256=canonical_parameters_sha256({"game_id": "foreign"}),
    )
    mutated_receipts = tuple(
        replace(
            receipt,
            logical_parameters_sha256=mutated_binding.logical_parameters_sha256,
        )
        for receipt in receipts
    )
    pending = replace(
        snapshot.pending_successes[0],
        logical_receipt_sha256=mutated_binding.logical_call_receipt_sha256,
    )

    with pytest.raises(RawRequestFinalizationError, match="unbound|parameters differ"):
        finalize_raw_request_capture(
            replace(snapshot, pending_successes=(pending,)),
            mutated_binding,
            mutated_receipts,
        )


def test_logical_provider_alias_is_persisted_and_replays_without_external_pin() -> None:
    bundle = _aliased_stats_bundle()

    assert len(bundle.observations) == 1
    observation = bundle.observations[0]
    binding_json = observation.logical_provider_parameter_binding_json
    binding_sha256 = observation.logical_provider_parameter_binding_sha256
    assert binding_json is not None
    assert binding_sha256 is not None
    replayed_binding = LogicalProviderParameterBindingV1.from_canonical_bytes(
        binding_json.encode("utf-8")
    )
    assert replayed_binding.binding_sha256 == binding_sha256
    assert replayed_binding.logical_parameters_sha256 != (
        observation.attempt.safe_parameters_sha256
    )
    assert validate_raw_request_authority_bundle(bundle) == bundle
    assert (
        validate_logical_provider_parameter_join(
            observation,
            logical_endpoint_name=replayed_binding.logical_endpoint_name,
            logical_parameters_sha256=replayed_binding.logical_parameters_sha256,
            result_route_ids=replayed_binding.result_route_ids,
        )
        == observation
    )


def test_logical_provider_alias_requires_the_external_pre_provider_pin() -> None:
    snapshot, binding, receipts, parameter_binding = _aliased_stats_case()

    with pytest.raises(
        RawRequestFinalizationError,
        match="parameters differ.*independently pinned",
    ):
        _finalize_raw_request_capture(snapshot, binding, receipts)
    with pytest.raises(
        RawRequestFinalizationError,
        match="external verification",
    ):
        _finalize_raw_request_capture(
            snapshot,
            binding,
            receipts,
            logical_provider_parameter_binding=parameter_binding,
            expected_logical_provider_parameter_binding_sha256="f" * 64,
        )


def test_direct_logical_provider_equality_rejects_an_alias_receipt() -> None:
    snapshot, provider_binding, receipts = _case("stats")
    _snapshot, _logical_binding, _logical_receipts, aliased = _aliased_stats_case()
    direct = LogicalProviderParameterBindingV1.build(
        logical_endpoint_name=provider_binding.endpoint_name,
        logical_parameters_sha256=provider_binding.logical_parameters_sha256,
        result_route_ids=provider_binding.result_route_ids,
        provider_entries=aliased.provider_entries,
    )

    with pytest.raises(
        RawRequestFinalizationError,
        match="direct logical/provider parameter equality",
    ):
        _finalize_raw_request_capture(
            snapshot,
            provider_binding,
            receipts,
            logical_provider_parameter_binding=direct,
            expected_logical_provider_parameter_binding_sha256=direct.binding_sha256,
        )


@pytest.mark.parametrize(
    "mutation",
    ("missing", "altered_digest", "altered_bytes", "foreign_valid_binding"),
)
def test_persisted_logical_provider_alias_mutations_fail_closed(mutation: str) -> None:
    bundle = _aliased_stats_bundle()
    observation = bundle.observations[0]
    binding_json = cast("str", observation.logical_provider_parameter_binding_json)
    binding = LogicalProviderParameterBindingV1.from_canonical_bytes(binding_json.encode())
    updates: dict[str, object]
    if mutation == "missing":
        updates = {
            "logical_provider_parameter_binding_sha256": None,
            "logical_provider_parameter_binding_json": None,
        }
    elif mutation == "altered_digest":
        updates = {"logical_provider_parameter_binding_sha256": "f" * 64}
    elif mutation == "altered_bytes":
        updates = {"logical_provider_parameter_binding_json": binding_json + " "}
    else:
        foreign = LogicalProviderParameterBindingV1.build(
            logical_endpoint_name="foreign_logical_endpoint",
            logical_parameters_sha256=binding.logical_parameters_sha256,
            result_route_ids=binding.result_route_ids,
            provider_entries=binding.provider_entries,
        )
        updates = {
            "logical_provider_parameter_binding_sha256": foreign.binding_sha256,
            "logical_provider_parameter_binding_json": foreign.canonical_bytes().decode(),
        }
    mutated = observation.model_copy(update=updates)

    with pytest.raises((RawRequestAuthorityError, ValueError)):
        RawRequestAuthorityBundleV2.build(
            objects=bundle.objects,
            observations=(mutated,),
            occurrences=bundle.occurrences,
            landings=bundle.landings,
        )


def test_attempt_provider_request_digest_is_strictly_revalidated() -> None:
    snapshot, binding, receipts = _case("stats")
    pending = snapshot.pending_successes[0]
    forged_attempt = pending.attempt.model_copy(update={"provider_request_sha256": "b" * 64})

    with pytest.raises(RawRequestFinalizationError, match="strict revalidation"):
        finalize_raw_request_capture(
            replace(
                snapshot,
                pending_successes=(replace(pending, attempt=forged_attempt),),
            ),
            binding,
            receipts,
        )


def test_static_attempt_has_exact_bodyless_parameter_authority() -> None:
    snapshot, binding, receipts = _case("static")
    pending = snapshot.pending_successes[0]
    safe_json, safe_digest, provider_request = canonical_semantic_parameters(
        "static",
        pending.attempt.endpoint_id,
        {},
    )

    bundle = finalize_raw_request_capture(snapshot, binding, receipts)

    assert bundle.objects == ()
    assert bundle.observations[0].body_disposition == "declared_bodyless"
    assert bundle.observations[0].transport.transport_kind == "static_snapshot"
    assert pending.attempt.safe_parameters_json == safe_json == "{}"
    assert pending.attempt.safe_parameters_sha256 == safe_digest
    assert pending.attempt.provider_request_sha256 == provider_request


def test_failure_only_snapshot_materializes_explicitly_incomplete_authority() -> None:
    route = _route("live_score_board")
    attempt = _attempt(route, parameters={})
    observation = RequestObservationV2.build(
        attempt=attempt,
        transport={"transport_kind": "live_http"},
        started_at=_STARTED_AT,
        finished_at=_STARTED_AT + timedelta(milliseconds=1),
        elapsed_ns=1_000_000,
        lifecycle="incomplete",
        outcome="transport_failure_no_response",
        failure_class="transport_transient",
        root_exception_class="ConnectionError",
        body_disposition="no_response",
        body_object_sha256=None,
        bodyless_evidence_sha256="c" * 64,
        result_occurrence_sha256s=(),
        route_landing_sha256s=(),
        capture_response_receipt_sha256=None,
        logical_receipt_sha256=None,
    )

    bundle = materialize_raw_request_failure_snapshot(
        RawRequestCaptureSnapshotV2(
            objects=(),
            observations=(observation,),
            pending_successes=(),
            issues=(),
        )
    )

    assert bundle.objects == bundle.occurrences == ()
    assert bundle.observations == (observation,)
    assert bundle.incomplete_provider_call_sha256s() == (observation.attempt.provider_call_sha256,)
    with pytest.raises(RawRequestAuthorityError, match="without a terminal selection"):
        bundle.require_complete_terminal_selection()


def test_failure_only_snapshot_preserves_exact_downstream_body_object() -> None:
    route = _route("live_score_board")
    attempt = _attempt(route, parameters={})
    body = ParserInputObjectV2.from_parser_input('{"captured":true}')
    observation = RequestObservationV2.build(
        attempt=attempt,
        transport={
            "transport_kind": "live_http",
            "status_code": 200,
            "effective_status_code": 200,
        },
        started_at=_STARTED_AT,
        finished_at=_STARTED_AT + timedelta(milliseconds=1),
        elapsed_ns=1_000_000,
        lifecycle="incomplete",
        outcome="downstream_incomplete",
        failure_class="response_contract",
        root_exception_class="ValueError",
        body_disposition="public_parser_input",
        body_object_sha256=body.object_sha256,
        bodyless_evidence_sha256=None,
        result_occurrence_sha256s=(),
        route_landing_sha256s=(),
        capture_response_receipt_sha256="d" * 64,
        logical_receipt_sha256=None,
    )

    bundle = materialize_raw_request_failure_snapshot(
        RawRequestCaptureSnapshotV2(
            objects=(body,),
            observations=(observation,),
            pending_successes=(),
            issues=(),
        )
    )

    assert bundle.objects == (body,)
    assert bundle.observations == (observation,)
    assert bundle.occurrences == ()


def _result_authority_pending_case() -> tuple[
    RawRequestCaptureSnapshotV2,
    LogicalCallReceiptBinding,
    tuple[CommittedStagingChunkReceiptV2, ...],
]:
    return _unknown_stats_case(
        "video_details",
        {"asset": {"url": "https://example.invalid/opaque", "metadata": {}}},
        include_results=False,
    )


def test_result_authority_pending_success_materializes_body_but_not_result_identity() -> None:
    snapshot, binding, receipts = _result_authority_pending_case()

    bundle = materialize_raw_request_incomplete_success_snapshot(
        snapshot,
        binding,
        receipts,
    )

    assert bundle.objects == snapshot.objects
    assert bundle.occurrences == ()
    assert len(bundle.observations) == 1
    assert bundle.observations[0].lifecycle == "incomplete"
    assert bundle.observations[0].outcome == "downstream_incomplete"
    assert bundle.observations[0].body_object_sha256 == snapshot.objects[0].object_sha256
    assert (
        bundle.observations[0].capture_response_receipt_sha256
        == snapshot.pending_successes[0].private_receipt_sha256
    )
    assert bundle.observations[0].logical_receipt_sha256 is None
    with pytest.raises(RawRequestAuthorityError, match="without a terminal selection"):
        bundle.require_complete_terminal_selection()


@pytest.mark.parametrize(
    "mutation",
    ["wrong_issue", "wrong_coordinate", "issue_root", "named_result", "wide_rows"],
)
def test_result_authority_pending_success_rejects_forged_completion(
    mutation: str,
) -> None:
    snapshot, binding, receipts = _result_authority_pending_case()
    issue = snapshot.issues[0]
    pending = snapshot.pending_successes[0]
    if mutation == "wrong_issue":
        snapshot = replace(snapshot, issues=(replace(issue, code="capture_unavailable"),))
    elif mutation == "wrong_coordinate":
        snapshot = replace(snapshot, issues=(replace(issue, request_ordinal=1),))
    elif mutation == "issue_root":
        snapshot = replace(snapshot, issues=(replace(issue, root_exception_class="ValueError"),))
    elif mutation == "named_result":
        original, _original_binding, _original_receipts = _unknown_stats_case(
            "video_details",
            {"resultSets": [{"name": "Observed", "headers": ["A"], "rowSet": [[1]]}]},
        )
        snapshot = replace(
            snapshot,
            pending_successes=(replace(pending, results=original.pending_successes[0].results),),
        )
    else:
        wide = next(
            receipt
            for receipt in receipts
            if LOSSLESS_FALLBACK_STAGING_KEY not in receipt.result_route_id
        )
        receipts = tuple(
            replace(receipt, persisted_row_count=1)
            if receipt.result_route_id == wide.result_route_id
            else receipt
            for receipt in receipts
        )

    with pytest.raises(RawRequestFinalizationError):
        materialize_raw_request_incomplete_success_snapshot(
            snapshot,
            binding,
            receipts,
        )


def test_failure_only_snapshot_rejects_pending_issue_empty_and_orphan_inputs() -> None:
    success_snapshot, _binding, _receipts = _case("live")
    with pytest.raises(RawRequestFinalizationError, match="contains a pending success"):
        materialize_raw_request_failure_snapshot(success_snapshot)

    empty = RawRequestCaptureSnapshotV2(
        objects=(),
        observations=(),
        pending_successes=(),
        issues=(),
    )
    with pytest.raises(RawRequestFinalizationError, match="no completed observation"):
        materialize_raw_request_failure_snapshot(empty)

    route = _route("live_score_board")
    attempt = _attempt(route, parameters={})
    observation = RequestObservationV2.build(
        attempt=attempt,
        transport={"transport_kind": "live_http"},
        started_at=_STARTED_AT,
        finished_at=_STARTED_AT + timedelta(milliseconds=1),
        elapsed_ns=1_000_000,
        lifecycle="incomplete",
        outcome="transport_failure_no_response",
        failure_class="transport_transient",
        root_exception_class="ConnectionError",
        body_disposition="no_response",
        body_object_sha256=None,
        bodyless_evidence_sha256="d" * 64,
        result_occurrence_sha256s=(),
        route_landing_sha256s=(),
        capture_response_receipt_sha256=None,
        logical_receipt_sha256=None,
    )
    issue = RawRequestCaptureIssueV2(
        code="observation_unavailable",
        retry_ordinal=0,
        request_ordinal=0,
        root_exception_class="ValueError",
    )
    with pytest.raises(RawRequestFinalizationError, match="unresolved capture issues"):
        materialize_raw_request_failure_snapshot(
            replace(empty, observations=(observation,), issues=(issue,))
        )

    orphan = ParserInputObjectV2.from_parser_input('{"orphan":true}')
    with pytest.raises(RawRequestFinalizationError, match="orphan"):
        materialize_raw_request_failure_snapshot(
            replace(empty, objects=(orphan,), observations=(observation,))
        )
