from __future__ import annotations

import hashlib
import json
from copy import deepcopy
from dataclasses import replace
from typing import cast

import pytest

from nbadb.contracts import authority_semantic_diff as semantic_diff_module
from nbadb.contracts.authority_semantic_diff import (
    AffectedAuthorityScope,
    AuthorityChildIdentity,
    AuthoritySemanticAtom,
    AuthoritySemanticDiffError,
    AuthoritySemanticDiffV1,
    AuthoritySnapshot,
    ChangeClassification,
    DeltaBounds,
    build_authority_semantic_diff,
    verify_authority_semantic_diff_independently,
)
from nbadb.contracts.authority_semantic_diff_verifier import (
    VerifiedAuthoritySemanticDiffV1,
    build_verified_authority_semantic_diff,
)

_MANDATORY = ("field_temporal", "model_disposition", "request_closure")
_CHILD_SHA = "4" * 64
_DEFAULT = object()


def _sha256(value: object) -> str:
    return hashlib.sha256(
        json.dumps(
            value,
            allow_nan=False,
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        ).encode()
    ).hexdigest()


def _canonical_bytes(value: object) -> bytes:
    return json.dumps(
        value,
        allow_nan=False,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode()


def _scope(*, exact: bool = True) -> AffectedAuthorityScope:
    return AffectedAuthorityScope(
        scope_id="common_all_players:2025-26",
        scope_sha256="7" * 64,
        route_ids=("common_all_players:stg_common_all_players:0",),
        bound_values_sha256="8" * 64,
        exactly_enumerable=exact,
    )


def _root_atoms(child_ids: tuple[str, ...] = _MANDATORY) -> tuple[AuthoritySemanticAtom, ...]:
    return tuple(
        sorted(
            AuthoritySemanticAtom(
                atom_id=f"child:{child_id}",
                child_id=child_id,
                category="assurance_child",
                semantic_sha256=_CHILD_SHA,
                affected_scopes=(),
                addition_classification="breaking",
                mutation_classification="breaking",
                evidence_sha256="5" * 64,
            )
            for child_id in child_ids
        )
    )


def _atom(
    *,
    semantic_sha256: str = "a" * 64,
    addition: ChangeClassification = "additive",
    mutation: ChangeClassification = "bounded_compatible",
    exact: bool = True,
) -> AuthoritySemanticAtom:
    return AuthoritySemanticAtom(
        atom_id="field:common_all_players:new_field",
        child_id="field_temporal",
        category="field_occurrence",
        semantic_sha256=semantic_sha256,
        affected_scopes=(_scope(exact=exact),),
        addition_classification=addition,
        mutation_classification=mutation,
        evidence_sha256="b" * 64,
    )


def _snapshot(
    seed: str,
    *,
    complete: bool = True,
    semantic_atoms: tuple[AuthoritySemanticAtom, ...] | None = None,
) -> AuthoritySnapshot:
    child_ids = _MANDATORY if complete else _MANDATORY[:-1]
    authority_sha = seed * 64
    atoms = _root_atoms(child_ids) if semantic_atoms is None else tuple(sorted(semantic_atoms))
    children = tuple(
        AuthorityChildIdentity(
            child_id=child_id,
            child_sha256=_CHILD_SHA,
            parent_authority_sha256=authority_sha,
            semantic_atom_inventory_sha256=_sha256(
                [
                    item.to_dict()
                    for item in atoms
                    if item.child_id == child_id and item.atom_id != f"child:{child_id}"
                ]
            ),
            semantic_atom_count=sum(
                item.child_id == child_id and item.atom_id != f"child:{child_id}" for item in atoms
            ),
        )
        for child_id in child_ids
    )
    return AuthoritySnapshot(
        source_sha=seed * 40,
        authority_sha256=authority_sha,
        manifest_sha256=seed * 64,
        generation_semantic_sha256=seed * 64,
        mandatory_child_ids=_MANDATORY,
        children=children,
        semantic_atoms=atoms,
        complete=complete,
        independent_verifier_sha256="3" * 64,
    )


def _additive_transition() -> tuple[AuthoritySnapshot, AuthoritySnapshot]:
    roots = _root_atoms()
    return _snapshot("c", semantic_atoms=roots), _snapshot(
        "d", semantic_atoms=tuple(sorted((*roots, _atom())))
    )


def _mutation_transition(
    *,
    classification: ChangeClassification = "bounded_compatible",
    exact: bool = True,
) -> tuple[AuthoritySnapshot, AuthoritySnapshot]:
    before_atom = _atom(
        semantic_sha256="9" * 64,
        mutation=classification,
        exact=exact,
    )
    after_atom = replace(before_atom, semantic_sha256="a" * 64)
    roots = _root_atoms()
    return (
        _snapshot("c", semantic_atoms=tuple(sorted((*roots, before_atom)))),
        _snapshot("d", semantic_atoms=tuple(sorted((*roots, after_atom)))),
    )


def _build(
    *,
    previous: AuthoritySnapshot | None | object = _DEFAULT,
    current: AuthoritySnapshot | None = None,
    first: bool = False,
    preferred: str | None = "targeted_backfill",
    bounds: DeltaBounds | None = None,
) -> AuthoritySemanticDiffV1:
    default_previous, default_current = _additive_transition()
    previous_snapshot = cast(
        "AuthoritySnapshot | None", default_previous if previous is _DEFAULT else previous
    )
    current_snapshot = default_current if current is None else current
    return build_authority_semantic_diff(
        previous=previous_snapshot,
        current=current_snapshot,
        first_extraction=first,
        preferred_delta_mode=preferred,
        delta_bounds=(
            DeltaBounds(backfill_scope_ids=(_scope().scope_id,)) if bounds is None else bounds
        ),
    )


def test_exact_atom_addition_is_derived_but_forces_full_without_denominator_authority() -> None:
    receipt = _build()

    assert receipt.selected_mode == "full"
    assert receipt.decision_reason == "fine_atom_denominator_authority_missing"
    assert receipt.admission_allowed is True
    assert len(receipt.changes) == 1
    assert receipt.changes[0].change_id == "atom:field:common_all_players:new_field"
    assert receipt.changes[0].classification == "additive"
    assert AuthoritySemanticDiffV1.from_canonical_bytes(receipt.canonical_bytes) == receipt
    proof = verify_authority_semantic_diff_independently(receipt)
    assert proof.decision_receipt_sha256 == receipt.receipt_sha256
    assert proof.reconstructed_selected_mode == "full"
    envelope = build_verified_authority_semantic_diff(receipt)
    assert envelope.decision == receipt
    assert envelope.verification == proof
    assert (
        VerifiedAuthoritySemanticDiffV1.from_canonical_bytes(envelope.canonical_bytes) == envelope
    )


def test_first_extraction_cannot_be_overridden_with_delta() -> None:
    receipt = _build(first=True)

    assert receipt.selected_mode == "full"
    assert receipt.decision_reason == "first_extraction_requires_full"
    payload = receipt.to_dict()
    payload["selected_mode"] = "targeted_backfill"
    with pytest.raises(AuthoritySemanticDiffError, match="overridden"):
        AuthoritySemanticDiffV1.from_dict(payload)


def test_missing_or_incomplete_previous_authority_requires_full() -> None:
    missing = _build(previous=None, current=_snapshot("d"), preferred="since_last_observed")
    incomplete = _build(previous=_snapshot("c", complete=False))

    assert (missing.selected_mode, missing.decision_reason) == (
        "full",
        "previous_authority_missing",
    )
    assert (incomplete.selected_mode, incomplete.decision_reason) == (
        "full",
        "previous_authority_incomplete",
    )


def test_incomplete_current_blocks_and_primary_receipt_cannot_self_issue_verification() -> None:
    incomplete = _build(current=_snapshot("d", complete=False))

    assert incomplete.selected_mode == "blocked"
    assert incomplete.admission_allowed is False
    payload = _build().to_dict()
    payload["verification_status"] = "verified"
    with pytest.raises(AuthoritySemanticDiffError, match="fields differ"):
        AuthoritySemanticDiffV1.from_dict(payload)


@pytest.mark.parametrize(
    ("classification", "exact"),
    [("breaking", True), ("ambiguous", True), ("bounded_compatible", False)],
)
def test_breaking_ambiguous_or_unbounded_atom_mutation_requires_full(
    classification: ChangeClassification,
    exact: bool,
) -> None:
    previous, current = _mutation_transition(classification=classification, exact=exact)
    receipt = _build(previous=previous, current=current)

    assert receipt.selected_mode == "full"
    assert receipt.decision_reason == "breaking_ambiguous_or_unbounded_change"


def test_unchanged_authority_can_use_since_last_only_with_exact_watermark() -> None:
    unchanged = _snapshot("c")
    admitted = _build(
        previous=unchanged,
        current=unchanged,
        preferred="since_last_observed",
        bounds=DeltaBounds(since_watermark_sha256="f" * 64),
    )
    missing = _build(
        previous=unchanged,
        current=unchanged,
        preferred="since_last_observed",
        bounds=DeltaBounds(),
    )

    assert admitted.selected_mode == "since_last_observed"
    verified = build_verified_authority_semantic_diff(admitted)
    assert verified.verification.reconstructed_selected_mode == "since_last_observed"
    assert missing.selected_mode == "full"
    assert missing.decision_reason == "delta_bounds_incomplete"


def test_changed_snapshot_without_changed_atoms_fails_closed_to_full() -> None:
    previous = _snapshot("c")
    current = _snapshot("d")
    receipt = _build(
        previous=previous,
        current=current,
        preferred="since_last_observed",
        bounds=DeltaBounds(since_watermark_sha256="f" * 64),
    )

    assert receipt.changes == ()
    assert (receipt.selected_mode, receipt.decision_reason) == (
        "full",
        "semantic_change_inventory_missing",
    )


def test_recent_window_and_backfill_bounds_are_mode_specific() -> None:
    unchanged = _snapshot("c")
    recent = _build(
        previous=unchanged,
        current=unchanged,
        preferred="recent_window",
        bounds=DeltaBounds(
            recent_window_start="2026-08-01T00:00:00Z",
            recent_window_end="2026-08-26T00:00:00Z",
        ),
    )
    wrong_scope = _build(
        previous=unchanged,
        current=unchanged,
        bounds=DeltaBounds(backfill_scope_ids=("foreign:scope",)),
    )

    assert recent.selected_mode == "recent_window"
    assert wrong_scope.selected_mode == "full"


def test_snapshot_rejects_foreign_missing_or_rebound_atom_state() -> None:
    snapshot = _snapshot("c")
    with pytest.raises(AuthoritySemanticDiffError, match="foreign parent"):
        replace(
            snapshot,
            children=(replace(snapshot.children[0], parent_authority_sha256="0" * 64),),
            semantic_atoms=(),
            complete=False,
        )
    with pytest.raises(AuthoritySemanticDiffError, match="every mandatory child"):
        replace(snapshot, children=snapshot.children[:-1])
    with pytest.raises(AuthoritySemanticDiffError, match="root atom differs"):
        replace(
            snapshot,
            semantic_atoms=tuple(
                replace(item, semantic_sha256="0" * 64)
                if item.atom_id == "child:field_temporal"
                else item
                for item in snapshot.semantic_atoms
            ),
        )
    with pytest.raises(AuthoritySemanticDiffError, match="exact boolean"):
        AuthoritySnapshot.from_dict({**snapshot.to_dict(), "complete": 1})


def test_wire_decoder_rejects_noncanonical_duplicate_and_tampered_receipts() -> None:
    receipt = _build()
    with pytest.raises(AuthoritySemanticDiffError, match="not canonical"):
        AuthoritySemanticDiffV1.from_canonical_bytes(receipt.canonical_bytes + b"\n")
    with pytest.raises(AuthoritySemanticDiffError, match="duplicate JSON key"):
        AuthoritySemanticDiffV1.from_canonical_bytes(b'{"kind":"a","kind":"b"}')
    with pytest.raises(AuthoritySemanticDiffError, match="digest is invalid"):
        AuthoritySemanticDiffV1.from_dict({**receipt.to_dict(), "receipt_sha256": "0" * 64})


def test_caller_cannot_remove_or_rebind_a_derived_change() -> None:
    receipt = _build()
    with pytest.raises(AuthoritySemanticDiffError, match="exact semantic atom transition"):
        replace(receipt, changes=())
    forged = replace(receipt.changes[0], evidence_sha256="0" * 64)
    with pytest.raises(AuthoritySemanticDiffError, match="exact semantic atom transition"):
        replace(receipt, changes=(forged,))


def test_atom_policy_mutation_and_removal_are_conservatively_breaking() -> None:
    roots = _root_atoms()
    before_atom = _atom(semantic_sha256="9" * 64)
    policy_changed = replace(before_atom, evidence_sha256="0" * 64)
    previous = _snapshot("c", semantic_atoms=tuple(sorted((*roots, before_atom))))
    changed = _snapshot("d", semantic_atoms=tuple(sorted((*roots, policy_changed))))
    removed = _snapshot("d", semantic_atoms=roots)

    changed_receipt = _build(previous=previous, current=changed)
    removed_receipt = _build(previous=previous, current=removed)

    assert changed_receipt.changes[0].reason_code == "semantic_atom_policy_changed"
    assert changed_receipt.changes[0].classification == "breaking"
    assert removed_receipt.changes[0].reason_code == "semantic_atom_removed"
    assert removed_receipt.changes[0].classification == "breaking"
    assert changed_receipt.selected_mode == removed_receipt.selected_mode == "full"


def test_snapshot_atom_inventory_digest_is_exact() -> None:
    snapshot = _snapshot("c")
    payload = snapshot.to_dict()
    payload["semantic_atom_inventory_sha256"] = "0" * 64

    with pytest.raises(AuthoritySemanticDiffError, match="inventory digest is invalid"):
        AuthoritySnapshot.from_dict(payload)


def test_independent_verifier_rejects_primary_transition_common_mode(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    previous, current = _additive_transition()
    monkeypatch.setattr(
        semantic_diff_module,
        "_derive_authority_changes",
        lambda _previous, _current: (),
    )
    forged = build_authority_semantic_diff(
        previous=previous,
        current=current,
        first_extraction=False,
        preferred_delta_mode="since_last_observed",
        delta_bounds=DeltaBounds(since_watermark_sha256="f" * 64),
    )

    with pytest.raises(AuthoritySemanticDiffError, match="independent semantic atom transition"):
        verify_authority_semantic_diff_independently(forged)


def test_independent_verifier_rejects_primary_decision_common_mode(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    previous, current = _mutation_transition(classification="breaking")
    monkeypatch.setattr(
        semantic_diff_module,
        "_decision",
        lambda *_args, **_kwargs: ("targeted_backfill", "exact_bounded_delta"),
    )
    forged = build_authority_semantic_diff(
        previous=previous,
        current=current,
        first_extraction=False,
        preferred_delta_mode="targeted_backfill",
        delta_bounds=DeltaBounds(backfill_scope_ids=(_scope().scope_id,)),
    )

    with pytest.raises(AuthoritySemanticDiffError, match="independent semantic diff decision"):
        verify_authority_semantic_diff_independently(forged)


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("reconstructed_selected_mode", "targeted_backfill"),
        ("reconstructed_change_inventory_sha256", "2" * 64),
        ("verifier_source_sha256", "0" * 64),
        ("decision_wire_sha256", "1" * 64),
    ],
)
def test_resealed_forged_verification_proof_is_recomputed_and_rejected(
    field: str,
    value: str,
) -> None:
    envelope = build_verified_authority_semantic_diff(_build())
    payload = deepcopy(envelope.to_dict())
    verification = payload["verification"]
    assert isinstance(verification, dict)
    verification = cast("dict[str, object]", verification)
    verification[field] = value
    verification["proof_sha256"] = _sha256(
        {key: item for key, item in verification.items() if key != "proof_sha256"}
    )
    payload["envelope_sha256"] = _sha256(
        {key: item for key, item in payload.items() if key != "envelope_sha256"}
    )

    with pytest.raises(AuthoritySemanticDiffError, match="proof differs from reconstruction"):
        VerifiedAuthoritySemanticDiffV1.from_canonical_bytes(_canonical_bytes(payload))


def test_unresealed_mutated_verification_proof_is_rejected() -> None:
    envelope = build_verified_authority_semantic_diff(_build())
    payload = deepcopy(envelope.to_dict())
    verification = payload["verification"]
    assert isinstance(verification, dict)
    verification = cast("dict[str, object]", verification)
    verification["reconstructed_decision_reason"] = "forged_reason"

    with pytest.raises(AuthoritySemanticDiffError, match="proof digest is invalid"):
        VerifiedAuthoritySemanticDiffV1.from_canonical_bytes(_canonical_bytes(payload))


def test_proof_swapped_from_another_valid_decision_is_rejected_after_reseal() -> None:
    target = build_verified_authority_semantic_diff(_build())
    unchanged = _snapshot("c")
    donor = build_verified_authority_semantic_diff(
        _build(
            previous=unchanged,
            current=unchanged,
            preferred="since_last_observed",
            bounds=DeltaBounds(since_watermark_sha256="f" * 64),
        )
    )
    payload = deepcopy(target.to_dict())
    payload["verification"] = donor.verification.to_dict()
    payload["envelope_sha256"] = _sha256(
        {key: item for key, item in payload.items() if key != "envelope_sha256"}
    )

    with pytest.raises(AuthoritySemanticDiffError, match="proof differs from reconstruction"):
        VerifiedAuthoritySemanticDiffV1.from_canonical_bytes(_canonical_bytes(payload))


def test_valid_decision_swapped_under_stale_proof_is_rejected_after_reseal() -> None:
    original = build_verified_authority_semantic_diff(_build())
    unchanged = _snapshot("c")
    donor = build_verified_authority_semantic_diff(
        _build(
            previous=unchanged,
            current=unchanged,
            preferred="recent_window",
            bounds=DeltaBounds(
                recent_window_start="2026-08-01T00:00:00Z",
                recent_window_end="2026-08-31T00:00:00Z",
            ),
        )
    )
    payload = deepcopy(original.to_dict())
    payload["decision"] = donor.decision.to_dict()
    payload["envelope_sha256"] = _sha256(
        {key: item for key, item in payload.items() if key != "envelope_sha256"}
    )

    with pytest.raises(AuthoritySemanticDiffError, match="proof differs from reconstruction"):
        VerifiedAuthoritySemanticDiffV1.from_canonical_bytes(_canonical_bytes(payload))


@pytest.mark.parametrize("mutation", ["missing", "unknown"])
def test_verification_proof_rejects_missing_or_unknown_keys(mutation: str) -> None:
    envelope = build_verified_authority_semantic_diff(_build())
    payload = deepcopy(envelope.to_dict())
    verification = payload["verification"]
    assert isinstance(verification, dict)
    verification = cast("dict[str, object]", verification)
    if mutation == "missing":
        verification.pop("verification_status")
    else:
        verification["unknown"] = "forged"

    with pytest.raises(AuthoritySemanticDiffError, match="proof fields differ"):
        VerifiedAuthoritySemanticDiffV1.from_canonical_bytes(_canonical_bytes(payload))


def test_verified_envelope_rejects_noncanonical_and_duplicate_wire() -> None:
    envelope = build_verified_authority_semantic_diff(_build())
    with pytest.raises(AuthoritySemanticDiffError, match="not exact canonical"):
        VerifiedAuthoritySemanticDiffV1.from_canonical_bytes(envelope.canonical_bytes + b"\n")
    with pytest.raises(AuthoritySemanticDiffError, match="duplicate JSON key"):
        VerifiedAuthoritySemanticDiffV1.from_canonical_bytes(b'{"kind":"a","kind":"b"}')
