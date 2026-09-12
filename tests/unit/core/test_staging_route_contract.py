from __future__ import annotations

from dataclasses import FrozenInstanceError, replace

import pytest

from nbadb.contracts.staging_route_contract import (
    EXPECTED_STAGING_ROUTE_COUNT,
    _make_bundle,
    staging_route_contract_bundle,
    validate_staging_route_contract_bundle,
)
from nbadb.orchestrate.staging_map import STAGING_MAP
from nbadb.schemas.registry import get_input_schema


@pytest.fixture(scope="module")
def route_bundle():
    return staging_route_contract_bundle()


def test_contract_compiles_the_exact_current_staging_map(route_bundle) -> None:
    routes = route_bundle.routes

    assert EXPECTED_STAGING_ROUTE_COUNT == 438
    assert len(routes) == len(STAGING_MAP) == EXPECTED_STAGING_ROUTE_COUNT
    assert tuple(route.ordinal for route in routes) == tuple(range(len(STAGING_MAP)))
    assert len({route.route_id for route in routes}) == len(STAGING_MAP)
    assert len({route.staging_key for route in routes}) == len(STAGING_MAP)
    assert tuple(route.staging_key for route in routes) == tuple(
        entry.staging_key for entry in STAGING_MAP
    )
    assert tuple(route.route_id for route in routes) == tuple(
        f"{entry.endpoint_name}:{entry.staging_key}:{entry.result_set_index}"
        for entry in STAGING_MAP
    )
    assert route_bundle.source_family_counts == (
        ("live", 10),
        ("static", 4),
        ("stats", 424),
    )
    assert route_bundle.status_counts == (
        ("bound_provider_packet", 432),
        ("classified_provider_columns_absent", 2),
        ("classified_provider_packet_absent", 4),
    )
    assert route_bundle.endpoint_role_counts == (
        ("canonical", 418),
        ("intentional_alias", 20),
    )
    assert route_bundle.storage_role_counts == (
        ("direct", 349),
        ("intentional_copy", 55),
        ("intentional_schema_alias", 34),
    )
    assert route_bundle.storage_mapping_status_counts == (
        ("complete", 422),
        ("lossless_payload_json", 10),
        ("provider_columns_absent", 6),
    )


def test_contract_has_no_unresolved_schema_or_unclassified_packet(route_bundle) -> None:
    for route in route_bundle.routes:
        schema_cls = get_input_schema(route.staging_key)
        assert schema_cls is not None
        assert route.storage_columns == tuple(schema_cls.to_schema().columns)
        assert route.resolved_schema_class == schema_cls.__name__
        assert route.resolved_schema_tier in {"raw", "staging"}
        assert route.resolved_schema_table
        if route.classified_status == "bound_provider_packet":
            assert route.provider_result_set_name
            assert route.provider_columns
            assert route.disposition_reason is None
        else:
            assert route.disposition_reason

    dispositions = {
        route.route_id: route.classified_status
        for route in route_bundle.routes
        if route.classified_status != "bound_provider_packet"
    }
    assert dispositions == {
        "defense_hub:stg_defense_hub_stat10:1": ("classified_provider_columns_absent"),
        "scoreboard_v2:stg_scoreboard_win_probability:9": ("classified_provider_columns_absent"),
        "video_details:stg_video_details:0": "classified_provider_packet_absent",
        "video_details_asset:stg_video_details_asset:0": ("classified_provider_packet_absent"),
        "video_events:stg_video_events:0": "classified_provider_packet_absent",
        "video_events_asset:stg_video_events_asset:0": ("classified_provider_packet_absent"),
    }
    partial_storage_routes = {
        route.route_id
        for route in route_bundle.routes
        if route.storage_mapping_status == "declared_storage_subset"
    }
    assert partial_storage_routes == set()


def test_contract_records_route_local_provider_and_column_identity(route_bundle) -> None:
    league_log = route_bundle.by_route_id["league_game_log:stg_league_game_log:0"]
    assert league_log.provider_endpoint_id == "LeagueGameLog"
    assert league_log.canonical_provider_endpoint_id == "LeagueGameLog"
    assert league_log.provider_runtime_class == "LeagueGameLog"
    assert league_log.provider_runtime_module == "nba_api.stats.endpoints.leaguegamelog"
    assert league_log.provider_result_set_name == "LeagueGameLog"
    assert league_log.provider_result_set_ordinal == 0
    assert league_log.provider_columns[:3] == ("SEASON_ID", "TEAM_ID", "TEAM_ABBREVIATION")
    assert league_log.canonical_columns[:3] == (
        "season_id",
        "team_id",
        "team_abbreviation",
    )
    assert league_log.column_mappings[0].to_dict() == {
        "provider_column": "SEASON_ID",
        "canonical_column": "season_id",
        "storage_column": "season_id",
        "transform": "rename",
    }

    live_player = route_bundle.by_route_id["live_box_score:stg_live_box_score_player_stats_home:5"]
    assert live_player.provider_endpoint_id == "BoxScore"
    assert live_player.provider_result_set_name == "game_hometeam_players"
    assert live_player.provider_result_set_ordinal == 6
    assert live_player.canonical_result_set_name == "live_box_score.home_team_player_stats"
    assert live_player.canonical_result_set_ordinal == 5
    assert live_player.storage_mapping_status == "lossless_payload_json"
    assert any(
        mapping.provider_column == "statistics.points"
        and mapping.storage_column == "points"
        and mapping.transform == "nested_projection"
        for mapping in live_player.column_mappings
    )

    static_team = route_bundle.by_route_id["static_teams:stg_static_teams:0"]
    championship = next(
        mapping
        for mapping in static_team.column_mappings
        if mapping.provider_column == "championship_year"
    )
    assert championship.canonical_column == "championship_years_json"
    assert championship.storage_column == "championship_years_json"
    assert championship.transform == "list_to_canonical_json"

    wnba_team = route_bundle.by_route_id["static_wnba_teams:stg_static_wnba_teams:0"]
    wnba_championship = next(
        mapping
        for mapping in wnba_team.column_mappings
        if mapping.provider_column == "championship_year"
    )
    assert wnba_championship.canonical_column == "championship_years_json"
    assert wnba_championship.storage_column == "championship_years_json"
    assert wnba_championship.transform == "list_to_canonical_json"


def test_contract_records_explicit_alias_copy_and_optional_policies(route_bundle) -> None:
    endpoint_alias = route_bundle.by_route_id["home_page_leaders:stg_home_page_leaders:0"]
    assert endpoint_alias.endpoint_role == "intentional_alias"
    assert endpoint_alias.canonical_endpoint_name == "homepage_leaders"
    assert endpoint_alias.endpoint_alias_target == "homepage_leaders"
    assert endpoint_alias.storage_role == "intentional_copy"
    assert endpoint_alias.storage_role_target == "stg_homepage_leaders"

    schema_alias = route_bundle.by_route_id["schedule:stg_schedule:0"]
    assert schema_alias.storage_role == "intentional_schema_alias"
    assert schema_alias.storage_role_target == "stg_schedule_league_v2"

    optional = route_bundle.by_route_id["scoreboard_v2:stg_scoreboard_win_probability:9"]
    assert optional.presence_policy == "optional"
    assert optional.missing_result_set_policy == "materialize_empty"
    assert optional.present_empty_policy == "allowed"
    assert optional.allow_missing_result_set is True
    assert sum(route.presence_policy == "optional" for route in route_bundle.routes) == 1


def test_contract_access_is_deeply_immutable(route_bundle) -> None:
    route = route_bundle.routes[0]
    with pytest.raises(FrozenInstanceError):
        route.ordinal = 99
    with pytest.raises(AttributeError):
        route.provider_columns.append("MUTATED")
    with pytest.raises(TypeError):
        route_bundle.by_route_id[route.route_id] = route


def test_contract_digest_is_deterministic_and_order_sensitive(route_bundle) -> None:
    assert staging_route_contract_bundle() is route_bundle
    assert len(route_bundle.digest) == 64
    assert all(len(route.contract_sha256) == 64 for route in route_bundle.routes)
    assert _make_bundle(route_bundle.routes).digest == route_bundle.digest

    reordered = (route_bundle.routes[1], route_bundle.routes[0], *route_bundle.routes[2:])
    assert _make_bundle(reordered).digest != route_bundle.digest
    with pytest.raises(ValueError, match="ordinals"):
        validate_staging_route_contract_bundle(_make_bundle(reordered))


@pytest.mark.parametrize(
    ("mutation", "error"),
    [
        (
            lambda route: replace(
                route,
                provider_columns=tuple(reversed(route.provider_columns)),
            ),
            "provider column order differs",
        ),
        (
            lambda route: replace(route, route_id=f"mutated:{route.route_id}"),
            "route ID differs",
        ),
    ],
)
def test_validator_rejects_mutated_provider_columns_or_route_ids(
    route_bundle,
    mutation,
    error: str,
) -> None:
    route_index = next(
        index for index, route in enumerate(route_bundle.routes) if len(route.provider_columns) > 1
    )
    routes = list(route_bundle.routes)
    routes[route_index] = mutation(routes[route_index])
    mutated = _make_bundle(routes)

    with pytest.raises(ValueError, match=error):
        validate_staging_route_contract_bundle(mutated)


def test_validator_rejects_mutated_alias_policy(route_bundle) -> None:
    route_index = next(
        index
        for index, route in enumerate(route_bundle.routes)
        if route.endpoint_role == "intentional_alias"
    )
    routes = list(route_bundle.routes)
    routes[route_index] = replace(
        routes[route_index],
        endpoint_alias_target="different_canonical_endpoint",
    )
    mutated = _make_bundle(routes)

    with pytest.raises(ValueError, match="alias target is not a staging endpoint"):
        validate_staging_route_contract_bundle(mutated)


def test_validator_rejects_mutated_optional_policy(route_bundle) -> None:
    route_index = next(
        index
        for index, route in enumerate(route_bundle.routes)
        if route.presence_policy == "optional"
    )
    routes = list(route_bundle.routes)
    routes[route_index] = replace(routes[route_index], presence_policy="required")
    mutated = _make_bundle(routes)

    with pytest.raises(ValueError, match="required route policy disagrees"):
        validate_staging_route_contract_bundle(mutated)
