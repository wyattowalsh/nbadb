"""Strict public schema for committed W2 operation receipts."""

from __future__ import annotations

import hashlib
import json
from dataclasses import fields
from typing import Final

import pandera.polars as pa

from nbadb.contracts.raw_request_authority import MAX_AUTHORITY_ROWS
from nbadb.contracts.w2_operation import (
    W2_OPERATION_SCHEMA_VERSION,
    W2OperationError,
    W2OperationReceiptV1,
)
from nbadb.schemas.base import BaseSchema

_SHA256_PATTERN: Final = r"^[0-9a-f]{64}$"
_MAX_ORDINAL: Final = (1 << 63) - 1
_MAX_OPERATION_ROWS: Final = 14_000_000

_INTEGER_COLUMNS: Final = frozenset(
    {
        "schema_version",
        *(item.name for item in fields(W2OperationReceiptV1) if item.name.endswith("_count")),
    }
)

RAW_NBA_API_W2_OPERATION_COLUMNS: Final[tuple[str, ...]] = (
    "schema_version",
    *(item.name for item in fields(W2OperationReceiptV1)),
)
RAW_NBA_API_W2_OPERATION_SCHEMA_DESCRIPTOR: Final[tuple[tuple[str, str, bool], ...]] = tuple(
    (name, "int" if name in _INTEGER_COLUMNS else "str", False)
    for name in RAW_NBA_API_W2_OPERATION_COLUMNS
)
RAW_NBA_API_W2_OPERATION_SCHEMA_SHA256: Final = hashlib.sha256(
    json.dumps(
        [list(item) for item in RAW_NBA_API_W2_OPERATION_SCHEMA_DESCRIPTOR],
        allow_nan=False,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
).hexdigest()


class RawNbaApiW2OperationSchema(BaseSchema):
    """One exact bundle-scoped committed W2 operation receipt."""

    schema_version: int = pa.Field(eq=W2_OPERATION_SCHEMA_VERSION)
    operation_receipt_sha256: str = pa.Field(str_matches=_SHA256_PATTERN)
    operation_key_sha256: str = pa.Field(str_matches=_SHA256_PATTERN)
    operation_attempt_count: int = pa.Field(ge=1, le=MAX_AUTHORITY_ROWS)
    operation_attempt_root_sha256: str = pa.Field(str_matches=_SHA256_PATTERN)
    raw_authority_bundle_sha256: str = pa.Field(str_matches=_SHA256_PATTERN)
    committed_staging_readback_count: int = pa.Field(ge=0, le=_MAX_OPERATION_ROWS)
    committed_staging_readback_root_sha256: str = pa.Field(str_matches=_SHA256_PATTERN)
    body_value_projection_receipt_sha256: str = pa.Field(str_matches=_SHA256_PATTERN)
    body_projection_policy_sha256: str = pa.Field(str_matches=_SHA256_PATTERN)
    body_blob_inventory_sha256: str = pa.Field(str_matches=_SHA256_PATTERN)
    body_blob_count: int = pa.Field(ge=0, le=_MAX_OPERATION_ROWS)
    body_blob_root_sha256: str = pa.Field(str_matches=_SHA256_PATTERN)
    body_blob_readback_count: int = pa.Field(ge=0, le=_MAX_OPERATION_ROWS)
    body_blob_readback_root_sha256: str = pa.Field(str_matches=_SHA256_PATTERN)
    body_blob_byte_count: int = pa.Field(ge=0, le=_MAX_ORDINAL)
    parser_input_object_count: int = pa.Field(ge=0, le=_MAX_OPERATION_ROWS)
    parser_input_object_root_sha256: str = pa.Field(str_matches=_SHA256_PATTERN)
    declared_bodyless_authority_sha256: str = pa.Field(str_matches=_SHA256_PATTERN)
    bodyless_packet_count: int = pa.Field(ge=0, le=_MAX_OPERATION_ROWS)
    bodyless_packet_root_sha256: str = pa.Field(str_matches=_SHA256_PATTERN)
    bodyless_readback_count: int = pa.Field(ge=0, le=_MAX_OPERATION_ROWS)
    bodyless_readback_root_sha256: str = pa.Field(str_matches=_SHA256_PATTERN)
    bodyless_packet_byte_count: int = pa.Field(ge=0, le=_MAX_ORDINAL)
    observation_source_count: int = pa.Field(ge=0, le=_MAX_OPERATION_ROWS)
    observation_source_root_sha256: str = pa.Field(str_matches=_SHA256_PATTERN)
    lossless_ownership_receipt_sha256: str = pa.Field(str_matches=_SHA256_PATTERN)
    ownership_observation_count: int = pa.Field(ge=0, le=_MAX_OPERATION_ROWS)
    ownership_observation_root_sha256: str = pa.Field(str_matches=_SHA256_PATTERN)
    ownership_partition_count: int = pa.Field(ge=0, le=_MAX_OPERATION_ROWS)
    ownership_partition_root_sha256: str = pa.Field(str_matches=_SHA256_PATTERN)
    ownership_fixed_zero_landing_root_sha256: str = pa.Field(str_matches=_SHA256_PATTERN)
    ownership_binding_count: int = pa.Field(ge=0, le=_MAX_OPERATION_ROWS)
    ownership_binding_root_sha256: str = pa.Field(str_matches=_SHA256_PATTERN)
    ownership_source_record_count: int = pa.Field(ge=0, le=_MAX_OPERATION_ROWS)
    ownership_source_record_root_sha256: str = pa.Field(str_matches=_SHA256_PATTERN)
    expected_unit_inventory_sha256: str = pa.Field(str_matches=_SHA256_PATTERN)
    expected_unit_count: int = pa.Field(ge=0, le=_MAX_OPERATION_ROWS)
    expected_unit_root_sha256: str = pa.Field(str_matches=_SHA256_PATTERN)
    representation_assignment_count: int = pa.Field(ge=0, le=_MAX_OPERATION_ROWS)
    representation_assignment_root_sha256: str = pa.Field(str_matches=_SHA256_PATTERN)
    route_field_landing_receipt_sha256: str = pa.Field(str_matches=_SHA256_PATTERN)
    route_field_landing_count: int = pa.Field(ge=0, le=_MAX_OPERATION_ROWS)
    route_field_landing_root_sha256: str = pa.Field(str_matches=_SHA256_PATTERN)
    value_projection_plan_sha256: str = pa.Field(str_matches=_SHA256_PATTERN)
    public_table_value_projection_receipt_sha256: str = pa.Field(str_matches=_SHA256_PATTERN)
    value_projection_equality_receipt_sha256: str = pa.Field(str_matches=_SHA256_PATTERN)
    projection_sha256: str = pa.Field(str_matches=_SHA256_PATTERN)
    projection_partition_count: int = pa.Field(ge=0, le=_MAX_OPERATION_ROWS)
    projection_partition_root_sha256: str = pa.Field(str_matches=_SHA256_PATTERN)
    projection_item_count: int = pa.Field(ge=0, le=_MAX_OPERATION_ROWS)
    projection_item_root_sha256: str = pa.Field(str_matches=_SHA256_PATTERN)
    partition_equality_count: int = pa.Field(ge=0, le=_MAX_OPERATION_ROWS)
    partition_equality_root_sha256: str = pa.Field(str_matches=_SHA256_PATTERN)
    item_equality_count: int = pa.Field(ge=0, le=_MAX_OPERATION_ROWS)
    item_equality_root_sha256: str = pa.Field(str_matches=_SHA256_PATTERN)
    equality_root_sha256: str = pa.Field(str_matches=_SHA256_PATTERN)
    result_cell_schema_sha256: str = pa.Field(str_matches=_SHA256_PATTERN)
    result_cell_row_count: int = pa.Field(ge=0, le=_MAX_OPERATION_ROWS)
    result_cell_row_root_sha256: str = pa.Field(str_matches=_SHA256_PATTERN)
    stats_lossless_schema_sha256: str = pa.Field(str_matches=_SHA256_PATTERN)
    stats_lossless_row_count: int = pa.Field(ge=0, le=_MAX_OPERATION_ROWS)
    stats_lossless_row_root_sha256: str = pa.Field(str_matches=_SHA256_PATTERN)
    live_lossless_schema_sha256: str = pa.Field(str_matches=_SHA256_PATTERN)
    live_lossless_row_count: int = pa.Field(ge=0, le=_MAX_OPERATION_ROWS)
    live_lossless_row_root_sha256: str = pa.Field(str_matches=_SHA256_PATTERN)
    value_representation_schema_sha256: str = pa.Field(str_matches=_SHA256_PATTERN)
    value_representation_row_count: int = pa.Field(ge=0, le=_MAX_OPERATION_ROWS)
    value_representation_row_root_sha256: str = pa.Field(str_matches=_SHA256_PATTERN)
    route_field_landing_schema_sha256: str = pa.Field(str_matches=_SHA256_PATTERN)
    route_field_landing_row_count: int = pa.Field(ge=0, le=_MAX_OPERATION_ROWS)
    route_field_landing_row_root_sha256: str = pa.Field(str_matches=_SHA256_PATTERN)
    w2_operation_schema_sha256: str = pa.Field(
        eq=RAW_NBA_API_W2_OPERATION_SCHEMA_SHA256,
        str_matches=_SHA256_PATTERN,
    )

    @pa.dataframe_check
    @classmethod
    def exact_receipt_replay_and_unique_identities(cls, data: pa.PolarsData) -> bool:
        try:
            frame = data.lazyframe.collect()
            if frame.height > _MAX_OPERATION_ROWS:
                return False
            operation_keys: set[str] = set()
            operation_receipts: set[str] = set()
            for row in frame.iter_rows(named=True):
                operation_key = row["operation_key_sha256"]
                operation_receipt = row["operation_receipt_sha256"]
                if type(operation_key) is not str or type(operation_receipt) is not str:
                    return False
                if operation_key in operation_keys or operation_receipt in operation_receipts:
                    return False
                W2OperationReceiptV1.from_row(
                    row,
                    expected_operation_receipt_sha256=operation_receipt,
                    expected_operation_key_sha256=operation_key,
                    expected_raw_authority_bundle_sha256=row["raw_authority_bundle_sha256"],
                    expected_w2_operation_schema_sha256=(RAW_NBA_API_W2_OPERATION_SCHEMA_SHA256),
                )
                operation_keys.add(operation_key)
                operation_receipts.add(operation_receipt)
        except (W2OperationError, TypeError, ValueError, UnicodeError, RecursionError):
            raise ValueError("W2 operation table failed exact receipt replay") from None
        return True

    class Config:
        coerce = False
        strict = True
        ordered = True


__all__ = [
    "RAW_NBA_API_W2_OPERATION_COLUMNS",
    "RAW_NBA_API_W2_OPERATION_SCHEMA_DESCRIPTOR",
    "RAW_NBA_API_W2_OPERATION_SCHEMA_SHA256",
    "RawNbaApiW2OperationSchema",
]
