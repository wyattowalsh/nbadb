"""Strict fixed-table schemas for public ``nba_api`` request authority."""

from __future__ import annotations

import pandera.polars as pa
import polars as pl
from pandera.engines import polars_engine  # noqa: TC002

from nbadb.contracts.raw_request_authority import (
    DETERMINISTIC_GZIP_CODEC,
    DETERMINISTIC_GZIP_CONTRACT_SHA256,
    MAX_PARAMETER_JSON_BYTES,
    MAX_PARSER_INPUT_BYTES,
    MAX_PARSER_INPUT_STORED_BYTES,
    MAX_RESULT_JSON_BYTES,
    PUBLIC_PARSER_INPUT_REPRESENTATION,
)
from nbadb.core.extraction_failures import SAFE_ROOT_ERROR_NAMES
from nbadb.schemas.base import BaseSchema

_SHA256_PATTERN = r"^[0-9a-f]{64}$"
_GIT_SHA_PATTERN = r"^[0-9a-f]{40}$"
_SAFE_ID_PATTERN = r"^[A-Za-z0-9_][A-Za-z0-9_.:-]{0,199}$"
_RESULT_NAME_PATTERN = r"^[A-Za-z0-9_][A-Za-z0-9_.:-]{0,255}$"
_UTC_US_DTYPE = {
    "time_zone_agnostic": False,
    "time_zone": "UTC",
    "time_unit": "us",
}


class _FixedRawAuthoritySchema(BaseSchema):
    """Fail-closed table configuration for fixed public authority tables."""

    class Config:
        coerce = False
        strict = True
        ordered = True


class RawNbaApiParserInputObjectSchema(_FixedRawAuthoritySchema):
    """One deterministic compressed object for exact parser-consumed bytes."""

    schema_version: int = pa.Field(eq=2)
    object_sha256: str = pa.Field(str_matches=_SHA256_PATTERN, unique=True)
    representation: str = pa.Field(eq=PUBLIC_PARSER_INPUT_REPRESENTATION)
    media_type: str = pa.Field(eq="application/json")
    text_encoding: str = pa.Field(eq="utf-8")
    codec: str = pa.Field(eq=DETERMINISTIC_GZIP_CODEC)
    codec_contract_sha256: str = pa.Field(eq=DETERMINISTIC_GZIP_CONTRACT_SHA256)
    response_sha256: str = pa.Field(str_matches=_SHA256_PATTERN)
    uncompressed_bytes: int = pa.Field(ge=1, le=MAX_PARSER_INPUT_BYTES)
    stored_sha256: str = pa.Field(str_matches=_SHA256_PATTERN)
    stored_bytes: int = pa.Field(ge=1, le=MAX_PARSER_INPUT_STORED_BYTES)
    stored_payload: bytes


class RawNbaApiRequestObservationSchema(_FixedRawAuthoritySchema):
    """One exact request-attempt observation, body-bearing or typed bodyless."""

    schema_version: int = pa.Field(eq=2)
    observation_sha256: str = pa.Field(str_matches=_SHA256_PATTERN, unique=True)
    observation_record_sha256: str = pa.Field(str_matches=_SHA256_PATTERN, unique=True)
    semantic_request_sha256: str = pa.Field(str_matches=_SHA256_PATTERN)
    logical_invocation_sha256: str = pa.Field(str_matches=_SHA256_PATTERN)
    provider_call_sha256: str = pa.Field(str_matches=_SHA256_PATTERN)
    attempt_sha256: str = pa.Field(str_matches=_SHA256_PATTERN, unique=True)
    provider_call_role: str = pa.Field(str_matches=_SAFE_ID_PATTERN)
    provider_call_ordinal: int = pa.Field(ge=0)
    retry_ordinal: int = pa.Field(ge=0)
    request_ordinal: int = pa.Field(ge=0)
    source_family: str = pa.Field(isin=["stats", "live", "static"])
    endpoint_id: str = pa.Field(str_matches=_SAFE_ID_PATTERN)
    provider_request_sha256: str = pa.Field(str_matches=_SHA256_PATTERN)
    request_surface_sha256: str = pa.Field(str_matches=_SHA256_PATTERN)
    runtime_contract_sha256: str = pa.Field(str_matches=_SHA256_PATTERN)
    provider_authority_sha256: str = pa.Field(str_matches=_SHA256_PATTERN)
    endpoint_contract_sha256: str = pa.Field(str_matches=_SHA256_PATTERN)
    safe_parameters_json: str = pa.Field(str_length=(2, MAX_PARAMETER_JSON_BYTES))
    safe_parameters_sha256: str = pa.Field(str_matches=_SHA256_PATTERN)
    competition_id: str | None = pa.Field(
        nullable=True,
        str_matches=_SAFE_ID_PATTERN,
    )
    competition_identity_sha256: str | None = pa.Field(
        nullable=True,
        str_matches=_SHA256_PATTERN,
    )
    scope_sha256: str = pa.Field(str_matches=_SHA256_PATTERN)
    pagination_sha256: str | None = pa.Field(
        nullable=True,
        str_matches=_SHA256_PATTERN,
    )
    page_ordinal: int | None = pa.Field(nullable=True, ge=0)
    source_sha: str = pa.Field(str_matches=_GIT_SHA_PATTERN)
    run_id: int = pa.Field(ge=1)
    run_attempt: int = pa.Field(ge=1)
    chain_id: str = pa.Field(str_matches=_SAFE_ID_PATTERN)
    lane_id: str = pa.Field(str_matches=_SAFE_ID_PATTERN)
    transport_kind: str = pa.Field(isin=["stats_http", "live_http", "static_snapshot"])
    status_code: int | None = pa.Field(nullable=True, ge=100, le=599)
    effective_status_code: int | None = pa.Field(nullable=True, ge=100, le=599)
    started_at: polars_engine.DateTime = pa.Field(dtype_kwargs=_UTC_US_DTYPE)
    finished_at: polars_engine.DateTime | None = pa.Field(
        nullable=True,
        dtype_kwargs=_UTC_US_DTYPE,
    )
    elapsed_ns: int | None = pa.Field(nullable=True, ge=0)
    lifecycle: str = pa.Field(isin=["allocated", "incomplete", "selected_terminal"])
    outcome: str = pa.Field(
        isin=[
            "allocated",
            "success_nonempty",
            "success_empty",
            "downstream_incomplete",
            "static_snapshot_success",
            "http_transient_error",
            "http_application_error",
            "malformed_json",
            "application_error_envelope",
            "contract_mismatch",
            "parser_failure",
            "transport_failure_no_response",
            "cancelled_before_response",
        ]
    )
    failure_class: str | None = pa.Field(
        nullable=True,
        isin=[
            "transport_transient",
            "response_contract",
            "application",
            "vpn_egress",
            "runner_infrastructure",
            "timeout_progress",
            "timeout_stalled",
            "contract_blocked",
        ],
    )
    root_exception_class: str | None = pa.Field(
        nullable=True,
        isin=sorted(SAFE_ROOT_ERROR_NAMES),
    )
    body_disposition: str = pa.Field(
        isin=[
            "public_parser_input",
            "declared_bodyless",
            "no_response",
            "excluded_failure_body",
        ]
    )
    body_object_sha256: str | None = pa.Field(
        nullable=True,
        str_matches=_SHA256_PATTERN,
    )
    bodyless_evidence_sha256: str | None = pa.Field(
        nullable=True,
        str_matches=_SHA256_PATTERN,
    )
    body_authority_receipt_sha256: str = pa.Field(str_matches=_SHA256_PATTERN)
    result_occurrence_count: int = pa.Field(ge=0)
    result_occurrences_sha256: str = pa.Field(str_matches=_SHA256_PATTERN)
    route_landing_count: int = pa.Field(ge=0)
    route_landings_sha256: str = pa.Field(str_matches=_SHA256_PATTERN)
    capture_response_receipt_sha256: str | None = pa.Field(
        nullable=True,
        str_matches=_SHA256_PATTERN,
    )
    logical_receipt_sha256: str | None = pa.Field(
        nullable=True,
        str_matches=_SHA256_PATTERN,
    )
    logical_provider_parameter_binding_sha256: str | None = pa.Field(
        nullable=True,
        str_matches=_SHA256_PATTERN,
    )
    logical_provider_parameter_binding_json: str | None = pa.Field(
        nullable=True,
        str_length=(2, 2 * 1024 * 1024),
    )
    public_authority_receipt_sha256: str = pa.Field(str_matches=_SHA256_PATTERN)


class RawNbaApiResultOccurrenceSchema(_FixedRawAuthoritySchema):
    """One ordered or duplicate result occurrence under one observation."""

    schema_version: int = pa.Field(eq=2)
    occurrence_sha256: str = pa.Field(str_matches=_SHA256_PATTERN, unique=True)
    observation_sha256: str = pa.Field(str_matches=_SHA256_PATTERN)
    occurrence_ordinal: int = pa.Field(ge=0)
    result_name: str = pa.Field(str_matches=_RESULT_NAME_PATTERN)
    duplicate_name_ordinal: int = pa.Field(ge=0)
    provider_result_ordinal: int | None = pa.Field(nullable=True, ge=0)
    canonical_result_ordinal: int | None = pa.Field(nullable=True, ge=0)
    json_path: str | None = pa.Field(nullable=True, str_length=(1, 1_024))
    container_kind: str = pa.Field(
        isin=[
            "nba_api_result_set",
            "nba_api_static_records",
            "nba_api_live_json_array",
            "nba_api_live_json_object",
        ]
    )
    presence: str = pa.Field(
        isin=[
            "present",
            "missing",
            "null",
            "mixed_absent",
            "present_empty",
            "empty_object",
            "empty_array",
            "not_observed_parent_empty",
        ]
    )
    ordered_headers_json: str = pa.Field(str_length=(2, MAX_RESULT_JSON_BYTES))
    ordered_headers_sha256: str = pa.Field(str_matches=_SHA256_PATTERN)
    header_count: int = pa.Field(ge=0)
    row_count: int = pa.Field(ge=0)
    cell_count: int = pa.Field(ge=0)
    node_count: int = pa.Field(ge=0)
    container_count: int = pa.Field(ge=0)
    missing_count: int = pa.Field(ge=0)
    null_count: int = pa.Field(ge=0)
    parent_state_sha256: str | None = pa.Field(
        nullable=True,
        str_matches=_SHA256_PATTERN,
    )
    output_sha256: str = pa.Field(str_matches=_SHA256_PATTERN)
    canonical_route_ids_json: str = pa.Field(str_length=(3, MAX_RESULT_JSON_BYTES))
    canonical_route_ids_sha256: str = pa.Field(str_matches=_SHA256_PATTERN)
    committed_staging_receipts_json: str = pa.Field(str_length=(2, MAX_RESULT_JSON_BYTES))
    committed_staging_receipts_sha256: str = pa.Field(str_matches=_SHA256_PATTERN)
    landing_disposition: str = pa.Field(
        isin=[
            "wide_only",
            "lossless_only",
            "wide_plus_lossless",
            "presence_only",
        ]
    )
    logical_result_receipt_sha256: str = pa.Field(str_matches=_SHA256_PATTERN)
    route_receipt_sha256: str = pa.Field(str_matches=_SHA256_PATTERN)

    @pa.dataframe_check
    @classmethod
    def parent_empty_unobserved_is_exact_live_state(
        cls,
        data: pa.PolarsData,
    ) -> bool:
        """Restrict the parent-empty sentinel without changing other states."""

        zero_counts = pl.all_horizontal(
            [
                pl.col(column_name).eq(0)
                for column_name in (
                    "row_count",
                    "cell_count",
                    "node_count",
                    "container_count",
                    "missing_count",
                    "null_count",
                )
            ]
        )
        valid_parent_empty = (
            pl.col("container_kind").is_in(["nba_api_live_json_array", "nba_api_live_json_object"])
            & pl.col("json_path").is_not_null()
            & pl.col("parent_state_sha256").is_not_null()
            & zero_counts
        )
        return bool(
            data.lazyframe.select(
                pl.col("presence").ne("not_observed_parent_empty").or_(valid_parent_empty).all()
            )
            .collect()
            .item()
        )


class RawNbaApiObservationRouteLandingSchema(_FixedRawAuthoritySchema):
    """One exact response-level route landing for one selected observation."""

    schema_version: int = pa.Field(eq=2)
    landing_sha256: str = pa.Field(str_matches=_SHA256_PATTERN, unique=True)
    observation_sha256: str = pa.Field(str_matches=_SHA256_PATTERN)
    logical_receipt_sha256: str = pa.Field(str_matches=_SHA256_PATTERN)
    route_ordinal: int = pa.Field(ge=0)
    route_id: str = pa.Field(str_matches=_SAFE_ID_PATTERN)
    staging_key: str = pa.Field(str_matches=_SAFE_ID_PATTERN)
    route_authority_kind: str = pa.Field(
        isin=[
            "staging_route_contract_v1",
            "conditional_staging_route_admission_v1",
        ]
    )
    route_authority_sha256: str = pa.Field(str_matches=_SHA256_PATTERN)
    landing_semantic: str = pa.Field(
        isin=[
            "occurrence_bound",
            "conditional_lossless",
            "response_fixed_zero",
            "response_canonical_alias",
        ]
    )
    conditional_lossless: bool
    alias_target_route_id: str | None = pa.Field(
        nullable=True,
        str_matches=_SAFE_ID_PATTERN,
    )
    live_snapshot_at: polars_engine.DateTime | None = pa.Field(
        nullable=True,
        dtype_kwargs=_UTC_US_DTYPE,
    )
    source_occurrence_count: int = pa.Field(ge=0)
    source_occurrences_sha256: str = pa.Field(str_matches=_SHA256_PATTERN)
    committed_receipt_schema_version: int = pa.Field(eq=2)
    committed_receipt_kind: str = pa.Field(eq="committed_staging_chunk_receipt_v2")
    chunk_id: str = pa.Field(str_length=(1, 512))
    canonical_frame_format: str = pa.Field(str_length=(1, 200))
    frame_content_hash_contract: str = pa.Field(str_length=(1, 200))
    frame_schema_hash_contract: str = pa.Field(str_length=(1, 200))
    content_hash: str = pa.Field(str_matches=_SHA256_PATTERN)
    persisted_row_count: int = pa.Field(ge=0)
    persisted_content_sha256: str = pa.Field(str_matches=_SHA256_PATTERN)
    persisted_schema_sha256: str = pa.Field(str_matches=_SHA256_PATTERN)
    logical_call_receipt_sha256: str = pa.Field(str_matches=_SHA256_PATTERN)
    provider_authority_sha256: str = pa.Field(str_matches=_SHA256_PATTERN)
    logical_parameters_sha256: str = pa.Field(str_matches=_SHA256_PATTERN)
    result_route_id: str = pa.Field(str_matches=_SAFE_ID_PATTERN)
    receipt_root_sha256: str = pa.Field(str_matches=_SHA256_PATTERN)

    @pa.dataframe_check
    @classmethod
    def semantic_partition_is_exact(cls, data: pa.PolarsData) -> bool:
        """Keep conditional, alias, and source denominator states disjoint."""

        semantic = pl.col("landing_semantic")
        conditional = semantic.eq("conditional_lossless")
        alias = semantic.eq("response_canonical_alias")
        fixed_zero = semantic.eq("response_fixed_zero")
        occurrence = semantic.eq("occurrence_bound")
        valid = (
            pl.col("conditional_lossless").eq(conditional)
            & pl.col("route_authority_kind")
            .eq("conditional_staging_route_admission_v1")
            .eq(conditional)
            & pl.col("alias_target_route_id").is_not_null().eq(alias)
            & pl.when(occurrence).then(pl.col("source_occurrence_count").gt(0)).otherwise(True)
            & pl.when(fixed_zero | alias)
            .then(pl.col("source_occurrence_count").eq(0))
            .otherwise(True)
        )
        return bool(data.lazyframe.select(valid.all()).collect().item())


__all__ = [
    "RawNbaApiObservationRouteLandingSchema",
    "RawNbaApiParserInputObjectSchema",
    "RawNbaApiRequestObservationSchema",
    "RawNbaApiResultOccurrenceSchema",
]
