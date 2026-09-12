from __future__ import annotations

from collections import Counter
from dataclasses import FrozenInstanceError, replace
from types import MappingProxyType

import pytest

from nbadb.contracts.field_fate_contract import (
    EXPECTED_NESTED_PROJECTION_OCCURRENCE_COUNT,
    EXPECTED_PROVIDER_FIELD_OCCURRENCE_COUNT,
    EXPECTED_REPEATED_ROUTE_OCCURRENCE_COUNT,
    EXPECTED_STORAGE_MAPPED_OCCURRENCE_COUNT,
    EXPECTED_STORAGE_ONLY_SINK_OCCURRENCE_COUNT,
    EXPECTED_STORAGE_UNMAPPED_OCCURRENCE_COUNT,
    EXPECTED_TOP_LEVEL_PROVIDER_FIELD_OCCURRENCE_COUNT,
    EXPECTED_UNIQUE_PROVIDER_FIELD_IDENTITY_COUNT,
    EXPECTED_ZERO_FIELD_ROUTE_COUNT,
    FieldFateContractCompilationError,
    _make_bundle,
    compile_field_fate_contracts,
    validate_field_fate_contract_bundle,
)
from nbadb.contracts.staging_route_contract import staging_route_contract_bundle


@pytest.fixture(scope="module")
def field_bundle():
    return compile_field_fate_contracts()


def test_compiler_uses_exact_route_occurrence_denominator(field_bundle) -> None:
    route_bundle = staging_route_contract_bundle()
    route_occurrences = sum(len(route.column_mappings) for route in route_bundle.routes)

    assert len(route_bundle.routes) == 438
    assert route_occurrences == EXPECTED_PROVIDER_FIELD_OCCURRENCE_COUNT == 11_323
    assert len(field_bundle.fields) == route_occurrences
    assert field_bundle.provider_field_occurrence_count == route_occurrences
    assert (
        field_bundle.top_level_provider_field_occurrence_count
        == EXPECTED_TOP_LEVEL_PROVIDER_FIELD_OCCURRENCE_COUNT
        == 11_321
    )
    assert (
        field_bundle.nested_projection_occurrence_count
        == EXPECTED_NESTED_PROJECTION_OCCURRENCE_COUNT
        == 2
    )
    assert tuple(field.occurrence_ordinal for field in field_bundle.fields) == tuple(
        range(route_occurrences)
    )


def test_occurrence_order_and_route_identity_are_exact(field_bundle) -> None:
    route_bundle = staging_route_contract_bundle()
    expected = tuple(
        (
            f"{route.route_id}#field:{field_ordinal}",
            route.route_id,
            route.ordinal,
            field_ordinal,
            mapping.provider_column,
            mapping.canonical_column,
            mapping.storage_column,
            mapping.transform,
        )
        for route in route_bundle.routes
        for field_ordinal, mapping in enumerate(route.column_mappings)
    )
    observed = tuple(
        (
            field.occurrence_id,
            field.route_id,
            field.route_ordinal,
            field.route_field_ordinal,
            field.provider_column,
            field.canonical_column,
            field.storage_column,
            field.mapping_transform,
        )
        for field in field_bundle.fields
    )

    assert observed == expected
    assert len(field_bundle.by_occurrence_id) == EXPECTED_PROVIDER_FIELD_OCCURRENCE_COUNT
    assert all(field_bundle.field(field.occurrence_id) is field for field in field_bundle.fields)


def test_unique_provider_identity_does_not_collapse_route_occurrences(
    field_bundle,
) -> None:
    assert (
        field_bundle.unique_provider_field_identity_count
        == EXPECTED_UNIQUE_PROVIDER_FIELD_IDENTITY_COUNT
        == 9_694
    )
    assert (
        field_bundle.repeated_route_occurrence_count
        == EXPECTED_REPEATED_ROUTE_OCCURRENCE_COUNT
        == 1_629
    )
    identity_counts: dict[str, int] = {}
    for field in field_bundle.fields:
        identity_counts[field.provider_field_identity_sha256] = (
            identity_counts.get(field.provider_field_identity_sha256, 0) + 1
        )
    assert len(identity_counts) == EXPECTED_UNIQUE_PROVIDER_FIELD_IDENTITY_COUNT
    assert sum(identity_counts.values()) == EXPECTED_PROVIDER_FIELD_OCCURRENCE_COUNT
    assert any(count > 1 for count in identity_counts.values())


def test_exact_storage_mappings_and_unmapped_provider_fields(field_bundle) -> None:
    mapped = [field for field in field_bundle.fields if field.storage_column is not None]
    unmapped = [field for field in field_bundle.fields if field.storage_column is None]

    assert len(mapped) == EXPECTED_STORAGE_MAPPED_OCCURRENCE_COUNT == 11_323
    assert len(unmapped) == EXPECTED_STORAGE_UNMAPPED_OCCURRENCE_COUNT == 0
    assert field_bundle.mapping_transform_counts == (
        ("identity", 144),
        ("list_to_canonical_json", 2),
        ("nested_projection", 2),
        ("payload_json_record", 126),
        ("rename", 11_049),
    )
    assert field_bundle.storage_tier_counts == (("raw", 315), ("staging", 11_008))
    assert all(
        field.staging_disposition.status == "exact_declared_storage_mapping"
        and field.staging_disposition.green is True
        and field.staging_disposition.target_column == field.storage_column
        for field in mapped
    )
    assert all(
        field.staging_disposition.status == "declared_storage_target_absent"
        and field.staging_disposition.green is False
        and "storage_mapping_missing" in field.blockers
        for field in unmapped
    )


def test_nested_projections_are_explicit_provider_occurrences(field_bundle) -> None:
    nested = [
        field for field in field_bundle.fields if field.provider_field_kind == "nested_projection"
    ]

    assert [field.route_id for field in nested] == [
        "live_box_score:stg_live_box_score_player_stats_home:5",
        "live_box_score:stg_live_box_score_player_stats_away:6",
    ]
    assert {field.provider_column for field in nested} == {"statistics.points"}
    assert {field.canonical_column for field in nested} == {"points"}
    assert {field.storage_column for field in nested} == {"points"}
    assert {field.mapping_transform for field in nested} == {"nested_projection"}


def test_storage_only_columns_remain_sinks_not_provider_sources(field_bundle) -> None:
    sinks = field_bundle.storage_only_sinks

    assert len(sinks) == EXPECTED_STORAGE_ONLY_SINK_OCCURRENCE_COUNT == 1_445
    assert tuple(sink.occurrence_ordinal for sink in sinks) == tuple(range(len(sinks)))
    assert len({sink.occurrence_id for sink in sinks}) == len(sinks)
    assert all(sink.disposition == "local_storage_sink_not_provider_denominator" for sink in sinks)
    assert all(sink.blockers == ("storage_only_source_disposition_unreviewed",) for sink in sinks)
    assert not {(sink.route_id, sink.storage_column) for sink in sinks} & {
        (field.route_id, field.storage_column)
        for field in field_bundle.fields
        if field.storage_column is not None
    }
    assert Counter(
        sink.route_id
        for sink in sinks
        if sink.route_id
        in {
            "video_events:stg_video_events:0",
            "video_events_asset:stg_video_events_asset:0",
        }
    ) == {
        "video_events:stg_video_events:0": 31,
        "video_events_asset:stg_video_events_asset:0": 31,
    }


def test_zero_field_routes_remain_explicit_blockers(field_bundle) -> None:
    assert len(field_bundle.zero_field_routes) == EXPECTED_ZERO_FIELD_ROUTE_COUNT == 6
    assert {route.route_id for route in field_bundle.zero_field_routes} == {
        "defense_hub:stg_defense_hub_stat10:1",
        "scoreboard_v2:stg_scoreboard_win_probability:9",
        "video_details:stg_video_details:0",
        "video_details_asset:stg_video_details_asset:0",
        "video_events:stg_video_events:0",
        "video_events_asset:stg_video_events_asset:0",
    }
    assert all(route.disposition_reason for route in field_bundle.zero_field_routes)
    assert all(
        route.blockers == ("provider_field_inventory_absent",)
        for route in field_bundle.zero_field_routes
    )


def test_candidate_lineage_is_visible_but_never_admitted(field_bundle) -> None:
    summary = {
        item.kind: (item.field_occurrence_count, item.target_count)
        for item in field_bundle.candidate_evidence_summary
    }

    assert summary == {
        "explicit_star_source_metadata_candidate": (1_310, 1_387),
        "dependency_same_name_candidate": (9_571, 10_147),
        "sql_passthrough_candidate": (2_313, 2_344),
        "global_same_name_candidate": (10_779, 411_204),
        "normalized_name_inference": (764, 1_899),
    }
    evidence = [item for field in field_bundle.fields for item in field.non_green_lineage_evidence]
    assert evidence
    assert all(item.targets for item in evidence)
    assert all(item.admitted is False and item.green is False for item in evidence)
    assert all(len(item.targets_sha256) == 64 for item in evidence)
    assert all(
        field.star_disposition.target_table is None
        and field.star_disposition.target_column is None
        and field.star_disposition.reviewed is False
        and field.star_disposition.green is False
        for field in field_bundle.fields
    )


def test_every_field_exposes_all_disposition_slots_and_remains_non_green(
    field_bundle,
) -> None:
    assert (
        field_bundle.unresolved_provider_field_occurrence_count
        == EXPECTED_PROVIDER_FIELD_OCCURRENCE_COUNT
    )
    assert field_bundle.model_green is False

    for field in field_bundle.fields:
        assert field.physical_disposition.status == (
            "provider_declaration_not_physical_field_observation"
        )
        assert field.physical_disposition.green is False
        assert field.model_disposition.status == "unreviewed_no_model_disposition"
        assert field.model_disposition.green is False
        assert field.metric_disposition.status == "unreviewed_no_metric_disposition"
        assert field.metric_disposition.green is False
        assert field.reason
        assert field.owner == "nbadb_data_model"
        assert field.revalidation_path
        assert field.blockers
        assert field.model_green is False

    blockers = {
        (item.scope, item.code): item.occurrence_count for item in field_bundle.blocker_summary
    }
    assert (
        blockers[("provider_field", "physical_field_capture_unobserved")]
        == EXPECTED_PROVIDER_FIELD_OCCURRENCE_COUNT
    )
    assert (
        blockers[("provider_field", "star_lineage_unreviewed")]
        == EXPECTED_PROVIDER_FIELD_OCCURRENCE_COUNT
    )
    assert (
        blockers[("provider_field", "model_disposition_unreviewed")]
        == EXPECTED_PROVIDER_FIELD_OCCURRENCE_COUNT
    )
    assert (
        blockers[("provider_field", "metric_disposition_unreviewed")]
        == EXPECTED_PROVIDER_FIELD_OCCURRENCE_COUNT
    )
    assert ("provider_field", "storage_mapping_missing") not in blockers
    assert (
        blockers[("storage_only_sink", "storage_only_source_disposition_unreviewed")]
        == EXPECTED_STORAGE_ONLY_SINK_OCCURRENCE_COUNT
    )
    assert blockers[("zero_field_route", "provider_field_inventory_absent")] == 6


def test_all_previously_partial_silver_routes_are_injective_and_complete(
    field_bundle,
) -> None:
    route_ids = {
        "box_score_player_track:stg_box_score_player_track:0",
        "cume_stats_player:stg_cume_player:0",
        "cume_stats_player:stg_cume_player_game_by_game:0",
        "cume_stats_player:stg_cume_player_totals:1",
        "cume_stats_team:stg_cume_team:0",
        "cume_stats_team:stg_cume_team_game_by_game:0",
        "cume_stats_team:stg_cume_team_totals:1",
        "draft_board:stg_draft_board:0",
        "dunk_score_leaders:stg_dunk_score_leaders:0",
        "gravity_leaders:stg_gravity_leaders:0",
        "league_leaders:stg_league_leaders:0",
    }
    fields_by_route = {
        route_id: tuple(field for field in field_bundle.fields if field.route_id == route_id)
        for route_id in route_ids
    }

    for route_id, fields in fields_by_route.items():
        assert fields, route_id
        assert all(field.storage_column is not None for field in fields), route_id
        assert len({field.storage_column for field in fields}) == len(fields), route_id

    for left_route, right_route in (
        (
            "cume_stats_player:stg_cume_player:0",
            "cume_stats_player:stg_cume_player_game_by_game:0",
        ),
        (
            "cume_stats_team:stg_cume_team:0",
            "cume_stats_team:stg_cume_team_game_by_game:0",
        ),
    ):
        left = fields_by_route[left_route]
        right = fields_by_route[right_route]
        assert tuple(field.storage_column for field in left) == tuple(
            field.storage_column for field in right
        )
        assert {field.occurrence_id for field in left}.isdisjoint(
            field.occurrence_id for field in right
        )


def test_compilation_is_deterministic(field_bundle) -> None:
    repeated = compile_field_fate_contracts()

    assert repeated == field_bundle
    assert repeated.digest == field_bundle.digest
    assert len(repeated.digest) == 64
    validate_field_fate_contract_bundle(repeated)


def test_bundle_is_deeply_immutable(field_bundle) -> None:
    field = field_bundle.fields[0]

    with pytest.raises(FrozenInstanceError):
        field_bundle.model_green = True
    with pytest.raises(TypeError):
        field_bundle.fields[0] = field
    with pytest.raises(FrozenInstanceError):
        field.star_disposition.green = True
    with pytest.raises(TypeError):
        field_bundle.by_occurrence_id[field.occurrence_id] = field


def test_validation_fails_closed_on_field_loss_or_route_drift(field_bundle) -> None:
    truncated = _make_bundle(
        fields=field_bundle.fields[:-1],
        storage_only_sinks=field_bundle.storage_only_sinks,
        zero_field_routes=field_bundle.zero_field_routes,
        staging_route_contract_sha256=field_bundle.staging_route_contract_sha256,
        star_table_contract_sha256=field_bundle.star_table_contract_sha256,
        provider_authority_sha256=field_bundle.provider_authority_sha256,
    )
    with pytest.raises(
        FieldFateContractCompilationError,
        match="provider-field denominator",
    ):
        validate_field_fate_contract_bundle(truncated)

    first = field_bundle.fields[0]
    mutated_fields = (replace(first, route_id="mutated:route"), *field_bundle.fields[1:])
    mutated = replace(
        field_bundle,
        fields=mutated_fields,
        _by_occurrence_id=MappingProxyType(
            {field.occurrence_id: field for field in mutated_fields}
        ),
    )
    with pytest.raises(FieldFateContractCompilationError):
        validate_field_fate_contract_bundle(mutated)
