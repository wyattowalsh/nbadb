from __future__ import annotations

import json
from dataclasses import replace

import pytest

from nbadb.contracts.review_evidence import ReviewReceiptV1, ReviewValidationReceiptV1
from nbadb.contracts.stable_model_disposition import (
    StableModelCandidateV1,
    StableModelDispositionError,
    StableModelDispositionInventoryV1,
    StableModelDispositionV1,
    compile_stable_model_disposition_inventory,
    draft_required_model_dispositions,
)


def _candidate(
    candidate_id: str,
    *,
    kind: str = "fact",
    gate_requirement: str | None = None,
    dependencies: tuple[str, ...] = (),
    implementation_status: str = "implemented",
) -> StableModelCandidateV1:
    return StableModelCandidateV1(
        candidate_id=candidate_id,
        candidate_kind=kind,
        gate_requirement=(
            gate_requirement
            if gate_requirement is not None
            else (
                "lossless_required"
                if kind in {"source", "staging"}
                else "experimental_only"
                if kind == "experimental_model"
                else "stable_required"
            )
        ),
        structural_sha256=("a" if candidate_id == "source.base" else "b") * 64,
        dependency_ids=tuple(sorted(dependencies)),
        evidence_sha256s=("c" * 64,),
        implementation_status=implementation_status,
        implementation_sha256=("d" * 64 if implementation_status == "implemented" else None),
    )


def _decision(
    candidate: StableModelCandidateV1,
    *,
    disposition: str = "stable",
    review_digest: str = "0" * 64,
) -> StableModelDispositionV1:
    return StableModelDispositionV1(
        candidate_id=candidate.candidate_id,
        candidate_sha256=candidate.candidate_sha256,
        candidate_structural_sha256=candidate.structural_sha256,
        disposition=disposition,
        reason_code=f"decision:{disposition}",
        reason_evidence_sha256s=("e" * 64,),
        revalidation_owner="owner:model-governance",
        revalidation_trigger="authority-change",
        review_receipt_sha256=review_digest,
    )


def _review(
    candidate: StableModelCandidateV1,
    decision: StableModelDispositionV1,
    *,
    disposition: str = "accepted",
) -> ReviewReceiptV1:
    validations = tuple(
        sorted(
            ReviewValidationReceiptV1(
                receipt_id=f"test:{validation_class}",
                validation_class=validation_class,
                command_sha256=character * 64,
                evidence_sha256=character * 64,
                passed=True,
            )
            for validation_class, character in (
                ("positive", "1"),
                ("negative", "2"),
                ("mutation", "3"),
            )
        )
    )
    if disposition == "changes_required":
        validations = tuple(
            replace(item, passed=False) if item.validation_class == "mutation" else item
            for item in validations
        )
    return ReviewReceiptV1(
        subject_kind="stable_model_disposition",
        subject_semantic_sha256=decision.semantic_sha256,
        author_task_id=f"author:{candidate.candidate_id}",
        author_role="model-author",
        reviewer_task_id=f"reviewer:{candidate.candidate_id}",
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
        disposition=disposition,
        findings=(),
        validation_receipts=validations,
    )


def _reviewed_decision(
    candidate: StableModelCandidateV1,
    *,
    disposition: str = "stable",
    review_disposition: str = "accepted",
) -> tuple[StableModelDispositionV1, ReviewReceiptV1]:
    provisional = _decision(candidate, disposition=disposition)
    review = _review(candidate, provisional, disposition=review_disposition)
    return replace(provisional, review_receipt_sha256=review.receipt_sha256), review


def test_requirement_preserving_drafts_cover_every_candidate_without_faking_review() -> None:
    source = _candidate("source.base", kind="source")
    fact = _candidate("fact.output", dependencies=(source.candidate_id,))
    missing_fact = _candidate(
        "fact.missing",
        dependencies=(source.candidate_id,),
        implementation_status="missing",
    )
    experiment = _candidate(
        "experimental.rapm",
        kind="experimental_model",
        implementation_status="missing",
    )
    authority_sha256 = "f" * 64

    drafts = draft_required_model_dispositions(
        candidate_source_authority_sha256=authority_sha256,
        candidates=(experiment, missing_fact, fact, source),
    )
    by_id = {item.candidate_id: item for item in drafts}

    assert tuple(item.candidate_id for item in drafts) == tuple(sorted(by_id))
    assert by_id[source.candidate_id].disposition == "stable"
    assert by_id[fact.candidate_id].disposition == "stable"
    assert by_id[missing_fact.candidate_id].disposition == "stable"
    assert by_id[experiment.candidate_id].disposition == "experimental"
    assert all(authority_sha256 in item.reason_evidence_sha256s for item in drafts)
    assert all(item.review_receipt_sha256 != "0" * 64 for item in drafts)

    inventory = compile_stable_model_disposition_inventory(
        candidate_source_authority_sha256=authority_sha256,
        candidates=(source, fact, missing_fact, experiment),
        dispositions=drafts,
        review_receipts=(),
    )
    blocker_pairs = {(item.candidate_id, item.code) for item in inventory.blockers}
    assert all(
        (candidate.candidate_id, "independent_review_receipt_missing") in blocker_pairs
        for candidate in (source, fact, missing_fact, experiment)
    )
    assert (
        missing_fact.candidate_id,
        "stable_implementation_missing",
    ) in blocker_pairs
    assert not any(item.code == "candidate_disposition_missing" for item in inventory.blockers)
    assert inventory.release_gate_green is False


def test_requirement_preserving_draft_review_identity_binds_candidate_source() -> None:
    candidate = _candidate("fact.output")

    first = draft_required_model_dispositions(
        candidate_source_authority_sha256="e" * 64,
        candidates=(candidate,),
    )
    second = draft_required_model_dispositions(
        candidate_source_authority_sha256="f" * 64,
        candidates=(candidate,),
    )

    assert first[0].semantic_sha256 != second[0].semantic_sha256
    assert first[0].review_receipt_sha256 != second[0].review_receipt_sha256


def test_complete_reviewed_candidate_partition_can_be_green_and_round_trip() -> None:
    source = _candidate("source.base", kind="source")
    fact = _candidate("fact.output", dependencies=(source.candidate_id,))
    experiment = _candidate(
        "experimental.rapm",
        kind="experimental_model",
        implementation_status="missing",
    )
    pairs = (
        _reviewed_decision(source),
        _reviewed_decision(fact),
        _reviewed_decision(experiment, disposition="experimental"),
    )

    inventory = compile_stable_model_disposition_inventory(
        candidate_source_authority_sha256="f" * 64,
        candidates=(source, fact, experiment),
        dispositions=tuple(pair[0] for pair in pairs),
        review_receipts=tuple(pair[1] for pair in pairs),
    )

    assert inventory.release_gate_green is True
    assert inventory.blockers == ()
    assert inventory.inventory_sha256 == inventory.to_dict()["inventory_sha256"]
    assert (
        StableModelDispositionInventoryV1.from_canonical_bytes(inventory.canonical_bytes)
        == inventory
    )


@pytest.mark.parametrize(
    ("case", "expected_code"),
    [
        ("missing_disposition", "candidate_disposition_missing"),
        ("missing_review", "independent_review_receipt_missing"),
        ("changes_required", "independent_review_changes_required"),
        ("missing_implementation", "stable_implementation_missing"),
        ("public_experimental", "stable_surface_deferred_as_experimental"),
    ],
)
def test_incomplete_or_deferred_candidate_partition_remains_red(
    case: str,
    expected_code: str,
) -> None:
    candidate = _candidate(
        "fact.output",
        implementation_status="missing" if case == "missing_implementation" else "implemented",
    )
    if case == "missing_disposition":
        decisions: tuple[StableModelDispositionV1, ...] = ()
        reviews: tuple[ReviewReceiptV1, ...] = ()
    else:
        disposition = "experimental" if case == "public_experimental" else "stable"
        decision, review = _reviewed_decision(
            candidate,
            disposition=disposition,
            review_disposition=("changes_required" if case == "changes_required" else "accepted"),
        )
        decisions = (decision,)
        reviews = () if case == "missing_review" else (review,)

    inventory = compile_stable_model_disposition_inventory(
        candidate_source_authority_sha256="f" * 64,
        candidates=(candidate,),
        dispositions=decisions,
        review_receipts=reviews,
    )

    assert inventory.release_gate_green is False
    assert expected_code in {item.code for item in inventory.blockers}


def test_stable_candidate_requires_stable_dependency_disposition() -> None:
    source = _candidate("source.base", kind="source")
    fact = _candidate("fact.output", dependencies=(source.candidate_id,))
    source_decision, source_review = _reviewed_decision(source, disposition="rejected")
    fact_decision, fact_review = _reviewed_decision(fact)

    inventory = compile_stable_model_disposition_inventory(
        candidate_source_authority_sha256="f" * 64,
        candidates=(source, fact),
        dispositions=(source_decision, fact_decision),
        review_receipts=(source_review, fact_review),
    )

    assert any(
        item.candidate_id == fact.candidate_id
        and item.code == f"nonstable_dependency:{source.candidate_id}"
        for item in inventory.blockers
    )


@pytest.mark.parametrize("disposition", ["experimental", "withheld", "rejected"])
def test_required_candidate_cannot_be_deferred_because_implementation_is_missing(
    disposition: str,
) -> None:
    candidate = _candidate("fact.required", implementation_status="missing")
    decision, review = _reviewed_decision(candidate, disposition=disposition)

    inventory = compile_stable_model_disposition_inventory(
        candidate_source_authority_sha256="f" * 64,
        candidates=(candidate,),
        dispositions=(decision,),
        review_receipts=(review,),
    )

    assert inventory.release_gate_green is False
    assert "required_candidate_not_stable" in {item.code for item in inventory.blockers}


def test_reviewed_optional_candidate_may_be_rejected_without_blocking_stable_release() -> None:
    candidate = _candidate(
        "analytics.optional",
        gate_requirement="optional_candidate",
        implementation_status="not_applicable",
    )
    decision, review = _reviewed_decision(candidate, disposition="rejected")

    inventory = compile_stable_model_disposition_inventory(
        candidate_source_authority_sha256="f" * 64,
        candidates=(candidate,),
        dispositions=(decision,),
        review_receipts=(review,),
    )

    assert inventory.release_gate_green is True
    assert inventory.blockers == ()


def test_candidate_kind_and_gate_requirement_must_be_coherent() -> None:
    with pytest.raises(StableModelDispositionError, match="must be lossless_required"):
        _candidate("source.base", kind="source", gate_requirement="optional_candidate")
    with pytest.raises(StableModelDispositionError, match="must be experimental_only"):
        _candidate(
            "experimental.rapm",
            kind="experimental_model",
            gate_requirement="optional_candidate",
        )
    with pytest.raises(StableModelDispositionError, match="must use experimental_model"):
        _candidate("fact.output", gate_requirement="experimental_only")


def test_join_rejects_foreign_stale_and_rebound_evidence() -> None:
    candidate = _candidate("fact.output")
    foreign = _candidate("fact.foreign")
    foreign_decision, foreign_review = _reviewed_decision(foreign)
    with pytest.raises(StableModelDispositionError, match="foreign candidates"):
        compile_stable_model_disposition_inventory(
            candidate_source_authority_sha256="f" * 64,
            candidates=(candidate,),
            dispositions=(foreign_decision,),
            review_receipts=(foreign_review,),
        )

    decision, review = _reviewed_decision(candidate)
    with pytest.raises(StableModelDispositionError, match="structural authority drifted"):
        compile_stable_model_disposition_inventory(
            candidate_source_authority_sha256="f" * 64,
            candidates=(candidate,),
            dispositions=(replace(decision, candidate_structural_sha256="9" * 64),),
            review_receipts=(review,),
        )

    with pytest.raises(StableModelDispositionError, match="candidate authority drifted"):
        compile_stable_model_disposition_inventory(
            candidate_source_authority_sha256="f" * 64,
            candidates=(replace(candidate, evidence_sha256s=("8" * 64,)),),
            dispositions=(decision,),
            review_receipts=(review,),
        )

    rebound_decision = replace(
        decision,
        review_receipt_sha256=foreign_review.receipt_sha256,
    )
    with pytest.raises(StableModelDispositionError, match="rebound to foreign evidence"):
        compile_stable_model_disposition_inventory(
            candidate_source_authority_sha256="f" * 64,
            candidates=(candidate,),
            dispositions=(rebound_decision,),
            review_receipts=(foreign_review,),
        )


def test_direct_constructor_recomputes_complete_join_and_rejects_false_green() -> None:
    candidate = _candidate("fact.output")
    decision, _review_receipt = _reviewed_decision(candidate)

    for dispositions, reviews in (((), ()), ((decision,), ())):
        with pytest.raises(
            StableModelDispositionError,
            match="blocker inventory differs from the exact candidate/disposition/review join",
        ):
            StableModelDispositionInventoryV1(
                candidate_source_authority_sha256="f" * 64,
                candidates=(candidate,),
                dispositions=dispositions,
                review_receipts=reviews,
                blockers=(),
                release_gate_green=True,
            )


def test_direct_constructor_rejects_foreign_stale_and_rebound_evidence() -> None:
    candidate = _candidate("fact.output")
    foreign = _candidate("fact.foreign")
    decision, review = _reviewed_decision(candidate)
    foreign_decision, foreign_review = _reviewed_decision(foreign)

    attacks = (
        ((foreign_decision,), (foreign_review,), "foreign candidates"),
        (
            (replace(decision, candidate_structural_sha256="9" * 64),),
            (review,),
            "structural authority drifted",
        ),
        (
            (replace(decision, candidate_sha256="9" * 64),),
            (review,),
            "candidate authority drifted",
        ),
        (
            (replace(decision, review_receipt_sha256=foreign_review.receipt_sha256),),
            (foreign_review,),
            "rebound to foreign evidence",
        ),
    )
    for dispositions, reviews, message in attacks:
        with pytest.raises(StableModelDispositionError, match=message):
            StableModelDispositionInventoryV1(
                candidate_source_authority_sha256="f" * 64,
                candidates=(candidate,),
                dispositions=dispositions,
                review_receipts=reviews,
                blockers=(),
                release_gate_green=True,
            )


def test_direct_constructor_cannot_erase_derived_blockers_before_serialization() -> None:
    candidate = _candidate("fact.output")
    decision = _decision(candidate)
    red_inventory = compile_stable_model_disposition_inventory(
        candidate_source_authority_sha256="f" * 64,
        candidates=(candidate,),
        dispositions=(decision,),
        review_receipts=(),
    )

    assert red_inventory.canonical_bytes
    with pytest.raises(
        StableModelDispositionError,
        match="blocker inventory differs from the exact candidate/disposition/review join",
    ):
        replace(red_inventory, blockers=(), release_gate_green=True)


def test_candidate_graph_rejects_unknown_dependencies_and_cycles() -> None:
    with pytest.raises(StableModelDispositionError, match="inventory must be nonempty"):
        compile_stable_model_disposition_inventory(
            candidate_source_authority_sha256="f" * 64,
            candidates=(),
            dispositions=(),
            review_receipts=(),
        )

    fact = _candidate("fact.output")
    inverted_source = _candidate(
        "source.base",
        kind="source",
        dependencies=(fact.candidate_id,),
    )
    with pytest.raises(StableModelDispositionError, match="dependency leaves"):
        compile_stable_model_disposition_inventory(
            candidate_source_authority_sha256="f" * 64,
            candidates=(fact, inverted_source),
            dispositions=(),
            review_receipts=(),
        )

    inverted_staging = _candidate(
        "staging.output",
        kind="staging",
        dependencies=(fact.candidate_id,),
    )
    with pytest.raises(StableModelDispositionError, match="dependency-layer inversions"):
        compile_stable_model_disposition_inventory(
            candidate_source_authority_sha256="f" * 64,
            candidates=(fact, inverted_staging),
            dispositions=(),
            review_receipts=(),
        )

    unknown = _candidate("fact.output", dependencies=("source.missing",))
    with pytest.raises(StableModelDispositionError, match="unknown dependencies"):
        compile_stable_model_disposition_inventory(
            candidate_source_authority_sha256="f" * 64,
            candidates=(unknown,),
            dispositions=(),
            review_receipts=(),
        )

    first = _candidate("fact.first", dependencies=("fact.second",))
    second = _candidate("fact.second", dependencies=("fact.first",))
    with pytest.raises(StableModelDispositionError, match="contains a cycle"):
        compile_stable_model_disposition_inventory(
            candidate_source_authority_sha256="f" * 64,
            candidates=(first, second),
            dispositions=(),
            review_receipts=(),
        )


def test_canonical_readback_rejects_mutation_duplicate_keys_and_whitespace() -> None:
    candidate = _candidate("fact.output")
    decision, review = _reviewed_decision(candidate)
    inventory = compile_stable_model_disposition_inventory(
        candidate_source_authority_sha256="f" * 64,
        candidates=(candidate,),
        dispositions=(decision,),
        review_receipts=(review,),
    )
    payload = inventory.to_dict()
    payload["release_gate_green"] = False
    with pytest.raises(StableModelDispositionError, match="differs from the exact recomputed"):
        StableModelDispositionInventoryV1.from_dict(payload)

    payload = inventory.to_dict()
    payload["schema_version"] = True
    with pytest.raises(StableModelDispositionError, match="identity is invalid"):
        StableModelDispositionInventoryV1.from_dict(payload)

    payload = inventory.to_dict()
    payload["release_gate_green"] = 1
    with pytest.raises(StableModelDispositionError, match="exact boolean"):
        StableModelDispositionInventoryV1.from_dict(payload)

    duplicate = inventory.canonical_bytes.replace(
        b'{"blockers"', b'{"kind":"duplicate","blockers"', 1
    )
    with pytest.raises(StableModelDispositionError, match="duplicate JSON key: kind"):
        StableModelDispositionInventoryV1.from_canonical_bytes(duplicate)

    with pytest.raises(StableModelDispositionError, match="not canonical"):
        StableModelDispositionInventoryV1.from_canonical_bytes(inventory.canonical_bytes + b"\n")


def test_serialized_inventory_is_plain_canonical_json() -> None:
    candidate = _candidate("fact.output")
    decision, review = _reviewed_decision(candidate)
    inventory = compile_stable_model_disposition_inventory(
        candidate_source_authority_sha256="f" * 64,
        candidates=(candidate,),
        dispositions=(decision,),
        review_receipts=(review,),
    )

    assert json.loads(inventory.canonical_bytes)["inventory_sha256"] == (inventory.inventory_sha256)
