from __future__ import annotations

from collections import Counter
from dataclasses import replace

import pytest

from nbadb.contracts.request_scope_storage_contract import (
    EXPECTED_REQUEST_SCOPE_STORAGE_COLUMN_COUNTS,
    EXPECTED_REQUEST_SCOPE_STORAGE_FIELD_COUNT,
    EXPECTED_REQUEST_SCOPE_STORAGE_ROUTE_COUNT,
)
from nbadb.contracts.staging_route_contract import (
    staging_route_contract_bundle,
    validate_staging_route_contract_bundle,
)


def test_bundle_carries_exact_request_scope_storage_authority() -> None:
    bundle = staging_route_contract_bundle()
    fields = tuple(item for route in bundle.routes for item in route.request_scope_storage_fields)

    assert bundle.request_scope_storage_field_count == len(fields) == 608
    assert EXPECTED_REQUEST_SCOPE_STORAGE_FIELD_COUNT == 608
    assert (
        bundle.request_scope_storage_route_count
        == sum(bool(route.request_scope_storage_fields) for route in bundle.routes)
        == 313
    )
    assert EXPECTED_REQUEST_SCOPE_STORAGE_ROUTE_COUNT == 313
    assert Counter(item.storage_column for item in fields) == {
        "season_year": 172,
        "season_type": 127,
        "league_id": 309,
    }
    assert dict(EXPECTED_REQUEST_SCOPE_STORAGE_COLUMN_COUNTS) == {
        "season_year": 172,
        "season_type": 127,
        "league_id": 309,
    }
    assert len(bundle.request_scope_storage_sha256) == 64
    validate_staging_route_contract_bundle(bundle)


def test_common_all_players_possible_storage_suffix_is_exact() -> None:
    route = staging_route_contract_bundle().by_route_id[
        "common_all_players:stg_common_all_players:0"
    ]

    assert tuple(item.storage_column for item in route.request_scope_storage_fields) == (
        "season_year",
        "league_id",
    )
    assert route.possible_storage_columns == (
        *route.storage_columns,
        "season_year",
        "league_id",
    )
    assert all(item.source_parameter_names for item in route.request_scope_storage_fields)
    assert not set(route.storage_columns) & {
        item.storage_column for item in route.request_scope_storage_fields
    }


def test_alias_routes_derive_scope_independently_but_keep_route_identity() -> None:
    bundle = staging_route_contract_bundle()
    alias_routes = tuple(
        route
        for route in bundle.routes
        if route.endpoint_role == "intentional_alias" and route.request_scope_storage_fields
    )
    assert alias_routes
    assert all(route.endpoint_alias_target for route in alias_routes)
    assert all(
        item.route_id == route.route_id
        for route in alias_routes
        for item in route.request_scope_storage_fields
    )


def test_reordered_or_rebound_scope_authority_is_rejected() -> None:
    bundle = staging_route_contract_bundle()
    route = bundle.by_route_id["common_all_players:stg_common_all_players:0"]
    reordered = replace(
        route,
        request_scope_storage_fields=tuple(reversed(route.request_scope_storage_fields)),
    )
    routes = tuple(reordered if item.route_id == route.route_id else item for item in bundle.routes)
    changed = replace(bundle, routes=routes)

    with pytest.raises(ValueError, match="request-scope"):
        validate_staging_route_contract_bundle(changed)
