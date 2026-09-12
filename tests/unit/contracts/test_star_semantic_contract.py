from __future__ import annotations

from dataclasses import replace

import pytest

from nbadb.contracts.review_evidence import ReviewReceiptV1, ReviewValidationReceiptV1
from nbadb.contracts.star_semantic_contract import (
    ColumnLineageEdgeV1,
    DependencyCardinalityV1,
    FunctionalDependencyV1,
    KeyGroupV1,
    RelationshipV1,
    RowPolicyV1,
    StarSemanticContractError,
    StarTableSemanticContractV1,
    TemporalPolicyV1,
)


def _contract(*, review_digest: str = "9" * 64) -> StarTableSemanticContractV1:
    return StarTableSemanticContractV1(
        table_name="fact_sample",
        table_family="fact",
        structural_table_sha256="1" * 64,
        schema_sha256="2" * 64,
        transform_sha256="3" * 64,
        stable_disposition_sha256="4" * 64,
        stability="stable",
        public_disposition="published",
        purpose_code="game-observation",
        purpose_evidence_sha256="5" * 64,
        ordered_columns=("game_id", "season_type", "team_id", "value", "observed_at"),
        grain_dimensions=("game_id", "team_id"),
        observation_identity=("game_id", "season_type", "team_id"),
        key_mode="keyed",
        key_groups=(
            KeyGroupV1(
                key_id="natural:game-team",
                key_kind="natural",
                columns=("game_id", "team_id"),
                null_policy="forbidden",
                evidence_sha256="6" * 64,
            ),
        ),
        functional_dependencies=(
            FunctionalDependencyV1(
                dependency_id="fd:game-team-value",
                determinants=("game_id", "team_id"),
                dependents=("value",),
                evidence_sha256="7" * 64,
            ),
        ),
        relationships=(
            RelationshipV1(
                relationship_id="fk:team",
                local_columns=("team_id",),
                target_table="dim_team",
                target_columns=("team_id",),
                cardinality="many_to_one",
                orphan_policy="reject",
                timing="event_time",
                evidence_sha256="8" * 64,
            ),
        ),
        lineage_edges=tuple(
            ColumnLineageEdgeV1(
                edge_id=f"lineage:{column}",
                target_column=column,
                source_kind="storage_occurrence",
                source_ids=(f"stg_sample:{column}",),
                source_dependency_ids=("stg_sample",),
                transform_kind="copy",
                expression_sha256=None,
                evidence_sha256="a" * 64,
            )
            for column in ("game_id", "observed_at", "season_type", "team_id", "value")
        ),
        competition_discriminators=("season_type",),
        request_discriminators=("game_id",),
        source_mode="dependency_backed",
        source_precedence=("stg_sample",),
        row_policy=RowPolicyV1(
            row_mode="event",
            filter_policy="preserve",
            dedup_policy="none",
            union_policy="none",
            aggregation_policy="none",
            additivity="additive",
            evidence_sha256="b" * 64,
        ),
        temporal_policy=TemporalPolicyV1(
            event_columns=("game_id",),
            observation_columns=("observed_at",),
            load_columns=(),
            version_columns=(),
            feature_cutoff_columns=("observed_at",),
            correction_policy="replace_scope",
            truth_mode="as_observed",
            evidence_sha256="c" * 64,
        ),
        scd_policy="not_applicable",
        algorithm_id=None,
        algorithm_version=None,
        coverage_policy="complete_scope",
        incomplete_policy="reject",
        empty_policy="materialize_typed_empty",
        unavailable_policy="typed_unavailable",
        dependency_cardinalities=(
            DependencyCardinalityV1(
                dependency_id="stg_sample",
                effect="row_preserving",
                equation_code="output-equals-distinct-input-grain",
                evidence_sha256="d" * 64,
            ),
        ),
        positive_witness_sha256s=("e" * 64,),
        negative_witness_sha256s=("f" * 64,),
        mutation_witness_sha256s=("0" * 64,),
        review_receipt_sha256=review_digest,
    )


def _review(contract: StarTableSemanticContractV1, *, accepted: bool = True) -> ReviewReceiptV1:
    validations = tuple(
        sorted(
            ReviewValidationReceiptV1(
                receipt_id=f"test:{kind}",
                validation_class=kind,
                command_sha256=character * 64,
                evidence_sha256=character * 64,
                passed=accepted or kind != "mutation",
            )
            for kind, character in (
                ("positive", "a"),
                ("negative", "b"),
                ("mutation", "c"),
            )
        )
    )
    return ReviewReceiptV1(
        subject_kind="star_table_semantic_contract",
        subject_semantic_sha256=contract.semantic_sha256,
        author_task_id="task:star-author",
        author_role="semantic-author",
        reviewer_task_id="task:star-reviewer",
        reviewer_role="independent-reviewer",
        independence_evidence_kind="independent_agent_review",
        independence_evidence_sha256="d" * 64,
        accepted_input_sha256s=tuple(
            sorted(
                {
                    contract.semantic_sha256,
                    contract.structural_table_sha256,
                    contract.schema_sha256,
                    contract.transform_sha256,
                    contract.stable_disposition_sha256,
                }
            )
        ),
        disposition="accepted" if accepted else "changes_required",
        findings=(),
        validation_receipts=validations,
    )


def _reviewed_contract() -> tuple[StarTableSemanticContractV1, ReviewReceiptV1]:
    provisional = _contract()
    review = _review(provisional)
    return replace(provisional, review_receipt_sha256=review.receipt_sha256), review


def _source_free_contract(*, algorithm_derived: bool = False) -> StarTableSemanticContractV1:
    contract = _contract()
    lineage = tuple(
        ColumnLineageEdgeV1(
            edge_id=f"lineage:{column}",
            target_column=column,
            source_kind="audit" if algorithm_derived else "literal",
            source_ids=(f"transform:fact_sample:{column}",),
            source_dependency_ids=(),
            transform_kind="expression" if algorithm_derived else "copy",
            expression_sha256="1" * 64 if algorithm_derived else None,
            evidence_sha256="a" * 64,
        )
        for column in sorted(contract.ordered_columns)
    )
    return replace(
        contract,
        source_mode="reviewed_source_free",
        source_precedence=(),
        lineage_edges=lineage,
        dependency_cardinalities=(),
        algorithm_id="algorithm:fact-sample" if algorithm_derived else None,
        algorithm_version="v1" if algorithm_derived else None,
    )


def test_typed_star_semantics_round_trip_and_bind_accepted_review() -> None:
    contract, review = _reviewed_contract()

    assert StarTableSemanticContractV1.from_canonical_bytes(contract.canonical_bytes) == contract
    contract.validate_review_receipt(review)
    assert contract.semantic_sha256 == contract.to_dict()["semantic_sha256"]


def test_reviewed_source_free_semantics_round_trip_with_literal_or_algorithm_lineage() -> None:
    literal = _source_free_contract()
    algorithm = _source_free_contract(algorithm_derived=True)

    assert StarTableSemanticContractV1.from_canonical_bytes(literal.canonical_bytes) == literal
    assert StarTableSemanticContractV1.from_canonical_bytes(algorithm.canonical_bytes) == algorithm
    assert literal.source_precedence == literal.dependency_cardinalities == ()
    assert algorithm.algorithm_id == "algorithm:fact-sample"


def test_source_mode_cannot_bypass_dependency_or_source_free_authority_invariants() -> None:
    dependency_backed = _contract()
    source_free = _source_free_contract()

    with pytest.raises(StarSemanticContractError, match="require nonempty"):
        replace(dependency_backed, source_precedence=())
    with pytest.raises(StarSemanticContractError, match="require empty"):
        replace(source_free, source_precedence=("stg_sample",))
    with pytest.raises(StarSemanticContractError, match="dependency identities"):
        replace(
            source_free,
            lineage_edges=dependency_backed.lineage_edges,
            source_precedence=(),
        )
    with pytest.raises(StarSemanticContractError, match="dependency cardinalities"):
        replace(
            source_free,
            dependency_cardinalities=dependency_backed.dependency_cardinalities,
        )
    with pytest.raises(StarSemanticContractError, match="require algorithm identity"):
        replace(
            _source_free_contract(algorithm_derived=True),
            algorithm_id=None,
            algorithm_version=None,
        )


def test_contract_requires_exact_lineage_coverage_for_every_ordered_column() -> None:
    contract = _contract()
    with pytest.raises(StarSemanticContractError, match="lineage target coverage differs"):
        replace(contract, lineage_edges=contract.lineage_edges[:-1])

    with pytest.raises(StarSemanticContractError, match="unknown columns"):
        replace(
            contract,
            lineage_edges=tuple(
                sorted(
                    (
                        *contract.lineage_edges,
                        replace(
                            contract.lineage_edges[0],
                            edge_id="lineage:foreign",
                            target_column="foreign",
                        ),
                    )
                )
            ),
        )

    with pytest.raises(StarSemanticContractError, match="exactly one edge per target"):
        replace(
            contract,
            lineage_edges=tuple(
                sorted(
                    (
                        *contract.lineage_edges,
                        replace(
                            contract.lineage_edges[0],
                            edge_id="lineage:duplicate-target",
                            source_ids=("stg_sample:duplicate",),
                        ),
                    )
                )
            ),
        )


def test_contract_rejects_empty_schema_key_and_relationship_ambiguity() -> None:
    contract = _contract()
    with pytest.raises(StarSemanticContractError, match="ordered_columns must be nonempty"):
        replace(contract, ordered_columns=())
    with pytest.raises(StarSemanticContractError, match="keyed table requires"):
        replace(contract, key_groups=())
    with pytest.raises(StarSemanticContractError, match="reviewed bag cannot carry"):
        replace(contract, key_mode="reviewed_bag")
    with pytest.raises(StarSemanticContractError, match="exact typed tuple"):
        replace(contract, key_groups=(object(),))
    with pytest.raises(StarSemanticContractError, match="semantically unique"):
        replace(
            contract,
            key_groups=tuple(
                sorted(
                    (
                        *contract.key_groups,
                        replace(
                            contract.key_groups[0],
                            key_id="candidate:game-team-conflict",
                            key_kind="candidate",
                            null_policy="allowed_equal",
                        ),
                    )
                )
            ),
        )
    with pytest.raises(StarSemanticContractError, match="unknown columns"):
        replace(
            contract,
            relationships=(replace(contract.relationships[0], local_columns=("foreign",)),),
        )
    with pytest.raises(StarSemanticContractError, match="semantic identities must be unique"):
        replace(
            contract,
            relationships=tuple(
                sorted(
                    (
                        *contract.relationships,
                        replace(
                            contract.relationships[0],
                            relationship_id="fk:team-conflict",
                            cardinality="many_to_many",
                            orphan_policy="allow",
                        ),
                    )
                )
            ),
        )


def test_contract_rejects_partial_algorithm_and_foreign_temporal_columns() -> None:
    contract = _contract()
    with pytest.raises(StarSemanticContractError, match="must co-occur"):
        replace(contract, algorithm_id="model:rapm")
    with pytest.raises(StarSemanticContractError, match="unknown columns"):
        replace(
            contract,
            temporal_policy=replace(
                contract.temporal_policy,
                load_columns=("loaded_at",),
            ),
        )


def test_contract_rejects_observation_identity_unrelated_to_grain_and_discriminators() -> None:
    contract = _contract()
    with pytest.raises(StarSemanticContractError, match="exactly cover grain"):
        replace(contract, observation_identity=("value",))
    with pytest.raises(StarSemanticContractError, match="semantic key columns"):
        replace(
            contract,
            grain_dimensions=("season_type",),
            observation_identity=("game_id", "season_type"),
        )


def test_contract_rejects_mutable_sequence_inputs() -> None:
    contract = _contract()
    with pytest.raises(StarSemanticContractError, match="ordered_columns must be an exact tuple"):
        replace(contract, ordered_columns=list(contract.ordered_columns))
    with pytest.raises(StarSemanticContractError, match="key columns must be an exact tuple"):
        KeyGroupV1(
            key_id="natural:test",
            key_kind="natural",
            columns=["game_id"],
            null_policy="forbidden",
            evidence_sha256="1" * 64,
        )
    with pytest.raises(
        StarSemanticContractError,
        match="relationship local_columns must be an exact tuple",
    ):
        replace(
            contract.relationships[0],
            local_columns=["team_id"],
        )


def test_contract_rejects_incoherent_lineage_source_arity() -> None:
    contract = _contract()
    with pytest.raises(StarSemanticContractError, match="copy lineage requires exactly one"):
        replace(
            contract.lineage_edges[0],
            source_ids=("stg_sample:first", "stg_sample:second"),
        )
    with pytest.raises(StarSemanticContractError, match="union lineage requires at least two"):
        replace(
            contract.lineage_edges[0],
            transform_kind="union",
            expression_sha256="1" * 64,
        )


def test_contract_rejects_temporal_and_scd_contradictions() -> None:
    contract = _contract()
    with pytest.raises(StarSemanticContractError, match="type2 SCD requires correction"):
        replace(contract, scd_policy="type2")
    with pytest.raises(StarSemanticContractError, match="type2 SCD requires version"):
        replace(
            contract,
            scd_policy="type2",
            temporal_policy=replace(contract.temporal_policy, correction_policy="scd"),
        )
    with pytest.raises(StarSemanticContractError, match="requires type2 SCD"):
        replace(
            contract,
            temporal_policy=replace(contract.temporal_policy, correction_policy="scd"),
        )
    with pytest.raises(StarSemanticContractError, match="as_observed requires observation"):
        replace(
            contract,
            temporal_policy=replace(contract.temporal_policy, observation_columns=()),
        )
    with pytest.raises(StarSemanticContractError, match="type1 SCD cannot carry version"):
        replace(
            contract,
            scd_policy="type1",
            temporal_policy=replace(
                contract.temporal_policy,
                version_columns=("observed_at",),
            ),
        )
    with pytest.raises(StarSemanticContractError, match="replacement or latest-truth"):
        replace(
            contract,
            scd_policy="type1",
            temporal_policy=replace(
                contract.temporal_policy,
                correction_policy="append_only",
            ),
        )


def test_contract_rejects_table_family_and_row_semantic_contradictions() -> None:
    contract = _contract()
    with pytest.raises(StarSemanticContractError, match="aggregate table requires"):
        replace(contract, table_name="agg_sample", table_family="aggregate")
    with pytest.raises(StarSemanticContractError, match="bridge table requires"):
        replace(contract, table_name="bridge_sample", table_family="bridge")


def test_contract_rejects_missing_or_foreign_dependency_cardinality() -> None:
    contract = _contract()
    with pytest.raises(StarSemanticContractError, match="exactly cover source_precedence"):
        replace(contract, dependency_cardinalities=())
    with pytest.raises(StarSemanticContractError, match="exactly cover source_precedence"):
        replace(
            contract,
            dependency_cardinalities=(
                replace(contract.dependency_cardinalities[0], dependency_id="foreign"),
            ),
        )

    with pytest.raises(StarSemanticContractError, match="lineage dependencies"):
        replace(
            contract,
            source_precedence=("foreign",),
            dependency_cardinalities=(
                replace(contract.dependency_cardinalities[0], dependency_id="foreign"),
            ),
        )


def test_review_binding_rejects_wrong_digest_semantics_inputs_and_changes_required() -> None:
    contract, review = _reviewed_contract()
    with pytest.raises(StarSemanticContractError, match="digest differs"):
        contract.validate_review_receipt(replace(review, independence_evidence_sha256="1" * 64))

    foreign_contract = replace(contract, purpose_code="foreign-purpose")
    foreign_review = _review(foreign_contract)
    rebound = replace(contract, review_receipt_sha256=foreign_review.receipt_sha256)
    with pytest.raises(StarSemanticContractError, match="foreign semantics"):
        rebound.validate_review_receipt(foreign_review)

    incomplete_review = replace(
        review,
        accepted_input_sha256s=(contract.semantic_sha256,),
    )
    incomplete_contract = replace(
        contract,
        review_receipt_sha256=incomplete_review.receipt_sha256,
    )
    with pytest.raises(StarSemanticContractError, match="omits required structural"):
        incomplete_contract.validate_review_receipt(incomplete_review)

    changes = _review(_contract(), accepted=False)
    changes_contract = replace(contract, review_receipt_sha256=changes.receipt_sha256)
    with pytest.raises(StarSemanticContractError, match="requires accepted disposition"):
        changes_contract.validate_review_receipt(changes)


def test_canonical_parser_rejects_digest_mutation_duplicate_keys_and_whitespace() -> None:
    contract = _contract()
    payload = contract.to_dict()
    payload["semantic_sha256"] = "f" * 64
    with pytest.raises(StarSemanticContractError, match="digest is invalid"):
        StarTableSemanticContractV1.from_dict(payload)

    payload = contract.to_dict()
    payload["schema_version"] = True
    with pytest.raises(StarSemanticContractError, match="identity is invalid"):
        StarTableSemanticContractV1.from_dict(payload)

    duplicate = contract.canonical_bytes.replace(
        b'{"algorithm_id"', b'{"kind":"duplicate","algorithm_id"', 1
    )
    with pytest.raises(StarSemanticContractError, match="duplicate JSON key: kind"):
        StarTableSemanticContractV1.from_canonical_bytes(duplicate)

    with pytest.raises(StarSemanticContractError, match="not canonical"):
        StarTableSemanticContractV1.from_canonical_bytes(contract.canonical_bytes + b"\n")


@pytest.mark.parametrize("field", ["purpose_code", "row_policy", "semantic_sha256"])
def test_contract_rejects_missing_and_unknown_members(field: str) -> None:
    payload = _contract().to_dict()
    del payload[field]
    with pytest.raises(StarSemanticContractError, match="fields differ"):
        StarTableSemanticContractV1.from_dict(payload)

    payload = _contract().to_dict()
    payload["reviewed"] = True
    with pytest.raises(StarSemanticContractError, match="unexpected=reviewed"):
        StarTableSemanticContractV1.from_dict(payload)
