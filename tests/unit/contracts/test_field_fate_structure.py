from __future__ import annotations

import json
from collections import Counter, defaultdict
from dataclasses import FrozenInstanceError, replace
from datetime import UTC, datetime
from pathlib import Path

import polars as pl
import pyarrow as pa
import pytest

import nbadb.contracts.field_fate_structure as structure_module
from nbadb.contracts.field_fate_structure import (
    EXPECTED_BOUND_STORAGE_SINK_COUNT,
    EXPECTED_EXPANDED_SOURCE_OCCURRENCE_COUNT,
    EXPECTED_LIVE_SOURCE_OCCURRENCE_COUNT,
    EXPECTED_PROVIDER_SOURCE_OCCURRENCE_COUNT,
    EXPECTED_ROUTE_FIELD_BINDING_COUNT,
    EXPECTED_ROUTED_SOURCE_OCCURRENCE_COUNT,
    EXPECTED_SINGLE_ROUTE_SOURCE_OCCURRENCE_COUNT,
    EXPECTED_STATIC_SOURCE_OCCURRENCE_COUNT,
    EXPECTED_STATS_SOURCE_OCCURRENCE_COUNT,
    EXPECTED_STORAGE_ONLY_SINK_COUNT,
    EXPECTED_STORAGE_SINK_COUNT,
    EXPECTED_UNROUTED_SOURCE_OCCURRENCE_COUNT,
    ConditionalRouteOccurrenceAuthorityV1,
    FieldFateStructureError,
    FieldFateStructureV1,
    ProviderFieldSourceOccurrenceV1,
    RouteLandingFieldJoinV1,
    StatsLosslessFieldBindingV1,
    canonical_json_bytes,
    compile_field_fate_structure,
    derive_conditional_route_occurrence_authority,
    validate_conditional_route_occurrence_authority,
    validate_field_fate_structure,
)
from nbadb.contracts.raw_request_authority import (
    ObservationRouteLandingV2,
    ParserInputObjectV2,
    RawRequestAuthorityBundleV2,
    RequestObservationV2,
    ResultOccurrenceV2,
    decode_parser_input_object,
)
from nbadb.contracts.raw_request_finalization import (
    RawRequestFinalizationError,
    finalize_raw_request_capture,
    materialize_raw_request_incomplete_success_snapshot,
)
from nbadb.contracts.request_scope_storage_contract import (
    EXPECTED_REQUEST_SCOPE_STORAGE_FIELD_COUNT,
    request_scope_arrow_type,
)
from nbadb.contracts.staging_route_contract import staging_route_contract_bundle
from nbadb.core.nba_api_runtime_contract import pinned_live_contracts
from nbadb.extract.nba_api_adapter import (
    rederive_raw_authority_result_sets,
    rederive_raw_authority_route_frames,
    rederive_raw_authority_stats_fallback,
    rederive_raw_authority_unknown_stats_response,
    validate_lossless_fallback_frame,
)
from nbadb.extract.stats_lossless import build_unknown_stats_lossless_fallback
from nbadb.orchestrate.staging_batches import (
    CommittedStagingChunkReceiptV2,
    CommittedStagingFrameReadbackV2,
    frame_content_hash,
    frame_schema_hash,
)
from nbadb.schemas.registry import get_input_schema
from nbadb.schemas.staging.nba_api_lossless import StagingNbaApiLosslessResultCellsSchema
from tests.unit.contracts.test_raw_request_finalization import (
    _case,
    _live_plan_authority,
    _unknown_stats_case,
)
from tests.unit.extract.test_live_lossless_nodes import _complete_endpoint_payload


@pytest.fixture(scope="module")
def structure() -> FieldFateStructureV1:
    return compile_field_fate_structure()


def _route_arrow_schema(route_id: str) -> pa.Schema:
    route = staging_route_contract_bundle().by_route_id[route_id]
    schema_cls = get_input_schema(route.staging_key)
    assert schema_cls is not None
    declared = schema_cls.to_schema()
    assert tuple(declared.columns) == route.storage_columns
    return (
        pl.DataFrame(
            schema={
                name: column.dtype.type if column.dtype is not None else pl.Null
                for name, column in declared.columns.items()
            }
        )
        .to_arrow()
        .schema
    )


def _route_arrow_schema_with_scope(
    route_id: str,
    *scope_columns: str,
) -> pa.Schema:
    route = staging_route_contract_bundle().by_route_id[route_id]
    by_name = {item.storage_column: item for item in route.request_scope_storage_fields}
    return pa.schema(
        (
            *_route_arrow_schema(route_id),
            *(
                pa.field(
                    column,
                    request_scope_arrow_type(by_name[column].logical_type),
                )
                for column in scope_columns
            ),
        )
    )


def _selected_stats_conditional_authority(
    structure: FieldFateStructureV1,
    *,
    frame_response_receipt_sha256: str | None = None,
) -> tuple[str, pl.DataFrame, ConditionalRouteOccurrenceAuthorityV1]:
    snapshot, binding, receipts = _case("stats", fallback=True)
    pending = snapshot.pending_successes[0]
    response_receipt_sha256 = frame_response_receipt_sha256 or pending.private_receipt_sha256
    route = next(
        item
        for item in staging_route_contract_bundle().routes
        if item.endpoint_name == "league_game_log"
    )
    receipt = next(
        item for item in receipts if "stg_nba_api_lossless_result_cells" in item.result_route_id
    )
    headers = route.provider_columns
    values = [[None] * len(headers), [None] * len(headers)]
    values[0][0] = 1
    values[1][0] = "one"
    parser_input = json.dumps(
        {
            "resultSets": [
                {
                    "name": route.provider_result_set_name,
                    "headers": list(headers),
                    "rowSet": values,
                }
            ]
        },
        sort_keys=True,
        separators=(",", ":"),
    )
    body = ParserInputObjectV2.from_parser_input(parser_input)
    derivations = rederive_raw_authority_result_sets(
        source_family="stats",
        endpoint_id=pending.attempt.endpoint_id,
        parser_input=parser_input.encode("utf-8"),
        provider_authority_sha256=pending.attempt.provider_authority_sha256,
        endpoint_contract_sha256_value=pending.attempt.endpoint_contract_sha256,
    )
    assert len(derivations) == 1
    derivation = derivations[0]
    pending_result = pending.results[0]
    snapshot = replace(
        snapshot,
        objects=(body,),
        pending_successes=(
            replace(
                pending,
                body_object=body,
                results=(
                    replace(
                        pending_result,
                        result_set=derivation.result_set,
                        ordered_headers=derivation.ordered_headers,
                    ),
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
        .bind_response_receipt(response_receipt_sha256)
        .frame
    )
    validate_lossless_fallback_frame(
        frame,
        expected_response_receipt_sha256=response_receipt_sha256,
    )
    content_sha256 = frame_content_hash(frame)
    receipt = replace(
        receipt,
        content_hash=content_sha256,
        persisted_row_count=frame.height,
        persisted_content_sha256=content_sha256,
        persisted_schema_sha256=frame_schema_hash(frame),
    )
    empty_wide_frame = pl.DataFrame()
    empty_wide_content_sha256 = frame_content_hash(empty_wide_frame)
    committed = tuple(
        receipt
        if item.result_route_id == receipt.result_route_id
        # The deliberately mixed first-column values cannot be represented by
        # the declared wide frame without coercion.  Exact fallback replay
        # therefore lands the response only in the conditional lossless route.
        else replace(
            item,
            content_hash=empty_wide_content_sha256,
            persisted_row_count=0,
            persisted_content_sha256=empty_wide_content_sha256,
            persisted_schema_sha256=frame_schema_hash(empty_wide_frame),
        )
        if item.result_route_id == route.route_id
        else item
        for item in receipts
    )
    raw_bundle = finalize_raw_request_capture(
        snapshot,
        binding,
        committed,
    )
    readback = CommittedStagingFrameReadbackV2.build(
        committed_receipt=receipt,
        frame=frame,
    )
    return (
        receipt.result_route_id,
        frame,
        derive_conditional_route_occurrence_authority(
            structure=structure,
            route_id=receipt.result_route_id,
            raw_bundle=raw_bundle,
            readback=readback,
        ),
    )


def _selected_unknown_stats_conditional_authority(
    structure: FieldFateStructureV1,
) -> tuple[str, pl.DataFrame, ConditionalRouteOccurrenceAuthorityV1]:
    snapshot, binding, receipts = _unknown_stats_case(
        "video_events",
        {
            "resultSets": [
                {"name": "Observed", "headers": [], "rowSet": [[]]},
                {"name": "Observed", "headers": ["A"], "rowSet": [[1]]},
            ],
            "future": {"nested": [True, None]},
        },
    )
    pending = snapshot.pending_successes[0]
    assert pending.body_object is not None
    parser_input = decode_parser_input_object(pending.body_object)
    unknown = rederive_raw_authority_unknown_stats_response(
        endpoint_id=pending.attempt.endpoint_id,
        parser_input=parser_input,
        safe_parameters_json=pending.attempt.safe_parameters_json,
        provider_authority_sha256=pending.attempt.provider_authority_sha256,
        endpoint_contract_sha256_value=pending.attempt.endpoint_contract_sha256,
    ).bind_response_receipt(pending.private_receipt_sha256)
    fallback = build_unknown_stats_lossless_fallback(unknown)
    assert fallback is not None
    frame = fallback.frame
    raw_bundle = finalize_raw_request_capture(snapshot, binding, receipts)
    receipt = next(
        item for item in receipts if item.staging_key == "stg_nba_api_lossless_result_cells"
    )
    readback = CommittedStagingFrameReadbackV2.build(
        committed_receipt=receipt,
        frame=frame,
    )
    return (
        receipt.result_route_id,
        frame,
        derive_conditional_route_occurrence_authority(
            structure=structure,
            route_id=receipt.result_route_id,
            raw_bundle=raw_bundle,
            readback=readback,
        ),
    )


def _body_node_conditional_authority(
    structure: FieldFateStructureV1,
    *,
    payload: dict[str, object] | None = None,
    include_results: bool = False,
) -> tuple[str, pl.DataFrame, ConditionalRouteOccurrenceAuthorityV1]:
    snapshot, binding, receipts = _unknown_stats_case(
        "video_details",
        payload if payload is not None else {"unexpected": {"nested": [1]}},
        include_results=include_results,
    )
    snapshot = replace(snapshot, issues=())
    pending = snapshot.pending_successes[0]
    assert pending.body_object is not None
    parser_input = decode_parser_input_object(pending.body_object)
    unknown = rederive_raw_authority_unknown_stats_response(
        endpoint_id=pending.attempt.endpoint_id,
        parser_input=parser_input,
        safe_parameters_json=pending.attempt.safe_parameters_json,
        provider_authority_sha256=pending.attempt.provider_authority_sha256,
        endpoint_contract_sha256_value=pending.attempt.endpoint_contract_sha256,
    ).bind_response_receipt(pending.private_receipt_sha256)
    fallback = build_unknown_stats_lossless_fallback(unknown)
    assert fallback is not None
    frame = fallback.frame
    raw_bundle = finalize_raw_request_capture(snapshot, binding, receipts)
    receipt = next(
        item for item in receipts if item.staging_key == "stg_nba_api_lossless_result_cells"
    )
    readback = CommittedStagingFrameReadbackV2.build(
        committed_receipt=receipt,
        frame=frame,
    )
    return (
        receipt.result_route_id,
        frame,
        derive_conditional_route_occurrence_authority(
            structure=structure,
            route_id=receipt.result_route_id,
            raw_bundle=raw_bundle,
            readback=readback,
        ),
    )


def _live_conditional_authority(
    structure: FieldFateStructureV1,
    *,
    frame_response_receipt_sha256: str | None = None,
) -> tuple[str, pl.DataFrame, ConditionalRouteOccurrenceAuthorityV1]:
    snapshot, binding, receipts = _case("live")
    route_bundle = staging_route_contract_bundle()
    route = next(item for item in route_bundle.routes if item.endpoint_name == "live_score_board")
    contract = pinned_live_contracts()[route.provider_endpoint_id]
    payload = _complete_endpoint_payload(contract)
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
    assert len(pending.results) == len(derivations)
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
    response_receipt_sha256 = frame_response_receipt_sha256 or pending.private_receipt_sha256
    snapshot = replace(
        snapshot,
        objects=(body,),
        pending_successes=(pending,),
    )
    live_snapshot_at = datetime(2026, 8, 27, 12, 0, tzinfo=UTC)
    frame_derivations = rederive_raw_authority_route_frames(
        source_family="live",
        endpoint_name=binding.endpoint_name,
        endpoint_id=pending.attempt.endpoint_id,
        selected_route_ids=binding.result_route_ids,
        parser_input=parser_input.encode("utf-8"),
        safe_parameters_json=pending.attempt.safe_parameters_json,
        provider_authority_sha256=pending.attempt.provider_authority_sha256,
        endpoint_contract_sha256_value=pending.attempt.endpoint_contract_sha256,
        capture_response_receipt_sha256=response_receipt_sha256,
        live_snapshot_at=live_snapshot_at,
    )
    derivation_by_route = {item.route_id: item for item in frame_derivations}
    receipt = next(
        item for item in receipts if "stg_nba_api_live_lossless_nodes" in item.result_route_id
    )
    frame = derivation_by_route[receipt.result_route_id].frame
    committed = tuple(
        replace(
            item,
            content_hash=derivation_by_route[item.result_route_id].frame_content_sha256,
            persisted_row_count=derivation_by_route[item.result_route_id].row_count,
            persisted_content_sha256=derivation_by_route[item.result_route_id].frame_content_sha256,
            persisted_schema_sha256=derivation_by_route[item.result_route_id].frame_schema_sha256,
        )
        for item in receipts
    )
    plan = _live_plan_authority(
        snapshot,
        binding,
        snapshot_at=live_snapshot_at,
    )
    raw_bundle = finalize_raw_request_capture(
        snapshot,
        binding,
        committed,
        live_plan_authority=plan,
        expected_live_plan_authority_sha256=plan.authority_sha256,
    )
    readback = CommittedStagingFrameReadbackV2.build(
        committed_receipt=receipt,
        frame=frame,
    )
    return (
        receipt.result_route_id,
        frame,
        derive_conditional_route_occurrence_authority(
            structure=structure,
            route_id=receipt.result_route_id,
            raw_bundle=raw_bundle,
            readback=readback,
        ),
    )


def _rebind_bundle_endpoint_contract(
    bundle: RawRequestAuthorityBundleV2,
    endpoint_contract_sha256: str,
) -> RawRequestAuthorityBundleV2:
    original = bundle.observations[0]
    rebound_attempt = original.attempt.model_copy(
        update={"endpoint_contract_sha256": endpoint_contract_sha256}
    )
    occurrence_ids = tuple(
        item.occurrence_sha256
        for item in sorted(bundle.occurrences, key=lambda item: item.occurrence_ordinal)
        if item.observation_sha256 == original.attempt.observation_sha256
    )
    landing_ids = tuple(
        item.landing_sha256
        for item in sorted(bundle.landings, key=lambda item: item.route_ordinal)
        if item.observation_sha256 == original.attempt.observation_sha256
    )
    rebound = RequestObservationV2.build(
        attempt=rebound_attempt,
        transport=original.transport,
        started_at=original.started_at,
        finished_at=original.finished_at,
        elapsed_ns=original.elapsed_ns,
        lifecycle=original.lifecycle,
        outcome=original.outcome,
        failure_class=original.failure_class,
        root_exception_class=original.root_exception_class,
        body_disposition=original.body_disposition,
        body_object_sha256=original.body_object_sha256,
        bodyless_evidence_sha256=original.bodyless_evidence_sha256,
        result_occurrence_sha256s=occurrence_ids,
        route_landing_sha256s=landing_ids,
        capture_response_receipt_sha256=original.capture_response_receipt_sha256,
        logical_receipt_sha256=original.logical_receipt_sha256,
    )
    return RawRequestAuthorityBundleV2.build(
        objects=bundle.objects,
        observations=(rebound, *bundle.observations[1:]),
        occurrences=bundle.occurrences,
        landings=bundle.landings,
    )


def _rebuild_result_occurrence(
    occurrence: ResultOccurrenceV2,
    **updates: object,
) -> ResultOccurrenceV2:
    payload: dict[str, object] = {
        "observation_sha256": occurrence.observation_sha256,
        "occurrence_ordinal": occurrence.occurrence_ordinal,
        "result_name": occurrence.result_name,
        "duplicate_name_ordinal": occurrence.duplicate_name_ordinal,
        "provider_result_ordinal": occurrence.provider_result_ordinal,
        "canonical_result_ordinal": occurrence.canonical_result_ordinal,
        "json_path": occurrence.json_path,
        "container_kind": occurrence.container_kind,
        "presence": occurrence.presence,
        "ordered_headers": json.loads(occurrence.ordered_headers_json),
        "row_count": occurrence.row_count,
        "cell_count": occurrence.cell_count,
        "node_count": occurrence.node_count,
        "container_count": occurrence.container_count,
        "missing_count": occurrence.missing_count,
        "null_count": occurrence.null_count,
        "parent_state_sha256": occurrence.parent_state_sha256,
        "output_sha256": occurrence.output_sha256,
        "canonical_route_ids": json.loads(occurrence.canonical_route_ids_json),
        "committed_staging_receipts": json.loads(occurrence.committed_staging_receipts_json),
        "landing_disposition": occurrence.landing_disposition,
    }
    payload.update(updates)
    return ResultOccurrenceV2.build(**payload)  # type: ignore[arg-type]


def _replace_bundle_occurrence(
    bundle: RawRequestAuthorityBundleV2,
    replacement: ResultOccurrenceV2,
) -> RawRequestAuthorityBundleV2:
    occurrences = tuple(
        replacement if item.occurrence_ordinal == replacement.occurrence_ordinal else item
        for item in bundle.occurrences
    )
    original = bundle.observations[0]
    observation = RequestObservationV2.build(
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
        body_object_sha256=original.body_object_sha256,
        bodyless_evidence_sha256=original.bodyless_evidence_sha256,
        result_occurrence_sha256s=tuple(
            item.occurrence_sha256
            for item in sorted(occurrences, key=lambda item: item.occurrence_ordinal)
        ),
        route_landing_sha256s=tuple(
            item.landing_sha256
            for item in sorted(bundle.landings, key=lambda item: item.route_ordinal)
            if item.observation_sha256 == original.attempt.observation_sha256
        ),
        capture_response_receipt_sha256=original.capture_response_receipt_sha256,
        logical_receipt_sha256=original.logical_receipt_sha256,
    )
    return RawRequestAuthorityBundleV2.build(
        objects=bundle.objects,
        observations=(observation, *bundle.observations[1:]),
        occurrences=occurrences,
        landings=bundle.landings,
    )


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


def _reseal_live_snapshot_authority(
    *,
    authority: ConditionalRouteOccurrenceAuthorityV1,
    route_id: str,
    frame: pl.DataFrame,
    snapshot_at: datetime,
) -> tuple[RawRequestAuthorityBundleV2, CommittedStagingFrameReadbackV2]:
    forged_frame = frame.with_columns(
        pl.lit(snapshot_at).cast(frame.schema["snapshot_at"]).alias("snapshot_at"),
        pl.lit(snapshot_at.date()).cast(frame.schema["snapshot_date"]).alias("snapshot_date"),
    )
    content_sha256 = frame_content_hash(forged_frame)
    forged_receipt = replace(
        authority.readback.committed_receipt,
        content_hash=content_sha256,
        persisted_row_count=forged_frame.height,
        persisted_content_sha256=content_sha256,
        persisted_schema_sha256=frame_schema_hash(forged_frame),
    )

    occurrences: list[ResultOccurrenceV2] = []
    for occurrence in authority.raw_bundle.occurrences:
        receipts = json.loads(occurrence.committed_staging_receipts_json)
        assert isinstance(receipts, list)
        for receipt in receipts:
            assert isinstance(receipt, dict)
            if receipt.get("route_id") == route_id:
                receipt["receipt_sha256"] = forged_receipt.receipt_root_sha256
        occurrences.append(
            _rebuild_result_occurrence(
                occurrence,
                committed_staging_receipts=receipts,
            )
        )
    rebuilt_occurrences = tuple(occurrences)

    landings = tuple(
        ObservationRouteLandingV2.build(
            observation_sha256=landing.observation_sha256,
            logical_receipt_sha256=landing.logical_receipt_sha256,
            route_ordinal=landing.route_ordinal,
            route_authority_kind=landing.route_authority_kind,
            route_authority_sha256=landing.route_authority_sha256,
            landing_semantic=landing.landing_semantic,
            conditional_lossless=landing.conditional_lossless,
            alias_target_route_id=landing.alias_target_route_id,
            live_snapshot_at=landing.live_snapshot_at,
            source_occurrence_sha256s=tuple(
                occurrence.occurrence_sha256
                for occurrence in rebuilt_occurrences
                if landing.route_id in occurrence.canonical_route_ids()
            ),
            committed_receipt=(
                forged_receipt
                if landing.route_id == route_id
                else _committed_receipt_from_landing(landing)
            ),
        )
        for landing in authority.raw_bundle.landings
    )
    original = authority.raw_bundle.observations[0]
    observation = RequestObservationV2.build(
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
        body_object_sha256=original.body_object_sha256,
        bodyless_evidence_sha256=original.bodyless_evidence_sha256,
        result_occurrence_sha256s=tuple(
            occurrence.occurrence_sha256 for occurrence in rebuilt_occurrences
        ),
        route_landing_sha256s=tuple(landing.landing_sha256 for landing in landings),
        capture_response_receipt_sha256=original.capture_response_receipt_sha256,
        logical_receipt_sha256=original.logical_receipt_sha256,
    )
    bundle = RawRequestAuthorityBundleV2.build(
        objects=authority.raw_bundle.objects,
        observations=(observation,),
        occurrences=rebuilt_occurrences,
        landings=landings,
    )
    return (
        bundle,
        CommittedStagingFrameReadbackV2.build(
            committed_receipt=forged_receipt,
            frame=forged_frame,
        ),
    )


def test_provider_source_census_preserves_exact_occurrences(
    structure: FieldFateStructureV1,
) -> None:
    occurrences = structure.provider_sources.occurrences
    assert len(occurrences) == EXPECTED_PROVIDER_SOURCE_OCCURRENCE_COUNT
    assert Counter(item.source_family for item in occurrences) == {
        "stats": EXPECTED_STATS_SOURCE_OCCURRENCE_COUNT,
        "live": EXPECTED_LIVE_SOURCE_OCCURRENCE_COUNT,
        "static": EXPECTED_STATIC_SOURCE_OCCURRENCE_COUNT,
    }
    assert Counter(item.provenance_kind for item in occurrences) == {
        "installed_stats_header_atom": 9_513,
        "installed_live_source_field_atom": 409,
        "unverified_live_docs_field": 21,
        "installed_live_nested_scalar_projection": 1,
        "installed_static_field_projection": 26,
    }
    assert (
        sum(item.direct_source_field for item in occurrences if item.source_family == "live") == 430
    )


def test_stats_same_name_headers_do_not_collapse(
    structure: FieldFateStructureV1,
) -> None:
    groups: dict[tuple[str, str], list[ProviderFieldSourceOccurrenceV1]] = defaultdict(list)
    for occurrence in structure.provider_sources.occurrences:
        if occurrence.source_family == "stats":
            groups[(occurrence.endpoint_id, occurrence.provider_field_name)].append(occurrence)
    repeated = [items for items in groups.values() if len(items) > 1]
    assert repeated
    for items in repeated:
        occurrence_ids = {item.occurrence_id for item in items}
        occurrence_hashes = {item.occurrence_sha256 for item in items}
        result_field_ordinals = {(item.result_set_ordinal, item.field_ordinal) for item in items}
        assert len(occurrence_ids) == len(items)
        assert len(occurrence_hashes) == len(items)
        assert len(result_field_ordinals) == len(items)


def test_live_paths_and_static_ordinals_are_lossless(
    structure: FieldFateStructureV1,
) -> None:
    live = [item for item in structure.provider_sources.occurrences if item.source_family == "live"]
    assert len({(item.endpoint_id, item.source_path) for item in live}) == len(live)
    assert all(item.source_path.startswith("$.") for item in live)

    static = [
        item for item in structure.provider_sources.occurrences if item.source_family == "static"
    ]
    assert all(
        item.authority_atom_id.startswith("installed_static_field_projection:")
        and len(item.authority_atom_sha256) == 64
        for item in static
    )
    by_dataset: dict[str, list[int]] = defaultdict(list)
    for occurrence in static:
        by_dataset[occurrence.endpoint_id].append(occurrence.field_ordinal)
    assert {name: ordinals for name, ordinals in sorted(by_dataset.items())} == {
        "static_players": list(range(5)),
        "static_teams": list(range(8)),
        "static_wnba_players": list(range(5)),
        "static_wnba_teams": list(range(8)),
    }

    nested = [
        item
        for item in structure.provider_sources.occurrences
        if item.provenance_kind == "installed_live_nested_scalar_projection"
    ]
    assert [(item.provider_field_name, item.source_path) for item in nested] == [
        ("value", "$.game.actions.personIdsFilter.value")
    ]
    assert nested[0].authority_atom_id.startswith(
        "installed_live_nested_scalar_projection:PlayByPlay:"
    )


def test_route_expansion_is_separate_and_complete(
    structure: FieldFateStructureV1,
) -> None:
    bindings = structure.route_bindings.bindings
    expansions = structure.route_bindings.source_expansions
    assert len(bindings) == EXPECTED_ROUTE_FIELD_BINDING_COUNT
    assert Counter(item.source_family for item in bindings) == {
        "stats": 11_142,
        "live": 155,
        "static": 26,
    }
    assert Counter(item.status for item in expansions) == {
        "single_route": EXPECTED_SINGLE_ROUTE_SOURCE_OCCURRENCE_COUNT,
        "expanded_routes": EXPECTED_EXPANDED_SOURCE_OCCURRENCE_COUNT,
        "unrouted": EXPECTED_UNROUTED_SOURCE_OCCURRENCE_COUNT,
    }
    assert sum(item.status != "unrouted" for item in expansions) == (
        EXPECTED_ROUTED_SOURCE_OCCURRENCE_COUNT
    )
    source_by_id = structure.provider_sources.by_occurrence_id
    unrouted = [item for item in expansions if item.status == "unrouted"]
    assert {source_by_id[item.source_occurrence_id].source_family for item in unrouted} == {"live"}


def test_wide_unrouted_live_fields_have_exact_lossless_node_bindings(
    structure: FieldFateStructureV1,
) -> None:
    bindings = structure.lossless_bindings
    assert len(bindings) == EXPECTED_UNROUTED_SOURCE_OCCURRENCE_COUNT
    assert {item.source_occurrence_id for item in bindings} == {
        item.source_occurrence_id
        for item in structure.route_bindings.source_expansions
        if item.status == "unrouted"
    }
    assert Counter(item.binding_strategy for item in bindings) == {
        "object_contract_field": 275,
        "scalar_result_set_item": 1,
    }
    assert {item.staging_key for item in bindings} == {"stg_nba_api_live_lossless_nodes"}
    assert len({item.sink_authority_sha256 for item in bindings}) == 1
    assert all("contract_json_path" in item.selector_columns for item in bindings)
    assert all(item.contract_result_set_json_path for item in bindings)
    assert all(item.contract_field_json_path for item in bindings)
    assert not {
        item.source_occurrence_id
        for item in structure.blockers
        if item.blocker_kind == "lossless_storage_binding_unresolved"
    }


def test_missing_exact_checkout_retains_field_level_docs_authority_blockers(
    structure: FieldFateStructureV1,
) -> None:
    blockers = [
        item for item in structure.blockers if item.blocker_kind == "source_authority_unavailable"
    ]
    assert len(blockers) == 21
    assert {item.source_occurrence_id for item in blockers} == {
        item.occurrence_id
        for item in structure.provider_sources.occurrences
        if item.provenance_kind == "unverified_live_docs_field"
    }


def test_stats_route_multiplicity_and_nested_live_paths_are_exact(
    structure: FieldFateStructureV1,
) -> None:
    source_by_id = structure.provider_sources.by_occurrence_id
    stats_expansions = [
        expansion
        for expansion in structure.route_bindings.source_expansions
        if source_by_id[expansion.source_occurrence_id].source_family == "stats"
    ]
    assert Counter(len(item.binding_ids) for item in stats_expansions) == {
        1: 8_294,
        2: 809,
        3: 410,
    }

    nested = [
        item
        for item in structure.route_bindings.bindings
        if item.mapping_transform == "nested_projection"
    ]
    assert len(nested) == 2
    assert {item.provider_column for item in nested} == {"statistics.points"}
    assert {source_by_id[item.source_occurrence_id].source_path for item in nested} == {
        "$.game.homeTeam.players.statistics.points",
        "$.game.awayTeam.players.statistics.points",
    }


def test_storage_sinks_partition_bindings_from_storage_only_columns(
    structure: FieldFateStructureV1,
) -> None:
    sinks = structure.storage_sinks.sinks
    assert len(sinks) == EXPECTED_STORAGE_SINK_COUNT
    assert Counter(item.status for item in sinks) == {
        "provider_bound": EXPECTED_BOUND_STORAGE_SINK_COUNT,
        "storage_only": EXPECTED_STORAGE_ONLY_SINK_COUNT,
    }
    binding_ids = [binding_id for sink in sinks for binding_id in sink.binding_ids]
    assert len(binding_ids) == EXPECTED_ROUTE_FIELD_BINDING_COUNT
    assert len(set(binding_ids)) == len(binding_ids)
    assert set(binding_ids) == set(structure.route_bindings.by_binding_id)


def test_route_landing_fields_preserve_static_provider_authority(
    structure: FieldFateStructureV1,
) -> None:
    route_id = "static_players:stg_static_players:0"
    route = staging_route_contract_bundle().by_route_id[route_id]

    fields = structure.route_landing_fields(route_id, _route_arrow_schema(route_id))

    assert all(type(item) is RouteLandingFieldJoinV1 for item in fields)
    assert tuple(item.sink.storage_ordinal for item in fields) == tuple(range(len(fields)))
    assert tuple(item.sink.storage_column for item in fields) == route.storage_columns
    assert {item.origin for item in fields} == {"provider_bound"}
    assert all(len(item.route_bindings) == len(item.provider_sources) == 1 for item in fields)
    for item in fields:
        binding = item.route_bindings[0]
        source = item.provider_sources[0]
        assert binding.binding_id in item.sink.binding_ids
        assert binding.source_occurrence_id == source.occurrence_id
        assert binding.source_occurrence_sha256 == source.occurrence_sha256
        assert source.source_family == "static"
        assert source.endpoint_id == route.provider_endpoint_id
        assert source.result_set_name == route.provider_result_set_name
        assert source.result_set_ordinal == route.provider_result_set_ordinal
        assert source.field_ordinal == binding.mapping_ordinal


def test_route_landing_fields_preserve_multi_bound_and_storage_only_fields(
    structure: FieldFateStructureV1,
) -> None:
    route_id = "live_play_by_play:stg_live_play_by_play:0"
    route = staging_route_contract_bundle().by_route_id[route_id]

    fields = structure.route_landing_fields(route_id, _route_arrow_schema(route_id))

    assert tuple(item.sink.storage_column for item in fields) == route.storage_columns
    assert tuple(item.sink.storage_ordinal for item in fields) == tuple(range(len(fields)))
    payload = next(item for item in fields if item.sink.storage_column == "payload_json")
    assert payload.origin == "provider_multi_bound"
    assert len(payload.route_bindings) == len(payload.provider_sources) == 42
    assert tuple(item.mapping_ordinal for item in payload.route_bindings) == tuple(
        sorted(item.mapping_ordinal for item in payload.route_bindings)
    )
    assert tuple(item.binding_id for item in payload.route_bindings) == payload.sink.binding_ids

    action_number = next(item for item in fields if item.sink.storage_column == "action_number")
    assert action_number.origin == "provider_bound"
    assert len(action_number.route_bindings) == len(action_number.provider_sources) == 1

    snapshot_at = next(item for item in fields if item.sink.storage_column == "snapshot_at")
    assert snapshot_at.origin == "storage_only"
    assert snapshot_at.sink.status == "storage_only"
    assert snapshot_at.route_bindings == ()
    assert snapshot_at.provider_sources == ()
    assert snapshot_at.lossless_bindings == ()
    assert "lossless_bound" not in {item.origin for item in fields}

    for item in fields:
        for binding, source in zip(
            item.route_bindings,
            item.provider_sources,
            strict=True,
        ):
            mapping = route.column_mappings[binding.mapping_ordinal]
            assert binding.provider_column == mapping.provider_column
            assert binding.canonical_column == mapping.canonical_column
            assert binding.storage_column == mapping.storage_column == item.sink.storage_column
            assert binding.source_occurrence_id == source.occurrence_id
            assert binding.source_occurrence_sha256 == source.occurrence_sha256
            assert source.source_family == route.source_family
            assert source.endpoint_id == route.provider_endpoint_id
            assert source.endpoint_contract_sha256 == route.endpoint_contract_sha256


def test_request_scope_route_landing_accepts_exact_common_all_players_suffix(
    structure: FieldFateStructureV1,
) -> None:
    route_id = "common_all_players:stg_common_all_players:0"
    route = staging_route_contract_bundle().by_route_id[route_id]
    exact = _route_arrow_schema_with_scope(route_id, "season_year", "league_id")

    fields = structure.route_landing_fields(route_id, exact)

    assert len(fields) == len(route.storage_columns) + 2
    assert tuple(item.sink.storage_ordinal for item in fields) == tuple(range(len(fields)))
    assert tuple(item.sink.storage_column for item in fields) == (
        *route.storage_columns,
        "season_year",
        "league_id",
    )
    for item in fields[-2:]:
        assert item.origin == "storage_only"
        assert item.sink.status == "storage_only"
        assert item.sink.binding_ids == ()
        assert item.sink.route_contract_sha256 == route.contract_sha256
        assert item.route_bindings == item.provider_sources == item.lossless_bindings == ()


def test_request_scope_route_landing_accepts_optional_ordered_subsets(
    structure: FieldFateStructureV1,
) -> None:
    route_id = "common_all_players:stg_common_all_players:0"

    for columns in ((), ("season_year",), ("league_id",), ("season_year", "league_id")):
        fields = structure.route_landing_fields(
            route_id,
            _route_arrow_schema_with_scope(route_id, *columns),
        )
        assert tuple(item.sink.storage_column for item in fields[-len(columns) :]) == (
            columns if columns else tuple(item.sink.storage_column for item in fields)
        )
        assert tuple(item.sink.storage_ordinal for item in fields) == tuple(range(len(fields)))


def test_request_scope_route_landing_rejects_extra_reordered_and_type_drift(
    structure: FieldFateStructureV1,
) -> None:
    route_id = "common_all_players:stg_common_all_players:0"
    base = tuple(_route_arrow_schema(route_id))
    season = pa.field("season_year", pa.large_string())
    league = pa.field("league_id", pa.large_string())
    hostile = (
        pa.schema((*base, league, season)),
        pa.schema((*base, season, pa.field("foreign_scope", pa.large_string()))),
        pa.schema((*base, pa.field("season_year", pa.int64()))),
        pa.schema((*base, pa.field("season_year", pa.string()))),
        pa.schema((*base, pa.field("season_year", pa.large_string(), nullable=False))),
        pa.schema((*base, pa.field("season_year", pa.large_string(), metadata={b"x": b"y"}))),
    )

    for schema in hostile:
        with pytest.raises(FieldFateStructureError, match="request-scope"):
            structure.route_landing_fields(route_id, schema)


def test_request_scope_field_denominator_is_separate_from_provider_bindings(
    structure: FieldFateStructureV1,
) -> None:
    routes = staging_route_contract_bundle().routes
    scope_fields = tuple(item for route in routes for item in route.request_scope_storage_fields)

    assert len(scope_fields) == EXPECTED_REQUEST_SCOPE_STORAGE_FIELD_COUNT == 608
    assert len(structure.route_bindings.bindings) == EXPECTED_ROUTE_FIELD_BINDING_COUNT
    assert len(structure.storage_sinks.sinks) == EXPECTED_STORAGE_SINK_COUNT == 13_260
    assert all(
        item.storage_column not in route.storage_columns
        for route in routes
        for item in route.request_scope_storage_fields
    )


def test_route_landing_fields_reject_noncanonical_arrow_schemas(
    structure: FieldFateStructureV1,
) -> None:
    route_id = "static_players:stg_static_players:0"
    exact = _route_arrow_schema(route_id)
    fields = list(exact)
    wrong_type = pa.field(fields[0].name, pa.string())
    renamed = pa.field("wrong_name", fields[0].type)
    field_metadata = pa.field(
        fields[0].name,
        fields[0].type,
        metadata={b"foreign": b"metadata"},
    )
    nonnullable = pa.field(fields[0].name, fields[0].type, nullable=False)
    hostile_schemas = (
        pa.schema((*fields[1:], fields[0])),
        pa.schema((renamed, *fields[1:])),
        pa.schema(fields[:-1]),
        pa.schema((*fields, pa.field("invented", pa.string()))),
        pa.schema((wrong_type, *fields[1:])),
        pa.schema(fields, metadata={b"foreign": b"metadata"}),
        pa.schema((field_metadata, *fields[1:])),
        pa.schema((nonnullable, *fields[1:])),
    )

    for hostile in hostile_schemas:
        with pytest.raises(FieldFateStructureError, match="Arrow"):
            structure.route_landing_fields(route_id, hostile)
    with pytest.raises(FieldFateStructureError, match="exact Arrow schema"):
        structure.route_landing_fields(route_id, object())  # type: ignore[arg-type]


@pytest.mark.parametrize(
    "route_id",
    (
        "live_play_by_play:stg_nba_api_live_lossless_nodes:1",
        "league_game_log:stg_nba_api_lossless_result_cells:1",
    ),
)
def test_route_landing_fields_fail_closed_without_conditional_sink_authority(
    structure: FieldFateStructureV1,
    route_id: str,
) -> None:
    with pytest.raises(
        FieldFateStructureError,
        match="conditional lossless route requires exact occurrence authority",
    ):
        structure.route_landing_fields(
            route_id,
            _route_arrow_schema("static_players:stg_static_players:0"),
        )
    assert not any(item.route_id == route_id for item in structure.storage_sinks.sinks)


def test_selected_stats_conditional_route_joins_exact_occurrence_local_rows(
    structure: FieldFateStructureV1,
) -> None:
    route_id, frame, authority = _selected_stats_conditional_authority(structure)

    validated = validate_conditional_route_occurrence_authority(
        authority,
        structure=structure,
    )
    fields = structure.route_landing_fields(
        route_id,
        frame.to_arrow().schema,
        conditional_authority=authority,
    )

    assert validated.source_shape == "selected_result_bound"
    assert validated.source_family == "stats"
    assert validated.route_local_ordinal == 1
    assert validated.source_parameters_sha256s
    assert validated.source_parameters_sha256s == (validated.committed_logical_parameters_sha256,)
    assert validated.staging_parameters_sha256 is None
    assert len(validated.stats_bindings) == frame.height
    assert all(
        type(item) is StatsLosslessFieldBindingV1
        and item.binding_kind == "selected_result_bound"
        and item.source_occurrence_sha256 is not None
        and item.body_object_sha256 is None
        for item in validated.stats_bindings
    )
    assert tuple(item.sink.storage_column for item in fields) == tuple(frame.columns)
    assert {item.origin for item in fields} == {"lossless_bound", "storage_only"}
    assert all(not item.route_bindings for item in fields)
    assert all(not item.provider_sources for item in fields)
    assert not any(item.route_id == route_id for item in structure.storage_sinks.sinks)


def test_selected_unknown_stats_route_binds_legacy_results_and_response_nodes(
    structure: FieldFateStructureV1,
) -> None:
    route_id, frame, authority = _selected_unknown_stats_conditional_authority(structure)

    validated = validate_conditional_route_occurrence_authority(
        authority,
        structure=structure,
    )
    fields = structure.route_landing_fields(
        route_id,
        frame.to_arrow().schema,
        conditional_authority=authority,
    )

    assert validated.source_shape == "hybrid_result_body_bound"
    assert validated.source_family == "stats"
    assert len(validated.result_occurrence_sha256s) == 2
    assert len(validated.body_object_sha256s) == 1
    assert validated.source_parameters_sha256s == (validated.committed_logical_parameters_sha256,)
    assert validated.staging_parameters_sha256 is not None
    assert validated.staging_parameters_sha256 != validated.committed_logical_parameters_sha256
    assert len(validated.stats_bindings) == frame.height
    result_bound = tuple(
        item for item in validated.stats_bindings if item.binding_kind == "selected_result_bound"
    )
    body_bound = tuple(
        item for item in validated.stats_bindings if item.binding_kind == "body_node_bound"
    )
    assert result_bound and body_bound
    assert {item.record_kind for item in body_bound} == {"response", "json_node"}
    assert {
        item.result_set_occurrence for item in result_bound if item.record_kind == "result_set"
    } == {
        0,
        1,
    }
    assert all(item.source_occurrence_sha256 is not None for item in result_bound)
    assert all(item.body_object_sha256 == validated.body_object_sha256s[0] for item in body_bound)
    assert tuple(item.sink.storage_column for item in fields) == tuple(frame.columns)


def test_selected_unknown_stats_route_rejects_resealed_fixed_route_injection(
    structure: FieldFateStructureV1,
) -> None:
    route_id, _frame, authority = _selected_unknown_stats_conditional_authority(structure)
    original = authority.raw_bundle.occurrences[0]
    fixed_route_id = "video_events:stg_video_events:0"
    receipts = list(json.loads(original.committed_staging_receipts_json))
    receipts.append(
        {
            "receipt_sha256": "e" * 64,
            "route_id": fixed_route_id,
        }
    )
    replacement = _rebuild_result_occurrence(
        original,
        canonical_route_ids=(fixed_route_id, route_id),
        committed_staging_receipts=tuple(receipts),
        landing_disposition="wide_plus_lossless",
    )
    with pytest.raises(
        ValueError,
        match="route landing source occurrence denominator is invalid",
    ):
        _replace_bundle_occurrence(authority.raw_bundle, replacement)


def test_selected_stats_conditional_route_rejects_response_receipt_rebinding(
    structure: FieldFateStructureV1,
) -> None:
    with pytest.raises(
        RawRequestFinalizationError,
        match="post-commit authority is not closed",
    ):
        _selected_stats_conditional_authority(
            structure,
            frame_response_receipt_sha256="d" * 64,
        )


def test_selected_stats_conditional_route_rejects_parser_body_rebinding(
    structure: FieldFateStructureV1,
) -> None:
    route_id, _frame, authority = _selected_stats_conditional_authority(structure)
    original = authority.raw_bundle.observations[0]
    foreign_body = ParserInputObjectV2.from_parser_input('{"fixture":true}')
    observation = RequestObservationV2.build(
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
        result_occurrence_sha256s=tuple(
            item.occurrence_sha256 for item in authority.raw_bundle.occurrences
        ),
        route_landing_sha256s=tuple(item.landing_sha256 for item in authority.raw_bundle.landings),
        capture_response_receipt_sha256=original.capture_response_receipt_sha256,
        logical_receipt_sha256=original.logical_receipt_sha256,
    )
    with pytest.raises(
        ValueError,
        match="ordinary result inventory cannot be rederived exactly",
    ):
        RawRequestAuthorityBundleV2.build(
            objects=(foreign_body,),
            observations=(observation,),
            occurrences=authority.raw_bundle.occurrences,
            landings=authority.raw_bundle.landings,
        )


def test_stats_lossless_row_identity_is_serialized_and_resealed_mutation_rejected(
    structure: FieldFateStructureV1,
) -> None:
    _route_id, _frame, authority = _selected_stats_conditional_authority(structure)
    binding = authority.stats_bindings[0]
    original_binding_sha256 = binding.binding_sha256

    assert binding.to_dict()["row_identity_json"] == binding.row_identity_json
    row_identity = json.loads(binding.row_identity_json)
    row_identity["record_kind"] = "forged_record_kind"
    forged_json = canonical_json_bytes(row_identity).decode("utf-8")
    object.__setattr__(binding, "row_identity_json", forged_json)
    object.__setattr__(
        binding,
        "row_identity_sha256",
        structure_module.canonical_sha256(row_identity),
    )
    resealed_binding_evidence = binding.to_dict()
    resealed_binding_evidence.pop("binding_evidence_sha256")
    object.__setattr__(
        binding,
        "binding_evidence_sha256",
        structure_module.canonical_sha256(resealed_binding_evidence),
    )
    assert binding.binding_sha256 != original_binding_sha256
    object.__setattr__(
        authority,
        "authority_sha256",
        structure_module.canonical_sha256(authority.identity_payload()),
    )

    with pytest.raises(FieldFateStructureError, match="differs from exact sources"):
        validate_conditional_route_occurrence_authority(
            authority,
            structure=structure,
        )


def test_live_conditional_route_reuses_exact_lossless_field_bindings(
    structure: FieldFateStructureV1,
) -> None:
    route_id, frame, authority = _live_conditional_authority(structure)

    fields = structure.route_landing_fields(
        route_id,
        frame.to_arrow().schema,
        conditional_authority=authority,
    )

    assert authority.source_shape == "live_lossless_bound"
    assert authority.source_family == "live"
    assert authority.stats_bindings == ()
    assert len(authority.live_binding_ids) == 57
    assert authority.staging_parameters_sha256 is None
    assert tuple(item.sink.storage_column for item in fields) == tuple(frame.columns)
    bound = [item for item in fields if item.origin == "lossless_bound"]
    assert bound
    assert all(item.provider_sources for item in bound)
    assert all(len(item.lossless_bindings) == len(item.provider_sources) for item in bound)
    assert all(source.source_family == "live" for item in bound for source in item.provider_sources)


def test_live_conditional_route_rejects_response_receipt_rebinding(
    structure: FieldFateStructureV1,
) -> None:
    with pytest.raises(
        RawRequestFinalizationError,
        match="committed staging receipt differs from exact route-frame rederivation",
    ):
        _live_conditional_authority(
            structure,
            frame_response_receipt_sha256="d" * 64,
        )


def test_live_conditional_route_rejects_endpoint_contract_rebinding(
    structure: FieldFateStructureV1,
) -> None:
    _route_id, _frame, authority = _live_conditional_authority(structure)
    with pytest.raises(
        ValueError,
        match="fixed route landing differs from pinned route authority",
    ):
        _rebind_bundle_endpoint_contract(authority.raw_bundle, "e" * 64)


def test_live_conditional_route_rejects_resealed_snapshot_time_rebinding(
    structure: FieldFateStructureV1,
) -> None:
    route_id, frame, authority = _live_conditional_authority(structure)
    forged_bundle, forged_readback = _reseal_live_snapshot_authority(
        authority=authority,
        route_id=route_id,
        frame=frame,
        snapshot_at=datetime(2026, 8, 28, 12, 0, tzinfo=UTC),
    )
    conditional_landing = next(
        landing for landing in forged_bundle.landings if landing.route_id == route_id
    )

    assert conditional_landing.live_snapshot_at == datetime(2026, 8, 27, 12, 0, tzinfo=UTC)
    assert (
        conditional_landing.receipt_root_sha256
        == forged_readback.committed_receipt.receipt_root_sha256
    )
    with pytest.raises(
        FieldFateStructureError,
        match="frame snapshot differs from selected route landing",
    ):
        derive_conditional_route_occurrence_authority(
            structure=structure,
            route_id=route_id,
            raw_bundle=forged_bundle,
            readback=forged_readback,
        )


@pytest.mark.parametrize(
    ("field_name", "forged_value"),
    (
        ("output_sha256", "e" * 64),
        ("result_name", "forged_live_result"),
        ("canonical_result_ordinal", 999),
    ),
)
def test_live_conditional_route_rejects_resealed_result_denominator_mutations(
    structure: FieldFateStructureV1,
    field_name: str,
    forged_value: object,
) -> None:
    route_id, _frame, authority = _live_conditional_authority(structure)
    original = min(
        authority.raw_bundle.occurrences,
        key=lambda item: item.occurrence_ordinal,
    )
    replacement = _rebuild_result_occurrence(
        original,
        **{field_name: forged_value},
    )
    with pytest.raises(
        ValueError,
        match="route landing source occurrence denominator is invalid",
    ):
        _replace_bundle_occurrence(authority.raw_bundle, replacement)


def test_zero_occurrence_video_terminal_route_remains_body_node_bound(
    structure: FieldFateStructureV1,
) -> None:
    route_id, frame, authority = _body_node_conditional_authority(structure)

    fields = structure.route_landing_fields(
        route_id,
        frame.to_arrow().schema,
        conditional_authority=authority,
    )

    assert authority.source_shape == "body_node_bound"
    assert authority.result_occurrence_sha256s == ()
    assert len(authority.body_object_sha256s) == 1
    assert authority.source_parameters_sha256s == (authority.committed_logical_parameters_sha256,)
    assert authority.staging_parameters_sha256 is not None
    assert authority.staging_parameters_sha256 != authority.source_parameters_sha256s[0]
    assert len(authority.stats_bindings) == frame.height
    assert all(
        item.binding_kind == "body_node_bound"
        and item.source_occurrence_sha256 is None
        and item.body_object_sha256 == authority.body_object_sha256s[0]
        for item in authority.stats_bindings
    )
    assert any(
        item.record_kind == "json_node" and item.json_path == "$"
        for item in authority.stats_bindings
    )
    assert all(not item.provider_sources for item in fields)
    assert all(
        item.origin != "lossless_bound"
        or all(
            type(binding) is StatsLosslessFieldBindingV1
            and binding.binding_kind == "body_node_bound"
            for binding in item.lossless_bindings
        )
        for item in fields
    )


def test_incomplete_video_conditional_route_is_rejected(
    structure: FieldFateStructureV1,
) -> None:
    snapshot, binding, receipts = _unknown_stats_case(
        "video_details",
        {"unexpected": {"nested": [1]}},
        include_results=False,
    )
    pending = snapshot.pending_successes[0]
    assert pending.body_object is not None
    parser_input = decode_parser_input_object(pending.body_object)
    unknown = rederive_raw_authority_unknown_stats_response(
        endpoint_id=pending.attempt.endpoint_id,
        parser_input=parser_input,
        safe_parameters_json=pending.attempt.safe_parameters_json,
        provider_authority_sha256=pending.attempt.provider_authority_sha256,
        endpoint_contract_sha256_value=pending.attempt.endpoint_contract_sha256,
    ).bind_response_receipt(pending.private_receipt_sha256)
    fallback = build_unknown_stats_lossless_fallback(unknown)
    assert fallback is not None
    raw_bundle = materialize_raw_request_incomplete_success_snapshot(
        snapshot,
        binding,
        receipts,
    )
    receipt = next(
        item for item in receipts if item.staging_key == "stg_nba_api_lossless_result_cells"
    )
    readback = CommittedStagingFrameReadbackV2.build(
        committed_receipt=receipt,
        frame=fallback.frame,
    )

    assert raw_bundle.observations[0].lifecycle == "incomplete"
    assert raw_bundle.landings == ()
    with pytest.raises(
        FieldFateStructureError,
        match="conditional selected route authority is invalid",
    ):
        derive_conditional_route_occurrence_authority(
            structure=structure,
            route_id=receipt.result_route_id,
            raw_bundle=raw_bundle,
            readback=readback,
        )


def test_named_video_occurrence_cannot_be_reclassified_as_body_node_bound(
    structure: FieldFateStructureV1,
) -> None:
    _route_id, _frame, authority = _body_node_conditional_authority(
        structure,
        payload={
            "resultSets": [
                {
                    "name": "Stats",
                    "headers": ["C"],
                    "rowSet": [[3]],
                }
            ]
        },
        include_results=True,
    )

    assert authority.source_shape == "hybrid_result_body_bound"
    assert authority.result_occurrence_sha256s
    assert any(item.binding_kind == "selected_result_bound" for item in authority.stats_bindings)


def test_body_node_conditional_route_rejects_embedded_result_occurrence(
    structure: FieldFateStructureV1,
) -> None:
    route_id, _frame, authority = _body_node_conditional_authority(structure)
    original = authority.raw_bundle.observations[0]
    receipt_root = authority.readback.committed_receipt.receipt_root_sha256
    occurrence = ResultOccurrenceV2.build(
        observation_sha256=original.attempt.observation_sha256,
        occurrence_ordinal=0,
        result_name="forged_result",
        duplicate_name_ordinal=0,
        provider_result_ordinal=0,
        canonical_result_ordinal=None,
        json_path=None,
        container_kind="nba_api_result_set",
        presence="present",
        ordered_headers=("X",),
        row_count=1,
        cell_count=1,
        node_count=0,
        container_count=1,
        missing_count=0,
        null_count=0,
        parent_state_sha256=None,
        output_sha256="a" * 64,
        canonical_route_ids=(route_id,),
        committed_staging_receipts=({"route_id": route_id, "receipt_sha256": receipt_root},),
        landing_disposition="lossless_only",
    )
    observation = RequestObservationV2.build(
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
        body_object_sha256=original.body_object_sha256,
        bodyless_evidence_sha256=original.bodyless_evidence_sha256,
        result_occurrence_sha256s=(occurrence.occurrence_sha256,),
        route_landing_sha256s=tuple(item.landing_sha256 for item in authority.raw_bundle.landings),
        capture_response_receipt_sha256=original.capture_response_receipt_sha256,
        logical_receipt_sha256=original.logical_receipt_sha256,
    )
    with pytest.raises(ValueError, match="route landing source occurrence denominator"):
        RawRequestAuthorityBundleV2.build(
            objects=authority.raw_bundle.objects,
            observations=(observation,),
            occurrences=(occurrence,),
            landings=authority.raw_bundle.landings,
        )


def test_body_node_conditional_route_rejects_endpoint_contract_rebinding(
    structure: FieldFateStructureV1,
) -> None:
    _route_id, _frame, authority = _body_node_conditional_authority(structure)
    with pytest.raises(
        ValueError,
        match="successful outcome lacks a declared result occurrence",
    ):
        _rebind_bundle_endpoint_contract(authority.raw_bundle, "e" * 64)


@pytest.mark.parametrize(
    ("column_name", "forged_digest", "error_match"),
    (
        (
            "response_receipt_sha256",
            "e" * 64,
            "conditional selected route authority is invalid",
        ),
        (
            "parameters_sha256",
            "f" * 64,
            "conditional selected route authority is invalid",
        ),
    ),
)
def test_body_node_route_rejects_recomputed_v2_frame_identity_mutations(
    structure: FieldFateStructureV1,
    column_name: str,
    forged_digest: str,
    error_match: str,
) -> None:
    route_id, frame, authority = _body_node_conditional_authority(structure)
    forged_frame = frame.with_columns(pl.lit(forged_digest).alias(column_name))
    content_sha256 = frame_content_hash(forged_frame)
    forged_receipt = replace(
        authority.readback.committed_receipt,
        content_hash=content_sha256,
        persisted_row_count=forged_frame.height,
        persisted_content_sha256=content_sha256,
        persisted_schema_sha256=frame_schema_hash(forged_frame),
    )
    forged_readback = CommittedStagingFrameReadbackV2.build(
        committed_receipt=forged_receipt,
        frame=forged_frame,
    )

    with pytest.raises(FieldFateStructureError, match=error_match):
        derive_conditional_route_occurrence_authority(
            structure=structure,
            route_id=route_id,
            raw_bundle=authority.raw_bundle,
            readback=forged_readback,
        )


def test_conditional_route_join_rejects_foreign_roots_routes_and_schemas(
    structure: FieldFateStructureV1,
) -> None:
    selected_route, selected_frame, selected = _selected_stats_conditional_authority(structure)
    body_route, body_frame, body = _body_node_conditional_authority(structure)

    with pytest.raises(
        FieldFateStructureError,
        match="source authority|receipt|admission|raw observation|selected route authority",
    ):
        structure.route_landing_fields(
            body_route,
            body_frame.to_arrow().schema,
            conditional_authority=replace(body, raw_bundle=selected.raw_bundle),
        )
    with pytest.raises(FieldFateStructureError, match="foreign route"):
        structure.route_landing_fields(
            selected_route,
            selected_frame.to_arrow().schema,
            conditional_authority=body,
        )
    hostile_schema = pa.schema(list(reversed(selected_frame.to_arrow().schema)))
    with pytest.raises(FieldFateStructureError, match="Arrow fields"):
        structure.route_landing_fields(
            selected_route,
            hostile_schema,
            conditional_authority=selected,
        )
    with pytest.raises(FieldFateStructureError, match="rejects foreign conditional"):
        structure.route_landing_fields(
            "static_players:stg_static_players:0",
            _route_arrow_schema("static_players:stg_static_players:0"),
            conditional_authority=selected,
        )


def test_route_landing_join_rejects_dropped_invented_or_mixed_members(
    structure: FieldFateStructureV1,
) -> None:
    route_id = "live_play_by_play:stg_live_play_by_play:0"
    fields = structure.route_landing_fields(route_id, _route_arrow_schema(route_id))
    payload = next(item for item in fields if item.sink.storage_column == "payload_json")
    storage_only = next(item for item in fields if item.origin == "storage_only")

    with pytest.raises(FieldFateStructureError, match="binding multiplicity"):
        replace(payload, route_bindings=payload.route_bindings[:-1])
    with pytest.raises(FieldFateStructureError, match="sources differ in multiplicity"):
        replace(payload, provider_sources=payload.provider_sources[:-1])
    with pytest.raises(FieldFateStructureError, match="binding/source join"):
        replace(
            payload,
            provider_sources=(payload.provider_sources[1], *payload.provider_sources[1:]),
        )
    with pytest.raises(FieldFateStructureError, match="origin differs"):
        replace(payload, origin="provider_bound")
    with pytest.raises(FieldFateStructureError, match="origin differs"):
        replace(storage_only, origin="lossless_bound")
    with pytest.raises(FieldFateStructureError, match="sources differ in multiplicity"):
        replace(storage_only, provider_sources=(payload.provider_sources[0],))

    lossless_binding = structure.lossless_bindings[0]
    lossless_source = structure.provider_sources.by_occurrence_id[
        lossless_binding.source_occurrence_id
    ]
    with pytest.raises(FieldFateStructureError, match="cannot invent wide bindings"):
        RouteLandingFieldJoinV1(
            sink=storage_only.sink,
            route_bindings=(),
            provider_sources=(lossless_source,),
            lossless_bindings=(lossless_binding,),
            origin="lossless_bound",
        )


def test_exact_video_event_routes_add_only_two_lossless_storage_contracts(
    structure: FieldFateStructureV1,
) -> None:
    lossless_columns = tuple(StagingNbaApiLosslessResultCellsSchema.to_schema().columns)
    route_ids = (
        "video_events:stg_video_events:0",
        "video_events_asset:stg_video_events_asset:0",
    )
    sinks_by_route = {
        route_id: tuple(item for item in structure.storage_sinks.sinks if item.route_id == route_id)
        for route_id in route_ids
    }

    assert len(lossless_columns) == 31
    assert sum(len(items) for items in sinks_by_route.values()) == 62
    for items in sinks_by_route.values():
        assert tuple(item.storage_column for item in items) == lossless_columns
        assert all(item.status == "storage_only" for item in items)
        assert all(item.binding_ids == () for item in items)


def test_structure_is_canonical_frozen_and_not_model_green(
    structure: FieldFateStructureV1,
) -> None:
    assert compile_field_fate_structure() is structure
    assert json.loads(canonical_json_bytes(structure.to_dict())) == structure.to_dict()
    assert structure.identity_sha256 == structure.identity_sha256
    assert structure.to_dict()["summary"] == {
        "provider_source_occurrence_count": 9_970,
        "route_binding_count": 11_323,
        "storage_sink_count": 13_260,
        "wide_unrouted_source_occurrence_count": 276,
        "lossless_field_binding_count": 276,
        "open_blocker_count": 21,
        "source_authority_blocker_count": 21,
        "unresolved_lossless_binding_count": 0,
        "lossless_field_binding_complete": True,
        "model_green": "not_evaluated_by_structural_layer",
    }
    with pytest.raises(FrozenInstanceError):
        # The assignment itself is the assertion: the frozen model must reject it.
        structure.provider_sources.occurrences[0].provider_field_name = "changed"  # type: ignore[misc]  # ty: ignore[invalid-assignment]


def test_source_omission_overlap_and_stale_binding_fail_closed(
    structure: FieldFateStructureV1,
) -> None:
    with pytest.raises(FieldFateStructureError, match="denominator"):
        replace(
            structure.provider_sources,
            occurrences=structure.provider_sources.occurrences[:-1],
        )
    overlap = tuple(
        sorted(
            (
                *structure.provider_sources.occurrences[:-1],
                structure.provider_sources.occurrences[0],
            ),
            key=lambda item: item.occurrence_id,
        )
    )
    with pytest.raises(FieldFateStructureError, match="overlap"):
        replace(structure.provider_sources, occurrences=overlap)

    bad_binding = replace(
        structure.route_bindings.bindings[0],
        source_occurrence_sha256="0" * 64,
    )
    bad_bindings = replace(
        structure.route_bindings,
        bindings=(bad_binding, *structure.route_bindings.bindings[1:]),
    )
    rebound_sinks = replace(
        structure.storage_sinks,
        route_binding_inventory_sha256=bad_bindings.identity_sha256,
    )
    with pytest.raises(FieldFateStructureError, match="missing or stale source"):
        FieldFateStructureV1(
            provider_sources=structure.provider_sources,
            route_bindings=bad_bindings,
            storage_sinks=rebound_sinks,
            lossless_bindings=structure.lossless_bindings,
            blockers=structure.blockers,
        )


def test_validation_rejects_semantically_mutated_route_binding(
    structure: FieldFateStructureV1,
) -> None:
    changed_binding = replace(
        structure.route_bindings.bindings[0],
        provider_column="STALE_PROVIDER_COLUMN",
    )
    changed_routes = replace(
        structure.route_bindings,
        bindings=(changed_binding, *structure.route_bindings.bindings[1:]),
    )
    changed_sinks = replace(
        structure.storage_sinks,
        route_binding_inventory_sha256=changed_routes.identity_sha256,
    )
    changed = FieldFateStructureV1(
        provider_sources=structure.provider_sources,
        route_bindings=changed_routes,
        storage_sinks=changed_sinks,
        lossless_bindings=structure.lossless_bindings,
        blockers=structure.blockers,
    )
    with pytest.raises(FieldFateStructureError, match="current authorities"):
        validate_field_fate_structure(changed)


def test_structural_module_has_no_star_or_assurance_parent_cycle() -> None:
    source = Path(structure_module.__file__).read_text(encoding="utf-8")
    forbidden_imports = (
        "nbadb.contracts.assurance",
        "nbadb.contracts.field_fate_contract",
        "nbadb.schemas.star",
        "nbadb.transform",
    )
    assert all(f"from {name} import" not in source for name in forbidden_imports)
