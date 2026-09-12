"""Strict public schema for value-free route-field landing bindings."""

from __future__ import annotations

import pandera.polars as pa

from nbadb.contracts.public_value_types import (
    EXPECTED_VALUE_UNIT_KINDS_V1,
    MAX_PUBLIC_VALUE_EXPECTED_UNITS,
    PUBLIC_VALUE_AUTHORITY_SCHEMA_VERSION,
    PUBLIC_VALUE_REPRESENTATION_KINDS_V1,
    PUBLIC_VALUE_SOURCE_INPUT_KINDS_V1,
)
from nbadb.contracts.route_field_landing_authority import (
    MAX_ROUTE_FIELD_LANDING_FIELDS,
    MAX_ROUTE_FIELD_LANDING_RECEIPTS,
    MAX_ROUTE_FIELD_LANDING_ROWS,
    RawNbaApiRouteFieldLandingV1,
    RouteFieldLandingAuthorityError,
)
from nbadb.schemas.base import BaseSchema

_SHA256_PATTERN = r"^[0-9a-f]{64}$"


class RawNbaApiRouteFieldLandingSchema(BaseSchema):
    """One exact unit × route-field binding or zero-field sentinel."""

    schema_version: int = pa.Field(eq=PUBLIC_VALUE_AUTHORITY_SCHEMA_VERSION)
    landing_field_sha256: str = pa.Field(str_matches=_SHA256_PATTERN, unique=True)
    landing_field_ordinal: int = pa.Field(ge=0, lt=MAX_ROUTE_FIELD_LANDING_ROWS)
    route_receipt_ordinal: int = pa.Field(ge=0, lt=MAX_ROUTE_FIELD_LANDING_RECEIPTS)
    raw_authority_bundle_sha256: str = pa.Field(str_matches=_SHA256_PATTERN)
    route_landing_receipt_sha256: str = pa.Field(str_matches=_SHA256_PATTERN)
    raw_route_landing_sha256: str = pa.Field(str_matches=_SHA256_PATTERN)
    observation_sha256: str = pa.Field(str_matches=_SHA256_PATTERN)
    route_ordinal: int = pa.Field(ge=0, lt=MAX_ROUTE_FIELD_LANDING_RECEIPTS)
    route_id: str = pa.Field(str_length=(1, 512))
    staging_key: str = pa.Field(str_length=(1, 512))
    unit_sha256: str = pa.Field(str_matches=_SHA256_PATTERN)
    unit_ordinal: int = pa.Field(ge=0, lt=MAX_PUBLIC_VALUE_EXPECTED_UNITS)
    unit_kind: str = pa.Field(isin=EXPECTED_VALUE_UNIT_KINDS_V1)
    occurrence_sha256: str | None = pa.Field(nullable=True, str_matches=_SHA256_PATTERN)
    occurrence_ordinal: int | None = pa.Field(
        nullable=True, ge=0, lt=MAX_PUBLIC_VALUE_EXPECTED_UNITS
    )
    assignment_sha256: str = pa.Field(str_matches=_SHA256_PATTERN)
    source_input_kind: str = pa.Field(isin=PUBLIC_VALUE_SOURCE_INPUT_KINDS_V1)
    representation_kind: str = pa.Field(isin=PUBLIC_VALUE_REPRESENTATION_KINDS_V1)
    row_kind: str = pa.Field(isin=["field_binding", "route_only"])
    field_ordinal: int | None = pa.Field(nullable=True, ge=0, lt=MAX_ROUTE_FIELD_LANDING_FIELDS)
    field_name: str | None = pa.Field(nullable=True, str_length=(1, 1_024))
    field_authority_sha256: str | None = pa.Field(nullable=True, str_matches=_SHA256_PATTERN)
    field_origin: str | None = pa.Field(
        nullable=True,
        isin=["provider_bound", "provider_multi_bound", "lossless_bound", "storage_only"],
    )
    logical_type_sha256: str | None = pa.Field(nullable=True, str_matches=_SHA256_PATTERN)

    @pa.dataframe_check
    @classmethod
    def exact_rows_replay_and_ordinals_are_contiguous(cls, data: pa.PolarsData) -> bool:
        try:
            frame = data.lazyframe.collect()
            seen_bundle_ordinals: set[tuple[str, int]] = set()
            next_ordinal_by_bundle: dict[str, int] = {}
            for row in frame.iter_rows(named=True):
                parsed = RawNbaApiRouteFieldLandingV1.from_row(row)
                bundle_sha256 = parsed.raw_authority_bundle_sha256
                bundle_ordinal = (bundle_sha256, parsed.landing_field_ordinal)
                if (
                    bundle_ordinal in seen_bundle_ordinals
                    or parsed.landing_field_ordinal != next_ordinal_by_bundle.get(bundle_sha256, 0)
                ):
                    return False
                seen_bundle_ordinals.add(bundle_ordinal)
                next_ordinal_by_bundle[bundle_sha256] = parsed.landing_field_ordinal + 1
        except (
            RouteFieldLandingAuthorityError,
            TypeError,
            ValueError,
            UnicodeError,
            RecursionError,
        ):
            raise ValueError(
                "route-field landing table failed exact value-free row replay"
            ) from None
        return True

    class Config:
        coerce = False
        strict = True
        ordered = True


__all__ = ["RawNbaApiRouteFieldLandingSchema"]
