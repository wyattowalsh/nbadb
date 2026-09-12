from __future__ import annotations

import ast
import copy
import hashlib
import inspect
import json
from pathlib import Path
from typing import Any, cast

import pytest

from nbadb.orchestrate import request_universe_generation_verifier as verifier
from nbadb.orchestrate.request_universe_generation_contract import (
    CommittedObservationGenerationV1,
    ExplicitTemporalScopeValueV1,
    FieldOccurrenceInputV1,
    LogicalRequestCallV1,
    RequestUniverseCandidateGenerationV1,
    RequestUniverseCandidateSourceV1,
    RequestUniverseFinalizationSourceV1,
    RequestUniverseShardV1,
    RouteRequestMemberV1,
    TemporalScopeKind,
    TerminalRequestClassificationV1,
    TerminalRequestDisposition,
    TerminalRequestEvidenceV1,
    UnintegratedCumeValueV1,
    compile_request_universe_candidate_generation_v1,
    compile_request_universe_v1,
)
from nbadb.orchestrate.request_universe_generation_verifier import (
    IndependentRequestUniverseCandidateError,
    RequestUniverseCandidateIndependentProofV1,
    RequestUniverseIndependentEmptyDeltaReceiptV1,
    RequestUniverseIndependentProofV1,
    verify_request_universe_candidate_independently,
    verify_request_universe_v1_independently,
)

_AUTHORITY = "a" * 64
_FIELD_FATE = "b" * 64
_TEMPORAL = "c" * 64
_CUME = "2a910d5340f8cd24c32ca4494dd1b293f7a790f95a7d5294c1115f340363c6ee"
_CUME_WORKLOAD_JSON = (
    '{"disposition":"complete","entity_id":7,"entity_kind":"player",'
    '"foundation_receipt_sha256":"1111111111111111111111111111111111111111111111111111111111111111",'
    '"game_ids":["0022300001"],"kind":"nbadb_cume_workload",'
    '"provider_authority_sha256":"aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",'
    '"schema_version":1,"season":"2023-24","season_type":"Regular Season",'
    '"typed_zero_reason":null}'
)


def _source_and_candidate() -> tuple[
    RequestUniverseCandidateSourceV1,
    dict[str, object],
]:
    page = LogicalRequestCallV1.from_parameters(
        authority_generation_sha256=_AUTHORITY,
        source_family="stats",
        endpoint_name="player_game_logs_v2",
        canonical_endpoint_name="player_game_logs",
        physical_endpoint_name="player_game_logs_v2",
        parameters={"PlayerID": 7, "Season": "2023-24"},
        pagination_kind="page",
        pagination_value=3,
    )
    dependent = LogicalRequestCallV1.from_parameters(
        authority_generation_sha256=_AUTHORITY,
        source_family="stats",
        endpoint_name="team_and_players_vs_players",
        canonical_endpoint_name="team_and_players_vs",
        physical_endpoint_name="team_and_players_vs_players",
        parameters={"PlayerID": 7, "Season": "2023-24", "TeamID": 11},
        dependent_workload_kind="five_v_five",
        dependent_workload_sha256="d" * 64,
        dependent_physical_alias="team_and_players_vs_players",
    )
    page_route = RouteRequestMemberV1.build(
        call=page,
        route_id="player_game_logs_v2:stg_player_game_logs_v2:0",
        result_name="PlayerGameLogs",
        result_ordinal=0,
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
    periods = (
        ExplicitTemporalScopeValueV1(
            authority_generation_sha256=_AUTHORITY,
            physical_call_id=page_route.physical_call_id,
            route_request_member_id=page_route.route_request_member_id,
            route_id=page_route.route_id,
            endpoint_name=page_route.endpoint_name,
            request_scope_sha256=page_route.request_scope_sha256,
            temporal_contract_sha256=_TEMPORAL,
            temporal_scope_kind=TemporalScopeKind.SEASON,
            temporal_scope_value="2023-24",
        ),
        ExplicitTemporalScopeValueV1(
            authority_generation_sha256=_AUTHORITY,
            physical_call_id=dependent_route.physical_call_id,
            route_request_member_id=dependent_route.route_request_member_id,
            route_id=dependent_route.route_id,
            endpoint_name=dependent_route.endpoint_name,
            request_scope_sha256=dependent_route.request_scope_sha256,
            temporal_contract_sha256=_TEMPORAL,
            temporal_scope_kind=TemporalScopeKind.GAME_ID,
            temporal_scope_value="0022300001",
        ),
    )
    source = RequestUniverseCandidateSourceV1(
        authority_generation_sha256=_AUTHORITY,
        field_fate_contract_sha256=_FIELD_FATE,
        temporal_contract_sha256=_TEMPORAL,
        logical_calls=tuple(sorted((page, dependent), key=lambda item: item.physical_call_id)),
        route_members=tuple(
            sorted(
                (page_route, dependent_route),
                key=lambda item: item.route_request_member_id,
            )
        ),
        field_occurrences=tuple(sorted(fields, key=lambda item: item.identity_sha256)),
        explicit_temporal_scopes=tuple(sorted(periods, key=lambda item: item.identity_sha256)),
        unintegrated_cume_values=(
            UnintegratedCumeValueV1(
                authority_generation_sha256=_AUTHORITY,
                entity_kind="player",
                workload_content_sha256=_CUME,
                workload_canonical_json=_CUME_WORKLOAD_JSON,
                physical_endpoint_aliases=(
                    "cume_stats_player",
                    "cume_stats_player_games",
                ),
            ),
        ),
    )
    return source, compile_request_universe_candidate_generation_v1(source).to_dict()


def _canonical_bytes(value: object) -> bytes:
    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
        allow_nan=False,
    ).encode("utf-8")


def _digest(value: object) -> str:
    return hashlib.sha256(_canonical_bytes(value)).hexdigest()


def _closure_payload(provider_request_sha256s: tuple[str, ...]) -> dict[str, object]:
    units = list(provider_request_sha256s)
    unit_root = _digest(units)
    iteration_zero = {
        "iteration": 0,
        "request_surface_sha256": "1" * 64,
        "scope_sha256": "2" * 64,
        "input_units": [],
        "new_units": units,
        "output_units": units,
        "evidence": [],
    }
    final_iteration = {
        "iteration": 1,
        "request_surface_sha256": "1" * 64,
        "scope_sha256": "2" * 64,
        "input_units": units,
        "new_units": [],
        "output_units": units,
        "evidence": [
            {
                "evidence_kind": "fixed_point",
                "complete": True,
                "discovered_units": [],
                "input_units": units,
            }
        ],
    }
    return {
        "schema_version": 2,
        "kind": "nbadb_request_closure_runtime_receipt",
        "request_surface_sha256": "1" * 64,
        "terminal_policy_sha256": "2" * 64,
        "route_manifest_sha256": "3" * 64,
        "scope_sha256": "2" * 64,
        "unit_inventory_sha256": unit_root,
        "request_binding_inventory_sha256": "4" * 64,
        "terminal_inventory_sha256": "5" * 64,
        "staging_receipt_inventory_sha256": "6" * 64,
        "persisted_staging_receipt_roots": [],
        "persisted_staging_receipt_roots_sha256": _digest([]),
        "route_manifest": {},
        "scope": {},
        "observations": [{"provider_request_sha256": value} for value in provider_request_sha256s],
        "closure": {
            "iterations": [iteration_zero, final_iteration],
            "independent_proof": {
                "verifier_id": "independent_request_closure_v1",
                "unit_inventory_sha256": unit_root,
            },
        },
    }


def _reseal(payload: dict[str, object]) -> dict[str, object]:
    bindings = (
        ("logical_calls", "logical_call_count", "logical_call_inventory_sha256"),
        ("route_members", "route_member_count", "route_member_inventory_sha256"),
        (
            "field_period_cells",
            "field_period_cell_count",
            "field_period_inventory_sha256",
        ),
        ("blockers", "blocker_count", "blocker_inventory_sha256"),
    )
    for inventory_name, count_name, digest_name in bindings:
        inventory = payload[inventory_name]
        assert isinstance(inventory, list)
        payload[count_name] = len(inventory)
        payload[digest_name] = _digest(inventory)
    return payload


def _candidate_copy() -> tuple[dict[str, object], dict[str, object]]:
    source, candidate = _source_and_candidate()
    return copy.deepcopy(source.to_dict()), copy.deepcopy(candidate)


def test_independent_known_answer_exactly_matches_primary_candidate() -> None:
    source, candidate = _source_and_candidate()
    proof = verify_request_universe_candidate_independently(
        source_payload=source.to_dict(),
        candidate_payload=candidate,
    )

    assert proof.identity_sha256 == (
        "02ab13f595ea5e61c071b8840a2259ed6fc571ae1ea758df504642674b9d2148"
    )
    assert proof.candidate_generation_sha256 == (
        "bf82aa0973fcc7eea20cfbd94718422cc55e2a59830b016cd3387da6a8f8ec92"
    )
    assert proof.source_inputs_sha256 == source.source_inputs_sha256
    assert proof.logical_call_count == 2
    assert proof.route_member_count == 2
    assert proof.field_period_cell_count == 3
    assert proof.blocker_count == 2
    assert proof.exact_inventory_equal is True
    assert proof.candidate_only is True
    assert proof.terminal is False
    assert proof.release_eligible is False
    assert (
        RequestUniverseCandidateIndependentProofV1.from_canonical_bytes(proof.canonical_bytes)
        == proof
    )


@pytest.mark.parametrize(
    "inventory_name",
    ["logical_calls", "route_members", "field_period_cells", "blockers"],
)
def test_independent_verifier_rejects_removed_and_resealed_members(
    inventory_name: str,
) -> None:
    source, candidate = _candidate_copy()
    inventory = candidate[inventory_name]
    assert isinstance(inventory, list) and inventory
    inventory.pop()
    _reseal(candidate)

    with pytest.raises(
        IndependentRequestUniverseCandidateError,
        match="differs|non-fixed-point",
    ):
        verify_request_universe_candidate_independently(
            source_payload=source,
            candidate_payload=candidate,
        )


def _mutate_endpoint(payload: dict[str, object]) -> None:
    calls = cast_list(payload["logical_calls"])
    calls[0]["endpoint_name"] = "forged_endpoint"


def _mutate_result(payload: dict[str, object]) -> None:
    routes = cast_list(payload["route_members"])
    routes[0]["result_name"] = "ForgedResult"


def _mutate_field(payload: dict[str, object]) -> None:
    cells = cast_list(payload["field_period_cells"])
    cells[0]["provider_field"] = "FORGED_FIELD"


def _mutate_period(payload: dict[str, object]) -> None:
    cells = cast_list(payload["field_period_cells"])
    target = next(cell for cell in cells if cell["temporal_scope_kind"] == "season")
    target["temporal_scope_value"] = "2022-23"


def _mutate_pagination(payload: dict[str, object]) -> None:
    calls = cast_list(payload["logical_calls"])
    target = next(call for call in calls if call["pagination_kind"] == "page")
    target["pagination_value"] = 99


def _mutate_dependent(payload: dict[str, object]) -> None:
    calls = cast_list(payload["logical_calls"])
    target = next(call for call in calls if call["dependent_workload_sha256"] is not None)
    target["dependent_physical_alias"] = "forged_dependent_alias"


def _mutate_cume(payload: dict[str, object]) -> None:
    blockers = cast_list(payload["blockers"])
    blocker = next(item for item in blockers if item["blocker_code"] == "unintegrated_cume_value")
    blocker["subject_id"] = "9" * 64


def cast_list(value: object) -> list[dict[str, Any]]:
    assert isinstance(value, list)
    assert all(isinstance(item, dict) for item in value)
    return cast("list[dict[str, Any]]", value)


@pytest.mark.parametrize(
    "mutation",
    [
        _mutate_endpoint,
        _mutate_result,
        _mutate_field,
        _mutate_period,
        _mutate_pagination,
        _mutate_dependent,
        _mutate_cume,
    ],
    ids=["endpoint", "result", "field", "period", "pagination", "dependent", "cume"],
)
def test_independent_verifier_rejects_replaced_and_resealed_dimensions(
    mutation: Any,
) -> None:
    source, candidate = _candidate_copy()
    mutation(candidate)
    _reseal(candidate)

    with pytest.raises(
        IndependentRequestUniverseCandidateError,
        match="differs|sorted",
    ):
        verify_request_universe_candidate_independently(
            source_payload=source,
            candidate_payload=candidate,
        )


@pytest.mark.parametrize("field_name", ["terminal", "release_eligible"])
def test_independent_verifier_rejects_premature_finality(field_name: str) -> None:
    source, candidate = _candidate_copy()
    candidate[field_name] = True

    with pytest.raises(IndependentRequestUniverseCandidateError, match="cannot be terminal"):
        verify_request_universe_candidate_independently(
            source_payload=source,
            candidate_payload=candidate,
        )


def _mutate_false_to_integer(payload: dict[str, object]) -> None:
    payload["terminal"] = 0
    payload["release_eligible"] = 0


def _mutate_schema_integer_to_bool(payload: dict[str, object]) -> None:
    payload["schema_version"] = True


def _mutate_pagination_integer_to_float(payload: dict[str, object]) -> None:
    calls = cast_list(payload["logical_calls"])
    target = next(call for call in calls if call["pagination_kind"] == "page")
    target["pagination_value"] = float(target["pagination_value"])


def _mutate_result_ordinal_integer_to_bool(payload: dict[str, object]) -> None:
    routes = cast_list(payload["route_members"])
    target = next(route for route in routes if route["result_ordinal"] == 1)
    target["result_ordinal"] = True


def _mutate_nested_parameter_integer_to_float(payload: dict[str, object]) -> None:
    calls = cast_list(payload["logical_calls"])
    parameters = cast_list(calls[0]["parameter_items"])
    target = next(parameter for parameter in parameters if parameter["name"] == "PlayerID")
    target["value"] = float(target["value"])


def _mutate_nested_path_index_to_bool(payload: dict[str, object]) -> None:
    routes = cast_list(payload["route_members"])
    target = next(route for route in routes if route["nested_path"])
    target["nested_path"] = [True]


def _mutate_nested_cell_ordinal_to_bool(payload: dict[str, object]) -> None:
    cells = cast_list(payload["field_period_cells"])
    cells[0]["field_occurrence_ordinal"] = False


@pytest.mark.parametrize(
    "mutation",
    [
        _mutate_false_to_integer,
        _mutate_schema_integer_to_bool,
        _mutate_pagination_integer_to_float,
        _mutate_result_ordinal_integer_to_bool,
        _mutate_nested_parameter_integer_to_float,
        _mutate_nested_path_index_to_bool,
        _mutate_nested_cell_ordinal_to_bool,
    ],
    ids=[
        "false-to-zero",
        "schema-int-to-bool",
        "pagination-int-to-float",
        "ordinal-int-to-bool",
        "nested-parameter-int-to-float",
        "nested-path-index-to-bool",
        "nested-cell-ordinal-to-bool",
    ],
)
def test_independent_verifier_rejects_python_equality_type_confusions(
    mutation: Any,
) -> None:
    source, candidate = _candidate_copy()
    mutation(candidate)

    with pytest.raises(IndependentRequestUniverseCandidateError):
        verify_request_universe_candidate_independently(
            source_payload=source,
            candidate_payload=candidate,
        )


def test_independent_verifier_rejects_boolean_source_schema_version() -> None:
    source, candidate = _candidate_copy()
    source["schema_version"] = True

    with pytest.raises(IndependentRequestUniverseCandidateError, match="schema identity"):
        verify_request_universe_candidate_independently(
            source_payload=source,
            candidate_payload=candidate,
        )


def test_independent_verifier_rejects_forged_cume_alias_and_content_bindings() -> None:
    source, candidate = _candidate_copy()
    cume = cast_list(source["unintegrated_cume_values"])[0]
    cume["physical_endpoint_aliases"] = ["forged_cume_alias"]
    with pytest.raises(IndependentRequestUniverseCandidateError, match="entity-bound set"):
        verify_request_universe_candidate_independently(
            source_payload=source,
            candidate_payload=candidate,
        )

    source, candidate = _candidate_copy()
    cume = cast_list(source["unintegrated_cume_values"])[0]
    cume["entity_kind"] = "team"
    cume["physical_endpoint_aliases"] = [
        "cume_stats_team",
        "cume_stats_team_games",
    ]
    with pytest.raises(IndependentRequestUniverseCandidateError, match="rebound"):
        verify_request_universe_candidate_independently(
            source_payload=source,
            candidate_payload=candidate,
        )

    source, candidate = _candidate_copy()
    cume = cast_list(source["unintegrated_cume_values"])[0]
    cume["workload_content_sha256"] = "9" * 64
    with pytest.raises(IndependentRequestUniverseCandidateError, match="content digest"):
        verify_request_universe_candidate_independently(
            source_payload=source,
            candidate_payload=candidate,
        )


def test_independent_verifier_rejects_source_authority_and_typed_period_drift() -> None:
    source, candidate = _candidate_copy()
    calls = cast_list(source["logical_calls"])
    calls[0]["authority_generation_sha256"] = "f" * 64
    with pytest.raises(IndependentRequestUniverseCandidateError, match="mixed authority"):
        verify_request_universe_candidate_independently(
            source_payload=source,
            candidate_payload=candidate,
        )

    source, candidate = _candidate_copy()
    periods = cast_list(source["explicit_temporal_scopes"])
    periods[0]["temporal_scope_kind"] = "season"
    periods[0]["temporal_scope_value"] = "2023-25"
    with pytest.raises(IndependentRequestUniverseCandidateError, match="season value"):
        verify_request_universe_candidate_independently(
            source_payload=source,
            candidate_payload=candidate,
        )


def test_proof_parser_rejects_noncanonical_duplicate_and_finality_bytes() -> None:
    source, candidate = _source_and_candidate()
    proof = verify_request_universe_candidate_independently(
        source_payload=source.to_dict(), candidate_payload=candidate
    )
    with pytest.raises(IndependentRequestUniverseCandidateError, match="not exact canonical"):
        RequestUniverseCandidateIndependentProofV1.from_canonical_bytes(
            proof.canonical_bytes + b"\n"
        )
    duplicate = proof.canonical_bytes.replace(
        b'"terminal":false', b'"terminal":false,"terminal":false'
    )
    with pytest.raises(IndependentRequestUniverseCandidateError, match="duplicate keys"):
        RequestUniverseCandidateIndependentProofV1.from_canonical_bytes(duplicate)
    payload = proof.to_dict()
    payload["terminal"] = True
    with pytest.raises(IndependentRequestUniverseCandidateError, match="cannot attest"):
        RequestUniverseCandidateIndependentProofV1.from_dict(payload)


def _final_source_and_universe():
    _source, candidate_payload = _source_and_candidate()
    candidate = RequestUniverseCandidateGenerationV1.from_dict(candidate_payload)
    checkpoint = "4" * 64
    w2 = "6" * 64
    temporal = candidate.field_period_inventory_sha256
    provider_request_sha256s = tuple(
        sorted(f"{index + 1}" * 64 for index, _call in enumerate(candidate.logical_calls))
    )
    closure_payload = _closure_payload(provider_request_sha256s)
    closure = _digest(closure_payload)
    generation_key = _digest(
        {
            "authority_generation_sha256": _AUTHORITY,
            "checkpoint_identity_sha256": checkpoint,
            "request_closure_receipt_sha256": closure,
            "w2_authority_identity_sha256": w2,
            "temporal_field_denominator_sha256": temporal,
            "closure_fixed_point_provider_request_inventory_sha256": _digest(
                list(provider_request_sha256s)
            ),
            "parent_observation_generation_sha256": None,
            "generation_ordinal": 1,
        }
    )
    evidence = tuple(
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
            request_observation_sha256=f"{index + 3}" * 64,
            request_call=call,
            disposition=(
                TerminalRequestDisposition.CAPTURED_NONEMPTY
                if index == 0
                else TerminalRequestDisposition.CAPTURED_PRESENT_EMPTY
            ),
            captured_row_count=1 if index == 0 else 0,
            result_receipt_count=1,
            staging_receipt_count=1,
            result_receipt_inventory_sha256="7" * 64,
            staging_receipt_inventory_sha256="8" * 64,
        )
        for index, call in enumerate(candidate.logical_calls)
    )
    generation = CommittedObservationGenerationV1(
        authority_generation_sha256=_AUTHORITY,
        checkpoint_identity_sha256=checkpoint,
        request_closure_receipt_sha256=closure,
        w2_authority_identity_sha256=w2,
        temporal_field_denominator_sha256=temporal,
        closure_fixed_point_provider_request_sha256s=provider_request_sha256s,
        terminal_evidence=evidence,
    )
    evidence_by_call = {item.physical_call_id: item for item in evidence}
    classifications = tuple(
        TerminalRequestClassificationV1(
            authority_generation_sha256=_AUTHORITY,
            committed_observation_generation_sha256=generation.generation_sha256,
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
    source = RequestUniverseFinalizationSourceV1(
        authority_generation_sha256=_AUTHORITY,
        checkpoint_identity_sha256=checkpoint,
        checkpoint_authority_generation_sha256=_AUTHORITY,
        request_closure_receipt_sha256=closure,
        request_closure_authority_generation_sha256=_AUTHORITY,
        w2_authority_identity_sha256=w2,
        w2_authority_generation_sha256=_AUTHORITY,
        temporal_field_denominator_sha256=temporal,
        temporal_field_authority_generation_sha256=_AUTHORITY,
        committed_observation_generation_sha256=generation.generation_sha256,
        committed_observation_authority_generation_sha256=_AUTHORITY,
        candidate_source_sha256=candidate.source_inputs_sha256,
        candidate_generation_sha256=candidate.identity_sha256,
        candidate_independent_proof_sha256="7" * 64,
        source_admission_sha256="8" * 64,
        committed_observation_generation=generation,
        logical_calls=candidate.logical_calls,
        terminal_classifications=classifications,
        shards=shards,
    )
    return source, compile_request_universe_v1(source), closure_payload


def test_final_independent_verifier_rederives_exact_empty_delta() -> None:
    source, universe, closure_payload = _final_source_and_universe()
    proof, receipt = verify_request_universe_v1_independently(
        finalization_source_payload=source.to_dict(),
        request_universe_payload=universe.to_dict(),
        request_closure_payload=closure_payload,
    )

    assert type(proof) is RequestUniverseIndependentProofV1
    assert type(receipt) is RequestUniverseIndependentEmptyDeltaReceiptV1
    assert receipt.delta_count == 0
    assert receipt.derivation_input_sha256 == (
        source.committed_observation_generation.generation_sha256
    )
    assert receipt.derived_call_inventory_sha256 == (
        source.committed_observation_generation.next_generation_call_inventory_sha256
    )


def test_final_independent_verifier_rejects_caller_supplied_next_calls() -> None:
    source, universe, closure_payload = _final_source_and_universe()
    payload = source.to_dict()
    generation = cast("dict[str, object]", payload["committed_observation_generation"])
    calls = cast_list(generation["next_generation_calls"])
    extra = LogicalRequestCallV1.from_parameters(
        authority_generation_sha256=_AUTHORITY,
        source_family="stats",
        endpoint_name="player_game_logs_v2",
        canonical_endpoint_name="player_game_logs",
        physical_endpoint_name="player_game_logs_v2",
        parameters={"PlayerID": 99, "Season": "2023-24"},
    ).to_dict()
    calls.append(extra)
    calls.sort(key=lambda item: cast("str", item["physical_call_id"]))
    generation["next_generation_call_count"] = len(calls)
    generation["next_generation_call_inventory_sha256"] = _digest(calls)
    generation_body = dict(generation)
    generation_body.pop("generation_sha256")
    generation["generation_sha256"] = _digest(generation_body)
    payload["committed_observation_generation_sha256"] = generation["generation_sha256"]
    for classification in cast_list(payload["terminal_classifications"]):
        classification["committed_observation_generation_sha256"] = generation["generation_sha256"]

    with pytest.raises(
        IndependentRequestUniverseCandidateError,
        match="serialized next-generation calls",
    ):
        verify_request_universe_v1_independently(
            finalization_source_payload=payload,
            request_universe_payload=universe.to_dict(),
            request_closure_payload=closure_payload,
        )


def test_final_independent_verifier_rejects_typed_evidence_and_partition_drift() -> None:
    source, universe, closure_payload = _final_source_and_universe()
    malformed = source.to_dict()
    generation = cast("dict[str, object]", malformed["committed_observation_generation"])
    evidence = cast_list(generation["terminal_evidence"])[0]
    evidence["captured_row_count"] = 0
    with pytest.raises(IndependentRequestUniverseCandidateError, match="row count"):
        verify_request_universe_v1_independently(
            finalization_source_payload=malformed,
            request_universe_payload=universe.to_dict(),
            request_closure_payload=closure_payload,
        )

    missing_capture_receipt = source.to_dict()
    missing_generation = cast(
        "dict[str, object]",
        missing_capture_receipt["committed_observation_generation"],
    )
    missing_evidence = cast_list(missing_generation["terminal_evidence"])[0]
    missing_evidence["result_receipt_count"] = 0
    with pytest.raises(
        IndependentRequestUniverseCandidateError,
        match="present result/staging receipts",
    ):
        verify_request_universe_v1_independently(
            finalization_source_payload=missing_capture_receipt,
            request_universe_payload=universe.to_dict(),
            request_closure_payload=closure_payload,
        )

    overlap = source.to_dict()
    shards = cast_list(overlap["shards"])
    shard_ids = cast("list[str]", shards[0]["physical_call_ids"])
    second_ids = cast("list[str]", shards[1]["physical_call_ids"])
    second_ids.append(shard_ids[0])
    second_ids.sort()
    shards[1]["request_inventory_sha256"] = _digest(second_ids)
    with pytest.raises(IndependentRequestUniverseCandidateError, match="partition"):
        verify_request_universe_v1_independently(
            finalization_source_payload=overlap,
            request_universe_payload=universe.to_dict(),
            request_closure_payload=closure_payload,
        )


def test_final_independent_verifier_rejects_primary_compiler_disagreement() -> None:
    source, universe, closure_payload = _final_source_and_universe()
    payload = universe.to_dict()
    payload["checkpoint_identity_sha256"] = "f" * 64
    with pytest.raises(IndependentRequestUniverseCandidateError, match="disagrees"):
        verify_request_universe_v1_independently(
            finalization_source_payload=source.to_dict(),
            request_universe_payload=payload,
            request_closure_payload=closure_payload,
        )


def test_verifier_ast_has_a_hard_primary_import_boundary() -> None:
    path = Path(inspect.getsourcefile(verifier) or "")
    source = path.read_text(encoding="utf-8")
    tree = ast.parse(source)
    imported = {
        alias.name
        for node in ast.walk(tree)
        if isinstance(node, (ast.Import, ast.ImportFrom))
        for alias in node.names
    }

    assert "request_universe_generation_contract" not in source
    assert not any(name.startswith("nbadb") for name in imported)
    assert not {
        "canonical_request_universe_json_bytes",
        "canonical_request_universe_sha256",
        "compile_request_universe_candidate_generation_v1",
    } & {node.id for node in ast.walk(tree) if isinstance(node, ast.Name)}
