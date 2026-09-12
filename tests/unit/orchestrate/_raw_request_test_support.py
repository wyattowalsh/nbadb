"""Synthetic validated assurance authority for low-level raw-request tests."""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import cast
from unittest.mock import patch

import polars as pl

from nbadb.contracts.assurance import AssuranceGeneration
from nbadb.contracts.assurance_admission import AssuranceAdmission
from nbadb.contracts.raw_request_authority import (
    ObservationRouteLandingV2,
    ParserInputObjectV2,
    RawRequestAuthorityBundleV2,
    RequestAttemptIdentityV2,
    RequestObservationV2,
    ResultOccurrenceV2,
)
from nbadb.contracts.staging_route_contract import (
    admit_conditional_lossless_route,
    staging_route_contract_bundle,
)
from nbadb.core.nba_api_provenance import expected_nba_api_provider_authority
from nbadb.core.nba_api_runtime_contract import (
    endpoint_contract_sha256,
    pinned_runtime_contracts,
)
from nbadb.extract.nba_api_adapter import rederive_raw_authority_unknown_stats_response
from nbadb.extract.stats_lossless import build_unknown_stats_lossless_fallback
from nbadb.orchestrate import raw_request_assurance as authority_module
from nbadb.orchestrate.raw_request_assurance import (
    RawRequestAssuranceAuthorityV2,
    load_raw_request_assurance_authority,
)
from nbadb.orchestrate.staging_batches import (
    CANONICAL_FRAME_FORMAT,
    FRAME_CONTENT_HASH_CONTRACT,
    FRAME_SCHEMA_HASH_CONTRACT,
    CommittedStagingChunkReceiptV2,
    frame_content_hash,
    frame_schema_hash,
)
from nbadb.orchestrate.staging_map import LOSSLESS_FALLBACK_STAGING_KEY

_STARTED_AT = datetime(2026, 8, 27, 12, 0, tzinfo=UTC)
_SOURCE_SHA = "1" * 40
_VIDEO_DETAILS_PARAMETERS = {"team_id": 1, "player_id": 2, "season": "2024-25"}


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


def _committed_receipt(
    *,
    route_id: str,
    staging_key: str,
    logical_receipt_sha256: str,
    provider_authority_sha256: str,
    logical_parameters_sha256: str,
    frame: pl.DataFrame,
) -> CommittedStagingChunkReceiptV2:
    content_sha256 = frame_content_hash(frame)
    schema_sha256 = frame_schema_hash(frame)
    return CommittedStagingChunkReceiptV2(
        chunk_id=f"chunk:{route_id}",
        staging_key=staging_key,
        canonical_frame_format=CANONICAL_FRAME_FORMAT,
        frame_content_hash_contract=FRAME_CONTENT_HASH_CONTRACT,
        frame_schema_hash_contract=FRAME_SCHEMA_HASH_CONTRACT,
        content_hash=content_sha256,
        persisted_row_count=frame.height,
        persisted_content_sha256=content_sha256,
        persisted_schema_sha256=schema_sha256,
        logical_call_receipt_sha256=logical_receipt_sha256,
        provider_authority_sha256=provider_authority_sha256,
        logical_parameters_sha256=logical_parameters_sha256,
        result_route_id=route_id,
    )


def raw_request_video_authority_bundle(
    *,
    payload: object | None = None,
    retry_ordinal: int = 0,
    terminal: bool = True,
) -> RawRequestAuthorityBundleV2:
    """Build exact VideoDetails V2 evidence, including response-level landings."""

    endpoint_id = "VideoDetails"
    contract = pinned_runtime_contracts()[endpoint_id]
    provider_authority_sha256 = cast(
        "str",
        expected_nba_api_provider_authority()["authority_sha256"],
    )
    attempt = RequestAttemptIdentityV2.build(
        semantic_request_sha256=_sha("video-details-semantic-request"),
        logical_invocation_sha256=_sha("video-details-logical-invocation"),
        provider_call_role="primary",
        provider_call_ordinal=0,
        retry_ordinal=retry_ordinal,
        request_ordinal=0,
        source_family="stats",
        endpoint_id=endpoint_id,
        parameters=_VIDEO_DETAILS_PARAMETERS,
        provider_authority_sha256=provider_authority_sha256,
        endpoint_contract_sha256=endpoint_contract_sha256(contract),
        competition_id=None,
        competition_identity_sha256=None,
        scope_sha256=_sha("video-details-scope"),
        pagination_sha256=None,
        page_ordinal=None,
        source_sha=_SOURCE_SHA,
        run_id=101,
        run_attempt=1,
        chain_id="chain",
        lane_id="lane",
    )
    if not terminal:
        observation = RequestObservationV2.build(
            attempt=attempt,
            transport={"transport_kind": "stats_http"},
            started_at=_STARTED_AT,
            finished_at=_STARTED_AT + timedelta(seconds=1),
            elapsed_ns=1_000_000_000,
            lifecycle="incomplete",
            outcome="transport_failure_no_response",
            failure_class="transport_transient",
            root_exception_class="ConnectionError",
            body_disposition="no_response",
            body_object_sha256=None,
            bodyless_evidence_sha256=_sha("video-details-no-response"),
            result_occurrence_sha256s=(),
            route_landing_sha256s=(),
            capture_response_receipt_sha256=None,
            logical_receipt_sha256=None,
        )
        return RawRequestAuthorityBundleV2.build(
            objects=(),
            observations=(observation,),
            occurrences=(),
            landings=(),
        )

    parser_input = _parser_input({} if payload is None else payload)
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
    if len(fixed_routes) != 1:
        raise AssertionError("VideoDetails must expose one exact fixed route")
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
    capture_receipt_sha256 = _sha(f"capture:{parser_input!r}")
    logical_receipt_sha256 = _sha("video-details-logical-receipt")
    fallback = build_unknown_stats_lossless_fallback(
        unknown.bind_response_receipt(capture_receipt_sha256),
        expected_response_receipt_sha256=capture_receipt_sha256,
        expected_parameters_sha256=unknown.parameters_sha256,
        expected_parser_input_sha256=unknown.parser_input_sha256,
    )

    conditional_receipt = (
        None
        if fallback is None
        else _committed_receipt(
            route_id=conditional_route_id,
            staging_key=conditional_admission.staging_key,
            logical_receipt_sha256=logical_receipt_sha256,
            provider_authority_sha256=attempt.provider_authority_sha256,
            logical_parameters_sha256=attempt.safe_parameters_sha256,
            frame=fallback.frame,
        )
    )
    alias_policy = fixed_route.storage_columns == conditional_admission.storage_columns
    fixed_frame = fallback.frame if fallback is not None and alias_policy else pl.DataFrame()
    fixed_receipt = _committed_receipt(
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
        if conditional_receipt is None:
            raise AssertionError("named VideoDetails results require lossless fallback")
        duplicate_name_ordinal = duplicate_names.get(item.name, 0)
        duplicate_names[item.name] = duplicate_name_ordinal + 1
        occurrences.append(
            ResultOccurrenceV2.build(
                observation_sha256=attempt.observation_sha256,
                occurrence_ordinal=occurrence_ordinal,
                result_name=item.name,
                duplicate_name_ordinal=duplicate_name_ordinal,
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
                canonical_route_ids=(conditional_route_id,),
                committed_staging_receipts=(
                    {
                        "route_id": conditional_route_id,
                        "receipt_sha256": conditional_receipt.receipt_root_sha256,
                    },
                ),
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
                source_occurrence_sha256s=tuple(item.occurrence_sha256 for item in occurrences),
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
        result_occurrence_sha256s=tuple(item.occurrence_sha256 for item in occurrences),
        route_landing_sha256s=tuple(item.landing_sha256 for item in landings),
        capture_response_receipt_sha256=capture_receipt_sha256,
        logical_receipt_sha256=logical_receipt_sha256,
    )
    return RawRequestAuthorityBundleV2.build(
        objects=(body,),
        observations=(observation,),
        occurrences=tuple(occurrences),
        landings=tuple(landings),
    )


def raw_request_assurance_authority(
    *,
    source_sha: str = "a" * 40,
) -> RawRequestAssuranceAuthorityV2:
    """Route test evidence through the same loader-only construction boundary."""

    provider = expected_nba_api_provider_authority()
    selected = (
        *authority_module._FIELD_AUTHORITY_CHILD_NAMES,  # noqa: SLF001
        *authority_module._MODEL_AUTHORITY_CHILD_NAMES,  # noqa: SLF001
    )
    admission = AssuranceAdmission(
        source_sha=source_sha,
        assurance_manifest_sha256="1" * 64,
        generation_semantic_sha256="2" * 64,
        provider_evidence_sha256=str(provider["provider_evidence_sha256"]),
        provider_authority_sha256=str(provider["authority_sha256"]),
        authority_semantic_diff_sha256="3" * 64,
        authority_update_mode="full",
        first_extraction=True,
        model_status="GREEN",
    )
    generation = AssuranceGeneration(
        directory=Path("/synthetic/raw-request-assurance-generation"),
        manifest={
            "children": [
                {"name": name, "contract_sha256": f"{index + 4:064x}"}
                for index, name in enumerate(selected)
            ],
            "generation_semantic_sha256": admission.generation_semantic_sha256,
            "gate_results": {"model_green": True},
        },
        admission=admission,
        generation_index={},
        generation_index_sha256="4" * 64,
    )
    with patch.object(
        authority_module,
        "validate_assurance_generation",
        return_value=generation,
    ):
        return load_raw_request_assurance_authority(
            generation.directory,
            project_root=Path("/synthetic/project"),
            endpoint_analysis_docs_root=Path("/synthetic/nba-api"),
        )


__all__ = ["raw_request_assurance_authority", "raw_request_video_authority_bundle"]
