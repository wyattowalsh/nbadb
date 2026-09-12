from __future__ import annotations

import hashlib
import json
from dataclasses import replace

import pytest

from nbadb.contracts import stable_model_disposition_verifier as verifier_module
from nbadb.contracts.review_evidence import ReviewReceiptV1, ReviewValidationReceiptV1
from nbadb.contracts.stable_model_disposition import (
    StableModelCandidateV1,
    StableModelDispositionV1,
    compile_stable_model_disposition_inventory,
)
from nbadb.contracts.stable_model_disposition_verifier import (
    IndependentStableModelDispositionError,
    StableModelDispositionIndependentProofV1,
    verify_stable_model_disposition_inventory_independently,
)


def _canonical(value: object) -> bytes:
    return json.dumps(
        value,
        allow_nan=False,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode()


def _candidate(
    candidate_id: str,
    *,
    kind: str = "fact",
    gate: str | None = None,
    dependencies: tuple[str, ...] = (),
    implemented: bool = True,
) -> StableModelCandidateV1:
    return StableModelCandidateV1(
        candidate_id=candidate_id,
        candidate_kind=kind,  # type: ignore[arg-type]
        gate_requirement=(
            gate
            or (
                "lossless_required"
                if kind in {"source", "staging"}
                else "experimental_only"
                if kind == "experimental_model"
                else "stable_required"
            )
        ),  # type: ignore[arg-type]
        structural_sha256=("a" if kind == "source" else "b") * 64,
        dependency_ids=dependencies,
        evidence_sha256s=("c" * 64,),
        implementation_status="implemented" if implemented else "missing",
        implementation_sha256="d" * 64 if implemented else None,
    )


def _reviewed(
    candidate: StableModelCandidateV1,
    *,
    source_sha256: str,
    disposition: str,
) -> tuple[StableModelDispositionV1, ReviewReceiptV1]:
    provisional = StableModelDispositionV1(
        candidate_id=candidate.candidate_id,
        candidate_sha256=candidate.candidate_sha256,
        candidate_structural_sha256=candidate.structural_sha256,
        disposition=disposition,  # type: ignore[arg-type]
        reason_code=f"decision:{disposition}",
        reason_evidence_sha256s=("e" * 64,),
        revalidation_owner="owner:model-governance",
        revalidation_trigger="authority-change",
        review_receipt_sha256="0" * 64,
    )
    validations = tuple(
        sorted(
            ReviewValidationReceiptV1(
                receipt_id=f"validation:{validation_class}",
                validation_class=validation_class,  # type: ignore[arg-type]
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
    review = ReviewReceiptV1(
        subject_kind="stable_model_disposition",
        subject_semantic_sha256=provisional.semantic_sha256,
        author_task_id=f"author:{candidate.candidate_id}",
        author_role="model-author",
        reviewer_task_id=f"reviewer:{candidate.candidate_id}",
        reviewer_role="independent-reviewer",
        independence_evidence_kind="independent_agent_review",
        independence_evidence_sha256="4" * 64,
        accepted_input_sha256s=tuple(
            sorted(
                {
                    source_sha256,
                    candidate.candidate_sha256,
                    candidate.structural_sha256,
                    provisional.semantic_sha256,
                }
            )
        ),
        disposition="accepted",
        findings=(),
        validation_receipts=validations,
    )
    return replace(provisional, review_receipt_sha256=review.receipt_sha256), review


def _inputs() -> tuple[
    str,
    tuple[StableModelCandidateV1, ...],
    tuple[StableModelDispositionV1, ...],
    tuple[ReviewReceiptV1, ...],
]:
    source_sha256 = "f" * 64
    source = _candidate("source.base", kind="source")
    fact = _candidate("fact.output", dependencies=(source.candidate_id,))
    experimental = _candidate("experimental.rapm", kind="experimental_model", implemented=False)
    pairs = (
        _reviewed(source, source_sha256=source_sha256, disposition="stable"),
        _reviewed(fact, source_sha256=source_sha256, disposition="stable"),
        _reviewed(
            experimental,
            source_sha256=source_sha256,
            disposition="experimental",
        ),
    )
    return (
        source_sha256,
        (source, fact, experimental),
        tuple(item[0] for item in pairs),
        tuple(item[1] for item in pairs),
    )


def _verify(
    source_sha256: str,
    candidates: tuple[StableModelCandidateV1, ...],
    dispositions: tuple[StableModelDispositionV1, ...],
    reviews: tuple[ReviewReceiptV1, ...],
    *,
    observed: bytes | None = None,
) -> StableModelDispositionIndependentProofV1:
    inventory = compile_stable_model_disposition_inventory(
        candidate_source_authority_sha256=source_sha256,
        candidates=candidates,
        dispositions=dispositions,
        review_receipts=reviews,
    )
    return verify_stable_model_disposition_inventory_independently(
        candidate_source_authority_sha256=source_sha256,
        candidate_canonical_bytes=tuple(_canonical(item.to_dict()) for item in candidates),
        disposition_canonical_bytes=tuple(_canonical(item.to_dict()) for item in dispositions),
        review_receipt_canonical_bytes=tuple(item.canonical_bytes for item in reviews),
        observed_inventory_canonical_bytes=observed or inventory.canonical_bytes,
    )


def _independent_inventory_bytes(
    *,
    source_sha256: str,
    candidates: tuple[StableModelCandidateV1, ...],
    dispositions: tuple[StableModelDispositionV1, ...],
    reviews: tuple[ReviewReceiptV1, ...],
    blockers: tuple[tuple[str, str], ...],
) -> bytes:
    candidate_rows = [
        item.to_dict() for item in sorted(candidates, key=lambda item: item.candidate_id)
    ]
    disposition_rows = [
        item.to_dict() for item in sorted(dispositions, key=lambda item: item.candidate_id)
    ]
    review_rows = [item.to_dict() for item in sorted(reviews, key=lambda item: item.receipt_sha256)]
    blocker_rows = [
        {"candidate_id": candidate_id, "code": code} for candidate_id, code in sorted(blockers)
    ]
    content = {
        "schema_version": 1,
        "kind": "nbadb_stable_model_disposition_inventory",
        "candidate_source_authority_sha256": source_sha256,
        "candidate_inventory_sha256": hashlib.sha256(_canonical(candidate_rows)).hexdigest(),
        "candidates": candidate_rows,
        "dispositions": disposition_rows,
        "review_receipts": review_rows,
        "blockers": blocker_rows,
        "release_gate_green": not blocker_rows,
    }
    return _canonical(
        {**content, "inventory_sha256": hashlib.sha256(_canonical(content)).hexdigest()}
    )


def _verify_independent_rows(
    *,
    source_sha256: str,
    candidates: tuple[StableModelCandidateV1, ...],
    dispositions: tuple[StableModelDispositionV1, ...],
    reviews: tuple[ReviewReceiptV1, ...],
    blockers: tuple[tuple[str, str], ...],
) -> StableModelDispositionIndependentProofV1:
    return verify_stable_model_disposition_inventory_independently(
        candidate_source_authority_sha256=source_sha256,
        candidate_canonical_bytes=tuple(_canonical(item.to_dict()) for item in candidates),
        disposition_canonical_bytes=tuple(_canonical(item.to_dict()) for item in dispositions),
        review_receipt_canonical_bytes=tuple(item.canonical_bytes for item in reviews),
        observed_inventory_canonical_bytes=_independent_inventory_bytes(
            source_sha256=source_sha256,
            candidates=candidates,
            dispositions=dispositions,
            reviews=reviews,
            blockers=blockers,
        ),
    )


def test_independent_verifier_reconstructs_green_inventory_and_proof_round_trip() -> None:
    source_sha256, candidates, dispositions, reviews = _inputs()

    proof = _verify(source_sha256, candidates, dispositions, reviews)

    assert proof.verified is True
    assert proof.release_gate_green is True
    assert proof.candidate_count == 3
    assert proof.disposition_count == 3
    assert proof.review_receipt_count == 3
    assert proof.blocker_count == 0
    observed = compile_stable_model_disposition_inventory(
        candidate_source_authority_sha256=source_sha256,
        candidates=candidates,
        dispositions=dispositions,
        review_receipts=reviews,
    ).canonical_bytes
    assert (
        StableModelDispositionIndependentProofV1.from_canonical_bytes(
            proof.canonical_bytes,
            observed_inventory_canonical_bytes=observed,
        )
        == proof
    )


def test_independent_verifier_reconstructs_red_missing_review_blocker() -> None:
    source_sha256, candidates, dispositions, reviews = _inputs()
    inventory = compile_stable_model_disposition_inventory(
        candidate_source_authority_sha256=source_sha256,
        candidates=candidates,
        dispositions=dispositions,
        review_receipts=reviews[1:],
    )

    proof = verify_stable_model_disposition_inventory_independently(
        candidate_source_authority_sha256=source_sha256,
        candidate_canonical_bytes=tuple(_canonical(item.to_dict()) for item in candidates),
        disposition_canonical_bytes=tuple(_canonical(item.to_dict()) for item in dispositions),
        review_receipt_canonical_bytes=tuple(item.canonical_bytes for item in reviews[1:]),
        observed_inventory_canonical_bytes=inventory.canonical_bytes,
    )

    assert proof.release_gate_green is False
    assert proof.blocker_count == 1


def test_independent_verifier_rejects_resealed_observed_false_green() -> None:
    source_sha256, candidates, dispositions, reviews = _inputs()
    inventory = compile_stable_model_disposition_inventory(
        candidate_source_authority_sha256=source_sha256,
        candidates=candidates,
        dispositions=dispositions,
        review_receipts=reviews[1:],
    )
    payload = inventory.to_dict()
    payload["blockers"] = []
    payload["release_gate_green"] = True
    content = {key: value for key, value in payload.items() if key != "inventory_sha256"}
    payload["inventory_sha256"] = __import__("hashlib").sha256(_canonical(content)).hexdigest()

    with pytest.raises(
        IndependentStableModelDispositionError,
        match="differs from independent reconstruction",
    ):
        _verify(
            source_sha256,
            candidates,
            dispositions,
            reviews[1:],
            observed=_canonical(payload),
        )


def test_independent_verifier_rejects_rebound_review_and_source_authority() -> None:
    source_sha256, candidates, dispositions, reviews = _inputs()
    observed = compile_stable_model_disposition_inventory(
        candidate_source_authority_sha256=source_sha256,
        candidates=candidates,
        dispositions=dispositions,
        review_receipts=reviews,
    ).canonical_bytes

    with pytest.raises(
        IndependentStableModelDispositionError,
        match="rebound to foreign evidence",
    ):
        verify_stable_model_disposition_inventory_independently(
            candidate_source_authority_sha256="9" * 64,
            candidate_canonical_bytes=tuple(_canonical(item.to_dict()) for item in candidates),
            disposition_canonical_bytes=tuple(_canonical(item.to_dict()) for item in dispositions),
            review_receipt_canonical_bytes=tuple(item.canonical_bytes for item in reviews),
            observed_inventory_canonical_bytes=observed,
        )

    rebound = replace(dispositions[0], review_receipt_sha256=reviews[1].receipt_sha256)
    with pytest.raises(
        IndependentStableModelDispositionError,
        match="foreign receipts|rebound to foreign evidence",
    ):
        verify_stable_model_disposition_inventory_independently(
            candidate_source_authority_sha256=source_sha256,
            candidate_canonical_bytes=tuple(_canonical(item.to_dict()) for item in candidates),
            disposition_canonical_bytes=tuple(
                _canonical(item.to_dict()) for item in (rebound, *dispositions[1:])
            ),
            review_receipt_canonical_bytes=tuple(item.canonical_bytes for item in reviews),
            observed_inventory_canonical_bytes=observed,
        )


def test_independent_verifier_rejects_noncanonical_duplicate_and_bool_confusion() -> None:
    source_sha256, candidates, dispositions, reviews = _inputs()
    candidate = _canonical(candidates[0].to_dict())
    duplicate = candidate.replace(b'{"candidate_id"', b'{"candidate_id":"x","candidate_id"', 1)
    inventory = compile_stable_model_disposition_inventory(
        candidate_source_authority_sha256=source_sha256,
        candidates=candidates,
        dispositions=dispositions,
        review_receipts=reviews,
    )
    with pytest.raises(IndependentStableModelDispositionError, match="duplicate JSON key"):
        verify_stable_model_disposition_inventory_independently(
            candidate_source_authority_sha256=source_sha256,
            candidate_canonical_bytes=(
                duplicate,
                *tuple(_canonical(item.to_dict()) for item in candidates[1:]),
            ),
            disposition_canonical_bytes=tuple(_canonical(item.to_dict()) for item in dispositions),
            review_receipt_canonical_bytes=tuple(item.canonical_bytes for item in reviews),
            observed_inventory_canonical_bytes=inventory.canonical_bytes,
        )

    proof = _verify(source_sha256, candidates, dispositions, reviews)
    proof_payload = proof.to_dict()
    proof_payload["candidate_count"] = True
    with pytest.raises(IndependentStableModelDispositionError, match="type is invalid"):
        StableModelDispositionIndependentProofV1.from_dict(
            proof_payload,
            observed_inventory_canonical_bytes=inventory.canonical_bytes,
        )


def test_proof_from_dict_requires_observed_binding_and_exact_kind_type() -> None:
    source_sha256, candidates, dispositions, reviews = _inputs()
    observed = compile_stable_model_disposition_inventory(
        candidate_source_authority_sha256=source_sha256,
        candidates=candidates,
        dispositions=dispositions,
        review_receipts=reviews,
    ).canonical_bytes
    proof = _verify(source_sha256, candidates, dispositions, reviews)

    class EqualKind:
        def __eq__(self, other: object) -> bool:
            return other == proof.kind

    payload = proof.to_dict()
    payload["kind"] = EqualKind()
    with pytest.raises(IndependentStableModelDispositionError, match="proof kind is invalid"):
        StableModelDispositionIndependentProofV1.from_dict(
            payload,
            observed_inventory_canonical_bytes=observed,
        )


def test_oversized_json_integer_uses_typed_fail_closed_error() -> None:
    source_sha256, candidates, dispositions, reviews = _inputs()
    observed = compile_stable_model_disposition_inventory(
        candidate_source_authority_sha256=source_sha256,
        candidates=candidates,
        dispositions=dispositions,
        review_receipts=reviews,
    ).canonical_bytes
    oversized = observed.replace(b'"schema_version":1', b'"schema_version":' + b"9" * 5_000, 1)

    with pytest.raises(
        IndependentStableModelDispositionError,
        match="oversized JSON integer",
    ):
        verify_stable_model_disposition_inventory_independently(
            candidate_source_authority_sha256=source_sha256,
            candidate_canonical_bytes=tuple(_canonical(item.to_dict()) for item in candidates),
            disposition_canonical_bytes=tuple(_canonical(item.to_dict()) for item in dispositions),
            review_receipt_canonical_bytes=tuple(item.canonical_bytes for item in reviews),
            observed_inventory_canonical_bytes=oversized,
        )


def test_independent_verifier_rejects_graph_and_candidate_type_mutations() -> None:
    source_sha256, candidates, dispositions, reviews = _inputs()
    candidate_payload = candidates[0].to_dict()
    candidate_payload["implementation_sha256"] = None
    with pytest.raises(
        IndependentStableModelDispositionError,
        match="implementation status and digest disagree",
    ):
        verify_stable_model_disposition_inventory_independently(
            candidate_source_authority_sha256=source_sha256,
            candidate_canonical_bytes=(
                _canonical(candidate_payload),
                *tuple(_canonical(item.to_dict()) for item in candidates[1:]),
            ),
            disposition_canonical_bytes=tuple(_canonical(item.to_dict()) for item in dispositions),
            review_receipt_canonical_bytes=tuple(item.canonical_bytes for item in reviews),
            observed_inventory_canonical_bytes=compile_stable_model_disposition_inventory(
                candidate_source_authority_sha256=source_sha256,
                candidates=candidates,
                dispositions=dispositions,
                review_receipts=reviews,
            ).canonical_bytes,
        )


def test_observed_nested_bool_type_confusion_is_rejected_byte_exactly() -> None:
    source_sha256, candidates, dispositions, reviews = _inputs()
    inventory = compile_stable_model_disposition_inventory(
        candidate_source_authority_sha256=source_sha256,
        candidates=candidates,
        dispositions=dispositions,
        review_receipts=reviews,
    )
    for mutate in ("review_schema", "validation_passed"):
        payload = inventory.to_dict()
        review = payload["review_receipts"][0]  # type: ignore[index]
        if mutate == "review_schema":
            review["schema_version"] = True  # type: ignore[index]
        else:
            review["validation_receipts"][0]["passed"] = 1  # type: ignore[index]
        with pytest.raises(
            IndependentStableModelDispositionError,
            match="differs from independent reconstruction",
        ):
            verify_stable_model_disposition_inventory_independently(
                candidate_source_authority_sha256=source_sha256,
                candidate_canonical_bytes=tuple(_canonical(item.to_dict()) for item in candidates),
                disposition_canonical_bytes=tuple(
                    _canonical(item.to_dict()) for item in dispositions
                ),
                review_receipt_canonical_bytes=tuple(item.canonical_bytes for item in reviews),
                observed_inventory_canonical_bytes=_canonical(payload),
            )


def test_resealed_red_proof_cannot_round_trip_as_green() -> None:
    source_sha256, candidates, dispositions, reviews = _inputs()
    observed = compile_stable_model_disposition_inventory(
        candidate_source_authority_sha256=source_sha256,
        candidates=candidates,
        dispositions=dispositions,
        review_receipts=reviews[1:],
    ).canonical_bytes
    proof = verify_stable_model_disposition_inventory_independently(
        candidate_source_authority_sha256=source_sha256,
        candidate_canonical_bytes=tuple(_canonical(item.to_dict()) for item in candidates),
        disposition_canonical_bytes=tuple(_canonical(item.to_dict()) for item in dispositions),
        review_receipt_canonical_bytes=tuple(item.canonical_bytes for item in reviews[1:]),
        observed_inventory_canonical_bytes=observed,
    )
    object.__setattr__(proof, "blocker_count", 0)
    object.__setattr__(proof, "release_gate_green", True)

    for deserialize in (
        lambda: StableModelDispositionIndependentProofV1.from_dict(
            proof.to_dict(),
            observed_inventory_canonical_bytes=observed,
        ),
        lambda: StableModelDispositionIndependentProofV1.from_canonical_bytes(
            proof.canonical_bytes,
            observed_inventory_canonical_bytes=observed,
        ),
    ):
        with pytest.raises(
            IndependentStableModelDispositionError,
            match="summary differs from its observed inventory",
        ):
            deserialize()


def test_aggregate_budget_includes_observed_inventory_bytes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source_sha256, candidates, dispositions, reviews = _inputs()
    observed = compile_stable_model_disposition_inventory(
        candidate_source_authority_sha256=source_sha256,
        candidates=candidates,
        dispositions=dispositions,
        review_receipts=reviews,
    ).canonical_bytes
    candidate_bytes = tuple(_canonical(item.to_dict()) for item in candidates)
    disposition_bytes = tuple(_canonical(item.to_dict()) for item in dispositions)
    review_bytes = tuple(item.canonical_bytes for item in reviews)
    row_total = sum(
        len(raw) for values in (candidate_bytes, disposition_bytes, review_bytes) for raw in values
    )
    monkeypatch.setattr(
        verifier_module,
        "_MAX_AGGREGATE_INPUT_BYTES",
        row_total + len(observed) - 1,
    )

    with pytest.raises(
        IndependentStableModelDispositionError,
        match="aggregate byte budget",
    ):
        verify_stable_model_disposition_inventory_independently(
            candidate_source_authority_sha256=source_sha256,
            candidate_canonical_bytes=candidate_bytes,
            disposition_canonical_bytes=disposition_bytes,
            review_receipt_canonical_bytes=review_bytes,
            observed_inventory_canonical_bytes=observed,
        )


def test_long_acyclic_graph_uses_bounded_iterative_validation() -> None:
    candidates = tuple(
        _candidate(
            f"fact.chain.{index:04d}",
            dependencies=((f"fact.chain.{index + 1:04d}",) if index < 1199 else ()),
        )
        for index in range(1200)
    )
    with pytest.raises(
        IndependentStableModelDispositionError,
        match="observed disposition inventory",
    ):
        verify_stable_model_disposition_inventory_independently(
            candidate_source_authority_sha256="f" * 64,
            candidate_canonical_bytes=tuple(_canonical(item.to_dict()) for item in candidates),
            disposition_canonical_bytes=(),
            review_receipt_canonical_bytes=(),
            observed_inventory_canonical_bytes=b"{}",
        )


@pytest.mark.parametrize(
    ("candidate_payloads", "message"),
    [
        (
            (
                {
                    **_candidate("fact.unknown").to_dict(),
                    "dependency_ids": ["source.missing"],
                },
            ),
            "unknown dependencies",
        ),
        (
            (
                {
                    **_candidate("fact.first").to_dict(),
                    "dependency_ids": ["fact.second"],
                },
                {
                    **_candidate("fact.second").to_dict(),
                    "dependency_ids": ["fact.first"],
                },
            ),
            "contains a cycle",
        ),
        (
            (
                {
                    **_candidate("source.base", kind="source").to_dict(),
                    "dependency_ids": ["fact.output"],
                },
                _candidate("fact.output").to_dict(),
            ),
            "dependency leaves",
        ),
        (
            (
                {
                    **_candidate("staging.output", kind="staging").to_dict(),
                    "dependency_ids": ["fact.output"],
                },
                _candidate("fact.output").to_dict(),
            ),
            "dependency-layer inversions",
        ),
    ],
)
def test_graph_failures_are_typed_and_fail_closed(
    candidate_payloads: tuple[dict[str, object], ...],
    message: str,
) -> None:
    with pytest.raises(IndependentStableModelDispositionError, match=message):
        verify_stable_model_disposition_inventory_independently(
            candidate_source_authority_sha256="f" * 64,
            candidate_canonical_bytes=tuple(_canonical(item) for item in candidate_payloads),
            disposition_canonical_bytes=(),
            review_receipt_canonical_bytes=(),
            observed_inventory_canonical_bytes=b"{}",
        )


def test_blocker_partition_is_independently_reconstructed_without_primary_compiler() -> None:
    source_sha256 = "f" * 64
    candidate = _candidate("fact.output", implemented=False)
    decision, review = _reviewed(
        candidate,
        source_sha256=source_sha256,
        disposition="stable",
    )
    expected = _independent_inventory_bytes(
        source_sha256=source_sha256,
        candidates=(candidate,),
        dispositions=(decision,),
        reviews=(review,),
        blockers=((candidate.candidate_id, "stable_implementation_missing"),),
    )
    proof = verify_stable_model_disposition_inventory_independently(
        candidate_source_authority_sha256=source_sha256,
        candidate_canonical_bytes=(_canonical(candidate.to_dict()),),
        disposition_canonical_bytes=(_canonical(decision.to_dict()),),
        review_receipt_canonical_bytes=(review.canonical_bytes,),
        observed_inventory_canonical_bytes=expected,
    )
    assert proof.blocker_count == 1
    assert proof.release_gate_green is False

    missing = _independent_inventory_bytes(
        source_sha256=source_sha256,
        candidates=(candidate,),
        dispositions=(),
        reviews=(),
        blockers=((candidate.candidate_id, "candidate_disposition_missing"),),
    )
    missing_proof = verify_stable_model_disposition_inventory_independently(
        candidate_source_authority_sha256=source_sha256,
        candidate_canonical_bytes=(_canonical(candidate.to_dict()),),
        disposition_canonical_bytes=(),
        review_receipt_canonical_bytes=(),
        observed_inventory_canonical_bytes=missing,
    )
    assert missing_proof.blocker_count == 1


def test_changes_required_review_blocker_is_reconstructed_directly() -> None:
    source_sha256 = "f" * 64
    candidate = _candidate("fact.output")
    decision, accepted_review = _reviewed(
        candidate,
        source_sha256=source_sha256,
        disposition="stable",
    )
    validations = tuple(
        replace(item, passed=False) if item.validation_class == "negative" else item
        for item in accepted_review.validation_receipts
    )
    changes_required = replace(
        accepted_review,
        disposition="changes_required",
        validation_receipts=validations,
    )
    decision = replace(decision, review_receipt_sha256=changes_required.receipt_sha256)

    proof = _verify_independent_rows(
        source_sha256=source_sha256,
        candidates=(candidate,),
        dispositions=(decision,),
        reviews=(changes_required,),
        blockers=((candidate.candidate_id, "independent_review_changes_required"),),
    )
    assert proof.blocker_count == 1


@pytest.mark.parametrize(
    ("kind", "implemented", "disposition", "expected_codes"),
    [
        ("fact", True, "withheld", ("required_candidate_not_stable",)),
        (
            "experimental_model",
            True,
            "stable",
            ("experimental_candidate_promoted_without_kind_change",),
        ),
        (
            "fact",
            True,
            "experimental",
            (
                "required_candidate_not_stable",
                "stable_surface_deferred_as_experimental",
            ),
        ),
    ],
)
def test_gate_and_disposition_blockers_are_reconstructed_directly(
    kind: str,
    implemented: bool,
    disposition: str,
    expected_codes: tuple[str, ...],
) -> None:
    source_sha256 = "f" * 64
    candidate = _candidate("model.output", kind=kind, implemented=implemented)
    decision, review = _reviewed(
        candidate,
        source_sha256=source_sha256,
        disposition=disposition,
    )

    proof = _verify_independent_rows(
        source_sha256=source_sha256,
        candidates=(candidate,),
        dispositions=(decision,),
        reviews=(review,),
        blockers=tuple((candidate.candidate_id, code) for code in expected_codes),
    )
    assert proof.blocker_count == len(expected_codes)


@pytest.mark.parametrize("dependency_has_disposition", [False, True])
def test_both_nonstable_dependency_forms_are_reconstructed_directly(
    dependency_has_disposition: bool,
) -> None:
    source_sha256 = "f" * 64
    dependency = _candidate("source.base", kind="source")
    dependent = _candidate("fact.output", dependencies=(dependency.candidate_id,))
    dependent_decision, dependent_review = _reviewed(
        dependent,
        source_sha256=source_sha256,
        disposition="stable",
    )
    decisions = [dependent_decision]
    reviews = [dependent_review]
    blockers = [
        (dependent.candidate_id, f"nonstable_dependency:{dependency.candidate_id}"),
    ]
    if dependency_has_disposition:
        dependency_decision, dependency_review = _reviewed(
            dependency,
            source_sha256=source_sha256,
            disposition="withheld",
        )
        decisions.append(dependency_decision)
        reviews.append(dependency_review)
        blockers.append((dependency.candidate_id, "required_candidate_not_stable"))
    else:
        blockers.append((dependency.candidate_id, "candidate_disposition_missing"))

    proof = _verify_independent_rows(
        source_sha256=source_sha256,
        candidates=(dependency, dependent),
        dispositions=tuple(decisions),
        reviews=tuple(reviews),
        blockers=tuple(blockers),
    )
    assert proof.blocker_count == 2


@pytest.mark.parametrize(
    ("field", "message"),
    [
        ("candidate_structural_sha256", "disposition structural authority drifted"),
        ("candidate_sha256", "disposition candidate authority drifted"),
    ],
)
def test_disposition_authority_digest_mismatches_fail_closed(
    field: str,
    message: str,
) -> None:
    source_sha256 = "f" * 64
    candidate = _candidate("fact.output")
    decision, _review = _reviewed(
        candidate,
        source_sha256=source_sha256,
        disposition="stable",
    )
    decision = replace(decision, **{field: "9" * 64})

    with pytest.raises(IndependentStableModelDispositionError, match=message):
        verify_stable_model_disposition_inventory_independently(
            candidate_source_authority_sha256=source_sha256,
            candidate_canonical_bytes=(_canonical(candidate.to_dict()),),
            disposition_canonical_bytes=(_canonical(decision.to_dict()),),
            review_receipt_canonical_bytes=(),
            observed_inventory_canonical_bytes=b"{}",
        )


@pytest.mark.parametrize(
    "rebind",
    [
        "subject_kind",
        "subject_semantic_sha256",
        "candidate_sha256",
        "candidate_structural_sha256",
        "candidate_source_authority_sha256",
    ],
)
def test_each_review_authority_join_rejects_rebinding(rebind: str) -> None:
    source_sha256 = "f" * 64
    candidate = _candidate("fact.output")
    decision, review = _reviewed(
        candidate,
        source_sha256=source_sha256,
        disposition="stable",
    )
    if rebind == "subject_kind":
        review = replace(review, subject_kind="foreign_subject")
    elif rebind == "subject_semantic_sha256":
        accepted = set(review.accepted_input_sha256s)
        accepted.remove(review.subject_semantic_sha256)
        accepted.add("9" * 64)
        review = replace(
            review,
            subject_semantic_sha256="9" * 64,
            accepted_input_sha256s=tuple(sorted(accepted)),
        )
    else:
        digest = {
            "candidate_sha256": candidate.candidate_sha256,
            "candidate_structural_sha256": candidate.structural_sha256,
            "candidate_source_authority_sha256": source_sha256,
        }[rebind]
        review = replace(
            review,
            accepted_input_sha256s=tuple(
                item for item in review.accepted_input_sha256s if item != digest
            ),
        )
    decision = replace(decision, review_receipt_sha256=review.receipt_sha256)

    with pytest.raises(
        IndependentStableModelDispositionError,
        match="review receipt is rebound to foreign evidence",
    ):
        verify_stable_model_disposition_inventory_independently(
            candidate_source_authority_sha256=source_sha256,
            candidate_canonical_bytes=(_canonical(candidate.to_dict()),),
            disposition_canonical_bytes=(_canonical(decision.to_dict()),),
            review_receipt_canonical_bytes=(review.canonical_bytes,),
            observed_inventory_canonical_bytes=b"{}",
        )
