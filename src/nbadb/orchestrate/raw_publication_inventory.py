"""Private inventory for the exact-four Raw Authority V2 relations.

The four relations in this module carry provider response bodies or the exact
bindings needed to reconstruct them.  They are private capture/assurance
state, never public publication resources.  The legacy publication API is
retained only because checked-in metadata/model diagnostics still import it;
it returns an empty tuple so those consumers cannot accidentally republish the
private namespace while their owning waves migrate to explicit disposition.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import TYPE_CHECKING, Final

from nbadb.schemas.raw.nba_api_authority import (
    RawNbaApiObservationRouteLandingSchema,
    RawNbaApiParserInputObjectSchema,
    RawNbaApiRequestObservationSchema,
    RawNbaApiResultOccurrenceSchema,
)
from nbadb.schemas.registry import get_input_schema

if TYPE_CHECKING:
    import pandera.polars as pa

__all__ = [
    "PRIVATE_RAW_REQUEST_AUTHORITY_TABLE_NAMES",
    "RAW_REQUEST_AUTHORITY_CATEGORY",
    "RAW_REQUEST_AUTHORITY_PRIVATE_CATEGORY",
    "RawRequestAuthorityPrivateTable",
    "RawRequestAuthorityPublicationTable",
    "raw_request_authority_private_tables",
    "raw_request_authority_publication_tables",
]

RAW_REQUEST_AUTHORITY_PRIVATE_CATEGORY: Final = "raw_request_authority_private"
# Legacy category key kept import-compatible until W2.5 removes it from
# metadata.  It contains no tables and confers no publication authority.
RAW_REQUEST_AUTHORITY_CATEGORY: Final = "raw_request_authority"
_RAW_TABLE_RE: Final = re.compile(r"raw_[a-z0-9_]+\Z", flags=re.ASCII)

PRIVATE_RAW_REQUEST_AUTHORITY_TABLE_NAMES: Final = (
    "raw_nba_api_parser_input_object",
    "raw_nba_api_request_observation",
    "raw_nba_api_result_occurrence",
    "raw_nba_api_observation_route_landing",
)


@dataclass(frozen=True, slots=True)
class RawRequestAuthorityPrivateTable:
    """One exact private Raw Authority V2 relation and its strict schema."""

    table_name: str
    schema_type: type[pa.DataFrameModel]
    description: str
    contains_provider_body_authority: bool = True


# Import compatibility for the checked-in model-census module.  The public
# inventory function below is deliberately empty, so the alias cannot make a
# relation public.
RawRequestAuthorityPublicationTable = RawRequestAuthorityPrivateTable

_SCHEMA_DESCRIPTIONS: dict[type[pa.DataFrameModel], str] = {
    RawNbaApiParserInputObjectSchema: (
        "Private content-addressed UTF-8 provider parser-input bodies with bounded "
        "storage and exact representation digests."
    ),
    RawNbaApiRequestObservationSchema: (
        "Private request-attempt observations bound to exact provider body authority."
    ),
    RawNbaApiResultOccurrenceSchema: (
        "Private duplicate-preserving result occurrences needed for body reconstruction."
    ),
    RawNbaApiObservationRouteLandingSchema: (
        "Private response-to-route landing authority joining observations, occurrences, "
        "and committed staging receipts."
    ),
}

_SCHEMA_ORDER: tuple[type[pa.DataFrameModel], ...] = (
    RawNbaApiParserInputObjectSchema,
    RawNbaApiRequestObservationSchema,
    RawNbaApiResultOccurrenceSchema,
    RawNbaApiObservationRouteLandingSchema,
)


def raw_request_authority_private_tables() -> tuple[RawRequestAuthorityPrivateTable, ...]:
    """Return the exact store/schema-backed private Raw Authority V2 inventory."""

    from nbadb.orchestrate.raw_request_store import RAW_REQUEST_AUTHORITY_TABLES

    table_names = RAW_REQUEST_AUTHORITY_TABLES
    if (
        type(table_names) is not tuple
        or table_names != PRIVATE_RAW_REQUEST_AUTHORITY_TABLE_NAMES
        or len(table_names) != len(set(table_names))
        or any(
            type(name) is not str or _RAW_TABLE_RE.fullmatch(name) is None for name in table_names
        )
    ):
        raise RuntimeError("private raw request-authority store inventory is malformed")

    entries: list[RawRequestAuthorityPrivateTable] = []
    for table_name, expected_schema_type in zip(table_names, _SCHEMA_ORDER, strict=True):
        schema_type = get_input_schema(table_name)
        if schema_type is not expected_schema_type:
            raise RuntimeError(
                f"private raw request-authority store/schema identity drifted: {table_name}"
            )
        config = schema_type.Config
        if (
            config.strict is not True
            or config.coerce is not False
            or getattr(config, "ordered", None) is not True
        ):
            raise RuntimeError("private raw request-authority schema is not strict and ordered")
        entries.append(
            RawRequestAuthorityPrivateTable(
                table_name=table_name,
                schema_type=schema_type,
                description=_SCHEMA_DESCRIPTIONS[schema_type],
            )
        )
    return tuple(entries)


def raw_request_authority_publication_tables() -> tuple[RawRequestAuthorityPrivateTable, ...]:
    """Return no public tables: the exact-four are private-only.

    This fail-safe compatibility surface exists only while W2.5 metadata and
    model-diagnostic consumers migrate to ``PublicDataDispositionV1``.  No
    caller may infer publication authority from the legacy name.
    """

    # Validate the private registry first so store/schema drift still fails
    # closed instead of being hidden by the empty public projection.
    raw_request_authority_private_tables()
    return ()
