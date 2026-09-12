from __future__ import annotations

from collections import Counter

import polars as pl
import pytest

import nbadb.extract.base as base_module
from nbadb.contracts.request_scope_storage_contract import (
    EXPECTED_REQUEST_SCOPE_STORAGE_COLUMN_COUNTS,
    EXPECTED_REQUEST_SCOPE_STORAGE_FIELD_COUNT,
    EXPECTED_REQUEST_SCOPE_STORAGE_ROUTE_COUNT,
    REQUEST_SCOPE_COLUMN_POLICIES,
    RequestScopeStorageContractError,
    derive_request_scope_storage_fields,
    selected_request_scope_storage_fields,
    validate_production_request_scope_injection_policy,
)
from nbadb.contracts.staging_route_contract import staging_route_contract_bundle
from nbadb.core.nba_api_request_surface import pinned_request_surface_authority
from nbadb.schemas.registry import get_input_schema


def test_code_owned_policy_matches_production_keys_and_order() -> None:
    validate_production_request_scope_injection_policy()

    assert tuple(item.storage_column for item in REQUEST_SCOPE_COLUMN_POLICIES) == (
        "season_year",
        "season_type",
        "league_id",
    )
    assert tuple(item.parameter_names for item in REQUEST_SCOPE_COLUMN_POLICIES) == (
        ("season", "season_nullable", "season_year"),
        (
            "season_type_all_star",
            "season_type_playoffs",
            "season_type",
            "season_type_nullable",
            "season_type_all_star_nullable",
        ),
        ("league_id", "league_id_nullable"),
    )


def test_scope_census_matches_independent_pinned_parameter_authority() -> None:
    routes = staging_route_contract_bundle().routes
    endpoints = {
        item.endpoint_id: item
        for item in pinned_request_surface_authority().endpoints
        if item.source_family == "stats"
    }
    independently_derived: list[tuple[str, str]] = []
    for route in routes:
        if route.source_family != "stats":
            continue
        parameter_names = {item.name for item in endpoints[route.provider_endpoint_id].parameters}
        for policy in REQUEST_SCOPE_COLUMN_POLICIES:
            if (
                parameter_names.intersection(policy.parameter_names)
                and policy.storage_column not in route.canonical_columns
                and policy.storage_column not in route.storage_columns
            ):
                independently_derived.append((route.route_id, policy.storage_column))

    route_derived = [
        (route.route_id, item.storage_column)
        for route in routes
        for item in route.request_scope_storage_fields
    ]
    assert route_derived == independently_derived
    assert len(route_derived) == EXPECTED_REQUEST_SCOPE_STORAGE_FIELD_COUNT == 608
    assert len({route_id for route_id, _column in route_derived}) == 313
    assert EXPECTED_REQUEST_SCOPE_STORAGE_ROUTE_COUNT == 313
    assert Counter(column for _route_id, column in route_derived) == {
        "season_year": 172,
        "season_type": 127,
        "league_id": 309,
    }
    assert dict(EXPECTED_REQUEST_SCOPE_STORAGE_COLUMN_COUNTS) == {
        "season_year": 172,
        "season_type": 127,
        "league_id": 309,
    }


def test_optional_scope_fields_are_selected_by_exact_alias_precedence() -> None:
    route = staging_route_contract_bundle().by_route_id[
        "common_all_players:stg_common_all_players:0"
    ]
    assert [item.storage_column for item in route.request_scope_storage_fields] == [
        "season_year",
        "league_id",
    ]

    assert selected_request_scope_storage_fields(route.request_scope_storage_fields, {}) == ()
    selected = selected_request_scope_storage_fields(
        route.request_scope_storage_fields,
        {"season": "2024-25", "league_id": "00"},
    )
    assert tuple(item.storage_column for item in selected) == ("season_year", "league_id")
    assert tuple(item.logical_type for item in selected) == (
        "large_string",
        "large_string",
    )


def test_common_all_players_production_injection_has_exact_arrow_schema() -> None:
    route = staging_route_contract_bundle().by_route_id[
        "common_all_players:stg_common_all_players:0"
    ]
    schema_cls = get_input_schema(route.staging_key)
    assert schema_cls is not None
    declared = schema_cls.to_schema()
    frame = pl.DataFrame(
        schema={
            name: column.dtype.type if column.dtype is not None else pl.Null
            for name, column in declared.columns.items()
        }
    )

    injected = base_module._inject_request_scope_columns(
        frame,
        {"season": "2024-25", "league_id": "00"},
    )

    assert tuple(injected.columns) == route.possible_storage_columns
    assert injected.to_arrow().schema[-2].type.equals(pl.Series(["x"]).to_arrow().type)
    assert injected.to_arrow().schema[-1].type.equals(pl.Series(["x"]).to_arrow().type)


def test_integer_season_year_alias_has_independent_exact_type() -> None:
    route = staging_route_contract_bundle().by_route_id[
        "draft_combine_drill_results:stg_draft_combine_drills:0"
    ]
    fields = route.request_scope_storage_fields
    assert [
        (item.storage_column, item.source_parameter_names, item.logical_type) for item in fields
    ] == [
        ("season_year", ("season_year",), "int64"),
        ("league_id", ("league_id",), "large_string"),
    ]
    assert selected_request_scope_storage_fields(fields, {"season_year": 2024}) == fields[:1]
    with pytest.raises(RequestScopeStorageContractError, match="integer value"):
        selected_request_scope_storage_fields(fields, {"season_year": "2024"})
    with pytest.raises(RequestScopeStorageContractError, match="integer value"):
        selected_request_scope_storage_fields(fields, {"season_year": True})


def test_missing_required_scope_value_fails_closed() -> None:
    fields = derive_request_scope_storage_fields(
        route_id="required:stg_required:0",
        source_family="stats",
        provider_required_parameters=("season",),
        provider_optional_parameters=(),
        canonical_columns=("value",),
        declared_storage_columns=("value",),
    )
    assert len(fields) == 1
    assert fields[0].required_parameter_names == ("season",)
    with pytest.raises(RequestScopeStorageContractError, match="required"):
        selected_request_scope_storage_fields(fields, {})
    with pytest.raises(RequestScopeStorageContractError, match="required"):
        selected_request_scope_storage_fields(fields, {"season": ""})


def test_provider_and_declared_schema_columns_are_never_redeclared_as_scope() -> None:
    route = staging_route_contract_bundle().by_route_id["schedule:stg_schedule:0"]
    assert "league_id" in route.canonical_columns
    assert "league_id" in route.storage_columns
    assert route.request_scope_storage_fields == ()

    fields = derive_request_scope_storage_fields(
        route_id="synthetic:stg_synthetic:0",
        source_family="stats",
        provider_required_parameters=(),
        provider_optional_parameters=("season", "league_id"),
        canonical_columns=("league_id",),
        declared_storage_columns=("value", "season_year"),
    )
    assert fields == ()


def test_live_static_and_parameterless_routes_have_no_scope_authority() -> None:
    routes = staging_route_contract_bundle().routes
    assert all(
        not route.request_scope_storage_fields
        for route in routes
        if route.source_family in {"live", "static"}
    )
    assert (
        derive_request_scope_storage_fields(
            route_id="parameterless:stg_parameterless:0",
            source_family="stats",
            provider_required_parameters=(),
            provider_optional_parameters=(),
            canonical_columns=("value",),
            declared_storage_columns=("value",),
        )
        == ()
    )


def test_production_injection_key_mutation_fails_closed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        base_module,
        "_SEASON_YEAR_KEYS",
        (*base_module._SEASON_YEAR_KEYS, "foreign_season"),
    )
    with pytest.raises(RequestScopeStorageContractError, match="keys/order"):
        validate_production_request_scope_injection_policy()
