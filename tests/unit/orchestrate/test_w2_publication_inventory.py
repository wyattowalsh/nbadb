from __future__ import annotations

import re
from dataclasses import fields
from typing import TYPE_CHECKING, cast

import pytest

import nbadb.orchestrate.w2_publication_inventory as inventory_module
from nbadb.contracts.live_lossless_value_authority import (
    LIVE_LOSSLESS_NODE_COLUMNS,
    LIVE_LOSSLESS_NODE_SCHEMA_SHA256,
    LiveLosslessNodeRecordV1,
)
from nbadb.contracts.public_table_value_projection import (
    RAW_NBA_API_RESULT_CELL_SCHEMA_SHA256,
    RAW_NBA_API_ROUTE_FIELD_LANDING_SCHEMA_SHA256,
    RAW_NBA_API_VALUE_REPRESENTATION_SCHEMA_SHA256,
)
from nbadb.contracts.public_value_types import ValueRepresentationAssignmentV1
from nbadb.contracts.raw_result_cell_authority import RawNbaApiResultCellV2
from nbadb.contracts.route_field_landing_authority import (
    RAW_NBA_API_ROUTE_FIELD_LANDING_COLUMNS,
    RawNbaApiRouteFieldLandingV1,
)
from nbadb.contracts.stats_lossless_value_authority import (
    STATS_LOSSLESS_RECORD_COLUMNS,
    STATS_LOSSLESS_RECORD_SCHEMA_SHA256,
    StatsLosslessRecordV1,
)
from nbadb.contracts.w2_operation import W2OperationReceiptV1
from nbadb.orchestrate import public_value_authority_store, w2_operation_store
from nbadb.orchestrate.raw_publication_inventory import (
    raw_request_authority_private_tables,
    raw_request_authority_publication_tables,
)
from nbadb.orchestrate.raw_request_store import RAW_REQUEST_AUTHORITY_TABLES
from nbadb.orchestrate.w2_publication_inventory import (
    W2_PUBLIC_VALUE_AUTHORITY_CATEGORY,
    W2PublicValueAuthorityPublicationTable,
    w2_public_value_authority_publication_tables,
)
from nbadb.schemas.raw.nba_api_live_lossless_node import RawNbaApiLiveLosslessNodeSchema
from nbadb.schemas.raw.nba_api_result_cell import RawNbaApiResultCellSchema
from nbadb.schemas.raw.nba_api_route_field_landing import (
    RawNbaApiRouteFieldLandingSchema,
)
from nbadb.schemas.raw.nba_api_stats_lossless_record import (
    RawNbaApiStatsLosslessRecordSchema,
)
from nbadb.schemas.raw.nba_api_value_representation import (
    RawNbaApiValueRepresentationSchema,
)
from nbadb.schemas.raw.nba_api_w2_operation import (
    RAW_NBA_API_W2_OPERATION_COLUMNS,
    RAW_NBA_API_W2_OPERATION_SCHEMA_SHA256,
    RawNbaApiW2OperationSchema,
)

if TYPE_CHECKING:
    from collections.abc import Callable


def _row_columns(row_model: type[object]) -> tuple[str, ...]:
    return ("schema_version", *(item.name for item in fields(row_model)))


_SEMANTIC_SOURCE_ORDER = (
    "raw_nba_api_result_cell",
    "raw_nba_api_stats_lossless_record",
    "raw_nba_api_live_lossless_node",
    "raw_nba_api_value_representation",
    "raw_nba_api_route_field_landing",
    "raw_nba_api_w2_operation",
)

_EXPECTED = {
    "raw_nba_api_result_cell": (
        RawNbaApiResultCellSchema,
        _row_columns(RawNbaApiResultCellV2),
        RAW_NBA_API_RESULT_CELL_SCHEMA_SHA256,
        RawNbaApiResultCellV2,
    ),
    "raw_nba_api_stats_lossless_record": (
        RawNbaApiStatsLosslessRecordSchema,
        STATS_LOSSLESS_RECORD_COLUMNS,
        STATS_LOSSLESS_RECORD_SCHEMA_SHA256,
        StatsLosslessRecordV1,
    ),
    "raw_nba_api_live_lossless_node": (
        RawNbaApiLiveLosslessNodeSchema,
        LIVE_LOSSLESS_NODE_COLUMNS,
        LIVE_LOSSLESS_NODE_SCHEMA_SHA256,
        LiveLosslessNodeRecordV1,
    ),
    "raw_nba_api_value_representation": (
        RawNbaApiValueRepresentationSchema,
        _row_columns(ValueRepresentationAssignmentV1),
        RAW_NBA_API_VALUE_REPRESENTATION_SCHEMA_SHA256,
        ValueRepresentationAssignmentV1,
    ),
    "raw_nba_api_route_field_landing": (
        RawNbaApiRouteFieldLandingSchema,
        RAW_NBA_API_ROUTE_FIELD_LANDING_COLUMNS,
        RAW_NBA_API_ROUTE_FIELD_LANDING_SCHEMA_SHA256,
        RawNbaApiRouteFieldLandingV1,
    ),
    "raw_nba_api_w2_operation": (
        RawNbaApiW2OperationSchema,
        RAW_NBA_API_W2_OPERATION_COLUMNS,
        RAW_NBA_API_W2_OPERATION_SCHEMA_SHA256,
        W2OperationReceiptV1,
    ),
}


def test_exact_six_inventory_binds_every_public_authority() -> None:
    entries = w2_public_value_authority_publication_tables()

    assert W2_PUBLIC_VALUE_AUTHORITY_CATEGORY == "w2_public_value_authority"
    assert type(entries) is tuple
    assert len(entries) == 6
    assert all(type(entry) is W2PublicValueAuthorityPublicationTable for entry in entries)
    assert tuple(entry.table_name for entry in entries) == tuple(sorted(_SEMANTIC_SOURCE_ORDER))
    assert (
        tuple(
            (
                *public_value_authority_store.PUBLIC_VALUE_AUTHORITY_TABLES,
                w2_operation_store.RAW_NBA_API_W2_OPERATION_TABLE,
            )
        )
        == _SEMANTIC_SOURCE_ORDER
    )
    assert len({entry.schema_type for entry in entries}) == 6
    assert len({entry.schema_sha256 for entry in entries}) == 6
    assert len({entry.row_model for entry in entries}) == 6

    for entry in entries:
        schema_type, ordered_columns, schema_sha256, row_model = _EXPECTED[entry.table_name]
        assert entry.schema_type is schema_type
        assert entry.ordered_columns == ordered_columns
        assert entry.schema_sha256 == schema_sha256
        assert re.fullmatch(r"[0-9a-f]{64}", entry.schema_sha256)
        assert entry.physical_types == tuple(
            str(column.dtype) for column in entry.schema_type.to_schema().columns.values()
        )
        assert len(entry.physical_types) == len(entry.ordered_columns)
        assert all(
            "binary" not in physical_type.lower() and "bytes" not in physical_type.lower()
            for physical_type in entry.physical_types
        )
        assert entry.row_model is row_model
        assert entry.ordered_columns == tuple(entry.schema_type.to_schema().columns)
        assert entry.ordered_columns == _row_columns(entry.row_model)
        assert entry.schema_type.Config.strict is True
        assert entry.schema_type.Config.coerce is False
        assert entry.schema_type.Config.ordered is True
        assert entry.description.strip()


def test_exact_four_raw_authority_inventory_is_not_expanded() -> None:
    assert RAW_REQUEST_AUTHORITY_TABLES == (
        "raw_nba_api_parser_input_object",
        "raw_nba_api_request_observation",
        "raw_nba_api_result_occurrence",
        "raw_nba_api_observation_route_landing",
    )
    private_four = raw_request_authority_private_tables()
    public_four = raw_request_authority_publication_tables()
    exact_six = w2_public_value_authority_publication_tables()

    assert public_four == ()
    assert len(private_four) == 4
    assert tuple(entry.table_name for entry in private_four) == RAW_REQUEST_AUTHORITY_TABLES
    assert {entry.table_name for entry in private_four}.isdisjoint(
        entry.table_name for entry in exact_six
    )
    assert w2_operation_store.RAW_NBA_API_W2_OPERATION_TABLE not in RAW_REQUEST_AUTHORITY_TABLES


@pytest.mark.parametrize(
    "mutation",
    (
        lambda values: values[:-1],
        lambda values: (*values, "raw_nba_api_unregistered"),
        lambda values: (values[0], values[1], values[2], values[3], values[3]),
        lambda values: tuple(reversed(values)),
        lambda values: (*values[:-1], "raw_nba_api_route_field_landing_alias"),
        lambda values: cast("tuple[str, ...]", list(values)),
    ),
)
def test_store_value_table_membership_alias_duplicates_and_order_fail_closed(
    monkeypatch: pytest.MonkeyPatch,
    mutation: Callable[[tuple[str, ...]], object],
) -> None:
    monkeypatch.setattr(
        public_value_authority_store,
        "PUBLIC_VALUE_AUTHORITY_TABLES",
        mutation(public_value_authority_store.PUBLIC_VALUE_AUTHORITY_TABLES),
    )

    with pytest.raises(RuntimeError, match="W2 publication store"):
        w2_public_value_authority_publication_tables()


@pytest.mark.parametrize(
    "operation_name",
    (
        "raw_nba_api_w2_operation_alias",
        "raw_nba_api_result_cell",
        "RAW_NBA_API_W2_OPERATION",
        7,
    ),
)
def test_operation_table_alias_collision_case_and_type_fail_closed(
    monkeypatch: pytest.MonkeyPatch,
    operation_name: object,
) -> None:
    monkeypatch.setattr(
        w2_operation_store,
        "RAW_NBA_API_W2_OPERATION_TABLE",
        operation_name,
    )

    with pytest.raises(RuntimeError, match="W2 publication store"):
        w2_public_value_authority_publication_tables()


@pytest.mark.parametrize("target_name", _SEMANTIC_SOURCE_ORDER)
def test_registry_schema_alias_or_mismatch_fails_closed(
    monkeypatch: pytest.MonkeyPatch,
    target_name: str,
) -> None:
    original = inventory_module.schema_registry.get_input_schema

    def foreign_schema(table_name: str) -> type[object] | None:
        if table_name == target_name:
            return RawNbaApiResultCellSchema if target_name != _SEMANTIC_SOURCE_ORDER[0] else None
        return original(table_name)

    monkeypatch.setattr(inventory_module.schema_registry, "get_input_schema", foreign_schema)

    with pytest.raises(RuntimeError, match="aliased or bound to a foreign raw schema"):
        w2_public_value_authority_publication_tables()


@pytest.mark.parametrize(
    ("module_name", "attribute"),
    (
        ("public_projection", "RAW_NBA_API_RESULT_CELL_SCHEMA_SHA256"),
        ("stats_authority", "STATS_LOSSLESS_RECORD_SCHEMA_SHA256"),
        ("live_authority", "LIVE_LOSSLESS_NODE_SCHEMA_SHA256"),
        ("public_projection", "RAW_NBA_API_VALUE_REPRESENTATION_SCHEMA_SHA256"),
        ("public_projection", "RAW_NBA_API_ROUTE_FIELD_LANDING_SCHEMA_SHA256"),
        ("w2_operation_schema", "RAW_NBA_API_W2_OPERATION_SCHEMA_SHA256"),
    ),
)
def test_each_schema_digest_drift_fails_closed(
    monkeypatch: pytest.MonkeyPatch,
    module_name: str,
    attribute: str,
) -> None:
    monkeypatch.setattr(getattr(inventory_module, module_name), attribute, "0" * 64)

    with pytest.raises(RuntimeError, match="schema digest"):
        w2_public_value_authority_publication_tables()


@pytest.mark.parametrize(
    ("module_name", "attribute"),
    (
        ("stats_authority", "STATS_LOSSLESS_RECORD_COLUMNS"),
        ("live_authority", "LIVE_LOSSLESS_NODE_COLUMNS"),
        ("route_field_authority", "RAW_NBA_API_ROUTE_FIELD_LANDING_COLUMNS"),
        ("w2_operation_schema", "RAW_NBA_API_W2_OPERATION_COLUMNS"),
    ),
)
def test_each_exported_ordered_column_authority_drift_fails_closed(
    monkeypatch: pytest.MonkeyPatch,
    module_name: str,
    attribute: str,
) -> None:
    module = getattr(inventory_module, module_name)
    monkeypatch.setattr(module, attribute, (*getattr(module, attribute), "injected_column"))

    with pytest.raises(RuntimeError, match="ordered columns"):
        w2_public_value_authority_publication_tables()


@pytest.mark.parametrize(
    ("module_name", "attribute"),
    (
        ("result_cell_authority", "RawNbaApiResultCellV2"),
        ("stats_authority", "StatsLosslessRecordV1"),
        ("live_authority", "LiveLosslessNodeRecordV1"),
        ("public_value_types", "ValueRepresentationAssignmentV1"),
        ("route_field_authority", "RawNbaApiRouteFieldLandingV1"),
        ("w2_operation_contract", "W2OperationReceiptV1"),
    ),
)
def test_each_row_model_drift_fails_closed(
    monkeypatch: pytest.MonkeyPatch,
    module_name: str,
    attribute: str,
) -> None:
    monkeypatch.setattr(getattr(inventory_module, module_name), attribute, object)

    with pytest.raises(RuntimeError, match="runtime authorities|row model"):
        w2_public_value_authority_publication_tables()


@pytest.mark.parametrize(
    ("module_name", "attribute"),
    (
        ("result_cell_schema", "RawNbaApiResultCellSchema"),
        ("stats_schema", "RawNbaApiStatsLosslessRecordSchema"),
        ("live_schema", "RawNbaApiLiveLosslessNodeSchema"),
        ("value_representation_schema", "RawNbaApiValueRepresentationSchema"),
        ("route_field_schema", "RawNbaApiRouteFieldLandingSchema"),
        ("w2_operation_schema", "RawNbaApiW2OperationSchema"),
    ),
)
def test_each_strict_schema_identity_drift_fails_closed(
    monkeypatch: pytest.MonkeyPatch,
    module_name: str,
    attribute: str,
) -> None:
    monkeypatch.setattr(
        getattr(inventory_module, module_name),
        attribute,
        RawNbaApiResultCellSchema
        if attribute != "RawNbaApiResultCellSchema"
        else RawNbaApiW2OperationSchema,
    )

    with pytest.raises(RuntimeError, match="runtime authorities|schema digest|row model"):
        w2_public_value_authority_publication_tables()


@pytest.mark.parametrize(
    ("setting", "value"),
    (
        ("strict", False),
        ("coerce", True),
        ("ordered", False),
    ),
)
def test_strict_schema_policy_drift_fails_closed(
    monkeypatch: pytest.MonkeyPatch,
    setting: str,
    value: bool,
) -> None:
    monkeypatch.setattr(RawNbaApiResultCellSchema.Config, setting, value)

    with pytest.raises(RuntimeError, match="strict, ordered, and non-coercing"):
        w2_public_value_authority_publication_tables()


def test_binary_physical_type_drift_fails_closed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    original = inventory_module._runtime_physical_types()
    mutated = list(original)
    mutated[0] = (*mutated[0][:-1], "Binary")
    monkeypatch.setattr(
        inventory_module,
        "_runtime_physical_types",
        lambda: tuple(mutated),
    )

    with pytest.raises(RuntimeError, match="ordered columns|physical"):
        w2_public_value_authority_publication_tables()


def test_schema_column_order_drift_fails_closed(monkeypatch: pytest.MonkeyPatch) -> None:
    original_schema = RawNbaApiResultCellSchema.to_schema()

    class ForeignSchema:
        columns = {**original_schema.columns, "injected_column": object()}

    monkeypatch.setattr(
        RawNbaApiResultCellSchema,
        "to_schema",
        classmethod(lambda _cls: ForeignSchema()),
    )

    with pytest.raises(
        RuntimeError,
        match="runtime authorities|schema, columns, and row model disagree",
    ):
        w2_public_value_authority_publication_tables()
