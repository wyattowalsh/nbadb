from __future__ import annotations

import ast
import hashlib
from copy import deepcopy
from dataclasses import replace
from pathlib import Path

import pytest

import nbadb.contracts.star_semantic_authoring_verifier as semantic_authoring_verifier
from nbadb.contracts.star_semantic_authoring import (
    StarTableSemanticDecisionV1,
    canonical_star_semantic_authoring_json_bytes,
    canonical_star_semantic_authoring_sha256,
    compile_star_semantic_authoring_generation_v1,
)
from nbadb.contracts.star_semantic_authoring_verifier import (
    IndependentStarSemanticAuthoringError,
    StarSemanticAuthoringIndependentProofV1,
    verify_star_semantic_authoring_generation_independently,
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


def _digest(label: str) -> str:
    return hashlib.sha256(label.encode()).hexdigest()


def _authority() -> StarTableSemanticAuthorityV1:
    return StarTableSemanticAuthorityV1(
        output_name="dim_team",
        table_family="dimension",
        structural_inventory_sha256=_digest("verifier:structural-inventory"),
        stable_inventory_sha256=_digest("verifier:stable-inventory"),
        structural_table_sha256=_digest("verifier:structural-table"),
        schema_sha256=_digest("verifier:schema"),
        transform_sha256=_digest("verifier:transform"),
        ordered_columns=("team_id", "team_name"),
        transformer_dependencies=("stg_team",),
        expected_candidate_id="star:dim_team",
        candidate_sha256=_digest("verifier:candidate"),
        candidate_kind="dimension",
        candidate_gate_requirement="stable_required",
        candidate_structural_sha256=_digest("verifier:candidate-structure"),
        candidate_implementation_status="implemented",
        candidate_implementation_sha256=_digest("verifier:candidate-implementation"),
        disposition_semantic_sha256=_digest("verifier:disposition"),
        disposition_status="stable",
    )


def _decision(authority: StarTableSemanticAuthorityV1) -> StarTableSemanticDecisionV1:
    return StarTableSemanticDecisionV1(
        table_name="dim_team",
        authority_sha256=authority.authority_sha256,
        purpose_code="team_identity",
        purpose_evidence_sha256=_digest("verifier:purpose"),
        grain_dimensions=("team_id",),
        observation_identity=("team_id",),
        key_mode="keyed",
        key_groups=(
            KeyGroupV1(
                key_id="natural",
                key_kind="natural",
                columns=("team_id",),
                null_policy="forbidden",
                evidence_sha256=_digest("verifier:key"),
            ),
        ),
        functional_dependencies=(),
        relationships=(),
        lineage_edges=tuple(
            sorted(
                (
                    ColumnLineageEdgeV1(
                        edge_id="lineage:team_id",
                        target_column="team_id",
                        source_kind="storage_occurrence",
                        source_ids=("stg_team.team_id",),
                        source_dependency_ids=("stg_team",),
                        transform_kind="copy",
                        expression_sha256=None,
                        evidence_sha256=_digest("verifier:lineage:team_id"),
                    ),
                    ColumnLineageEdgeV1(
                        edge_id="lineage:team_name",
                        target_column="team_name",
                        source_kind="storage_occurrence",
                        source_ids=("stg_team.team_name",),
                        source_dependency_ids=("stg_team",),
                        transform_kind="copy",
                        expression_sha256=None,
                        evidence_sha256=_digest("verifier:lineage:team_name"),
                    ),
                )
            )
        ),
        competition_discriminators=(),
        request_discriminators=(),
        source_mode="dependency_backed",
        row_policy=RowPolicyV1(
            row_mode="entity",
            filter_policy="preserve",
            dedup_policy="none",
            union_policy="none",
            aggregation_policy="none",
            additivity="not_applicable",
            evidence_sha256=_digest("verifier:row"),
        ),
        temporal_policy=TemporalPolicyV1(
            event_columns=(),
            observation_columns=(),
            load_columns=(),
            version_columns=(),
            feature_cutoff_columns=(),
            correction_policy="latest_truth",
            truth_mode="current_truth",
            evidence_sha256=_digest("verifier:temporal"),
        ),
        scd_policy="type1",
        algorithm_id=None,
        algorithm_version=None,
        coverage_policy="complete_scope",
        incomplete_policy="reject",
        empty_policy="materialize_typed_empty",
        unavailable_policy="typed_unavailable",
        dependency_cardinalities=(
            DependencyCardinalityV1(
                dependency_id="stg_team",
                effect="row_preserving",
                equation_code="one_output_per_team",
                evidence_sha256=_digest("verifier:cardinality"),
            ),
        ),
        positive_witness_sha256s=(_digest("verifier:positive"),),
        negative_witness_sha256s=(_digest("verifier:negative"),),
        mutation_witness_sha256s=(_digest("verifier:mutation"),),
    )


def _source() -> tuple[
    StarTableSemanticAuthorityV1,
    StarTableSemanticDecisionV1,
    bytes,
]:
    authority = _authority()
    decision = _decision(authority)
    generation = compile_star_semantic_authoring_generation_v1(
        authorities=(authority,),
        decisions=(decision,),
    )
    return authority, decision, generation.canonical_bytes


def _source_with_relationship() -> tuple[
    StarTableSemanticAuthorityV1,
    StarTableSemanticDecisionV1,
    bytes,
]:
    authority = _authority()
    decision = replace(
        _decision(authority),
        relationships=(
            RelationshipV1(
                relationship_id="self_team",
                local_columns=("team_id",),
                target_table="dim_team",
                target_columns=("team_id",),
                cardinality="many_to_one",
                orphan_policy="reject",
                timing="current",
                evidence_sha256=_digest("verifier:relationship:self-team"),
            ),
        ),
    )
    generation = compile_star_semantic_authoring_generation_v1(
        authorities=(authority,),
        decisions=(decision,),
    )
    return authority, decision, generation.canonical_bytes


def _source_free_source() -> tuple[
    StarTableSemanticAuthorityV1,
    StarTableSemanticDecisionV1,
    bytes,
]:
    authority = replace(_authority(), transformer_dependencies=())
    decision = replace(
        _decision(authority),
        source_mode="reviewed_source_free",
        lineage_edges=tuple(
            replace(
                edge,
                source_kind="literal",
                source_ids=(f"transform:dim_team:{edge.target_column}",),
                source_dependency_ids=(),
                transform_kind="expression",
                expression_sha256=_digest(f"verifier:expression:{edge.target_column}"),
            )
            for edge in _decision(authority).lineage_edges
        ),
        dependency_cardinalities=(),
        algorithm_id="algorithm:dim-team-source-free",
        algorithm_version="v1",
    )
    generation = compile_star_semantic_authoring_generation_v1(
        authorities=(authority,),
        decisions=(decision,),
    )
    return authority, decision, generation.canonical_bytes


def _authority_bytes(authority: StarTableSemanticAuthorityV1) -> bytes:
    return canonical_star_semantic_authoring_json_bytes(authority.to_dict())


def _verify(
    authority: StarTableSemanticAuthorityV1,
    decision: StarTableSemanticDecisionV1,
    observed: bytes,
) -> StarSemanticAuthoringIndependentProofV1:
    return verify_star_semantic_authoring_generation_independently(
        authority_canonical_bytes=(_authority_bytes(authority),),
        decision_canonical_bytes=(decision.canonical_bytes,),
        observed_generation_canonical_bytes=observed,
    )


def _reseal_candidate(candidate: dict[str, object]) -> None:
    candidate["candidate_sha256"] = canonical_star_semantic_authoring_sha256(
        {key: value for key, value in candidate.items() if key != "candidate_sha256"}
    )


def _reseal_generation(payload: dict[str, object]) -> bytes:
    payload["generation_sha256"] = canonical_star_semantic_authoring_sha256(
        {key: value for key, value in payload.items() if key != "generation_sha256"}
    )
    return canonical_star_semantic_authoring_json_bytes(payload)


def test_independent_known_answer_proves_only_source_relative_nonadmitted_equality() -> None:
    authority, decision, observed = _source()
    proof = _verify(authority, decision, observed)

    assert proof.proof_sha256 == "78c891b249e9d8c154ab0d20181281a1e1bd659637e5baa093d042e871839063"
    assert proof.candidate_count == 1
    assert proof.blocker_count == 1
    assert proof.verified is True
    assert proof.admitted is False
    assert proof.model_green is False
    assert proof.observed_generation_bytes_sha256 == hashlib.sha256(observed).hexdigest()
    assert (
        StarSemanticAuthoringIndependentProofV1.from_canonical_bytes(proof.canonical_bytes) == proof
    )


@pytest.mark.parametrize(
    ("path", "replacement"),
    [
        (("schema_version",), True),
        (("admitted",), 0),
        (("candidates", 0, "schema_version"), True),
        (("candidates", 0, "admitted"), 0),
        (("candidates", 0, "decision", "schema_version"), True),
    ],
)
def test_observed_nested_type_confusions_fail_before_equality(
    path: tuple[object, ...], replacement: object
) -> None:
    authority, decision, observed = _source()
    payload = deepcopy(json_loads(observed))
    target: object = payload
    for segment in path[:-1]:
        target = target[segment]  # type: ignore[index]
    target[path[-1]] = replacement  # type: ignore[index]
    if path[0] == "candidates":
        _reseal_candidate(payload["candidates"][0])  # type: ignore[index]
    mutated = _reseal_generation(payload)

    with pytest.raises(IndependentStarSemanticAuthoringError):
        _verify(authority, decision, mutated)


def test_remove_replace_and_reseal_review_closure_still_fail() -> None:
    authority, decision, observed = _source()
    for mode in ("remove", "replace"):
        payload = deepcopy(json_loads(observed))
        candidate = payload["candidates"][0]
        inputs = candidate["required_review_input_sha256s"]
        if mode == "remove":
            del inputs[0]
        else:
            inputs[0] = _digest("forged-review-input")
            inputs.sort()
        candidate["evidence_closure_sha256"] = canonical_star_semantic_authoring_sha256(
            {
                "schema_version": 1,
                "kind": "nbadb_star_semantic_review_input_closure",
                "required_review_input_sha256s": inputs,
            }
        )
        _reseal_candidate(candidate)
        mutated = _reseal_generation(payload)
        with pytest.raises(IndependentStarSemanticAuthoringError):
            _verify(authority, decision, mutated)


def test_independent_verifier_binds_exact_relationship_target_authority() -> None:
    authority, decision, observed = _source_with_relationship()
    payload = deepcopy(json_loads(observed))
    candidate = payload["candidates"][0]
    original = candidate["relationship_target_authority_sha256s"][0]
    forged = _digest("verifier:forged-target-authority")
    candidate["relationship_target_authority_sha256s"] = [forged]
    candidate["required_review_input_sha256s"] = sorted(
        forged if item == original else item for item in candidate["required_review_input_sha256s"]
    )
    candidate["evidence_closure_sha256"] = canonical_star_semantic_authoring_sha256(
        {
            "schema_version": 1,
            "kind": "nbadb_star_semantic_review_input_closure",
            "required_review_input_sha256s": candidate["required_review_input_sha256s"],
        }
    )
    _reseal_candidate(candidate)

    with pytest.raises(
        IndependentStarSemanticAuthoringError,
        match="differs from independent reconstruction",
    ):
        _verify(authority, decision, _reseal_generation(payload))


def test_independent_verifier_accepts_exact_reviewed_source_free_branch() -> None:
    authority, decision, observed = _source_free_source()
    proof = _verify(authority, decision, observed)

    assert proof.verified is True
    assert proof.candidate_count == 1
    assert proof.blocker_count == 1
    assert proof.admitted is False
    assert proof.model_green is False


def test_independent_verifier_mirrors_both_source_mode_authority_failures() -> None:
    empty_authority = replace(_authority(), transformer_dependencies=())
    dependency_decision = _decision(empty_authority)
    empty_observed = compile_star_semantic_authoring_generation_v1(
        authorities=(empty_authority,),
        decisions=(dependency_decision,),
    ).canonical_bytes
    empty_proof = _verify(empty_authority, dependency_decision, empty_observed)
    assert empty_proof.candidate_count == 0
    assert empty_proof.blocker_count == 2

    backed_authority = _authority()
    _source_free_authority, source_free_decision, _source_free_observed = _source_free_source()
    rebound_source_free = replace(
        source_free_decision,
        authority_sha256=backed_authority.authority_sha256,
    )
    backed_observed = compile_star_semantic_authoring_generation_v1(
        authorities=(backed_authority,),
        decisions=(rebound_source_free,),
    ).canonical_bytes
    backed_proof = _verify(backed_authority, rebound_source_free, backed_observed)
    assert backed_proof.candidate_count == 0
    assert backed_proof.blocker_count == 2


def test_independent_aggregate_relationship_budget_is_fail_closed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    authority, decision, observed = _source_with_relationship()
    monkeypatch.setattr(semantic_authoring_verifier, "_MAX_TOTAL_RELATIONSHIPS", 1)
    assert _verify(authority, decision, observed).verified is True

    with pytest.raises(
        IndependentStarSemanticAuthoringError,
        match="aggregate relationship budget",
    ):
        verify_star_semantic_authoring_generation_independently(
            authority_canonical_bytes=(
                _authority_bytes(authority),
                _authority_bytes(authority),
            ),
            decision_canonical_bytes=(decision.canonical_bytes, decision.canonical_bytes),
            observed_generation_canonical_bytes=observed,
        )


def test_semantic_candidate_blocker_and_inventory_mutations_fail_when_resealed() -> None:
    authority, decision, observed = _source()
    mutations: list[dict[str, object]] = []

    semantic = deepcopy(json_loads(observed))
    semantic_candidate = semantic["candidates"][0]
    semantic_candidate["semantic_sha256"] = _digest("forged-semantic")
    _reseal_candidate(semantic_candidate)
    mutations.append(semantic)

    no_candidate = deepcopy(json_loads(observed))
    no_candidate["candidates"] = []
    mutations.append(no_candidate)

    no_blocker = deepcopy(json_loads(observed))
    no_blocker["blockers"] = []
    mutations.append(no_blocker)

    rebound_inventory = deepcopy(json_loads(observed))
    rebound_inventory["authority_inventory_sha256"] = _digest("foreign-authority-inventory")
    mutations.append(rebound_inventory)

    for payload in mutations:
        with pytest.raises(IndependentStarSemanticAuthoringError):
            _verify(authority, decision, _reseal_generation(payload))


def test_mutated_or_omitted_source_inputs_cannot_verify_observed_generation() -> None:
    authority, decision, observed = _source()
    decision_payload = decision.to_dict()
    decision_payload["purpose_code"] = "forged_purpose"
    decision_payload["decision_sha256"] = canonical_star_semantic_authoring_sha256(
        {key: value for key, value in decision_payload.items() if key != "decision_sha256"}
    )
    mutated_decision_bytes = canonical_star_semantic_authoring_json_bytes(decision_payload)
    with pytest.raises(IndependentStarSemanticAuthoringError):
        verify_star_semantic_authoring_generation_independently(
            authority_canonical_bytes=(_authority_bytes(authority),),
            decision_canonical_bytes=(mutated_decision_bytes,),
            observed_generation_canonical_bytes=observed,
        )
    with pytest.raises(IndependentStarSemanticAuthoringError):
        verify_star_semantic_authoring_generation_independently(
            authority_canonical_bytes=(),
            decision_canonical_bytes=(),
            observed_generation_canonical_bytes=observed,
        )


def test_self_consistent_partial_source_remains_explicitly_blocked_and_non_green() -> None:
    authority, decision, _observed = _source()
    partial = compile_star_semantic_authoring_generation_v1(
        authorities=(authority,),
        decisions=(),
    )
    proof = verify_star_semantic_authoring_generation_independently(
        authority_canonical_bytes=(_authority_bytes(authority),),
        decision_canonical_bytes=(),
        observed_generation_canonical_bytes=partial.canonical_bytes,
    )

    assert proof.candidate_count == 0
    assert proof.blocker_count == 2
    assert proof.admitted is False
    assert proof.model_green is False
    assert {item.code for item in partial.blockers} == {
        "frozen_authority_completeness_unproven",
        "semantic_decision_missing",
    }


def test_duplicate_keys_noncanonical_bytes_and_proof_count_bool_are_rejected() -> None:
    authority, decision, observed = _source()
    duplicate = observed[:-1] + b',"model_green":false}'
    with pytest.raises(IndependentStarSemanticAuthoringError, match="duplicate"):
        _verify(authority, decision, duplicate)
    noncanonical = b" " + observed
    with pytest.raises(IndependentStarSemanticAuthoringError, match="canonical"):
        _verify(authority, decision, noncanonical)

    proof = _verify(authority, decision, observed)
    with pytest.raises(IndependentStarSemanticAuthoringError, match="nonnegative integer"):
        StarSemanticAuthoringIndependentProofV1(
            authority_inventory_sha256=proof.authority_inventory_sha256,
            decision_inventory_sha256=proof.decision_inventory_sha256,
            observed_generation_bytes_sha256=proof.observed_generation_bytes_sha256,
            generation_sha256=proof.generation_sha256,
            candidate_count=True,  # type: ignore[arg-type]
            blocker_count=proof.blocker_count,
            verified=True,
            admitted=False,
            model_green=False,
        )
    proof_payload = proof.to_dict()
    proof_payload["candidate_count"] = True
    proof_payload["proof_sha256"] = canonical_star_semantic_authoring_sha256(
        {key: value for key, value in proof_payload.items() if key != "proof_sha256"}
    )
    with pytest.raises(IndependentStarSemanticAuthoringError, match="invalid type"):
        StarSemanticAuthoringIndependentProofV1.from_dict(proof_payload)


def test_independent_verifier_has_no_primary_module_or_helper_import_boundary() -> None:
    path = Path("src/nbadb/contracts/star_semantic_authoring_verifier.py")
    source = path.read_text()
    tree = ast.parse(source)
    imported_modules = {
        node.module
        for node in ast.walk(tree)
        if isinstance(node, ast.ImportFrom) and node.module is not None
    }
    imported_modules.update(
        alias.name
        for node in ast.walk(tree)
        if isinstance(node, ast.Import)
        for alias in node.names
    )

    assert "nbadb.contracts.star_semantic_authoring" not in imported_modules
    assert "nbadb.contracts.star_semantic_contract" not in imported_modules
    assert "nbadb.contracts.star_semantic_inventory" not in imported_modules
    assert "from nbadb" not in source


def json_loads(raw: bytes) -> dict[str, object]:
    import json

    value = json.loads(raw)
    assert type(value) is dict
    return value
