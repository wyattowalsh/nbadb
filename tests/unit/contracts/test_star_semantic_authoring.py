from __future__ import annotations

import hashlib
import json
from dataclasses import replace

import pytest

import nbadb.contracts.star_semantic_authoring as semantic_authoring
from nbadb.contracts.review_evidence import (
    ReviewFindingV1,
    ReviewReceiptV1,
    ReviewValidationReceiptV1,
)
from nbadb.contracts.star_semantic_authoring import (
    StarSemanticAuthoringContractError,
    StarSemanticAuthoringGenerationV1,
    StarTableSemanticCandidateV1,
    StarTableSemanticDecisionV1,
    canonical_star_semantic_authoring_json_bytes,
    canonical_star_semantic_authoring_sha256,
    compile_star_semantic_authoring_generation_v1,
    materialize_reviewed_star_semantic_candidate_v1,
)
from nbadb.contracts.star_semantic_contract import (
    ColumnLineageEdgeV1,
    DependencyCardinalityV1,
    KeyGroupV1,
    RelationshipV1,
    RowPolicyV1,
    TemporalPolicyV1,
)
from nbadb.contracts.star_semantic_inventory import StarTableSemanticAuthorityV1
from nbadb.contracts.star_table_contract import compile_star_table_contracts


def _digest(label: str) -> str:
    return hashlib.sha256(label.encode()).hexdigest()


def _candidate_review(
    candidate: StarTableSemanticCandidateV1,
    *,
    include_candidate_closure: bool = True,
    accepted: bool = True,
) -> ReviewReceiptV1:
    validations = tuple(
        sorted(
            ReviewValidationReceiptV1(
                receipt_id=f"semantic:{validation_class}",
                validation_class=validation_class,  # type: ignore[arg-type]
                command_sha256=_digest(f"command:{validation_class}"),
                evidence_sha256=_digest(f"evidence:{validation_class}"),
                passed=accepted or validation_class != "mutation",
            )
            for validation_class in ("positive", "negative", "mutation")
        )
    )
    accepted_inputs = {
        *candidate.required_review_input_sha256s,
        candidate.semantic_sha256,
    }
    if include_candidate_closure:
        accepted_inputs.update({candidate.candidate_sha256, candidate.evidence_closure_sha256})
    return ReviewReceiptV1(
        subject_kind="star_table_semantic_contract",
        subject_semantic_sha256=candidate.semantic_sha256,
        author_task_id="author:star-semantic",
        author_role="semantic-author",
        reviewer_task_id="reviewer:star-semantic",
        reviewer_role="independent-reviewer",
        independence_evidence_kind="independent_agent_review",
        independence_evidence_sha256=_digest("reviewer-independence"),
        accepted_input_sha256s=tuple(sorted(accepted_inputs)),
        disposition="accepted" if accepted else "changes_required",
        findings=(),
        validation_receipts=validations,
    )


def _authority(
    *,
    output_name: str,
    table_family: str,
    columns: tuple[str, ...],
    dependencies: tuple[str, ...],
) -> StarTableSemanticAuthorityV1:
    return StarTableSemanticAuthorityV1(
        output_name=output_name,
        table_family=table_family,  # type: ignore[arg-type]
        structural_inventory_sha256=_digest("structural-inventory"),
        stable_inventory_sha256=_digest("stable-inventory"),
        structural_table_sha256=_digest(f"structural-table:{output_name}"),
        schema_sha256=_digest(f"schema:{output_name}"),
        transform_sha256=_digest(f"transform:{output_name}"),
        ordered_columns=columns,
        transformer_dependencies=dependencies,
        expected_candidate_id=f"star:{output_name}",
        candidate_sha256=_digest(f"candidate:{output_name}"),
        candidate_kind=table_family,
        candidate_gate_requirement="stable_required",
        candidate_structural_sha256=_digest(f"candidate-structure:{output_name}"),
        candidate_implementation_status="implemented",
        candidate_implementation_sha256=_digest(f"candidate-implementation:{output_name}"),
        disposition_semantic_sha256=_digest(f"disposition:{output_name}"),
        disposition_status="stable",
    )


def _lineage(
    *,
    table_name: str,
    target_column: str,
    dependency: str,
    source_kind: str = "storage_occurrence",
) -> ColumnLineageEdgeV1:
    return ColumnLineageEdgeV1(
        edge_id=f"lineage:{target_column}",
        target_column=target_column,
        source_kind=source_kind,  # type: ignore[arg-type]
        source_ids=(f"{dependency}.{target_column}",),
        source_dependency_ids=(dependency,),
        transform_kind="copy",
        expression_sha256=None,
        evidence_sha256=_digest(f"lineage:{table_name}:{target_column}"),
    )


def _decision(
    authority: StarTableSemanticAuthorityV1,
    *,
    grain: tuple[str, ...],
    lineage: tuple[ColumnLineageEdgeV1, ...],
    dependency_cardinalities: tuple[DependencyCardinalityV1, ...],
    relationships: tuple[RelationshipV1, ...] = (),
    row_mode: str = "entity",
    event_columns: tuple[str, ...] = (),
) -> StarTableSemanticDecisionV1:
    correction_policy = "append_only" if event_columns else "latest_truth"
    truth_mode = "event_truth" if event_columns else "current_truth"
    scd_policy = "not_applicable" if event_columns else "type1"
    return StarTableSemanticDecisionV1(
        table_name=authority.output_name,
        authority_sha256=authority.authority_sha256,
        purpose_code=f"purpose:{authority.output_name}",
        purpose_evidence_sha256=_digest(f"purpose:{authority.output_name}"),
        grain_dimensions=grain,
        observation_identity=grain,
        key_mode="keyed",
        key_groups=(
            KeyGroupV1(
                key_id="natural",
                key_kind="natural",
                columns=grain,
                null_policy="forbidden",
                evidence_sha256=_digest(f"key:{authority.output_name}"),
            ),
        ),
        functional_dependencies=(),
        relationships=relationships,
        lineage_edges=lineage,
        competition_discriminators=(),
        request_discriminators=(),
        source_mode="dependency_backed",
        row_policy=RowPolicyV1(
            row_mode=row_mode,  # type: ignore[arg-type]
            filter_policy="preserve",
            dedup_policy="none",
            union_policy="none",
            aggregation_policy="none",
            additivity="additive" if event_columns else "not_applicable",
            evidence_sha256=_digest(f"row:{authority.output_name}"),
        ),
        temporal_policy=TemporalPolicyV1(
            event_columns=event_columns,
            observation_columns=(),
            load_columns=(),
            version_columns=(),
            feature_cutoff_columns=(),
            correction_policy=correction_policy,  # type: ignore[arg-type]
            truth_mode=truth_mode,  # type: ignore[arg-type]
            evidence_sha256=_digest(f"temporal:{authority.output_name}"),
        ),
        scd_policy=scd_policy,  # type: ignore[arg-type]
        algorithm_id=None,
        algorithm_version=None,
        coverage_policy="complete_scope",
        incomplete_policy="reject",
        empty_policy="materialize_typed_empty",
        unavailable_policy="typed_unavailable",
        dependency_cardinalities=dependency_cardinalities,
        positive_witness_sha256s=(_digest(f"positive:{authority.output_name}"),),
        negative_witness_sha256s=(_digest(f"negative:{authority.output_name}"),),
        mutation_witness_sha256s=(_digest(f"mutation:{authority.output_name}"),),
    )


def _source_free_decision(
    authority: StarTableSemanticAuthorityV1,
) -> StarTableSemanticDecisionV1:
    grain = (authority.ordered_columns[0],)
    decision = _decision(
        authority,
        grain=grain,
        lineage=tuple(
            sorted(
                ColumnLineageEdgeV1(
                    edge_id=f"lineage:{column}",
                    target_column=column,
                    source_kind="literal",
                    source_ids=(f"transform:{authority.output_name}:{column}",),
                    source_dependency_ids=(),
                    transform_kind="expression",
                    expression_sha256=_digest(f"expression:{authority.output_name}:{column}"),
                    evidence_sha256=_digest(f"lineage:{authority.output_name}:{column}"),
                )
                for column in authority.ordered_columns
            )
        ),
        dependency_cardinalities=(),
    )
    return replace(
        decision,
        source_mode="reviewed_source_free",
        algorithm_id=f"algorithm:{authority.output_name}",
        algorithm_version="v1",
    )


def _micro_universe() -> tuple[
    tuple[StarTableSemanticAuthorityV1, ...],
    tuple[StarTableSemanticDecisionV1, ...],
]:
    dim_team = _authority(
        output_name="dim_team",
        table_family="dimension",
        columns=("team_id", "team_name"),
        dependencies=("stg_team",),
    )
    fact_game = _authority(
        output_name="fact_game",
        table_family="fact",
        columns=("game_id", "team_id", "points", "game_date"),
        dependencies=("stg_game", "star:dim_team"),
    )
    dim_decision = _decision(
        dim_team,
        grain=("team_id",),
        lineage=tuple(
            sorted(
                (
                    _lineage(
                        table_name="dim_team",
                        target_column="team_id",
                        dependency="stg_team",
                    ),
                    _lineage(
                        table_name="dim_team",
                        target_column="team_name",
                        dependency="stg_team",
                    ),
                )
            )
        ),
        dependency_cardinalities=(
            DependencyCardinalityV1(
                dependency_id="stg_team",
                effect="row_preserving",
                equation_code="one_output_per_team",
                evidence_sha256=_digest("cardinality:dim_team:stg_team"),
            ),
        ),
    )
    fact_decision = _decision(
        fact_game,
        grain=("game_id", "team_id"),
        lineage=tuple(
            sorted(
                (
                    _lineage(
                        table_name="fact_game",
                        target_column="game_id",
                        dependency="stg_game",
                    ),
                    _lineage(
                        table_name="fact_game",
                        target_column="team_id",
                        dependency="star:dim_team",
                        source_kind="star_column",
                    ),
                    _lineage(
                        table_name="fact_game",
                        target_column="points",
                        dependency="stg_game",
                    ),
                    _lineage(
                        table_name="fact_game",
                        target_column="game_date",
                        dependency="stg_game",
                    ),
                )
            )
        ),
        relationships=(
            RelationshipV1(
                relationship_id="team",
                local_columns=("team_id",),
                target_table="dim_team",
                target_columns=("team_id",),
                cardinality="many_to_one",
                orphan_policy="reject",
                timing="event_time",
                evidence_sha256=_digest("relationship:fact_game:dim_team"),
            ),
        ),
        dependency_cardinalities=tuple(
            sorted(
                (
                    DependencyCardinalityV1(
                        dependency_id="star:dim_team",
                        effect="row_preserving",
                        equation_code="many_games_to_one_team",
                        evidence_sha256=_digest("cardinality:fact_game:dim_team"),
                    ),
                    DependencyCardinalityV1(
                        dependency_id="stg_game",
                        effect="row_preserving",
                        equation_code="one_output_per_game_team",
                        evidence_sha256=_digest("cardinality:fact_game:stg_game"),
                    ),
                )
            )
        ),
        row_mode="event",
        event_columns=("game_date",),
    )
    return (dim_team, fact_game), (dim_decision, fact_decision)


def _compile() -> StarSemanticAuthoringGenerationV1:
    authorities, decisions = _micro_universe()
    return compile_star_semantic_authoring_generation_v1(
        authorities=authorities,
        decisions=decisions,
    )


def _blocker_codes(generation: StarSemanticAuthoringGenerationV1) -> set[str]:
    return {blocker.code for blocker in generation.blockers}


def test_literal_known_answer_is_exact_nonadmitted_candidate_generation() -> None:
    generation = _compile()

    assert (
        generation.generation_sha256
        == "fee3959605c43603e91b34090bf501663cd7965707d00edcf70b094dfa214887"
    )
    assert tuple(item.authority.output_name for item in generation.candidates) == (
        "dim_team",
        "fact_game",
    )
    assert _blocker_codes(generation) == {"frozen_authority_completeness_unproven"}
    assert generation.complete is False
    assert generation.admitted is False
    assert generation.model_green is False
    assert (
        StarSemanticAuthoringGenerationV1.from_canonical_bytes(generation.canonical_bytes)
        == generation
    )


def test_compiler_mechanically_binds_authority_and_full_evidence_closure() -> None:
    authorities, _decisions = _micro_universe()
    generation = _compile()
    fact = generation.candidates[1]

    assert fact.authority == authorities[1]
    assert fact.decision.table_name == fact.authority.output_name
    assert fact.relationship_target_authority_sha256s == (authorities[0].authority_sha256,)
    required = set(fact.required_review_input_sha256s)
    assert {
        fact.semantic_sha256,
        fact.authority_inventory_sha256,
        fact.authority.authority_sha256,
        fact.authority.structural_inventory_sha256,
        fact.authority.stable_inventory_sha256,
        fact.authority.structural_table_sha256,
        fact.authority.schema_sha256,
        fact.authority.transform_sha256,
        fact.authority.candidate_sha256,
        fact.authority.candidate_structural_sha256,
        fact.authority.candidate_implementation_sha256,
        fact.authority.disposition_semantic_sha256,
        fact.decision.decision_sha256,
        fact.decision.purpose_evidence_sha256,
        authorities[0].authority_sha256,
        fact.decision.row_policy.evidence_sha256,
        fact.decision.temporal_policy.evidence_sha256,
        *fact.decision.positive_witness_sha256s,
        *fact.decision.negative_witness_sha256s,
        *fact.decision.mutation_witness_sha256s,
    }.issubset(required)
    assert all(item.evidence_sha256 in required for item in fact.decision.key_groups)
    assert all(item.evidence_sha256 in required for item in fact.decision.relationships)
    assert all(item.evidence_sha256 in required for item in fact.decision.lineage_edges)
    assert all(item.evidence_sha256 in required for item in fact.decision.dependency_cardinalities)


def test_empty_missing_extra_and_partial_inputs_remain_blocked() -> None:
    empty = compile_star_semantic_authoring_generation_v1(authorities=(), decisions=())
    assert _blocker_codes(empty) == {
        "authority_inventory_empty",
        "frozen_authority_completeness_unproven",
    }
    assert empty.candidates == ()

    authorities, decisions = _micro_universe()
    partial = compile_star_semantic_authoring_generation_v1(
        authorities=authorities,
        decisions=(decisions[0],),
    )
    assert "semantic_decision_missing" in _blocker_codes(partial)
    assert tuple(item.authority.output_name for item in partial.candidates) == ("dim_team",)
    assert partial.model_green is False

    extra = replace(
        decisions[1],
        table_name="fact_unknown",
        authority_sha256=_digest("unknown-authority"),
    )
    with_extra = compile_star_semantic_authoring_generation_v1(
        authorities=authorities,
        decisions=tuple(sorted((decisions[0], extra), key=lambda item: item.table_name)),
    )
    assert "semantic_decision_without_authority" in _blocker_codes(with_extra)
    assert "semantic_decision_missing" in _blocker_codes(with_extra)


def test_structural_gaps_are_blockers_never_inferred_semantics() -> None:
    authorities, decisions = _micro_universe()
    empty_columns = replace(
        authorities[0],
        ordered_columns=(),
        candidate_implementation_status="missing",
        candidate_implementation_sha256=None,
    )
    empty_decision = replace(decisions[0], authority_sha256=empty_columns.authority_sha256)
    generation = compile_star_semantic_authoring_generation_v1(
        authorities=(empty_columns,),
        decisions=(empty_decision,),
    )
    assert generation.candidates == ()
    assert {
        "authority_ordered_columns_empty",
        "authority_candidate_implementation_missing",
    }.issubset(_blocker_codes(generation))

    zero_dependencies = replace(authorities[0], transformer_dependencies=())
    zero_decision = replace(decisions[0], authority_sha256=zero_dependencies.authority_sha256)
    generation = compile_star_semantic_authoring_generation_v1(
        authorities=(zero_dependencies,),
        decisions=(zero_decision,),
    )
    assert generation.candidates == ()
    assert "semantic_decision_invalid" in _blocker_codes(generation)

    # A semantically suggestive name never substitutes for an authored decision.
    no_decision = compile_star_semantic_authoring_generation_v1(
        authorities=(authorities[0],),
        decisions=(),
    )
    assert no_decision.candidates == ()
    assert "semantic_decision_missing" in _blocker_codes(no_decision)


def test_mixed_reordered_and_duplicate_source_inputs_fail() -> None:
    authorities, decisions = _micro_universe()
    mixed = replace(
        authorities[1],
        structural_inventory_sha256=_digest("other-structural-generation"),
    )
    mixed_decision = replace(decisions[1], authority_sha256=mixed.authority_sha256)
    with pytest.raises(StarSemanticAuthoringContractError, match="mixed"):
        compile_star_semantic_authoring_generation_v1(
            authorities=(authorities[0], mixed),
            decisions=(decisions[0], mixed_decision),
        )
    with pytest.raises(StarSemanticAuthoringContractError, match="sorted"):
        compile_star_semantic_authoring_generation_v1(
            authorities=tuple(reversed(authorities)),
            decisions=decisions,
        )
    with pytest.raises(StarSemanticAuthoringContractError, match="unique"):
        compile_star_semantic_authoring_generation_v1(
            authorities=(authorities[0], authorities[0]),
            decisions=(decisions[0],),
        )


def test_relationship_rebinding_and_invalid_authored_semantics_block_candidate() -> None:
    authorities, decisions = _micro_universe()
    foreign_relationship = replace(
        decisions[1].relationships[0],
        target_table="dim_missing",
    )
    rebound = replace(decisions[1], relationships=(foreign_relationship,))
    generation = compile_star_semantic_authoring_generation_v1(
        authorities=authorities,
        decisions=(decisions[0], rebound),
    )
    assert tuple(item.authority.output_name for item in generation.candidates) == ("dim_team",)
    assert "semantic_relationship_target_invalid" in _blocker_codes(generation)

    invalid_identity = replace(
        decisions[1],
        observation_identity=("game_id",),
    )
    generation = compile_star_semantic_authoring_generation_v1(
        authorities=authorities,
        decisions=(decisions[0], invalid_identity),
    )
    assert "semantic_decision_invalid" in _blocker_codes(generation)


def test_direct_candidate_fabrication_cannot_remove_or_replace_evidence() -> None:
    candidate = _compile().candidates[1]
    with pytest.raises(StarSemanticAuthoringContractError, match="closure"):
        replace(
            candidate,
            required_review_input_sha256s=candidate.required_review_input_sha256s[1:],
        )
    replacement = tuple(
        sorted(
            {
                *candidate.required_review_input_sha256s[1:],
                _digest("forged-evidence"),
            }
        )
    )
    with pytest.raises(StarSemanticAuthoringContractError, match="closure"):
        replace(candidate, required_review_input_sha256s=replacement)
    with pytest.raises(StarSemanticAuthoringContractError, match="foreign authority"):
        replace(candidate, decision=replace(candidate.decision, table_name="fact_other"))
    with pytest.raises(StarSemanticAuthoringContractError, match="invalid cardinality"):
        replace(candidate, relationship_target_authority_sha256s=())
    missing_implementation = replace(
        candidate.authority,
        candidate_implementation_status="missing",
        candidate_implementation_sha256=None,
    )
    with pytest.raises(StarSemanticAuthoringContractError, match="unresolved"):
        replace(
            candidate,
            authority=missing_implementation,
            decision=replace(
                candidate.decision,
                authority_sha256=missing_implementation.authority_sha256,
            ),
        )
    with pytest.raises(StarSemanticAuthoringContractError, match="exact false"):
        replace(candidate, admitted=True)  # type: ignore[arg-type]


def test_current_source_free_dimension_authorities_form_reviewable_candidates() -> None:
    current_tables = {
        table.output_name: table
        for table in compile_star_table_contracts().tables
        if table.output_name in {"dim_date", "dim_play_event_type", "dim_season_phase"}
    }
    assert set(current_tables) == {"dim_date", "dim_play_event_type", "dim_season_phase"}
    authorities = tuple(
        _authority(
            output_name=name,
            table_family="dimension",
            columns=tuple(column.name for column in current_tables[name].columns),
            dependencies=current_tables[name].transform.dependencies,
        )
        for name in sorted(current_tables)
    )
    assert all(authority.transformer_dependencies == () for authority in authorities)
    decisions = tuple(_source_free_decision(authority) for authority in authorities)

    generation = compile_star_semantic_authoring_generation_v1(
        authorities=authorities,
        decisions=decisions,
    )

    assert tuple(item.authority.output_name for item in generation.candidates) == tuple(
        sorted(current_tables)
    )
    assert _blocker_codes(generation) == {"frozen_authority_completeness_unproven"}
    assert all(
        item.decision.source_mode == "reviewed_source_free" for item in generation.candidates
    )
    assert all(
        item.admitted is False and item.model_green is False for item in generation.candidates
    )


def test_source_modes_cannot_rebind_empty_or_dependency_backed_authorities() -> None:
    authorities, decisions = _micro_universe()
    empty_authority = replace(authorities[0], transformer_dependencies=())
    dependency_mode = replace(
        decisions[0],
        authority_sha256=empty_authority.authority_sha256,
    )
    empty_generation = compile_star_semantic_authoring_generation_v1(
        authorities=(empty_authority,),
        decisions=(dependency_mode,),
    )
    assert "semantic_decision_invalid" in _blocker_codes(empty_generation)

    source_free_decision = replace(
        _source_free_decision(authorities[0]),
        authority_sha256=authorities[0].authority_sha256,
    )
    backed_generation = compile_star_semantic_authoring_generation_v1(
        authorities=(authorities[0],),
        decisions=(source_free_decision,),
    )
    assert "semantic_decision_invalid" in _blocker_codes(backed_generation)
    assert backed_generation.candidates == ()


def test_aggregate_relationship_budget_has_an_exact_boundary(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    authorities, decisions = _micro_universe()
    second_relationship = replace(
        decisions[1].relationships[0],
        relationship_id="team_by_game",
        local_columns=("game_id",),
    )
    over_budget = replace(
        decisions[1],
        relationships=tuple(sorted((*decisions[1].relationships, second_relationship))),
    )
    monkeypatch.setattr(semantic_authoring, "_MAX_TOTAL_RELATIONSHIPS", 1)
    at_boundary = compile_star_semantic_authoring_generation_v1(
        authorities=authorities,
        decisions=decisions,
    )
    assert (
        StarSemanticAuthoringGenerationV1.from_canonical_bytes(at_boundary.canonical_bytes)
        == at_boundary
    )

    with pytest.raises(StarSemanticAuthoringContractError, match="aggregate relationship budget"):
        compile_star_semantic_authoring_generation_v1(
            authorities=authorities,
            decisions=(decisions[0], over_budget),
        )


def test_primary_candidate_stays_nonadmitted_when_target_hash_is_self_consistently_resealed() -> (
    None
):
    candidate = _compile().candidates[1]
    original = candidate.relationship_target_authority_sha256s[0]
    forged = _digest("forged-relationship-target-authority")
    forged_inputs = tuple(
        sorted(
            forged if item == original else item for item in candidate.required_review_input_sha256s
        )
    )
    forged_closure = canonical_star_semantic_authoring_sha256(
        {
            "schema_version": 1,
            "kind": "nbadb_star_semantic_review_input_closure",
            "required_review_input_sha256s": list(forged_inputs),
        }
    )

    self_consistent_but_unbound = replace(
        candidate,
        relationship_target_authority_sha256s=(forged,),
        required_review_input_sha256s=forged_inputs,
        evidence_closure_sha256=forged_closure,
    )

    assert self_consistent_but_unbound.admitted is False
    assert self_consistent_but_unbound.model_green is False
    assert not hasattr(self_consistent_but_unbound, "review_receipt_sha256")


def test_canonical_parsers_reject_type_confusion_duplicate_keys_and_resealing() -> None:
    generation = _compile()
    decision_payload = generation.candidates[0].decision.to_dict()
    decision_payload["schema_version"] = True
    decision_payload["decision_sha256"] = hashlib.sha256(
        canonical_star_semantic_authoring_json_bytes(
            {key: value for key, value in decision_payload.items() if key != "decision_sha256"}
        )
    ).hexdigest()
    with pytest.raises(StarSemanticAuthoringContractError, match="schema"):
        StarTableSemanticDecisionV1.from_dict(decision_payload)

    generation_payload = generation.to_dict()
    generation_payload["admitted"] = 0
    generation_payload["generation_sha256"] = hashlib.sha256(
        canonical_star_semantic_authoring_json_bytes(
            {key: value for key, value in generation_payload.items() if key != "generation_sha256"}
        )
    ).hexdigest()
    with pytest.raises(StarSemanticAuthoringContractError, match="invalid type"):
        StarSemanticAuthoringGenerationV1.from_dict(generation_payload)

    duplicate = b'{"schema_version":1,"schema_version":1}'
    with pytest.raises(StarSemanticAuthoringContractError, match="duplicate"):
        StarTableSemanticDecisionV1.from_canonical_bytes(duplicate)
    noncanonical = json.dumps(generation.to_dict(), indent=2).encode()
    with pytest.raises(StarSemanticAuthoringContractError, match="canonical"):
        StarSemanticAuthoringGenerationV1.from_canonical_bytes(noncanonical)


def test_candidate_type_is_not_a_final_semantic_contract_or_review_receipt() -> None:
    candidate = _compile().candidates[0]

    assert type(candidate) is StarTableSemanticCandidateV1
    assert not hasattr(candidate, "review_receipt_sha256")
    assert candidate.admitted is False
    assert candidate.model_green is False


def test_exact_review_closure_materializes_one_table_local_semantic_contract() -> None:
    generation = _compile()
    candidate = generation.candidates[1]
    review = _candidate_review(candidate)

    contract = materialize_reviewed_star_semantic_candidate_v1(
        candidate=candidate,
        review_receipt=review,
    )

    assert contract.table_name == candidate.authority.output_name
    assert contract.semantic_sha256 == candidate.semantic_sha256
    assert contract.review_receipt_sha256 == review.receipt_sha256
    contract.validate_review_receipt(review)
    assert generation.admitted is False
    assert generation.model_green is False


def test_reviewed_materialization_rejects_partial_rebound_or_unaccepted_review() -> None:
    candidate = _compile().candidates[0]

    with pytest.raises(
        StarSemanticAuthoringContractError,
        match="omits the exact candidate evidence closure",
    ):
        materialize_reviewed_star_semantic_candidate_v1(
            candidate=candidate,
            review_receipt=_candidate_review(
                candidate,
                include_candidate_closure=False,
            ),
        )

    rebound = replace(
        _candidate_review(candidate),
        subject_semantic_sha256=_digest("foreign-semantics"),
        accepted_input_sha256s=tuple(
            sorted(
                {
                    *_candidate_review(candidate).accepted_input_sha256s,
                    _digest("foreign-semantics"),
                }
            )
        ),
    )
    with pytest.raises(
        StarSemanticAuthoringContractError,
        match="does not accept the exact candidate semantics",
    ):
        materialize_reviewed_star_semantic_candidate_v1(
            candidate=candidate,
            review_receipt=rebound,
        )

    with pytest.raises(
        StarSemanticAuthoringContractError,
        match="does not accept the exact candidate semantics",
    ):
        materialize_reviewed_star_semantic_candidate_v1(
            candidate=candidate,
            review_receipt=_candidate_review(candidate, accepted=False),
        )


@pytest.mark.parametrize(
    ("field_name", "mutated_value"),
    [
        ("validation_receipts", ()),
        ("independence_evidence_sha256", "not-a-sha256"),
        (
            "findings",
            (
                ReviewFindingV1(
                    finding_id="mutated:open",
                    severity="major",
                    status="open",
                    evidence_sha256=_digest("mutated-open-finding"),
                ),
            ),
        ),
    ],
)
def test_reviewed_materialization_reseals_post_construction_review_mutation(
    field_name: str,
    mutated_value: object,
) -> None:
    candidate = _compile().candidates[0]
    review = _candidate_review(candidate)
    object.__setattr__(review, field_name, mutated_value)

    with pytest.raises(
        StarSemanticAuthoringContractError,
        match="failed exact typed reconstruction",
    ):
        materialize_reviewed_star_semantic_candidate_v1(
            candidate=candidate,
            review_receipt=review,
        )


def test_reviewed_materialization_reseals_post_construction_candidate_mutation() -> None:
    candidate = _compile().candidates[0]
    object.__setattr__(
        candidate,
        "required_review_input_sha256s",
        tuple(sorted(candidate.required_review_input_sha256s[:5])),
    )
    object.__setattr__(candidate, "evidence_closure_sha256", _digest("forged-closure"))
    review = _candidate_review(candidate)

    with pytest.raises(
        StarSemanticAuthoringContractError,
        match="failed exact typed reconstruction",
    ):
        materialize_reviewed_star_semantic_candidate_v1(
            candidate=candidate,
            review_receipt=review,
        )
