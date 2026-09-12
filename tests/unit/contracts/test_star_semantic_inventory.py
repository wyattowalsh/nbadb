from __future__ import annotations

import hashlib
import json
from dataclasses import replace
from typing import cast

import pytest

from nbadb.contracts.review_evidence import ReviewReceiptV1, ReviewValidationReceiptV1
from nbadb.contracts.stable_model_disposition import (
    StableModelCandidateV1,
    StableModelDispositionInventoryV1,
    StableModelDispositionV1,
    compile_stable_model_disposition_inventory,
)
from nbadb.contracts.star_semantic_contract import (
    ColumnLineageEdgeV1,
    DependencyCardinalityV1,
    KeyGroupV1,
    RelationshipV1,
    RowPolicyV1,
    StarTableSemanticContractV1,
    TemporalPolicyV1,
)
from nbadb.contracts.star_semantic_inventory import (
    StarSemanticInventoryError,
    StarSemanticInventoryV1,
    StarTableSemanticAuthorityV1,
    compile_star_semantic_inventory,
    derive_star_semantic_authorities,
)
from nbadb.contracts.star_table_contract import (
    GrainContract,
    KeyPolicyContract,
    StarColumnContract,
    StarFamilyCounts,
    StarModelContractInventory,
    StarTableContract,
    TransformContract,
)


def _digest(value: object) -> str:
    payload = json.dumps(
        value,
        allow_nan=False,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode()
    return hashlib.sha256(payload).hexdigest()


def _structural_table() -> StarTableContract:
    columns = tuple(
        StarColumnContract(
            ordinal=ordinal,
            name=name,
            data_type="str" if name != "value" else "float64",
            nullable=False,
            unique=False,
            required=True,
            source=None,
            fk_ref=None,
            metadata_json="{}",
        )
        for ordinal, name in enumerate(
            ("game_id", "season_type", "team_id", "value", "observed_at")
        )
    )
    schema_sha256 = _digest(
        [
            {
                "ordinal": column.ordinal,
                "name": column.name,
                "data_type": column.data_type,
                "nullable": column.nullable,
                "unique": column.unique,
                "required": column.required,
                "source": column.source,
                "fk_ref": column.fk_ref,
                "metadata": {},
            }
            for column in columns
        ]
    )
    transform = TransformContract(
        class_name="SampleTransformer",
        qualname="SampleTransformer",
        runtime_module="nbadb.transform.facts.sample",
        binding_module="nbadb.transform.facts.sample",
        kind="sql",
        dependencies=("stg_sample",),
        implementation_sha256="3" * 64,
    )
    grain = GrainContract(
        label="sample",
        columns=(),
        evidence_kind="structural-only",
        reviewed=False,
    )
    key_policy = KeyPolicyContract(
        kind="unreviewed_bag",
        columns=(),
        reviewed=False,
        evidence_kind="structural-only",
    )
    payload = {
        "output_name": "fact_sample",
        "family": "fact",
        "purpose": "Synthetic structural test table.",
        "schema_class": "FactSampleSchema",
        "schema_module": "nbadb.schemas.star.fact_sample",
        "columns": [
            {
                "ordinal": column.ordinal,
                "name": column.name,
                "data_type": column.data_type,
                "nullable": column.nullable,
                "unique": column.unique,
                "required": column.required,
                "source": column.source,
                "fk_ref": column.fk_ref,
                "metadata": {},
            }
            for column in columns
        ],
        "schema_sha256": schema_sha256,
        "foreign_keys": [],
        "transform": {
            "class_name": transform.class_name,
            "qualname": transform.qualname,
            "runtime_module": transform.runtime_module,
            "binding_module": transform.binding_module,
            "kind": transform.kind,
            "dependencies": list(transform.dependencies),
            "implementation_sha256": transform.implementation_sha256,
        },
        "consumer_metadata": None,
        "grain": {
            "label": grain.label,
            "columns": [],
            "evidence_kind": grain.evidence_kind,
            "reviewed": grain.reviewed,
        },
        "key_policy": {
            "kind": key_policy.kind,
            "columns": [],
            "reviewed": key_policy.reviewed,
            "evidence_kind": key_policy.evidence_kind,
        },
        "semantic_policies": [],
        "blockers": [],
        "model_green": True,
    }
    return StarTableContract(
        output_name="fact_sample",
        family="fact",
        purpose="Synthetic structural test table.",
        schema_class="FactSampleSchema",
        schema_module="nbadb.schemas.star.fact_sample",
        columns=columns,
        schema_sha256=schema_sha256,
        foreign_keys=(),
        transform=transform,
        consumer_metadata=None,
        grain=grain,
        key_policy=key_policy,
        semantic_policies=(),
        blockers=(),
        model_green=True,
        contract_sha256=_digest(payload),
    )


def _structural_inventory(table: StarTableContract | None = None) -> StarModelContractInventory:
    table = _structural_table() if table is None else table
    counts = StarFamilyCounts(fact=1, dim=0, bridge=0, agg=0, analytics=0)
    payload = {
        "tables": [{"output_name": table.output_name, "contract_sha256": table.contract_sha256}],
        "family_counts": {
            "fact": 1,
            "dim": 0,
            "bridge": 0,
            "agg": 0,
            "analytics": 0,
        },
        "blocker_summary": [],
        "model_green": True,
    }
    return StarModelContractInventory(
        tables=(table,),
        family_counts=counts,
        blocker_summary=(),
        model_green=True,
        contract_sha256=_digest(payload),
    )


def _stable_review(
    candidate: StableModelCandidateV1,
    decision: StableModelDispositionV1,
) -> ReviewReceiptV1:
    return ReviewReceiptV1(
        subject_kind="stable_model_disposition",
        subject_semantic_sha256=decision.semantic_sha256,
        author_task_id="author:stable",
        author_role="model-author",
        reviewer_task_id="reviewer:stable",
        reviewer_role="independent-reviewer",
        independence_evidence_kind="independent_agent_review",
        independence_evidence_sha256="4" * 64,
        accepted_input_sha256s=tuple(
            sorted(
                {
                    candidate.candidate_sha256,
                    candidate.structural_sha256,
                    decision.semantic_sha256,
                    "f" * 64,
                }
            )
        ),
        disposition="accepted",
        findings=(),
        validation_receipts=_validation_receipts(),
    )


def _validation_receipts(*, accepted: bool = True) -> tuple[ReviewValidationReceiptV1, ...]:
    return tuple(
        sorted(
            ReviewValidationReceiptV1(
                receipt_id=f"test:{validation_class}",
                validation_class=validation_class,
                command_sha256=character * 64,
                evidence_sha256=character * 64,
                passed=accepted or validation_class != "mutation",
            )
            for validation_class, character in (
                ("positive", "1"),
                ("negative", "2"),
                ("mutation", "3"),
            )
        )
    )


def _stable_inventory(
    structural: StarModelContractInventory,
    *,
    disposition: str = "stable",
    candidate_kind: str = "fact",
    candidate_structural_sha256: str | None = None,
    implementation_sha256: str | None = None,
    candidate_evidence_sha256s: tuple[str, ...] | None = None,
    candidate_gate_requirement: str = "stable_required",
    include_star_candidate: bool = True,
) -> StableModelDispositionInventoryV1:
    table = structural.tables[0]
    if include_star_candidate:
        candidate = StableModelCandidateV1(
            candidate_id=f"star:{table.output_name}",
            candidate_kind=candidate_kind,
            gate_requirement=candidate_gate_requirement,
            structural_sha256=(
                table.contract_sha256
                if candidate_structural_sha256 is None
                else candidate_structural_sha256
            ),
            dependency_ids=(),
            evidence_sha256s=(
                tuple(
                    sorted(
                        {
                            structural.contract_sha256,
                            table.contract_sha256,
                            table.schema_sha256,
                            table.transform.implementation_sha256,
                        }
                    )
                )
                if candidate_evidence_sha256s is None
                else candidate_evidence_sha256s
            ),
            implementation_status="implemented",
            implementation_sha256=(
                table.transform.implementation_sha256
                if implementation_sha256 is None
                else implementation_sha256
            ),
        )
    else:
        candidate = StableModelCandidateV1(
            candidate_id="source:base",
            candidate_kind="source",
            gate_requirement="lossless_required",
            structural_sha256="a" * 64,
            dependency_ids=(),
            evidence_sha256s=("b" * 64,),
            implementation_status="implemented",
            implementation_sha256="c" * 64,
        )
    provisional = StableModelDispositionV1(
        candidate_id=candidate.candidate_id,
        candidate_sha256=candidate.candidate_sha256,
        candidate_structural_sha256=candidate.structural_sha256,
        disposition=disposition,
        reason_code=f"decision:{disposition}",
        reason_evidence_sha256s=("d" * 64,),
        revalidation_owner="owner:model-governance",
        revalidation_trigger="authority-change",
        review_receipt_sha256="0" * 64,
    )
    review = _stable_review(candidate, provisional)
    decision = replace(provisional, review_receipt_sha256=review.receipt_sha256)
    return compile_stable_model_disposition_inventory(
        candidate_source_authority_sha256="f" * 64,
        candidates=(candidate,),
        dispositions=(decision,),
        review_receipts=(review,),
    )


def _semantic_contract(
    structural: StarModelContractInventory,
    stable: StableModelDispositionInventoryV1,
    *,
    review_digest: str = "9" * 64,
    relationships: tuple[RelationshipV1, ...] | None = None,
) -> StarTableSemanticContractV1:
    table = structural.tables[0]
    decision = next(
        item for item in stable.dispositions if item.candidate_id == f"star:{table.output_name}"
    )
    return StarTableSemanticContractV1(
        table_name=table.output_name,
        table_family="fact",
        structural_table_sha256=table.contract_sha256,
        schema_sha256=table.schema_sha256,
        transform_sha256=table.transform.implementation_sha256,
        stable_disposition_sha256=decision.semantic_sha256,
        stability=decision.disposition,
        public_disposition="published",
        purpose_code="game-observation",
        purpose_evidence_sha256="5" * 64,
        ordered_columns=tuple(column.name for column in table.columns),
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
        functional_dependencies=(),
        relationships=(
            (
                RelationshipV1(
                    relationship_id="self:team",
                    local_columns=("team_id",),
                    target_table=table.output_name,
                    target_columns=("team_id",),
                    cardinality="many_to_one",
                    orphan_policy="allow",
                    timing="event_time",
                    evidence_sha256="8" * 64,
                ),
            )
            if relationships is None
            else relationships
        ),
        lineage_edges=tuple(
            sorted(
                ColumnLineageEdgeV1(
                    edge_id=f"lineage:{column.name}",
                    target_column=column.name,
                    source_kind="storage_occurrence",
                    source_ids=(f"stg_sample:{column.name}",),
                    source_dependency_ids=("stg_sample",),
                    transform_kind="copy",
                    expression_sha256=None,
                    evidence_sha256="a" * 64,
                )
                for column in table.columns
            )
        ),
        competition_discriminators=("season_type",),
        request_discriminators=("game_id",),
        source_mode="dependency_backed",
        source_precedence=table.transform.dependencies,
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
                equation_code="output-equals-input-grain",
                evidence_sha256="d" * 64,
            ),
        ),
        positive_witness_sha256s=("e" * 64,),
        negative_witness_sha256s=("f" * 64,),
        mutation_witness_sha256s=("0" * 64,),
        review_receipt_sha256=review_digest,
    )


def _semantic_review(
    contract: StarTableSemanticContractV1,
    *,
    authority_sha256: str,
    structural_inventory_sha256: str,
    stable_inventory_sha256: str,
    accepted: bool = True,
) -> ReviewReceiptV1:
    return ReviewReceiptV1(
        subject_kind="star_table_semantic_contract",
        subject_semantic_sha256=contract.semantic_sha256,
        author_task_id="author:semantic",
        author_role="semantic-author",
        reviewer_task_id="reviewer:semantic",
        reviewer_role="independent-reviewer",
        independence_evidence_kind="independent_agent_review",
        independence_evidence_sha256="7" * 64,
        accepted_input_sha256s=tuple(
            sorted(
                {
                    contract.semantic_sha256,
                    contract.structural_table_sha256,
                    contract.schema_sha256,
                    contract.transform_sha256,
                    contract.stable_disposition_sha256,
                    authority_sha256,
                    structural_inventory_sha256,
                    stable_inventory_sha256,
                }
            )
        ),
        disposition="accepted" if accepted else "changes_required",
        findings=(),
        validation_receipts=_validation_receipts(accepted=accepted),
    )


def _complete_join() -> tuple[
    StarModelContractInventory,
    StableModelDispositionInventoryV1,
    StarTableSemanticContractV1,
    ReviewReceiptV1,
    StarSemanticInventoryV1,
]:
    structural = _structural_inventory()
    stable = _stable_inventory(structural)
    authority = derive_star_semantic_authorities(
        structural_inventory=structural,
        stable_disposition_inventory=stable,
    )[0]
    provisional = _semantic_contract(structural, stable)
    review = _semantic_review(
        provisional,
        authority_sha256=authority.authority_sha256,
        structural_inventory_sha256=structural.contract_sha256,
        stable_inventory_sha256=stable.inventory_sha256,
    )
    contract = replace(provisional, review_receipt_sha256=review.receipt_sha256)
    inventory = compile_star_semantic_inventory(
        structural_inventory=structural,
        stable_disposition_inventory=stable,
        semantic_contracts=(contract,),
        review_receipts=(review,),
    )
    return structural, stable, contract, review, inventory


def test_authority_derivation_binds_exact_dynamic_structural_and_stable_parents() -> None:
    structural = _structural_inventory()
    stable = _stable_inventory(structural)

    authorities = derive_star_semantic_authorities(
        structural_inventory=structural,
        stable_disposition_inventory=stable,
    )

    assert len(authorities) == len(structural.tables) == 1
    authority = authorities[0]
    table = structural.tables[0]
    candidate = stable.candidates[0]
    disposition = stable.dispositions[0]
    assert authority.output_name == table.output_name
    assert authority.table_family == "fact"
    assert authority.ordered_columns == tuple(column.name for column in table.columns)
    assert authority.transformer_dependencies == table.transform.dependencies
    assert authority.expected_candidate_id == f"star:{table.output_name}"
    assert authority.candidate_sha256 == candidate.candidate_sha256
    assert authority.candidate_gate_requirement == "stable_required"
    assert authority.candidate_implementation_sha256 == table.transform.implementation_sha256
    assert authority.disposition_semantic_sha256 == disposition.semantic_sha256
    assert authority.disposition_status == "stable"


def test_complete_stable_published_reviewed_join_is_green_and_round_trips() -> None:
    _structural, _stable, _contract, _review, inventory = _complete_join()

    assert inventory.model_green is True
    assert inventory.blockers == ()
    assert inventory.inventory_sha256 == inventory.to_dict()["inventory_sha256"]
    assert StarSemanticInventoryV1.from_canonical_bytes(inventory.canonical_bytes) == inventory


def test_pre_authoring_inventory_is_canonically_red_for_missing_contract_and_review() -> None:
    structural = _structural_inventory()
    stable = _stable_inventory(structural)

    inventory = compile_star_semantic_inventory(
        structural_inventory=structural,
        stable_disposition_inventory=stable,
        semantic_contracts=(),
        review_receipts=(),
    )

    assert inventory.model_green is False
    assert {(item.scope_id, item.code) for item in inventory.blockers} == {
        ("fact_sample", "semantic_contract_missing"),
        ("fact_sample", "semantic_review_missing"),
    }
    assert StarSemanticInventoryV1.from_canonical_bytes(inventory.canonical_bytes) == inventory


def test_missing_candidate_and_disposition_remain_table_scoped_blockers() -> None:
    structural = _structural_inventory()
    stable = _stable_inventory(structural, include_star_candidate=False)

    inventory = compile_star_semantic_inventory(
        structural_inventory=structural,
        stable_disposition_inventory=stable,
        semantic_contracts=(),
        review_receipts=(),
    )

    codes = {item.code for item in inventory.blockers if item.scope_id == "fact_sample"}
    assert {"stable_candidate_missing", "stable_disposition_missing"} <= codes


def test_nonstable_public_table_and_globally_red_stable_inventory_both_block() -> None:
    structural = _structural_inventory()
    stable = _stable_inventory(structural, disposition="experimental")

    inventory = compile_star_semantic_inventory(
        structural_inventory=structural,
        stable_disposition_inventory=stable,
        semantic_contracts=(),
        review_receipts=(),
    )

    blockers = {(item.scope_id, item.code) for item in inventory.blockers}
    assert ("inventory", "stable_disposition_inventory_not_green") in blockers
    assert ("fact_sample", "registered_public_table_not_stable") in blockers


@pytest.mark.parametrize(
    ("candidate_kwargs", "message"),
    [
        ({"candidate_kind": "dimension"}, "candidate kind drifted"),
        ({"candidate_evidence_sha256s": ("8" * 64,)}, "evidence authority drifted"),
        ({"candidate_gate_requirement": "optional_candidate"}, "gate requirement drifted"),
    ],
)
def test_authority_derivation_rejects_candidate_family_and_parent_drift(
    candidate_kwargs: dict[str, str],
    message: str,
) -> None:
    structural = _structural_inventory()
    stable = _stable_inventory(structural, **candidate_kwargs)

    with pytest.raises(StarSemanticInventoryError, match=message):
        derive_star_semantic_authorities(
            structural_inventory=structural,
            stable_disposition_inventory=stable,
        )


@pytest.mark.parametrize(
    ("mutation", "message"),
    [
        ("structural", "structural table parent drifted"),
        ("schema", "schema parent drifted"),
        ("transform", "transform parent drifted"),
        ("columns", "ordered columns drifted"),
        ("source", "source precedence drifted"),
    ],
)
def test_semantic_contract_rejects_parent_order_and_source_precedence_drift(
    mutation: str,
    message: str,
) -> None:
    structural, stable, contract, _review, _inventory = _complete_join()
    if mutation == "structural":
        mutated = replace(contract, structural_table_sha256="1" * 64)
    elif mutation == "schema":
        mutated = replace(contract, schema_sha256="2" * 64)
    elif mutation == "transform":
        mutated = replace(contract, transform_sha256="4" * 64)
    elif mutation == "columns":
        mutated = replace(contract, ordered_columns=tuple(reversed(contract.ordered_columns)))
    else:
        mutated_edges = tuple(
            replace(edge, source_dependency_ids=("stg_other",)) for edge in contract.lineage_edges
        )
        mutated = replace(
            contract,
            source_precedence=("stg_other",),
            lineage_edges=mutated_edges,
            dependency_cardinalities=(
                replace(contract.dependency_cardinalities[0], dependency_id="stg_other"),
            ),
        )

    with pytest.raises(StarSemanticInventoryError, match=message):
        compile_star_semantic_inventory(
            structural_inventory=structural,
            stable_disposition_inventory=stable,
            semantic_contracts=(mutated,),
            review_receipts=(),
        )


@pytest.mark.parametrize("target", ["table", "column"])
def test_relationship_targets_are_checked_against_embedded_structural_universe(
    target: str,
) -> None:
    structural, stable, contract, _review, _inventory = _complete_join()
    relation = contract.relationships[0]
    relation = (
        replace(relation, target_table="fact_foreign")
        if target == "table"
        else replace(relation, target_columns=("missing_column",))
    )
    mutated = replace(contract, relationships=(relation,))

    with pytest.raises(StarSemanticInventoryError, match="relationship targets"):
        compile_star_semantic_inventory(
            structural_inventory=structural,
            stable_disposition_inventory=stable,
            semantic_contracts=(mutated,),
            review_receipts=(),
        )


def test_missing_and_changes_required_semantic_reviews_remain_blockers() -> None:
    structural, stable, contract, _review, _inventory = _complete_join()
    missing = compile_star_semantic_inventory(
        structural_inventory=structural,
        stable_disposition_inventory=stable,
        semantic_contracts=(contract,),
        review_receipts=(),
    )
    assert "semantic_review_missing" in {item.code for item in missing.blockers}

    authority = derive_star_semantic_authorities(
        structural_inventory=structural,
        stable_disposition_inventory=stable,
    )[0]
    provisional = replace(contract, review_receipt_sha256="9" * 64)
    review = _semantic_review(
        provisional,
        authority_sha256=authority.authority_sha256,
        structural_inventory_sha256=structural.contract_sha256,
        stable_inventory_sha256=stable.inventory_sha256,
        accepted=False,
    )
    reviewed = replace(provisional, review_receipt_sha256=review.receipt_sha256)
    red = compile_star_semantic_inventory(
        structural_inventory=structural,
        stable_disposition_inventory=stable,
        semantic_contracts=(reviewed,),
        review_receipts=(review,),
    )
    assert "semantic_review_changes_required" in {item.code for item in red.blockers}


def test_foreign_contract_review_and_rebound_review_evidence_are_rejected() -> None:
    structural, stable, contract, review, _inventory = _complete_join()
    with pytest.raises(StarSemanticInventoryError, match="foreign tables"):
        compile_star_semantic_inventory(
            structural_inventory=structural,
            stable_disposition_inventory=stable,
            semantic_contracts=(replace(contract, table_name="fact_foreign"),),
            review_receipts=(),
        )

    extra_review = replace(review, reviewer_task_id="reviewer:other")
    with pytest.raises(StarSemanticInventoryError, match="foreign receipt"):
        compile_star_semantic_inventory(
            structural_inventory=structural,
            stable_disposition_inventory=stable,
            semantic_contracts=(contract,),
            review_receipts=(review, extra_review),
        )

    other_contract = replace(contract, purpose_code="other-purpose", review_receipt_sha256="9" * 64)
    authority = derive_star_semantic_authorities(
        structural_inventory=structural,
        stable_disposition_inventory=stable,
    )[0]
    other_review = _semantic_review(
        other_contract,
        authority_sha256=authority.authority_sha256,
        structural_inventory_sha256=structural.contract_sha256,
        stable_inventory_sha256=stable.inventory_sha256,
    )
    rebound = replace(contract, review_receipt_sha256=other_review.receipt_sha256)
    with pytest.raises(StarSemanticInventoryError, match="rebound to foreign semantics"):
        compile_star_semantic_inventory(
            structural_inventory=structural,
            stable_disposition_inventory=stable,
            semantic_contracts=(rebound,),
            review_receipts=(other_review,),
        )


def test_direct_constructor_recomputes_blockers_and_cannot_serialize_false_green() -> None:
    structural = _structural_inventory()
    stable = _stable_inventory(structural)
    red = compile_star_semantic_inventory(
        structural_inventory=structural,
        stable_disposition_inventory=stable,
        semantic_contracts=(),
        review_receipts=(),
    )

    with pytest.raises(StarSemanticInventoryError, match="blocker inventory differs"):
        replace(red, blockers=(), model_green=True)


def test_direct_constructor_rejects_stale_authority_and_mutable_rows() -> None:
    _structural, _stable, _contract, _review, green = _complete_join()
    stale_authority = replace(green.authorities[0], schema_sha256="8" * 64)
    with pytest.raises(StarSemanticInventoryError, match="schema parent drifted"):
        replace(green, authorities=(stale_authority,))
    with pytest.raises(StarSemanticInventoryError, match="exact typed tuple"):
        replace(
            green,
            authorities=cast(
                "tuple[StarTableSemanticAuthorityV1, ...]",
                list(green.authorities),
            ),
        )


def test_structural_inventory_must_be_nonempty_and_digest_consistent() -> None:
    empty = StarModelContractInventory(
        tables=(),
        family_counts=StarFamilyCounts(fact=0, dim=0, bridge=0, agg=0, analytics=0),
        blocker_summary=(),
        model_green=True,
        contract_sha256="0" * 64,
    )
    structural = _structural_inventory()
    stable = _stable_inventory(structural)
    with pytest.raises(StarSemanticInventoryError, match="must be nonempty"):
        derive_star_semantic_authorities(
            structural_inventory=empty,
            stable_disposition_inventory=stable,
        )
    with pytest.raises(StarSemanticInventoryError, match="inventory digest drifted"):
        derive_star_semantic_authorities(
            structural_inventory=replace(structural, contract_sha256="0" * 64),
            stable_disposition_inventory=stable,
        )


def test_canonical_readback_rejects_duplicate_keys_bool_alias_digest_and_whitespace() -> None:
    _structural, _stable, _contract, _review, inventory = _complete_join()
    duplicate = inventory.canonical_bytes.replace(
        b'{"authorities"',
        b'{"kind":"duplicate","authorities"',
        1,
    )
    with pytest.raises(StarSemanticInventoryError, match="duplicate JSON key: kind"):
        StarSemanticInventoryV1.from_canonical_bytes(duplicate)

    payload = inventory.to_dict()
    payload["model_green"] = 1
    with pytest.raises(StarSemanticInventoryError, match="exact boolean"):
        StarSemanticInventoryV1.from_dict(payload)

    payload = inventory.to_dict()
    payload["inventory_sha256"] = "0" * 64
    with pytest.raises(StarSemanticInventoryError, match="digest is invalid"):
        StarSemanticInventoryV1.from_dict(payload)

    with pytest.raises(StarSemanticInventoryError, match="not canonical"):
        StarSemanticInventoryV1.from_canonical_bytes(inventory.canonical_bytes + b"\n")
