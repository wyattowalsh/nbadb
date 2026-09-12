from __future__ import annotations

import json
from dataclasses import FrozenInstanceError, replace

import pytest

from nbadb.contracts.review_evidence import (
    ReviewEvidenceError,
    ReviewFindingV1,
    ReviewReceiptV1,
    ReviewValidationReceiptV1,
)


def _validations(*, failed_class: str | None = None) -> tuple[ReviewValidationReceiptV1, ...]:
    return tuple(
        sorted(
            ReviewValidationReceiptV1(
                receipt_id=f"test:{validation_class}",
                validation_class=validation_class,  # ty: ignore[invalid-argument-type]
                command_sha256=character * 64,
                evidence_sha256=character.upper().lower() * 64,
                passed=validation_class != failed_class,
            )
            for validation_class, character in (
                ("positive", "a"),
                ("negative", "b"),
                ("mutation", "c"),
            )
        )
    )


def _receipt(
    *,
    disposition: str = "accepted",
    findings: tuple[ReviewFindingV1, ...] = (),
    validations: tuple[ReviewValidationReceiptV1, ...] | None = None,
) -> ReviewReceiptV1:
    subject = "d" * 64
    return ReviewReceiptV1(
        subject_kind="field.fragment",
        subject_semantic_sha256=subject,
        author_task_id="task:author",
        author_role="semantic-author",
        reviewer_task_id="task:reviewer",
        reviewer_role="independent-reviewer",
        independence_evidence_kind="independent_agent_review",
        independence_evidence_sha256="f" * 64,
        accepted_input_sha256s=(subject, "e" * 64),
        disposition=disposition,  # ty: ignore[invalid-argument-type]
        findings=findings,
        validation_receipts=validations or _validations(),
    )


def test_accepted_review_round_trips_canonical_digest_bound_evidence() -> None:
    receipt = _receipt(
        findings=(
            ReviewFindingV1(
                finding_id="finding:resolved",
                severity="major",
                status="resolved",
                evidence_sha256="f" * 64,
            ),
        )
    )

    encoded = receipt.canonical_bytes
    payload = json.loads(encoded)

    assert payload["receipt_sha256"] == receipt.receipt_sha256
    assert ReviewReceiptV1.from_dict(payload) == receipt
    assert ReviewReceiptV1.from_canonical_bytes(encoded) == receipt
    assert {item.validation_class for item in receipt.validation_receipts} == {
        "positive",
        "negative",
        "mutation",
    }
    with pytest.raises(FrozenInstanceError):
        receipt.author_task_id = "task:other"  # ty: ignore[invalid-assignment]


@pytest.mark.parametrize(
    ("field", "value", "match"),
    [
        ("reviewer_task_id", "task:author", "task identities must differ"),
        ("reviewer_role", "semantic-author", "roles must differ"),
        ("accepted_input_sha256s", ("e" * 64,), "exact subject semantic digest"),
        (
            "accepted_input_sha256s",
            ("e" * 64, "d" * 64),
            "sorted, and unique",
        ),
    ],
)
def test_review_rejects_self_review_and_invalid_input_partition(
    field: str,
    value: object,
    match: str,
) -> None:
    receipt = _receipt()

    with pytest.raises(ReviewEvidenceError, match=match):
        replace(receipt, **{field: value})


def test_accepted_review_rejects_open_findings_and_failed_validation() -> None:
    open_finding = ReviewFindingV1(
        finding_id="finding:open",
        severity="blocker",
        status="open",
        evidence_sha256="f" * 64,
    )
    with pytest.raises(ReviewEvidenceError, match="accepted review cannot"):
        _receipt(findings=(open_finding,))
    with pytest.raises(ReviewEvidenceError, match="accepted review cannot"):
        _receipt(validations=_validations(failed_class="mutation"))


def test_changes_required_requires_and_preserves_negative_evidence() -> None:
    validations = _validations(failed_class="negative")
    receipt = _receipt(disposition="changes_required", validations=validations)

    assert ReviewReceiptV1.from_canonical_bytes(receipt.canonical_bytes) == receipt
    assert any(not item.passed for item in receipt.validation_receipts)

    with pytest.raises(ReviewEvidenceError, match="must retain an open finding"):
        _receipt(disposition="changes_required")


def test_review_requires_each_validation_class_exactly_and_unique_ids() -> None:
    validations = _validations()
    with pytest.raises(ReviewEvidenceError, match="positive, negative, and mutation"):
        _receipt(validations=validations[:-1])

    duplicate = replace(validations[-1], receipt_id=validations[0].receipt_id)
    with pytest.raises(ReviewEvidenceError, match="unique identities"):
        _receipt(validations=tuple(sorted((*validations[:-1], duplicate))))


def test_canonical_parser_rejects_digest_mutation_duplicate_keys_and_whitespace() -> None:
    receipt = _receipt()
    payload = receipt.to_dict()
    payload["receipt_sha256"] = "0" * 64
    with pytest.raises(ReviewEvidenceError, match="digest is invalid"):
        ReviewReceiptV1.from_dict(payload)

    duplicate = receipt.canonical_bytes.replace(
        b'{"accepted_input_sha256s"',
        b'{"kind":"duplicate","accepted_input_sha256s"',
        1,
    )
    with pytest.raises(ReviewEvidenceError, match="duplicate JSON key: kind"):
        ReviewReceiptV1.from_canonical_bytes(duplicate)

    with pytest.raises(ReviewEvidenceError, match="not canonical"):
        ReviewReceiptV1.from_canonical_bytes(receipt.canonical_bytes + b"\n")


@pytest.mark.parametrize("member", ["subject_kind", "findings", "receipt_sha256"])
def test_review_rejects_missing_or_unknown_members(member: str) -> None:
    payload = _receipt().to_dict()
    del payload[member]
    with pytest.raises(ReviewEvidenceError, match="fields differ"):
        ReviewReceiptV1.from_dict(payload)

    payload = _receipt().to_dict()
    payload["reviewed"] = True
    with pytest.raises(ReviewEvidenceError, match="unexpected=reviewed"):
        ReviewReceiptV1.from_dict(payload)
