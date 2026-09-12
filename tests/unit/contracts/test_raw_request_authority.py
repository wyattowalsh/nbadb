from __future__ import annotations

import base64
import hashlib
import json
from copy import deepcopy
from datetime import UTC, datetime, timedelta
from typing import Any, cast

import polars as pl
import pytest
from pydantic import ValidationError

from nbadb.contracts import raw_request_authority
from nbadb.contracts.raw_request_authority import (
    BODYLESS_RESULT_OCCURRENCES_SHA256,
    BODYLESS_ROUTE_LANDINGS_SHA256,
    DETERMINISTIC_GZIP_CODEC,
    PUBLIC_PARSER_INPUT_REPRESENTATION,
    ObservationRouteLandingV2,
    ParserInputObjectV2,
    RawRequestAuthorityBundleV2,
    RawRequestAuthorityError,
    RequestAttemptIdentityV2,
    RequestObservationV2,
    ResultOccurrenceV2,
    canonical_semantic_parameters,
    decode_parser_input_object,
    validate_observation_route_landing,
    validate_parser_input_object,
    validate_raw_request_authority_bundle,
    validate_request_attempt_identity,
    validate_request_observation,
    validate_result_occurrence,
)
from nbadb.contracts.staging_route_contract import (
    admit_conditional_live_lossless_route,
    admit_conditional_lossless_route,
    staging_route_contract_bundle,
)
from nbadb.core.nba_api_provenance import expected_nba_api_provider_authority
from nbadb.core.nba_api_runtime_contract import (
    endpoint_contract_sha256,
    pinned_live_contracts,
    pinned_runtime_contracts,
)
from nbadb.extract.live_lossless import LIVE_LOSSLESS_STAGING_KEY
from nbadb.extract.nba_api_adapter import (
    rederive_raw_authority_result_sets,
    rederive_raw_authority_stats_fallback,
    rederive_raw_authority_stats_rows,
    rederive_raw_authority_stats_wide_rows,
    rederive_raw_authority_unknown_stats_response,
    rows_to_polars,
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

_HASHES = tuple(f"{value:064x}" for value in range(1, 80))
_SOURCE_SHA = "1" * 40
_STARTED_AT = datetime(2026, 8, 26, 12, 0, tzinfo=UTC)
_PROVIDER_AUTHORITY_SHA256 = cast(
    "str",
    expected_nba_api_provider_authority()["authority_sha256"],
)
_VIDEO_PARAMETERS = {
    "VideoDetails": {"team_id": 1, "player_id": 2, "season": "2024-25"},
    "VideoEvents": {"game_id": "0022400001", "game_event_id": 7},
}


def _sha(value: str | bytes) -> str:
    encoded = value if isinstance(value, bytes) else value.encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _parser_input(payload: object) -> bytes:
    return json.dumps(
        payload,
        allow_nan=False,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")


def _attempt(
    *,
    source_family: str = "live",
    endpoint_id: str = "ScoreBoard",
    parameters: dict[str, object] | None = None,
    provider_authority_sha256: str = _HASHES[2],
    endpoint_contract_sha256_value: str = _HASHES[3],
    provider_call_ordinal: int = 0,
    retry_ordinal: int = 0,
) -> RequestAttemptIdentityV2:
    return RequestAttemptIdentityV2.build(
        semantic_request_sha256=_sha(f"semantic:{provider_call_ordinal}"),
        logical_invocation_sha256=_sha(f"logical:{provider_call_ordinal}"),
        provider_call_role="primary",
        provider_call_ordinal=provider_call_ordinal,
        retry_ordinal=retry_ordinal,
        request_ordinal=retry_ordinal,
        source_family=source_family,  # type: ignore[arg-type]
        endpoint_id=endpoint_id,
        parameters={} if parameters is None else parameters,
        provider_authority_sha256=provider_authority_sha256,
        endpoint_contract_sha256=endpoint_contract_sha256_value,
        competition_id=None,
        competition_identity_sha256=None,
        scope_sha256=_sha(f"scope:{provider_call_ordinal}"),
        pagination_sha256=None,
        page_ordinal=None,
        source_sha=_SOURCE_SHA,
        run_id=101,
        run_attempt=1,
        chain_id="chain",
        lane_id="lane",
    )


def _receipt(
    *,
    route_id: str,
    staging_key: str,
    logical_receipt_sha256: str,
    provider_authority_sha256: str,
    logical_parameters_sha256: str,
    frame: pl.DataFrame | None = None,
    row_count: int | None = None,
    salt: str = "",
) -> CommittedStagingChunkReceiptV2:
    if frame is None:
        if row_count is None:
            raise AssertionError("test receipt requires a frame or row count")
        content_sha256 = _sha(f"content:{route_id}:{salt}")
        schema_sha256 = _sha(f"schema:{route_id}:{salt}")
        persisted_row_count = row_count
    else:
        content_sha256 = frame_content_hash(frame)
        schema_sha256 = frame_schema_hash(frame)
        persisted_row_count = frame.height
    return CommittedStagingChunkReceiptV2(
        chunk_id=f"chunk:{route_id}:{salt or 'base'}",
        staging_key=staging_key,
        canonical_frame_format=CANONICAL_FRAME_FORMAT,
        frame_content_hash_contract=FRAME_CONTENT_HASH_CONTRACT,
        frame_schema_hash_contract=FRAME_SCHEMA_HASH_CONTRACT,
        content_hash=content_sha256,
        persisted_row_count=persisted_row_count,
        persisted_content_sha256=content_sha256,
        persisted_schema_sha256=schema_sha256,
        logical_call_receipt_sha256=logical_receipt_sha256,
        provider_authority_sha256=provider_authority_sha256,
        logical_parameters_sha256=logical_parameters_sha256,
        result_route_id=route_id,
    )


def _mutated_payload(model: Any, **updates: object) -> dict[str, object]:
    payload = model.model_dump(mode="python", round_trip=True)
    payload.update(updates)
    return payload


def _video_bundle(
    endpoint_id: str,
    payload: object,
) -> tuple[
    RawRequestAuthorityBundleV2,
    RequestObservationV2,
    tuple[ResultOccurrenceV2, ...],
    tuple[ObservationRouteLandingV2, ...],
]:
    parser_input = _parser_input(payload)
    contract = pinned_runtime_contracts()[endpoint_id]
    attempt = _attempt(
        source_family="stats",
        endpoint_id=endpoint_id,
        parameters=_VIDEO_PARAMETERS[endpoint_id],
        provider_authority_sha256=_PROVIDER_AUTHORITY_SHA256,
        endpoint_contract_sha256_value=endpoint_contract_sha256(contract),
    )
    body = ParserInputObjectV2.from_parser_input(parser_input.decode("utf-8"))
    unknown = rederive_raw_authority_unknown_stats_response(
        endpoint_id=endpoint_id,
        parser_input=parser_input,
        safe_parameters_json=attempt.safe_parameters_json,
        provider_authority_sha256=attempt.provider_authority_sha256,
        endpoint_contract_sha256_value=attempt.endpoint_contract_sha256,
    )
    fixed_routes = tuple(
        route
        for route in staging_route_contract_bundle().routes
        if route.source_family == "stats"
        and route.provider_endpoint_id == endpoint_id
        and route.endpoint_contract_sha256 == attempt.endpoint_contract_sha256
    )
    assert len(fixed_routes) == 1
    fixed_route = fixed_routes[0]
    conditional_route_id = (
        f"{fixed_route.endpoint_name}:{LOSSLESS_FALLBACK_STAGING_KEY}:{len(contract.result_sets)}"
    )
    conditional_admission = admit_conditional_lossless_route(
        endpoint_name=fixed_route.endpoint_name,
        static_route_ids=(fixed_route.route_id,),
        conditional_route_ids=(conditional_route_id,),
        provider_authority_sha256=attempt.provider_authority_sha256,
    )
    capture_receipt_sha256 = _sha(f"capture:{endpoint_id}:{parser_input!r}")
    logical_receipt_sha256 = _sha(f"logical-receipt:{endpoint_id}")
    fallback = build_unknown_stats_lossless_fallback(
        unknown.bind_response_receipt(capture_receipt_sha256),
        expected_response_receipt_sha256=capture_receipt_sha256,
        expected_parameters_sha256=unknown.parameters_sha256,
        expected_parser_input_sha256=unknown.parser_input_sha256,
    )

    conditional_receipt = None
    if fallback is not None:
        conditional_receipt = _receipt(
            route_id=conditional_route_id,
            staging_key=conditional_admission.staging_key,
            logical_receipt_sha256=logical_receipt_sha256,
            provider_authority_sha256=attempt.provider_authority_sha256,
            logical_parameters_sha256=attempt.safe_parameters_sha256,
            frame=fallback.frame,
        )
    alias_policy = fixed_route.storage_columns == conditional_admission.storage_columns
    fixed_frame = fallback.frame if fallback is not None and alias_policy else pl.DataFrame()
    fixed_receipt = _receipt(
        route_id=fixed_route.route_id,
        staging_key=fixed_route.staging_key,
        logical_receipt_sha256=logical_receipt_sha256,
        provider_authority_sha256=attempt.provider_authority_sha256,
        logical_parameters_sha256=attempt.safe_parameters_sha256,
        frame=fixed_frame,
    )

    occurrences: list[ResultOccurrenceV2] = []
    duplicate_names: dict[str, int] = {}
    for occurrence_ordinal, item in enumerate(unknown.occurrences):
        duplicate_ordinal = duplicate_names.get(item.name, 0)
        duplicate_names[item.name] = duplicate_ordinal + 1
        assert conditional_receipt is not None
        occurrences.append(
            ResultOccurrenceV2.build(
                observation_sha256=attempt.observation_sha256,
                occurrence_ordinal=occurrence_ordinal,
                result_name=item.name,
                duplicate_name_ordinal=duplicate_ordinal,
                provider_result_ordinal=item.provider_index,
                canonical_result_ordinal=None,
                json_path=None,
                container_kind="nba_api_result_set",
                presence="present" if item.receipt.row_count else "present_empty",
                ordered_headers=item.headers,
                row_count=item.receipt.row_count,
                cell_count=item.receipt.row_count * len(item.headers),
                node_count=0,
                container_count=1,
                missing_count=0,
                null_count=0,
                parent_state_sha256=item.receipt.parent_occurrence_states_sha256,
                output_sha256=item.receipt.normalized_output_sha256,
                canonical_route_ids=[conditional_route_id],
                committed_staging_receipts=[
                    {
                        "route_id": conditional_route_id,
                        "receipt_sha256": conditional_receipt.receipt_root_sha256,
                    }
                ],
                landing_disposition="lossless_only",
            )
        )

    fixed_landing = ObservationRouteLandingV2.build(
        observation_sha256=attempt.observation_sha256,
        logical_receipt_sha256=logical_receipt_sha256,
        route_ordinal=0,
        route_authority_kind="staging_route_contract_v1",
        route_authority_sha256=fixed_route.contract_sha256,
        landing_semantic=(
            "response_canonical_alias"
            if fallback is not None and alias_policy
            else "response_fixed_zero"
        ),
        conditional_lossless=False,
        alias_target_route_id=(
            conditional_route_id if fallback is not None and alias_policy else None
        ),
        live_snapshot_at=None,
        source_occurrence_sha256s=(),
        committed_receipt=fixed_receipt,
    )
    landings = [fixed_landing]
    if conditional_receipt is not None:
        landings.append(
            ObservationRouteLandingV2.build(
                observation_sha256=attempt.observation_sha256,
                logical_receipt_sha256=logical_receipt_sha256,
                route_ordinal=1,
                route_authority_kind="conditional_staging_route_admission_v1",
                route_authority_sha256=conditional_admission.contract_sha256,
                landing_semantic="conditional_lossless",
                conditional_lossless=True,
                alias_target_route_id=None,
                live_snapshot_at=None,
                source_occurrence_sha256s=[item.occurrence_sha256 for item in occurrences],
                committed_receipt=conditional_receipt,
            )
        )
    observation = RequestObservationV2.build(
        attempt=attempt,
        transport={
            "transport_kind": "stats_http",
            "status_code": 200,
            "effective_status_code": 200,
        },
        started_at=_STARTED_AT,
        finished_at=_STARTED_AT + timedelta(seconds=1),
        elapsed_ns=1_000_000_000,
        lifecycle="selected_terminal",
        outcome=unknown.outcome,
        failure_class=None,
        root_exception_class=None,
        body_disposition="public_parser_input",
        body_object_sha256=body.object_sha256,
        bodyless_evidence_sha256=None,
        result_occurrence_sha256s=[item.occurrence_sha256 for item in occurrences],
        route_landing_sha256s=[item.landing_sha256 for item in landings],
        capture_response_receipt_sha256=capture_receipt_sha256,
        logical_receipt_sha256=logical_receipt_sha256,
    )
    bundle = RawRequestAuthorityBundleV2.build(
        objects=[body],
        observations=[observation],
        occurrences=occurrences,
        landings=landings,
    )
    return bundle, observation, tuple(occurrences), tuple(landings)


def _static_bundle(
    *,
    tamper_occurrence: bool = False,
    live_snapshot_at: datetime | None = None,
) -> tuple[
    RawRequestAuthorityBundleV2,
    RequestObservationV2,
    ResultOccurrenceV2,
    ObservationRouteLandingV2,
]:
    route = next(
        route
        for route in staging_route_contract_bundle().routes
        if route.endpoint_name == "static_players"
    )
    attempt = _attempt(
        source_family="static",
        endpoint_id=route.provider_endpoint_id,
        parameters={},
        provider_authority_sha256=route.provider_authority_sha256,
        endpoint_contract_sha256_value=route.endpoint_contract_sha256,
    )
    logical_receipt_sha256 = _sha("static-logical-receipt")
    derivations = rederive_raw_authority_result_sets(
        source_family="static",
        endpoint_id=attempt.endpoint_id,
        parser_input=None,
        provider_authority_sha256=attempt.provider_authority_sha256,
        endpoint_contract_sha256_value=attempt.endpoint_contract_sha256,
    )
    assert len(derivations) == 1
    derivation = derivations[0]
    result_receipt = derivation.result_set
    receipt = _receipt(
        route_id=route.route_id,
        staging_key=route.staging_key,
        logical_receipt_sha256=logical_receipt_sha256,
        provider_authority_sha256=attempt.provider_authority_sha256,
        logical_parameters_sha256=attempt.safe_parameters_sha256,
        row_count=result_receipt.row_count,
    )
    headers = derivation.ordered_headers
    occurrence = ResultOccurrenceV2.build(
        observation_sha256=attempt.observation_sha256,
        occurrence_ordinal=0,
        result_name=result_receipt.name,
        duplicate_name_ordinal=derivation.duplicate_name_ordinal,
        provider_result_ordinal=result_receipt.provider_index,
        canonical_result_ordinal=result_receipt.canonical_index,
        json_path="$",
        container_kind="nba_api_static_records",
        presence="present",
        ordered_headers=headers,
        row_count=result_receipt.row_count,
        cell_count=result_receipt.row_count * len(headers),
        node_count=result_receipt.row_count,
        container_count=result_receipt.container_count,
        missing_count=result_receipt.missing_count,
        null_count=result_receipt.null_count,
        parent_state_sha256=result_receipt.parent_occurrence_states_sha256,
        output_sha256=(
            _sha("forged-static-occurrence")
            if tamper_occurrence
            else result_receipt.normalized_output_sha256
        ),
        canonical_route_ids=[route.route_id],
        committed_staging_receipts=[
            {"route_id": route.route_id, "receipt_sha256": receipt.receipt_root_sha256}
        ],
        landing_disposition="wide_only",
    )
    landing = ObservationRouteLandingV2.build(
        observation_sha256=attempt.observation_sha256,
        logical_receipt_sha256=logical_receipt_sha256,
        route_ordinal=0,
        route_authority_kind="staging_route_contract_v1",
        route_authority_sha256=route.contract_sha256,
        landing_semantic="occurrence_bound",
        conditional_lossless=False,
        alias_target_route_id=None,
        live_snapshot_at=live_snapshot_at,
        source_occurrence_sha256s=[occurrence.occurrence_sha256],
        committed_receipt=receipt,
    )
    observation = RequestObservationV2.build(
        attempt=attempt,
        transport={"transport_kind": "static_snapshot"},
        started_at=_STARTED_AT,
        finished_at=_STARTED_AT + timedelta(microseconds=1),
        elapsed_ns=1_000,
        lifecycle="selected_terminal",
        outcome="static_snapshot_success",
        failure_class=None,
        root_exception_class=None,
        body_disposition="declared_bodyless",
        body_object_sha256=None,
        bodyless_evidence_sha256=_sha("static-snapshot"),
        result_occurrence_sha256s=[occurrence.occurrence_sha256],
        route_landing_sha256s=[landing.landing_sha256],
        capture_response_receipt_sha256=_sha("static-capture"),
        logical_receipt_sha256=logical_receipt_sha256,
    )
    bundle = RawRequestAuthorityBundleV2.build(
        objects=[],
        observations=[observation],
        occurrences=[occurrence],
        landings=[landing],
    )
    return bundle, observation, occurrence, landing


def _sample_live_value(sample_types: tuple[str, ...]) -> object:
    preferred = next((item for item in sample_types if item != "null"), "null")
    return {
        "array": [],
        "boolean": True,
        "integer": 1,
        "null": None,
        "number": 1.25,
        "object": {},
        "string": "fixture",
    }[preferred]


def _complete_live_result_container(result: Any, contract: Any) -> object:
    children = {
        child.parent_field_name: child
        for child in contract.result_sets
        if child.parent_result_set_name == result.name
    }
    scalar_projection = (
        len(result.fields) == 1
        and not result.fields[0].source_field
        and result.fields[0].name == "value"
    )
    if scalar_projection:
        record: object = _sample_live_value(result.fields[0].sample_types)
    else:
        record = {
            field.name: (
                _complete_live_result_container(children[field.name], contract)
                if field.name in children
                else _sample_live_value(field.sample_types)
            )
            for field in result.fields
        }
    return [record] if result.container_kind == "nba_api_live_json_array" else record


def _complete_live_payload(endpoint_id: str) -> dict[str, object]:
    contract = pinned_live_contracts()[endpoint_id]
    roots = {
        result.traversal_path[0]: result
        for result in contract.result_sets
        if result.parent_result_set_name is None
    }
    return {
        root_name: _complete_live_result_container(roots[root_name], contract)
        for root_name in contract.envelope_root_order
    }


def _live_occurrence_reseal_bundle(
    *,
    tamper_occurrence: bool = True,
    fixed_snapshot_at: datetime | None = _STARTED_AT,
    conditional_snapshot_at: datetime | None = _STARTED_AT,
) -> RawRequestAuthorityBundleV2:
    route = next(
        route
        for route in staging_route_contract_bundle().routes
        if route.endpoint_name == "live_odds"
    )
    contract = pinned_live_contracts()[route.provider_endpoint_id]
    attempt = _attempt(
        source_family="live",
        endpoint_id=route.provider_endpoint_id,
        parameters={},
        provider_authority_sha256=route.provider_authority_sha256,
        endpoint_contract_sha256_value=route.endpoint_contract_sha256,
    )
    parser_input = _parser_input(_complete_live_payload(route.provider_endpoint_id))
    body = ParserInputObjectV2.from_parser_input(parser_input.decode("utf-8"))
    derivations = rederive_raw_authority_result_sets(
        source_family="live",
        endpoint_id=attempt.endpoint_id,
        parser_input=parser_input,
        provider_authority_sha256=attempt.provider_authority_sha256,
        endpoint_contract_sha256_value=attempt.endpoint_contract_sha256,
    )
    logical_receipt_sha256 = _sha("logical:live-odds")
    fixed_receipt = _receipt(
        route_id=route.route_id,
        staging_key=route.staging_key,
        logical_receipt_sha256=logical_receipt_sha256,
        provider_authority_sha256=attempt.provider_authority_sha256,
        logical_parameters_sha256=attempt.safe_parameters_sha256,
        row_count=derivations[0].result_set.row_count,
    )
    conditional_route_id = (
        f"{route.endpoint_name}:{LIVE_LOSSLESS_STAGING_KEY}:{len(contract.result_sets)}"
    )
    conditional_admission = admit_conditional_live_lossless_route(
        endpoint_name=route.endpoint_name,
        static_route_ids=(route.route_id,),
        conditional_route_ids=(conditional_route_id,),
        provider_authority_sha256=attempt.provider_authority_sha256,
    )
    conditional_receipt = _receipt(
        route_id=conditional_route_id,
        staging_key=conditional_admission.staging_key,
        logical_receipt_sha256=logical_receipt_sha256,
        provider_authority_sha256=attempt.provider_authority_sha256,
        logical_parameters_sha256=attempt.safe_parameters_sha256,
        row_count=1,
    )
    occurrences: list[ResultOccurrenceV2] = []
    for occurrence_ordinal, derivation in enumerate(derivations):
        result = derivation.result_set
        route_ids = tuple(
            sorted(
                (
                    *((route.route_id,) if result.canonical_index == 0 else ()),
                    conditional_route_id,
                )
            )
        )
        receipt_by_route = {
            route.route_id: fixed_receipt,
            conditional_route_id: conditional_receipt,
        }
        occurrences.append(
            ResultOccurrenceV2.build(
                observation_sha256=attempt.observation_sha256,
                occurrence_ordinal=occurrence_ordinal,
                result_name=result.name,
                duplicate_name_ordinal=derivation.duplicate_name_ordinal,
                provider_result_ordinal=result.provider_index,
                canonical_result_ordinal=result.canonical_index,
                json_path=result.json_path,
                container_kind=result.container_kind,  # type: ignore[arg-type]
                presence="present",
                ordered_headers=derivation.ordered_headers,
                row_count=result.row_count,
                cell_count=result.row_count * len(derivation.ordered_headers),
                node_count=result.row_count,
                container_count=result.container_count + result.null_count,
                missing_count=result.missing_count,
                null_count=result.null_count,
                parent_state_sha256=result.parent_occurrence_states_sha256,
                output_sha256=(
                    _sha("forged-live-occurrence")
                    if tamper_occurrence and occurrence_ordinal == 0
                    else result.normalized_output_sha256
                ),
                canonical_route_ids=route_ids,
                committed_staging_receipts=[
                    {
                        "route_id": route_id,
                        "receipt_sha256": receipt_by_route[route_id].receipt_root_sha256,
                    }
                    for route_id in route_ids
                ],
                landing_disposition=(
                    "wide_plus_lossless" if route.route_id in route_ids else "lossless_only"
                ),
            )
        )
    landings = (
        ObservationRouteLandingV2.build(
            observation_sha256=attempt.observation_sha256,
            logical_receipt_sha256=logical_receipt_sha256,
            route_ordinal=0,
            route_authority_kind="staging_route_contract_v1",
            route_authority_sha256=route.contract_sha256,
            landing_semantic="occurrence_bound",
            conditional_lossless=False,
            alias_target_route_id=None,
            live_snapshot_at=fixed_snapshot_at,
            source_occurrence_sha256s=[occurrences[0].occurrence_sha256],
            committed_receipt=fixed_receipt,
        ),
        ObservationRouteLandingV2.build(
            observation_sha256=attempt.observation_sha256,
            logical_receipt_sha256=logical_receipt_sha256,
            route_ordinal=1,
            route_authority_kind="conditional_staging_route_admission_v1",
            route_authority_sha256=conditional_admission.contract_sha256,
            landing_semantic="conditional_lossless",
            conditional_lossless=True,
            alias_target_route_id=None,
            live_snapshot_at=conditional_snapshot_at,
            source_occurrence_sha256s=[item.occurrence_sha256 for item in occurrences],
            committed_receipt=conditional_receipt,
        ),
    )
    observation = RequestObservationV2.build(
        attempt=attempt,
        transport={
            "transport_kind": "live_http",
            "status_code": 200,
            "effective_status_code": 200,
        },
        started_at=_STARTED_AT,
        finished_at=_STARTED_AT + timedelta(seconds=1),
        elapsed_ns=1_000_000_000,
        lifecycle="selected_terminal",
        outcome="success_nonempty",
        failure_class=None,
        root_exception_class=None,
        body_disposition="public_parser_input",
        body_object_sha256=body.object_sha256,
        bodyless_evidence_sha256=None,
        result_occurrence_sha256s=[item.occurrence_sha256 for item in occurrences],
        route_landing_sha256s=[item.landing_sha256 for item in landings],
        capture_response_receipt_sha256=_sha("capture:live-odds"),
        logical_receipt_sha256=logical_receipt_sha256,
    )
    return RawRequestAuthorityBundleV2.build(
        objects=[body],
        observations=[observation],
        occurrences=occurrences,
        landings=landings,
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
    if variant == "strict":
        pass
    elif variant == "header_drift":
        headers = result_sets[0]["headers"]
        rows = result_sets[0]["rowSet"]
        assert isinstance(headers, list) and isinstance(rows, list)
        headers.append("ADDITIVE")
        first_row = rows[0]
        assert isinstance(first_row, list)
        first_row.append(None)
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


def _stats_wide_frame(route: Any, result_rows: Any) -> pl.DataFrame:
    values = tuple(
        tuple(json.loads(cell.canonical_json) for cell in row) for row in result_rows.rows
    )
    frame = rows_to_polars(result_rows.ordered_headers, values).rename(
        {mapping.provider_column: mapping.canonical_column for mapping in route.column_mappings}
    )
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
    validated = schema_cls.validate(frame)
    assert isinstance(validated, pl.DataFrame)
    return validated


def _stats_fallback_bundle(
    variant: str,
    *,
    tamper_fixed_frame: bool = False,
    tamper_conditional_frame: bool = False,
    tamper_occurrence: bool = False,
) -> tuple[
    RawRequestAuthorityBundleV2,
    RequestObservationV2,
    tuple[ResultOccurrenceV2, ...],
    tuple[ObservationRouteLandingV2, ...],
]:
    routes = tuple(
        sorted(
            (
                route
                for route in staging_route_contract_bundle().routes
                if route.endpoint_name == "franchise_history"
            ),
            key=lambda route: route.ordinal,
        )
    )
    assert routes and all(route.source_family == "stats" for route in routes)
    endpoint_id = routes[0].provider_endpoint_id
    contract = pinned_runtime_contracts()[endpoint_id]
    attempt = _attempt(
        source_family="stats",
        endpoint_id=endpoint_id,
        parameters={},
        provider_authority_sha256=routes[0].provider_authority_sha256,
        endpoint_contract_sha256_value=routes[0].endpoint_contract_sha256,
    )
    parser_input = _parser_input(_franchise_history_fallback_payload(variant))
    body = ParserInputObjectV2.from_parser_input(parser_input.decode("utf-8"))
    derivations = rederive_raw_authority_result_sets(
        source_family="stats",
        endpoint_id=endpoint_id,
        parser_input=parser_input,
        provider_authority_sha256=attempt.provider_authority_sha256,
        endpoint_contract_sha256_value=attempt.endpoint_contract_sha256,
    )
    safe_rows = rederive_raw_authority_stats_wide_rows(
        endpoint_id=endpoint_id,
        parser_input=parser_input,
        provider_authority_sha256=attempt.provider_authority_sha256,
        endpoint_contract_sha256_value=attempt.endpoint_contract_sha256,
    )
    capture_receipt_sha256 = _sha(f"capture:franchise-history:{variant}")
    logical_receipt_sha256 = _sha(f"logical:franchise-history:{variant}")
    fallback = rederive_raw_authority_stats_fallback(
        endpoint_id=endpoint_id,
        parser_input=parser_input,
        provider_authority_sha256=attempt.provider_authority_sha256,
        endpoint_contract_sha256_value=attempt.endpoint_contract_sha256,
    ).bind_response_receipt(capture_receipt_sha256)
    fixed_route_ids = tuple(route.route_id for route in routes)
    conditional_route_id = (
        f"franchise_history:{LOSSLESS_FALLBACK_STAGING_KEY}:{len(contract.result_sets)}"
    )
    conditional_admission = admit_conditional_lossless_route(
        endpoint_name="franchise_history",
        static_route_ids=fixed_route_ids,
        conditional_route_ids=(conditional_route_id,),
        provider_authority_sha256=attempt.provider_authority_sha256,
    )

    safe_by_canonical = {item.result_set.canonical_index: item for item in safe_rows}
    fixed_receipts: dict[str, CommittedStagingChunkReceiptV2] = {}
    for route_index, route in enumerate(routes):
        safe = safe_by_canonical.get(route.canonical_result_set_ordinal)
        frame = pl.DataFrame() if safe is None else _stats_wide_frame(route, safe)
        if tamper_fixed_frame and route_index == 0:
            frame = (
                pl.DataFrame(schema={"foreign": pl.Int64})
                if frame.height == 0
                else pl.DataFrame({"foreign": list(range(frame.height))})
            )
        fixed_receipts[route.route_id] = _receipt(
            route_id=route.route_id,
            staging_key=route.staging_key,
            logical_receipt_sha256=logical_receipt_sha256,
            provider_authority_sha256=attempt.provider_authority_sha256,
            logical_parameters_sha256=attempt.safe_parameters_sha256,
            frame=frame,
        )
    conditional_frame = fallback.frame
    if tamper_conditional_frame:
        conditional_frame = pl.DataFrame({"foreign": list(range(conditional_frame.height))})
    conditional_receipt = _receipt(
        route_id=conditional_route_id,
        staging_key=conditional_admission.staging_key,
        logical_receipt_sha256=logical_receipt_sha256,
        provider_authority_sha256=attempt.provider_authority_sha256,
        logical_parameters_sha256=attempt.safe_parameters_sha256,
        frame=conditional_frame,
    )

    declared_routes_by_result: dict[int, list[str]] = {
        index: [] for index in range(len(derivations))
    }
    wide_routes_by_result: dict[int, list[str]] = {index: [] for index in range(len(derivations))}
    for route in routes:
        expected = contract.result_sets[route.canonical_result_set_ordinal]
        expected_duplicate = sum(
            prior.result_set_name == expected.result_set_name
            for prior in contract.result_sets[: route.canonical_result_set_ordinal]
        )
        declared_index = next(
            index
            for index, derivation in enumerate(derivations)
            if derivation.result_set.name == expected.result_set_name
            and derivation.duplicate_name_ordinal == expected_duplicate
        )
        declared_routes_by_result[declared_index].append(route.route_id)
        safe = safe_by_canonical.get(route.canonical_result_set_ordinal)
        if safe is not None:
            wide_index = next(
                index
                for index, derivation in enumerate(derivations)
                if derivation.result_set.name == safe.result_set.name
                and derivation.result_set.provider_index == safe.result_set.provider_index
                and derivation.ordered_headers == safe.ordered_headers
            )
            assert wide_index == declared_index
            wide_routes_by_result[declared_index].append(route.route_id)

    occurrences: list[ResultOccurrenceV2] = []
    for occurrence_ordinal, derivation in enumerate(derivations):
        result = derivation.result_set
        route_ids = tuple(
            sorted((*declared_routes_by_result[occurrence_ordinal], conditional_route_id))
        )
        route_receipts = {
            **fixed_receipts,
            conditional_route_id: conditional_receipt,
        }
        committed = [
            {
                "route_id": route_id,
                "receipt_sha256": route_receipts[route_id].receipt_root_sha256,
            }
            for route_id in route_ids
        ]
        if result.container_count == 0:
            presence = "missing"
            headers: tuple[str, ...] = ()
            row_count = cell_count = node_count = container_count = null_count = 0
            missing_count = result.missing_count
        else:
            presence = "present" if result.row_count else "present_empty"
            headers = derivation.ordered_headers
            row_count = result.row_count
            cell_count = row_count * len(headers)
            node_count = 0
            container_count = result.container_count + result.null_count
            missing_count = result.missing_count
            null_count = result.null_count
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
                presence=presence,  # type: ignore[arg-type]
                ordered_headers=headers,
                row_count=row_count,
                cell_count=cell_count,
                node_count=node_count,
                container_count=container_count,
                missing_count=missing_count,
                null_count=null_count,
                parent_state_sha256=result.parent_occurrence_states_sha256,
                output_sha256=(
                    _sha("forged-stats-occurrence")
                    if tamper_occurrence and occurrence_ordinal == 0
                    else result.normalized_output_sha256
                ),
                canonical_route_ids=route_ids,
                committed_staging_receipts=committed,
                landing_disposition=(
                    "wide_plus_lossless"
                    if wide_routes_by_result[occurrence_ordinal]
                    else "lossless_only"
                ),
            )
        )

    landings: list[ObservationRouteLandingV2] = []
    for route_ordinal, route in enumerate(routes):
        sources = tuple(
            item for item in occurrences if route.route_id in item.canonical_route_ids()
        )
        landings.append(
            ObservationRouteLandingV2.build(
                observation_sha256=attempt.observation_sha256,
                logical_receipt_sha256=logical_receipt_sha256,
                route_ordinal=route_ordinal,
                route_authority_kind="staging_route_contract_v1",
                route_authority_sha256=route.contract_sha256,
                landing_semantic="occurrence_bound",
                conditional_lossless=False,
                alias_target_route_id=None,
                live_snapshot_at=None,
                source_occurrence_sha256s=[item.occurrence_sha256 for item in sources],
                committed_receipt=fixed_receipts[route.route_id],
            )
        )
    landings.append(
        ObservationRouteLandingV2.build(
            observation_sha256=attempt.observation_sha256,
            logical_receipt_sha256=logical_receipt_sha256,
            route_ordinal=len(routes),
            route_authority_kind="conditional_staging_route_admission_v1",
            route_authority_sha256=conditional_admission.contract_sha256,
            landing_semantic="conditional_lossless",
            conditional_lossless=True,
            alias_target_route_id=None,
            live_snapshot_at=None,
            source_occurrence_sha256s=[item.occurrence_sha256 for item in occurrences],
            committed_receipt=conditional_receipt,
        )
    )
    observation = RequestObservationV2.build(
        attempt=attempt,
        transport={
            "transport_kind": "stats_http",
            "status_code": 200,
            "effective_status_code": 200,
        },
        started_at=_STARTED_AT,
        finished_at=_STARTED_AT + timedelta(seconds=1),
        elapsed_ns=1_000_000_000,
        lifecycle="selected_terminal",
        outcome="success_nonempty",
        failure_class=None,
        root_exception_class=None,
        body_disposition="public_parser_input",
        body_object_sha256=body.object_sha256,
        bodyless_evidence_sha256=None,
        result_occurrence_sha256s=[item.occurrence_sha256 for item in occurrences],
        route_landing_sha256s=[item.landing_sha256 for item in landings],
        capture_response_receipt_sha256=capture_receipt_sha256,
        logical_receipt_sha256=logical_receipt_sha256,
    )
    bundle = RawRequestAuthorityBundleV2.build(
        objects=[body],
        observations=[observation],
        occurrences=occurrences,
        landings=landings,
    )
    return bundle, observation, tuple(occurrences), tuple(landings)


def _strict_stats_bundle(
    *,
    tamper_fixed_frame: bool = False,
) -> RawRequestAuthorityBundleV2:
    routes = tuple(
        sorted(
            (
                route
                for route in staging_route_contract_bundle().routes
                if route.endpoint_name == "franchise_history"
            ),
            key=lambda route: route.ordinal,
        )
    )
    attempt = _attempt(
        source_family="stats",
        endpoint_id=routes[0].provider_endpoint_id,
        parameters={},
        provider_authority_sha256=routes[0].provider_authority_sha256,
        endpoint_contract_sha256_value=routes[0].endpoint_contract_sha256,
    )
    parser_input = _parser_input(_franchise_history_fallback_payload("strict"))
    body = ParserInputObjectV2.from_parser_input(parser_input.decode("utf-8"))
    derivations = rederive_raw_authority_result_sets(
        source_family="stats",
        endpoint_id=attempt.endpoint_id,
        parser_input=parser_input,
        provider_authority_sha256=attempt.provider_authority_sha256,
        endpoint_contract_sha256_value=attempt.endpoint_contract_sha256,
    )
    strict_rows = rederive_raw_authority_stats_rows(
        endpoint_id=attempt.endpoint_id,
        parser_input=parser_input,
        provider_authority_sha256=attempt.provider_authority_sha256,
        endpoint_contract_sha256_value=attempt.endpoint_contract_sha256,
    )
    logical_receipt_sha256 = _sha("logical:franchise-history:strict")
    receipts: dict[str, CommittedStagingChunkReceiptV2] = {}
    for route_index, route in enumerate(routes):
        rows = next(
            item
            for item in strict_rows
            if item.result_set.canonical_index == route.canonical_result_set_ordinal
        )
        frame = _stats_wide_frame(route, rows)
        if tamper_fixed_frame and route_index == 0:
            frame = pl.DataFrame({"foreign": list(range(frame.height))})
        receipts[route.route_id] = _receipt(
            route_id=route.route_id,
            staging_key=route.staging_key,
            logical_receipt_sha256=logical_receipt_sha256,
            provider_authority_sha256=attempt.provider_authority_sha256,
            logical_parameters_sha256=attempt.safe_parameters_sha256,
            frame=frame,
        )

    occurrences: list[ResultOccurrenceV2] = []
    landings: list[ObservationRouteLandingV2] = []
    for route_ordinal, route in enumerate(routes):
        derivation = next(
            item
            for item in derivations
            if item.result_set.canonical_index == route.canonical_result_set_ordinal
        )
        result = derivation.result_set
        occurrence = ResultOccurrenceV2.build(
            observation_sha256=attempt.observation_sha256,
            occurrence_ordinal=route_ordinal,
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
            canonical_route_ids=[route.route_id],
            committed_staging_receipts=[
                {
                    "route_id": route.route_id,
                    "receipt_sha256": receipts[route.route_id].receipt_root_sha256,
                }
            ],
            landing_disposition="wide_only",
        )
        occurrences.append(occurrence)
        landings.append(
            ObservationRouteLandingV2.build(
                observation_sha256=attempt.observation_sha256,
                logical_receipt_sha256=logical_receipt_sha256,
                route_ordinal=route_ordinal,
                route_authority_kind="staging_route_contract_v1",
                route_authority_sha256=route.contract_sha256,
                landing_semantic="occurrence_bound",
                conditional_lossless=False,
                alias_target_route_id=None,
                live_snapshot_at=None,
                source_occurrence_sha256s=[occurrence.occurrence_sha256],
                committed_receipt=receipts[route.route_id],
            )
        )
    observation = RequestObservationV2.build(
        attempt=attempt,
        transport={
            "transport_kind": "stats_http",
            "status_code": 200,
            "effective_status_code": 200,
        },
        started_at=_STARTED_AT,
        finished_at=_STARTED_AT + timedelta(seconds=1),
        elapsed_ns=1_000_000_000,
        lifecycle="selected_terminal",
        outcome="success_nonempty",
        failure_class=None,
        root_exception_class=None,
        body_disposition="public_parser_input",
        body_object_sha256=body.object_sha256,
        bodyless_evidence_sha256=None,
        result_occurrence_sha256s=[item.occurrence_sha256 for item in occurrences],
        route_landing_sha256s=[item.landing_sha256 for item in landings],
        capture_response_receipt_sha256=_sha("capture:franchise-history:strict"),
        logical_receipt_sha256=logical_receipt_sha256,
    )
    return RawRequestAuthorityBundleV2.build(
        objects=[body],
        observations=[observation],
        occurrences=occurrences,
        landings=landings,
    )


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
def test_declared_stats_fallback_closes_fixed_and_conditional_frame_authority(
    variant: str,
    wide_admitted: bool,
) -> None:
    bundle, observation, occurrences, landings = _stats_fallback_bundle(variant)
    fixed = landings[:-1]
    conditional = landings[-1]

    assert validate_raw_request_authority_bundle(bundle) == bundle
    assert observation.result_occurrence_count == len(occurrences)
    assert conditional.landing_semantic == "conditional_lossless"
    assert conditional.source_occurrence_count == len(occurrences)
    assert conditional.persisted_row_count > 0
    assert all(item.source_occurrence_count == 1 for item in fixed)
    assert all((item.persisted_row_count > 0) == wide_admitted for item in fixed)
    for item in occurrences:
        route_ids = set(item.canonical_route_ids())
        if route_ids & {landing.route_id for landing in fixed}:
            assert item.landing_disposition == (
                "wide_plus_lossless" if wide_admitted else "lossless_only"
            )

    if variant == "missing_result":
        missing = next(item for item in occurrences if item.presence == "missing")
        assert missing.provider_result_ordinal is None
        assert missing.canonical_result_ordinal is None
        assert missing.ordered_headers() == ()
    if variant == "duplicate_name":
        repeated = [item for item in occurrences if item.result_name == occurrences[0].result_name]
        assert [item.duplicate_name_ordinal for item in repeated] == [0, 1]
        assert repeated[0].landing_disposition == "lossless_only"
        assert repeated[1].canonical_route_ids() == (conditional.route_id,)


def test_strict_stats_frame_hashes_are_rebuilt_before_receipt_admission() -> None:
    bundle = _strict_stats_bundle()
    assert validate_raw_request_authority_bundle(bundle) == bundle
    with pytest.raises(ValidationError, match="stats fixed route landing"):
        _strict_stats_bundle(tamper_fixed_frame=True)


def test_stats_fallback_rejects_coordinated_frame_and_occurrence_reseals() -> None:
    with pytest.raises(ValidationError, match="stats fixed route landing"):
        _stats_fallback_bundle("header_drift", tamper_fixed_frame=True)
    with pytest.raises(ValidationError, match="stats conditional lossless landing"):
        _stats_fallback_bundle("header_drift", tamper_conditional_frame=True)
    with pytest.raises(ValidationError, match="occurrence differs from exact rederivation"):
        _stats_fallback_bundle("header_drift", tamper_occurrence=True)


def test_static_and_live_occurrence_reseals_fail_exact_body_or_snapshot_replay() -> None:
    with pytest.raises(ValidationError, match="occurrence differs from exact rederivation"):
        _static_bundle(tamper_occurrence=True)
    with pytest.raises(ValidationError, match="occurrence differs from exact rederivation"):
        _live_occurrence_reseal_bundle()


def test_live_snapshot_time_is_sealed_and_partitioned_by_source_family() -> None:
    receipt = _receipt(
        route_id="live_route",
        staging_key="stg_live_route",
        logical_receipt_sha256=_sha("live-snapshot-logical"),
        provider_authority_sha256=_sha("live-snapshot-provider"),
        logical_parameters_sha256=_sha("live-snapshot-parameters"),
        row_count=1,
    )
    landing = ObservationRouteLandingV2.build(
        observation_sha256=_sha("live-snapshot-observation"),
        logical_receipt_sha256=_sha("live-snapshot-logical"),
        route_ordinal=0,
        route_authority_kind="staging_route_contract_v1",
        route_authority_sha256=_sha("live-snapshot-route"),
        landing_semantic="occurrence_bound",
        conditional_lossless=False,
        alias_target_route_id=None,
        live_snapshot_at=_STARTED_AT,
        source_occurrence_sha256s=[_sha("live-snapshot-occurrence")],
        committed_receipt=receipt,
    )
    assert ObservationRouteLandingV2.from_canonical_bytes(landing.to_canonical_bytes()) == landing
    with pytest.raises(ValidationError, match="shared snapshot time"):
        _live_occurrence_reseal_bundle(
            tamper_occurrence=False,
            conditional_snapshot_at=_STARTED_AT + timedelta(microseconds=1),
        )
    with pytest.raises(ValidationError, match="shared snapshot time"):
        _live_occurrence_reseal_bundle(
            tamper_occurrence=False,
            fixed_snapshot_at=None,
        )
    with pytest.raises(ValidationError, match="fabricated a live snapshot"):
        _static_bundle(live_snapshot_at=_STARTED_AT)


def test_public_exports_are_v2_only_and_cover_four_relation_adapters() -> None:
    expected = {
        "ParserInputObjectV2",
        "RequestAttemptIdentityV2",
        "RequestObservationV2",
        "ResultOccurrenceV2",
        "ObservationRouteLandingV2",
        "RawRequestAuthorityBundleV2",
        "OBSERVATION_ROUTE_LANDING_ADAPTER",
        "RAW_REQUEST_AUTHORITY_BUNDLE_ADAPTER",
    }
    assert expected <= set(raw_request_authority.__all__)
    assert not any(name.endswith("V1") for name in raw_request_authority.__all__)


def test_parser_input_is_exact_canonical_and_rejects_v1_or_sensitive_bytes() -> None:
    parser_input = '{"resultSets":[{"headers":["A","A"],"rowSet":[]}]}'
    body = ParserInputObjectV2.from_parser_input(parser_input)
    assert body.schema_version == 2
    assert body.representation == PUBLIC_PARSER_INPUT_REPRESENTATION
    assert body.codec == DETERMINISTIC_GZIP_CODEC
    assert decode_parser_input_object(body) == parser_input.encode()
    assert ParserInputObjectV2.from_canonical_bytes(body.to_canonical_bytes()) == body
    with pytest.raises(ValidationError):
        validate_parser_input_object(_mutated_payload(body, schema_version=1))
    with pytest.raises(RawRequestAuthorityError):
        ParserInputObjectV2.from_parser_input('{"authorization":"Bearer value"}')


@pytest.mark.parametrize(
    "secret_key",
    [
        "apiKey",
        "APIKey",
        "api-key",
        "api.key",
        "accessToken",
        "AccessToken",
        "access token",
        "clientSecret",
        "ClientSecret",
        "client/secret",
    ],
)
def test_parser_input_rejects_nested_normalized_secret_keys(secret_key: str) -> None:
    parser_input = json.dumps(
        {"outer": [{"nested": {secret_key: "sentinel"}}]},
        separators=(",", ":"),
    )
    with pytest.raises(
        RawRequestAuthorityError,
        match="prohibited transport or secret material",
    ):
        ParserInputObjectV2.from_parser_input(parser_input)


@pytest.mark.parametrize(
    "benign_key",
    [
        "apiKeyboard",
        "clientSecretariat",
        "accessTokenized",
        "publicApiKeyCount",
        "secretary",
    ],
)
def test_parser_input_allows_benign_secret_key_lookalikes(benign_key: str) -> None:
    parser_input = json.dumps(
        {"outer": [{"nested": {benign_key: "public-value"}}]},
        separators=(",", ":"),
    )
    body = ParserInputObjectV2.from_parser_input(parser_input)
    assert decode_parser_input_object(body) == parser_input.encode()


@pytest.mark.parametrize("stored_remainder", [1, 2])
def test_parser_input_rejects_noncanonical_rfc4648_pad_bits(stored_remainder: int) -> None:
    body = next(
        candidate
        for size in range(1, 512)
        if (
            candidate := ParserInputObjectV2.from_parser_input(
                json.dumps({"value": "x" * size}, separators=(",", ":"))
            )
        ).stored_bytes
        % 3
        == stored_remainder
    )
    payload = json.loads(body.to_canonical_bytes())
    encoded = payload["stored_payload_base64"]
    assert isinstance(encoded, str)
    alphabet = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789+/"
    significant_index = -3 if stored_remainder == 1 else -2
    original_index = alphabet.index(encoded[significant_index])
    alias_index = original_index + 1
    aliased = (
        f"{encoded[:significant_index]}{alphabet[alias_index]}{encoded[significant_index + 1 :]}"
    )
    assert base64.b64decode(aliased, validate=True) == body.stored_payload
    payload["stored_payload_base64"] = aliased
    with pytest.raises(RawRequestAuthorityError, match="base64 is not canonical"):
        ParserInputObjectV2.from_canonical_bytes(_parser_input(payload))


def test_attempt_identity_and_parameters_are_strict_canonical_v2() -> None:
    safe_json, safe_sha256, _provider_request = canonical_semantic_parameters(
        "live",
        "BoxScore",
        {"game_id": "0022500001"},
    )
    assert safe_json == '{"game_id":"0022500001"}'
    assert safe_sha256 == _sha(safe_json)
    attempt = _attempt()
    assert RequestAttemptIdentityV2.from_canonical_bytes(attempt.to_canonical_bytes()) == attempt
    with pytest.raises(ValidationError):
        validate_request_attempt_identity(_mutated_payload(attempt, schema_version=1))
    with pytest.raises(ValidationError):
        validate_request_attempt_identity(_mutated_payload(attempt, retry_ordinal=True))


def test_result_occurrence_preserves_duplicate_headers_presence_and_receipt_order() -> None:
    attempt = _attempt(
        source_family="stats",
        endpoint_id="ScoreboardV2",
        parameters={"game_date": "2026-08-26"},
    )
    occurrence = ResultOccurrenceV2.build(
        observation_sha256=attempt.observation_sha256,
        occurrence_ordinal=0,
        result_name="GameHeader",
        duplicate_name_ordinal=0,
        provider_result_ordinal=0,
        canonical_result_ordinal=0,
        json_path=None,
        container_kind="nba_api_result_set",
        presence="present_empty",
        ordered_headers=["GAME_ID", "GAME_ID"],
        row_count=0,
        cell_count=0,
        node_count=0,
        container_count=1,
        missing_count=0,
        null_count=0,
        parent_state_sha256=None,
        output_sha256=_HASHES[6],
        canonical_route_ids=["route_b", "route_a"],
        committed_staging_receipts=[
            {"route_id": "route_b", "receipt_sha256": _HASHES[12]},
            {"route_id": "route_a", "receipt_sha256": _HASHES[13]},
        ],
        landing_disposition="wide_only",
    )
    assert occurrence.ordered_headers() == ("GAME_ID", "GAME_ID")
    assert occurrence.canonical_route_ids() == ("route_b", "route_a")
    assert dict(occurrence.committed_staging_receipts_by_route()) == {
        "route_b": _HASHES[12],
        "route_a": _HASHES[13],
    }
    assert ResultOccurrenceV2.from_canonical_bytes(occurrence.to_canonical_bytes()) == occurrence
    with pytest.raises(ValidationError):
        validate_result_occurrence(_mutated_payload(occurrence, schema_version=1))


def test_observation_route_landing_binds_full_committed_receipt_and_semantic_partition() -> None:
    attempt = _attempt()
    logical_receipt = _sha("logical")
    receipt = _receipt(
        route_id="route_0",
        staging_key="stg_route_0",
        logical_receipt_sha256=logical_receipt,
        provider_authority_sha256=attempt.provider_authority_sha256,
        logical_parameters_sha256=attempt.safe_parameters_sha256,
        row_count=1,
    )
    landing = ObservationRouteLandingV2.build(
        observation_sha256=attempt.observation_sha256,
        logical_receipt_sha256=logical_receipt,
        route_ordinal=0,
        route_authority_kind="staging_route_contract_v1",
        route_authority_sha256=_sha("route-authority"),
        landing_semantic="occurrence_bound",
        conditional_lossless=False,
        alias_target_route_id=None,
        live_snapshot_at=None,
        source_occurrence_sha256s=[_sha("occurrence")],
        committed_receipt=receipt,
    )
    assert landing.receipt_root_sha256 == receipt.receipt_root_sha256
    assert landing.to_row()["result_route_id"] == "route_0"
    assert ObservationRouteLandingV2.from_canonical_bytes(landing.to_canonical_bytes()) == landing
    assert validate_observation_route_landing(landing) == landing
    for mutation in (
        {"schema_version": 1},
        {"route_ordinal": True},
        {"receipt_root_sha256": _sha("forged")},
        {"source_occurrence_count": 0},
        {"conditional_lossless": True},
        {"alias_target_route_id": "foreign"},
    ):
        with pytest.raises(ValidationError):
            ObservationRouteLandingV2.model_validate(_mutated_payload(landing, **mutation))


def test_ordinary_occurrence_bound_bundle_closes_all_four_inventories() -> None:
    bundle, observation, occurrence, landing = _static_bundle()
    assert observation.route_landing_count == 1
    assert observation.route_landings_sha256 != BODYLESS_ROUTE_LANDINGS_SHA256
    assert landing.source_occurrence_count == 1
    assert validate_raw_request_authority_bundle(bundle) == bundle
    bundle.require_complete_terminal_selection()
    assert bundle.selected_terminal_occurrences_for_route(
        landing.route_id,
        landing.receipt_root_sha256,
    ) == ((observation, occurrence),)


@pytest.mark.parametrize("payload", [{}, {"resultSets": []}])
@pytest.mark.parametrize("endpoint_id", ["VideoDetails", "VideoEvents"])
def test_unknown_video_no_drift_has_only_exact_fixed_zero_landing(
    endpoint_id: str,
    payload: object,
) -> None:
    bundle, observation, occurrences, landings = _video_bundle(endpoint_id, payload)
    assert occurrences == ()
    assert observation.outcome == "success_empty"
    assert observation.result_occurrence_count == 0
    assert len(landings) == 1
    assert landings[0].landing_semantic == "response_fixed_zero"
    assert landings[0].persisted_row_count == 0
    assert validate_raw_request_authority_bundle(bundle) == bundle


def test_video_details_drift_keeps_fixed_zero_and_adds_conditional_lossless() -> None:
    bundle, observation, occurrences, landings = _video_bundle(
        "VideoDetails",
        {"future": {"x": 1}},
    )
    assert observation.outcome == "success_nonempty"
    assert occurrences == ()
    assert [item.landing_semantic for item in landings] == [
        "response_fixed_zero",
        "conditional_lossless",
    ]
    assert landings[0].persisted_row_count == 0
    assert landings[1].persisted_row_count > 0
    assert validate_raw_request_authority_bundle(bundle) == bundle


def test_video_events_drift_aliases_exact_conditional_frame() -> None:
    bundle, _observation, occurrences, landings = _video_bundle(
        "VideoEvents",
        {"future": {"x": [1, "two"]}},
    )
    assert occurrences == ()
    assert [item.landing_semantic for item in landings] == [
        "response_canonical_alias",
        "conditional_lossless",
    ]
    fixed, conditional = landings
    assert fixed.alias_target_route_id == conditional.route_id
    assert (
        fixed.persisted_row_count,
        fixed.content_hash,
        fixed.persisted_content_sha256,
        fixed.persisted_schema_sha256,
    ) == (
        conditional.persisted_row_count,
        conditional.content_hash,
        conditional.persisted_content_sha256,
        conditional.persisted_schema_sha256,
    )
    assert validate_raw_request_authority_bundle(bundle) == bundle

    with pytest.raises(ValidationError, match="canonical-alias landing"):
        ObservationRouteLandingV2.build(
            observation_sha256=fixed.observation_sha256,
            logical_receipt_sha256=fixed.logical_receipt_sha256,
            route_ordinal=fixed.route_ordinal,
            route_authority_kind="staging_route_contract_v1",
            route_authority_sha256=fixed.route_authority_sha256,
            landing_semantic="response_canonical_alias",
            conditional_lossless=False,
            alias_target_route_id=conditional.route_id,
            live_snapshot_at=None,
            source_occurrence_sha256s=[_sha("fabricated-alias-source")],
            committed_receipt=_receipt(
                route_id=fixed.route_id,
                staging_key=fixed.staging_key,
                logical_receipt_sha256=fixed.logical_receipt_sha256,
                provider_authority_sha256=fixed.provider_authority_sha256,
                logical_parameters_sha256=fixed.logical_parameters_sha256,
                row_count=conditional.persisted_row_count,
            ),
        )


def test_unknown_video_duplicate_named_legacy_results_are_occurrence_bound_once_each() -> None:
    bundle, observation, occurrences, landings = _video_bundle(
        "VideoEvents",
        {
            "resultSets": [
                {"name": "Stats", "headers": ["A"], "rowSet": [[1]]},
                {"name": "Stats", "headers": ["A", "A"], "rowSet": [[2, 3]]},
            ]
        },
    )
    assert [item.duplicate_name_ordinal for item in occurrences] == [0, 1]
    assert [item.provider_result_ordinal for item in occurrences] == [0, 1]
    assert all(item.canonical_result_ordinal is None for item in occurrences)
    assert all(item.canonical_route_ids() == (landings[1].route_id,) for item in occurrences)
    assert landings[1].source_occurrence_count == 2
    assert observation.result_occurrence_count == 2
    assert validate_raw_request_authority_bundle(bundle) == bundle


def test_generic_zero_occurrence_success_is_rejected_before_bundle_admission() -> None:
    attempt = _attempt()
    body = ParserInputObjectV2.from_parser_input("{}")
    with pytest.raises(ValueError, match="declared result occurrence"):
        RequestObservationV2.build(
            attempt=attempt,
            transport={
                "transport_kind": "live_http",
                "status_code": 200,
                "effective_status_code": 200,
            },
            started_at=_STARTED_AT,
            finished_at=_STARTED_AT + timedelta(seconds=1),
            elapsed_ns=1,
            lifecycle="selected_terminal",
            outcome="success_empty",
            failure_class=None,
            root_exception_class=None,
            body_disposition="public_parser_input",
            body_object_sha256=body.object_sha256,
            bodyless_evidence_sha256=None,
            result_occurrence_sha256s=[],
            route_landing_sha256s=[_sha("fake-landing")],
            capture_response_receipt_sha256=_sha("capture"),
            logical_receipt_sha256=_sha("logical"),
        )


def test_video_drift_rejects_missing_extra_reordered_and_resealed_landings() -> None:
    bundle, observation, occurrences, landings = _video_bundle(
        "VideoEvents",
        {"future": {"x": 1}},
    )
    body = bundle.objects[0]
    fixed, conditional = landings

    missing_observation = RequestObservationV2.build(
        attempt=observation.attempt,
        transport=observation.transport,
        started_at=observation.started_at,
        finished_at=observation.finished_at,
        elapsed_ns=observation.elapsed_ns,
        lifecycle=observation.lifecycle,
        outcome=observation.outcome,
        failure_class=None,
        root_exception_class=None,
        body_disposition=observation.body_disposition,
        body_object_sha256=observation.body_object_sha256,
        bodyless_evidence_sha256=None,
        result_occurrence_sha256s=[item.occurrence_sha256 for item in occurrences],
        route_landing_sha256s=[fixed.landing_sha256],
        capture_response_receipt_sha256=observation.capture_response_receipt_sha256,
        logical_receipt_sha256=observation.logical_receipt_sha256,
    )
    with pytest.raises(ValidationError, match="conditional landing"):
        RawRequestAuthorityBundleV2.build(
            objects=[body],
            observations=[missing_observation],
            occurrences=occurrences,
            landings=[fixed],
        )

    reordered_observation = RequestObservationV2.build(
        attempt=observation.attempt,
        transport=observation.transport,
        started_at=observation.started_at,
        finished_at=observation.finished_at,
        elapsed_ns=observation.elapsed_ns,
        lifecycle=observation.lifecycle,
        outcome=observation.outcome,
        failure_class=None,
        root_exception_class=None,
        body_disposition=observation.body_disposition,
        body_object_sha256=observation.body_object_sha256,
        bodyless_evidence_sha256=None,
        result_occurrence_sha256s=[item.occurrence_sha256 for item in occurrences],
        route_landing_sha256s=[conditional.landing_sha256, fixed.landing_sha256],
        capture_response_receipt_sha256=observation.capture_response_receipt_sha256,
        logical_receipt_sha256=observation.logical_receipt_sha256,
    )
    with pytest.raises(ValidationError, match="canonically ordered"):
        RawRequestAuthorityBundleV2.build(
            objects=[body],
            observations=[reordered_observation],
            occurrences=occurrences,
            landings=[conditional, fixed],
        )

    extra_receipt = _receipt(
        route_id=conditional.route_id,
        staging_key=conditional.staging_key,
        logical_receipt_sha256=conditional.logical_receipt_sha256,
        provider_authority_sha256=conditional.provider_authority_sha256,
        logical_parameters_sha256=conditional.logical_parameters_sha256,
        row_count=conditional.persisted_row_count,
        salt="extra",
    )
    extra = ObservationRouteLandingV2.build(
        observation_sha256=observation.attempt.observation_sha256,
        logical_receipt_sha256=cast("str", observation.logical_receipt_sha256),
        route_ordinal=2,
        route_authority_kind="conditional_staging_route_admission_v1",
        route_authority_sha256=conditional.route_authority_sha256,
        landing_semantic="conditional_lossless",
        conditional_lossless=True,
        alias_target_route_id=None,
        live_snapshot_at=None,
        source_occurrence_sha256s=[item.occurrence_sha256 for item in occurrences],
        committed_receipt=extra_receipt,
    )
    extra_observation = RequestObservationV2.build(
        attempt=observation.attempt,
        transport=observation.transport,
        started_at=observation.started_at,
        finished_at=observation.finished_at,
        elapsed_ns=observation.elapsed_ns,
        lifecycle=observation.lifecycle,
        outcome=observation.outcome,
        failure_class=None,
        root_exception_class=None,
        body_disposition=observation.body_disposition,
        body_object_sha256=observation.body_object_sha256,
        bodyless_evidence_sha256=None,
        result_occurrence_sha256s=[item.occurrence_sha256 for item in occurrences],
        route_landing_sha256s=[item.landing_sha256 for item in (*landings, extra)],
        capture_response_receipt_sha256=observation.capture_response_receipt_sha256,
        logical_receipt_sha256=observation.logical_receipt_sha256,
    )
    with pytest.raises(ValidationError, match="multiple conditional"):
        RawRequestAuthorityBundleV2.build(
            objects=[body],
            observations=[extra_observation],
            occurrences=occurrences,
            landings=[*landings, extra],
        )


def test_bundle_rejects_foreign_route_authority_and_resealed_receipt_root() -> None:
    bundle, observation, occurrence, landing = _static_bundle()
    foreign = ObservationRouteLandingV2.build(
        observation_sha256=landing.observation_sha256,
        logical_receipt_sha256=landing.logical_receipt_sha256,
        route_ordinal=0,
        route_authority_kind="staging_route_contract_v1",
        route_authority_sha256=_sha("foreign-route-authority"),
        landing_semantic="occurrence_bound",
        conditional_lossless=False,
        alias_target_route_id=None,
        live_snapshot_at=None,
        source_occurrence_sha256s=[occurrence.occurrence_sha256],
        committed_receipt=_receipt(
            route_id=landing.route_id,
            staging_key=landing.staging_key,
            logical_receipt_sha256=landing.logical_receipt_sha256,
            provider_authority_sha256=landing.provider_authority_sha256,
            logical_parameters_sha256=landing.logical_parameters_sha256,
            row_count=1,
        ),
    )
    foreign_observation = RequestObservationV2.build(
        attempt=observation.attempt,
        transport=observation.transport,
        started_at=observation.started_at,
        finished_at=observation.finished_at,
        elapsed_ns=observation.elapsed_ns,
        lifecycle=observation.lifecycle,
        outcome=observation.outcome,
        failure_class=None,
        root_exception_class=None,
        body_disposition=observation.body_disposition,
        body_object_sha256=None,
        bodyless_evidence_sha256=observation.bodyless_evidence_sha256,
        result_occurrence_sha256s=[occurrence.occurrence_sha256],
        route_landing_sha256s=[foreign.landing_sha256],
        capture_response_receipt_sha256=observation.capture_response_receipt_sha256,
        logical_receipt_sha256=observation.logical_receipt_sha256,
    )
    with pytest.raises(ValidationError, match="pinned route authority"):
        RawRequestAuthorityBundleV2.build(
            objects=[],
            observations=[foreign_observation],
            occurrences=[occurrence],
            landings=[foreign],
        )

    resealed_receipt = _receipt(
        route_id=landing.route_id,
        staging_key=landing.staging_key,
        logical_receipt_sha256=landing.logical_receipt_sha256,
        provider_authority_sha256=landing.provider_authority_sha256,
        logical_parameters_sha256=landing.logical_parameters_sha256,
        row_count=1,
        salt="foreign-root",
    )
    resealed = ObservationRouteLandingV2.build(
        observation_sha256=landing.observation_sha256,
        logical_receipt_sha256=landing.logical_receipt_sha256,
        route_ordinal=0,
        route_authority_kind="staging_route_contract_v1",
        route_authority_sha256=landing.route_authority_sha256,
        landing_semantic="occurrence_bound",
        conditional_lossless=False,
        alias_target_route_id=None,
        live_snapshot_at=None,
        source_occurrence_sha256s=[occurrence.occurrence_sha256],
        committed_receipt=resealed_receipt,
    )
    resealed_observation = RequestObservationV2.build(
        attempt=observation.attempt,
        transport=observation.transport,
        started_at=observation.started_at,
        finished_at=observation.finished_at,
        elapsed_ns=observation.elapsed_ns,
        lifecycle=observation.lifecycle,
        outcome=observation.outcome,
        failure_class=None,
        root_exception_class=None,
        body_disposition=observation.body_disposition,
        body_object_sha256=None,
        bodyless_evidence_sha256=observation.bodyless_evidence_sha256,
        result_occurrence_sha256s=[occurrence.occurrence_sha256],
        route_landing_sha256s=[resealed.landing_sha256],
        capture_response_receipt_sha256=observation.capture_response_receipt_sha256,
        logical_receipt_sha256=observation.logical_receipt_sha256,
    )
    with pytest.raises(ValidationError, match="receipt root differs"):
        RawRequestAuthorityBundleV2.build(
            objects=[],
            observations=[resealed_observation],
            occurrences=[occurrence],
            landings=[resealed],
        )
    assert validate_raw_request_authority_bundle(bundle) == bundle


def test_failed_observation_is_bodyless_and_carries_no_route_landing() -> None:
    observation = RequestObservationV2.build(
        attempt=_attempt(),
        transport={
            "transport_kind": "live_http",
            "status_code": None,
            "effective_status_code": None,
        },
        started_at=_STARTED_AT,
        finished_at=_STARTED_AT + timedelta(seconds=1),
        elapsed_ns=1,
        lifecycle="incomplete",
        outcome="transport_failure_no_response",
        failure_class="transport_transient",
        root_exception_class="ReadTimeout",
        body_disposition="no_response",
        body_object_sha256=None,
        bodyless_evidence_sha256=_sha("no-response"),
        result_occurrence_sha256s=[],
        route_landing_sha256s=[],
        capture_response_receipt_sha256=None,
        logical_receipt_sha256=None,
    )
    assert observation.result_occurrences_sha256 == BODYLESS_RESULT_OCCURRENCES_SHA256
    assert observation.route_landings_sha256 == BODYLESS_ROUTE_LANDINGS_SHA256
    assert (
        RequestObservationV2.from_canonical_bytes(observation.to_canonical_bytes()) == observation
    )
    assert validate_request_observation(observation) == observation
    incomplete_bundle = RawRequestAuthorityBundleV2.build(
        objects=[],
        observations=[observation],
        occurrences=[],
        landings=[],
    )
    assert incomplete_bundle.incomplete_provider_call_sha256s() == (
        observation.attempt.provider_call_sha256,
    )


@pytest.mark.parametrize(
    ("outcome", "status_code", "body_disposition", "failure_class"),
    [
        ("http_transient_error", 500, "excluded_failure_body", "transport_transient"),
        ("http_application_error", 400, "excluded_failure_body", "application"),
        ("malformed_json", 200, "excluded_failure_body", "response_contract"),
        ("application_error_envelope", 200, "excluded_failure_body", "application"),
        ("contract_mismatch", 200, "excluded_failure_body", "response_contract"),
        ("parser_failure", 200, "excluded_failure_body", "response_contract"),
        ("transport_failure_no_response", None, "no_response", "transport_transient"),
        ("cancelled_before_response", None, "no_response", "runner_infrastructure"),
    ],
)
def test_every_failure_outcome_rejects_selected_terminal_lifecycle(
    outcome: str,
    status_code: int | None,
    body_disposition: str,
    failure_class: str,
) -> None:
    with pytest.raises(ValidationError, match="failed observation must remain incomplete"):
        RequestObservationV2.build(
            attempt=_attempt(),
            transport={
                "transport_kind": "live_http",
                "status_code": status_code,
                "effective_status_code": status_code,
            },
            started_at=_STARTED_AT,
            finished_at=_STARTED_AT + timedelta(seconds=1),
            elapsed_ns=1,
            lifecycle="selected_terminal",
            outcome=outcome,  # type: ignore[arg-type]
            failure_class=failure_class,  # type: ignore[arg-type]
            root_exception_class="ReadTimeout",
            body_disposition=body_disposition,  # type: ignore[arg-type]
            body_object_sha256=None,
            bodyless_evidence_sha256=_sha(f"failed:{outcome}"),
            result_occurrence_sha256s=[],
            route_landing_sha256s=[],
            capture_response_receipt_sha256=None,
            logical_receipt_sha256=None,
        )


def test_selected_route_requires_exact_response_level_landing_even_when_empty() -> None:
    video_bundle, _video_observation, video_occurrences, video_landings = _video_bundle(
        "VideoEvents",
        {},
    )
    assert video_occurrences == ()
    fixed = video_landings[0]
    assert (
        video_bundle.selected_terminal_occurrences_for_route(
            fixed.route_id,
            fixed.receipt_root_sha256,
        )
        == ()
    )
    with pytest.raises(RawRequestAuthorityError, match="landing has the wrong"):
        video_bundle.selected_terminal_occurrences_for_route(
            fixed.route_id,
            _sha("forged-empty-root"),
        )
    with pytest.raises(RawRequestAuthorityError, match="lacks response-level landing"):
        video_bundle.selected_terminal_occurrences_for_route(
            "foreign:route:0",
            fixed.receipt_root_sha256,
        )

    ordinary_bundle, observation, occurrence, landing = _static_bundle()
    assert ordinary_bundle.selected_terminal_occurrences_for_route(
        landing.route_id,
        landing.receipt_root_sha256,
    ) == ((observation, occurrence),)


def test_preallocation_resource_bounds_apply_before_digesting(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(raw_request_authority, "MAX_AUTHORITY_ROWS", 1)
    with pytest.raises(RawRequestAuthorityError, match="occurrence inventory exceeds"):
        RequestObservationV2.build(
            attempt=_attempt(),
            transport={
                "transport_kind": "live_http",
                "status_code": None,
                "effective_status_code": None,
            },
            started_at=_STARTED_AT,
            finished_at=_STARTED_AT + timedelta(seconds=1),
            elapsed_ns=1,
            lifecycle="incomplete",
            outcome="transport_failure_no_response",
            failure_class="transport_transient",
            root_exception_class="ReadTimeout",
            body_disposition="no_response",
            body_object_sha256=None,
            bodyless_evidence_sha256=_sha("no-response"),
            result_occurrence_sha256s=[_HASHES[0], _HASHES[1]],
            route_landing_sha256s=[],
            capture_response_receipt_sha256=None,
            logical_receipt_sha256=None,
        )
