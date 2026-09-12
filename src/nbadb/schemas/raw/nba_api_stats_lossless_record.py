"""Strict public schemas for declared-stats lossless value authority V1."""

from __future__ import annotations

import pandera.polars as pa
import polars as pl

from nbadb.contracts.stats_lossless_value_authority import (
    MAX_STATS_LOSSLESS_CANONICAL_BYTES,
    MAX_STATS_LOSSLESS_HEADERS,
    MAX_STATS_LOSSLESS_RECORDS,
    MAX_STATS_LOSSLESS_RESULTS,
    MAX_STATS_LOSSLESS_ROWS,
    PUBLIC_VALUE_AUTHORITY_SCHEMA_VERSION,
    RESPONSE_LOSSLESS_REPRESENTATION_KIND,
    STATS_LOSSLESS_REPRESENTATION_KIND,
    StatsLosslessRecordV1,
    StatsLosslessValueAuthorityError,
)
from nbadb.schemas.base import BaseSchema

_SHA256_PATTERN = r"^[0-9a-f]{64}$"
_PRESENCE_KINDS = ["present", "null", "empty_object", "empty_array"]
_VALUE_KINDS = ["null", "boolean", "integer", "number", "string", "array", "object"]
_RECORD_KINDS = [
    "response",
    "json_node",
    "result_set",
    "missing_expected",
    "raw_headers",
    "raw_rows",
    "header",
    "row",
    "cell",
]
_PER_RESULT_ANOMALY_BYTES = MAX_STATS_LOSSLESS_CANONICAL_BYTES


def _bounded_utf8(data: pa.PolarsData, columns: tuple[str, ...]) -> bool:
    expressions = []
    for column in columns:
        expressions.append(
            pl.col(column)
            .is_null()
            .or_(pl.col(column).str.len_bytes().is_between(1, MAX_STATS_LOSSLESS_CANONICAL_BYTES))
            .all()
            .alias(column)
        )
    return bool(data.lazyframe.select(expressions).collect().row(0) == (True,) * len(columns))


class _StrictPublicSchema(BaseSchema):
    class Config:
        coerce = False
        strict = True
        ordered = True


class RawNbaApiStatsLosslessRecordSchema(_StrictPublicSchema):
    """One exact occurrence-owned or response-residual stats record."""

    schema_version: int = pa.Field(eq=PUBLIC_VALUE_AUTHORITY_SCHEMA_VERSION)
    record_sha256: str = pa.Field(str_matches=_SHA256_PATTERN, unique=True)
    source_row_sha256: str = pa.Field(str_matches=_SHA256_PATTERN)
    representation_kind: str = pa.Field(
        isin=[STATS_LOSSLESS_REPRESENTATION_KIND, RESPONSE_LOSSLESS_REPRESENTATION_KIND]
    )
    owner_kind: str = pa.Field(isin=["result_occurrence", "response_residual"])
    raw_authority_bundle_sha256: str = pa.Field(str_matches=_SHA256_PATTERN)
    observation_record_sha256: str = pa.Field(str_matches=_SHA256_PATTERN)
    observation_sha256: str = pa.Field(str_matches=_SHA256_PATTERN)
    occurrence_sha256: str | None = pa.Field(nullable=True, str_matches=_SHA256_PATTERN)
    route_id: str = pa.Field(str_length=(1, 512))
    route_authority_sha256: str = pa.Field(str_matches=_SHA256_PATTERN)
    committed_receipt_sha256: str = pa.Field(str_matches=_SHA256_PATTERN)
    response_receipt_sha256: str = pa.Field(str_matches=_SHA256_PATTERN)
    provider_authority_sha256: str = pa.Field(str_matches=_SHA256_PATTERN)
    endpoint_contract_sha256: str = pa.Field(str_matches=_SHA256_PATTERN)
    response_mode_authority_sha256: str = pa.Field(str_matches=_SHA256_PATTERN)
    parser_input_sha256: str = pa.Field(str_matches=_SHA256_PATTERN)
    canonical_payload_sha256: str = pa.Field(str_matches=_SHA256_PATTERN)
    parameters_sha256: str = pa.Field(str_matches=_SHA256_PATTERN)
    endpoint_id: str = pa.Field(str_length=(1, 512))
    endpoint_slug: str = pa.Field(str_length=(1, 512))
    response_state: str = pa.Field(
        isin=[
            "missing_result_envelope",
            "unknown_result_envelope",
            "generic_nested_json",
            "legacy_present_empty",
            "legacy_present_nonempty",
        ]
    )
    legacy_envelope_name: str | None = pa.Field(nullable=True, str_length=(1, 256))
    global_record_ordinal: int = pa.Field(ge=0, lt=MAX_STATS_LOSSLESS_RECORDS)
    occurrence_record_ordinal: int | None = pa.Field(
        nullable=True,
        ge=0,
        lt=MAX_STATS_LOSSLESS_RECORDS,
    )
    response_record_ordinal: int | None = pa.Field(
        nullable=True,
        ge=0,
        lt=MAX_STATS_LOSSLESS_RECORDS,
    )
    record_kind: str = pa.Field(isin=_RECORD_KINDS)
    result_set_name: str | None = pa.Field(nullable=True, str_length=(1, 256))
    result_set_occurrence: int | None = pa.Field(
        nullable=True,
        ge=0,
        lt=MAX_STATS_LOSSLESS_RESULTS,
    )
    provider_result_ordinal: int | None = pa.Field(
        nullable=True,
        ge=0,
        lt=MAX_STATS_LOSSLESS_RESULTS,
    )
    expected_result_ordinal: int | None = pa.Field(
        nullable=True,
        ge=0,
        lt=MAX_STATS_LOSSLESS_RESULTS,
    )
    canonical_result_ordinal: int | None = pa.Field(
        nullable=True,
        ge=0,
        lt=MAX_STATS_LOSSLESS_RESULTS,
    )
    header_name: str | None = pa.Field(nullable=True, str_length=(0, 1_024))
    header_ordinal: int | None = pa.Field(nullable=True, ge=0, lt=MAX_STATS_LOSSLESS_HEADERS)
    row_ordinal: int | None = pa.Field(nullable=True, ge=0, lt=MAX_STATS_LOSSLESS_ROWS)
    node_ordinal: int | None = pa.Field(
        nullable=True,
        ge=0,
        lt=MAX_STATS_LOSSLESS_RECORDS,
    )
    parent_node_ordinal: int | None = pa.Field(
        nullable=True,
        ge=0,
        lt=MAX_STATS_LOSSLESS_RECORDS,
    )
    json_path: str | None = pa.Field(nullable=True, str_length=(1, 4_096))
    parent_json_path: str | None = pa.Field(nullable=True, str_length=(1, 4_096))
    depth: int | None = pa.Field(nullable=True, ge=0, le=64)
    object_key: str | None = pa.Field(nullable=True, str_length=(0, 1_024))
    object_key_ordinal: int | None = pa.Field(
        nullable=True,
        ge=0,
        lt=MAX_STATS_LOSSLESS_RECORDS,
    )
    array_ordinal: int | None = pa.Field(
        nullable=True,
        ge=0,
        lt=MAX_STATS_LOSSLESS_RECORDS,
    )
    presence_kind: str | None = pa.Field(nullable=True, isin=_PRESENCE_KINDS)
    value_kind: str | None = pa.Field(nullable=True, isin=_VALUE_KINDS)
    canonical_json: str | None = pa.Field(
        nullable=True,
        str_length=(1, MAX_STATS_LOSSLESS_CANONICAL_BYTES),
    )
    canonical_json_sha256: str | None = pa.Field(
        nullable=True,
        str_matches=_SHA256_PATTERN,
    )
    global_anomaly_codes_json: str = pa.Field(str_length=(1, _PER_RESULT_ANOMALY_BYTES))
    global_anomaly_codes_sha256: str = pa.Field(str_matches=_SHA256_PATTERN)

    @pa.dataframe_check
    @classmethod
    def canonical_json_utf8_bytes_are_bounded(cls, data: pa.PolarsData) -> bool:
        return _bounded_utf8(data, ("canonical_json", "global_anomaly_codes_json"))

    @pa.dataframe_check
    @classmethod
    def exact_public_rows_are_secret_safe(cls, data: pa.PolarsData) -> bool:
        try:
            frame = data.lazyframe.collect()
            if frame.height > MAX_STATS_LOSSLESS_RECORDS:
                return False
            for row in frame.iter_rows(named=True):
                StatsLosslessRecordV1.from_row(row)
        except (
            StatsLosslessValueAuthorityError,
            TypeError,
            ValueError,
            UnicodeError,
            RecursionError,
        ):
            raise ValueError(
                "stats-lossless public record failed the no-echo safety gate"
            ) from None
        return True


__all__ = [
    "RawNbaApiStatsLosslessRecordSchema",
]
