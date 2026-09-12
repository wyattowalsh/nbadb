"""Strict public schema for Public Value Authority V1 assignments."""

from __future__ import annotations

import pandera.polars as pa

from nbadb.contracts.public_value_types import (
    MAX_PUBLIC_VALUE_EXPECTED_UNITS,
    PUBLIC_VALUE_AUTHORITY_SCHEMA_VERSION,
    PUBLIC_VALUE_REPRESENTATION_KINDS_V1,
    PUBLIC_VALUE_SOURCE_INPUT_KINDS_V1,
    PublicValueTypesError,
    ValueRepresentationAssignmentV1,
)
from nbadb.schemas.base import BaseSchema

_SHA256_PATTERN = r"^[0-9a-f]{64}$"


class RawNbaApiValueRepresentationSchema(BaseSchema):
    """One value-free, exact-unit-to-representation assignment."""

    schema_version: int = pa.Field(eq=PUBLIC_VALUE_AUTHORITY_SCHEMA_VERSION)
    assignment_sha256: str = pa.Field(str_matches=_SHA256_PATTERN, unique=True)
    raw_authority_bundle_sha256: str = pa.Field(str_matches=_SHA256_PATTERN)
    unit_sha256: str = pa.Field(str_matches=_SHA256_PATTERN, unique=True)
    unit_ordinal: int = pa.Field(ge=0, lt=MAX_PUBLIC_VALUE_EXPECTED_UNITS)
    source_input_kind: str = pa.Field(isin=PUBLIC_VALUE_SOURCE_INPUT_KINDS_V1)
    representation_kind: str = pa.Field(isin=PUBLIC_VALUE_REPRESENTATION_KINDS_V1)

    @pa.dataframe_check
    @classmethod
    def exact_assignment_rows_replay(cls, data: pa.PolarsData) -> bool:
        try:
            frame = data.lazyframe.collect()
            seen_bundle_ordinals: set[tuple[str, int]] = set()
            next_ordinal_by_bundle: dict[str, int] = {}
            for row in frame.iter_rows(named=True):
                assignment = ValueRepresentationAssignmentV1.from_row(row)
                bundle_sha256 = assignment.raw_authority_bundle_sha256
                bundle_ordinal = (bundle_sha256, assignment.unit_ordinal)
                if (
                    bundle_ordinal in seen_bundle_ordinals
                    or assignment.unit_ordinal != next_ordinal_by_bundle.get(bundle_sha256, 0)
                ):
                    return False
                seen_bundle_ordinals.add(bundle_ordinal)
                next_ordinal_by_bundle[bundle_sha256] = assignment.unit_ordinal + 1
        except (
            PublicValueTypesError,
            TypeError,
            ValueError,
            UnicodeError,
            RecursionError,
        ):
            raise ValueError(
                "public value-representation row failed exact semantic replay"
            ) from None
        return True

    class Config:
        coerce = False
        strict = True
        ordered = True


__all__ = ["RawNbaApiValueRepresentationSchema"]
