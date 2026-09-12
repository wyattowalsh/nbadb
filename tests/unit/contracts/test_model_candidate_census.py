from __future__ import annotations

import json
from collections import Counter
from dataclasses import replace

import pytest

from nbadb.contracts import model_candidate_census as census_module
from nbadb.contracts.field_fate_structure import compile_field_fate_structure
from nbadb.contracts.model_candidate_census import (
    AnalyticalNeedsAuthorityV1,
    ModelCandidateCensusError,
    ModelCandidateCensusV1,
    canonical_analytical_needs_authority_v1,
    compile_model_candidate_census,
    parse_model_candidate_census,
    validate_model_candidate_census,
)
from nbadb.contracts.staging_route_contract import staging_route_contract_bundle
from nbadb.contracts.star_table_contract import compile_star_table_contracts


@pytest.fixture(scope="module")
def field_structure():
    return compile_field_fate_structure()


@pytest.fixture(scope="module")
def star_inventory():
    return compile_star_table_contracts()


@pytest.fixture(scope="module")
def analytical_needs():
    return canonical_analytical_needs_authority_v1()


@pytest.fixture(scope="module")
def census(field_structure, star_inventory, analytical_needs):
    return compile_model_candidate_census(
        field_structure=field_structure,
        star_inventory=star_inventory,
        analytical_needs=analytical_needs,
    )


def _payload(evidence) -> dict[str, object]:
    value = json.loads(evidence.structural_payload_json)
    assert type(value) is dict
    return value


def test_explicit_analytical_needs_authority_is_complete_and_canonical(
    analytical_needs,
) -> None:
    assert tuple(item.model_family for item in analytical_needs.needs) == (
        "forecast",
        "prospect_value",
        "rapm",
        "rating",
        "wpa",
        "xfg",
    )
    assert all(item.analytical_question for item in analytical_needs.needs)
    assert all(item.required_candidate_ids == () for item in analytical_needs.needs)
    assert (
        AnalyticalNeedsAuthorityV1.from_canonical_bytes(analytical_needs.canonical_bytes)
        == analytical_needs
    )


def test_census_has_exact_structurally_derived_candidate_counts(census) -> None:
    assert len(census.candidates) == 1_128
    assert Counter(item.candidate_kind for item in census.candidates) == {
        "source": 417,
        "staging": 444,
        "dimension": 18,
        "fact": 197,
        "bridge": 5,
        "aggregate": 19,
        "analytics": 14,
        "live": 8,
        "experimental_model": 6,
    }
    assert len(census.evidence) == len(census.candidates)
    assert census.to_stable_candidates() == census.candidates


def test_provider_source_candidates_preserve_every_field_occurrence(
    census,
    field_structure,
) -> None:
    source_evidence = [
        item for item in census.evidence if item.evidence_kind == "provider_result_occurrence"
    ]
    payloads = [_payload(item) for item in source_evidence]

    assert len(source_evidence) == 417
    assert sum(int(item["field_count"]) for item in payloads) == len(
        field_structure.provider_sources.occurrences
    )
    observed_occurrences = {
        occurrence_id for item in payloads for occurrence_id in item["field_occurrence_ids"]
    }
    assert observed_occurrences == {
        item.occurrence_id for item in field_structure.provider_sources.occurrences
    }


def test_exact_named_zero_field_results_and_video_conditional_authority(census) -> None:
    zero_payloads = [
        _payload(item)
        for item in census.evidence
        if item.evidence_kind == "provider_result_occurrence" and _payload(item)["field_count"] == 0
    ]
    payload_by_route = {route_id: item for item in zero_payloads for route_id in item["route_ids"]}
    candidates = {item.candidate_id: item for item in census.candidates}

    assert len(zero_payloads) == 6
    assert set(payload_by_route) == {
        "defense_hub:stg_defense_hub_stat10:1",
        "scoreboard_v2:stg_scoreboard_win_probability:9",
        "video_events:stg_video_events:0",
        "video_events_asset:stg_video_events_asset:0",
        "video_details:stg_video_details:0",
        "video_details_asset:stg_video_details_asset:0",
    }
    terminal_routes = {
        "defense_hub:stg_defense_hub_stat10:1",
        "scoreboard_v2:stg_scoreboard_win_probability:9",
    }
    assert {
        route_id
        for route_id, payload in payload_by_route.items()
        if payload["zero_field_result_contract_state"] == "explicit_named_zero_columns"
    } == terminal_routes
    for route_id in terminal_routes:
        payload = payload_by_route[route_id]
        assert payload["explicit_zero_field_contract"] is True
        assert payload["terminal_result_authority"] == "typed_present_empty_or_placeholder"
        assert payload["field_occurrence_ids"] == []
        assert payload["field_count"] == 0
        assert payload["route_binding_ids"] == []
        assert payload["lossless_field_binding_count"] == 0
    assert candidates["source:stats:DefenseHub:0001"].implementation_status == "implemented"
    assert candidates["source:stats:ScoreboardV2:0009"].implementation_status == "implemented"

    video_routes = set(payload_by_route) - terminal_routes
    conditional_implementation_sha256s = set()
    for route_id in video_routes:
        payload = payload_by_route[route_id]
        assert payload["explicit_zero_field_contract"] is False
        assert payload["zero_field_result_contract_state"] == "provider_result_contract_unknown"
        assert payload["terminal_result_authority"] == "unresolved"
        assert payload["conditional_lossless_binding"] is True
        assert payload["conditional_lossless_staging_key"] == "stg_nba_api_lossless_result_cells"
        assert len(payload["conditional_lossless_schema_sha256"]) == 64
        assert len(payload["conditional_lossless_validation_sha256"]) == 64
        conditional_implementation_sha256s.add(
            payload["conditional_lossless_implementation_sha256"]
        )
    assert len(conditional_implementation_sha256s) == 1
    video_candidates = {
        "source:stats:VideoDetails:0000",
        "source:stats:VideoDetailsAsset:0000",
        "source:stats:VideoEvents:0000",
        "source:stats:VideoEventsAsset:0000",
    }
    assert all(candidates[item].implementation_status == "implemented" for item in video_candidates)
    assert all(candidates[item].implementation_sha256 is not None for item in video_candidates)
    zero_blockers = [
        item for item in census.blockers if item.code == "source_result_contract_zero_fields"
    ]
    assert zero_blockers == []


def test_generic_named_zero_field_route_is_not_admitted(
    field_structure,
) -> None:
    routes = staging_route_contract_bundle()
    exact = routes.by_route_id["defense_hub:stg_defense_hub_stat10:1"]
    generic = replace(
        exact,
        route_id="generic_zero:stg_generic_zero:0",
        endpoint_name="generic_zero",
        staging_key="stg_generic_zero",
        provider_endpoint_id="GenericZero",
        canonical_provider_endpoint_id="GenericZero",
        provider_runtime_class="GenericZero",
        canonical_runtime_class="GenericZero",
        provider_runtime_module="nba_api.stats.endpoints.genericzero",
        provider_endpoint_slug="genericzero",
        provider_result_set_name="GenericZeroResult",
        provider_result_set_ordinal=0,
        canonical_result_set_name="GenericZeroResult",
        canonical_result_set_ordinal=0,
        declared_result_set_index=0,
    )
    mutated_routes = replace(routes, routes=(generic,))

    candidates, evidence, blockers, _by_occurrence, _by_route = (
        census_module._compile_source_candidates(field_structure, mutated_routes)
    )
    candidate_id = "source:stats:GenericZero:0000"
    candidate = next(item for item in candidates if item.candidate_id == candidate_id)
    payload = _payload(next(item for item in evidence if item.candidate_id == candidate_id))

    assert candidate.implementation_status == "missing"
    assert candidate.implementation_sha256 is None
    assert payload["zero_field_result_contract_state"] == "provider_result_contract_unknown"
    assert payload["terminal_result_authority"] == "unresolved"
    assert payload["conditional_lossless_binding"] is False
    assert payload["conditional_lossless_staging_key"] is None
    assert any(
        item.subject_id == candidate_id and item.code == "source_result_contract_zero_fields"
        for item in blockers
    )


def test_all_wide_unrouted_fields_have_lossless_binding_evidence(census) -> None:
    payloads = [
        _payload(item)
        for item in census.evidence
        if item.evidence_kind == "provider_result_occurrence"
    ]

    assert sum(int(item["wide_unrouted_field_count"]) for item in payloads) == 276
    assert sum(int(item["lossless_field_binding_count"]) for item in payloads) == 276
    assert sum(int(item["unresolved_lossless_binding_count"]) for item in payloads) == 0
    assert not any(item.code == "lossless_storage_binding_unresolved" for item in census.blockers)


def test_missing_live_docs_authority_remains_field_level_and_open(census) -> None:
    source_blockers = [
        item for item in census.blockers if item.code == "source_authority_unavailable"
    ]

    assert len(source_blockers) == 21
    assert len({item.evidence_sha256 for item in source_blockers}) == 21
    assert all(item.subject_id.startswith("source:live:") for item in source_blockers)


def test_staging_candidates_include_exact_four_raw_authority_tables(census) -> None:
    staging_evidence = [
        item
        for item in census.evidence
        if item.evidence_kind in {"staging_route", "conditional_staging", "raw_request_authority"}
    ]

    assert Counter(item.evidence_kind for item in staging_evidence) == {
        "staging_route": 438,
        "conditional_staging": 2,
        "raw_request_authority": 4,
    }
    assert {
        item.candidate_id
        for item in staging_evidence
        if item.evidence_kind == "conditional_staging"
    } == {
        "staging:stg_nba_api_live_lossless_nodes",
        "staging:stg_nba_api_lossless_result_cells",
    }
    assert {
        item.candidate_id
        for item in staging_evidence
        if item.evidence_kind == "raw_request_authority"
    } == {
        "staging:raw_nba_api_parser_input_object",
        "staging:raw_nba_api_request_observation",
        "staging:raw_nba_api_result_occurrence",
        "staging:raw_nba_api_observation_route_landing",
    }


@pytest.mark.parametrize(
    "mutation",
    [
        lambda values: values[:-1],
        lambda values: (*values, values[-1]),
        lambda values: (*values[:-2], values[-1], values[-2]),
        lambda values: (
            *values[:-1],
            replace(values[-1], schema_type=values[-2].schema_type),
        ),
    ],
)
def test_raw_authority_census_rejects_non_exact_four_table_closure(
    monkeypatch,
    mutation,
) -> None:
    from nbadb.orchestrate import raw_publication_inventory

    exact = raw_publication_inventory.raw_request_authority_private_tables()
    monkeypatch.setattr(
        raw_publication_inventory,
        "raw_request_authority_private_tables",
        lambda: mutation(exact),
    )

    with pytest.raises(ModelCandidateCensusError, match="inventory drifted"):
        census_module._raw_request_authority_rows()


def test_route_staging_dependencies_are_only_exact_source_bindings(census) -> None:
    candidates = {item.candidate_id: item for item in census.candidates}
    route_evidence = [item for item in census.evidence if item.evidence_kind == "staging_route"]

    for evidence in route_evidence:
        candidate = candidates[evidence.candidate_id]
        assert all(item.startswith("source:") for item in candidate.dependency_ids)
        payload = _payload(evidence)
        assert payload["route_ids"]
        assert payload["staging_key"] == evidence.candidate_id.removeprefix("staging:")


def test_staging_candidates_partition_declared_and_request_scope_storage(
    census,
    field_structure,
) -> None:
    route_evidence = [item for item in census.evidence if item.evidence_kind == "staging_route"]
    payloads = [_payload(item) for item in route_evidence]

    assert sum(int(item["storage_sink_count"]) for item in payloads) == len(
        field_structure.storage_sinks.sinks
    )
    assert sum(int(item["request_scope_storage_sink_count"]) for item in payloads) == 608
    assert sum(int(item["declared_storage_sink_count"]) for item in payloads) == 12_652
    for payload in payloads:
        assert int(payload["storage_sink_count"]) == int(
            payload["declared_storage_sink_count"]
        ) + int(payload["request_scope_storage_sink_count"])
        assert payload["storage_columns"] == [
            *payload["declared_storage_columns"],
            *payload["request_scope_storage_columns"],
        ]

    all_time = _payload(
        next(item for item in route_evidence if item.candidate_id == "staging:stg_all_time")
    )
    assert all_time["declared_storage_columns"] == [
        "player_id",
        "player_name",
        "ast",
        "ast_rank",
    ]
    assert all_time["request_scope_storage_columns"] == ["season_type", "league_id"]


def test_staging_candidate_census_rejects_rebound_request_scope_sink(
    field_structure,
    star_inventory,
    analytical_needs,
) -> None:
    sinks = list(field_structure.storage_sinks.sinks)
    target_index = next(
        index
        for index, sink in enumerate(sinks)
        if sink.route_id == "all_time_leaders_grids:stg_all_time:0"
        and sink.storage_column == "season_type"
    )
    sinks[target_index] = replace(sinks[target_index], storage_column="foreign_scope")
    mutated_sinks = replace(field_structure.storage_sinks, sinks=tuple(sinks))
    mutated_structure = replace(field_structure, storage_sinks=mutated_sinks)

    with pytest.raises(
        ModelCandidateCensusError,
        match="route/storage mismatch for all_time_leaders_grids:stg_all_time:0",
    ):
        compile_model_candidate_census(
            field_structure=mutated_structure,
            star_inventory=star_inventory,
            analytical_needs=analytical_needs,
        )


def test_video_event_routes_use_exact_nonempty_lossless_storage(census) -> None:
    blocked = {
        item.subject_id for item in census.blockers if item.code == "staging_route_zero_storage"
    }
    candidates = {item.candidate_id: item for item in census.candidates}
    evidence_by_candidate = {
        item.candidate_id: item for item in census.evidence if item.evidence_kind == "staging_route"
    }
    video_staging = {
        "staging:stg_video_events",
        "staging:stg_video_events_asset",
    }

    assert blocked == set()
    assert all(candidates[item].implementation_status == "implemented" for item in video_staging)
    for candidate_id in video_staging:
        payload = _payload(evidence_by_candidate[candidate_id])
        assert payload["explicit_zero_storage_route"] is False
        assert payload["storage_sink_count"] > 0
        assert payload["storage_columns"]


def test_star_candidates_bind_all_261_public_outputs(census, star_inventory) -> None:
    star_candidates = [
        item
        for item in census.candidates
        if item.candidate_kind in {"dimension", "fact", "bridge", "aggregate", "analytics", "live"}
    ]

    assert len(star_candidates) == len(star_inventory.tables) == 261
    assert {item.candidate_id.removeprefix("star:") for item in star_candidates} == {
        item.output_name for item in star_inventory.tables
    }


def test_star_evidence_binds_exact_schema_and_transform_implementations(
    census,
    star_inventory,
) -> None:
    table_by_name = {item.output_name: item for item in star_inventory.tables}
    public_evidence = [item for item in census.evidence if item.evidence_kind == "public_transform"]

    assert len(public_evidence) == 261
    for evidence in public_evidence:
        payload = _payload(evidence)
        table = table_by_name[str(payload["output_name"])]
        assert payload["schema_module"] == table.schema_module
        assert payload["schema_class"] == table.schema_class
        assert payload["schema_sha256"] == table.schema_sha256
        assert payload["transform_implementation_sha256"] == table.transform.implementation_sha256
        assert payload["star_contract_sha256"] == table.contract_sha256


def test_star_dependencies_have_explicit_transform_dependency_proofs(census) -> None:
    candidates = {item.candidate_id: item for item in census.candidates}
    for evidence in census.evidence:
        if evidence.evidence_kind != "public_transform":
            continue
        payload = _payload(evidence)
        proofs = {
            (item["transform_dependency"], item["candidate_id"])
            for item in payload["dependency_proofs"]
        }
        assert {item[1] for item in proofs} == set(candidates[evidence.candidate_id].dependency_ids)
        assert {item[0] for item in proofs} == set(payload["transform_dependencies"])
        assert payload["unresolved_transform_dependencies"] == []


def test_video_event_star_outputs_have_nonempty_lossless_contracts(census) -> None:
    blockers = [item for item in census.blockers if item.code == "star_structural_blocker"]
    candidates = {item.candidate_id: item for item in census.candidates}
    video_facts = {
        "star:fact_video_events",
        "star:fact_video_events_asset",
    }

    assert blockers == []
    assert all(candidates[item].implementation_status == "implemented" for item in video_facts)
    assert all(candidates[item].implementation_sha256 is not None for item in video_facts)


def test_experimental_candidates_come_only_from_explicit_needs(census, analytical_needs) -> None:
    experimental = [
        item for item in census.candidates if item.candidate_kind == "experimental_model"
    ]

    assert {item.candidate_id for item in experimental} == {
        item.candidate_id for item in analytical_needs.needs
    }
    assert all(item.implementation_status == "missing" for item in experimental)
    assert all(item.gate_requirement == "experimental_only" for item in experimental)


def test_census_never_claims_model_or_data_green(census) -> None:
    summary = census.to_dict()["summary"]
    assert type(summary) is dict
    assert summary["model_green"] == "not_evaluated_by_structural_census"
    assert summary["data_green"] == "not_evaluated_by_structural_census"
    assert len(census.blockers) == 21


def test_canonical_roundtrip_preserves_all_digests(census) -> None:
    parsed = parse_model_candidate_census(census.canonical_bytes)

    assert parsed == census
    assert parsed.census_sha256 == census.census_sha256
    assert parsed.candidate_inventory_sha256 == census.candidate_inventory_sha256
    assert parsed.evidence_inventory_sha256 == census.evidence_inventory_sha256
    assert parsed.blocker_inventory_sha256 == census.blocker_inventory_sha256
    assert len(census.candidate_source_authority_sha256) == 64


def test_bound_recomputation_accepts_the_exact_census(
    census,
    field_structure,
    star_inventory,
    analytical_needs,
) -> None:
    validate_model_candidate_census(
        census,
        field_structure=field_structure,
        star_inventory=star_inventory,
        analytical_needs=analytical_needs,
    )


@pytest.mark.parametrize(
    ("analytical_needs_input", "state", "blocker_code"),
    [
        (None, "absent", "analytical_needs_authority_absent"),
        (object(), "foreign", "analytical_needs_authority_foreign"),
    ],
)
def test_absent_or_foreign_analytical_needs_remain_explicit_blockers(
    analytical_needs_input,
    state,
    blocker_code,
    field_structure,
    star_inventory,
) -> None:
    result = compile_model_candidate_census(
        field_structure=field_structure,
        star_inventory=star_inventory,
        analytical_needs=analytical_needs_input,
    )

    assert result.analytical_needs_state == state
    assert len(result.candidates) == 1_122
    assert not any(item.candidate_kind == "experimental_model" for item in result.candidates)
    assert blocker_code in {item.code for item in result.blockers}


def test_forged_blocker_receipt_fails_exact_recomputation(
    census,
    field_structure,
    star_inventory,
    analytical_needs,
) -> None:
    forged = replace(census, blockers=census.blockers[1:])

    with pytest.raises(ModelCandidateCensusError, match="exact structural recomputation"):
        validate_model_candidate_census(
            forged,
            field_structure=field_structure,
            star_inventory=star_inventory,
            analytical_needs=analytical_needs,
        )


def test_stale_star_or_route_authority_fails_closed(
    field_structure,
    star_inventory,
    analytical_needs,
) -> None:
    stale_star = replace(star_inventory, contract_sha256="0" * 64)
    stale_routes = replace(staging_route_contract_bundle(), digest="0" * 64)

    with pytest.raises(ModelCandidateCensusError, match="star inventory contract digest drifted"):
        compile_model_candidate_census(
            field_structure=field_structure,
            star_inventory=stale_star,
            analytical_needs=analytical_needs,
        )
    with pytest.raises(ModelCandidateCensusError, match="current authority"):
        compile_model_candidate_census(
            field_structure=field_structure,
            star_inventory=star_inventory,
            analytical_needs=analytical_needs,
            route_bundle=stale_routes,
        )


def test_foreign_field_structure_fails_closed(star_inventory, analytical_needs) -> None:
    with pytest.raises(ModelCandidateCensusError, match="foreign concrete type"):
        compile_model_candidate_census(
            field_structure=object(),
            star_inventory=star_inventory,
            analytical_needs=analytical_needs,
        )


def test_duplicate_candidate_identity_is_rejected(census) -> None:
    duplicate = tuple(
        sorted((*census.candidates, census.candidates[0]), key=lambda item: item.candidate_id)
    )

    with pytest.raises(ModelCandidateCensusError, match="candidate identities overlap"):
        replace(census, candidates=duplicate)


def test_dependency_cycle_is_rejected_before_receipt_use(census) -> None:
    facts = [item for item in census.candidates if item.candidate_kind == "fact"][:2]
    first = replace(
        facts[0],
        dependency_ids=tuple(sorted((*facts[0].dependency_ids, facts[1].candidate_id))),
    )
    second = replace(
        facts[1],
        dependency_ids=tuple(sorted((*facts[1].dependency_ids, facts[0].candidate_id))),
    )
    replacements = {first.candidate_id: first, second.candidate_id: second}
    cyclic = tuple(replacements.get(item.candidate_id, item) for item in census.candidates)

    with pytest.raises(ModelCandidateCensusError, match="cycle"):
        replace(census, candidates=cyclic)


def test_canonical_parser_rejects_noncanonical_and_duplicate_json(census) -> None:
    with pytest.raises(ModelCandidateCensusError, match="not canonical"):
        parse_model_candidate_census(b" " + census.canonical_bytes)

    duplicate = b'{"census_sha256":"' + (b"0" * 64) + b'",' + census.canonical_bytes[1:]
    with pytest.raises(ModelCandidateCensusError, match="repeats JSON key"):
        parse_model_candidate_census(duplicate)


def test_canonical_parser_requires_type_exact_schema_values(census) -> None:
    payload = json.loads(census.canonical_bytes)
    payload["schema_version"] = True
    forged = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()

    with pytest.raises(ModelCandidateCensusError, match="identity is invalid"):
        ModelCandidateCensusV1.from_canonical_bytes(forged)
