from __future__ import annotations

import hashlib
import json
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from typing import Literal, cast

import polars as pl
import pytest

from nbadb.contracts import raw_request_reconstruction as reconstruction_module
from nbadb.contracts.raw_request_authority import (
    ObservationRouteLandingV2,
    ParserInputObjectV2,
    RequestAttemptIdentityV2,
    RequestObservationV2,
    ResultOccurrenceV2,
    canonical_json_bytes,
    decode_parser_input_object,
)
from nbadb.contracts.raw_request_finalization import finalize_raw_request_capture
from nbadb.contracts.raw_request_reconstruction import (
    LiveSnapshotPlanAuthorityV2,
    RawRequestReconstructionError,
    RawRequestReconstructionV2,
    ReconstructedParserInputV2,
    ReconstructedProviderResultPacketV2,
    ReconstructedRouteLandingV2,
    reconstruct_parser_input_authority,
    reconstruct_provider_result_packets,
    reconstruct_raw_request_authority,
    reconstruct_route_landings,
    validate_raw_request_reconstruction,
)
from nbadb.contracts.staging_route_contract import staging_route_contract_bundle
from nbadb.core.nba_api_runtime_contract import pinned_live_contracts
from nbadb.orchestrate.staging_batches import (
    CANONICAL_FRAME_FORMAT,
    FRAME_CONTENT_HASH_CONTRACT,
    FRAME_SCHEMA_HASH_CONTRACT,
    CommittedStagingChunkReceiptV2,
    frame_content_hash,
    frame_schema_hash,
)
from tests.unit.contracts.test_raw_request_authority import _strict_stats_bundle
from tests.unit.contracts.test_raw_request_finalization import (
    _case as _finalization_case,
)
from tests.unit.contracts.test_raw_request_finalization import (
    _live_plan_authority as _finalization_live_plan_authority,
)
from tests.unit.contracts.test_raw_request_finalization import (
    _replace_live_payload,
    _replace_stats_payload,
)
from tests.unit.extract.test_live_lossless_nodes import _complete_endpoint_payload

_HASHES = tuple(f"{value:064x}" for value in range(1, 200))
_SOURCE_SHA = "a" * 40
_STARTED_AT = datetime(2026, 8, 27, 12, 0, tzinfo=UTC)


class _AlwaysEqual:
    def __eq__(self, _other: object) -> bool:
        return True


def _sha(value: str | bytes) -> str:
    raw = value if isinstance(value, bytes) else value.encode()
    return hashlib.sha256(raw).hexdigest()


def _parent_state_sha256(*states: str) -> str:
    return _sha(canonical_json_bytes(list(states)))


def _attempt(
    *,
    source_family: Literal["stats", "live", "static"] = "live",
    endpoint_id: str = "ScoreBoard",
    parameters: dict[str, object] | None = None,
    retry_ordinal: int = 0,
    request_ordinal: int = 0,
    provider_authority_sha256: str = _HASHES[2],
    endpoint_contract_sha256: str = _HASHES[3],
) -> RequestAttemptIdentityV2:
    return RequestAttemptIdentityV2.build(
        semantic_request_sha256=_HASHES[0],
        logical_invocation_sha256=_HASHES[1],
        provider_call_role="primary",
        provider_call_ordinal=0,
        retry_ordinal=retry_ordinal,
        request_ordinal=request_ordinal,
        source_family=source_family,
        endpoint_id=endpoint_id,
        parameters={} if parameters is None else parameters,
        provider_authority_sha256=provider_authority_sha256,
        endpoint_contract_sha256=endpoint_contract_sha256,
        competition_id=None,
        competition_identity_sha256=None,
        scope_sha256=_HASHES[4],
        pagination_sha256=None,
        page_ordinal=None,
        source_sha=_SOURCE_SHA,
        run_id=101,
        run_attempt=1,
        chain_id="chain",
        lane_id="lane",
    )


def _receipt_payloads(route_ids: tuple[str, ...]) -> list[dict[str, str]]:
    return [
        {
            "route_id": route_id,
            "receipt_sha256": _sha(f"committed:{route_id}"),
        }
        for route_id in route_ids
    ]


def _route(endpoint_name: str):
    matches = tuple(
        route
        for route in staging_route_contract_bundle().routes
        if route.endpoint_name == endpoint_name
    )
    assert len(matches) == 1
    return matches[0]


def _committed_receipt(
    attempt: RequestAttemptIdentityV2,
    *,
    route_id: str,
    staging_key: str,
    row_count: int,
    salt: str,
) -> CommittedStagingChunkReceiptV2:
    content = _sha(f"content:{salt}")
    schema = _sha(f"schema:{salt}")
    return CommittedStagingChunkReceiptV2(
        chunk_id=f"chunk:{salt}",
        staging_key=staging_key,
        canonical_frame_format=CANONICAL_FRAME_FORMAT,
        frame_content_hash_contract=FRAME_CONTENT_HASH_CONTRACT,
        frame_schema_hash_contract=FRAME_SCHEMA_HASH_CONTRACT,
        content_hash=content,
        persisted_row_count=row_count,
        persisted_content_sha256=content,
        persisted_schema_sha256=schema,
        logical_call_receipt_sha256=_HASHES[20],
        provider_authority_sha256=attempt.provider_authority_sha256,
        logical_parameters_sha256=attempt.safe_parameters_sha256,
        result_route_id=route_id,
    )


def _receipt_payload(receipt: CommittedStagingChunkReceiptV2) -> dict[str, str]:
    return {
        "route_id": receipt.result_route_id,
        "receipt_sha256": receipt.receipt_root_sha256,
    }


def _receipt_from_landing(
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


def _rebuild_landing(
    landing: ObservationRouteLandingV2,
    *,
    source_occurrence_sha256s: tuple[str, ...],
    **updates: object,
) -> ObservationRouteLandingV2:
    payload: dict[str, object] = {
        "observation_sha256": landing.observation_sha256,
        "logical_receipt_sha256": landing.logical_receipt_sha256,
        "route_ordinal": landing.route_ordinal,
        "route_authority_kind": landing.route_authority_kind,
        "route_authority_sha256": landing.route_authority_sha256,
        "landing_semantic": landing.landing_semantic,
        "conditional_lossless": landing.conditional_lossless,
        "alias_target_route_id": landing.alias_target_route_id,
        "live_snapshot_at": landing.live_snapshot_at,
        "source_occurrence_sha256s": source_occurrence_sha256s,
        "committed_receipt": _receipt_from_landing(landing),
    }
    payload.update(updates)
    return ObservationRouteLandingV2.build(**payload)  # type: ignore[arg-type]


def _fixed_landing(
    attempt: RequestAttemptIdentityV2,
    occurrence: ResultOccurrenceV2,
    receipt: CommittedStagingChunkReceiptV2,
    *,
    route_ordinal: int = 0,
    live_snapshot_at: datetime | None = None,
) -> ObservationRouteLandingV2:
    route = staging_route_contract_bundle().by_route_id[receipt.result_route_id]
    return ObservationRouteLandingV2.build(
        observation_sha256=attempt.observation_sha256,
        logical_receipt_sha256=_HASHES[20],
        route_ordinal=route_ordinal,
        route_authority_kind="staging_route_contract_v1",
        route_authority_sha256=route.contract_sha256,
        landing_semantic="occurrence_bound",
        conditional_lossless=False,
        alias_target_route_id=None,
        live_snapshot_at=live_snapshot_at,
        source_occurrence_sha256s=[occurrence.occurrence_sha256],
        committed_receipt=receipt,
    )


def _terminal_observation(
    attempt: RequestAttemptIdentityV2,
    body: ParserInputObjectV2 | None,
    occurrences: tuple[ResultOccurrenceV2, ...],
    landings: tuple[ObservationRouteLandingV2, ...],
    *,
    outcome: Literal[
        "success_nonempty",
        "success_empty",
        "static_snapshot_success",
    ],
    bodyless_evidence_sha256: str | None = None,
) -> RequestObservationV2:
    return RequestObservationV2.build(
        attempt=attempt,
        transport=(
            {"transport_kind": "static_snapshot"}
            if attempt.source_family == "static"
            else {
                "transport_kind": f"{attempt.source_family}_http",
                "status_code": 200,
                "effective_status_code": 200,
            }
        ),
        started_at=_STARTED_AT,
        finished_at=_STARTED_AT + timedelta(seconds=1),
        elapsed_ns=1_000_000_000,
        lifecycle="selected_terminal",
        outcome=outcome,
        failure_class=None,
        root_exception_class=None,
        body_disposition="declared_bodyless" if body is None else "public_parser_input",
        body_object_sha256=None if body is None else body.object_sha256,
        bodyless_evidence_sha256=bodyless_evidence_sha256,
        result_occurrence_sha256s=[item.occurrence_sha256 for item in occurrences],
        route_landing_sha256s=[item.landing_sha256 for item in landings],
        capture_response_receipt_sha256=_HASHES[21],
        logical_receipt_sha256=_HASHES[20],
    )


def _live_plan_authority(
    observation: RequestObservationV2,
    landings: tuple[ObservationRouteLandingV2, ...],
    *,
    sealed_plan_bytes: bytes = b'{"kind":"fixture-sealed-plan","version":2}',
) -> LiveSnapshotPlanAuthorityV2:
    snapshot_values = {item.live_snapshot_at for item in landings}
    assert len(snapshot_values) == 1
    snapshot_at = next(iter(snapshot_values))
    assert snapshot_at is not None
    return LiveSnapshotPlanAuthorityV2.build(
        sealed_plan_bytes=sealed_plan_bytes,
        attempt=observation.attempt,
        route_ids=tuple(item.route_id for item in landings),
        live_snapshot_at=snapshot_at,
    )


def _foreign_live_plan_authority(
    observation: RequestObservationV2,
    landings: tuple[ObservationRouteLandingV2, ...],
    **attempt_updates: object,
) -> LiveSnapshotPlanAuthorityV2:
    original = observation.attempt
    attempt_values: dict[str, object] = {
        "semantic_request_sha256": original.semantic_request_sha256,
        "logical_invocation_sha256": original.logical_invocation_sha256,
        "provider_call_role": original.provider_call_role,
        "provider_call_ordinal": original.provider_call_ordinal,
        "retry_ordinal": original.retry_ordinal,
        "request_ordinal": original.request_ordinal,
        "source_family": original.source_family,
        "endpoint_id": original.endpoint_id,
        "parameters": json.loads(original.safe_parameters_json),
        "provider_authority_sha256": original.provider_authority_sha256,
        "endpoint_contract_sha256": original.endpoint_contract_sha256,
        "competition_id": original.competition_id,
        "competition_identity_sha256": original.competition_identity_sha256,
        "scope_sha256": original.scope_sha256,
        "pagination_sha256": original.pagination_sha256,
        "page_ordinal": original.page_ordinal,
        "source_sha": original.source_sha,
        "run_id": original.run_id,
        "run_attempt": original.run_attempt,
        "chain_id": original.chain_id,
        "lane_id": original.lane_id,
    }
    attempt_values.update(attempt_updates)
    foreign_attempt = RequestAttemptIdentityV2.build(**attempt_values)  # type: ignore[arg-type]
    snapshot = landings[0].live_snapshot_at
    assert snapshot is not None
    return LiveSnapshotPlanAuthorityV2.build(
        sealed_plan_bytes=b'{"kind":"foreign-sealed-plan","version":2}',
        attempt=foreign_attempt,
        route_ids=tuple(item.route_id for item in landings),
        live_snapshot_at=snapshot,
    )


def _reconstruct_raw(
    body: ParserInputObjectV2 | None,
    observation: RequestObservationV2,
    occurrences: tuple[ResultOccurrenceV2, ...],
    landings: tuple[ObservationRouteLandingV2, ...],
) -> RawRequestReconstructionV2:
    if observation.attempt.source_family != "live" or not landings:
        return reconstruct_raw_request_authority(body, observation, occurrences, landings)
    plan = _live_plan_authority(observation, landings)
    return reconstruct_raw_request_authority(
        body,
        observation,
        occurrences,
        landings,
        live_plan_authority=plan,
        expected_live_plan_authority_sha256=plan.authority_sha256,
    )


def _reconstruct_parser(
    body: ParserInputObjectV2 | None,
    observation: RequestObservationV2,
    occurrences: tuple[ResultOccurrenceV2, ...],
    landings: tuple[ObservationRouteLandingV2, ...],
) -> ReconstructedParserInputV2:
    if observation.attempt.source_family != "live" or not landings:
        return reconstruct_parser_input_authority(body, observation, occurrences, landings)
    plan = _live_plan_authority(observation, landings)
    return reconstruct_parser_input_authority(
        body,
        observation,
        occurrences,
        landings,
        live_plan_authority=plan,
        expected_live_plan_authority_sha256=plan.authority_sha256,
    )


def _reconstruct_packets(
    body: ParserInputObjectV2 | None,
    observation: RequestObservationV2,
    occurrences: tuple[ResultOccurrenceV2, ...],
    landings: tuple[ObservationRouteLandingV2, ...],
) -> tuple[ReconstructedProviderResultPacketV2, ...]:
    if observation.attempt.source_family != "live" or not landings:
        return reconstruct_provider_result_packets(body, observation, occurrences, landings)
    plan = _live_plan_authority(observation, landings)
    return reconstruct_provider_result_packets(
        body,
        observation,
        occurrences,
        landings,
        live_plan_authority=plan,
        expected_live_plan_authority_sha256=plan.authority_sha256,
    )


def _reconstruct_landings(
    body: ParserInputObjectV2 | None,
    observation: RequestObservationV2,
    occurrences: tuple[ResultOccurrenceV2, ...],
    landings: tuple[ObservationRouteLandingV2, ...],
) -> tuple[ReconstructedRouteLandingV2, ...]:
    if observation.attempt.source_family != "live" or not landings:
        return reconstruct_route_landings(body, observation, occurrences, landings)
    try:
        plan = _live_plan_authority(observation, landings)
    except (AssertionError, RawRequestReconstructionError):
        # Malformed landing inventories must be rejected by four-table closure
        # before a live-plan authority can be projected from them.
        return reconstruct_route_landings(body, observation, occurrences, landings)
    return reconstruct_route_landings(
        body,
        observation,
        occurrences,
        landings,
        live_plan_authority=plan,
        expected_live_plan_authority_sha256=plan.authority_sha256,
    )


def _live_case() -> tuple[
    ParserInputObjectV2,
    RequestObservationV2,
    tuple[ResultOccurrenceV2, ...],
    tuple[ObservationRouteLandingV2, ...],
    bytes,
]:
    snapshot, binding, _receipts = _finalization_case("live")
    contract = pinned_live_contracts()["ScoreBoard"]
    payload = _complete_endpoint_payload(contract)
    scoreboard = cast("dict[str, object]", payload["scoreboard"])
    scoreboard["games"] = []
    snapshot, receipts = _replace_live_payload(snapshot, binding, payload)
    plan = _finalization_live_plan_authority(snapshot, binding)
    bundle = finalize_raw_request_capture(
        snapshot,
        binding,
        receipts,
        live_plan_authority=plan,
        expected_live_plan_authority_sha256=plan.authority_sha256,
    )
    body = bundle.objects[0]
    exact_bytes = decode_parser_input_object(body)
    return body, bundle.observations[0], bundle.occurrences, bundle.landings, exact_bytes


def _stats_empty_case() -> tuple[
    ParserInputObjectV2,
    RequestObservationV2,
    tuple[ResultOccurrenceV2, ...],
    tuple[ObservationRouteLandingV2, ...],
]:
    snapshot, binding, _receipts = _finalization_case("stats")
    pending = snapshot.pending_successes[0]
    body = cast("ParserInputObjectV2", pending.body_object)
    payload = cast("dict[str, object]", json.loads(decode_parser_input_object(body)))
    result_sets = cast("list[dict[str, object]]", payload["resultSets"])
    for result_set in result_sets:
        result_set["rowSet"] = []
    snapshot, receipts = _replace_stats_payload(snapshot, binding, payload)
    bundle = finalize_raw_request_capture(snapshot, binding, receipts)
    return bundle.objects[0], bundle.observations[0], bundle.occurrences, bundle.landings


def _static_case() -> tuple[
    RequestObservationV2,
    tuple[ResultOccurrenceV2, ...],
    tuple[ObservationRouteLandingV2, ...],
]:
    snapshot, binding, receipts = _finalization_case("static")
    bundle = finalize_raw_request_capture(snapshot, binding, receipts)
    return bundle.observations[0], bundle.occurrences, bundle.landings


def _stats_fallback_case() -> tuple[
    ParserInputObjectV2,
    RequestObservationV2,
    tuple[ResultOccurrenceV2, ...],
    tuple[ObservationRouteLandingV2, ...],
]:
    snapshot, binding, receipts = _finalization_case("stats", fallback=True)
    bundle = finalize_raw_request_capture(snapshot, binding, receipts)
    return bundle.objects[0], bundle.observations[0], bundle.occurrences, bundle.landings


def _video_fixed_zero_case() -> tuple[
    ParserInputObjectV2,
    RequestObservationV2,
    tuple[ResultOccurrenceV2, ...],
    tuple[ObservationRouteLandingV2, ...],
]:
    route = _route("video_details")
    attempt = _attempt(
        source_family="stats",
        endpoint_id="VideoDetails",
        parameters={"team_id": 1, "player_id": 2, "season": "2024-25"},
        provider_authority_sha256=route.provider_authority_sha256,
        endpoint_contract_sha256=route.endpoint_contract_sha256,
    )
    body = ParserInputObjectV2.from_parser_input("{}")
    empty_frame = pl.DataFrame()
    empty_content = frame_content_hash(empty_frame)
    receipt = CommittedStagingChunkReceiptV2(
        chunk_id="chunk:video-fixed-zero",
        staging_key=route.staging_key,
        canonical_frame_format=CANONICAL_FRAME_FORMAT,
        frame_content_hash_contract=FRAME_CONTENT_HASH_CONTRACT,
        frame_schema_hash_contract=FRAME_SCHEMA_HASH_CONTRACT,
        content_hash=empty_content,
        persisted_row_count=0,
        persisted_content_sha256=empty_content,
        persisted_schema_sha256=frame_schema_hash(empty_frame),
        logical_call_receipt_sha256=_HASHES[20],
        provider_authority_sha256=attempt.provider_authority_sha256,
        logical_parameters_sha256=attempt.safe_parameters_sha256,
        result_route_id=route.route_id,
    )
    landing = ObservationRouteLandingV2.build(
        observation_sha256=attempt.observation_sha256,
        logical_receipt_sha256=_HASHES[20],
        route_ordinal=0,
        route_authority_kind="staging_route_contract_v1",
        route_authority_sha256=route.contract_sha256,
        landing_semantic="response_fixed_zero",
        conditional_lossless=False,
        alias_target_route_id=None,
        live_snapshot_at=None,
        source_occurrence_sha256s=(),
        committed_receipt=receipt,
    )
    landings = (landing,)
    observation = _terminal_observation(
        attempt,
        body,
        (),
        landings,
        outcome="success_empty",
    )
    return body, observation, (), landings


def _rebuild_occurrence(
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


def _rebuild_observation(
    observation: RequestObservationV2,
    occurrences: tuple[ResultOccurrenceV2, ...],
    landings: tuple[ObservationRouteLandingV2, ...],
    *,
    body_object_sha256: str | None = None,
) -> RequestObservationV2:
    return RequestObservationV2.build(
        attempt=observation.attempt,
        transport=observation.transport,
        started_at=observation.started_at,
        finished_at=observation.finished_at,
        elapsed_ns=observation.elapsed_ns,
        lifecycle=observation.lifecycle,
        outcome=observation.outcome,
        failure_class=observation.failure_class,
        root_exception_class=observation.root_exception_class,
        body_disposition=observation.body_disposition,
        body_object_sha256=(
            observation.body_object_sha256 if body_object_sha256 is None else body_object_sha256
        ),
        bodyless_evidence_sha256=observation.bodyless_evidence_sha256,
        result_occurrence_sha256s=[item.occurrence_sha256 for item in occurrences],
        route_landing_sha256s=[item.landing_sha256 for item in landings],
        capture_response_receipt_sha256=(observation.capture_response_receipt_sha256),
        logical_receipt_sha256=observation.logical_receipt_sha256,
    )


def test_reconstructs_exact_live_parser_bytes_and_parent_topology_deterministically() -> None:
    body, observation, occurrences, landings, exact_bytes = _live_case()

    first = _reconstruct_raw(body, observation, occurrences, landings)
    second = _reconstruct_raw(body, observation, occurrences, landings)

    assert first == second
    assert first.reconstruction_sha256 == second.reconstruction_sha256
    assert first.parser_input.parser_input_bytes == exact_bytes
    assert first.parser_input.parser_input_sha256 == hashlib.sha256(exact_bytes).hexdigest()
    assert first.parser_input.parser_input_length == len(exact_bytes)
    assert len(first.result_packets) == len(occurrences) == 11
    assert [item.occurrence_ordinal for item in first.result_packets] == list(range(11))
    assert [item.route_id for item in first.route_landings] == [item.route_id for item in landings]
    assert first.route_landings[0].source_occurrence_sha256s == (occurrences[2].occurrence_sha256,)
    assert first.route_landings[1].source_occurrence_sha256s == tuple(
        item.occurrence_sha256 for item in occurrences
    )
    assert {item.live_snapshot_at for item in first.route_landings} == {
        "2026-08-27T12:00:00.000000Z"
    }

    root = first.result_packets[1]
    empty_games = first.result_packets[2]
    unobserved_child = first.result_packets[3]
    assert root.declared_parent_result_ordinal is None
    assert root.observed_parent_result_ordinal is None
    assert empty_games.presence == "empty_array"
    assert empty_games.declared_parent_result_ordinal == 1
    assert empty_games.observed_parent_result_ordinal == 1
    assert unobserved_child.presence == "not_observed_parent_empty"
    assert unobserved_child.declared_parent_result_ordinal == 2
    assert unobserved_child.observed_parent_result_ordinal is None
    assert unobserved_child.parent_state_sha256 == _parent_state_sha256()
    assert unobserved_child.container_count == unobserved_child.node_count == 0


def test_reconstructs_zero_occurrence_response_level_route_without_fabricated_packet() -> None:
    body, observation, occurrences, landings = _video_fixed_zero_case()

    reconstruction = _reconstruct_raw(
        body,
        observation,
        occurrences,
        landings,
    )

    assert reconstruction.result_packets == ()
    assert len(reconstruction.route_landings) == 1
    landing = reconstruction.route_landings[0]
    assert landing.landing_semantic == "response_fixed_zero"
    assert landing.source_occurrence_sha256s == ()
    assert landing.persisted_row_count == 0


def test_route_landing_inventory_rejects_missing_extra_reordered_and_nonexact_inputs() -> None:
    body, observation, occurrences, landings, _ = _live_case()

    with pytest.raises(RawRequestReconstructionError, match="four-table raw authority"):
        _reconstruct_landings(body, observation, occurrences, landings[:-1])
    with pytest.raises(RawRequestReconstructionError, match="four-table raw authority"):
        _reconstruct_landings(body, observation, occurrences, (*landings, landings[0]))
    with pytest.raises(RawRequestReconstructionError, match="four-table raw authority"):
        _reconstruct_landings(body, observation, occurrences, tuple(reversed(landings)))
    with pytest.raises(RawRequestReconstructionError, match="exact tuple"):
        _reconstruct_landings(body, observation, occurrences, list(landings))  # type: ignore[arg-type]

    mutated = landings[0].model_copy(update={"landing_sha256": _HASHES[160]})
    with pytest.raises(RawRequestReconstructionError, match="four-table raw authority"):
        _reconstruct_landings(body, observation, occurrences, (mutated, landings[1]))


def test_route_landing_inventory_rejects_logically_rebuilt_duplicate_fixed_route() -> None:
    body, observation, occurrences, landings, _ = _live_case()
    fixed_sources = (occurrences[2].occurrence_sha256,)
    all_sources = tuple(item.occurrence_sha256 for item in occurrences)
    duplicate_fixed = _rebuild_landing(
        landings[0],
        source_occurrence_sha256s=fixed_sources,
        route_ordinal=1,
    )
    shifted_conditional = _rebuild_landing(
        landings[1],
        source_occurrence_sha256s=all_sources,
        route_ordinal=2,
    )
    duplicate_inventory = (landings[0], duplicate_fixed, shifted_conditional)
    duplicate_observation = _rebuild_observation(
        observation,
        occurrences,
        duplicate_inventory,
    )

    with pytest.raises(RawRequestReconstructionError, match="four-table raw authority"):
        _reconstruct_landings(
            body,
            duplicate_observation,
            occurrences,
            duplicate_inventory,
        )


def test_route_landing_inventory_rejects_foreign_observation_and_split_live_time() -> None:
    body, observation, occurrences, landings, _ = _live_case()
    fixed_sources = (occurrences[2].occurrence_sha256,)
    all_sources = tuple(item.occurrence_sha256 for item in occurrences)
    foreign_fixed = _rebuild_landing(
        landings[0],
        source_occurrence_sha256s=fixed_sources,
        observation_sha256=_HASHES[161],
    )
    foreign_inventory = (foreign_fixed, landings[1])
    foreign_observation = _rebuild_observation(
        observation,
        occurrences,
        foreign_inventory,
    )
    with pytest.raises(RawRequestReconstructionError, match="four-table raw authority"):
        _reconstruct_landings(body, foreign_observation, occurrences, foreign_inventory)

    shifted_conditional = _rebuild_landing(
        landings[1],
        source_occurrence_sha256s=all_sources,
        live_snapshot_at=_STARTED_AT + timedelta(microseconds=1),
    )
    split_time_inventory = (landings[0], shifted_conditional)
    split_time_observation = _rebuild_observation(
        observation,
        occurrences,
        split_time_inventory,
    )
    with pytest.raises(RawRequestReconstructionError, match="four-table raw authority"):
        _reconstruct_landings(
            body,
            split_time_observation,
            occurrences,
            split_time_inventory,
        )


def test_reconstructs_declared_static_bodylessness_without_empty_byte_invention() -> None:
    observation, occurrences, landings = _static_case()

    reconstruction = _reconstruct_raw(None, observation, occurrences, landings)

    assert reconstruction.parser_input.parser_input_bytes is None
    assert reconstruction.parser_input.parser_input_sha256 is None
    assert reconstruction.parser_input.parser_input_length is None
    assert (
        reconstruction.parser_input.bodyless_evidence_sha256 == observation.bodyless_evidence_sha256
    )
    assert reconstruction.result_packets[0].result_name == "players_shape_1"
    assert reconstruction.result_packets[0].container_kind == "nba_api_static_records"


def test_reconstructs_no_response_bodyless_failure_with_no_result_packets() -> None:
    attempt = _attempt()
    observation = RequestObservationV2.build(
        attempt=attempt,
        transport={
            "transport_kind": "live_http",
            "status_code": None,
            "effective_status_code": None,
        },
        started_at=_STARTED_AT,
        finished_at=_STARTED_AT + timedelta(seconds=1),
        elapsed_ns=1_000_000_000,
        lifecycle="incomplete",
        outcome="transport_failure_no_response",
        failure_class="transport_transient",
        root_exception_class="ReadTimeout",
        body_disposition="no_response",
        body_object_sha256=None,
        bodyless_evidence_sha256=_sha("no-response"),
        result_occurrence_sha256s=(),
        route_landing_sha256s=(),
        capture_response_receipt_sha256=None,
        logical_receipt_sha256=None,
    )

    reconstruction = _reconstruct_raw(None, observation, (), ())

    assert reconstruction.parser_input.parser_input_bytes is None
    assert reconstruction.result_packets == ()


def test_stats_present_empty_remains_distinct_from_live_unobserved_child() -> None:
    body, observation, occurrences, landings = _stats_empty_case()
    live_body, live_observation, live_occurrences, live_landings, _ = _live_case()

    stats_packet = _reconstruct_raw(body, observation, occurrences, landings).result_packets[0]
    live_packet = _reconstruct_raw(
        live_body,
        live_observation,
        live_occurrences,
        live_landings,
    ).result_packets[3]

    assert stats_packet.presence == "present_empty"
    assert stats_packet.container_count == 1
    assert stats_packet.declared_parent_result_ordinal is None
    assert live_packet.presence == "not_observed_parent_empty"
    assert live_packet.container_count == 0
    assert live_packet.declared_parent_result_ordinal == 2
    assert live_packet.observed_parent_result_ordinal is None


def test_reconstructs_stats_lossless_fallback_without_inventing_canonical_identity() -> None:
    body, observation, occurrences, landings = _stats_fallback_case()

    packets = _reconstruct_raw(
        body,
        observation,
        occurrences,
        landings,
    ).result_packets

    assert [item.result_name for item in packets] == ["LeagueGameLog", "Extra"]
    assert [item.provider_result_ordinal for item in packets] == [0, 1]
    assert [item.canonical_result_ordinal for item in packets] == [None, None]
    assert [item.presence for item in packets] == ["present", "present"]


def test_parser_input_authority_rejects_missing_extra_and_nonexact_object_types() -> None:
    body, observation, occurrences, landings, _ = _live_case()
    static_observation, static_occurrences, static_landings = _static_case()

    with pytest.raises(RawRequestReconstructionError, match="four-table raw authority"):
        _reconstruct_parser(None, observation, occurrences, landings)
    with pytest.raises(RawRequestReconstructionError, match="four-table raw authority"):
        _reconstruct_parser(body, static_observation, static_occurrences, static_landings)
    foreign_body = ParserInputObjectV2.from_parser_input('{"different":true}')
    with pytest.raises(RawRequestReconstructionError, match="four-table raw authority"):
        _reconstruct_parser(foreign_body, observation, occurrences, landings)
    with pytest.raises(RawRequestReconstructionError, match="exact contract type"):
        _reconstruct_parser(
            body.model_dump(mode="python"),  # type: ignore[arg-type]
            observation,
            occurrences,
            landings,
        )
    with pytest.raises(RawRequestReconstructionError, match="exact tuple"):
        _reconstruct_packets(
            body,
            observation,
            list(occurrences),  # type: ignore[arg-type]
            landings,
        )


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("object_sha256", _HASHES[100]),
        ("stored_sha256", _HASHES[101]),
        ("stored_bytes", 1),
        ("uncompressed_bytes", 1),
        ("response_sha256", _HASHES[102]),
        ("stored_payload", b"not-gzip"),
    ],
)
def test_parser_input_authority_rejects_digest_length_and_payload_mutations(
    field: str,
    value: object,
) -> None:
    body, observation, occurrences, landings, _ = _live_case()
    mutated = body.model_copy(update={field: value})

    with pytest.raises(RawRequestReconstructionError, match="four-table raw authority"):
        _reconstruct_parser(mutated, observation, occurrences, landings)


def test_occurrence_inventory_rejects_missing_extra_reordered_and_digest_mutations() -> None:
    body, observation, occurrences, landings, _ = _live_case()

    with pytest.raises(RawRequestReconstructionError, match="four-table raw authority"):
        _reconstruct_packets(body, observation, occurrences[:-1], landings)
    duplicate_inventory = occurrences + (occurrences[0],)
    duplicate_observation = _rebuild_observation(observation, duplicate_inventory, landings)
    with pytest.raises(RawRequestReconstructionError, match="four-table raw authority"):
        _reconstruct_packets(body, duplicate_observation, duplicate_inventory, landings)
    with pytest.raises(
        RawRequestReconstructionError,
        match="four-table raw authority|ordinals are not exact",
    ):
        _reconstruct_packets(
            body,
            observation,
            (occurrences[1], occurrences[0], *occurrences[2:]),
            landings,
        )

    mutated_observation = observation.model_copy(update={"result_occurrences_sha256": _HASHES[103]})
    with pytest.raises(RawRequestReconstructionError, match="four-table raw authority"):
        _reconstruct_packets(body, mutated_observation, occurrences, landings)


def test_occurrence_inventory_rejects_logically_valid_extra_and_duplicate_packets() -> None:
    body, observation, occurrences, landings, _ = _live_case()
    route_ids = ("foreign_route",)
    extra = ResultOccurrenceV2.build(
        observation_sha256=observation.attempt.observation_sha256,
        occurrence_ordinal=len(occurrences),
        result_name="foreign_result",
        duplicate_name_ordinal=0,
        provider_result_ordinal=None,
        canonical_result_ordinal=len(occurrences),
        json_path="$.foreignResult",
        container_kind="nba_api_live_json_array",
        presence="empty_array",
        ordered_headers=(),
        row_count=0,
        cell_count=0,
        node_count=1,
        container_count=1,
        missing_count=0,
        null_count=0,
        parent_state_sha256=_parent_state_sha256("present"),
        output_sha256=_sha("foreign-output"),
        canonical_route_ids=route_ids,
        committed_staging_receipts=_receipt_payloads(route_ids),
        landing_disposition="lossless_only",
    )
    extra_occurrences = (*occurrences, extra)
    extra_observation = _rebuild_observation(observation, extra_occurrences, landings)
    with pytest.raises(RawRequestReconstructionError, match="four-table raw authority"):
        _reconstruct_packets(body, extra_observation, extra_occurrences, landings)

    duplicate = _rebuild_occurrence(
        extra,
        result_name=occurrences[-1].result_name,
        duplicate_name_ordinal=0,
    )
    duplicate_occurrences = (*occurrences, duplicate)
    duplicate_observation = _rebuild_observation(observation, duplicate_occurrences, landings)
    with pytest.raises(RawRequestReconstructionError, match="four-table raw authority"):
        _reconstruct_packets(body, duplicate_observation, duplicate_occurrences, landings)


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("occurrence_sha256", _HASHES[110]),
        ("occurrence_ordinal", 7),
        ("container_kind", "nba_api_live_json_array"),
        ("presence", "missing"),
    ],
)
def test_occurrence_revalidation_rejects_digest_ordinal_container_and_presence_mutations(
    field: str,
    value: object,
) -> None:
    body, observation, occurrences, landings = _stats_empty_case()
    mutated = occurrences[0].model_copy(update={field: value})

    with pytest.raises(RawRequestReconstructionError, match="four-table raw authority"):
        _reconstruct_packets(body, observation, (mutated,), landings)


def test_logically_rebuilt_ordinal_and_container_mutations_fail_closed() -> None:
    body, observation, occurrences, landings = _stats_empty_case()
    ordinal_gap = _rebuild_occurrence(occurrences[0], occurrence_ordinal=1)
    ordinal_observation = _rebuild_observation(observation, (ordinal_gap,), landings)
    with pytest.raises(RawRequestReconstructionError, match="four-table raw authority"):
        _reconstruct_packets(body, ordinal_observation, (ordinal_gap,), landings)

    foreign_container = _rebuild_occurrence(
        occurrences[0],
        json_path="$.LeagueGameLog",
        container_kind="nba_api_live_json_array",
        presence="empty_array",
        ordered_headers=[],
        node_count=1,
    )
    container_observation = _rebuild_observation(observation, (foreign_container,), landings)
    with pytest.raises(RawRequestReconstructionError, match="four-table raw authority"):
        _reconstruct_packets(body, container_observation, (foreign_container,), landings)


def test_live_parent_topology_rejects_invented_and_suppressed_parent_observations() -> None:
    body, observation, occurrences, landings, _ = _live_case()
    child = occurrences[3]
    invented = _rebuild_occurrence(
        child,
        presence="missing",
        ordered_headers=[],
        missing_count=1,
        parent_state_sha256=_parent_state_sha256(),
    )
    invented_occurrences = (*occurrences[:3], invented, *occurrences[4:])
    invented_observation = _rebuild_observation(observation, invented_occurrences, landings)
    with pytest.raises(RawRequestReconstructionError, match="four-table raw authority"):
        _reconstruct_packets(body, invented_observation, invented_occurrences, landings)

    games = occurrences[2]
    contract = pinned_live_contracts()["ScoreBoard"].result_sets[2]
    suppressed = _rebuild_occurrence(
        games,
        presence="not_observed_parent_empty",
        ordered_headers=[field.name for field in contract.fields],
        node_count=0,
        container_count=0,
        parent_state_sha256=_parent_state_sha256(),
    )
    suppressed_occurrences = (*occurrences[:2], suppressed, *occurrences[3:])
    suppressed_observation = _rebuild_observation(observation, suppressed_occurrences, landings)
    with pytest.raises(RawRequestReconstructionError, match="four-table raw authority"):
        _reconstruct_packets(body, suppressed_observation, suppressed_occurrences, landings)


def test_zero_parent_child_rejects_a_foreign_parent_state_digest() -> None:
    body, observation, occurrences, landings, _ = _live_case()
    child = _rebuild_occurrence(
        occurrences[3],
        parent_state_sha256=_parent_state_sha256("present"),
    )
    mutated_occurrences = (*occurrences[:3], child, *occurrences[4:])
    mutated_observation = _rebuild_observation(observation, mutated_occurrences, landings)

    with pytest.raises(RawRequestReconstructionError, match="four-table raw authority"):
        _reconstruct_packets(body, mutated_observation, mutated_occurrences, landings)


@pytest.mark.parametrize("mutation", ["missing", "reordered", "duplicate_digest"])
def test_committed_receipt_inventory_mutations_fail_closed(mutation: str) -> None:
    body, observation, occurrences, landings = _stats_empty_case()
    occurrence = occurrences[0]
    if mutation == "missing":
        changed = _rebuild_occurrence(occurrence, committed_staging_receipts=[])
    else:
        route_ids = ["stats_route_a", "stats_route_b"]
        receipts = _receipt_payloads(tuple(route_ids))
        if mutation == "reordered":
            receipts.reverse()
        else:
            receipts[1]["receipt_sha256"] = receipts[0]["receipt_sha256"]
        changed = _rebuild_occurrence(
            occurrence,
            canonical_route_ids=route_ids,
            committed_staging_receipts=receipts,
        )
    changed_observation = _rebuild_observation(observation, (changed,), landings)

    with pytest.raises(
        RawRequestReconstructionError,
        match="four-table raw authority",
    ):
        _reconstruct_packets(body, changed_observation, (changed,), landings)


def test_cross_observation_occurrence_authority_fails_closed() -> None:
    body, _, occurrences, landings, _ = _live_case()
    other_attempt = _attempt(retry_ordinal=1, request_ordinal=1)
    other_observation = _terminal_observation(
        other_attempt,
        body,
        occurrences,
        landings,
        outcome="success_nonempty",
    )

    with pytest.raises(RawRequestReconstructionError, match="four-table raw authority"):
        _reconstruct_packets(body, other_observation, occurrences, landings)


def test_four_table_closure_rejects_body_zero_rows_resealed_as_one_row() -> None:
    body, observation, occurrences, landings = _stats_empty_case()
    original = occurrences[0]
    forged_content = _sha("forged-one-row-content")
    forged_receipt = replace(
        _receipt_from_landing(landings[0]),
        content_hash=forged_content,
        persisted_row_count=1,
        persisted_content_sha256=forged_content,
        persisted_schema_sha256=_sha("forged-one-row-schema"),
    )
    forged_occurrence = _rebuild_occurrence(
        original,
        presence="present",
        row_count=1,
        cell_count=original.header_count,
        output_sha256=_sha("forged-one-row-output"),
        committed_staging_receipts=[_receipt_payload(forged_receipt)],
    )
    forged_landing = _rebuild_landing(
        landings[0],
        source_occurrence_sha256s=(forged_occurrence.occurrence_sha256,),
        committed_receipt=forged_receipt,
    )
    forged_observation = _rebuild_observation(
        observation,
        (forged_occurrence,),
        (forged_landing,),
    )

    with pytest.raises(RawRequestReconstructionError, match="four-table raw authority"):
        _reconstruct_raw(
            body,
            forged_observation,
            (forged_occurrence,),
            (forged_landing,),
        )


def test_four_table_closure_rejects_omitted_fixed_multi_route_landing() -> None:
    bundle = _strict_stats_bundle()
    assert len(bundle.landings) > 1
    omitted_landings = bundle.landings[:-1]
    resealed_observation = _rebuild_observation(
        bundle.observations[0],
        bundle.occurrences,
        omitted_landings,
    )

    with pytest.raises(RawRequestReconstructionError, match="four-table raw authority"):
        _reconstruct_raw(
            bundle.objects[0],
            resealed_observation,
            bundle.occurrences,
            omitted_landings,
        )


def test_four_table_closure_rejects_forged_video_zero_frame_hashes() -> None:
    body, observation, occurrences, landings = _video_fixed_zero_case()
    landing = landings[0]
    forged_receipt = replace(
        _receipt_from_landing(landing),
        content_hash=_sha("forged-video-empty-content"),
        persisted_content_sha256=_sha("forged-video-empty-content"),
        persisted_schema_sha256=_sha("forged-video-empty-schema"),
    )
    forged_landing = _rebuild_landing(
        landing,
        source_occurrence_sha256s=(),
        committed_receipt=forged_receipt,
    )
    forged_observation = _rebuild_observation(
        observation,
        occurrences,
        (forged_landing,),
    )

    with pytest.raises(RawRequestReconstructionError, match="four-table raw authority"):
        _reconstruct_raw(body, forged_observation, occurrences, (forged_landing,))


def test_live_reconstruction_requires_independent_exact_plan_receipt() -> None:
    body, observation, occurrences, landings, _ = _live_case()
    plan = _live_plan_authority(observation, landings)

    with pytest.raises(RawRequestReconstructionError, match="lacks its exact plan"):
        reconstruct_raw_request_authority(body, observation, occurrences, landings)
    with pytest.raises(RawRequestReconstructionError, match="independent sealed receipt"):
        reconstruct_raw_request_authority(
            body,
            observation,
            occurrences,
            landings,
            live_plan_authority=plan,
            expected_live_plan_authority_sha256=_HASHES[170],
        )


def test_live_reconstruction_rejects_resealed_future_landings_against_old_plan() -> None:
    body, observation, occurrences, landings, _ = _live_case()
    plan = _live_plan_authority(observation, landings)
    future = _STARTED_AT + timedelta(days=365)
    reconstructed = _reconstruct_raw(body, observation, occurrences, landings)
    shifted_landings = tuple(
        _rebuild_landing(
            landing,
            source_occurrence_sha256s=reconstructed_landing.source_occurrence_sha256s,
            live_snapshot_at=future,
        )
        for landing, reconstructed_landing in zip(
            landings,
            reconstructed.route_landings,
            strict=True,
        )
    )
    shifted_observation = _rebuild_observation(
        observation,
        occurrences,
        shifted_landings,
    )

    with pytest.raises(
        RawRequestReconstructionError,
        match="four-table raw authority|crosses its exact request or route inventory",
    ):
        reconstruct_raw_request_authority(
            body,
            shifted_observation,
            occurrences,
            shifted_landings,
            live_plan_authority=plan,
            expected_live_plan_authority_sha256=plan.authority_sha256,
        )


@pytest.mark.parametrize(
    "attempt_updates",
    [
        {"source_sha": "b" * 40},
        {"run_id": 202},
        {"lane_id": "foreign-lane"},
        {"semantic_request_sha256": _HASHES[174]},
    ],
)
def test_live_reconstruction_rejects_foreign_plan_request_identity(
    attempt_updates: dict[str, object],
) -> None:
    body, observation, occurrences, landings, _ = _live_case()
    foreign_plan = _foreign_live_plan_authority(
        observation,
        landings,
        **attempt_updates,
    )

    with pytest.raises(
        RawRequestReconstructionError,
        match="crosses its exact request or route inventory",
    ):
        reconstruct_raw_request_authority(
            body,
            observation,
            occurrences,
            landings,
            live_plan_authority=foreign_plan,
            expected_live_plan_authority_sha256=foreign_plan.authority_sha256,
        )


def test_reconstruction_validator_replays_nested_and_top_level_identity() -> None:
    body, observation, occurrences, landings, _ = _live_case()
    plan = _live_plan_authority(observation, landings)
    reconstruction = reconstruct_raw_request_authority(
        body,
        observation,
        occurrences,
        landings,
        live_plan_authority=plan,
        expected_live_plan_authority_sha256=plan.authority_sha256,
    )
    assert (
        validate_raw_request_reconstruction(
            reconstruction,
            body,
            observation,
            occurrences,
            landings,
            live_plan_authority=plan,
            expected_live_plan_authority_sha256=plan.authority_sha256,
        )
        == reconstruction
    )

    for forged in (
        replace(reconstruction, reconstruction_sha256=_HASHES[171]),
        replace(
            reconstruction,
            parser_input=replace(
                reconstruction.parser_input,
                parser_input_bytes=b'{"forged":true}',
            ),
        ),
        replace(
            reconstruction,
            result_packets=(
                replace(reconstruction.result_packets[0], packet_sha256=_HASHES[172]),
                *reconstruction.result_packets[1:],
            ),
        ),
        replace(
            reconstruction,
            route_landings=(
                replace(
                    reconstruction.route_landings[0],
                    reconstruction_sha256=_HASHES[173],
                ),
                *reconstruction.route_landings[1:],
            ),
        ),
    ):
        with pytest.raises(RawRequestReconstructionError, match="differs from exact"):
            validate_raw_request_reconstruction(
                forged,
                body,
                observation,
                occurrences,
                landings,
                live_plan_authority=plan,
                expected_live_plan_authority_sha256=plan.authority_sha256,
            )


def test_reconstruction_validator_accepts_large_exact_parser_input_without_amplification() -> None:
    bundle = _strict_stats_bundle()
    baseline = reconstruct_raw_request_authority(
        bundle.objects[0],
        bundle.observations[0],
        bundle.occurrences,
        bundle.landings,
    )
    assert baseline.parser_input.parser_input_bytes is not None
    exact_parser_input = baseline.parser_input.parser_input_bytes + (b" " * 8_390_000)
    large_body = ParserInputObjectV2.from_parser_input(exact_parser_input.decode("utf-8"))
    large_observation = _rebuild_observation(
        bundle.observations[0],
        bundle.occurrences,
        bundle.landings,
        body_object_sha256=large_body.object_sha256,
    )
    reconstruction = reconstruct_raw_request_authority(
        large_body,
        large_observation,
        bundle.occurrences,
        bundle.landings,
    )

    validated = validate_raw_request_reconstruction(
        reconstruction,
        large_body,
        large_observation,
        bundle.occurrences,
        bundle.landings,
    )

    assert validated.parser_input.parser_input_bytes == exact_parser_input


@pytest.mark.parametrize(
    "field_name",
    [
        "reconstruction_sha256",
        "parser_input",
        "result_packets",
        "route_landings",
        "live_plan_authority_sha256",
    ],
)
def test_reconstruction_validator_rejects_hostile_top_level_equality(
    field_name: str,
) -> None:
    body, observation, occurrences, landings, _ = _live_case()
    plan = _live_plan_authority(observation, landings)
    reconstruction = reconstruct_raw_request_authority(
        body,
        observation,
        occurrences,
        landings,
        live_plan_authority=plan,
        expected_live_plan_authority_sha256=plan.authority_sha256,
    )
    forged = replace(reconstruction, **{field_name: _AlwaysEqual()})

    with pytest.raises(
        RawRequestReconstructionError,
        match="non-exact reconstruction field value",
    ):
        validate_raw_request_reconstruction(
            forged,
            body,
            observation,
            occurrences,
            landings,
            live_plan_authority=plan,
            expected_live_plan_authority_sha256=plan.authority_sha256,
        )


def test_reconstruction_contract_is_explicit_v2_without_raw_v1_aliases() -> None:
    assert LiveSnapshotPlanAuthorityV2.schema_version == 2
    assert RawRequestReconstructionV2.schema_version == 2
    assert ReconstructedParserInputV2.schema_version == 2
    assert ReconstructedProviderResultPacketV2.schema_version == 2
    assert ReconstructedRouteLandingV2.schema_version == 2
    for name in (
        "LiveSnapshotPlanAuthorityV1",
        "RawRequestReconstructionV1",
        "ReconstructedParserInputV1",
        "ReconstructedProviderResultPacketV1",
        "ReconstructedRouteLandingV1",
    ):
        assert not hasattr(reconstruction_module, name)
