"""Validated publication inventory for the six public W2 relations.

The five value-authority relations and the terminal W2 operation relation have
separate stores, but they form one publication boundary.  This registry joins
their exact store-owned names to the strict raw schemas, ordered columns,
schema identities, and row DTOs that own their public representation.

The Raw Authority V2 exact-four inventory remains a separate contract in
``raw_publication_inventory`` and is deliberately not widened here.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, fields
from typing import TYPE_CHECKING, Final

from nbadb.contracts import live_lossless_value_authority as live_authority
from nbadb.contracts import public_table_value_projection as public_projection
from nbadb.contracts import public_value_types as public_value_types
from nbadb.contracts import raw_result_cell_authority as result_cell_authority
from nbadb.contracts import route_field_landing_authority as route_field_authority
from nbadb.contracts import stats_lossless_value_authority as stats_authority
from nbadb.contracts import w2_operation as w2_operation_contract
from nbadb.schemas import registry as schema_registry
from nbadb.schemas.raw import nba_api_live_lossless_node as live_schema
from nbadb.schemas.raw import nba_api_result_cell as result_cell_schema
from nbadb.schemas.raw import nba_api_route_field_landing as route_field_schema
from nbadb.schemas.raw import nba_api_stats_lossless_record as stats_schema
from nbadb.schemas.raw import nba_api_value_representation as value_representation_schema
from nbadb.schemas.raw import nba_api_w2_operation as w2_operation_schema

if TYPE_CHECKING:
    import pandera.polars as pa

__all__ = [
    "W2_PUBLIC_VALUE_AUTHORITY_CATEGORY",
    "W2PublicValueAuthorityPublicationTable",
    "w2_public_value_authority_publication_tables",
]


W2_PUBLIC_VALUE_AUTHORITY_CATEGORY: Final = "w2_public_value_authority"

_RAW_TABLE_RE: Final = re.compile(r"raw_[a-z0-9_]+\Z", flags=re.ASCII)
_SHA256_RE: Final = re.compile(r"[0-9a-f]{64}\Z", flags=re.ASCII)


@dataclass(frozen=True, slots=True)
class W2PublicValueAuthorityPublicationTable:
    """One exact public W2 relation and every authority for its row shape."""

    table_name: str
    schema_type: type[pa.DataFrameModel]
    ordered_columns: tuple[str, ...]
    physical_types: tuple[str, ...]
    schema_sha256: str
    row_model: type[object]
    description: str


def _row_model_columns(row_model: type[object]) -> tuple[str, ...]:
    try:
        return ("schema_version", *(item.name for item in fields(row_model)))
    except (TypeError, ValueError):
        raise RuntimeError("W2 publication row model is not one exact dataclass") from None


def _schema_physical_types(schema_type: type[pa.DataFrameModel]) -> tuple[str, ...]:
    """Return exact ordered physical types from one strict Pandera schema."""

    try:
        return tuple(str(column.dtype) for column in schema_type.to_schema().columns.values())
    except Exception:
        raise RuntimeError("W2 publication physical type lookup failed") from None


_EXPECTED_RELATIONS: Final = (
    W2PublicValueAuthorityPublicationTable(
        table_name="raw_nba_api_result_cell",
        schema_type=result_cell_schema.RawNbaApiResultCellSchema,
        ordered_columns=_row_model_columns(result_cell_authority.RawNbaApiResultCellV2),
        physical_types=_schema_physical_types(result_cell_schema.RawNbaApiResultCellSchema),
        schema_sha256=public_projection.RAW_NBA_API_RESULT_CELL_SCHEMA_SHA256,
        row_model=result_cell_authority.RawNbaApiResultCellV2,
        description=(
            "Exact duplicate-preserving provider result cells reconstructed from selected "
            "terminal response source bytes."
        ),
    ),
    W2PublicValueAuthorityPublicationTable(
        table_name="raw_nba_api_stats_lossless_record",
        schema_type=stats_schema.RawNbaApiStatsLosslessRecordSchema,
        ordered_columns=stats_authority.STATS_LOSSLESS_RECORD_COLUMNS,
        physical_types=_schema_physical_types(stats_schema.RawNbaApiStatsLosslessRecordSchema),
        schema_sha256=stats_authority.STATS_LOSSLESS_RECORD_SCHEMA_SHA256,
        row_model=stats_authority.StatsLosslessRecordV1,
        description=(
            "Complete ordered stats result declarations, headers, rows, cells, and residual "
            "JSON nodes for lossless drift preservation."
        ),
    ),
    W2PublicValueAuthorityPublicationTable(
        table_name="raw_nba_api_live_lossless_node",
        schema_type=live_schema.RawNbaApiLiveLosslessNodeSchema,
        ordered_columns=live_authority.LIVE_LOSSLESS_NODE_COLUMNS,
        physical_types=_schema_physical_types(live_schema.RawNbaApiLiveLosslessNodeSchema),
        schema_sha256=live_authority.LIVE_LOSSLESS_NODE_SCHEMA_SHA256,
        row_model=live_authority.LiveLosslessNodeRecordV1,
        description=(
            "Complete ordered live result declarations, occurrences, nodes, and field cells "
            "for lossless response preservation."
        ),
    ),
    W2PublicValueAuthorityPublicationTable(
        table_name="raw_nba_api_value_representation",
        schema_type=value_representation_schema.RawNbaApiValueRepresentationSchema,
        ordered_columns=_row_model_columns(public_value_types.ValueRepresentationAssignmentV1),
        physical_types=_schema_physical_types(
            value_representation_schema.RawNbaApiValueRepresentationSchema
        ),
        schema_sha256=public_projection.RAW_NBA_API_VALUE_REPRESENTATION_SCHEMA_SHA256,
        row_model=public_value_types.ValueRepresentationAssignmentV1,
        description=(
            "Value-free bindings from every expected response unit to its sole public value "
            "representation."
        ),
    ),
    W2PublicValueAuthorityPublicationTable(
        table_name="raw_nba_api_route_field_landing",
        schema_type=route_field_schema.RawNbaApiRouteFieldLandingSchema,
        ordered_columns=route_field_authority.RAW_NBA_API_ROUTE_FIELD_LANDING_COLUMNS,
        physical_types=_schema_physical_types(route_field_schema.RawNbaApiRouteFieldLandingSchema),
        schema_sha256=public_projection.RAW_NBA_API_ROUTE_FIELD_LANDING_SCHEMA_SHA256,
        row_model=route_field_authority.RawNbaApiRouteFieldLandingV1,
        description=(
            "Exact value-free expected-unit to committed route-field bindings, including "
            "zero-field route sentinels."
        ),
    ),
    W2PublicValueAuthorityPublicationTable(
        table_name="raw_nba_api_w2_operation",
        schema_type=w2_operation_schema.RawNbaApiW2OperationSchema,
        ordered_columns=w2_operation_schema.RAW_NBA_API_W2_OPERATION_COLUMNS,
        physical_types=_schema_physical_types(w2_operation_schema.RawNbaApiW2OperationSchema),
        schema_sha256=w2_operation_schema.RAW_NBA_API_W2_OPERATION_SCHEMA_SHA256,
        row_model=w2_operation_contract.W2OperationReceiptV1,
        description=(
            "One mandatory bundle-scoped W2 operation receipt binding exact source, "
            "projection, equality, public-relation, and committed staging roots."
        ),
    ),
)


def _runtime_schema_types() -> tuple[type[pa.DataFrameModel], ...]:
    return (
        result_cell_schema.RawNbaApiResultCellSchema,
        stats_schema.RawNbaApiStatsLosslessRecordSchema,
        live_schema.RawNbaApiLiveLosslessNodeSchema,
        value_representation_schema.RawNbaApiValueRepresentationSchema,
        route_field_schema.RawNbaApiRouteFieldLandingSchema,
        w2_operation_schema.RawNbaApiW2OperationSchema,
    )


def _runtime_row_models() -> tuple[type[object], ...]:
    return (
        result_cell_authority.RawNbaApiResultCellV2,
        stats_authority.StatsLosslessRecordV1,
        live_authority.LiveLosslessNodeRecordV1,
        public_value_types.ValueRepresentationAssignmentV1,
        route_field_authority.RawNbaApiRouteFieldLandingV1,
        w2_operation_contract.W2OperationReceiptV1,
    )


def _runtime_ordered_columns() -> tuple[tuple[str, ...], ...]:
    return (
        _row_model_columns(result_cell_authority.RawNbaApiResultCellV2),
        stats_authority.STATS_LOSSLESS_RECORD_COLUMNS,
        live_authority.LIVE_LOSSLESS_NODE_COLUMNS,
        _row_model_columns(public_value_types.ValueRepresentationAssignmentV1),
        route_field_authority.RAW_NBA_API_ROUTE_FIELD_LANDING_COLUMNS,
        w2_operation_schema.RAW_NBA_API_W2_OPERATION_COLUMNS,
    )


def _runtime_physical_types() -> tuple[tuple[str, ...], ...]:
    return tuple(_schema_physical_types(schema_type) for schema_type in _runtime_schema_types())


def _runtime_schema_sha256s() -> tuple[str, ...]:
    return (
        public_projection.RAW_NBA_API_RESULT_CELL_SCHEMA_SHA256,
        stats_authority.STATS_LOSSLESS_RECORD_SCHEMA_SHA256,
        live_authority.LIVE_LOSSLESS_NODE_SCHEMA_SHA256,
        public_projection.RAW_NBA_API_VALUE_REPRESENTATION_SCHEMA_SHA256,
        public_projection.RAW_NBA_API_ROUTE_FIELD_LANDING_SCHEMA_SHA256,
        w2_operation_schema.RAW_NBA_API_W2_OPERATION_SCHEMA_SHA256,
    )


def _source_table_names() -> tuple[str, ...]:
    from nbadb.orchestrate import public_value_authority_store, w2_operation_store

    value_tables = public_value_authority_store.PUBLIC_VALUE_AUTHORITY_TABLES
    operation_table = w2_operation_store.RAW_NBA_API_W2_OPERATION_TABLE
    if (
        type(value_tables) is not tuple
        or len(value_tables) != 5
        or type(operation_table) is not str
    ):
        raise RuntimeError("W2 publication store table inventory is malformed")
    source = (*value_tables, operation_table)
    if (
        len(source) != len(_EXPECTED_RELATIONS)
        or any(type(name) is not str for name in source)
        or len(source) != len(set(source))
        or any(_RAW_TABLE_RE.fullmatch(name) is None for name in source)
    ):
        raise RuntimeError("W2 publication store table inventory is malformed")
    expected = tuple(item.table_name for item in _EXPECTED_RELATIONS)
    if source != expected:
        raise RuntimeError("W2 publication store table membership, alias, or order drifted")
    return source


def _validated_expected_relations() -> tuple[W2PublicValueAuthorityPublicationTable, ...]:
    expected = _EXPECTED_RELATIONS
    if (
        type(expected) is not tuple
        or len(expected) != 6
        or any(type(item) is not W2PublicValueAuthorityPublicationTable for item in expected)
    ):
        raise RuntimeError("W2 publication fixed relation contract is malformed")
    table_names = tuple(item.table_name for item in expected)
    schema_types = tuple(item.schema_type for item in expected)
    row_models = tuple(item.row_model for item in expected)
    physical_types = tuple(item.physical_types for item in expected)
    schema_sha256s = tuple(item.schema_sha256 for item in expected)
    if (
        len(table_names) != len(set(table_names))
        or len(schema_types) != len(set(schema_types))
        or len(row_models) != len(set(row_models))
        or any(
            len(types) != len(columns)
            for types, columns in zip(
                physical_types,
                (item.ordered_columns for item in expected),
                strict=True,
            )
        )
        or len(schema_sha256s) != len(set(schema_sha256s))
    ):
        raise RuntimeError("W2 publication fixed relation contract contains duplicates")
    return expected


def w2_public_value_authority_publication_tables() -> tuple[
    W2PublicValueAuthorityPublicationTable, ...
]:
    """Return the exact six store/schema/row-model-backed W2 public relations.

    Store membership and every upstream schema authority are read at call time,
    so aliases, reordering, duplicate names, or later schema/DTO drift cannot be
    hidden by an import-time snapshot.  The source order is validated before the
    returned inventory is sorted by table name for stable publication output.
    """

    source_names = _source_table_names()
    expected_relations = _validated_expected_relations()
    try:
        runtime_schema_types = _runtime_schema_types()
        runtime_row_models = _runtime_row_models()
        runtime_columns = _runtime_ordered_columns()
        runtime_physical_types = _runtime_physical_types()
        runtime_schema_sha256s = _runtime_schema_sha256s()
    except Exception:
        raise RuntimeError("W2 publication runtime authorities are malformed") from None

    entries: list[W2PublicValueAuthorityPublicationTable] = []
    for (
        table_name,
        expected,
        schema_type,
        row_model,
        ordered_columns,
        physical_types,
        schema_sha256,
    ) in zip(
        source_names,
        expected_relations,
        runtime_schema_types,
        runtime_row_models,
        runtime_columns,
        runtime_physical_types,
        runtime_schema_sha256s,
        strict=True,
    ):
        if (
            schema_type is not expected.schema_type
            or row_model is not expected.row_model
            or ordered_columns != expected.ordered_columns
            or physical_types != expected.physical_types
            or schema_sha256 != expected.schema_sha256
            or type(ordered_columns) is not tuple
            or not ordered_columns
            or any(type(column) is not str or not column for column in ordered_columns)
            or len(ordered_columns) != len(set(ordered_columns))
            or type(physical_types) is not tuple
            or len(physical_types) != len(ordered_columns)
            or any(
                type(physical_type) is not str
                or not physical_type
                or "binary" in physical_type.lower()
                or "bytes" in physical_type.lower()
                for physical_type in physical_types
            )
            or type(schema_sha256) is not str
            or _SHA256_RE.fullmatch(schema_sha256) is None
        ):
            raise RuntimeError(
                "W2 publication ordered columns, schema digest, or row model drifted"
            )
        try:
            registered_schema = schema_registry.get_input_schema(table_name)
            schema_columns = tuple(schema_type.to_schema().columns)
            model_columns = _row_model_columns(row_model)
            config = schema_type.Config
        except Exception:
            raise RuntimeError("W2 publication strict raw schema lookup failed") from None
        if registered_schema is not schema_type:
            raise RuntimeError(
                "W2 publication store name is aliased or bound to a foreign raw schema"
            )
        if schema_columns != ordered_columns or model_columns != ordered_columns:
            raise RuntimeError("W2 publication schema, columns, and row model disagree")
        if config.strict is not True or config.coerce is not False or config.ordered is not True:
            raise RuntimeError("W2 publication raw schema is not strict, ordered, and non-coercing")
        if type(expected.description) is not str or not expected.description.strip():
            raise RuntimeError("W2 publication relation description is malformed")
        entries.append(
            W2PublicValueAuthorityPublicationTable(
                table_name=table_name,
                schema_type=schema_type,
                ordered_columns=ordered_columns,
                physical_types=physical_types,
                schema_sha256=schema_sha256,
                row_model=row_model,
                description=expected.description,
            )
        )
    return tuple(sorted(entries, key=lambda entry: entry.table_name))
