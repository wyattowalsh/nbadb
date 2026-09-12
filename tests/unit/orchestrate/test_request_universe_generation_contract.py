from __future__ import annotations

import ast
import inspect
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace

import pytest

from nbadb.orchestrate import request_universe_generation_contract as subject
from nbadb.orchestrate.cume_workload_contract import CumeEntityKind, CumeWorkloadValue
from nbadb.orchestrate.request_universe_generation_contract import (
    CandidateBlockerV1,
    CommittedObservationGenerationV1,
    ExplicitTemporalScopeValueV1,
    FieldOccurrenceInputV1,
    LogicalRequestCallV1,
    RequestUniverseCandidateContractError,
    RequestUniverseCandidateGenerationV1,
    RequestUniverseCandidateSourceV1,
    RequestUniverseFinalizationSourceV1,
    RequestUniverseShardV1,
    RequestUniverseV1,
    RouteRequestMemberV1,
    TemporalScopeKind,
    TerminalRequestClassificationV1,
    TerminalRequestDisposition,
    TerminalRequestEvidenceV1,
    UnintegratedCumeValueV1,
    compile_request_universe_candidate_generation_v1,
    compile_request_universe_v1,
)

_AUTHORITY = "a" * 64
_FIELD_FATE = "b" * 64
_TEMPORAL = "c" * 64
_DEPENDENT = "d" * 64
_CUME = "2a910d5340f8cd24c32ca4494dd1b293f7a790f95a7d5294c1115f340363c6ee"
_CUME_WORKLOAD_JSON = (
    '{"disposition":"complete","entity_id":7,"entity_kind":"player",'
    '"foundation_receipt_sha256":"1111111111111111111111111111111111111111111111111111111111111111",'
    '"game_ids":["0022300001"],"kind":"nbadb_cume_workload",'
    '"provider_authority_sha256":"aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",'
    '"schema_version":1,"season":"2023-24","season_type":"Regular Season",'
    '"typed_zero_reason":null}'
)


def _micro_source() -> RequestUniverseCandidateSourceV1:
    page_zero = LogicalRequestCallV1.from_parameters(
        authority_generation_sha256=_AUTHORITY,
        source_family="stats",
        endpoint_name="player_game_logs_v2",
        canonical_endpoint_name="player_game_logs",
        physical_endpoint_name="player_game_logs_v2",
        parameters={"PlayerID": 7, "Season": "2023-24"},
        pagination_kind="page",
        pagination_value=0,
    )
    page_one = LogicalRequestCallV1.from_parameters(
        authority_generation_sha256=_AUTHORITY,
        source_family="stats",
        endpoint_name="player_game_logs_v2",
        canonical_endpoint_name="player_game_logs",
        physical_endpoint_name="player_game_logs_v2",
        parameters={"PlayerID": 7, "Season": "2023-24"},
        pagination_kind="page",
        pagination_value=1,
    )
    dependent = LogicalRequestCallV1.from_parameters(
        authority_generation_sha256=_AUTHORITY,
        source_family="stats",
        endpoint_name="team_and_players_vs_players",
        canonical_endpoint_name="team_and_players_vs",
        physical_endpoint_name="team_and_players_vs_players",
        parameters={"PlayerID": 7, "Season": "2023-24", "TeamID": 11},
        dependent_workload_kind="five_v_five",
        dependent_workload_sha256=_DEPENDENT,
        dependent_physical_alias="team_and_players_vs_players",
    )
    page_routes = tuple(
        RouteRequestMemberV1.build(
            call=call,
            route_id="player_game_logs_v2:stg_player_game_logs_v2:0",
            result_name="PlayerGameLogs",
            result_ordinal=0,
        )
        for call in (page_zero, page_one)
    )
    dependent_route = RouteRequestMemberV1.build(
        call=dependent,
        route_id=("team_and_players_vs_players:stg_team_and_players_vs_players:0"),
        result_name="PlayersVsPlayers",
        result_ordinal=1,
        nested_path=("statistics",),
    )
    fields = (
        FieldOccurrenceInputV1(
            authority_generation_sha256=_AUTHORITY,
            occurrence_id="player_game_logs_v2:stg_player_game_logs_v2:0#field:0",
            route_id="player_game_logs_v2:stg_player_game_logs_v2:0",
            endpoint_name="player_game_logs_v2",
            result_name="PlayerGameLogs",
            result_ordinal=0,
            nested_path=(),
            provider_field="PTS",
            field_occurrence_ordinal=0,
            field_fate_contract_sha256=_FIELD_FATE,
        ),
        FieldOccurrenceInputV1(
            authority_generation_sha256=_AUTHORITY,
            occurrence_id="player_game_logs_v2:stg_player_game_logs_v2:0#field:1",
            route_id="player_game_logs_v2:stg_player_game_logs_v2:0",
            endpoint_name="player_game_logs_v2",
            result_name="PlayerGameLogs",
            result_ordinal=0,
            nested_path=(),
            provider_field="PTS",
            field_occurrence_ordinal=1,
            field_fate_contract_sha256=_FIELD_FATE,
        ),
        FieldOccurrenceInputV1(
            authority_generation_sha256=_AUTHORITY,
            occurrence_id=("team_and_players_vs_players:stg_team_and_players_vs_players:0#field:0"),
            route_id=("team_and_players_vs_players:stg_team_and_players_vs_players:0"),
            endpoint_name="team_and_players_vs_players",
            result_name="PlayersVsPlayers",
            result_ordinal=1,
            nested_path=("statistics",),
            provider_field="MATCHUP_MINUTES",
            field_occurrence_ordinal=0,
            field_fate_contract_sha256=_FIELD_FATE,
        ),
    )
    period_values = (
        (page_routes[0], TemporalScopeKind.SEASON, "2023-24"),
        (page_routes[1], TemporalScopeKind.GAME_ID, "0022300001"),
        (dependent_route, TemporalScopeKind.SEASON_TYPE, "Regular Season"),
    )
    periods = tuple(
        ExplicitTemporalScopeValueV1(
            authority_generation_sha256=_AUTHORITY,
            physical_call_id=route.physical_call_id,
            route_request_member_id=route.route_request_member_id,
            route_id=route.route_id,
            endpoint_name=route.endpoint_name,
            request_scope_sha256=route.request_scope_sha256,
            temporal_contract_sha256=_TEMPORAL,
            temporal_scope_kind=kind,
            temporal_scope_value=value,
        )
        for route, kind, value in period_values
    )
    cume = UnintegratedCumeValueV1(
        authority_generation_sha256=_AUTHORITY,
        entity_kind="player",
        workload_content_sha256=_CUME,
        workload_canonical_json=_CUME_WORKLOAD_JSON,
        physical_endpoint_aliases=("cume_stats_player", "cume_stats_player_games"),
    )
    return RequestUniverseCandidateSourceV1(
        authority_generation_sha256=_AUTHORITY,
        field_fate_contract_sha256=_FIELD_FATE,
        temporal_contract_sha256=_TEMPORAL,
        logical_calls=tuple(
            sorted((page_zero, page_one, dependent), key=lambda item: item.physical_call_id)
        ),
        route_members=tuple(
            sorted(
                (*page_routes, dependent_route),
                key=lambda item: item.route_request_member_id,
            )
        ),
        field_occurrences=tuple(sorted(fields, key=lambda item: item.identity_sha256)),
        explicit_temporal_scopes=tuple(sorted(periods, key=lambda item: item.identity_sha256)),
        unintegrated_cume_values=(cume,),
    )


def test_literal_known_answer_conserves_every_candidate_dimension() -> None:
    source = _micro_source()
    candidate = compile_request_universe_candidate_generation_v1(source)

    assert candidate.identity_sha256 == (
        "bcbdbc1940a464af922f643198c6dcffc5e9a4ea0ab9f5ad0e3ad26bfe2285da"
    )
    assert source.source_inputs_sha256 == (
        "c2661f8c08e7878a6dba6ac8fcd8965377a9035dc5340de07083d0919579ad09"
    )
    assert candidate.source_inputs_sha256 == source.source_inputs_sha256
    assert candidate.terminal is False
    assert candidate.release_eligible is False
    assert len(candidate.logical_calls) == 3
    assert len(candidate.route_members) == 3
    assert len(candidate.field_period_cells) == 5
    assert {cell.state for cell in candidate.field_period_cells} == {"evidence_insufficient"}
    assert {cell.temporal_scope_kind for cell in candidate.field_period_cells} == {
        TemporalScopeKind.SEASON,
        TemporalScopeKind.SEASON_TYPE,
        TemporalScopeKind.GAME_ID,
    }
    assert {
        (cell.provider_field, cell.field_occurrence_ordinal)
        for cell in candidate.field_period_cells
        if cell.result_name == "PlayerGameLogs"
    } == {("PTS", 0), ("PTS", 1)}
    assert {
        (call.physical_endpoint_name, call.pagination_kind, call.pagination_value)
        for call in candidate.logical_calls
        if call.canonical_endpoint_name == "player_game_logs"
    } == {
        ("player_game_logs_v2", "page", 0),
        ("player_game_logs_v2", "page", 1),
    }
    dependent = next(call for call in candidate.logical_calls if call.dependent_workload_sha256)
    assert dependent.dependent_physical_alias == "team_and_players_vs_players"
    assert {blocker.blocker_code for blocker in candidate.blockers} == {
        "candidate_not_fixed_point",
        "unintegrated_cume_value",
    }
    assert _CUME not in {call.dependent_workload_sha256 for call in candidate.logical_calls}


def test_compiler_is_deterministic_canonical_and_strictly_round_trips() -> None:
    source = _micro_source()
    first = compile_request_universe_candidate_generation_v1(source)
    second = compile_request_universe_candidate_generation_v1(
        RequestUniverseCandidateSourceV1.from_dict(source.to_dict())
    )

    assert first == second
    assert first.canonical_bytes == second.canonical_bytes
    assert RequestUniverseCandidateGenerationV1.from_canonical_bytes(first.canonical_bytes) == first
    with pytest.raises(RequestUniverseCandidateContractError, match="not exact canonical"):
        RequestUniverseCandidateGenerationV1.from_canonical_bytes(first.canonical_bytes + b"\n")
    duplicate = first.canonical_bytes.replace(
        b'"terminal":false',
        b'"terminal":false,"terminal":false',
    )
    with pytest.raises(RequestUniverseCandidateContractError, match="duplicate keys"):
        RequestUniverseCandidateGenerationV1.from_canonical_bytes(duplicate)


def test_only_explicit_typed_period_values_become_cells() -> None:
    source = _micro_source()
    candidate = compile_request_universe_candidate_generation_v1(source)
    explicit = {
        (
            period.route_request_member_id,
            period.temporal_scope_kind,
            period.temporal_scope_value,
        )
        for period in source.explicit_temporal_scopes
    }

    assert {
        (
            cell.route_request_member_id,
            cell.temporal_scope_kind,
            cell.temporal_scope_value,
        )
        for cell in candidate.field_period_cells
    } <= explicit
    with pytest.raises(RequestUniverseCandidateContractError, match="consecutive"):
        replace(
            source.explicit_temporal_scopes[0],
            temporal_scope_kind=TemporalScopeKind.SEASON,
            temporal_scope_value="2023-25",
        )
    with pytest.raises(RequestUniverseCandidateContractError, match="calendar date"):
        replace(
            source.explicit_temporal_scopes[0],
            temporal_scope_kind=TemporalScopeKind.GAME_DATE,
            temporal_scope_value="2023-02-29",
        )


def test_current_field_and_temporal_projections_do_not_infer_periods() -> None:
    current_field = SimpleNamespace(
        occurrence_id="sample_endpoint:stg_sample:0#field:2",
        provider_field_kind="nested_projection",
        provider_column="statistics.points",
        route_id="sample_endpoint:stg_sample:0",
        endpoint_name="sample_endpoint",
        provider_result_set_name="SampleResult",
        provider_result_set_ordinal=0,
        route_field_ordinal=2,
    )
    projected = FieldOccurrenceInputV1.from_current_contract(
        authority_generation_sha256=_AUTHORITY,
        field_fate_contract_sha256=_FIELD_FATE,
        field_fate=current_field,
    )
    call = LogicalRequestCallV1.from_parameters(
        authority_generation_sha256=_AUTHORITY,
        source_family="stats",
        endpoint_name="sample_endpoint",
        canonical_endpoint_name="sample_endpoint",
        physical_endpoint_name="sample_endpoint",
        parameters={"Season": "2023-24"},
    )
    route = RouteRequestMemberV1.build(
        call=call,
        route_id="sample_endpoint:stg_sample:0",
        result_name="SampleResult",
        result_ordinal=0,
        nested_path=("statistics",),
    )
    current_temporal = SimpleNamespace(
        route_id=route.route_id,
        endpoint_name=route.endpoint_name,
        provider_result_set_name=route.result_name,
        provider_result_set_ordinal=route.result_ordinal,
        planner_start_season=1946,
        supported_season_types=("Regular Season",),
        availability_state="unknown",
    )
    explicit = ExplicitTemporalScopeValueV1.from_current_contract(
        authority_generation_sha256=_AUTHORITY,
        temporal_contract_sha256=_TEMPORAL,
        route_member=route,
        route_scope=current_temporal,
        temporal_scope_kind=TemporalScopeKind.SEASON,
        temporal_scope_value="2023-24",
    )

    assert projected.nested_path == ("statistics",)
    assert projected.provider_field == "points"
    assert explicit.temporal_scope_value == "2023-24"
    assert explicit.temporal_scope_value != current_temporal.planner_start_season


def test_mixed_authority_inputs_fail_before_candidate_compilation() -> None:
    source = _micro_source()
    foreign_authority = "f" * 64
    foreign_call = LogicalRequestCallV1.from_parameters(
        authority_generation_sha256=foreign_authority,
        source_family="stats",
        endpoint_name="foreign_endpoint",
        canonical_endpoint_name="foreign_endpoint",
        physical_endpoint_name="foreign_endpoint",
        parameters={},
    )
    foreign_route = RouteRequestMemberV1.build(
        call=foreign_call,
        route_id="foreign_endpoint:stg_foreign:0",
        result_name="Foreign",
        result_ordinal=0,
    )
    variants = (
        {
            "logical_calls": tuple(
                sorted((*source.logical_calls, foreign_call), key=lambda x: x.physical_call_id)
            )
        },
        {
            "route_members": tuple(
                sorted(
                    (*source.route_members, foreign_route), key=lambda x: x.route_request_member_id
                )
            )
        },
        {
            "field_occurrences": tuple(
                sorted(
                    (
                        *source.field_occurrences,
                        replace(
                            source.field_occurrences[0],
                            authority_generation_sha256=foreign_authority,
                            occurrence_id="foreign_endpoint:stg_foreign:0#field:0",
                        ),
                    ),
                    key=lambda x: x.identity_sha256,
                )
            )
        },
        {
            "explicit_temporal_scopes": tuple(
                sorted(
                    (
                        *source.explicit_temporal_scopes,
                        replace(
                            source.explicit_temporal_scopes[0],
                            authority_generation_sha256=foreign_authority,
                        ),
                    ),
                    key=lambda x: x.identity_sha256,
                )
            )
        },
        {
            "unintegrated_cume_values": tuple(
                sorted(
                    (
                        *source.unintegrated_cume_values,
                        replace(
                            source.unintegrated_cume_values[0],
                            authority_generation_sha256=foreign_authority,
                        ),
                    ),
                    key=lambda item: item.identity_sha256,
                )
            )
        },
    )
    for changes in variants:
        with pytest.raises(RequestUniverseCandidateContractError, match="mixed-authority"):
            replace(source, **changes)


def test_unintegrated_cume_values_cannot_be_promoted_to_request_units() -> None:
    source = _micro_source()
    cume_call = LogicalRequestCallV1.from_parameters(
        authority_generation_sha256=_AUTHORITY,
        source_family="stats",
        endpoint_name="cume_stats_player",
        canonical_endpoint_name="cume_stats_player",
        physical_endpoint_name="cume_stats_player",
        parameters={"GameIDs": "0022300001", "PlayerID": 7},
    )
    with pytest.raises(RequestUniverseCandidateContractError, match="cannot become"):
        replace(
            source,
            logical_calls=tuple(
                sorted((*source.logical_calls, cume_call), key=lambda item: item.physical_call_id)
            ),
        )


def test_cume_aliases_and_workload_content_are_exactly_entity_bound() -> None:
    cume = _micro_source().unintegrated_cume_values[0]
    with pytest.raises(RequestUniverseCandidateContractError, match="entity-bound set"):
        replace(cume, physical_endpoint_aliases=("forged_cume_alias",))
    with pytest.raises(RequestUniverseCandidateContractError, match="rebound"):
        replace(
            cume,
            entity_kind="team",
            physical_endpoint_aliases=("cume_stats_team", "cume_stats_team_games"),
        )
    with pytest.raises(RequestUniverseCandidateContractError, match="content digest"):
        replace(cume, workload_content_sha256="9" * 64)
    with pytest.raises(RequestUniverseCandidateContractError, match="rebound"):
        replace(
            cume,
            workload_canonical_json=cume.workload_canonical_json.replace(
                '"entity_kind":"player"',
                '"entity_kind":"team"',
            ),
        )


@pytest.mark.parametrize(
    ("entity_kind", "expected_aliases"),
    [
        (
            CumeEntityKind.PLAYER,
            ("cume_stats_player", "cume_stats_player_games"),
        ),
        (
            CumeEntityKind.TEAM,
            ("cume_stats_team", "cume_stats_team_games"),
        ),
    ],
)
def test_current_cume_projection_binds_exact_entity_content_and_aliases(
    entity_kind: CumeEntityKind,
    expected_aliases: tuple[str, str],
) -> None:
    workload = CumeWorkloadValue.complete(
        entity_kind=entity_kind,
        entity_id=7,
        season="2023-24",
        season_type="Regular Season",
        game_ids=("0022300001",),
        foundation_receipt_sha256="1" * 64,
        provider_authority_sha256=_AUTHORITY,
    )
    projected = UnintegratedCumeValueV1.from_current_contract(
        authority_generation_sha256=_AUTHORITY,
        workload=workload,
    )

    assert projected.entity_kind == entity_kind.value
    assert projected.workload_content_sha256 == workload.content_sha256
    assert projected.workload_canonical_json == workload.canonical_bytes.decode("utf-8")
    assert projected.physical_endpoint_aliases == expected_aliases


def test_candidate_finality_is_structurally_unrepresentable() -> None:
    candidate = compile_request_universe_candidate_generation_v1(_micro_source())
    with pytest.raises(RequestUniverseCandidateContractError, match="cannot be terminal"):
        replace(candidate, terminal=True)
    with pytest.raises(RequestUniverseCandidateContractError, match="cannot be terminal"):
        replace(candidate, release_eligible=True)
    with pytest.raises(RequestUniverseCandidateContractError, match="evidence_insufficient"):
        replace(
            candidate,
            field_period_cells=(
                replace(candidate.field_period_cells[0], state="observed_nonempty"),
                *candidate.field_period_cells[1:],
            ),
        )


def test_candidate_rejects_mixed_contract_authorities_and_structural_orphans() -> None:
    candidate = compile_request_universe_candidate_generation_v1(_micro_source())
    with pytest.raises(RequestUniverseCandidateContractError, match="mixed field-fate"):
        replace(candidate, field_fate_contract_sha256="f" * 64)
    with pytest.raises(RequestUniverseCandidateContractError, match="mixed temporal"):
        replace(candidate, temporal_contract_sha256="f" * 64)

    calls = candidate.logical_calls[1:]
    with pytest.raises(RequestUniverseCandidateContractError, match="route differs"):
        replace(
            candidate,
            logical_calls=calls,
            logical_call_inventory_sha256=subject.canonical_request_universe_sha256(
                [item.to_dict() for item in calls]
            ),
        )

    routes = candidate.route_members[1:]
    with pytest.raises(RequestUniverseCandidateContractError, match="cell differs"):
        replace(
            candidate,
            route_members=routes,
            route_member_inventory_sha256=subject.canonical_request_universe_sha256(
                [item.to_dict() for item in routes]
            ),
        )


def test_candidate_requires_a_nonempty_blocker_inventory() -> None:
    candidate = compile_request_universe_candidate_generation_v1(_micro_source())
    with pytest.raises(RequestUniverseCandidateContractError, match="bounded cardinality"):
        replace(
            candidate,
            blockers=(),
            blocker_inventory_sha256=subject.canonical_request_universe_sha256([]),
        )
    with pytest.raises(RequestUniverseCandidateContractError, match="non-fixed-point"):
        replace(
            candidate,
            blockers=(
                CandidateBlockerV1(
                    authority_generation_sha256=_AUTHORITY,
                    blocker_code="candidate_not_fixed_point",
                    subject_id="request_universe_candidate_generation_v1",
                    evidence_sha256="0" * 64,
                ),
            ),
        )
    cume_only = tuple(
        blocker
        for blocker in candidate.blockers
        if blocker.blocker_code == "unintegrated_cume_value"
    )
    with pytest.raises(RequestUniverseCandidateContractError, match="non-fixed-point"):
        replace(
            candidate,
            blockers=cume_only,
            blocker_inventory_sha256=subject.canonical_request_universe_sha256(
                [item.to_dict() for item in cume_only]
            ),
        )


def test_primary_compiler_has_no_runtime_provider_filesystem_clock_or_registry_reads() -> None:
    path = Path(inspect.getsourcefile(subject) or "")
    tree = ast.parse(path.read_text(encoding="utf-8"))
    runtime_imports = {
        alias.name
        for node in tree.body
        if isinstance(node, (ast.Import, ast.ImportFrom))
        for alias in node.names
    }
    assert not any(name.startswith("nbadb") for name in runtime_imports)
    compiler = next(
        node
        for node in tree.body
        if isinstance(node, ast.FunctionDef)
        and node.name == "compile_request_universe_candidate_generation_v1"
    )
    called = {
        node.func.id
        for node in ast.walk(compiler)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
    }
    assert called.isdisjoint(
        {
            "open",
            "Path",
            "datetime",
            "date",
            "time",
            "getenv",
            "pinned_request_surface_authority",
            "temporal_availability_contract_bundle",
            "compile_field_fate_contracts",
        }
    )


def _finalization_source() -> RequestUniverseFinalizationSourceV1:
    candidate = compile_request_universe_candidate_generation_v1(_micro_source())
    checkpoint = "4" * 64
    closure = "5" * 64
    w2 = "6" * 64
    temporal = candidate.field_period_inventory_sha256
    closure_provider_requests = tuple(
        sorted(f"{index + 1}" * 64 for index, _call in enumerate(candidate.logical_calls))
    )
    generation_key = subject.canonical_request_universe_sha256(
        {
            "authority_generation_sha256": _AUTHORITY,
            "checkpoint_identity_sha256": checkpoint,
            "request_closure_receipt_sha256": closure,
            "w2_authority_identity_sha256": w2,
            "temporal_field_denominator_sha256": temporal,
            "closure_fixed_point_provider_request_inventory_sha256": (
                subject.canonical_request_universe_sha256(list(closure_provider_requests))
            ),
            "parent_observation_generation_sha256": None,
            "generation_ordinal": 1,
        }
    )
    dispositions = (
        TerminalRequestDisposition.CAPTURED_NONEMPTY,
        TerminalRequestDisposition.CAPTURED_PRESENT_EMPTY,
        TerminalRequestDisposition.UPSTREAM_UNAVAILABLE,
    )
    evidence = tuple(
        sorted(
            (
                TerminalRequestEvidenceV1(
                    authority_generation_sha256=_AUTHORITY,
                    checkpoint_identity_sha256=checkpoint,
                    request_closure_receipt_sha256=closure,
                    w2_authority_identity_sha256=w2,
                    temporal_field_denominator_sha256=temporal,
                    observation_generation_key_sha256=generation_key,
                    physical_call_id=call.physical_call_id,
                    request_scope_sha256=call.request_scope_sha256,
                    source_family=call.source_family,
                    endpoint_name=call.endpoint_name,
                    provider_request_sha256=f"{index + 1}" * 64,
                    request_observation_sha256=f"{index + 4}" * 64,
                    request_call=call,
                    disposition=disposition,
                    captured_row_count=(
                        1
                        if disposition is TerminalRequestDisposition.CAPTURED_NONEMPTY
                        else 0
                        if disposition is not TerminalRequestDisposition.UPSTREAM_UNAVAILABLE
                        else None
                    ),
                    result_receipt_count=(
                        1
                        if disposition is not TerminalRequestDisposition.UPSTREAM_UNAVAILABLE
                        else None
                    ),
                    staging_receipt_count=(
                        1
                        if disposition is not TerminalRequestDisposition.UPSTREAM_UNAVAILABLE
                        else None
                    ),
                    result_receipt_inventory_sha256=(
                        "7" * 64
                        if disposition is not TerminalRequestDisposition.UPSTREAM_UNAVAILABLE
                        else None
                    ),
                    staging_receipt_inventory_sha256=(
                        "8" * 64
                        if disposition is not TerminalRequestDisposition.UPSTREAM_UNAVAILABLE
                        else None
                    ),
                    typed_upstream_unavailable_evidence_sha256=(
                        "9" * 64
                        if disposition is TerminalRequestDisposition.UPSTREAM_UNAVAILABLE
                        else None
                    ),
                    upstream_support_authority_sha256=(
                        "a" * 64
                        if disposition is TerminalRequestDisposition.UPSTREAM_UNAVAILABLE
                        else None
                    ),
                    safe_probe_receipt_sha256=(
                        "b" * 64
                        if disposition is TerminalRequestDisposition.UPSTREAM_UNAVAILABLE
                        else None
                    ),
                    unavailable_reason_code=(
                        "provider_contract_absent_for_scope"
                        if disposition is TerminalRequestDisposition.UPSTREAM_UNAVAILABLE
                        else None
                    ),
                    validity_scope_start=(
                        "2023-24"
                        if disposition is TerminalRequestDisposition.UPSTREAM_UNAVAILABLE
                        else None
                    ),
                    validity_scope_end=(
                        "2023-24"
                        if disposition is TerminalRequestDisposition.UPSTREAM_UNAVAILABLE
                        else None
                    ),
                    independent_verifier_id=(
                        "support-verifier-v1"
                        if disposition is TerminalRequestDisposition.UPSTREAM_UNAVAILABLE
                        else None
                    ),
                    independent_verifier_sha256=(
                        "c" * 64
                        if disposition is TerminalRequestDisposition.UPSTREAM_UNAVAILABLE
                        else None
                    ),
                    revalidation_policy=(
                        "on_authority_or_scope_change"
                        if disposition is TerminalRequestDisposition.UPSTREAM_UNAVAILABLE
                        else None
                    ),
                )
                for index, (call, disposition) in enumerate(
                    zip(candidate.logical_calls, dispositions, strict=True)
                )
            ),
            key=lambda item: item.physical_call_id,
        )
    )
    observation_generation = CommittedObservationGenerationV1(
        authority_generation_sha256=_AUTHORITY,
        checkpoint_identity_sha256=checkpoint,
        request_closure_receipt_sha256=closure,
        w2_authority_identity_sha256=w2,
        temporal_field_denominator_sha256=temporal,
        closure_fixed_point_provider_request_sha256s=closure_provider_requests,
        terminal_evidence=evidence,
    )
    evidence_by_call = {item.physical_call_id: item for item in evidence}
    classifications = tuple(
        TerminalRequestClassificationV1(
            authority_generation_sha256=_AUTHORITY,
            committed_observation_generation_sha256=(observation_generation.generation_sha256),
            physical_call_id=call.physical_call_id,
            request_scope_sha256=call.request_scope_sha256,
            disposition=evidence_by_call[call.physical_call_id].disposition,
            evidence=evidence_by_call[call.physical_call_id],
        )
        for call in candidate.logical_calls
    )
    shards = tuple(
        RequestUniverseShardV1(
            authority_generation_sha256=_AUTHORITY,
            shard_id=f"shard-{index:03d}",
            physical_call_ids=(call.physical_call_id,),
        )
        for index, call in enumerate(candidate.logical_calls)
    )
    return RequestUniverseFinalizationSourceV1(
        authority_generation_sha256=_AUTHORITY,
        checkpoint_identity_sha256=checkpoint,
        checkpoint_authority_generation_sha256=_AUTHORITY,
        request_closure_receipt_sha256=closure,
        request_closure_authority_generation_sha256=_AUTHORITY,
        w2_authority_identity_sha256=w2,
        w2_authority_generation_sha256=_AUTHORITY,
        temporal_field_denominator_sha256=temporal,
        temporal_field_authority_generation_sha256=_AUTHORITY,
        committed_observation_generation_sha256=(observation_generation.generation_sha256),
        committed_observation_authority_generation_sha256=_AUTHORITY,
        candidate_source_sha256=candidate.source_inputs_sha256,
        candidate_generation_sha256=candidate.identity_sha256,
        candidate_independent_proof_sha256="7" * 64,
        source_admission_sha256="8" * 64,
        committed_observation_generation=observation_generation,
        logical_calls=candidate.logical_calls,
        terminal_classifications=classifications,
        shards=shards,
    )


def _expanded_observation_generation(
    source: RequestUniverseFinalizationSourceV1,
    call: LogicalRequestCallV1,
    *,
    provider_request_sha256: str,
) -> CommittedObservationGenerationV1:
    current = source.committed_observation_generation
    closure_units = tuple(
        sorted(
            {
                *current.closure_fixed_point_provider_request_sha256s,
                provider_request_sha256,
            }
        )
    )
    generation_key = subject.canonical_request_universe_sha256(
        {
            "authority_generation_sha256": current.authority_generation_sha256,
            "checkpoint_identity_sha256": current.checkpoint_identity_sha256,
            "request_closure_receipt_sha256": current.request_closure_receipt_sha256,
            "w2_authority_identity_sha256": current.w2_authority_identity_sha256,
            "temporal_field_denominator_sha256": (current.temporal_field_denominator_sha256),
            "closure_fixed_point_provider_request_inventory_sha256": (
                subject.canonical_request_universe_sha256(list(closure_units))
            ),
            "parent_observation_generation_sha256": (current.parent_observation_generation_sha256),
            "generation_ordinal": current.generation_ordinal,
        }
    )
    rekeyed = tuple(
        replace(
            item,
            observation_generation_key_sha256=generation_key,
            evidence_sha256="",
        )
        for item in current.terminal_evidence
    )
    extra = replace(
        rekeyed[0],
        observation_generation_key_sha256=generation_key,
        physical_call_id=call.physical_call_id,
        request_scope_sha256=call.request_scope_sha256,
        source_family=call.source_family,
        endpoint_name=call.endpoint_name,
        provider_request_sha256=provider_request_sha256,
        request_observation_sha256="e" * 64,
        request_call=call,
        evidence_sha256="",
    )
    return CommittedObservationGenerationV1(
        authority_generation_sha256=current.authority_generation_sha256,
        checkpoint_identity_sha256=current.checkpoint_identity_sha256,
        request_closure_receipt_sha256=current.request_closure_receipt_sha256,
        w2_authority_identity_sha256=current.w2_authority_identity_sha256,
        temporal_field_denominator_sha256=current.temporal_field_denominator_sha256,
        closure_fixed_point_provider_request_sha256s=closure_units,
        terminal_evidence=tuple(sorted((*rekeyed, extra), key=lambda item: item.physical_call_id)),
        parent_observation_generation_sha256=(current.parent_observation_generation_sha256),
        generation_ordinal=current.generation_ordinal,
    )


def test_final_request_universe_is_exact_terminal_and_primary_delta_empty() -> None:
    source = _finalization_source()
    universe = compile_request_universe_v1(source)

    assert RequestUniverseV1.from_canonical_bytes(universe.canonical_bytes) == universe
    assert universe.terminal is True
    assert universe.release_eligible is False
    assert universe.primary_empty_delta_receipt.delta_count == 0
    assert universe.primary_empty_delta_receipt.logical_call_count == len(universe.logical_calls)
    assert {item.disposition for item in universe.terminal_classifications} == set(
        TerminalRequestDisposition
    )
    assert {
        physical_call_id
        for shard in universe.shards
        for physical_call_id in shard.physical_call_ids
    } == {call.physical_call_id for call in universe.logical_calls}


@pytest.mark.parametrize(
    "disposition",
    ["skipped", "unattempted", "retry_exhausted", "contract_unmodeled"],
)
def test_final_classification_rejects_every_nonterminal_disposition(
    disposition: str,
) -> None:
    payload = _finalization_source().terminal_classifications[0].to_dict()
    payload["disposition"] = disposition
    with pytest.raises(RequestUniverseCandidateContractError, match="unsupported"):
        TerminalRequestClassificationV1.from_dict(payload)


def test_final_source_rejects_partial_duplicate_and_nonempty_fixed_points() -> None:
    source = _finalization_source()
    with pytest.raises(RequestUniverseCandidateContractError, match="denominator"):
        replace(source, terminal_classifications=source.terminal_classifications[:-1])
    with pytest.raises(RequestUniverseCandidateContractError, match="sorted unique"):
        replace(
            source,
            terminal_classifications=(
                source.terminal_classifications[0],
                *source.terminal_classifications,
            ),
        )
    derived = LogicalRequestCallV1.from_parameters(
        authority_generation_sha256=_AUTHORITY,
        source_family="stats",
        endpoint_name="player_game_logs_v2",
        canonical_endpoint_name="player_game_logs",
        physical_endpoint_name="player_game_logs_v2",
        parameters={"PlayerID": 99, "Season": "2023-24"},
    )
    generation = _expanded_observation_generation(
        source,
        derived,
        provider_request_sha256="d" * 64,
    )
    generation_evidence = {item.physical_call_id: item for item in generation.terminal_evidence}
    classifications = tuple(
        replace(
            item,
            committed_observation_generation_sha256=generation.generation_sha256,
            evidence=generation_evidence[item.physical_call_id],
        )
        for item in source.terminal_classifications
    )
    nonempty = replace(
        source,
        committed_observation_generation=generation,
        committed_observation_generation_sha256=generation.generation_sha256,
        terminal_classifications=classifications,
    )
    with pytest.raises(RequestUniverseCandidateContractError, match="nonempty"):
        compile_request_universe_v1(nonempty)


def test_final_source_rejects_partition_overlap_stale_evidence_and_cycles() -> None:
    source = _finalization_source()
    overlap = replace(
        source.shards[1],
        physical_call_ids=tuple(
            sorted(
                (
                    source.logical_calls[0].physical_call_id,
                    source.logical_calls[1].physical_call_id,
                )
            )
        ),
        request_inventory_sha256="",
    )
    with pytest.raises(RequestUniverseCandidateContractError, match="overlaps"):
        replace(source, shards=(source.shards[0], overlap, source.shards[2]))
    with pytest.raises(RequestUniverseCandidateContractError, match="stale or foreign"):
        replace(source, w2_authority_generation_sha256="f" * 64)
    with pytest.raises(RequestUniverseCandidateContractError, match="cyclic"):
        replace(
            source,
            ancestor_request_universe_sha256s=("1" * 64, "1" * 64),
            parent_request_universe_sha256="1" * 64,
            generation_ordinal=3,
        )


def test_final_source_rejects_guessed_matchup_cartesian_pairs() -> None:
    source = _finalization_source()
    guessed = LogicalRequestCallV1.from_parameters(
        authority_generation_sha256=_AUTHORITY,
        source_family="stats",
        endpoint_name="team_and_players_vs_players",
        canonical_endpoint_name="team_and_players_vs",
        physical_endpoint_name="team_and_players_vs_players",
        parameters={"PlayerID": 99, "Season": "2023-24", "TeamID": 88},
    )
    generation = _expanded_observation_generation(
        source,
        guessed,
        provider_request_sha256="d" * 64,
    )
    guessed_evidence = next(
        item
        for item in generation.terminal_evidence
        if item.physical_call_id == guessed.physical_call_id
    )
    guessed_classification = TerminalRequestClassificationV1(
        authority_generation_sha256=_AUTHORITY,
        committed_observation_generation_sha256=generation.generation_sha256,
        physical_call_id=guessed.physical_call_id,
        request_scope_sha256=guessed.request_scope_sha256,
        disposition=guessed_evidence.disposition,
        evidence=guessed_evidence,
    )
    guessed_shard = RequestUniverseShardV1(
        authority_generation_sha256=_AUTHORITY,
        shard_id="shard-999",
        physical_call_ids=(guessed.physical_call_id,),
    )
    generation_evidence = {item.physical_call_id: item for item in generation.terminal_evidence}
    with pytest.raises(RequestUniverseCandidateContractError, match="dependent-workload"):
        replace(
            source,
            logical_calls=tuple(
                sorted((*source.logical_calls, guessed), key=lambda item: item.physical_call_id)
            ),
            terminal_classifications=tuple(
                sorted(
                    (
                        *(
                            replace(
                                item,
                                committed_observation_generation_sha256=(
                                    generation.generation_sha256
                                ),
                                evidence=generation_evidence[item.physical_call_id],
                            )
                            for item in source.terminal_classifications
                        ),
                        guessed_classification,
                    ),
                    key=lambda item: item.physical_call_id,
                )
            ),
            committed_observation_generation=generation,
            committed_observation_generation_sha256=generation.generation_sha256,
            shards=(*source.shards, guessed_shard),
        )
