"""Strict public schemas for normalized live sealed-plan authority."""

from __future__ import annotations

import pandera.polars as pa
from pandera.engines import polars_engine  # noqa: TC002

from nbadb.contracts.raw_live_plan_authority import MAX_LIVE_PLAN_BYTES
from nbadb.schemas.base import BaseSchema

_SHA256_PATTERN = r"^[0-9a-f]{64}$"
_GIT_SHA_PATTERN = r"^[0-9a-f]{40}$"
_SAFE_ID_PATTERN = r"^[A-Za-z0-9_][A-Za-z0-9_.:-]{0,511}$"
_UTC_US_DTYPE = {
    "time_zone_agnostic": False,
    "time_zone": "UTC",
    "time_unit": "us",
}


class _FixedLivePlanSchema(BaseSchema):
    class Config:
        coerce = False
        strict = True
        ordered = True


class RawNbaApiLivePlanGenerationReceiptSchema(_FixedLivePlanSchema):
    schema_version: int = pa.Field(eq=2)
    generation_receipt_sha256: str = pa.Field(str_matches=_SHA256_PATTERN, unique=True)
    generation_id: str = pa.Field(str_matches=_SAFE_ID_PATTERN, unique=True)
    generation_kind: str = pa.Field(
        isin=[
            "full_root",
            "full_derived_game_fanout",
            "successor_wave_0",
            "successor_wave_1",
            "successor_update",
        ]
    )
    parent_generation_receipt_sha256: str | None = pa.Field(
        nullable=True,
        str_matches=_SHA256_PATTERN,
    )
    parent_capture_root_sha256: str | None = pa.Field(
        nullable=True,
        str_matches=_SHA256_PATTERN,
    )
    sealed_plan_bytes: bytes
    sealed_plan_sha256: str = pa.Field(str_matches=_SHA256_PATTERN)
    sealed_plan_length: int = pa.Field(ge=1, le=MAX_LIVE_PLAN_BYTES)
    plan_item_count: int = pa.Field(ge=1, le=1_000_000)
    plan_items_sha256: str = pa.Field(str_matches=_SHA256_PATTERN)
    source_sha: str = pa.Field(str_matches=_GIT_SHA_PATTERN)
    producing_head_sha: str = pa.Field(str_matches=_GIT_SHA_PATTERN)
    workflow_path: str = pa.Field(str_length=(1, 1_024))
    workflow_content_sha256: str = pa.Field(str_matches=_SHA256_PATTERN)
    run_id: int = pa.Field(ge=1)
    run_attempt: int = pa.Field(ge=1)
    chain_id: str = pa.Field(str_matches=_SAFE_ID_PATTERN)
    producer_job_id: int = pa.Field(ge=1)
    producer_job_name_sha256: str = pa.Field(str_matches=_SHA256_PATTERN)
    runner_identity_sha256: str = pa.Field(str_matches=_SHA256_PATTERN)
    matrix_lane_id: str = pa.Field(str_matches=_SAFE_ID_PATTERN)
    operation: str = pa.Field(str_matches=_SAFE_ID_PATTERN)
    nonce_sha256: str = pa.Field(str_matches=_SHA256_PATTERN)
    artifact_id: int = pa.Field(ge=1)
    artifact_name: str = pa.Field(str_matches=_SAFE_ID_PATTERN)
    artifact_digest_sha256: str = pa.Field(str_matches=_SHA256_PATTERN)
    artifact_size: int = pa.Field(ge=1)
    artifact_archive_url_sha256: str = pa.Field(str_matches=_SHA256_PATTERN)
    artifact_expires_at: polars_engine.DateTime = pa.Field(dtype_kwargs=_UTC_US_DTYPE)
    member_path: str = pa.Field(str_length=(1, 1_024))
    member_sha256: str = pa.Field(str_matches=_SHA256_PATTERN)
    member_length: int = pa.Field(ge=1)
    collector_receipt_sha256: str = pa.Field(str_matches=_SHA256_PATTERN)
    external_receipt_sha256: str = pa.Field(str_matches=_SHA256_PATTERN)
    live_snapshot_at: polars_engine.DateTime = pa.Field(dtype_kwargs=_UTC_US_DTYPE)
    generated_at: polars_engine.DateTime = pa.Field(dtype_kwargs=_UTC_US_DTYPE)


class RawNbaApiLivePlanCallAdmissionSchema(_FixedLivePlanSchema):
    schema_version: int = pa.Field(eq=2)
    admission_receipt_sha256: str = pa.Field(str_matches=_SHA256_PATTERN, unique=True)
    plan_generation_receipt_sha256: str = pa.Field(str_matches=_SHA256_PATTERN)
    plan_item_ordinal: int = pa.Field(ge=0)
    plan_item_sha256: str = pa.Field(str_matches=_SHA256_PATTERN)
    observation_sha256: str = pa.Field(str_matches=_SHA256_PATTERN, unique=True)
    semantic_request_sha256: str = pa.Field(str_matches=_SHA256_PATTERN)
    logical_invocation_sha256: str = pa.Field(str_matches=_SHA256_PATTERN)
    provider_call_sha256: str = pa.Field(str_matches=_SHA256_PATTERN)
    source_sha: str = pa.Field(str_matches=_GIT_SHA_PATTERN)
    run_id: int = pa.Field(ge=1)
    run_attempt: int = pa.Field(ge=1)
    chain_id: str = pa.Field(str_matches=_SAFE_ID_PATTERN)
    lane_id: str = pa.Field(str_matches=_SAFE_ID_PATTERN)
    scope_sha256: str = pa.Field(str_matches=_SHA256_PATTERN)
    safe_parameters_sha256: str = pa.Field(str_matches=_SHA256_PATTERN)
    endpoint_id: str = pa.Field(str_matches=_SAFE_ID_PATTERN)
    endpoint_contract_sha256: str = pa.Field(str_matches=_SHA256_PATTERN)
    provider_authority_sha256: str = pa.Field(str_matches=_SHA256_PATTERN)
    route_ids_json: str = pa.Field(str_length=(3, MAX_LIVE_PLAN_BYTES))
    route_ids_sha256: str = pa.Field(str_matches=_SHA256_PATTERN)
    route_count: int = pa.Field(ge=1, le=4_096)
    live_snapshot_at: polars_engine.DateTime = pa.Field(dtype_kwargs=_UTC_US_DTYPE)
    issued_at: polars_engine.DateTime = pa.Field(dtype_kwargs=_UTC_US_DTYPE)
    authorized_at: polars_engine.DateTime = pa.Field(dtype_kwargs=_UTC_US_DTYPE)
    expires_at: polars_engine.DateTime = pa.Field(dtype_kwargs=_UTC_US_DTYPE)
    authorization_collector_receipt_sha256: str = pa.Field(str_matches=_SHA256_PATTERN)
    authorization_receipt_sha256: str = pa.Field(str_matches=_SHA256_PATTERN)


class RawNbaApiObservationLivePlanSchema(_FixedLivePlanSchema):
    schema_version: int = pa.Field(eq=2)
    binding_receipt_sha256: str = pa.Field(str_matches=_SHA256_PATTERN, unique=True)
    observation_sha256: str = pa.Field(str_matches=_SHA256_PATTERN, unique=True)
    observation_record_sha256: str = pa.Field(str_matches=_SHA256_PATTERN, unique=True)
    plan_generation_receipt_sha256: str = pa.Field(str_matches=_SHA256_PATTERN)
    plan_admission_receipt_sha256: str = pa.Field(str_matches=_SHA256_PATTERN, unique=True)
    live_plan_authority_sha256: str = pa.Field(str_matches=_SHA256_PATTERN, unique=True)
    plan_item_ordinal: int = pa.Field(ge=0)
    plan_item_sha256: str = pa.Field(str_matches=_SHA256_PATTERN)
    semantic_request_sha256: str = pa.Field(str_matches=_SHA256_PATTERN)
    logical_invocation_sha256: str = pa.Field(str_matches=_SHA256_PATTERN)
    provider_call_sha256: str = pa.Field(str_matches=_SHA256_PATTERN)
    logical_receipt_sha256: str = pa.Field(str_matches=_SHA256_PATTERN)
    capture_response_receipt_sha256: str = pa.Field(str_matches=_SHA256_PATTERN)
    source_sha: str = pa.Field(str_matches=_GIT_SHA_PATTERN)
    run_id: int = pa.Field(ge=1)
    run_attempt: int = pa.Field(ge=1)
    chain_id: str = pa.Field(str_matches=_SAFE_ID_PATTERN)
    lane_id: str = pa.Field(str_matches=_SAFE_ID_PATTERN)
    scope_sha256: str = pa.Field(str_matches=_SHA256_PATTERN)
    safe_parameters_sha256: str = pa.Field(str_matches=_SHA256_PATTERN)
    endpoint_id: str = pa.Field(str_matches=_SAFE_ID_PATTERN)
    endpoint_contract_sha256: str = pa.Field(str_matches=_SHA256_PATTERN)
    provider_authority_sha256: str = pa.Field(str_matches=_SHA256_PATTERN)
    route_ids_json: str = pa.Field(str_length=(3, MAX_LIVE_PLAN_BYTES))
    route_ids_sha256: str = pa.Field(str_matches=_SHA256_PATTERN)
    route_count: int = pa.Field(ge=1, le=4_096)
    landing_sha256s_json: str = pa.Field(str_length=(3, MAX_LIVE_PLAN_BYTES))
    landing_sha256s_sha256: str = pa.Field(str_matches=_SHA256_PATTERN)
    landing_receipt_roots_json: str = pa.Field(str_length=(3, MAX_LIVE_PLAN_BYTES))
    landing_receipt_roots_sha256: str = pa.Field(str_matches=_SHA256_PATTERN)
    landing_count: int = pa.Field(ge=1, le=4_096)
    landing_authority_sha256: str = pa.Field(str_matches=_SHA256_PATTERN)
    live_snapshot_at: polars_engine.DateTime = pa.Field(dtype_kwargs=_UTC_US_DTYPE)


__all__ = [
    "RawNbaApiLivePlanCallAdmissionSchema",
    "RawNbaApiLivePlanGenerationReceiptSchema",
    "RawNbaApiObservationLivePlanSchema",
]
