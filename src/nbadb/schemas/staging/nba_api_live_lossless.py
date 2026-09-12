"""Fixed staging contract for receipt-bound ``nba_api`` live JSON nodes."""

from __future__ import annotations

import datetime as dt  # noqa: TC003

import pandera.polars as pa
from pandera.engines import polars_engine  # noqa: TC002

from nbadb.schemas.base import BaseSchema


class StagingNbaApiLiveLosslessNodesSchema(BaseSchema):
    """Ordered, replayable node projection of one captured live response."""

    response_receipt_sha256: str = pa.Field(str_matches=r"^[0-9a-f]{64}$")
    provider_authority_sha256: str = pa.Field(str_matches=r"^[0-9a-f]{64}$")
    endpoint_contract_sha256: str = pa.Field(str_matches=r"^[0-9a-f]{64}$")
    endpoint_id: str
    endpoint_slug: str
    request_parameters_json: str
    snapshot_at: polars_engine.DateTime = pa.Field(
        dtype_kwargs={
            "time_zone_agnostic": False,
            "time_zone": "UTC",
            "time_unit": "us",
        }
    )
    snapshot_date: dt.date
    record_kind: str = pa.Field(isin=["result_set_declaration", "json_node"])
    result_set_name: str | None = pa.Field(nullable=True)
    result_set_ordinal: int | None = pa.Field(nullable=True, ge=0)
    result_set_occurrence: int | None = pa.Field(nullable=True, ge=0)
    result_set_row_ordinal: int | None = pa.Field(nullable=True, ge=0)
    contract_json_path: str | None = pa.Field(nullable=True)
    container_kind: str | None = pa.Field(nullable=True)
    node_ordinal: int | None = pa.Field(nullable=True, ge=0)
    parent_node_ordinal: int | None = pa.Field(nullable=True, ge=0)
    json_path: str | None = pa.Field(nullable=True)
    parent_json_path: str | None = pa.Field(nullable=True)
    depth: int | None = pa.Field(nullable=True, ge=0)
    object_key: str | None = pa.Field(nullable=True)
    object_key_ordinal: int | None = pa.Field(nullable=True, ge=0)
    contract_field_ordinal: int | None = pa.Field(nullable=True, ge=0)
    array_ordinal: int | None = pa.Field(nullable=True, ge=0)
    presence_kind: str = pa.Field(
        isin=["declared", "present", "null", "empty_object", "empty_array", "missing"]
    )
    value_kind: str | None = pa.Field(
        nullable=True,
        isin=["object", "array", "null", "boolean", "integer", "number", "string", "missing"],
    )
    canonical_json: str | None = pa.Field(nullable=True)
    known_contract_field: bool | None = pa.Field(nullable=True)
    anomaly_codes_json: str


__all__ = ["StagingNbaApiLiveLosslessNodesSchema"]
